"""Thin wrappers around the Wikidata Query Service (WDQS).

The slice-based scan in addlabel_bot relies on Blazegraph's bd:slice service,
so these queries have to go to WDQS and cannot use shared_lib.qlever.
"""

import pywikibot as pwb
import requests
from pywikibot.data import sparql

WDQS_ENDPOINT = "https://query.wikidata.org/sparql"
READ_TIMEOUT = 60  # sec


def query_wdqs(query: str, retry_counter: int = 3):
    """Query WDQS via pywikibot; returns bindings, or None when the slice is
    exhausted (WDQS answers such queries with a timeout error)."""
    query_object = sparql.SparqlQuery(max_retries=retry_counter)
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


def query_wdqs_simple(query: str):
    """One-shot WDQS query without retry logic; used by the lookup-cache
    builders in languages.py / countries.py."""
    response = requests.get(
        WDQS_ENDPOINT, params={"query": query, "format": "json"}, timeout=READ_TIMEOUT
    )
    payload = response.json()
    return payload["results"]["bindings"]
