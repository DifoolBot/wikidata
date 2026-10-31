"""'Military ranks of X' articles -> the model of the user's golden example.

  python ranks.py [--wiki en] [--min-age-days 180]
  in:  output/items_<wiki>.tsv, output/opening_<wiki>.tsv, output/done_<wiki>.txt (skipped)
  out: output/qs_<wiki>_ranks_all.txt (QS v1) + ranks_review.tsv (qid, why, title, main item, main article)

Model (user 2026-10-30): military ranks of the Soviet Union (Q20982613), P279 military rank + P17 the country. X = the
item of the enwiki article named by the rest of the title (see history.py), FORCE when the title names an armed force
instead. P17 only when that item is a state; otherwise P279 alone and a note in the review file.
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
TITLE = re.compile(r"^Military ranks of (.+)$")
RANK = "Q56019"
FORCE = {
    "the Armed Forces of Gabon": "Gabon", "the Royal Lao Armed Forces": "Kingdom of Laos",
    "the Royal Cambodian Armed Forces": "Cambodia", "the Thai armed forces": "Thailand",
    "the Colombian Armed Forces": "Colombia", "the Bulgarian People's Army": "People's Republic of Bulgaria",
    "the KGB (1955–1991)": "Soviet Union", "Imperial Iran": "Pahlavi Iran",
    "Slovakia (1939–1945)": "Slovak Republic (1939–1945)", "the Confederate States": "Confederate States of America",
}


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
    variants = {q: [FORCE[r]] if r in FORCE else [v[0].upper() + v[1:] for v in
                                                  dict.fromkeys([re.sub(r"^the ", "", r, flags=re.I), r])]
                for q, r in cand.items()}
    target = enwiki_items(sorted({v for vs in variants.values() for v in vs}))
    main_items = sorted({item for _, item in target.values()})
    info = places(main_items)
    alias = names_of(main_items)
    lines, notes, with_country = [], [], 0
    for q in sorted(cand, key=lambda x: int(x[1:])):
        rest = cand[q]
        art, item = next((target[v] for v in variants[q] if v in target), ("", ""))
        kind, cs, disambig = info.get(item, ("", [], False))
        keys = {key(n) for n in alias.get(item, set())} - {""}
        match = rest in FORCE or any(k in key(rest) or key(rest) in k for k in keys)
        lines.append(f"{q}\tP279\t{RANK}\n")
        if item and not disambig and match and (kind == "country" or item in cs):
            lines.append(f"{q}\tP17\t{item}\n")
            with_country += 1
        else:
            notes.append((q, "P279 only", title[q], item, art))
    with open(os.path.join(OUT, f"qs_{args.wiki}_ranks_all.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(lines)
    with open(os.path.join(OUT, "ranks_review.tsv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("qid\twhy\ttitle\tmain item\tmain article\n")
        fh.writelines("\t".join(n) + "\n" for n in notes)
        fh.writelines(f"{q}\ttoo new\t{title[q]}\t\t\n" for q in too_new)
    print(f"{len(cand) + len(too_new)} titles, {len(too_new)} too new; {len(cand)} items, {with_country} with P17; "
          f"{len(lines)} QS lines -> qs_{args.wiki}_ranks_all.txt")


if __name__ == "__main__":
    main()
