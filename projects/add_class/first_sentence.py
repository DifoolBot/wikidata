"""Opening text of the articles in items_<wiki>.tsv from the weekly CirrusSearch dump (Toolforge, READ-ONLY).

  python3 first_sentence.py ITEMS_TSV OUT_TSV [--dump DIR] [--chars 600] [--shards N]
  -> OUT_TSV: qid, opening text (first --chars characters of the plain article text, newlines flattened)

Runs on Toolforge as a job (the dump is mounted there, no API load):
  /public/dumps/public/other/cirrus_search_index/<date>/index_name=enwiki_content/*.json.bz2
Records come in pairs: an {"index": ...} line, then the page document (title, text, ...); redirects have no text.
Default --dump is the newest dated directory. The replicas hold no page text, the Enterprise dumps stop at 2025-03.
"""
import argparse
import bz2
import glob
import json
import os

ROOT = "/public/dumps/public/other/cirrus_search_index"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("items")
    ap.add_argument("out")
    ap.add_argument("--wiki", default="enwiki")
    ap.add_argument("--dump", help="dump directory (default: newest)")
    ap.add_argument("--chars", type=int, default=600)
    ap.add_argument("--shards", type=int, help="only the first N shards (test)")
    args = ap.parse_args()
    dump = args.dump or os.path.join(sorted(glob.glob(os.path.join(ROOT, "2*")))[-1],
                                     f"index_name={args.wiki}_content")
    with open(args.items, encoding="utf-8") as fh:
        qid = dict(reversed(line.rstrip("\n").split("\t", 1)) for line in fh if "\t" in line)
    shards = sorted(glob.glob(os.path.join(dump, "*.json.bz2")))[:args.shards]
    print(f"{len(qid)} titles, {len(shards)} shards in {dump}", flush=True)
    found = 0
    with open(args.out, "w", encoding="utf-8", newline="\n") as out:
        for n, path in enumerate(shards, 1):
            with bz2.open(path, "rt", encoding="utf-8") as fh:
                for line in fh:
                    if not line.startswith('{"index'):
                        doc = json.loads(line)
                        q = qid.get(doc.get("title"))
                        if q and doc.get("text"):
                            text = " ".join(doc["text"][:args.chars].split())
                            out.write(f"{q}\t{text}\n")
                            found += 1
            out.flush()
            print(f"   shard {n}/{len(shards)}: {found} found ...", flush=True)
    print(f"{found} of {len(qid)} articles -> {args.out}")


if __name__ == "__main__":
    main()
