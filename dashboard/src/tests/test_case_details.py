"""Tests for the UIAPI-sourced case detail path (group + comments).

Comments are sourced from the top-level ``RedHatSupportCaseComment__c`` object
(not the empty ``RedHatSupportCase.CaseComments`` nested connection), so
``fetch_case_details_uiapi`` issues two kinds of GraphQL query: the case-detail
query (``RedHatSupportCase``) and the comment query
(``RedHatSupportCaseComment__c``). The ``graphql_post`` fakes below dispatch on
the query text to return the matching envelope.
"""

import json
from datetime import datetime

import pytest

from t5gweb import cache
from t5gweb.cache import (
    fetch_case_details_uiapi,
    get_case_details,
)
from t5gweb.utils import uiapi_comment_to_dict


def _detail_node(case_number, group_name=None):
    """Build a RedHatSupportCase edge node like the detail query returns."""
    return {
        "CaseNumber__c": {"value": case_number},
        "Group__r": {"Name": {"value": group_name}} if group_name else None,
    }


def _comment_node(
    case_number,
    body="body",
    author="Jane",
    created="2026-09-01T00:00:00.000Z",
    is_customer=False,
    is_associate=False,
    visibility="Public",
):
    """Build a RedHatSupportCaseComment__c node like the comment query returns."""
    return {
        "Case__r": {"CaseNumber__c": {"value": case_number}},
        "Body__c": {"value": body},
        "CreatedDate": {"value": created},
        "Visibility__c": {"value": visibility},
        "IsCustomer__c": {"value": is_customer},
        "IsAssociate__c": {"value": is_associate},
        "CreatedBy": {"Name": {"value": author}},
    }


def _detail_page(nodes, has_next=False, end_cursor=None):
    """Wrap RedHatSupportCase nodes in the GraphQL envelope."""
    return {
        "data": {
            "redhat_support_uiapi": {
                "query": {
                    "RedHatSupportCase": {
                        "pageInfo": {
                            "hasNextPage": has_next,
                            "endCursor": end_cursor,
                        },
                        "edges": [{"node": n} for n in nodes],
                    }
                }
            }
        }
    }


def _comments_page(nodes, has_next=False, end_cursor=None):
    """Wrap RedHatSupportCaseComment__c nodes in the GraphQL envelope."""
    return {
        "data": {
            "redhat_support_uiapi": {
                "query": {
                    "RedHatSupportCaseComment__c": {
                        "pageInfo": {
                            "hasNextPage": has_next,
                            "endCursor": end_cursor,
                        },
                        "edges": [{"node": n} for n in nodes],
                    }
                }
            }
        }
    }


def _is_comment_query(query):
    return "RedHatSupportCaseComment__c" in query


class TestUiapiCommentToDict:
    def test_customer_comment(self):
        node = _comment_node(
            "1",
            body="hello",
            author="Jane Doe",
            created="2026-09-01T00:00:00.000Z",
            is_customer=True,
        )
        assert uiapi_comment_to_dict(node) == {
            "commentBody": "hello",
            "createdBy": "Jane Doe",
            "createdByType": "Customer",
            "isPublic": True,
            "createdDate": "2026-09-01T00:00:00.000Z",
        }

    def test_is_public_from_visibility(self):
        assert uiapi_comment_to_dict(_comment_node("1"))["isPublic"] is True
        assert (
            uiapi_comment_to_dict(_comment_node("1", visibility="Private"))["isPublic"]
            is False
        )

    def test_is_public_unknown_when_visibility_absent(self):
        # Null/missing visibility means "the API told us nothing": report None
        # so it is stored as NULL (rendered public) rather than badging the
        # whole history private on a guess.
        node = _comment_node("1")
        node["Visibility__c"] = None
        assert uiapi_comment_to_dict(node)["isPublic"] is None

        del node["Visibility__c"]
        assert uiapi_comment_to_dict(node)["isPublic"] is None

    def test_body_html_converted_to_markdown(self):
        # Body__c is entity-escaped HTML; it is unescaped then converted to MD.
        node = _comment_node(
            "1", body="&lt;p&gt;Hi &lt;strong&gt;there&lt;/strong&gt;&lt;/p&gt;"
        )
        assert uiapi_comment_to_dict(node)["commentBody"] == "Hi **there**"

    def test_associate_comment_type(self):
        node = _comment_node("1", is_associate=True)
        assert uiapi_comment_to_dict(node)["createdByType"] == "Associate"

    def test_internal_comment_type(self):
        node = _comment_node("1")  # neither customer nor associate
        assert uiapi_comment_to_dict(node)["createdByType"] == "Internal"

    def test_missing_author_defaults_to_unknown(self):
        node = {
            "Body__c": {"value": "body"},
            "CreatedDate": {"value": "2026-09-01T00:00:00.000Z"},
            "CreatedBy": None,
        }
        assert uiapi_comment_to_dict(node)["createdBy"] == "unknown"

    def test_missing_body_defaults_to_empty_string(self):
        node = {
            "Body__c": None,
            "CreatedDate": {"value": "2026-09-01T00:00:00.000Z"},
            "CreatedBy": {"Name": {"value": "Jane"}},
        }
        assert uiapi_comment_to_dict(node)["commentBody"] == ""

    def test_missing_created_date_is_none(self):
        node = {
            "Body__c": {"value": "body"},
            "CreatedDate": None,
            "CreatedBy": {"Name": {"value": "Jane"}},
        }
        assert uiapi_comment_to_dict(node)["createdDate"] is None


class TestFetchCaseDetailsUiapi:
    def test_maps_group_and_comments(self, monkeypatch):
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})

        def fake_post(url, headers, query, variables):
            if _is_comment_query(query):
                return _comments_page(
                    [
                        _comment_node(
                            "12345678",
                            body="first",
                            author="Jane",
                            created="2026-09-01T00:00:00.000Z",
                            is_customer=True,
                        )
                    ]
                )
            return _detail_page([_detail_node("12345678", group_name="Telco 5G")])

        monkeypatch.setattr(cache, "graphql_post", fake_post)

        result = fetch_case_details_uiapi(
            {"graphql_api": "u", "offline_token": "t"}, "tok", ["12345678"]
        )

        assert result == {
            "12345678": {
                "group_name": "Telco 5G",
                "comments": [
                    {
                        "commentBody": "first",
                        "createdBy": "Jane",
                        "createdByType": "Customer",
                        "isPublic": True,
                        "createdDate": "2026-09-01T00:00:00.000Z",
                    }
                ],
            }
        }

    def test_missing_group_and_no_comments(self, monkeypatch):
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})

        def fake_post(url, headers, query, variables):
            if _is_comment_query(query):
                return _comments_page([])
            return _detail_page([_detail_node("12345678", group_name=None)])

        monkeypatch.setattr(cache, "graphql_post", fake_post)

        result = fetch_case_details_uiapi(
            {"graphql_api": "u", "offline_token": "t"}, "tok", ["12345678"]
        )
        assert result["12345678"]["group_name"] is None
        assert result["12345678"]["comments"] == []

    def test_chunks_detail_by_case_detail_chunk_size(self, monkeypatch):
        monkeypatch.setattr(cache, "_CASE_DETAIL_CHUNK_SIZE", 2)
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})

        detail_wheres = []

        def fake_post(url, headers, query, variables):
            if _is_comment_query(query):
                return _comments_page([])
            cns = variables["where"]["CaseNumber__c"]["in"]
            detail_wheres.append(cns)
            return _detail_page([_detail_node(cn) for cn in cns])

        monkeypatch.setattr(cache, "graphql_post", fake_post)

        result = fetch_case_details_uiapi(
            {"graphql_api": "u", "offline_token": "t"}, "tok", ["1", "2", "3"]
        )

        assert detail_wheres == [["1", "2"], ["3"]]
        assert set(result) == {"1", "2", "3"}

    def test_paginates_detail_within_chunk(self, monkeypatch):
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        detail_pages = [
            _detail_page([_detail_node("1")], has_next=True, end_cursor="CURSOR"),
            _detail_page([_detail_node("2")], has_next=False),
        ]
        detail_afters = []

        def fake_post(url, headers, query, variables):
            if _is_comment_query(query):
                return _comments_page([])
            detail_afters.append(variables["after"])
            return detail_pages[len(detail_afters) - 1]

        monkeypatch.setattr(cache, "graphql_post", fake_post)

        result = fetch_case_details_uiapi(
            {"graphql_api": "u", "offline_token": "t"}, "tok", ["1", "2"]
        )

        assert detail_afters == [None, "CURSOR"]
        assert set(result) == {"1", "2"}

    def test_reauth_and_retry_on_failure(self, monkeypatch):
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(cache.libtelco5g, "get_token", lambda token: "fresh-token")
        state = {"detail_calls": 0}

        def fake_post(url, headers, query, variables):
            if _is_comment_query(query):
                return _comments_page([])
            state["detail_calls"] += 1
            if state["detail_calls"] == 1:
                raise RuntimeError("GraphQL error: 403")
            return _detail_page([_detail_node("1", group_name="G")])

        monkeypatch.setattr(cache, "graphql_post", fake_post)

        result = fetch_case_details_uiapi(
            {"graphql_api": "u", "offline_token": "t"}, "tok", ["1"]
        )
        assert result["1"]["group_name"] == "G"
        assert state["detail_calls"] == 2

    def test_detail_chunk_skipped_when_retry_also_fails(self, monkeypatch):
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(cache.libtelco5g, "get_token", lambda token: "fresh")

        def fake_post(url, headers, query, variables):
            if _is_comment_query(query):
                return _comments_page([])
            raise RuntimeError("GraphQL error: 403")

        monkeypatch.setattr(cache, "graphql_post", fake_post)

        result = fetch_case_details_uiapi(
            {"graphql_api": "u", "offline_token": "t"}, "tok", ["1"]
        )
        assert result == {}

    def test_comments_merge_onto_matching_case(self, monkeypatch):
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})

        def fake_post(url, headers, query, variables):
            if _is_comment_query(query):
                return _comments_page(
                    [
                        _comment_node("1", body="c1", is_customer=True),
                        _comment_node("2", body="c2", is_associate=True),
                    ]
                )
            cns = variables["where"]["CaseNumber__c"]["in"]
            return _detail_page([_detail_node(cn, group_name="G") for cn in cns])

        monkeypatch.setattr(cache, "graphql_post", fake_post)

        result = fetch_case_details_uiapi(
            {"graphql_api": "u", "offline_token": "t"}, "tok", ["1", "2"]
        )
        assert [c["commentBody"] for c in result["1"]["comments"]] == ["c1"]
        assert result["1"]["comments"][0]["createdByType"] == "Customer"
        assert [c["commentBody"] for c in result["2"]["comments"]] == ["c2"]
        assert result["2"]["comments"][0]["createdByType"] == "Associate"


class TestCommentFetchIsIncremental:
    """Stored comments are not re-read on every sync."""

    @staticmethod
    def _collect(monkeypatch, watermarks, fail_on_floor=False):
        """Run a detail fetch for cases 1 and 2, returning the comment wheres."""
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(cache.libtelco5g, "get_token", lambda token: "fresh")
        monkeypatch.setattr(
            cache, "comment_watermarks_postgres", lambda cases: watermarks
        )
        comment_wheres = []

        def fake_post(url, headers, query, variables):
            if not _is_comment_query(query):
                cns = variables["where"]["CaseNumber__c"]["in"]
                return _detail_page([_detail_node(cn) for cn in cns])
            where = variables["where"]
            comment_wheres.append(where)
            if fail_on_floor and "and" in where:
                raise RuntimeError("GraphQL error: unknown filter CreatedDate")
            return _comments_page([_comment_node("1", body="c1")])

        monkeypatch.setattr(cache, "graphql_post", fake_post)
        fetch_case_details_uiapi(
            {"graphql_api": "u", "offline_token": "t"}, "tok", ["1", "2"]
        )
        return comment_wheres

    def test_no_stored_comments_fetches_full_history(self, monkeypatch):
        wheres = self._collect(monkeypatch, {})

        assert wheres == [{"Case__r": {"CaseNumber__c": {"in": ["1", "2"]}}}]

    def test_stored_comments_floor_the_query(self, monkeypatch):
        wheres = self._collect(
            monkeypatch,
            {
                "1": datetime(2026, 9, 10, 8, 0, 0),
                "2": datetime(2026, 9, 12, 8, 0, 0),
            },
        )

        # Both cases are known, so a single swept chunk floored at the oldest
        # of the two watermarks - never re-reading what is already stored.
        # gte takes a RedHatSupportDateTimeInput ({"value": <ISO Z>}); a bare
        # string is rejected with VALIDATION_INVALID_TYPE_VARIABLE.
        assert wheres == [
            {
                "and": [
                    {"Case__r": {"CaseNumber__c": {"in": ["1", "2"]}}},
                    {"CreatedDate": {"gte": {"value": "2026-09-10T08:00:00Z"}}},
                ]
            }
        ]

    def test_case_without_stored_comments_still_swept_in_full(self, monkeypatch):
        wheres = self._collect(monkeypatch, {"2": datetime(2026, 9, 12, 8, 0, 0)})

        # Case 1 has nothing stored: its history must not be floored by case
        # 2's watermark, or it would never be fetched at all.
        assert wheres[0] == {"Case__r": {"CaseNumber__c": {"in": ["1"]}}}
        assert wheres[1]["and"][0] == {"Case__r": {"CaseNumber__c": {"in": ["2"]}}}

    def test_throttling_does_not_disable_the_floor(self, monkeypatch):
        # A 403/WAF throttle must not be read as "the API refuses the floor":
        # dropping it would re-read every comment of every case while the API
        # is already pushing back. The chunk is skipped, the floor stays on.
        monkeypatch.setattr(cache, "_CASE_DETAIL_CHUNK_SIZE", 1)
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(cache.libtelco5g, "get_token", lambda token: "fresh")
        monkeypatch.setattr(
            cache,
            "comment_watermarks_postgres",
            lambda cases: {
                "1": datetime(2026, 9, 10, 8, 0, 0),
                "2": datetime(2026, 9, 10, 8, 0, 0),
            },
        )
        comment_wheres = []

        def fake_post(url, headers, query, variables):
            if not _is_comment_query(query):
                cns = variables["where"]["CaseNumber__c"]["in"]
                return _detail_page([_detail_node(cn) for cn in cns])
            comment_wheres.append(variables["where"])
            raise RuntimeError("GraphQL error: 403 Forbidden")

        monkeypatch.setattr(cache, "graphql_post", fake_post)
        fetch_case_details_uiapi(
            {"graphql_api": "u", "offline_token": "t"}, "tok", ["1", "2"]
        )

        # Two chunks, two attempts each (initial + token refresh), floored
        # throughout - never retried bare.
        assert len(comment_wheres) == 4
        assert all("and" in where for where in comment_wheres)

    def test_floor_retry_does_not_duplicate_collected_comments(self, monkeypatch):
        # The retry restarts the chunk at its first page, so comments read
        # before the rejection must not be kept as well.
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(cache.libtelco5g, "get_token", lambda token: "fresh")
        monkeypatch.setattr(
            cache,
            "comment_watermarks_postgres",
            lambda cases: {"1": datetime(2026, 9, 10, 8, 0, 0)},
        )

        def fake_post(url, headers, query, variables):
            if not _is_comment_query(query):
                return _detail_page([_detail_node("1")])
            if "and" in variables["where"]:
                if variables["after"] is None:
                    # First floored page succeeds...
                    return _comments_page(
                        [_comment_node("1", body="first page")],
                        has_next=True,
                        end_cursor="cursor-1",
                    )
                # ...the second is refused, so the chunk restarts unfloored.
                raise RuntimeError(
                    "GraphQL error: invalid input value at `$where.and[1]."
                    "CreatedDate.gte`"
                )
            return _comments_page(
                [
                    _comment_node("1", body="first page"),
                    _comment_node("1", body="second page"),
                ]
            )

        monkeypatch.setattr(cache, "graphql_post", fake_post)
        result = fetch_case_details_uiapi(
            {"graphql_api": "u", "offline_token": "t"}, "tok", ["1"]
        )

        assert [c["commentBody"] for c in result["1"]["comments"]] == [
            "first page",
            "second page",
        ]

    def test_falls_back_to_unfiltered_when_floor_rejected(self, monkeypatch):
        wheres = self._collect(
            monkeypatch,
            {"1": datetime(2026, 9, 10, 8, 0, 0), "2": datetime(2026, 9, 10, 8, 0, 0)},
            fail_on_floor=True,
        )

        # The floored attempt (tried twice - once per token) is abandoned and
        # the sweep redone without it, so comments are never silently lost.
        assert "and" in wheres[0]
        assert wheres[-1] == {"Case__r": {"CaseNumber__c": {"in": ["1", "2"]}}}


class TestGetCaseDetails:
    def test_builds_details_and_loads_comments(self, monkeypatch):
        cases = {
            "1": {"status": "Waiting on Red Hat", "createdate": "2026-09-01T00:00:00Z"},
            "2": {"status": "Closed", "createdate": "2026-09-01T00:00:00Z"},
        }
        store = {}
        monkeypatch.setattr(
            cache.libtelco5g, "redis_get", lambda key: cases if key == "cases" else None
        )
        monkeypatch.setattr(
            cache.libtelco5g, "redis_set", lambda key, val: store.__setitem__(key, val)
        )
        monkeypatch.setattr(cache.libtelco5g, "get_token", lambda token: "tok")

        comments = [
            {
                "commentBody": "c",
                "createdBy": "Jane",
                "createdByType": "Customer",
                "createdDate": "2026-09-02Z",
            }
        ]
        monkeypatch.setattr(
            cache,
            "fetch_case_details_uiapi",
            lambda cfg, token, open_cases: {
                "1": {"group_name": "Telco 5G", "comments": comments}
            },
        )
        loaded = []
        monkeypatch.setattr(
            cache,
            "load_comments_postgres",
            lambda case, created, api: loaded.append((case, api)),
        )

        get_case_details({"offline_token": "t", "graphql_api": "u"})

        details = json.loads(store["details"])
        assert details == {
            "1": {
                "crit_sit": False,
                "group_name": "Telco 5G",
                "notified_users": [],
                "relief_at": None,
                "resolved_at": None,
            }
        }
        # closed case "2" is excluded; only open case "1" loads comments
        assert loaded == [("1", comments)]
        # case_bz stays an empty map (its long-standing contract)
        assert json.loads(store["case_bz"]) == {}

    def test_no_cases_writes_none(self, monkeypatch):
        store = {}
        monkeypatch.setattr(cache.libtelco5g, "redis_get", lambda key: None)
        monkeypatch.setattr(
            cache.libtelco5g, "redis_set", lambda key, val: store.__setitem__(key, val)
        )

        get_case_details({"offline_token": "t", "graphql_api": "u"})

        assert json.loads(store["details"]) is None
        assert json.loads(store["case_bz"]) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
