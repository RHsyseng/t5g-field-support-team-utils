"""graphql.py: Red Hat GraphQL (Hydra v3) client for case selection and population"""

import json
import logging
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from dateutil import parser as date_parser

from t5gweb import libtelco5g
from t5gweb.utils import int_or_none

# Selection query. Account name is pulled inline via the
# RedHatSupportAccount parent relationship so no separate /v1/accounts/{ref}
# lookup is needed. This light query carries every field the case-assignment
# path needs (account, severity, status, subject, product, dates), so get_cases
# builds the projection straight from it - no per-case case(id) population. The
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
# normalize to this form at ingest to preserve the stored contract.
_CANONICAL_TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# Case detail / population query - the GraphQL twin of GET /v3/cases/{n}
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

# Transient GraphQL upstream failures worth retrying.
_GRAPHQL_TRANSIENT_MARKERS = (
    "503",
    "502",
    "504",
    "Service Unavailable",
    "SUBREQUEST_HTTP_ERROR",
    "unsupported content-type",
)

# Number of concurrent case(id) population requests. The casesFilter batch
# endpoint ignores the caseNumbers filter on this deployment, so population is one
# case(id) round-trip per case; doing them sequentially blows the request/worker
# timeout on a few hundred cases, so fan them out over a small thread pool. Kept
# modest because too much concurrency makes the gateway shed load with empty
# responses (and init-cache + the web worker can populate at the same time, so the
# effective concurrency is a multiple of this). Override with the
# ``graphql_population_workers`` env var if the endpoint tolerates more.
_MAX_POPULATE_WORKERS = int_or_none(os.environ.get("graphql_population_workers")) or 8


def make_graphql_headers(token):
    """Builds the HTTP headers for Red Hat GraphQL API requests

    The GraphQL endpoint needs a JSON content type and the Apollo client
    identification headers used by the saved-search client; the plain
    REST headers (Accept + Authorization only) are not sufficient.

    Args:
        token(str): A valid bearer token

    Returns:
        dict: valid headers for use with the requests module
    """
    return {
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip",
        "Authorization": "Bearer " + token,
        "apollographql-client-name": "t5g-field-support-team-utils",
        "apollographql-client-version": "1.0",
    }


# t5gweb.organize_cards only has {"Waiting on Red Hat", "Waiting on Customer",
# "Closed"} columns and KeyErrors on anything else, so collapse the whole Status
# picklist to those three buckets at ingest: closed -> "Closed", any customer-side
# wait -> "Waiting on Customer", everything else (Red Hat is the active party) ->
# "Waiting on Red Hat".
def remap_case_status(status):
    """Collapse a GraphQL case status into a display bucket.

    Args:
        status(str): the Status value returned by the GraphQL API.

    Returns:
        str: one of "Closed", "Waiting on Customer", or "Waiting on Red Hat".
            An empty/missing status defaults to "Waiting on Red Hat" so the
            table view never KeyErrors.
    """
    lowered = (status or "").lower()
    if "closed" in lowered:
        return "Closed"
    if "customer" in lowered:
        return "Waiting on Customer"
    return "Waiting on Red Hat"


def normalize_timestamp(value):
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


def build_where(saved_search, open_only=True):
    """Build the GraphQL ``where`` filter from the saved-search config.

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
    product_block = (
        {"or": [{"Product": {"Name": {"like": f"%{p}%"}}} for p in products]}
        if products
        else None
    )

    branches = []
    if subject_contains:
        branches.append(
            {"or": [{"Subject": {"like": f"%{s}%"}} for s in subject_contains]}
        )
    for branch in saved_search.get("account_branches", []):
        accounts = branch["accounts"]
        if len(accounts) == 1:
            account_block = {"Account_Number__c": {"eq": accounts[0]}}
        else:
            account_block = {"Account_Number__c": {"in": list(accounts)}}
        if branch.get("product") and product_block:
            branches.append({"and": [account_block, product_block]})
        else:
            branches.append(account_block)

    where = {"or": branches}
    if open_only:
        where = {"and": [{"IsClosed": {"eq": False}}, where]}
    return where


def graphql_post(url, headers, query, variables, timeout=180, retries=5):
    """POST a GraphQL query, retrying transient upstream failures.

    Args:
        url: the GraphQL endpoint.
        headers: request headers (see make_graphql_headers).
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
                # the case. The real fix is fewer requests: keep population
                # concurrency modest (see _MAX_POPULATE_WORKERS).
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


def fetch_saved_search_cases(cfg, token, limit=None):
    """Select the telco case set via the Red Hat GraphQL saved-search.

    Cursor-pages the account+product+subject query and
    returns the light case nodes; each is populated with the detail endpoint
    later to build the full projection. The query is ordered by
    ``LastModifiedDate DESC``, so when ``limit`` is set the returned list is the
    ``limit`` most-recently-modified matches.

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
        data = graphql_post(
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


def populate_cases_parallel(cfg, url, headers, case_numbers):
    """Populate many cases concurrently via the GraphQL ``case(id)`` query.

    Fans ``case_numbers`` out over a bounded thread pool (each a case(id)
    round-trip). On a per-case failure the access token is
    refreshed once - serialized under a lock and collapsed so a burst of
    simultaneous auth failures triggers a single refresh, not one per case - and
    the case retried once, mirroring the sequential ``_populate_case_with_reauth``.

    Args:
        cfg: configuration dictionary (needs ``offline_token``).
        url: the GraphQL endpoint.
        headers: current GraphQL request headers.
        case_numbers: list of case numbers to populate.

    Returns:
        tuple: ``(populated, headers)`` where ``populated`` maps case number to its
            HydraCase dict (cases that never populated are omitted), and
            ``headers`` are the (possibly refreshed) headers for reuse.
    """
    lock = threading.Lock()
    state = {"headers": headers}

    def worker(case_number):
        used = state["headers"]
        try:
            data = graphql_post(
                url, used, GRAPHQL_CASE_DETAIL_QUERY, {"id": case_number}
            )
            return case_number, (data.get("data") or {}).get("case")
        except Exception as exc:
            with lock:
                # Only refresh if nobody else already did since this worker's
                # attempt, so a stampede of failures costs one token exchange.
                if state["headers"] is used:
                    logging.warning(
                        "re-authenticating after population error for %s: %s",
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
                data = graphql_post(
                    url, retry_headers, GRAPHQL_CASE_DETAIL_QUERY, {"id": case_number}
                )
                return case_number, (data.get("data") or {}).get("case")
            except Exception as exc2:
                logging.warning(
                    "could not populate case %s via GraphQL: %s", case_number, exc2
                )
                return case_number, None

    populated = {}
    with ThreadPoolExecutor(max_workers=_MAX_POPULATE_WORKERS) as executor:
        for case_number, case_json in executor.map(worker, case_numbers):
            if case_json:
                populated[case_number] = case_json
    return populated, state["headers"]
