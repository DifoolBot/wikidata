"""
call_bot.py

Debug entry point for the viaf_score bot.

Runs the full per-pair scoring pipeline (fetch both entities → build Person
objects → compute the six sub-scores → resolve the special label) against a
single QID pair, reusing the bot's real ``create_item`` so there is no logic
drift from a normal run.  Set a breakpoint anywhere in the score_* functions or
Person.examine and step through exactly one pair.

Two modes:
  - main()  → FILE mode: run the real page pipeline against a local wikitext
    file instead of the live page, and write the result to another file.  Use
    this to test on a small hand-made table (e.g. to check whether unscored
    rows are wrongly removed) without touching the wiki.
  - test()  → SINGLE-PAIR mode: score one LEFT/RIGHT QID pair and print the
    per-component breakdown plus the resulting Score-column label.

How to use:
  1. Edit the constants in the CONFIG block below.
  2. Run / debug this file.  In VS Code the bundled "Python Debugger: Current
     File" config works as-is (the .env file puts ``projects`` on PYTHONPATH).
     From a terminal:  ``cd projects && python -m viaf_score_upd.call_bot``

Notes:
  - Neither mode ever touches the wiki page.  FILE mode reads/writes local
    files; SINGLE-PAIR mode only reads entities.  To update the live page, run
    viaf_score.py itself (``python viaf_score.py [--rescore] [--dry-run]``).
  - VIAF / EXTERNAL_ID / PID feed the special-label logic (VIAF filled, Left has
    VIAF, Left external ID removed, …).  Leave the defaults if you only care
    about the numeric score; set them to reproduce a specific row's label.
"""

import logging
import os

from viaf_score_upd.viaf_score import (
    Person,
    create_item,
    score_bnf,
    score_birth_country,
    score_floruit,
    score_overlap_life,
    score_same_year,
)
import viaf_score_upd.viaf_score as viaf

# ── CONFIG: FILE mode (main) ──────────────────────────────────────────────────
# Paths are resolved relative to this file's directory unless absolute.
INPUT_FILE = "sample_in.txt"  # local wikitext to score
OUTPUT_FILE = "sample_out.txt"  # where the rebuilt wikitext is written
RESCORE = False  # True = recompute existing scores too
FIRST: int | None = 10  # score at most N rows across the page (None = all)
SKIP = 0  # skip the first M scorable rows first (window: FIRST 10 SKIP 0, ...)
ONLY_PID: str | None = None  # e.g. "P244" to update only that section (None = all)
REMOVE_DONE = False  # False = keep "done" rows so you can see what would be removed

# ── CONFIG: SINGLE-PAIR mode (test) ───────────────────────────────────────────
LEFT = "Q102214820"  # the "left" QID (the item with the VIAF cluster)
RIGHT = "Q113077361"  # the "right" QID (the candidate match)
PID = "P244"  # external-id property for this section (P214 = VIAF)
VIAF = ""  # VIAF id from the cluster (for the deprecated/filled labels)
EXTERNAL_ID = ""  # left's external id (for the "external ID removed" label)
# ─────────────────────────────────────────────────────────────────────────────

# Scoring recap (see viaf_score.py docstring):
#   same birth year   +5 / -1        same death year   +5 / -1
#   overlapping life   +1 / -100      same birth country +1 / -20
#   floruit mismatch    0 / -10       shared/other BnF   +2 / -2
# The special label (Redirect, VIAF filled, Different from, …) overrides the
# numeric score when it applies.


def _breakdown(left: Person, right: Person) -> None:
    """Print the six sub-scores the way compute_score sums them."""
    parts = [
        ("same birth year", score_same_year(left.birth_date, right.birth_date)),
        ("same death year", score_same_year(left.death_date, right.death_date)),
        ("overlap life", score_overlap_life(left, right)),
        ("birth country", score_birth_country(left, right)),
        ("floruit", score_floruit(left, right)),
        ("bnf", score_bnf(left, right)),
    ]
    for name, value in parts:
        print(f"    {name:<18} {value:+d}")
    print(f"    {'total':<18} {sum(v for _, v in parts):+d}")


def test() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    print(f"Scoring {LEFT} vs {RIGHT} | pid={PID}")

    # Per-component breakdown (skipped for redirects, mirroring create_item).
    left = Person(LEFT, PID)
    right = Person(RIGHT, PID)
    left.examine()
    right.examine()
    if left.is_redirect or right.is_redirect:
        print("  (redirect: sub-scores not computed)")
    else:
        _breakdown(left, right)

    # ↓↓↓ Set a breakpoint here, or inside create_item / any score_* ↓↓↓
    pair = create_item(LEFT, RIGHT, VIAF, PID, EXTERNAL_ID)

    if pair is None:
        print("  create_item failed (see warning above)")
        return
    print(f"  score cell -> {pair.text!r}  (raw score={pair.score})")


def _resolve(path: str) -> str:
    """Resolve *path* relative to this file's directory unless it's absolute."""
    if os.path.isabs(path):
        return path
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), path)


def test_file() -> None:
    """FILE mode: run the real pipeline over INPUT_FILE, write OUTPUT_FILE."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    in_path = _resolve(INPUT_FILE)
    out_path = _resolve(OUTPUT_FILE)

    with open(in_path, encoding="utf-8") as f:
        original = f.read()

    print(
        f"Scoring {in_path} | rescore={RESCORE} | first={FIRST} skip={SKIP} | "
        f"pid={ONLY_PID} | remove_done={REMOVE_DONE}"
    )

    # ↓↓↓ Set a breakpoint here, or inside score_wikitext / create_item ↓↓↓
    new_text = viaf.process_wikitext(
        original,
        rescore=RESCORE,
        first=FIRST,
        skip=SKIP,
        remove_done=REMOVE_DONE,
        only_pid=ONLY_PID,
    )

    if new_text is None:
        print("  no changes; writing the input through unchanged")
        new_text = original
    else:
        in_rows = sum(1 for ln in original.splitlines() if ln.strip() == "|-")
        out_rows = sum(1 for ln in new_text.splitlines() if ln.strip() == "|-")
        print(f"  data rows: {in_rows} in -> {out_rows} out")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(new_text)
    print(f"  wrote {out_path}")


def main() -> None:
    viaf.process_page(rescore=True, dry_run=False, remove_done=True, only_pid="P244")
    viaf.process_page(rescore=True, dry_run=False, remove_done=True, only_pid="P269")


if __name__ == "__main__":
    main()
