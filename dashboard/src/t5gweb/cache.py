"""cache.py: caching functions for the t5gweb"""

import datetime
import json
import logging
import os
import random
import re
import threading
import time
import xmlrpc
from concurrent.futures import ThreadPoolExecutor

import bugzilla
import requests
from dateutil import parser as date_parser
from jira.exceptions import JIRAError

from t5gweb import libtelco5g
from t5gweb.database import (
    load_cases_postgres,
    load_comments_postgres,
    load_jira_card_postgres,
)
from t5gweb.utils import (
    format_comment,
    format_date,
    make_graphql_headers,
    make_headers,
    remap_case_status,
)

# Selection query (planv3.md §3a). Account name is pulled inline via the
# RedHatSupportAccount parent relationship so no separate /v1/accounts/{ref}
# lookup is needed. This light query carries every field the case-assignment
# path needs (account, severity, status, subject, product, dates), so get_cases
# builds the projection straight from it - no per-case case(id) hydration. The
# richer fields (description, comments, tags, critSit, ...) are filled in later
# by get_case_details, so they are left blank/placeholder here.
GRAPHQL_SAVED_SEARCH_QUERY = """
query SavedSearch($where: RedHatSupportCase_Filter, $after: String) {
  redhat_support_uiapi { query {
    RedHatSupportCase(where: $where, first: 100, after: $after,
                      orderBy: { LastModifiedDate: { order: DESC } }) {
      totalCount
      pageInfo { hasNextPage endCursor }
      edges { node {
        CaseNumber__c { value }
        Account_Number__c { value }
        RedHatSupportAccount { Name { value } }
        Status { value }
        Priority { value }
        Product { Name { value } }
        Subject { value }
        CreatedDate { value }
        LastModifiedDate { value }
      } }
    }
  } }
}
"""

# Canonical timestamp form the downstream code expects (utils.format_date and
# libtelco5g._is_old_case both strptime this exact pattern). The UIAPI selection
# query returns fractional-second timestamps ("2026-09-03T12:36:12.000Z"), so
# normalize to the v1 form at ingest to preserve the stored contract.
_CANONICAL_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _normalize_ts(value):
    """Coerce an API timestamp to the canonical ``%Y-%m-%dT%H:%M:%SZ`` form.

    The GraphQL UIAPI selection returns timestamps with a fractional-second part
    (``.000Z``) that ``utils.format_date`` / ``_is_old_case`` cannot parse.
    Parse leniently and reformat; return the value unchanged if it is empty or
    cannot be parsed (so a bad value surfaces later rather than crashing ingest).

    Args:
        value: the raw timestamp string (or None).

    Returns:
        str or None: the normalized timestamp, or the original value.
    """
    if not value:
        return value
    try:
        return date_parser.parse(value).strftime(_CANONICAL_TS_FORMAT)
    except (ValueError, TypeError):
        return value


# Placeholder for projection fields the light saved-search query does not carry.
# get_case_details (or a future per-case backfill queue) replaces the real value;
# until then the card/dashboard shows this rather than an empty string.
_PENDING_VALUE = "In progress - details not yet synced"

# Case detail / hydration query - the GraphQL twin of GET /v3/cases/{n}
# (HydraCase mirrors the v3 REST GetCaseResponse field-for-field).
GRAPHQL_CASE_DETAIL_QUERY = """
query CaseDetail($id: String!) {
  case(id: $id) {
    caseNumber
    ownerId
    severity
    summary
    status
    createdDate
    lastModifiedDate
    description
    product
    version
    accountNumberRef
    isClosed
    lastClosedAt
    critSit
    groupName
    apiTags
    bugzillas
    notifiedUsers { ssoUsername title type }
    comments { commentBody createdBy createdDate }
  }
}
"""

# Transient GraphQL upstream failures worth retrying (planv3.md §3a).
_GRAPHQL_TRANSIENT_MARKERS = (
    "503",
    "502",
    "504",
    "Service Unavailable",
    "SUBREQUEST_HTTP_ERROR",
    "unsupported content-type",
)


def _product_or(products):
    """OR block matching any product in the configured list by name substring."""
    return {"or": [{"Product": {"Name": {"like": f"%{p}%"}}} for p in products]}


def _account_filter(accounts):
    """Match a single account (eq) or a list of accounts (in)."""
    if len(accounts) == 1:
        return {"Account_Number__c": {"eq": accounts[0]}}
    return {"Account_Number__c": {"in": list(accounts)}}


def build_where(saved_search, open_only=True):
    """Build the GraphQL ``where`` filter from the saved-search config.

    Ported from the field owner's tested saved-search script (planv3.md §3a).
    The filter is ``OR(subject-contains block, each account branch)``, each
    branch being ``Account_Number__c IN (...)`` optionally AND-ed with the
    product block when the branch sets ``product: true``. When ``open_only`` is
    set the whole OR is AND-ed with ``IsClosed: {eq: false}``.

    Args:
        saved_search: dict with ``products``, ``subject_contains`` and
            ``account_branches`` keys (see cfg/sample.env).
        open_only: when True, restrict to non-closed cases.

    Returns:
        dict: the GraphQL ``where`` filter object.
    """
    products = saved_search.get("products", [])
    subject_contains = saved_search.get("subject_contains", [])
    product_block = _product_or(products) if products else None

    branches = []
    if subject_contains:
        branches.append(
            {"or": [{"Subject": {"like": f"%{s}%"}} for s in subject_contains]}
        )
    for branch in saved_search.get("account_branches", []):
        account_block = _account_filter(branch["accounts"])
        if branch.get("product") and product_block:
            branches.append({"and": [account_block, product_block]})
        else:
            branches.append(account_block)

    where = {"or": branches}
    if open_only:
        where = {"and": [{"IsClosed": {"eq": False}}, where]}
    return where


def _graphql_post(url, headers, query, variables, timeout=180, retries=5):
    """POST a GraphQL query, retrying transient upstream failures.

    Args:
        url: the GraphQL endpoint.
        headers: request headers (see utils.make_graphql_headers).
        query: the GraphQL query string.
        variables: the query variables dict.
        timeout: per-request timeout in seconds.
        retries: number of attempts before giving up.

    Returns:
        dict: the parsed GraphQL response.

    Raises:
        RuntimeError: if the request keeps failing after all retries.
    """
    body = {"query": query, "variables": variables}
    for attempt in range(retries):
        err = None
        transient = False
        try:
            r = requests.post(url, json=body, headers=headers, timeout=timeout)
        except requests.exceptions.RequestException as exc:
            # network-level failure (reset, timeout) - always worth retrying
            err = str(exc)
            transient = True
        else:
            try:
                data = r.json()
            except ValueError:
                # Non-JSON body. Under request-rate pressure the edge WAF/CDN
                # returns an HTML "403 Access Denied" page instead of JSON
                # (r.json() then fails with "Expecting value: line 1 column 1").
                # This is a throttle, so back off and retry rather than dropping
                # the case. The real fix is fewer requests: keep hydration
                # concurrency modest (see _MAX_HYDRATION_WORKERS).
                err = "HTTP %s non-JSON body: %r" % (r.status_code, r.text[:120])
                transient = True
            else:
                if data.get("errors"):
                    err = json.dumps(data["errors"])[:500]
                    transient = any(m in err for m in _GRAPHQL_TRANSIENT_MARKERS)
                else:
                    return data

        if attempt < retries - 1 and transient:
            # exponential backoff with jitter so the pool's threads don't all
            # retry in lockstep and re-trigger the same overload.
            wait = 2**attempt + random.uniform(0, 1)
            logging.warning(
                "transient GraphQL error, retry %s/%s in %.1fs: %s",
                attempt + 1,
                retries - 1,
                wait,
                (err or "no data")[:120],
            )
            time.sleep(wait)
            continue
        raise RuntimeError("GraphQL error: " + (err or "no data"))


def _fetch_saved_search_cases(cfg, token, limit=None):
    """Select the telco case set via the Red Hat GraphQL saved-search.

    Cursor-pages the tested account+product+subject query (planv3.md §3a) and
    returns the light case nodes; each is hydrated with the v3 detail endpoint
    later to build the full projection. The query is ordered by
    ``LastModifiedDate DESC``, so when ``limit`` is set the returned list is the
    ``limit`` most-recently-modified matches (the v1 ``max_portal_results``
    contract: v1 capped the search with ``rows=max_portal_results``).

    Args:
        cfg: configuration dictionary (needs ``graphql_api`` and
            ``saved_search``).
        token: a valid bearer access token.
        limit: maximum number of cases to return; ``None``/``0`` means no cap.

    Returns:
        list: dicts with the light projection fields (``caseNumber``, ``account``,
            ``severity``, ``status``, ``problem``, ``product``, ``createdate``,
            ``last_update``) - everything the case-assignment path needs.
    """
    url = cfg["graphql_api"]
    headers = make_graphql_headers(token)
    where = build_where(cfg["saved_search"])

    cases = []
    after = None
    total = None
    while True:
        data = _graphql_post(
            url, headers, GRAPHQL_SAVED_SEARCH_QUERY, {"where": where, "after": after}
        )
        conn = data["data"]["redhat_support_uiapi"]["query"]["RedHatSupportCase"]
        total = conn["totalCount"]
        for edge in conn["edges"]:
            node = edge["node"]
            account = ((node.get("RedHatSupportAccount") or {}).get("Name") or {}).get(
                "value"
            )
            product = ((node.get("Product") or {}).get("Name") or {}).get("value")
            cases.append(
                {
                    "caseNumber": node["CaseNumber__c"]["value"],
                    "account": account,
                    "severity": (node.get("Priority") or {}).get("value"),
                    "status": (node.get("Status") or {}).get("value"),
                    "problem": (node.get("Subject") or {}).get("value"),
                    "product": product,
                    "createdate": (node.get("CreatedDate") or {}).get("value"),
                    "last_update": (node.get("LastModifiedDate") or {}).get("value"),
                }
            )
        page_info = conn["pageInfo"]
        if limit and len(cases) >= limit:
            cases = cases[:limit]
            break
        if not page_info["hasNextPage"]:
            break
        after = page_info["endCursor"]

    logging.warning(
        "GraphQL saved-search matched %s cases (totalCount=%s, limit=%s)",
        len(cases),
        total,
        limit,
    )
    return cases


def _hydrate_case_graphql(url, headers, case_number):
    """Fetch full case detail via the GraphQL ``case(id)`` query (HydraCase).

    GraphQL twin of ``GET /v3/cases/{n}`` (planv3.md §3b). Returns the raw
    HydraCase object.

    Args:
        url: the GraphQL endpoint.
        headers: GraphQL request headers.
        case_number: the case number to hydrate.

    Returns:
        dict or None: the HydraCase object, or None if not returned.
    """
    data = _graphql_post(url, headers, GRAPHQL_CASE_DETAIL_QUERY, {"id": case_number})
    return (data.get("data") or {}).get("case")


def _int_or_none(value):
    """Coerce a config value to a positive int, or None when unset/invalid.

    ``max_portal_results`` and ``graphql_hydration_workers`` arrive as strings
    from the environment; treat a missing, non-numeric or non-positive value as
    "unset".

    Args:
        value: the raw config value (str, int or None).

    Returns:
        int or None: the positive integer, or None when there is no valid value.
    """
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


# Number of concurrent case(id) hydration requests. The casesFilter batch
# endpoint ignores the caseNumbers filter on this deployment, so hydration is one
# case(id) round-trip per case; doing them sequentially blows the request/worker
# timeout on a few hundred cases, so fan them out over a small thread pool. Kept
# modest because too much concurrency makes the gateway shed load with empty
# responses (and init-cache + the web worker can hydrate at the same time, so the
# effective concurrency is a multiple of this). Override with the
# ``graphql_hydration_workers`` env var if the endpoint tolerates more.
_MAX_HYDRATION_WORKERS = _int_or_none(os.environ.get("graphql_hydration_workers")) or 8


def _hydrate_cases_parallel(cfg, url, headers, case_numbers):
    """Hydrate many cases concurrently via the GraphQL ``case(id)`` query.

    Fans ``case_numbers`` out over a bounded thread pool (each a case(id)
    round-trip; planv3.md §3b). On a per-case failure the access token is
    refreshed once - serialized under a lock and collapsed so a burst of
    simultaneous auth failures triggers a single refresh, not one per case - and
    the case retried once, mirroring the sequential ``_hydrate_case_with_reauth``.

    Args:
        cfg: configuration dictionary (needs ``offline_token``).
        url: the GraphQL endpoint.
        headers: current GraphQL request headers.
        case_numbers: list of case numbers to hydrate.

    Returns:
        tuple: ``(hydrated, headers)`` where ``hydrated`` maps case number to its
            HydraCase dict (cases that never hydrated are omitted), and
            ``headers`` are the (possibly refreshed) headers for reuse.
    """
    lock = threading.Lock()
    state = {"headers": headers}

    def worker(case_number):
        used = state["headers"]
        try:
            return case_number, _hydrate_case_graphql(url, used, case_number)
        except Exception as exc:
            with lock:
                # Only refresh if nobody else already did since this worker's
                # attempt, so a stampede of failures costs one token exchange.
                if state["headers"] is used:
                    logging.warning(
                        "re-authenticating after hydration error for %s: %s",
                        case_number,
                        exc,
                    )
                    try:
                        state["headers"] = make_graphql_headers(
                            libtelco5g.get_token(cfg["offline_token"])
                        )
                    except Exception as refresh_exc:
                        logging.warning("token refresh failed: %s", refresh_exc)
                retry_headers = state["headers"]
            try:
                return case_number, _hydrate_case_graphql(
                    url, retry_headers, case_number
                )
            except Exception as exc2:
                logging.warning(
                    "could not hydrate case %s via GraphQL: %s", case_number, exc2
                )
                return case_number, None

    hydrated = {}
    with ThreadPoolExecutor(max_workers=_MAX_HYDRATION_WORKERS) as executor:
        for case_number, case_json in executor.map(worker, case_numbers):
            if case_json:
                hydrated[case_number] = case_json
    return hydrated, state["headers"]


def get_cases(cfg):
    """Get cases from the Red Hat GraphQL saved-search and cache them

    Selects the telco case set with the tested GraphQL saved-search
    (account + product + subject; planv3.md §3a), capped at
    ``max_portal_results`` most-recently-modified cases, and builds the case
    projection **straight from that one light query** - no per-case case(id)
    hydration. The light query already carries every field the case-assignment
    path needs (account, severity, status, subject, product, dates); the richer
    fields the light query cannot supply (description, tags, product_version,
    owner) are left blank / "in progress" and backfilled later by
    get_case_details. Results are stored in both PostgreSQL and Redis. Replaces
    the v1 Solr tag-glob search.

    Args:
        cfg: Configuration dictionary containing API credentials, the
            ``saved_search`` selection, and API endpoints

    Returns:
        None. Results are cached in Redis under the 'cases' key.
    """
    if not cfg.get("saved_search"):
        logging.error("no saved_search configured; skipping case selection")
        return

    token = libtelco5g.get_token(cfg["offline_token"])

    logging.warning("selecting cases via the GraphQL saved-search")
    start = time.time()
    # Cap the selection at max_portal_results, mirroring the v1 rows= cap. The
    # saved-search is ordered LastModifiedDate DESC, so this yields the N latest.
    limit = _int_or_none(cfg.get("max_portal_results"))
    selected = _fetch_saved_search_cases(cfg, token, limit=limit)

    cases = {}
    for entry in selected:
        case = entry["caseNumber"]
        cases[case] = {
            # owner / tags / product_version / description are not carried by the
            # light saved-search query; leave them blank/placeholder so the
            # assignment path (which does not need them) works now, and let
            # get_case_details backfill the real values later.
            "owner": None,
            "severity": entry["severity"],
            "account": entry["account"],
            "problem": entry["problem"],
            # v3 status vocabulary can differ from v1 - remap before anything
            # buckets on the string downstream (planv3.md §6.4).
            "status": remap_case_status(entry["status"]),
            "createdate": _normalize_ts(entry["createdate"]),
            "last_update": _normalize_ts(entry["last_update"]),
            "description": _PENDING_VALUE,
            # Product.Name from the UIAPI selection already includes the version
            # (unlike HydraCase, which splits them), so store it as-is.
            "product": entry["product"],
            "product_version": None,
        }

    end = time.time()
    logging.warning("selected %s cases in %s seconds", len(cases), end - start)

    try:
        load_cases_postgres(cases)
    except Exception as e:
        logging.error("Failed to load cases to Postgres: %s ", e)

    libtelco5g.redis_set("cases", json.dumps(cases))


def get_escalations(cfg, cases):
    """Get cases that have been escalated by querying the escalations JIRA board

    Args:
        cfg: generated by utils.set_cfg()
        cases: cases returned from portal API using the configured query

    Returns:
        list: open Jira cards that have been escalated
    """
    if (
        cases is None
        or cfg["jira_escalations_project"] is None
        or cfg["jira_escalations_label"] is None
    ):
        return None

    logging.warning("getting escalated cases from JIRA")
    jira_conn = libtelco5g.jira_connection(cfg)
    max_cards = cfg["max_jira_results"]
    project = libtelco5g.get_project_id(jira_conn, cfg["jira_escalations_project"])
    escalations_label = cfg["jira_escalations_label"]
    jira_query = (
        f"project = {project.id} AND labels = "
        f'"{escalations_label}" AND status != "Closed"'
    )

    # Use expand to decrypt the restricted custom fields
    # Custom field: SFDC Case Links in escalations proj.
    escalated_cards = jira_conn.search_issues(
        jira_query, 0, max_cards, fields=["customfield_10979"], expand="renderedFields"
    )
    escalations = []
    for card in escalated_cards:
        # Custom field: SFDC Case Links in escalations proj.
        case = card.renderedFields.customfield_10979
        if case is not None:
            escalations.append(case)
    return escalations


def get_cards(cfg, self=None, background=False):
    """Pull the latest information from the JIRA cards

    Retrieves all JIRA cards matching the configured query, processes each
    card to extract relevant information, and caches the results. Optionally
    supports background processing with progress updates.

    Args:
        cfg: Configuration dictionary containing JIRA connection parameters
            and query settings
        self: Optional Celery task instance for progress updates when running
            in background mode. Defaults to None.
        background: Boolean indicating whether to report progress updates for
            background processing. Defaults to False.

    Returns:
        dict: Dictionary with key 'cards cached' containing the count of
            cached cards
    """

    # Get cached data
    cached_data = _get_cached_data()
    cases, bugs, issues, escalations, details = cached_data

    # Get JIRA connection and card list
    jira_conn = libtelco5g.jira_connection(cfg)
    card_list = _get_jira_cards_list(cfg, jira_conn)

    # Process each card
    jira_cards = {}
    time_now = datetime.datetime.now(datetime.timezone.utc)

    for index, card in enumerate(card_list):
        if background:
            _update_progress(self, index, len(card_list))

        try:
            card_data = _build_card_data(
                card,
                cases,
                bugs,
                issues,
                escalations,
                details,
                time_now,
                cfg,
            )
            if card_data:
                jira_cards[card.key] = card_data
                load_jira_card_postgres(cases, card_data["case_number"], card)

        except Exception as e:
            logging.warning("Error processing card %s: %s", card, str(e))
            continue

    # Cache the results
    libtelco5g.redis_set("cards", json.dumps(jira_cards))
    libtelco5g.redis_set(
        "timestamp", json.dumps(str(datetime.datetime.now(datetime.timezone.utc)))
    )
    return {"cards cached": len(jira_cards)}


def _get_cached_data():
    # Generated by: Cursor
    """Get all cached data needed for card processing

    Retrieves cached data from Redis including cases, bugs, issues,
    escalations, and case details.

    Returns:
        tuple: A 5-tuple containing (cases, bugs, issues, escalations, details)
            where each element may be None if not cached
    """
    cases = libtelco5g.redis_get("cases")
    bugs = libtelco5g.redis_get("bugs")
    issues = libtelco5g.redis_get("issues")
    escalations = libtelco5g.redis_get("escalations")
    details = libtelco5g.redis_get("details")
    return cases, bugs, issues, escalations, details


def _execute_jira_query_with_retry(jira_conn, jira_query, cfg, max_results):
    # Generated by: Cursor
    """Execute JIRA query with automatic retry on authentication errors

    Attempts to execute a JIRA query and automatically reconnects if a
    JIRAError occurs (typically 401 authentication errors).

    Args:
        jira_conn: Active JIRA connection object
        jira_query: JQL query string to execute
        cfg: Configuration dictionary for reconnection if needed
        max_results: Maximum number of results to return

    Returns:
        list: list of JIRA issue objects matching the query
    """
    try:
        return jira_conn.search_issues(jira_query, 0, max_results)
    except JIRAError:
        logging.warning("JIRA Exception. Possible 401. Reconnecting.....")
        jira_conn = libtelco5g.jira_connection(cfg)
        return jira_conn.search_issues(jira_query, 0, max_results)


def _get_jira_cards_list(cfg, jira_conn):
    # Generated by: Cursor
    """Get the list of JIRA cards based on configuration

    Constructs a JQL query based on configuration settings (sprint or project)
    and retrieves matching JIRA cards.

    Args:
        cfg: Configuration dictionary containing project, board, sprint, and
            query parameters
        jira_conn: Active JIRA connection object

    Returns:
        card_list: list of JIRA card objects matching the query
    """
    max_cards = cfg["max_jira_results"]
    project = libtelco5g.get_project_id(jira_conn, cfg["project"])
    board = libtelco5g.get_board_id(jira_conn, cfg["board"])

    if cfg["sprintname"] and cfg["sprintname"] != "":
        sprint = libtelco5g.get_latest_sprint(jira_conn, board.id, cfg["sprintname"])
        jira_query = (
            "sprint=" + str(sprint.id) + ' AND labels = "' + cfg["jira_query"] + '"'
        )
        logging.warning("sprint: %s", sprint)
    else:
        jira_query = (
            "project=" + str(project.id) + ' AND labels = "' + cfg["jira_query"] + '"'
        )

    logging.warning("pulling cards from jira")
    card_list = _execute_jira_query_with_retry(jira_conn, jira_query, cfg, max_cards)

    return card_list


def _update_progress(self, current, total):
    # Generated by: Cursor
    """Update task progress for background processing

    Updates the Celery task state to report progress during background
    card refresh operations.

    Args:
        self: Celery task instance
        current: Current progress count (cards processed)
        total: Total number of cards to process
    """
    self.update_state(
        state="PROGRESS",
        meta={
            "current": current,
            "total": total,
            "status": "Refreshing Cards in Background...",
        },
    )


def _build_card_data(card, cases, bugs, issues, escalations, details, time_now, cfg):
    # Generated by: Cursor
    """Build complete card data for a single JIRA card

    Processes a JIRA card and aggregates data from multiple sources including
    case information, bugzilla details, escalation status, and labels.

    Args:
        card: JIRA card object to process
        cases: Dictionary of cached case data
        bugs: Dictionary of cached bugzilla data
        issues: Dictionary of cached JIRA issues
        escalations: List of escalated case numbers
        details: Dictionary of cached case detail information
        time_now: Current datetime for calculating days open
        cfg: Configuration dictionary

    Returns:
        dict: Complete card data dictionary with all relevant fields, or None
            if the card cannot be processed
    """
    # Extract case number from summary
    case_number = card.fields.summary.split(":")[0]
    if not re.match("[0-9]{8}", case_number):
        logging.warning("error parsing case number for (%s)", card)
        return None

    if not case_number or case_number not in cases.keys():
        logging.warning("card isn't associated with a case. discarding (%s)", card)
        return None

    # Get comments
    comments = _get_card_comments(card.fields.comment.comments)

    # Get assignee and contributor info
    assignee = _get_assignee_info(card)
    contributor = _get_contributor_info(card)

    # Get case-related data
    case_data = cases[case_number]
    tags = case_data.get("tags", [])

    # Get bug info
    bugzilla = _get_bug_info(case_number, case_data, bugs)

    # Get issues info
    case_issues = issues.get(case_number) if issues else None

    # Get escalation info
    escalation_info = _get_escalation_info(
        case_number, escalations, case_issues, card.fields.labels, cfg
    )

    # Get case details
    case_detail_info = _get_case_detail_info(case_number, details)

    # Get label-based flags
    label_flags = _get_label_flags(card.fields.labels, escalation_info["escalated"])

    # Build the complete card data
    return {
        "card_status": libtelco5g.status_map[card.fields.status.name],
        "card_created": card.fields.created,
        "account": case_data["account"],
        "summary": case_data["problem"],
        "description": case_data["description"],
        "comments": comments,
        "assignee": assignee,
        "contributor": contributor,
        "case_number": case_number,
        "tags": tags,
        "labels": card.fields.labels,
        "bugzilla": bugzilla,
        "issues": case_issues,
        "severity": re.search(r"[a-zA-Z]+", case_data["severity"]).group(),
        "priority": card.fields.priority.name,
        "escalated": escalation_info["escalated"],
        "escalated_link": escalation_info["escalated_link"],
        "potential_escalation": label_flags["potential_escalation"],
        "product": case_data["product"],
        "case_status": case_data["status"],
        "crit_sit": case_detail_info["crit_sit"],
        "group_name": case_detail_info["group_name"],
        "case_updated_date": datetime.datetime.strftime(
            format_date(case_data["last_update"]),
            "%Y-%m-%d %H:%M",
        ),
        "case_days_open": (
            time_now.replace(tzinfo=None) - format_date(case_data["createdate"])
        ).days,
        "case_created": case_data["createdate"],
        "notified_users": case_detail_info["notified_users"],
        "relief_at": case_detail_info["relief_at"],
        "resolved_at": case_detail_info["resolved_at"],
        "daily_telco": label_flags["daily_telco"],
    }


def _get_card_comments(comments):
    # Generated by: Cursor
    """Extract and format card comments

    Processes JIRA comment objects and formats them for display.

    Args:
        comments: List of JIRA comment objects

    Returns:
        list: List of tuples containing (formatted_body, timestamp) for each
            comment
    """
    card_comments = []
    for comment in comments:
        body = format_comment(comment)
        tstamp = comment.updated
        card_comments.append((body, tstamp))
    return card_comments


def _get_assignee_info(issue):
    # Generated by: Cursor
    """Extract assignee information from JIRA issue

    Retrieves the assignee details from a JIRA issue, handling cases where
    no assignee is set.

    Args:
        issue: JIRA issue object

    Returns:
        dict: Dictionary containing 'displayName', 'key', and 'name' fields.
            All values are None if no assignee is set.
    """
    assignee = {"displayName": None, "accountId": None, "emailAddress": None}
    if issue.fields.assignee:
        assignee = {
            "displayName": issue.fields.assignee.displayName,
            "accountId": issue.fields.assignee.accountId,
            "emailAddress": issue.fields.assignee.emailAddress,
        }
    return assignee


def _get_contributor_info(issue):
    # Generated by: Cursor
    """Extract contributor information from JIRA issue

    Retrieves the list of contributing engineers from a JIRA issue's custom
    field.

    Args:
        issue: JIRA issue object

    Returns:
        list: List of dictionaries, each containing 'displayName', 'key', and
            'name' for each contributor. Empty list if no contributors.
    """
    contributor = []
    if issue.fields.customfield_10466:  # Contributors custom field
        for engineer in issue.fields.customfield_10466:  # Contributors custom field
            contributor.append(
                {
                    "displayName": engineer.displayName,
                    "accountId": engineer.accountId,
                    "emailAddress": engineer.emailAddress,
                }
            )
    return contributor


def _get_bug_info(case_number, case_data, bugs):
    # Generated by: Cursor
    """Get bugzilla information for the case

    Retrieves cached bugzilla data for a specific case number.

    Args:
        case_number: The case number to look up
        case_data: Dictionary containing the case's data
        bugs: Dictionary of cached bugzilla data keyed by case number

    Returns:
        dict: Bugzilla information if available, None otherwise
    """
    if "bug" in case_data.keys() and bugs is not None and case_number in bugs.keys():
        return bugs[case_number]
    return None


def _get_escalation_info(case_number, escalations, case_issues, labels, cfg):
    # Generated by: Cursor
    """Determine escalation status and links

    Checks if a case has been escalated and finds the associated escalation
    JIRA link if available.

    Args:
        case_number: The case number to check
        escalations: List of escalated case numbers
        case_issues: List of JIRA issues associated with the case
        labels: List of JIRA labels from the card
        cfg: Configuration dictionary containing escalation project name

    Returns:
        dict: Dictionary with 'escalated' (bool) and 'escalated_link' (str or
            None) keys
    """
    escalated = bool(escalations and case_number in escalations)
    escalated_link = None

    if case_issues:
        for case_issue in case_issues:
            if cfg["jira_escalations_project"] in case_issue["id"]:
                escalated_link = case_issue["url"]
                break

    return {"escalated": escalated, "escalated_link": escalated_link}


def _get_case_detail_info(case_number, details):
    # Generated by: Cursor
    """Get case detail information from cache

    Retrieves detailed case information including CritSit status, group name,
    and notification details.

    Args:
        case_number: The case number to look up
        details: Dictionary of cached case details keyed by case number

    Returns:
        dict: Dictionary containing 'crit_sit', 'group_name', 'notified_users',
            'relief_at', and 'resolved_at' keys. Returns default values if case
            not found.
    """
    if case_number in details.keys():
        return {
            "crit_sit": details[case_number]["crit_sit"],
            "group_name": details[case_number]["group_name"],
            "notified_users": details[case_number]["notified_users"],
            "relief_at": details[case_number]["relief_at"],
            "resolved_at": details[case_number]["resolved_at"],
        }
    else:
        return {
            "crit_sit": False,
            "group_name": None,
            "notified_users": [],
            "relief_at": None,
            "resolved_at": None,
        }


def _get_label_flags(labels, escalated):
    # Generated by: Cursor
    """Extract boolean flags based on JIRA labels

    Parses JIRA labels to determine special status flags for the card.

    Args:
        labels: List of JIRA label strings
        escalated: Boolean indicating if the case is already escalated

    Returns:
        dict: Dictionary with 'potential_escalation' and 'daily_telco' boolean
            flags
    """
    potential_escalation = "PotentialEscalation" in labels and not escalated
    daily_telco = "Daily_Telco_OCP" in labels

    return {"potential_escalation": potential_escalation, "daily_telco": daily_telco}


def get_case_details(cfg):
    """Caches CritSit and CaseGroup from open cases

    Retrieves detailed information for each open case from the Red Hat Portal
    API including CritSit status, group names, notified users, and associated
    bugzillas. Results are cached in Redis.

    Args:
        cfg: Configuration dictionary containing API credentials and endpoints

    Returns:
        None. Results are cached in Redis under 'details' and 'case_bz' keys.
    """
    cases = libtelco5g.redis_get("cases")
    if cases is None:
        libtelco5g.redis_set("details", json.dumps(None))
        libtelco5g.redis_set("case_bz", json.dumps(None))
        return

    bz_dict = {}
    token = libtelco5g.get_token(cfg["offline_token"])
    url = cfg["graphql_api"]
    headers = make_graphql_headers(token)
    case_details = {}
    logging.warning("getting all bugzillas and case details")

    # Hydrate the open cases concurrently (same reason as get_cases: sequential
    # case(id) round-trips over a few hundred cases blow the request timeout).
    # The Redis/Postgres writes below stay on this thread to avoid touching the
    # DB layer from worker threads.
    open_cases = [case for case in cases if cases[case]["status"] != "Closed"]
    hydrated, headers = _hydrate_cases_parallel(cfg, url, headers, open_cases)

    for case in open_cases:
        case_json = hydrated.get(case)
        if not case_json:
            continue

        case_details[case] = {
            # crit_sit and notified_users are populated on the GraphQL
            # HydraCase (live-verified 2026-09-18) - unlike the empty v3 REST
            # payload, so they are active again (planv3.md §3b/§3e).
            "crit_sit": case_json.get("critSit", False),
            "group_name": case_json.get("groupName", None),
            "notified_users": case_json.get("notifiedUsers") or [],
            # reliefAt / resolvedAt do not exist on HydraCase (dead reads in
            # v1 too - no regression).
            "relief_at": None,
            "resolved_at": None,
        }
        if "bug" in cases[case]:
            # HydraCase.bugzillas is a list of id strings; wrap them so the
            # bugzilla detail pass (get_bz_details) keeps its dict contract.
            bz_dict[case] = [
                {"bugzillaNumber": bug} for bug in case_json.get("bugzillas") or []
            ]

        api_comments = case_json.get("comments", [])
        if api_comments:
            try:
                case_created_date = format_date(cases[case]["createdate"])
                load_comments_postgres(case, case_created_date, api_comments)
            except Exception as e:
                logging.error("Failed to load comments for case %s: %s", case, e)

    libtelco5g.redis_set("details", json.dumps(case_details))
    libtelco5g.redis_set("case_bz", json.dumps(bz_dict))


def get_bz_details(cfg):
    """Get details about Bugzillas from API

    Queries the Bugzilla API to retrieve detailed information about bugs
    associated with cases, including target release, assignee, last change
    time, and other metadata. Results are cached in Redis.

    Args:
        cfg: Configuration dictionary containing Bugzilla API key

    Returns:
        None. Results are cached in Redis under the 'bugs' key.
    """
    logging.warning("getting additional info via bugzilla API")
    bz_dict = libtelco5g.redis_get("case_bz")
    if bz_dict is None or cfg["bz_key"] is None or cfg["bz_key"] == "":
        libtelco5g.redis_set("bugs", json.dumps(None))
        return

    bz_url = "bugzilla.redhat.com"
    bz_api = bugzilla.Bugzilla(bz_url, api_key=cfg["bz_key"])
    for case in bz_dict:
        for bug in bz_dict[case]:
            try:
                bugs = bz_api.getbug(bug["bugzillaNumber"])
            except xmlrpc.client.Fault:
                logging.warning(
                    "error retrieving bug %s - restricted?", bug["bugzillaNumber"]
                )
                bugs = None
            if bugs:
                bug["target_release"] = bugs.target_release
                bug["assignee"] = bugs.assigned_to
                bug["last_change_time"] = datetime.datetime.strftime(
                    datetime.datetime.strptime(
                        str(bugs.last_change_time), "%Y%m%dT%H:%M:%S"
                    ),
                    "%Y-%m-%d",
                )  # convert from xmlrpc.client.DateTime to str and reformat
                bug["internal_whiteboard"] = bugs.internal_whiteboard
                bug["qa_contact"] = bugs.qa_contact
                bug["severity"] = bugs.severity
            else:
                bug["target_release"] = ["unavailable"]
                bug["assignee"] = "unavailable"
                bug["last_change_time"] = "unavailable"
                bug["internal_whiteboard"] = "unavailable"
                bug["qa_contact"] = "unavailable"
                bug["severity"] = "unavailable"

    libtelco5g.redis_set("bugs", json.dumps(bz_dict))


def get_issue_details(cfg):
    """Cache issues associated with cases

    Retrieves all JIRA issues associated with open cases from the Red Hat
    Portal API and JIRA, extracting detailed information for each issue.
    Results are cached in Redis.

    Args:
        cfg: Configuration dictionary containing API credentials and JIRA
            connection parameters

    Returns:
        None. Results are cached in Redis under the 'issues' key.
    """
    logging.warning("caching issues")

    cases = libtelco5g.redis_get("cases")
    if cases is None:
        libtelco5g.redis_set("issues", json.dumps(None))
        return

    # Setup authentication and JIRA connection
    token, headers, jira_conn = _setup_issue_processing(cfg)

    # Process issues for all open cases
    jira_issues = {}
    open_cases = [case for case in cases if cases[case]["status"] != "Closed"]

    for case in open_cases:
        try:
            case_issues = _process_case_issues(case, cfg, token, headers, jira_conn)
            if case_issues:
                jira_issues[case] = case_issues
        except Exception as e:
            logging.warning("Error processing issues for case %s: %s", case, str(e))
            continue

    # Cache the results
    libtelco5g.redis_set("issues", json.dumps(jira_issues))
    logging.warning("issues cached")


def _setup_issue_processing(cfg):
    # Generated by: Cursor
    """Setup authentication and JIRA connection for issue processing

    Initializes the necessary authentication tokens and JIRA connection
    objects for processing issues.

    Args:
        cfg: Configuration dictionary containing API credentials and JIRA
            connection parameters

    Returns:
        tuple: A 3-tuple containing (token, headers, jira_conn) for API access
    """
    # Reuse the existing libtelco5g setup pattern for consistency
    token = libtelco5g.get_token(cfg["offline_token"])
    headers = make_headers(token)
    jira_conn = libtelco5g.jira_connection(cfg)

    return token, headers, jira_conn


def _process_case_issues(case, cfg, token, headers, jira_conn):
    # Generated by: Cursor
    """Process all issues for a specific case

    Retrieves issues from the API for a case and processes each one to extract
    detailed JIRA information.

    Args:
        case: Case number to process
        cfg: Configuration dictionary
        token: Authentication token for Red Hat Portal API
        headers: HTTP headers for API requests
        jira_conn: Active JIRA connection object

    Returns:
        list: List of processed issue dictionaries, or None if no valid issues
            found
    """
    # Get issues from API
    issues_data = _get_case_issues_from_api(case, cfg, token, headers)
    if not issues_data:
        return None

    case_issues = []
    for issue in issues_data:
        if "title" in issue.keys():
            try:
                processed_issue = _process_single_jira_issue(issue, jira_conn)
                if processed_issue:
                    case_issues.append(processed_issue)
            except JIRAError:
                logging.warning("Can't access %s", issue["resourceKey"])
                continue
            except Exception as e:
                logging.warning(
                    "Error processing issue %s: %s",
                    issue.get("resourceKey", "unknown"),
                    str(e),
                )
                continue

    return case_issues if case_issues else None


def _get_case_issues_from_api(case, cfg, token, headers):
    # Generated by: Cursor
    """Get issues for a case from the Red Hat API

    Makes an API request to retrieve all JIRA issues associated with a
    specific case. Handles 401 authentication errors with retry.

    Args:
        case: Case number to query
        cfg: Configuration dictionary containing API endpoint
        token: Authentication token for Red Hat Portal API
        headers: HTTP headers for API requests

    Returns:
        list: List of issue data from API, or None if no issues found or
            request fails
    """
    issues_url = f"{cfg['redhat_api']}/cases/{case}/jiras"
    issues = requests.get(issues_url, headers=headers)

    # Handle 401 authorization errors
    if issues.status_code == 401:
        token = libtelco5g.get_token(cfg["offline_token"])
        headers = make_headers(token)
        issues = requests.get(issues_url, headers=headers)

    if issues.status_code == 200 and len(issues.json()) > 0:
        return issues.json()

    return None


def _process_single_jira_issue(issue, jira_conn):
    # Generated by: Cursor
    """Process a single JIRA issue and extract all relevant fields

    Retrieves full details for a JIRA issue and extracts all relevant fields
    including status, QA contact, severity, assignee, and more.

    Args:
        issue: Issue data dictionary from Red Hat API containing resourceKey
            and other basic info
        jira_conn: Active JIRA connection object

    Returns:
        dict: Complete issue data dictionary with all extracted fields, or
            None if issue cannot be accessed
    """
    try:
        bug = jira_conn.issue(issue["resourceKey"], expand="renderedFields")
    except JIRAError:
        logging.warning("Can't access %s", issue["resourceKey"])
        return None

    # Extract all JIRA fields
    jira_fields = _extract_jira_fields(bug)

    # Build the complete issue data
    return {
        "id": issue["resourceKey"],
        "url": issue["resourceURL"],
        "title": issue["title"],
        "status": issue["status"],
        "updated": datetime.datetime.strftime(
            format_date(str(issue["lastModifiedDate"])),
            "%Y-%m-%d",
        ),
        **jira_fields,
    }


def _extract_jira_fields(bug):
    # Generated by: Cursor
    """Extract all relevant fields from a JIRA bug

    Extracts QA contact, severity, issue type, assignee, fix versions,
    priority, and private keywords from a JIRA bug object.

    Args:
        bug: JIRA issue/bug object

    Returns:
        dict: Dictionary containing all extracted field values
    """
    fields = {}

    # QA contact
    fields["qa_contact"] = _extract_qa_contact(bug)

    # Severity
    fields["jira_severity"] = _extract_jira_severity(bug)

    # Issue type
    fields["jira_type"] = _extract_jira_type(bug)

    # Assignee
    fields["assignee"] = _extract_assignee_email(bug)

    # Fix versions (target release)
    fields["fix_versions"] = _extract_fix_versions(bug)

    # Priority
    fields["priority"] = _extract_priority(bug)

    # Private keywords
    fields["private_keywords"] = _extract_private_keywords(bug)

    return fields


def _extract_qa_contact(bug):
    # Generated by: Cursor
    """Extract QA contact from JIRA bug

    Retrieves the QA contact email address from a JIRA bug's custom field.

    Args:
        bug: JIRA issue/bug object

    Returns:
        str: QA contact email address, or None if not set
    """
    try:
        return bug.fields.customfield_10470.emailAddress  # QA Contact custom field
    except AttributeError:
        return None


def _extract_jira_severity(bug):
    # Generated by: Cursor
    """Extract severity from JIRA bug

    Retrieves the severity value from a JIRA bug's custom field.

    Args:
        bug: JIRA issue/bug object

    Returns:
        str: Severity value, or None if not set
    """
    try:
        return bug.fields.customfield_10840.value  # Severity custom field
    except AttributeError:
        return None


def _extract_jira_type(bug):
    # Generated by: Cursor
    """Extract issue type from JIRA bug

    Retrieves the issue type name (e.g., Bug, Story, Task) from a JIRA bug.

    Args:
        bug: JIRA issue/bug object

    Returns:
        str: Issue type name, or None if not set
    """
    try:
        return bug.fields.issuetype.name
    except AttributeError:
        return None


def _extract_assignee_email(bug):
    # Generated by: Cursor
    """Extract assignee email from JIRA bug

    Retrieves the email address of the assignee from a JIRA bug.

    Args:
        bug: JIRA issue/bug object

    Returns:
        str: Assignee email address, or None if not assigned
    """
    if bug.fields.assignee is not None:
        return bug.fields.assignee.emailAddress
    return None


def _extract_fix_versions(bug):
    # Generated by: Cursor
    """Extract fix versions from JIRA bug

    Retrieves the list of fix versions (target releases) from a JIRA bug.

    Args:
        bug: JIRA issue/bug object

    Returns:
        list: List of version name strings, or None if no fix versions set
    """
    if len(bug.fields.fixVersions) > 0:
        return [version.name for version in bug.fields.fixVersions]
    return None


def _extract_priority(bug):
    # Generated by: Cursor
    """Extract priority from JIRA bug

    Retrieves the priority name from a JIRA bug.

    Args:
        bug: JIRA issue/bug object

    Returns:
        str: Priority name, or None if not set
    """
    if bug.fields.priority:
        return bug.fields.priority.name
    return None


def _extract_private_keywords(bug):
    # Generated by: Cursor
    """Extract private keywords from JIRA bug

    Retrieves the list of private keywords from a JIRA bug's custom field.

    Args:
        bug: JIRA issue/bug object

    Returns:
        list: List of private keyword strings, or None if not set or empty
    """
    try:
        private_keywords_raw = (
            bug.renderedFields.customfield_11087
        )  # RH Private Keywords
    except AttributeError:
        return None

    if private_keywords_raw is not None and len(private_keywords_raw) > 0:
        # Private keywords are stored as a comma-separated list of strings
        # like "Telco:Priority-1,Priority-2"
        return [
            private_keyword.strip()
            for private_keyword in private_keywords_raw.split(",")
        ]
    return None


def get_stats():
    """Generate and cache daily statistics

    Generates statistics for the current day and adds them to the cached
    historical stats data. The stats are keyed by date in YYYY-MM-DD format.

    Returns:
        None. Results are cached in Redis under the 'stats' key.
    """
    logging.warning("caching {} stats")
    all_stats = libtelco5g.redis_get("stats")
    new_stats = libtelco5g.generate_stats()
    tstamp = datetime.datetime.now(datetime.timezone.utc)
    today = tstamp.strftime("%Y-%m-%d")
    stats = {today: new_stats}
    all_stats.update(stats)
    libtelco5g.redis_set("stats", json.dumps(all_stats))
