"""enwiki short descriptions of the candidate items -> output/shortdesc_<wiki>.tsv (qid, description). READ-ONLY.

  python projects/add_class/shortdesc.py [--wiki en]

Candidates = items in a decided stub (review_<wiki>.tsv). Only local short descriptions (page property
'wikibase-shortdesc'); make_qs.py uses them to keep kinds ('Type of mace') and concepts ('Astrophysical process')
out of the P31 batches.
"""
import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from replica_cats import BATCH, lit, run  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", default="en")
    args = ap.parse_args()
    with open(os.path.join(OUT, f"review_{args.wiki}.tsv"), encoding="utf-8") as fh:
        decided = {r["stub"] for r in csv.DictReader(fh, delimiter="\t") if r["decision"]}
    with open(os.path.join(OUT, f"cats_{args.wiki}.tsv"), encoding="utf-8") as fh:
        qids = {q for q, c in (line.rstrip("\n").split("\t") for line in fh) if c in decided}
    title = {}
    with open(os.path.join(OUT, f"items_{args.wiki}.tsv"), encoding="utf-8") as fh:
        for q, t in (line.rstrip("\n").split("\t", 1) for line in fh):
            if q in qids:
                title[t.replace(" ", "_")] = q
    ts = sorted(title)
    sql = "".join(f"SELECT page_title, pp_value FROM page JOIN page_props ON pp_page = page_id "
                  f"AND pp_propname = 'wikibase-shortdesc' WHERE page_namespace = 0 "
                  f"AND page_title IN ({','.join(map(lit, ts[i:i + BATCH]))});\n" for i in range(0, len(ts), BATCH))
    rows = run(args.wiki, sql)
    path = os.path.join(OUT, f"shortdesc_{args.wiki}.tsv")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(f"{title[t]}\t{d}\n" for t, d in rows if t in title)
    print(f"{len(title)} items, {len(rows)} with a local short description -> {path}")


if __name__ == "__main__":
    main()
