"""Thin wrappers around the Wikidata Query Service (WDQS).

Since 2026-11-24 these go to WDQS v2 (QLever backend, query-next.wikidata.org);
v1 (Blazegraph, query.wikidata.org) may degrade from February 2027 and ends in
June 2027. v2 has no bd:slice, so addlabel_bot pages its scan with an ordered
subquery + LIMIT/OFFSET instead. The standard Wikidata prefixes are predeclared
on v2, as on v1.
"""

import pywikibot as pwb
import requests
from pywikibot.data import sparql

WDQS_ENDPOINT = "https://query-next.wikidata.org/sparql"
WD_ENTITY_URL = "http://www.wikidata.org/entity/"
USER_AGENT = "DifoolBot/1.0 (https://www.wikidata.org/wiki/User:DifoolBot)"
READ_TIMEOUT = 60  # sec


def query_wdqs(query: str, retry_counter: int = 3):
    """Query WDQS v2 via pywikibot; returns bindings ([] for an empty result),
    or None on a timeout or an unexpected error."""
    query_object = sparql.SparqlQuery(
        endpoint=WDQS_ENDPOINT, entity_url=WD_ENTITY_URL, max_retries=retry_counter
    )
    try:
        payload = query_object.query(query=query)
        if not payload:
            return None
        return payload["results"]["bindings"]
    except pwb.exceptions.TimeoutError:
        return None
    except Exception as ex:
        template = "An exception of type {0} occurred. Arguments:\n{1!r}"
        message = template.format(type(ex).__name__, ex.args)
        print("*** Uncaught Error ***")
        print(message)
        return None


def query_wdqs_simple(query: str):
    """One-shot WDQS query without retry logic; used by the lookup-cache
    builders in languages.py / countries.py."""
    response = requests.get(
        WDQS_ENDPOINT,
        params={"query": query, "format": "json"},
        headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
        timeout=READ_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    return payload["results"]["bindings"]
