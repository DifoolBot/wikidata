"""'History of X' / 'History and culture of X' articles -> P31 aspect of history + P1269 (facet of) X.

  python history.py [--wiki en] [--min-age-days 180]
  in:  output/items_<wiki>.tsv, output/opening_<wiki>.tsv, output/done_<wiki>.txt (skipped)
  out: output/qs_<wiki>_history_all.txt (QS v1) + history_review.tsv (qid, note, title, main item, label, opening)

Model (user 2026-10-30): history and culture of breastfeeding (Q5774799), the Wikidata majority (4,536 enwiki
'History of' items have P31 Q17524420): P31 aspect of history; history of a city (Q28747937) when X is a city,
history of a country or state (Q17544377) when X is a country (direct P31, so not a state like Kerala). X = the item
of the enwiki article named by the rest of the title, redirects followed (enwiki API via pywikibot, logged in,
maxlag 5). P1269 only when that item's label matches X ('History of the SAT' redirects to a wrestling stable,
'History of ecstasy' to a disambiguation page): otherwise P31 alone and a note in history_review.tsv.
Skipped: a work ('The History of Llanthony Priory is a medieval Latin text'), a redirect back to the item itself.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_qs import first_revision  # noqa: E402
from stub_table import qlever  # noqa: E402
from verify_stub import first_sentence  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
REPO = os.path.dirname(os.path.dirname(HERE))
TITLE = re.compile(r"^(?:History and [Cc]ulture|History) of (.+)$")
ASPECT, CITY, COUNTRY = "Q17524420", "Q28747937", "Q17544377"
WORK = re.compile(r"\bis an? (?:[\w-]+ ){0,4}(?:book|novel|poem|journal|magazine|documentary|film|album|song|podcast|"
                  r"painting|play|treatise|monograph|chronicle|encyclopedia|text|manuscript|video game)\b", re.I)
PREFIX = """PREFIX wd: <http://www.wikidata.org/entity/> PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> PREFIX schema: <http://schema.org/>
"""


def enwiki_items(titles):
    """Article title -> (target title, item) on enwiki, redirects followed."""
    os.environ.setdefault("PYWIKIBOT_DIR", REPO)  # pywikibot only looks for user-config.py in the cwd otherwise
    import pywikibot
    from pywikibot.data import api
    site = pywikibot.Site("en", "wikipedia")
    site.login()
    found = {}
    for i in range(0, len(titles), 50):
        part = titles[i:i + 50]
        d = api.Request(site=site, parameters={"action": "query", "titles": "|".join(part), "redirects": 1,
                                               "prop": "pageprops", "ppprop": "wikibase_item",
                                               "maxlag": 5}).submit()["query"]
        norm = {x["from"]: x["to"] for x in d.get("normalized", [])}
        red = {x["from"]: x["to"] for x in d.get("redirects", [])}
        item = {p["title"]: p.get("pageprops", {}).get("wikibase_item") for p in d["pages"].values()
                if "missing" not in p}
        for t in part:
            x = red.get(norm.get(t, t), norm.get(t, t))
            if item.get(x):
                found[t] = (x, item[x])
    return found


def kinds(items):
    """item -> (label, 'city' / 'country' / '')."""
    out = {}
    for i in range(0, len(items), 300):
        q = PREFIX + f"""SELECT ?m (SAMPLE(?l) AS ?label) (SAMPLE(?k) AS ?kind) WHERE {{
  VALUES ?m {{ {" ".join("wd:" + x for x in items[i:i + 300])} }}
  OPTIONAL {{ ?m rdfs:label ?l FILTER(LANG(?l) IN ("en", "mul")) }}
  OPTIONAL {{ {{ VALUES ?t {{ wd:Q6256 wd:Q3624078 }} ?m wdt:P31 ?t BIND("country" AS ?k) }}
    UNION {{ ?m wdt:P31/wdt:P279* wd:Q515 BIND("city" AS ?k) }} }} }} GROUP BY ?m"""
        out.update((r["m"], (r.get("label", ""), r.get("kind", ""))) for r in qlever(q))
    return out


def names_of(items):
    """item -> its en/mul label and aliases: 'Indonesia national football team' is an alias of 'Indonesia men's
    national football team' (Q657451)."""
    out = {}
    for i in range(0, len(items), 300):
        q = PREFIX + f"""PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
SELECT ?m ?n WHERE {{ VALUES ?m {{ {" ".join("wd:" + x for x in items[i:i + 300])} }}
  {{ ?m rdfs:label ?n }} UNION {{ ?m skos:altLabel ?n }} FILTER(LANG(?n) IN ("en", "mul")) }}"""
        for r in qlever(q):
            out.setdefault(r["m"], set()).add(r["n"])
    return out


def key(t):
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().casefold()
    t = re.sub(r"^the ", "", re.sub(r"\([^)]*\)", "", t).strip())
    return re.sub(r"[^a-z0-9]", "", t.split(",")[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", default="en")
    ap.add_argument("--min-age-days", type=int, default=180)
    args = ap.parse_args()
    with open(os.path.join(OUT, f"items_{args.wiki}.tsv"), encoding="utf-8") as fh:
        title = dict(line.rstrip("\n").split("\t", 1) for line in fh if "\t" in line)
    try:
        with open(os.path.join(OUT, f"done_{args.wiki}.txt"), encoding="utf-8") as fh:
            done = {line.strip() for line in fh if line.strip()}
    except FileNotFoundError:
        done = set()
    cand = {q: TITLE.match(t).group(1) for q, t in title.items() if TITLE.match(t) and q not in done}
    opening = {}
    with open(os.path.join(OUT, f"opening_{args.wiki}.tsv"), encoding="utf-8") as fh:
        for line in fh:
            q, text = line.rstrip("\n").split("\t", 1)
            if q in cand:
                opening[q] = first_sentence(text)
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.min_age_days)).strftime("%Y%m%d%H%M%S")
    first = first_revision(list(cand))
    too_new = [q for q in cand if first.get(q, "9") > cutoff]
    for q in too_new:
        del cand[q]
    # 'the SAT' -> 'SAT' first: the article 'The SAT' is a wrestling stable
    variants = {q: [v[0].upper() + v[1:] for v in dict.fromkeys([re.sub(r"^the ", "", r, flags=re.I), r])]
                for q, r in cand.items()}
    target = enwiki_items(sorted({v for vs in variants.values() for v in vs}))
    info = kinds(sorted({item for _, item in target.values()}))
    alias = names_of(sorted(info))
    disambig = set()
    items = sorted(info)
    for i in range(0, len(items), 300):
        q = PREFIX + f"""SELECT ?m WHERE {{ VALUES ?m {{ {" ".join("wd:" + x for x in items[i:i + 300])} }}
  ?m wdt:P31 wd:Q4167410 }}"""
        disambig.update(r["m"] for r in qlever(q))
    lines, notes = [], []
    for q in sorted(cand, key=lambda x: int(x[1:])):
        rest = cand[q]
        art, item = next((target[v] for v in variants[q] if v in target), ("", ""))
        label, kind = info.get(item, ("", ""))
        s = opening.get(q, "")
        if WORK.search(s[:200]):
            notes.append((q, "a work: skipped", title[q], item, label, s))
            continue
        if item == q:
            notes.append((q, "redirects to itself: skipped", title[q], item, label, s))
            continue
        if not item:
            notes.append((q, "no main article: skipped", title[q], "", "", s))
            continue
        lines.append(f"{q}\tP31\t{CITY if kind == 'city' else COUNTRY if kind == 'country' else ASPECT}\n")
        keys = {key(n) for n in alias.get(item, {label})} - {""}
        if item in disambig:
            notes.append((q, "main item is a disambiguation page: P31 only", title[q], item, label, s))
        elif any(k == key(rest) or k in key(rest) for k in keys):
            lines.append(f"{q}\tP1269\t{item}\n")
        else:
            notes.append((q, "main item label differs: P31 only", title[q], item, label, s))
    with open(os.path.join(OUT, f"qs_{args.wiki}_history_all.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(lines)
    with open(os.path.join(OUT, "history_review.tsv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("qid\tnote\ttitle\tmain item\tlabel\topening\n")
        fh.writelines("\t".join(map(str, n)) + "\n" for n in sorted(notes, key=lambda n: n[1]))
    print(f"{len(cand) + len(too_new)} history titles, {len(too_new)} too new; {len(notes)} notes; "
          f"{len(lines)} QS lines -> qs_{args.wiki}_history_all.txt")
    print(json.dumps({n: sum(1 for x in notes if x[1] == n) for n in sorted({x[1] for x in notes})}))


if __name__ == "__main__":
    main()
