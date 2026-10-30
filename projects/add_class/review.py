"""Typed stub categories from output/stub_table_<wiki>.tsv -> output/review_<wiki>.tsv, for the hand decision.

  python projects/add_class/review.py [--wiki en]

Typed = the parent category names the stub's head word in the plural ('Weapon_stubs' -> 'Weapons',
'Indian_ethnic_group_stubs' -> 'Ethnic_groups_in_India'); a topic stub keeps the mass noun ('Finance_stubs' ->
'Finance') and is left out. One row per (stub, class); stubs with several classes get one row each.
decision: fill in P31 or P279 (or leave empty = skip); suggest is only a hint from how the class is used.
"""
import argparse
import collections
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")


def plurals(word):
    w = word.lower()
    out = {w + "s", w + "es"}
    if w.endswith("y"):
        out.add(w[:-1] + "ies")
    if w.endswith("man"):
        out.add(w[:-3] + "men")
    return out


def typed(stub, parent):
    last = stub[:-len("_stubs")].split("_")[-1]
    return bool(plurals(last) & set(parent.split(">")[-1].lower().split("_")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", default="en")
    args = ap.parse_args()
    with open(os.path.join(OUT, f"stub_table_{args.wiki}.tsv"), encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh, delimiter="\t") if r["suggest"] and typed(r["stub"], r["parent"])]
    seen = collections.OrderedDict()
    for r in sorted(rows, key=lambda r: (-int(r["items"]), r["stub"])):
        seen.setdefault((r["stub"], r["class"]), r)
    n_classes = collections.Counter(s for s, _ in seen)
    path = os.path.join(OUT, f"review_{args.wiki}.tsv")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["stub", "items", "class", "label", "n_p31", "n_p279", "suggest", "several", "parent", "decision"])
        for (s, _), r in seen.items():
            w.writerow([s, r["items"], r["class"], r["label"], r["n_p31"], r["n_p279"], r["suggest"],
                        "1" if n_classes[s] > 1 else "", r["parent"], ""])
    print(f"{len(n_classes)} typed stubs, {len(seen)} rows, "
          f"{sum(int(seen[k]['items']) for k in seen if n_classes[k[0]] == 1)} items in single-class stubs -> {path}")


if __name__ == "__main__":
    main()
