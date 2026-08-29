#!/usr/bin/env python3
"""review_to_wiki.py -- turn the viaf_deconflate review worklist
(``output/review.txt``) into wikitext: one sortable table per outcome, with QIDs
as {{Q|...}} and the deprecated VIAF value linked. Pure text -- no pywikibot.

The state file is tab-separated: QID<TAB>viaf_dep<TAB>outcome<TAB>date<TAB>detail
(see record_state in deconflate.py). Any *.txt in that shape works, so you can
also point it at output/done.txt for an edit log.

Usage:
    python projects/viaf_deconflate/review_to_wiki.py            # -> stdout
    python projects/viaf_deconflate/review_to_wiki.py --out review.wiki
    python projects/viaf_deconflate/review_to_wiki.py output/done.txt
"""
import argparse
from collections import OrderedDict
from pathlib import Path

DEFAULT_REVIEW = Path(__file__).resolve().parent / "output" / "review.txt"

# Outcomes shown first (most attention needed); anything else follows, as-seen.
ORDER = [
    "NEW_CLUSTER_CONFLATED", "AMBIGUOUS_SHARED_ID", "DUPLICATE_RANK",
    "INCONSISTENT", "PROBABLY_CONFLATED", "CORRECT_AS_OF_NOW",
    "LIST_REDIRECT", "LIST_ABANDONED", "INSUFFICIENT",
]


def parse(path: str) -> list[tuple[str, str, str, str, str]]:
    """Rows of (qid, viaf_dep, outcome, date, detail) from a state file."""
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 3 or not parts[0].startswith("Q"):
                continue
            qid, dep, outcome = parts[0].strip(), parts[1].strip(), parts[2].strip()
            date = parts[3].strip() if len(parts) > 3 else ""
            detail = parts[4].strip() if len(parts) > 4 else ""
            rows.append((qid, dep, outcome, date, detail))
    return rows


def _cell(text: str) -> str:
    """Clean a detail for a wikitable cell: drop the ", needs a human" tail (the
    whole page is a review worklist), say "normal rank" rather than "live" /
    "not-deprecated", and guard the pipe."""
    return (text.replace(", needs a human", "")
                .replace("value is live", "value is normal rank")
                .replace("value is not-deprecated", "value is normal rank")
                .replace("live VIAF", "normal rank VIAF")
                .replace("|", "{{!}}").strip())


def _viaf(value: str) -> str:
    return f"[https://viaf.org/viaf/{value}/ {value}]" if value else ""


def to_wiki(rows: list[tuple[str, str, str, str, str]]) -> str:
    groups: "OrderedDict[str, list]" = OrderedDict()
    for r in rows:
        groups.setdefault(r[2], []).append(r)
    keys = [o for o in ORDER if o in groups] + [o for o in groups if o not in ORDER]

    out = [f"Review worklist &mdash; {len(rows)} item(s), "
           f"generated from <code>output/review.txt</code>.", ""]
    for outcome in keys:
        g = sorted(groups[outcome], key=lambda r: int(r[0][1:]))
        out.append(f"== {outcome} ({len(g)}) ==")
        out.append('{| class="wikitable sortable"')
        out.append("! # !! Item !! Deprecated VIAF !! Details !! Date")
        for i, (qid, dep, _o, date, detail) in enumerate(g, 1):
            out.append("|-")
            out.append(f"| {i} || {{{{Q|{qid}}}}} || {_viaf(dep)} || "
                       f"{_cell(detail)} || {date}")
        out.append("|}")
        out.append("")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("review", nargs="?", default=str(DEFAULT_REVIEW),
                    help="state file to read (default: output/review.txt)")
    ap.add_argument("--out", default=None, help="write wikitext here (else stdout)")
    args = ap.parse_args()

    if not Path(args.review).exists():
        print(f"no such file: {args.review}")
        return
    rows = parse(args.review)
    wiki = to_wiki(rows)
    if args.out:
        Path(args.out).write_text(wiki, encoding="utf-8")
        print(f"wrote {len(rows)} row(s) to {args.out}")
    else:
        print(wiki)


if __name__ == "__main__":
    main()
