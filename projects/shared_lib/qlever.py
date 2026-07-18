import time
from pathlib import Path

import requests

QLEVER_WIKIDATA_URL = "https://qlever.cs.uni-freiburg.de/api/wikidata"
WD_ENTITY_PREFIX = "http://www.wikidata.org/entity/"

READ_TIMEOUT = 300  # sec
# Identify ourselves: anonymous default-UA requests get rate-limited quickly,
# especially from Toolforge's shared egress IP.
USER_AGENT = "DifoolBot/1.0 (https://www.wikidata.org/wiki/User:DifoolBot)"
MAX_RETRIES = 3


def run_qlever_query(query: str, timeout: int = READ_TIMEOUT) -> list[dict]:
    """Run a SPARQL query against qlever's Wikidata endpoint.

    Returns the raw SPARQL-JSON result bindings (an empty list if there are none).
    Retries with backoff when rate-limited (429), honoring Retry-After.
    """
    for attempt in range(MAX_RETRIES + 1):
        response = requests.get(
            QLEVER_WIKIDATA_URL,
            params={"query": query},
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
        )
        if response.status_code == 429 and attempt < MAX_RETRIES:
            try:
                wait = int(response.headers.get("Retry-After", ""))
            except ValueError:
                wait = 30 * (attempt + 1)
            time.sleep(wait)
            continue
        response.raise_for_status()
        data = response.json()
        return data.get("results", {}).get("bindings", [])
    raise AssertionError("unreachable")


def query_item_qids(query: str, var: str = "item") -> list[str]:
    """Run a query selecting ?<var> entities and return their QIDs, in result order."""
    qids = []
    for binding in run_qlever_query(query):
        uri = binding.get(var, {}).get("value", "")
        qid = uri.rsplit("/", 1)[-1]
        if qid.startswith("Q"):
            qids.append(qid)
    return qids


def build_url_items_query(
    url_properties: list[str], domain_substrings: list[str]
) -> str:
    """Build a SPARQL query selecting items that carry, on any of url_properties,
    a URL statement whose value contains one of domain_substrings.

    Deliberately minimal: no ordering or extra joins, which push the query over
    the public endpoint's resource budget (it answers 429 after ~1 min).
    fetch_qids_to_file sorts the QIDs newest-first client-side instead.
    """
    props = " ".join(f"p:{pid}" for pid in url_properties)
    domain_filter = " ||\n    ".join(
        f'CONTAINS(STR(?url), "{domain}")' for domain in domain_substrings
    )
    return f"""PREFIX p: <http://www.wikidata.org/prop/>
SELECT DISTINCT ?item WHERE {{
  VALUES ?prop {{ {props} }}
  ?item ?prop ?statement .
  ?statement ?psDirect ?url .
  FILTER(
    {domain_filter}
  )
}}
"""


def fetch_qids_to_file(query: str, output_file: Path, var: str = "item") -> int:
    """Run query, write the resulting QIDs (one per line, newest item first) to
    output_file, return the count."""
    qids = query_item_qids(query, var=var)
    qids.sort(key=lambda qid: int(qid[1:]), reverse=True)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        "".join(f"{qid}\n" for qid in qids), encoding="utf-8"
    )
    return len(qids)
