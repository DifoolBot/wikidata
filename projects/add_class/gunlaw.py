"""'Gun law(s) in/of X' articles -> the model of the user's golden example.

  python gunlaw.py [--wiki en] [--min-age-days 180]
  in:  output/items_<wiki>.tsv, output/done_<wiki>.txt (skipped)
  out: output/qs_<wiki>_gunlaw_all.txt (QS v1) + gunlaw_review.tsv (qid, why, title, main item, main article)

Model (user 2026-10-31): gun law in the United States (Q1151222), P31 legislation + P1269 gun control + P1001 X.
X = the item of the enwiki article named by the rest of the title (see history.py). 'Gun politics in X' has another
model (Q17005971: aspect in a geographic region), but no such title is left. 'Firearms regulation/policy in X' and
'Gun control in X' follow the gun law model too (user 2026-10-31).
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
TITLE = re.compile(r"^(?:Gun laws? (?:in|of)|Firearms (?:regulation|policy) in|Gun control in) (.+)$")
LEGISLATION, GUN_CONTROL, SET_INDEX = "Q49371", "Q1328508", "Q15623926"
SET_INDEX_ITEMS = {"Q116873131"}  # Gun laws in Washington: the state or D.C.
REVIEW = {"Q16982937": "by state: overview of the states, not one jurisdiction"}


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
    lines, notes, count = [], [], 0
    for q in sorted(cand, key=lambda x: int(x[1:])):
        rest = cand[q]
        art, item = next((target[v] for v in variants[q] if v in target), ("", ""))
        _, _, disambig = info.get(item, ("", [], False))
        keys = {key(n) for n in alias.get(item, set())} - {""}
        if q in SET_INDEX_ITEMS:
            lines.append(f"{q}\tP31\t{SET_INDEX}\n")
        elif q in REVIEW:
            notes.append((q, REVIEW[q], title[q], item, art))
        elif not item or disambig or not any(k in key(rest) or key(rest) in k for k in keys):
            notes.append((q, "no matching main item: skipped", title[q], item, art))
        else:
            lines += [f"{q}\tP31\t{LEGISLATION}\n", f"{q}\tP1269\t{GUN_CONTROL}\n", f"{q}\tP1001\t{item}\n"]
            count += 1
    with open(os.path.join(OUT, f"qs_{args.wiki}_gunlaw_all.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(lines)
    with open(os.path.join(OUT, "gunlaw_review.tsv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("qid\twhy\ttitle\tmain item\tmain article\n")
        fh.writelines("\t".join(n) + "\n" for n in notes)
        fh.writelines(f"{q}\ttoo new\t{title[q]}\t\t\n" for q in too_new)
    print(f"{len(cand) + len(too_new)} titles, {len(too_new)} too new; {count} laws; {len(notes)} in review; "
          f"{len(lines)} QS lines -> qs_{args.wiki}_gunlaw_all.txt")


if __name__ == "__main__":
    main()
