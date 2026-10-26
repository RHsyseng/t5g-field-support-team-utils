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
        cases = {"00000001": _open_entry("00000001")}
        merge_closed_cases({}, "tok", cases)
        assert cases == {"00000001": _open_entry("00000001")}

    def test_dropped_case_verified_closed_is_marked(self, monkeypatch):
        prior = {
            "00000002": _open_entry("00000002"),
            "00000001": _open_entry("00000001"),
        }
        monkeypatch.setattr(cache.libtelco5g, "redis_get", lambda key: prior)
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(
            cache,
            "graphql_post",
            lambda *a, **k: _page(
                [
                    _closure_node(
                        "00000002", True, closed_date="2026-03-01T10:00:00.000Z"
                    )
                ]
            ),
        )

        cases = {"00000001": _open_entry("00000001")}
        merge_closed_cases({"graphql_api": "x"}, "tok", cases)

        assert cases["00000002"]["status"] == "Closed"
        # ClosedDate is normalized to the canonical (no fractional seconds) form.
        assert cases["00000002"]["closeddate"] == "2026-03-01T10:00:00Z"
        # The still-open case already in this run is untouched.
        assert cases["00000001"]["status"] == "Waiting on Red Hat"

    def test_carried_forward_severity_is_repaired(self, monkeypatch):
        # A projection that came back through PostgreSQL carries a bare "3".
        # It must be re-expanded here: the Redis copy wins over PostgreSQL and
        # is rewritten at the end of the sync, so a stale value would carry
        # itself forward forever and _build_card_data would lose the card.
        degraded = _open_entry("00000003")
        degraded["status"] = "Closed"
        degraded["closeddate"] = "2026-02-15T00:00:00Z"
        degraded["severity"] = "3"
        monkeypatch.setattr(
            cache.libtelco5g, "redis_get", lambda key: {"00000003": degraded}
        )

        cases = {}
        merge_closed_cases({"graphql_api": "x"}, "tok", cases)

        assert cases["00000003"]["severity"] == "3 (Medium)"

    def test_already_closed_case_carried_without_verifying(self, monkeypatch):
        closed = _open_entry("00000003")
        closed["status"] = "Closed"
        closed["closeddate"] = "2026-02-15T00:00:00Z"
        prior = {"00000003": closed}
        monkeypatch.setattr(cache.libtelco5g, "redis_get", lambda key: prior)

        def boom(*a, **k):
            raise AssertionError(
                "closure query should not run for already-closed cases"
            )

        monkeypatch.setattr(cache, "graphql_post", boom)

        cases = {}
        merge_closed_cases({"graphql_api": "x"}, "tok", cases)

        assert cases["00000003"]["status"] == "Closed"
        assert cases["00000003"]["closeddate"] == "2026-02-15T00:00:00Z"

    def test_already_closed_missing_closeddate_gets_fallback(self, monkeypatch):
        closed = _open_entry("00000003")
        closed["status"] = "Closed"  # no closeddate key
        prior = {"00000003": closed}
        monkeypatch.setattr(cache.libtelco5g, "redis_get", lambda key: prior)

        cases = {}
        merge_closed_cases({"graphql_api": "x"}, "tok", cases)

        # Falls back to last_update so generate_stats never KeyErrors.
        assert cases["00000003"]["closeddate"] == "2026-02-01T00:00:00Z"

    def test_dropped_but_still_open_is_carried_unchanged(self, monkeypatch):
        prior = {"00000004": _open_entry("00000004", status="Waiting on Customer")}
        monkeypatch.setattr(cache.libtelco5g, "redis_get", lambda key: prior)
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(
            cache,
            "graphql_post",
            lambda *a, **k: _page([_closure_node("00000004", False)]),
        )

        cases = {}
        merge_closed_cases({"graphql_api": "x"}, "tok", cases)

        # Carried forward, not marked closed.
        assert cases["00000004"]["status"] == "Waiting on Customer"
        assert "closeddate" not in cases["00000004"]

    def test_non_support_records_are_not_carried_forward(self, monkeypatch):
        # EN-* escalation notifications are filtered out of the fresh selection,
        # but older cache/Postgres entries still hold them. Carrying them forward
        # resurrected them on every run: case(id) 404s on them so they can never
        # be verified closed, leaving them permanently "open" for
        # sync_portal_to_jira to turn into JIRA cards.
        prior = {
            "EN-00001": _open_entry("EN-00001"),
            "00000002": _open_entry("00000002"),
        }
        monkeypatch.setattr(cache.libtelco5g, "redis_get", lambda key: prior)
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})

        verified = []

        def record(cfg, token, case_numbers):
            verified.extend(case_numbers)
            return {}

        monkeypatch.setattr(cache, "fetch_case_closure_uiapi", record)

        cases = {}
        merge_closed_cases({"graphql_api": "x"}, "tok", cases)

        assert "EN-00001" not in cases
        # The real case alongside it is still carried forward as before.
        assert cases["00000002"]["status"] == "Waiting on Red Hat"
        # The 404-ing record is never even sent for verification.
        assert verified == ["00000002"]

    def test_non_support_records_from_postgres_are_not_carried_forward(
        self, monkeypatch
    ):
        monkeypatch.setattr(
            cache,
            "load_open_cases_postgres",
            lambda: {"EN-00002": _open_entry("EN-00002")},
        )
        monkeypatch.setattr(cache.libtelco5g, "redis_get", lambda key: {})

        def boom(*a, **k):
            raise AssertionError("no verification should run for a filtered record")

        monkeypatch.setattr(cache, "fetch_case_closure_uiapi", boom)

        cases = {}
        merge_closed_cases({"graphql_api": "x"}, "tok", cases)

        assert cases == {}

    def test_verification_failure_keeps_prior_entries(self, monkeypatch):
        prior = {"00000002": _open_entry("00000002")}
        monkeypatch.setattr(cache.libtelco5g, "redis_get", lambda key: prior)

        def boom(cfg, token, case_numbers):
            raise RuntimeError("graphql down")

        monkeypatch.setattr(cache, "fetch_case_closure_uiapi", boom)

        cases = {}
        merge_closed_cases({"graphql_api": "x"}, "tok", cases)

        # Entry preserved despite the failure; not dropped, not forced closed.
        assert cases["00000002"]["status"] == "Waiting on Red Hat"

    def test_postgres_only_closed_case_carried_from_stored_projection(
        self, monkeypatch
    ):
        # Redis has already lost the case (e.g. dropped by a pre-feature build),
        # but Postgres still holds its projection. It must be carried forward and
        # marked Closed using the stored projection - no GraphQL rebuild.
        monkeypatch.setattr(cache.libtelco5g, "redis_get", lambda key: {})
        lost = _open_entry("00000005")
        lost["account"] = "ACME"
        lost["problem"] = "recovered problem"
        monkeypatch.setattr(
            cache, "load_open_cases_postgres", lambda: {"00000005": lost}
        )
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(
            cache,
            "graphql_post",
            lambda *a, **k: _page(
                [
                    _closure_node(
                        "00000005",
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

        assert cases["00000005"]["status"] == "Closed"
        assert cases["00000005"]["closeddate"] == "2026-03-01T10:00:00Z"
        # The stored projection is carried through intact.
        assert cases["00000005"]["account"] == "ACME"
        assert cases["00000005"]["problem"] == "recovered problem"

    def test_postgres_only_still_open_case_is_carried(self, monkeypatch):
        # Known to Postgres, absent from Redis, and still open (dropped past the
        # result cap): carry it forward from the stored projection, not dropped.
        monkeypatch.setattr(cache.libtelco5g, "redis_get", lambda key: {})
        capped = _open_entry("00000004", status="Waiting on Customer")
        monkeypatch.setattr(
            cache, "load_open_cases_postgres", lambda: {"00000004": capped}
        )
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(
            cache,
            "graphql_post",
            lambda *a, **k: _page([_closure_node("00000004", is_closed=False)]),
        )

        cases = {}
        merge_closed_cases({"graphql_api": "x"}, "tok", cases)

        assert cases["00000004"]["status"] == "Waiting on Customer"

    def test_postgres_error_falls_back_to_redis_universe(self, monkeypatch):
        # When load_open_cases_postgres raises PgError, the merge degrades to the
        # Redis universe alone instead of blowing up the whole sync.
        from t5gweb.database import PgError

        def _boom():
            raise PgError("db down")

        monkeypatch.setattr(cache, "load_open_cases_postgres", _boom)
        prior = {"00000002": _open_entry("00000002")}
        monkeypatch.setattr(cache.libtelco5g, "redis_get", lambda key: prior)
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(
            cache,
            "graphql_post",
            lambda *a, **k: _page(
                [
                    _closure_node(
                        "00000002", True, closed_date="2026-03-01T10:00:00.000Z"
                    )
                ]
            ),
        )

        cases = {}
        merge_closed_cases({"graphql_api": "x"}, "tok", cases)

        assert cases["00000002"]["status"] == "Closed"

    def test_redis_projection_preferred_over_postgres(self, monkeypatch):
        # When both Redis and Postgres hold the case, the fresher full-fidelity
        # Redis projection (description, etc.) wins over the stored Postgres one.
        redis_prior = {"00000002": _open_entry("00000002")}
        redis_prior["00000002"]["description"] = "rich history text"
        pg_prior = {"00000002": _open_entry("00000002")}
        pg_prior["00000002"]["description"] = "stale postgres text"
        monkeypatch.setattr(cache.libtelco5g, "redis_get", lambda key: redis_prior)
        monkeypatch.setattr(cache, "load_open_cases_postgres", lambda: pg_prior)
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(
            cache,
            "graphql_post",
            lambda *a, **k: _page(
                [
                    _closure_node(
                        "00000002", True, closed_date="2026-03-01T10:00:00.000Z"
                    )
                ]
            ),
        )

        cases = {}
        merge_closed_cases({"graphql_api": "x"}, "tok", cases)

        assert cases["00000002"]["status"] == "Closed"
        assert cases["00000002"]["description"] == "rich history text"


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
        cases = {"00000001": _open_entry("00000001")}
        assert backfill_tracked_cases({}, "tok", cases, set()) == []
        assert cases == {"00000001": _open_entry("00000001")}

    def test_nothing_missing_skips_fetch(self, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("should not fetch when nothing is missing")

        monkeypatch.setattr(cache, "graphql_post", boom)

        cases = {"00000001": _open_entry("00000001")}
        # Every tracked case is already present, so there is nothing to fetch.
        assert (
            backfill_tracked_cases({"graphql_api": "x"}, "tok", cases, {"00000001"})
            == []
        )
        assert cases == {"00000001": _open_entry("00000001")}

    def test_missing_closed_case_is_backfilled_and_marked(self, monkeypatch):
        # "00000002" is tracked (has a card) but absent from cases and from any stored
        # universe - only recoverable by fetching its projection by case number.
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(
            cache,
            "graphql_post",
            lambda *a, **k: _page(
                [
                    _projection_node(
                        "00000002",
                        is_closed=True,
                        closed_date="2026-03-01T10:00:00.000Z",
                        status="Closed",
                        account="ACME",
                        problem="recovered",
                    )
                ]
            ),
        )

        cases = {"00000001": _open_entry("00000001")}
        added = backfill_tracked_cases(
            {"graphql_api": "x"}, "tok", cases, {"00000002", "00000001"}
        )

        assert added == ["00000002"]
        assert cases["00000002"]["status"] == "Closed"
        # Timestamp normalized to the canonical (no fractional seconds) form.
        assert cases["00000002"]["closeddate"] == "2026-03-01T10:00:00Z"
        assert cases["00000002"]["account"] == "ACME"
        assert cases["00000002"]["problem"] == "recovered"
        assert cases["00000002"]["description"] == cache._PENDING_VALUE
        # The already-present case is untouched.
        assert cases["00000001"] == _open_entry("00000001")

    def test_missing_open_case_backfilled_without_closeddate(self, monkeypatch):
        monkeypatch.setattr(cache, "make_graphql_headers", lambda token: {})
        monkeypatch.setattr(
            cache,
            "graphql_post",
            lambda *a, **k: _page(
                [
                    _projection_node(
                        "00000004", is_closed=False, status="Waiting on Customer"
                    )
                ]
            ),
        )

        cases = {}
        backfill_tracked_cases({"graphql_api": "x"}, "tok", cases, {"00000004"})

        assert cases["00000004"]["status"] == "Waiting on Customer"
        assert "closeddate" not in cases["00000004"]

    def test_fetch_failure_is_noop(self, monkeypatch):
        def boom(cfg, token, case_numbers):
            raise RuntimeError("graphql down")

        monkeypatch.setattr(cache, "fetch_case_projection_uiapi", boom)

        cases = {}
        assert (
            backfill_tracked_cases({"graphql_api": "x"}, "tok", cases, {"00000002"})
            == []
        )
        assert cases == {}
