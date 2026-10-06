"""Tests for retaining closed cases that drop out of the open saved-search.

Covers fetch_case_closure_uiapi (the closure-verification query) and
merge_closed_cases (carrying dropped cases forward, marked "Closed").
"""

import pytest

from t5gweb import cache
from t5gweb.cache import (
    _ensure_closeddate,
    backfill_tracked_cases,
    fetch_case_closure_uiapi,
    fetch_case_projection_uiapi,
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


def _projection_node(
    case_number,
    is_closed=False,
    closed_date=None,
    status="Waiting on Red Hat",
    account="ACME",
    severity="2 (High)",
    problem="prob",
    product="OpenShift 4.16",
    createdate="2026-01-01T00:00:00.000Z",
    last_update="2026-02-01T00:00:00.000Z",
):
    """Build a RedHatSupportCase node like the projection query returns."""
    return {
        "CaseNumber__c": {"value": case_number},
        "RedHatSupportAccount": {"Name": {"value": account}},
        "Status": {"value": status},
        "Priority": {"value": severity},
        "Product": {"Name": {"value": product}},
        "Subject": {"value": problem},
        "CreatedDate": {"value": createdate},
        "LastModifiedDate": {"value": last_update},
        "IsClosed": {"value": is_closed},
        "ClosedDate": {"value": closed_date},
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
    @pytest.fixture(autouse=True)
    def _empty_pg_universe(self, monkeypatch):
        """Default the Postgres universe to empty so tests that only exercise the
        Redis path don't reach a real database. Tests covering the Postgres path
        override this with their own ``load_open_cases_postgres`` patch."""
        monkeypatch.setattr(cache, "load_open_cases_postgres", lambda: {})

    def test_no_prior_cache_is_noop(self, monkeypatch):
        monkeypatch.setattr(cache.libtelco5g, "redis_get", lambda key: {})
        cases = {"open1": _open_entry("open1")}
        merge_closed_cases({}, "tok", cases)
        assert cases == {"open1": _open_entry("open1")}

    def test_dropped_case_verified_closed_is_marked(self, monkeypatch):
        prior = {"gone": _open_entry("gone"), "open1": _open_entry("open1")}
        monkeypatch.setattr(cache.libtelco5g, "redis_get", lambda key: prior)
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
        monkeypatch.setattr(cache.libtelco5g, "redis_get", lambda key: prior)

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
        monkeypatch.setattr(cache.libtelco5g, "redis_get", lambda key: prior)

        cases = {}
        merge_closed_cases({"graphql_api": "x"}, "tok", cases)

        # Falls back to last_update so generate_stats never KeyErrors.
        assert cases["done"]["closeddate"] == "2026-02-01T00:00:00Z"

    def test_dropped_but_still_open_is_carried_unchanged(self, monkeypatch):
        prior = {"capped": _open_entry("capped", status="Waiting on Customer")}
        monkeypatch.setattr(cache.libtelco5g, "redis_get", lambda key: prior)
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
        monkeypatch.setattr(cache.libtelco5g, "redis_get", lambda key: prior)

        def boom(cfg, token, case_numbers):
            raise RuntimeError("graphql down")

        monkeypatch.setattr(cache, "fetch_case_closure_uiapi", boom)

        cases = {}
        merge_closed_cases({"graphql_api": "x"}, "tok", cases)

        # Entry preserved despite the failure; not dropped, not forced closed.
        assert cases["gone"]["status"] == "Waiting on Red Hat"

    def test_postgres_only_closed_case_carried_from_stored_projection(
        self, monkeypatch
    ):
        # Redis has already lost the case (e.g. dropped by a pre-feature build),
        # but Postgres still holds its projection. It must be carried forward and
        # marked Closed using the stored projection - no GraphQL rebuild.
        monkeypatch.setattr(cache.libtelco5g, "redis_get", lambda key: {})
        lost = _open_entry("lost")
        lost["account"] = "ACME"
        lost["problem"] = "recovered problem"
        monkeypatch.setattr(cache, "load_open_cases_postgres", lambda: {"lost": lost})
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(
            cache,
            "graphql_post",
            lambda *a, **k: _page(
                [
                    _closure_node(
                        "lost",
                        is_closed=True,
                        closed_date="2026-03-01T10:00:00.000Z",
                        status="Closed",
                        last_update="2026-03-01T10:00:00.000Z",
                    )
                ]
            ),
        )

        cases = {}
        merge_closed_cases({"graphql_api": "x"}, "tok", cases)

        assert cases["lost"]["status"] == "Closed"
        assert cases["lost"]["closeddate"] == "2026-03-01T10:00:00Z"
        # The stored projection is carried through intact.
        assert cases["lost"]["account"] == "ACME"
        assert cases["lost"]["problem"] == "recovered problem"

    def test_postgres_only_still_open_case_is_carried(self, monkeypatch):
        # Known to Postgres, absent from Redis, and still open (dropped past the
        # result cap): carry it forward from the stored projection, not dropped.
        monkeypatch.setattr(cache.libtelco5g, "redis_get", lambda key: {})
        capped = _open_entry("capped", status="Waiting on Customer")
        monkeypatch.setattr(
            cache, "load_open_cases_postgres", lambda: {"capped": capped}
        )
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(
            cache,
            "graphql_post",
            lambda *a, **k: _page([_closure_node("capped", is_closed=False)]),
        )

        cases = {}
        merge_closed_cases({"graphql_api": "x"}, "tok", cases)

        assert cases["capped"]["status"] == "Waiting on Customer"

    def test_redis_projection_preferred_over_postgres(self, monkeypatch):
        # When both Redis and Postgres hold the case, the fresher full-fidelity
        # Redis projection (description, etc.) wins over the stored Postgres one.
        redis_prior = {"gone": _open_entry("gone")}
        redis_prior["gone"]["description"] = "rich history text"
        pg_prior = {"gone": _open_entry("gone")}
        pg_prior["gone"]["description"] = "stale postgres text"
        monkeypatch.setattr(cache.libtelco5g, "redis_get", lambda key: redis_prior)
        monkeypatch.setattr(cache, "load_open_cases_postgres", lambda: pg_prior)
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(
            cache,
            "graphql_post",
            lambda *a, **k: _page(
                [_closure_node("gone", True, closed_date="2026-03-01T10:00:00.000Z")]
            ),
        )

        cases = {}
        merge_closed_cases({"graphql_api": "x"}, "tok", cases)

        assert cases["gone"]["status"] == "Closed"
        assert cases["gone"]["description"] == "rich history text"


class TestFetchCaseProjectionUiapi:
    def test_parses_projection_fields(self, monkeypatch):
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        node = _projection_node(
            "11111111",
            is_closed=True,
            closed_date="2026-03-01T10:00:00.000Z",
            status="Closed",
            account="ACME",
            severity="2 (High)",
            problem="disk full",
            product="OpenShift 4.16",
        )
        monkeypatch.setattr(cache, "graphql_post", lambda *a, **k: _page([node]))

        result = fetch_case_projection_uiapi({"graphql_api": "x"}, "tok", ["11111111"])

        assert result == {
            "11111111": {
                "account": "ACME",
                "severity": "2 (High)",
                "status": "Closed",
                "problem": "disk full",
                "product": "OpenShift 4.16",
                "createdate": "2026-01-01T00:00:00.000Z",
                "last_update": "2026-02-01T00:00:00.000Z",
                "is_closed": True,
                "closeddate": "2026-03-01T10:00:00.000Z",
            }
        }


class TestBackfillTrackedCases:
    def test_no_tracked_cases_is_noop(self):
        cases = {"open1": _open_entry("open1")}
        assert backfill_tracked_cases({}, "tok", cases, set()) == []
        assert cases == {"open1": _open_entry("open1")}

    def test_nothing_missing_skips_fetch(self, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("should not fetch when nothing is missing")

        monkeypatch.setattr(cache, "graphql_post", boom)

        cases = {"open1": _open_entry("open1")}
        # Every tracked case is already present, so there is nothing to fetch.
        assert (
            backfill_tracked_cases({"graphql_api": "x"}, "tok", cases, {"open1"}) == []
        )
        assert cases == {"open1": _open_entry("open1")}

    def test_missing_closed_case_is_backfilled_and_marked(self, monkeypatch):
        # "gone" is tracked (has a card) but absent from cases and from any stored
        # universe - only recoverable by fetching its projection by case number.
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(
            cache,
            "graphql_post",
            lambda *a, **k: _page(
                [
                    _projection_node(
                        "gone",
                        is_closed=True,
                        closed_date="2026-03-01T10:00:00.000Z",
                        status="Closed",
                        account="ACME",
                        problem="recovered",
                    )
                ]
            ),
        )

        cases = {"open1": _open_entry("open1")}
        added = backfill_tracked_cases(
            {"graphql_api": "x"}, "tok", cases, {"gone", "open1"}
        )

        assert added == ["gone"]
        assert cases["gone"]["status"] == "Closed"
        # Timestamp normalized to the canonical (no fractional seconds) form.
        assert cases["gone"]["closeddate"] == "2026-03-01T10:00:00Z"
        assert cases["gone"]["account"] == "ACME"
        assert cases["gone"]["problem"] == "recovered"
        assert cases["gone"]["description"] == cache._PENDING_VALUE
        # The already-present case is untouched.
        assert cases["open1"] == _open_entry("open1")

    def test_missing_open_case_backfilled_without_closeddate(self, monkeypatch):
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(
            cache,
            "graphql_post",
            lambda *a, **k: _page(
                [
                    _projection_node(
                        "capped", is_closed=False, status="Waiting on Customer"
                    )
                ]
            ),
        )

        cases = {}
        backfill_tracked_cases({"graphql_api": "x"}, "tok", cases, {"capped"})

        assert cases["capped"]["status"] == "Waiting on Customer"
        assert "closeddate" not in cases["capped"]

    def test_fetch_failure_is_noop(self, monkeypatch):
        def boom(cfg, token, case_numbers):
            raise RuntimeError("graphql down")

        monkeypatch.setattr(cache, "fetch_case_projection_uiapi", boom)

        cases = {}
        assert (
            backfill_tracked_cases({"graphql_api": "x"}, "tok", cases, {"gone"}) == []
        )
        assert cases == {}
