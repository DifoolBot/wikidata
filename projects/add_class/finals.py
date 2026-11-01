"""'<year> ... final(s)' articles -> the model of the user's golden examples.

  python finals.py [--wiki en] [--min-age-days 180]
  in:  output/items_<wiki>.tsv, output/opening_<wiki>.tsv, output/done_<wiki>.txt (skipped)
  out: output/qs_<wiki>_finals_all.txt (QS v1) + finals_review.tsv (qid, why, title, opening)

Model (user 2026-10-31): 2020 Hazfi Cup Final (Q98399678), P31 final + P641 the sport. The other years of the same
competition give the sport and, when they all use it, a class of its own (AFL Grand Final). A tournament or a series
named 'Finals' is no final match: NOT_A_MATCH goes to the review file. The teams (P1923) and place (P276) are left out.
"""
import argparse
import collections
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_qs import first_revision  # noqa: E402
from replica_cats import run  # noqa: E402
from stub_table import qlever  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
TITLE = re.compile(r"^\d{4}(?:[–-]\d{2,4})? .* [Ff]inals?$")
FINAL = "Q1366722"
OWN_CLASS = {"afl grand": "Q2819161", "afl women's grand": "Q39087320"}
NOT_A_MATCH = {"formula bmw world", "nbtc national", "psa world tour", "men's psa world tour", "korn ferry tour",
               "tcr world ranking", "women's softball world cup", "men's softball world cup", "premier padel",
               "master", "wpt master", "pbr world", "davis cup", "bsn", "eurocup"}
# a sport named in the title or the opening; plain 'football' only counts after the other years of the competition
SPORT = [(r"australian rules", "Q50776"), (r"cricket|twenty20", "Q5375"), (r"basketball", "Q5372"),
         (r"hurling", "Q213711"), (r"rugby", "Q5849"), (r"ice hockey|iihf", "Q41466"), (r"squash", "Q133201"),
         (r"tennis", "Q847"), (r"kho kho", "Q3520517")]
FOOTBALL = re.compile(r"soccer|football", re.I)
ASSOCIATION_FOOTBALL = "Q2736"


def competition(t):
    t = re.sub(r"^\d{4}(?:[–-]\d{2,4})? ", "", t.replace("_", " "))
    return re.sub(r" [Ff]inals?$", "", t).casefold()


def sibling_sports(want, ours):
    """competition -> Counter of P641 of its other years on enwiki."""
    rows = run("en", "SELECT page_title, pp_value FROM page JOIN page_props ON pp_page = page_id AND "
                     "pp_propname = 'wikibase_item' WHERE page_namespace = 0 AND page_is_redirect = 0 AND "
                     "(page_title LIKE '%inal' OR page_title LIKE '%inals') AND CONVERT(page_title USING utf8mb4) "
                     "REGEXP '^[0-9]{4}(–[0-9]{2,4})?_.*_[Ff]inals?$';\n")
    comp = {item: competition(t) for t, item in rows if competition(t) in want and item not in ours}
    items = sorted(comp)
    out = collections.defaultdict(collections.Counter)
    for i in range(0, len(items), 300):
        q = f"""PREFIX wd: <http://www.wikidata.org/entity/> PREFIX wdt: <http://www.wikidata.org/prop/direct/>
SELECT ?i ?c WHERE {{ VALUES ?i {{ {" ".join("wd:" + x for x in items[i:i + 300])} }} ?i wdt:P641 ?c }}"""
        for r in qlever(q):
            out[comp[r["i"]]][r["c"]] += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", default="en")
    ap.add_argument("--min-age-days", type=int, default=180)
    args = ap.parse_args()
    with open(os.path.join(OUT, f"items_{args.wiki}.tsv"), encoding="utf-8") as fh:
        title = dict(line.rstrip("\n").split("\t", 1) for line in fh if "\t" in line)
    with open(os.path.join(OUT, f"done_{args.wiki}.txt"), encoding="utf-8") as fh:
        done = {line.strip() for line in fh if line.strip()}
    cand = [q for q, t in title.items() if TITLE.match(t) and q not in done]
    opening = {}
    with open(os.path.join(OUT, f"opening_{args.wiki}.tsv"), encoding="utf-8") as fh:
        for line in fh:
            q, text = line.rstrip("\n").split("\t", 1)
            opening[q] = text
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.min_age_days)).strftime("%Y%m%d%H%M%S")
    first = first_revision(cand)
    sports = sibling_sports({competition(title[q]) for q in cand}, set(cand))
    lines, notes, finals = [], [], 0
    for q in sorted(cand, key=lambda x: int(x[1:])):
        t, s = title[q], opening.get(q, "")
        c = competition(t)

        def note(why):
            notes.append((q, why, t, s[:150]))

        if first.get(q, "9") > cutoff:
            note("too new")
            continue
        if c in NOT_A_MATCH:
            note("a tournament or series, no final match")
            continue
        if not s.strip():
            note("no opening")
            continue
        lines.append(f"{q}\tP31\t{OWN_CLASS.get(c, FINAL)}\n")
        finals += 1
        text = f"{t} {s[:300]}"
        sport = next((v for word, v in SPORT if re.search(word, text, re.I)), "")
        if not sport and sports.get(c):
            sport = sports[c].most_common(1)[0][0]
        if not sport and FOOTBALL.search(text):
            sport = ASSOCIATION_FOOTBALL
        if sport:
            lines.append(f"{q}\tP641\t{sport}\n")
        else:
            note("P31 only, no sport found")
    with open(os.path.join(OUT, f"qs_{args.wiki}_finals_all.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(lines)
    with open(os.path.join(OUT, "finals_review.tsv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("qid\twhy\ttitle\topening\n")
        fh.writelines("\t".join(n) + "\n" for n in sorted(notes, key=lambda n: n[1]))
    print(f"{len(cand)} titles; {finals} finals; {len(notes)} notes; {len(lines)} QS lines -> "
          f"qs_{args.wiki}_finals_all.txt")


if __name__ == "__main__":
    main()
