"""Stub category -> candidate class table for review (READ-ONLY).

  python projects/add_class/stub_table.py [--wiki en] [--min 5]
  -> output/stub_table_<wiki>.tsv: stub, items, parent, prop, class, label, n_p31, n_p279, suggest, decision

Route (user 2026-10-28): article -> its stub category ('Artistic_technique_stubs') -> that category's non-stub
parent ('Artistic_techniques', Q8803164) -> the parent's P301 main topic / P4224 contains (artistic technique
Q11177771) = candidate P31 for the article. A stub without such a parent inherits from its stub parent
('1920s_aircraft_stubs' -> 'Aircraft_stubs' -> 'Aircraft'). suggest = P31 or P279, whichever the target is used
as more (>= MIN_USE uses), '' for a topic like 'finance'; the decision column is filled in by hand (Q-id / skip).
"""
import argparse
import collections
import csv
import os
import sys
import time

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "nl_books"))
from author_ids import qlever_wait  # noqa: E402
from replica_cats import BATCH, lit, run  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
UA = {"User-Agent": "DifoolBot-add_class (https://www.wikidata.org/wiki/User:DifoolBot)"}
MAINT = ("Stub_categories", "Automatic_category_TOC", "Pages_", "Stub_categories_needing", "Wikipedia_", "Hidden_",
         "Tracking_", "Container_categories", "Template_", "Underpopulated_")
QBATCH = 400
MIN_USE = 50  # a target used fewer times as P31/P279 value is taken as a topic, not a class
STUB_CAT = "Q24046192"  # 'Wikimedia category of stubs': a P301/P4224 put on the wrong level, ignored


def is_stub(c):
    return c.endswith("_stubs")


def content_parents(parents):
    return [p for p in parents if p and not is_stub(p) and not p.startswith(MAINT)]


_last_wdqs = [0.0]


def wdqs(query):
    """The same query on query.wikidata.org (fallback when QLever keeps answering 429): 5 s apart, Retry-After
    honoured. Returns the response, or None when WDQS refuses too."""
    for _ in range(3):
        time.sleep(max(0.0, _last_wdqs[0] + 5 - time.time()))
        _last_wdqs[0] = time.time()
        try:
            r = requests.post("https://query.wikidata.org/sparql", data={"query": query}, timeout=90,
                              headers={"Accept": "application/sparql-results+json", **UA})
        except requests.RequestException:
            return None
        if r.status_code != 429:
            try:  # a WDQS timeout mid-stream still answers 200, with truncated JSON
                return r if r.ok and r.json() else None
            except ValueError:
                return None
        wait = int(r.headers.get("Retry-After", "60") or 60)
        print(f"   WDQS 429, waiting {wait} s ...", flush=True)
        time.sleep(wait)
    return None


def qlever(query):
    """SPARQL rows, values cut to what follows the last '/'. SPARQL_FIRST=wdqs (the default since QLever's 429s,
    user 2026-10-30) asks WDQS first and QLever only when WDQS fails (a heavy query times out at 60 s there);
    SPARQL_FIRST=qlever goes back to QLever first with WDQS after two 429s."""
    if os.environ.get("SPARQL_FIRST", "wdqs") == "wdqs":
        r = wdqs(query)
        if r is not None:
            return [{k: v["value"].rsplit("/", 1)[-1] for k, v in b.items()} for b in r.json()["results"]["bindings"]]
        print("   WDQS failed, trying QLever ...", flush=True)
    for attempt in range(6):
        qlever_wait()
        r = requests.post("https://qlever.dev/api/wikidata", data={"query": query}, timeout=600,
                          headers={"Accept": "application/sparql-results+json", **UA})
        if r.status_code != 429:
            break
        if attempt >= 1:  # two 429s in a row: try WDQS before waiting longer (user 2026-10-30)
            w = wdqs(query)
            if w is not None:
                r = w
                break
        print(f"   QLever 429, waiting {60 * (attempt + 1)} s ...", flush=True)
        time.sleep(60 * (attempt + 1))
    r.raise_for_status()
    return [{k: v["value"].rsplit("/", 1)[-1] for k, v in b.items()} for b in r.json()["results"]["bindings"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", default="en")
    ap.add_argument("--min", type=int, default=5, help="only stub categories with at least this many items")
    args = ap.parse_args()
    info = {}
    with open(os.path.join(OUT, f"catinfo_{args.wiki}.tsv"), encoding="utf-8") as fh:
        for c, item, hidden, parents in (line.rstrip("\n").split("\t") for line in fh):
            info[c] = (item, hidden == "1", parents.split("|") if parents else [])
    items_per = collections.defaultdict(set)
    with open(os.path.join(OUT, f"cats_{args.wiki}.tsv"), encoding="utf-8") as fh:
        for q, c in (line.rstrip("\n").split("\t") for line in fh):
            if is_stub(c):
                items_per[c].add(q)
    stubs = sorted((c for c in items_per if len(items_per[c]) >= args.min), key=lambda c: -len(items_per[c]))
    print(f"{len(items_per)} stub categories, {len(stubs)} with >= {args.min} items; "
          f"{len(set().union(*items_per.values()))} items in a stub category")

    # stub parents of stubs (one level up) are needed when a stub has no content parent
    need = set(stubs)
    for c in stubs:
        if not content_parents(info.get(c, ("", False, []))[2]):
            need.update(p for p in info.get(c, ("", False, []))[2] if is_stub(p))
    missing = sorted(c for c in need if c not in info)
    for c, rows in fetch_info(args.wiki, missing).items():
        info[c] = rows
    parents = sorted({p for c in need for p in content_parents(info.get(c, ("", False, []))[2])})
    for c, rows in fetch_info(args.wiki, [p for p in parents if p not in info]).items():
        info[c] = rows

    # parent category item -> P301 / P4224 targets, label
    cat_items = sorted({info[p][0] for p in parents if p in info and info[p][0]})
    target = collections.defaultdict(list)
    for i in range(0, len(cat_items), QBATCH):
        vals = " ".join("wd:" + q for q in cat_items[i:i + QBATCH])
        q = f"""PREFIX wd: <http://www.wikidata.org/entity/> PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?cat ?p ?t ?en ?mul WHERE {{ VALUES ?cat {{ {vals} }}
  {{ ?cat wdt:P301 ?t BIND("P301" AS ?p) }} UNION {{ ?cat wdt:P4224 ?t BIND("P4224" AS ?p) }}
  FILTER(?t != wd:Q4663261 && ?t != wd:Q24046192)
  OPTIONAL {{ ?t rdfs:label ?en FILTER(LANG(?en)="en") }} OPTIONAL {{ ?t rdfs:label ?mul FILTER(LANG(?mul)="mul") }}
}}"""
        for r in qlever(q):
            target[r["cat"]].append((r["p"], r["t"], r.get("en") or r.get("mul", "")))
        print(f"   QLever {min(i + QBATCH, len(cat_items))}/{len(cat_items)}", flush=True)
    usage = class_usage(sorted({t for v in target.values() for _, t, _ in v}))

    def rows_for(c):
        out = []
        for p in content_parents(info.get(c, ("", False, []))[2]):
            item = info.get(p, ("",))[0]
            for prop, t, label in dict.fromkeys(target.get(item, [])):
                out.append((p, prop, t, label))
        return out

    path = os.path.join(OUT, f"stub_table_{args.wiki}.tsv")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["stub", "items", "parent", "prop", "class", "label", "n_p31", "n_p279", "suggest", "decision"])
        for c in stubs:
            rows = rows_for(c)
            if not rows:  # inherit from the stub parent(s)
                rows = [(f"{sp}>{p}", prop, t, label) for sp in info.get(c, ("", False, []))[2] if is_stub(sp)
                        for p, prop, t, label in rows_for(sp)]
            if not rows:
                w.writerow([c, len(items_per[c]), "", "", "", "", "", "", "", ""])
            for p, prop, t, label in rows:
                n31, n279 = usage.get(t, (0, 0))
                w.writerow([c, len(items_per[c]), p, prop, t, label, n31, n279, suggest(n31, n279), ""])
    print(f"-> {path}")


def class_usage(targets):
    """Target -> (#items with P31 = target, #items with P279 = target)."""
    usage = {}
    for i in range(0, len(targets), QBATCH):
        vals = " ".join("wd:" + q for q in targets[i:i + QBATCH])
        for prop in ("P31", "P279"):
            q = (f"PREFIX wd: <http://www.wikidata.org/entity/> PREFIX wdt: <http://www.wikidata.org/prop/direct/> "
                 f"SELECT ?t (COUNT(?x) AS ?n) WHERE {{ VALUES ?t {{ {vals} }} ?x wdt:{prop} ?t }} GROUP BY ?t")
            for r in qlever(q):
                n = usage.setdefault(r["t"], [0, 0])
                n[0 if prop == "P31" else 1] = int(r["n"])
        print(f"   usage {min(i + QBATCH, len(targets))}/{len(targets)}", flush=True)
    return usage


def suggest(n31, n279):
    """P31 / P279 when the target is clearly used as a class, else '' (a topic like 'finance')."""
    if n31 + n279 < MIN_USE:
        return ""
    return "P31" if n31 >= n279 else "P279"


def fetch_info(wiki, cats):
    """Category -> (item, hidden, parents) from the replica for categories not seen yet."""
    info = {c: ["", False, []] for c in cats}
    sql = ""
    for i in range(0, len(cats), BATCH):
        part = ",".join(map(lit, cats[i:i + BATCH]))
        sql += (f"SELECT 'I', page_title, pp_propname, pp_value FROM page JOIN page_props ON pp_page = page_id "
                f"AND pp_propname IN ('wikibase_item', 'hiddencat') WHERE page_namespace = 14 AND page_title IN ({part});\n")
        sql += (f"SELECT 'P', page_title, lt_title FROM page JOIN categorylinks ON cl_from = page_id "
                f"JOIN linktarget ON lt_id = cl_target_id AND lt_namespace = 14 "
                f"WHERE page_namespace = 14 AND page_title IN ({part});\n")
    for r in run(wiki, sql) if sql else []:
        if r[0] == "I" and r[1] in info:
            if r[2] == "wikibase_item":
                info[r[1]][0] = r[3]
            else:
                info[r[1]][1] = True
        elif r[0] == "P" and r[1] in info:
            info[r[1]][2].append(r[2])
    return {c: tuple(v) for c, v in info.items()}


if __name__ == "__main__":
    main()
