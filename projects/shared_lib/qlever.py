from pathlib import Path

import requests

QLEVER_WIKIDATA_URL = "https://qlever.cs.uni-freiburg.de/api/wikidata"
WD_ENTITY_PREFIX = "http://www.wikidata.org/entity/"

READ_TIMEOUT = 300  # sec


def run_qlever_query(query: str, timeout: int = READ_TIMEOUT) -> list[dict]:
    """Run a SPARQL query against qlever's Wikidata endpoint.

    Returns the raw SPARQL-JSON result bindings (an empty list if there are none).
    """
    response = requests.get(
        QLEVER_WIKIDATA_URL, params={"query": query}, timeout=timeout
    )
    response.raise_for_status()
    data = response.json()
    return data.get("results", {}).get("bindings", [])


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

    Results are ordered by descending QID number (newest items first).
    """
    props = " ".join(f"p:{pid}" for pid in url_properties)
    domain_filter = " ||\n    ".join(
        f'CONTAINS(STR(?url), "{domain}")' for domain in domain_substrings
    )
    return f"""PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
PREFIX wikibase: <http://wikiba.se/ontology#>
SELECT DISTINCT ?item WHERE {{
  VALUES ?prop {{ {props} }}
  ?item ?prop ?statement .
  ?statement ?psDirect ?url .
  FILTER(
    {domain_filter}
  )
  ?item wikibase:statements ?statementCount .  # forces item metadata join
  BIND(xsd:integer(STRAFTER(STR(?item), "Q")) AS ?qnum)
}}
ORDER BY DESC(?qnum)
"""


def fetch_qids_to_file(query: str, output_file: Path, var: str = "item") -> int:
    """Run query, write the resulting QIDs (one per line) to output_file, return the count."""
    qids = query_item_qids(query, var=var)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        "".join(f"{qid}\n" for qid in qids), encoding="utf-8"
    )
    return len(qids)
