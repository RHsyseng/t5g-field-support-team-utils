"""graphql.py: Red Hat GraphQL (Hydra v3) HTTP client - headers and request execution"""

import json
import logging
import random
import time

import requests

# Transient GraphQL upstream failures worth retrying.
_GRAPHQL_TRANSIENT_MARKERS = (
    "503",
    "502",
    "504",
    "Service Unavailable",
    "SUBREQUEST_HTTP_ERROR",
    "unsupported content-type",
)


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
