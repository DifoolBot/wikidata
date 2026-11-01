"""United States House and Senate committee articles -> the model of the user's golden examples.

  python congress.py [--wiki en] [--min-age-days 180]
  in:  output/items_<wiki>.tsv, output/opening_<wiki>.tsv, output/done_<wiki>.txt (skipped)
  out: output/qs_<wiki>_congress_all.txt (QS v1) + congress_review.tsv (qid, why, title, opening)

Model (user 2026-10-31):
- committee: United States House Committee on the Judiciary (Q1131462), P31 United States congressional committee +
  P17 United States + P361 the chamber.
- subcommittee: United States Senate Appropriations Subcommittee on Defense (Q7891225), P31 United States congressional
  subcommittee + P17 United States + P361 the committee, the enwiki article PARENT of the name in the title.
Anything else with the same start (journals, offices, caucuses, a court case) goes to the review file.
"""
import argparse
import datetime as dt
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from history import enwiki_items  # noqa: E402
from make_qs import first_revision  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
COMMITTEE, SUBCOMMITTEE, USA = "Q476190", "Q7892394", "Q30"
CHAMBER = {"House": "Q11701", "Senate": "Q66096"}
SUB = re.compile(r"^United States (House|Senate) (.+?) Subcommittee\b")
COM = re.compile(r"^United States (House|Senate) (?:(?:Permanent )?Select |Special )?Committee (?:on|to) ")
PARENT = {
    ("House", "Oversight"): "Oversight and Government Reform",
    ("House", "Oversight and Government Reform"): "Oversight and Government Reform",
    ("House", "Appropriations"): "Appropriations", ("House", "Armed Services"): "Armed Services",
    ("House", "Foreign Affairs"): "Foreign Affairs", ("House", "Agriculture"): "Agriculture",
    ("House", "Financial Services"): "Financial Services", ("House", "Judiciary"): "the Judiciary",
    ("House", "Education"): "Education and Workforce", ("House", "Energy"): "Energy and Commerce",
    ("House", "Homeland Security"): "Homeland Security", ("House", "Natural Resources"): "Natural Resources",
    ("House", "Science"): "Science, Space, and Technology", ("House", "Small Business"): "Small Business",
    ("House", "Veterans' Affairs"): "Veterans' Affairs", ("House", "Ways and Means"): "Ways and Means",
    ("House", "Transportation"): "Transportation and Infrastructure",
    ("House", "Administration"): "House Administration", ("House", "Rules"): "Rules",
    ("Senate", "Appropriations"): "Appropriations", ("Senate", "Judiciary"): "the Judiciary",
    ("Senate", "Foreign Relations"): "Foreign Relations", ("Senate", "Armed Services"): "Armed Services",
    ("Senate", "Banking"): "Banking, Housing, and Urban Affairs",
    ("Senate", "Commerce"): "Commerce, Science, and Transportation",
    ("Senate", "Agriculture"): "Agriculture, Nutrition, and Forestry",
    ("Senate", "Environment and Public Works"): "Environment and Public Works",
    ("Senate", "Environment"): "Environment and Public Works", ("Senate", "Finance"): "Finance",
    ("Senate", "Energy"): "Energy and Natural Resources",
    ("Senate", "Homeland Security"): "Homeland Security and Governmental Affairs",
    ("Senate", "Health"): "Health, Education, Labor, and Pensions",
}
INTELLIGENCE = "United States House Permanent Select Committee on Intelligence"


def parent_title(chamber, name):
    if (chamber, name) == ("House", "Intelligence"):
        return INTELLIGENCE
    if (chamber, name) in PARENT:
        return f"United States {chamber} Committee on {PARENT[chamber, name]}"
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", default="en")
    ap.add_argument("--min-age-days", type=int, default=180)
    args = ap.parse_args()
    with open(os.path.join(OUT, f"items_{args.wiki}.tsv"), encoding="utf-8") as fh:
        title = dict(line.rstrip("\n").split("\t", 1) for line in fh if "\t" in line)
    with open(os.path.join(OUT, f"done_{args.wiki}.txt"), encoding="utf-8") as fh:
        done = {line.strip() for line in fh if line.strip()}
    cand = [q for q, t in title.items() if re.match(r"United States (House|Senate)", t) and q not in done]
    opening = {}
    with open(os.path.join(OUT, f"opening_{args.wiki}.tsv"), encoding="utf-8") as fh:
        for line in fh:
            q, text = line.rstrip("\n").split("\t", 1)
            opening[q] = text
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.min_age_days)).strftime("%Y%m%d%H%M%S")
    first = first_revision(cand)
    parents = {parent_title(*SUB.match(title[q]).groups()) for q in cand if SUB.match(title[q])} - {""}
    target = enwiki_items(sorted(parents))
    lines, notes, count = [], [], {"committee": 0, "subcommittee": 0}
    for q in sorted(cand, key=lambda x: int(x[1:])):
        t, s = title[q], opening.get(q, "")

        def note(why):
            notes.append((q, why, t, s[:150]))

        if first.get(q, "9") > cutoff:
            note("too new")
        elif re.search(r"\b(?:may|can|could) refer to\b", s[:200]):
            note("may refer to")
        elif m := SUB.match(t):
            parent = target.get(parent_title(*m.groups()))
            if not parent:
                note(f"no parent committee for '{m.group(2)}'")
            elif parent[1] == q:
                note("the parent is the item itself")
            else:
                lines += [f"{q}\tP31\t{SUBCOMMITTEE}\n", f"{q}\tP17\t{USA}\n", f"{q}\tP361\t{parent[1]}\n"]
                count["subcommittee"] += 1
        elif m := COM.match(t):
            lines += [f"{q}\tP31\t{COMMITTEE}\n", f"{q}\tP17\t{USA}\n", f"{q}\tP361\t{CHAMBER[m.group(1)]}\n"]
            count["committee"] += 1
        else:
            note("not a committee title")
    with open(os.path.join(OUT, f"qs_{args.wiki}_congress_all.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(lines)
    with open(os.path.join(OUT, "congress_review.tsv"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("qid\twhy\ttitle\topening\n")
        fh.writelines("\t".join(n) + "\n" for n in sorted(notes, key=lambda n: n[1]))
    print(f"{len(cand)} titles; {count['committee']} committees, {count['subcommittee']} subcommittees; "
          f"{len(notes)} in review; {len(lines)} QS lines -> qs_{args.wiki}_congress_all.txt")


if __name__ == "__main__":
    main()
