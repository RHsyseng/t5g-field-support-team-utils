"""Tests for retaining closed cases that drop out of the open saved-search.

Covers fetch_case_closure_uiapi (the closure-verification query) and
merge_closed_cases (carrying dropped cases forward, marked "Closed").
"""

from t5gweb import cache
from t5gweb.cache import (
    _ensure_closeddate,
    fetch_case_closure_uiapi,
    merge_closed_cases,
)


def _closure_node(
    case_number, is_closed, closed_date=None, status=None, last_update=None
):
    """Build a RedHatSupportCase edge node like the closure query returns."""
    return {
        "CaseNumber__c": {"value": case_number},
        "IsClosed": {"value": is_closed},
        "ClosedDate": {"value": closed_date},
        "Status": {"value": status},
        "LastModifiedDate": {"value": last_update},
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


def _open_entry(case_number, status="Waiting on Red Hat"):
    """A minimal open-case projection as get_cases builds it."""
    return {
        "owner": None,
        "severity": "2 (High)",
        "account": "ACME",
        "problem": f"problem {case_number}",
        "status": status,
        "createdate": "2026-01-01T00:00:00Z",
        "last_update": "2026-02-01T00:00:00Z",
        "description": "desc",
        "product": "OpenShift 4.16",
        "product_version": None,
    }


class TestFetchCaseClosureUiapi:
    def test_parses_closure_fields(self, monkeypatch):
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        node = _closure_node(
            "11111111",
            is_closed=True,
            closed_date="2026-03-01T10:00:00.000Z",
            status="Closed",
            last_update="2026-03-01T10:00:00.000Z",
        )
        monkeypatch.setattr(cache, "graphql_post", lambda *a, **k: _page([node]))

        result = fetch_case_closure_uiapi({"graphql_api": "x"}, "tok", ["11111111"])

        assert result == {
            "11111111": {
                "is_closed": True,
                "closeddate": "2026-03-01T10:00:00.000Z",
                "status": "Closed",
                "last_update": "2026-03-01T10:00:00.000Z",
            }
        }

    def test_missing_isclosed_defaults_false(self, monkeypatch):
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        node = {"CaseNumber__c": {"value": "22222222"}}
        monkeypatch.setattr(cache, "graphql_post", lambda *a, **k: _page([node]))

        result = fetch_case_closure_uiapi({"graphql_api": "x"}, "tok", ["22222222"])

        assert result["22222222"]["is_closed"] is False
        assert result["22222222"]["closeddate"] is None

    def test_chunks_by_detail_chunk_size(self, monkeypatch):
        monkeypatch.setattr(cache, "_CASE_DETAIL_CHUNK_SIZE", 2)
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        seen = []

        def fake_post(url, headers, query, variables):
            seen.append(variables["where"]["CaseNumber__c"]["in"])
            return _page(
                [
                    _closure_node(c, True)
                    for c in variables["where"]["CaseNumber__c"]["in"]
                ]
            )

        monkeypatch.setattr(cache, "graphql_post", fake_post)

        fetch_case_closure_uiapi({"graphql_api": "x"}, "tok", ["a", "b", "c"])

        assert seen == [["a", "b"], ["c"]]

    def test_reauth_and_retry_on_failure(self, monkeypatch):
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(cache.libtelco5g, "get_token", lambda token: "fresh")
        calls = {"n": 0}

        def fake_post(url, headers, query, variables):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return _page([_closure_node("33333333", True)])

        monkeypatch.setattr(cache, "graphql_post", fake_post)

        result = fetch_case_closure_uiapi(
            {"graphql_api": "x", "offline_token": "o"}, "tok", ["33333333"]
        )

        assert result["33333333"]["is_closed"] is True
        assert calls["n"] == 2

    def test_chunk_skipped_when_retry_also_fails(self, monkeypatch):
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(cache.libtelco5g, "get_token", lambda token: "fresh")

        def fake_post(url, headers, query, variables):
            raise RuntimeError("down")

        monkeypatch.setattr(cache, "graphql_post", fake_post)

        result = fetch_case_closure_uiapi(
            {"graphql_api": "x", "offline_token": "o"}, "tok", ["44444444"]
        )

        assert result == {}


class TestEnsureCloseddate:
    def test_keeps_existing_closeddate(self):
        entry = {"closeddate": "2026-05-01T00:00:00Z", "last_update": "x"}
        assert _ensure_closeddate(entry)["closeddate"] == "2026-05-01T00:00:00Z"

    def test_falls_back_to_last_update(self):
        entry = {"last_update": "2026-04-01T00:00:00Z", "createdate": "2026-01-01Z"}
        assert _ensure_closeddate(entry)["closeddate"] == "2026-04-01T00:00:00Z"

    def test_falls_back_to_createdate(self):
        entry = {"last_update": None, "createdate": "2026-01-01T00:00:00Z"}
        assert _ensure_closeddate(entry)["closeddate"] == "2026-01-01T00:00:00Z"


class TestMergeClosedCases:
    def test_no_prior_cache_is_noop(self, monkeypatch):
        monkeypatch.setattr(cache.libtelco5g, "redis_get", lambda key: {})
        cases = {"open1": _open_entry("open1")}
        merge_closed_cases({}, "tok", cases)
        assert cases == {"open1": _open_entry("open1")}

    def test_dropped_case_verified_closed_is_marked(self, monkeypatch):
        prior = {"gone": _open_entry("gone"), "open1": _open_entry("open1")}
        monkeypatch.setattr(
            cache.libtelco5g, "redis_get", lambda key: prior
        )
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(
            cache,
            "graphql_post",
            lambda *a, **k: _page(
                [_closure_node("gone", True, closed_date="2026-03-01T10:00:00.000Z")]
            ),
        )

        cases = {"open1": _open_entry("open1")}
        merge_closed_cases({"graphql_api": "x"}, "tok", cases)

        assert cases["gone"]["status"] == "Closed"
        # ClosedDate is normalized to the canonical (no fractional seconds) form.
        assert cases["gone"]["closeddate"] == "2026-03-01T10:00:00Z"
        # The still-open case already in this run is untouched.
        assert cases["open1"]["status"] == "Waiting on Red Hat"

    def test_already_closed_case_carried_without_verifying(self, monkeypatch):
        closed = _open_entry("done")
        closed["status"] = "Closed"
        closed["closeddate"] = "2026-02-15T00:00:00Z"
        prior = {"done": closed}
        monkeypatch.setattr(
            cache.libtelco5g, "redis_get", lambda key: prior
        )

        def boom(*a, **k):
            raise AssertionError(
                "closure query should not run for already-closed cases"
            )

        monkeypatch.setattr(cache, "graphql_post", boom)

        cases = {}
        merge_closed_cases({"graphql_api": "x"}, "tok", cases)

        assert cases["done"]["status"] == "Closed"
        assert cases["done"]["closeddate"] == "2026-02-15T00:00:00Z"

    def test_already_closed_missing_closeddate_gets_fallback(self, monkeypatch):
        closed = _open_entry("done")
        closed["status"] = "Closed"  # no closeddate key
        prior = {"done": closed}
        monkeypatch.setattr(
            cache.libtelco5g, "redis_get", lambda key: prior
        )

        cases = {}
        merge_closed_cases({"graphql_api": "x"}, "tok", cases)

        # Falls back to last_update so generate_stats never KeyErrors.
        assert cases["done"]["closeddate"] == "2026-02-01T00:00:00Z"

    def test_dropped_but_still_open_is_carried_unchanged(self, monkeypatch):
        prior = {"capped": _open_entry("capped", status="Waiting on Customer")}
        monkeypatch.setattr(
            cache.libtelco5g, "redis_get", lambda key: prior
        )
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(
            cache,
            "graphql_post",
            lambda *a, **k: _page([_closure_node("capped", False)]),
        )

        cases = {}
        merge_closed_cases({"graphql_api": "x"}, "tok", cases)

        # Carried forward, not marked closed.
        assert cases["capped"]["status"] == "Waiting on Customer"
        assert "closeddate" not in cases["capped"]

    def test_verification_failure_keeps_prior_entries(self, monkeypatch):
        prior = {"gone": _open_entry("gone")}
        monkeypatch.setattr(
            cache.libtelco5g, "redis_get", lambda key: prior
        )

        def boom(cfg, token, case_numbers):
            raise RuntimeError("graphql down")

        monkeypatch.setattr(cache, "fetch_case_closure_uiapi", boom)

        cases = {}
        merge_closed_cases({"graphql_api": "x"}, "tok", cases)

        # Entry preserved despite the failure; not dropped, not forced closed.
        assert cases["gone"]["status"] == "Waiting on Red Hat"
