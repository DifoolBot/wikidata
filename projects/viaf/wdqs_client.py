from pywikibot.data import sparql


class WdqsQueryError(Exception):
    """A WDQS query did not complete: timeout, server error, or an unparsable
    reply.

    Raised rather than returning None, because callers cannot otherwise tell a
    query that failed from one that legitimately matched no rows. Treating the
    former as the latter silently turns a lookup into a false negative - see
    ViafBot.get_duplicate_qids, where it would mean "no duplicate items exist".

    The message starts with 'WDQS query failed' so the CLEAN_UP procedure can
    recognise it as transient and mark the item for a retry.
    """


def query_wdqs(query: str, retry_counter: int = 3) -> list:
    """Run a SPARQL query against WDQS and return its (possibly empty) rows.

    Raises WdqsQueryError if the query did not complete.
    """
    query_object = sparql.SparqlQuery(max_retries=retry_counter)
    try:
        payload = query_object.query(query=query)
    except Exception as ex:
        raise WdqsQueryError(
            f"WDQS query failed: {type(ex).__name__}: {ex}"
        ) from ex

    # pywikibot returns None for an empty or undecodable response; a query that
    # simply matched nothing still returns a payload with an empty bindings list.
    if payload is None:
        raise WdqsQueryError("WDQS query failed: no parsable response")
    try:
        return payload["results"]["bindings"]
    except (KeyError, TypeError) as ex:
        raise WdqsQueryError(f"WDQS query failed: unexpected response: {ex}") from ex
