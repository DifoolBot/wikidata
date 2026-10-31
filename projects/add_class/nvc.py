"""'British NVC community <code>' articles -> P279 the major category of the British National Vegetation Classification.

  python nvc.py [--wiki en] [--min-age-days 180]
  in:  output/items_<wiki>.tsv, output/opening_<wiki>.tsv, output/done_<wiki>.txt (skipped)
  out: output/qs_<wiki>_nvc_all.txt (QS v1) + nvc_review.tsv (qid, why, title, opening)

Model (user 2026-10-30): the code prefix names the category (en:British National Vegetation Classification), as on the
classified siblings: MG1 P279 mesotrophic grassland. A category item without P31/P279 gets P279 plant community, as
mesotrophic grassland (Q6821647) has. An opening that names another category goes to the review file.
"""
import argparse
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_qs import first_revision  # noqa: E402
from stub_table import qlever  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
TITLE = re.compile(r"^British NVC community ([A-Z]+)\d+[a-z]?$")
PLANT_COMMUNITY = "Q1418712"
# prefix -> category item, word in the opening
CATEGORY = {
    "W": ("Q8032895", r"woodland|scrub"), "M": ("Q6873169", r"\bmire"), "H": ("Q5694359", r"\bheath"),
    "MG": ("Q6821647", r"mesotrophic"), "CG": ("Q5018767", r"calcicolous"), "U": ("Q5018772", r"calcifugous|montane"),
    "A": ("Q4782801", r"aquatic"), "S": ("Q7653388", r"swamp|fen"), "SM": ("Q7405788", r"salt-?marsh"),
    "SD": ("Q7497456", r"shingle|strandline|sand-?dune"), "MC": ("Q6765859", r"maritime cliff"),
    "OV": ("Q7918369", r"open habitat"),
}


def classified(items):
    """The items that have a P31 or P279 now."""
    out = set()
    for i in range(0, len(items), 300):
        q = f"""PREFIX wd: <http://www.wikidata.org/entity/> PREFIX wdt: <http://www.wikidata.org/prop/direct/>
SELECT DISTINCT ?i WHERE {{ VALUES ?i {{ {" ".join("wd:" + x for x in items[i:i + 300])} }}
  {{ ?i wdt:P31 ?c }} UNION {{ ?i wdt:P279 ?c }} }}"""
        out.update(r["i"] for r in qlever(q))
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
    cand = {q: TITLE.match(t).group(1) for q, t in title.items() if TITLE.match(t) and q not in done}
    opening = {}
    with open(os.path.join(OUT, f"opening_{args.wiki}.tsv"), encoding="utf-8") as fh:
        for line in fh:
            q, text = line.rstrip("\n").split("\t", 1)
            if q in cand:
                opening[q] = text
    categories = sorted({c for c, _ in CATEGORY.values()})
    first = first_revision(list(cand))
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.min_age_days)).strftime("%Y%m%d%H%M%S")
    have = classified(sorted(cand) + categories)
    lines, notes = [], []
    for q in sorted(cand, key=lambda x: int(x[1:])):
        cat, word = CATEGORY[cand[q]]
        s = opening.get(q, "")
        if first.get(q, "9") > cutoff:
            notes.append((q, "too new", title[q], s[:150]))
        elif q in have:
            notes.append((q, "has a class by now", title[q], s[:150]))
        elif not re.search(word, s[:400], re.I):
            notes.append((q, "opening names another category", title[q], s[:150]))
        else:
            lines.append(f"{q}\tP279\t{cat}\n")
    members = len(lines)
    lines += [f"{c}\tP279\t{PLANT_COMMUNITY}\n" for c in categories if c not in have and c not in done]
    with open(os.path.join(OUT, f"qs_{args.wiki}_nvc_all.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(lines)
    with open(os.path.join(OUT, "nvc_review.tsv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("qid\twhy\ttitle\topening\n")
        fh.writelines("\t".join(n) + "\n" for n in notes)
    print(f"{len(cand)} titles; {members} communities + {len(lines) - members} categories; {len(notes)} in review; "
          f"{len(lines)} QS lines -> qs_{args.wiki}_nvc_all.txt")


if __name__ == "__main__":
    main()
