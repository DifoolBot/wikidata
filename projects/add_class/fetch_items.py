"""Unclassified items (no P31, no P279) with a sitelink on one wiki -> output/items_<wiki>.tsv (qid, title).
READ-ONLY, one QLever query. Sitelinks with a redirect badge (Q70893996 / Q70894304) are left out: no article behind them.

  python projects/add_class/fetch_items.py [--wiki en.wikipedia.org]
"""
import argparse
import os
import sys
import time

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nl_books"))
from author_ids import qlever_wait  # noqa: E402 -- shared 30 s gap between QLever queries

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
UA = {"User-Agent": "DifoolBot-add_class (https://www.wikidata.org/wiki/User:DifoolBot)"}

QUERY = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX wikibase: <http://wikiba.se/ontology#>
PREFIX schema: <http://schema.org/>
SELECT ?q ?title WHERE {
  ?article schema:about ?item ; schema:isPartOf <https://%s/> ; schema:name ?title .
  MINUS { ?item wdt:P31 [] } MINUS { ?item wdt:P279 [] }
  MINUS { ?article wikibase:badge wd:Q70893996 } MINUS { ?article wikibase:badge wd:Q70894304 }
  BIND(STRAFTER(STR(?item), "http://www.wikidata.org/entity/") AS ?q)
}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", default="en.wikipedia.org")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    for attempt in range(6):  # QLever rate-limits bursts (429): back off 60, 120, ... s
        qlever_wait()
        r = requests.post("https://qlever.dev/api/wikidata", data={"query": QUERY % args.wiki}, timeout=600,
                          headers={"Accept": "text/tab-separated-values", **UA})
        if r.status_code != 429:
            break
        print(f"   QLever 429, waiting {60 * (attempt + 1)} s ...", flush=True)
        time.sleep(60 * (attempt + 1))
    r.raise_for_status()
    r.encoding = "utf-8"  # QLever sends no charset; split on \n only (splitlines also breaks on U+0085 etc.)
    lines = [x for x in r.text.split("\n")[1:] if x]
    path = os.path.join(OUT, f"items_{args.wiki.split('.')[0]}{'' if 'wikipedia' in args.wiki else '_' + args.wiki.split('.')[1]}.tsv")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for line in lines:
            if "\t" not in line:
                print(f"   skipped: {line[:200]!r}")
                continue
            q, title = line.split("\t", 1)
            # TSV literals come as "Title"@en
            title = title.rsplit("@", 1)[0].strip('"').replace('\\"', '"').replace("\\\\", "\\")
            fh.write(f"{q.strip(chr(34))}\t{title}\n")
    print(f"{len(lines)} items -> {path}")


if __name__ == "__main__":
    main()
