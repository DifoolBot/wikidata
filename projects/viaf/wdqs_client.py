import time

import pywikibot as pwb
from pywikibot.data import sparql

# A failed WDQS query is retried a few times before the item is given up on.
# Both symptoms seen in practice are transient: 429 (the service is throttling
# us - we query it once per record) and 5xx (the service is struggling, common
# while a large QuickStatements import is running).
MAX_ATTEMPTS = 4
FIRST_BACKOFF_SECS = 5
MAX_BACKOFF_SECS = 120
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


class WdqsQueryError(Exception):
    """A WDQS query did not complete: throttled, server error, or an unparsable
    reply.

    Raised rather than returning None, because callers cannot otherwise tell a
    query that failed from one that legitimately matched no rows. Treating the
    former as the latter silently turns a lookup into a false negative - see
    ViafBot.get_duplicate_qids, where it would mean "no duplicate items exist".

    The message starts with 'WDQS query failed' so the CLEAN_UP procedure can
    recognise it as transient and mark the item for a retry.
    """


def _status_of(query_object) -> int | None:
    """HTTP status of the last response, if there was one."""
    response = getattr(query_object, "last_response", None)
    return getattr(response, "status_code", None)


def _retry_after_secs(query_object) -> float | None:
    """The server's own Retry-After, when it sends one (429s often do)."""
    response = getattr(query_object, "last_response", None)
    headers = getattr(response, "headers", None) or {}
    value = headers.get("Retry-After")
    if value is None:
        return None
    try:
        return float(value)  # delta-seconds; the HTTP-date form is not used here
    except (TypeError, ValueError):
        return None


def query_wdqs(query: str, retry_counter: int = 3) -> list:
    """Run a SPARQL query against WDQS and return its (possibly empty) rows.

    Transient failures are retried with backoff, honouring Retry-After when the
    server sends one. Raises WdqsQueryError if the query still did not complete,
    so a caller never mistakes a failure for an empty result.
    """
    query_object = sparql.SparqlQuery(max_retries=retry_counter)
    backoff = FIRST_BACKOFF_SECS

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            payload = query_object.query(query=query)
        except Exception as ex:
            reason = f"{type(ex).__name__}: {ex}"
        else:
            if payload is not None:
                try:
                    return payload["results"]["bindings"]
                except (KeyError, TypeError) as ex:
                    raise WdqsQueryError(
                        f"WDQS query failed: unexpected response: {ex}"
                    ) from ex
            # pywikibot returns None for an empty or undecodable body, which is
            # what a 429 or 5xx error page looks like. A query that merely
            # matched nothing still returns an empty bindings list, so a None
            # payload is always a failure.
            reason = "no parsable response"

        status = _status_of(query_object)
        if status is not None:
            reason = f"HTTP {status}: {reason}"

        # A rejected query (400) or anything else non-transient will not fix
        # itself; retrying only wastes the service's time. An unknown status
        # (the request never got a response) is treated as transient.
        if status is not None and status not in RETRYABLE_STATUS:
            raise WdqsQueryError(f"WDQS query failed: {reason}")
        if attempt == MAX_ATTEMPTS:
            raise WdqsQueryError(f"WDQS query failed after {attempt} attempts: {reason}")

        wait = min(_retry_after_secs(query_object) or backoff, MAX_BACKOFF_SECS)
        pwb.warning(
            f"WDQS {reason}; retry {attempt}/{MAX_ATTEMPTS - 1} in {wait:.0f}s"
        )
        time.sleep(wait)
        backoff = min(backoff * 2, MAX_BACKOFF_SECS)

    raise WdqsQueryError("WDQS query failed")  # not reached; loop always exits above
