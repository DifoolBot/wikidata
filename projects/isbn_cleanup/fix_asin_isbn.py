"""Record the ISBN of items whose ISBN lives only in the ASIN field (P5749).

For a print book, Amazon's ASIN *is* the ISBN-10 (the ASIN was designed ISBN-compatible),
so older self-published books often have their ISBN-10 stored as P5749 (ASIN) and nowhere
else. This bot finds items with a **single** ISBN-10-shaped P5749 value and **no** ISBN-13
(P212) / ISBN-10 (P957), validates the value as a real ISBN-10, and records it properly:
adds **P957** (the ISBN-10) and **P212** (the derived ISBN-13). The redundant-but-valid
ASIN is left untouched (no community consensus to remove ISBN-10s from P5749).

Deliberately out of scope:
  * items with **more than one** ISBN-10-shaped ASIN -> skipped (ambiguous, logged);
  * P5749 values that **don't validate** as an ISBN-10 (genuine numeric ASINs) -> skipped,
    logged for review, never touched;
  * splitting MIX (conflated work+version) items into a work + editions -> a later task.

Dry-run by default. Pass --save to actually edit (requires pywikibot auth).

    python projects/isbn_cleanup/fix_asin_isbn.py            # dry run, whole list
    python projects/isbn_cleanup/fix_asin_isbn.py --limit 5  # dry run, 5 items
    python projects/isbn_cleanup/fix_asin_isbn.py --qid Q123 # one item, even if done
    python projects/isbn_cleanup/fix_asin_isbn.py --save     # really edit
"""

import argparse
import hashlib
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

import pywikibot
import requests
from stdnum import isbn as stdnum_isbn

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd

QLEVER_URL = "https://qlever.dev/api/wikidata"
USER_AGENT = "DifoolBot/1.0 (https://www.wikidata.org/wiki/User:DifoolBot)"
ISBN10_RE = re.compile(r"^[0-9]{9}[0-9X]$")

HERE = Path(__file__).parent
OUTPUT_DIR = HERE / "output"
DONE_FILE = OUTPUT_DIR / "asin_isbn_done.txt"
FAILED_FILE = OUTPUT_DIR / "asin_isbn_failed.txt"
REVIEW_FILE = OUTPUT_DIR / "asin_isbn_review.txt"

site = pywikibot.Site("wikidata", "wikidata")
repo = site.data_repository()


def daily_editgroup(tag: str) -> str:
    return hashlib.sha1(f"{tag}:{date.today().isoformat()}".encode()).hexdigest()[:12]


def isbn10_asins(claims) -> list[str]:
    """ISBN-10-shaped P5749 values on a claims mapping (real B0 ASINs excluded)."""
    out = []
    for c in claims.get(wd.PID_AMAZON_STANDARD_IDENTIFICATION_NUMBER, []):
        v = c.getTarget()
        if isinstance(v, str) and ISBN10_RE.match(v):
            out.append(v)
    return out


def fetch_candidates() -> dict:
    """{qid: [isbn10-shaped ASIN values]} for items with such a P5749 and no P212/P957."""
    query = """PREFIX wdt: <http://www.wikidata.org/prop/direct/>
SELECT ?item ?v WHERE {
  ?item wdt:P5749 ?v .
  FILTER(REGEX(?v, "^[0-9]{9}[0-9X]$"))
  FILTER NOT EXISTS { ?item wdt:P212 ?a }
  FILTER NOT EXISTS { ?item wdt:P957 ?b }
}
ORDER BY ?item"""
    r = requests.post(QLEVER_URL, data={"query": query},
                      headers={"User-Agent": USER_AGENT, "Accept": "text/tab-separated-values"},
                      timeout=180)
    r.raise_for_status()
    out = defaultdict(list)
    for line in r.text.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        qid = parts[0].strip().rsplit("/", 1)[-1].rstrip(">")
        val = parts[1].strip().strip('"')
        if qid.startswith("Q") and ISBN10_RE.match(val):
            out[qid].append(val)
    return out


def process_item(qid: str, asin: str, edit_group: str, test: bool) -> tuple[bool, str | None]:
    """Add P957 (ISBN-10) + P212 (ISBN-13) derived from the ASIN. Returns
    (changed, review_reason). review_reason set (nothing edited) when the value isn't a
    valid ISBN-10, or the item already has an ISBN now."""
    item = pywikibot.ItemPage(repo, qid)
    page = cwd.WikiDataPage(item, test=test)
    page.edit_group = edit_group

    if page.claims.get(wd.PID_ISBN_13) or page.claims.get(wd.PID_ISBN_10):
        return False, "already has an ISBN (P212/P957) now -- skip"

    comp = stdnum_isbn.compact(asin)
    if len(comp) != 10 or not stdnum_isbn.is_valid(comp):
        return False, f"P5749 {asin} is not a valid ISBN-10 (likely a genuine ASIN)"

    isbn10 = stdnum_isbn.format(comp)
    isbn13 = stdnum_isbn.format(stdnum_isbn.to_isbn13(comp))

    print(f"  P5749 {asin} -> +P957 {isbn10}  +P212 {isbn13}", flush=True)
    c10 = pywikibot.Claim(repo, wd.PID_ISBN_10)
    c10.setTarget(isbn10)
    page.add_claim(wd.PID_ISBN_10, c10)
    c13 = pywikibot.Claim(repo, wd.PID_ISBN_13)
    c13.setTarget(isbn13)
    page.add_claim(wd.PID_ISBN_13, c13)
    page.summary = "add ISBN (P212/P957) from the ISBN-10 stored as ASIN (P5749)"
    return page.apply(), None


def load_processed() -> set:
    processed = set()
    for path in (DONE_FILE, FAILED_FILE):
        if path.exists():
            with open(path, encoding="utf-8") as f:
                processed |= {line.split("\t", 1)[0].strip() for line in f if line.strip()}
    return processed


def append_line(path: Path, line: str) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Add ISBN (P212/P957) from an ISBN-10 stored as ASIN (P5749).")
    parser.add_argument("--save", action="store_true",
                        help="really edit Wikidata and record results (default: dry run)")
    parser.add_argument("--limit", type=int, metavar="N", help="stop after N not-yet-done items")
    parser.add_argument("--qid", action="append", default=[], metavar="QID",
                        help="process only this QID, even if already processed (repeatable)")
    parser.add_argument("--editgroup", metavar="ID",
                        help="override the batch id (default: a stable per-day id)")
    args = parser.parse_args()

    edit_group = args.editgroup or daily_editgroup("fix_asin_isbn")
    kind = "override" if args.editgroup else "daily; groups today's runs"
    print(f"editgroup={edit_group} ({kind}) ({'SAVE' if args.save else 'dry run'})", flush=True)

    if args.qid:
        cands = {}
        for q in args.qid:
            it = pywikibot.ItemPage(repo, q)
            it.get()
            cands[q] = isbn10_asins(it.claims)
        force = True
    else:
        cands = fetch_candidates()
        print(f"{len(cands)} item(s) with an ISBN-10-shaped ASIN and no P212/P957", flush=True)
        force = False

    done = load_processed()
    processed = edited = skipped_multi = review = 0
    for qid, vals in cands.items():
        if args.limit is not None and processed >= args.limit:
            break
        if not force and qid in done:
            continue
        if len(vals) != 1:
            # duplicate / no ISBN-10-shaped ASIN -> ambiguous, leave out
            skipped_multi += 1
            print(f"Skipping {qid}: {len(vals)} ISBN-10 ASIN(s) {vals} -- ambiguous", flush=True)
            if args.save:
                append_line(REVIEW_FILE, f"{qid}\tmultiple/none ISBN-10 ASINs: {vals}")
            continue
        print(f"Processing {qid} ...", flush=True)
        processed += 1
        try:
            changed, reason = process_item(qid, vals[0], edit_group=edit_group, test=not args.save)
        except Exception as e:
            pywikibot.error(f"Error on {qid}: {e}")
            if args.save:
                append_line(FAILED_FILE, f"{qid}\t{str(e)[:400]}")
            continue
        if reason:
            review += 1
            print(f"  REVIEW {qid}: {reason}", flush=True)
        else:
            edited += 1
        if args.save:
            if reason:
                append_line(REVIEW_FILE, f"{qid}\t{reason}")
            else:
                append_line(DONE_FILE, f"{qid}\t{'changed' if changed else 'no-change'}")
    print(f"Done: {processed} processed -> {edited} would-add ISBN, {review} review "
          f"(not a valid ISBN-10); {skipped_multi} skipped (multiple ASINs).", flush=True)


if __name__ == "__main__":
    main()
