"""Add ISBN publisher prefix (P3035) to publisher items that lack it.

Consumes data/p3035_backfill_candidates.tsv (built from the group-0/1 Wikipedia
ISBN-publisher-code lists, resolved to QIDs and heavily filtered). By default it
processes only the vetted set:

    safe_batch == "yes"  AND  registry != "unchecked"

i.e. clean single-publisher rows on a publisher-typed item, not a person, whose
prefix is not already on another QID, and (for the institutional slice) confirmed
against the ISBN-International registry. See ../../notes/isbn_bot.md for how the
candidate list and its filters were built.

For each row it adds `list_prefix` as a P3035 statement on `qid`, unless that
exact value is already present (idempotent). It never modifies existing P3035
statements.

Dry-run by default. Pass --save to actually edit (requires pywikibot auth).

    python projects/isbn_cleanup/backfill_p3035.py             # dry run, whole set
    python projects/isbn_cleanup/backfill_p3035.py --limit 5   # dry run, 5 items
    python projects/isbn_cleanup/backfill_p3035.py --all       # include unvetted rows too
    python projects/isbn_cleanup/backfill_p3035.py --save      # really edit
"""

import argparse
import csv
import random
import re
from pathlib import Path

import pywikibot

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd

HERE = Path(__file__).parent
DATA_FILE = HERE / "data" / "p3035_backfill_candidates.tsv"
OUTPUT_DIR = HERE / "output"
DONE_FILE = OUTPUT_DIR / "backfill_done.txt"
FAILED_FILE = OUTPUT_DIR / "backfill_failed.txt"

# Guard: a well-formed P3035 value (EAN + group + registrant), nothing more.
VALID_PREFIX = re.compile(r"^97[89]-\d{1,5}-\d{1,7}$")

site = pywikibot.Site("wikidata", "wikidata")
repo = site.data_repository()


def load_candidates(include_all: bool) -> list[tuple[str, str]]:
    """Return (qid, prefix) rows to process, in file order."""
    out = []
    with open(DATA_FILE, encoding="utf-8") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if not include_all and not (
                r["safe_batch"] == "yes" and r.get("registry", "") != "unchecked"
            ):
                continue
            prefix = r["list_prefix"].strip()
            if VALID_PREFIX.match(prefix):
                out.append((r["qid"], prefix))
    return out


def process_item(qid: str, prefix: str, edit_group: str, test: bool) -> str:
    """Add `prefix` as P3035 on `qid`. Returns 'added' | 'already' | 'no-change'."""
    item = pywikibot.ItemPage(repo, qid)
    page = cwd.WikiDataPage(item, test=test)
    page.edit_group = edit_group

    existing = {
        c.getTarget()
        for c in page.claims.get(wd.PID_ISBN_PUBLISHER_PREFIX, [])
        if isinstance(c.getTarget(), str)
    }
    if prefix in existing:
        return "already"

    page.add_statement(
        cwd.ExternalIDStatement("", wd.PID_ISBN_PUBLISHER_PREFIX, prefix)
    )
    page.summary = "add ISBN publisher prefix"
    return "added" if page.apply() else "no-change"


def load_processed() -> set:
    processed = set()
    for path in (DONE_FILE, FAILED_FILE):
        if path.exists():
            with open(path, encoding="utf-8") as f:
                processed |= {
                    line.split("\t", 1)[0].strip() for line in f if line.strip()
                }
    return processed


def append_line(path: Path, line: str) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Back-fill ISBN publisher prefix (P3035) from the candidate list."
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="really edit Wikidata and record results (default: dry run)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="stop after processing N not-yet-done items",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="process every row in the file, not just the vetted safe_batch set",
    )
    args = parser.parse_args()

    edit_group = f"{random.randrange(0, 2**48):x}"
    print(f"editgroup={edit_group} ({'SAVE' if args.save else 'dry run'})", flush=True)

    candidates = load_candidates(include_all=args.all)
    print(
        f"{len(candidates)} candidate row(s) "
        f"({'all rows' if args.all else 'vetted safe_batch set'})",
        flush=True,
    )

    done = load_processed()
    processed = 0
    for qid, prefix in candidates:
        if args.limit is not None and processed >= args.limit:
            break
        if qid in done:
            continue
        processed += 1
        print(f"{qid}  += P3035 {prefix}", flush=True)
        try:
            result = process_item(
                qid, prefix, edit_group=edit_group, test=not args.save
            )
        except Exception as e:
            pywikibot.error(f"Error on {qid}: {e}")
            if args.save:
                append_line(FAILED_FILE, f"{qid}\t{prefix}\t{str(e)[:400]}")
            continue
        print(f"  -> {result}", flush=True)
        if args.save:
            append_line(DONE_FILE, f"{qid}\t{prefix}\t{result}")
    print(f"Done: {processed} item(s) processed.", flush=True)


if __name__ == "__main__":
    main()
