"""Tests for the UIAPI-sourced case detail path (group + comments)."""

import json

import pytest

from t5gweb import cache
from t5gweb.cache import (
    fetch_case_details_uiapi,
    get_case_details,
)
from t5gweb.utils import uiapi_comment_to_dict


def _node(case_number, group_name=None, comments=None):
    """Build a RedHatSupportCase edge node like the UIAPI query returns."""
    return {
        "CaseNumber__c": {"value": case_number},
        "Group__r": {"Name": {"value": group_name}} if group_name else None,
        "CaseComments": {
            "edges": [{"node": c} for c in (comments or [])],
        },
    }


def _comment(body, author, created, published=True):
    return {
        "CommentBody": {"value": body},
        "CreatedDate": {"value": created},
        "IsPublished": {"value": published},
        "CreatedBy": {"Name": {"value": author}},
    }


def _page(nodes, has_next=False, end_cursor=None):
    """Wrap nodes in the GraphQL envelope graphql_post returns."""
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


class TestUiapiCommentToDict:
    def test_full_node(self):
        node = _comment("hello", "Jane Doe", "2026-09-01T00:00:00.000Z")
        assert uiapi_comment_to_dict(node) == {
            "commentBody": "hello",
            "createdBy": "Jane Doe",
            "createdDate": "2026-09-01T00:00:00.000Z",
        }

    def test_missing_author_defaults_to_unknown(self):
        node = {
            "CommentBody": {"value": "body"},
            "CreatedDate": {"value": "2026-09-01T00:00:00.000Z"},
            "CreatedBy": None,
        }
        assert uiapi_comment_to_dict(node)["createdBy"] == "unknown"

    def test_missing_body_defaults_to_empty_string(self):
        node = {
            "CommentBody": None,
            "CreatedDate": {"value": "2026-09-01T00:00:00.000Z"},
            "CreatedBy": {"Name": {"value": "Jane"}},
        }
        assert uiapi_comment_to_dict(node)["commentBody"] == ""

    def test_missing_created_date_is_none(self):
        node = {
            "CommentBody": {"value": "body"},
            "CreatedDate": None,
            "CreatedBy": {"Name": {"value": "Jane"}},
        }
        assert uiapi_comment_to_dict(node)["createdDate"] is None


class TestFetchCaseDetailsUiapi:
    def test_maps_group_and_comments(self, monkeypatch):
        node = _node(
            "12345678",
            group_name="Telco 5G",
            comments=[_comment("first", "Jane", "2026-09-01T00:00:00.000Z")],
        )
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(cache, "graphql_post", lambda *a, **k: _page([node]))

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
                        "createdDate": "2026-09-01T00:00:00.000Z",
                    }
                ],
            }
        }

    def test_missing_group_is_none(self, monkeypatch):
        node = _node("12345678", group_name=None, comments=[])
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(cache, "graphql_post", lambda *a, **k: _page([node]))

        result = fetch_case_details_uiapi(
            {"graphql_api": "u", "offline_token": "t"}, "tok", ["12345678"]
        )
        assert result["12345678"]["group_name"] is None
        assert result["12345678"]["comments"] == []

    def test_chunks_by_case_detail_chunk_size(self, monkeypatch):
        monkeypatch.setattr(cache, "_CASE_DETAIL_CHUNK_SIZE", 2)
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})

        seen_wheres = []

        def fake_post(url, headers, query, variables):
            seen_wheres.append(variables["where"]["CaseNumber__c"]["in"])
            nodes = [_node(cn) for cn in variables["where"]["CaseNumber__c"]["in"]]
            return _page(nodes)

        monkeypatch.setattr(cache, "graphql_post", fake_post)

        result = fetch_case_details_uiapi(
            {"graphql_api": "u", "offline_token": "t"}, "tok", ["1", "2", "3"]
        )

        assert seen_wheres == [["1", "2"], ["3"]]
        assert set(result) == {"1", "2", "3"}

    def test_paginates_within_chunk(self, monkeypatch):
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        pages = [
            _page([_node("1")], has_next=True, end_cursor="CURSOR"),
            _page([_node("2")], has_next=False),
        ]
        calls = []

        def fake_post(url, headers, query, variables):
            calls.append(variables["after"])
            return pages[len(calls) - 1]

        monkeypatch.setattr(cache, "graphql_post", fake_post)

        result = fetch_case_details_uiapi(
            {"graphql_api": "u", "offline_token": "t"}, "tok", ["1", "2"]
        )

        assert calls == [None, "CURSOR"]
        assert set(result) == {"1", "2"}

    def test_reauth_and_retry_on_failure(self, monkeypatch):
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(cache.libtelco5g, "get_token", lambda token: "fresh-token")
        node = _node("1", group_name="G")
        state = {"calls": 0}

        def fake_post(url, headers, query, variables):
            state["calls"] += 1
            if state["calls"] == 1:
                raise RuntimeError("GraphQL error: 403")
            return _page([node])

        monkeypatch.setattr(cache, "graphql_post", fake_post)

        result = fetch_case_details_uiapi(
            {"graphql_api": "u", "offline_token": "t"}, "tok", ["1"]
        )
        assert result["1"]["group_name"] == "G"
        assert state["calls"] == 2

    def test_chunk_skipped_when_retry_also_fails(self, monkeypatch):
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(cache.libtelco5g, "get_token", lambda token: "fresh")

        def fake_post(url, headers, query, variables):
            raise RuntimeError("GraphQL error: 403")

        monkeypatch.setattr(cache, "graphql_post", fake_post)

        result = fetch_case_details_uiapi(
            {"graphql_api": "u", "offline_token": "t"}, "tok", ["1"]
        )
        assert result == {}


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
            {"commentBody": "c", "createdBy": "Jane", "createdDate": "2026-09-02Z"}
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
