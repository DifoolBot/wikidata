"""'National symbols of X' articles -> the model of the user's golden example.

  python symbols.py [--wiki en] [--min-age-days 180]
  in:  output/items_<wiki>.tsv, output/opening_<wiki>.tsv, output/done_<wiki>.txt (skipped)
  out: output/qs_<wiki>_symbols_all.txt (QS v1) + symbols_review.tsv (qid, why, title, main item, main article)

Model (user 2026-10-31): National symbols of Russia (Q26832819), P279 national symbol + P17 the country + P1268
(represents) X. An opening that says it is a list falls back on national symbols of Canada (Q2328602), P31 list article
+ P360 national symbol + P17. X = the item of the enwiki article named by the rest of the title (see history.py). A
state is its own P17, a part of a state has the one P17 of its item (England: United Kingdom), a people has none.
"""
import argparse
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from history import enwiki_items, key, names_of  # noqa: E402
from make_qs import first_revision  # noqa: E402
from politics import places  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
TITLE = re.compile(r"^National symbols of (.+)$")
SYMBOL, LIST = "Q1128637", "Q13406463"
IS_LIST = re.compile(r"\b(?:is|article is) an? (?:[\w-]+ )?list\b", re.I)


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
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.min_age_days)).strftime("%Y%m%d%H%M%S")
    first = first_revision(list(cand))
    too_new = [q for q in cand if first.get(q, "9") > cutoff]
    for q in too_new:
        del cand[q]
    variants = {q: [v[0].upper() + v[1:] for v in dict.fromkeys([re.sub(r"^the ", "", r, flags=re.I), r])]
                for q, r in cand.items()}
    target = enwiki_items(sorted({v for vs in variants.values() for v in vs}))
    main_items = sorted({item for _, item in target.values()})
    info = places(main_items)
    alias = names_of(main_items)
    lines, notes, count = [], [], {"symbol": 0, "list": 0}
    for q in sorted(cand, key=lambda x: int(x[1:])):
        rest, s = cand[q], opening.get(q, "")
        art, item = next((target[v] for v in variants[q] if v in target), ("", ""))
        kind, cs, disambig = info.get(item, ("", [], False))
        keys = {key(n) for n in alias.get(item, set())} - {""}
        if not s.strip():
            notes.append((q, "no opening: skipped", title[q], item, art))
            continue
        if not item or disambig or not any(k in key(rest) or key(rest) in k for k in keys):
            notes.append((q, "no matching main item: skipped", title[q], item, art))
            continue
        country = item if kind == "country" or item in cs else cs[0] if len(set(cs)) == 1 else ""
        if IS_LIST.search(s[:200]):
            lines += [f"{q}\tP31\t{LIST}\n", f"{q}\tP360\t{SYMBOL}\n"]
            count["list"] += 1
        else:
            lines += [f"{q}\tP279\t{SYMBOL}\n", f"{q}\tP1268\t{item}\n"]
            count["symbol"] += 1
        if country:
            lines.append(f"{q}\tP17\t{country}\n")
        else:
            notes.append((q, f"no P17: {len(set(cs))} countries on the main item", title[q], item, art))
    with open(os.path.join(OUT, f"qs_{args.wiki}_symbols_all.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(lines)
    with open(os.path.join(OUT, "symbols_review.tsv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("qid\twhy\ttitle\tmain item\tmain article\n")
        fh.writelines("\t".join(n) + "\n" for n in notes)
        fh.writelines(f"{q}\ttoo new\t{title[q]}\t\t\n" for q in too_new)
    print(f"{len(cand) + len(too_new)} titles, {len(too_new)} too new; {count['symbol']} symbol model, "
          f"{count['list']} list model; {len(notes)} notes; {len(lines)} QS lines -> qs_{args.wiki}_symbols_all.txt")


if __name__ == "__main__":
    main()
