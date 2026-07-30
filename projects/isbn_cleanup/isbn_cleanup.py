"""Fix malformed ISBN publisher prefix (P3035) statements on Wikidata.

P3035 must hold *only* an ISBN registrant prefix -- `978-<group>-<registrant>`,
no publication element and no check digit. A survey of every P3035 value found
~74 that violate the format constraint, in three shapes:

  * MOVE_ISBN   -- a full, valid ISBN was pasted into P3035 on a book/work item
                   (e.g. 9780008568207 on "The Beast and the Bethany"). P3035 is
                   the wrong property; the ISBN belongs in P212. The bot adds
                   P212 with canonical hyphenation (via stdnum) and removes the
                   bogus P3035 -- a *move*, so the ISBN is preserved, not lost.
  * FIXPREFIX   -- a correct registrant prefix whose only defect is non-ASCII
                   dash characters (e.g. U+2010 in "978‐0‐9747077"); the
                   value is normalised to ASCII hyphens in place, staying in P3035.
  * PUBLISHER   -- a real publisher item whose prefix is truncated/garbled
                   ("978-5", "608"). P3035 is the right property but the value
                   needs a human decision.
  * OTHER       -- two ISBNs in one field, "ISBN : ..." literal text, etc.

The MOVE and FIXPREFIX cases are automated; everything else is logged to
review.txt untouched. A value is treated as a movable ISBN only when stdnum says it is a
valid ISBN (check digit included) AND the target item is a bibliographic entity
(or untyped) -- never a publisher, person, or organisation, where adding P212
would itself be wrong.

Dry-run by default. Pass --save to actually edit (requires pywikibot auth).

    python projects/isbn_cleanup/isbn_cleanup.py               # dry run, whole list
    python projects/isbn_cleanup/isbn_cleanup.py --limit 5     # dry run, 5 items
    python projects/isbn_cleanup/isbn_cleanup.py --qid Q123    # one item, even if done
    python projects/isbn_cleanup/isbn_cleanup.py --save        # really edit
    python projects/isbn_cleanup/isbn_cleanup.py --fetch-items # rebuild input/items.tsv
"""

import argparse
import random
import re
from pathlib import Path

import pywikibot
import requests
from stdnum import isbn as stdnum_isbn

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd

# QLever moved off qlever.cs.uni-freiburg.de; the old host 308-redirects to a
# URL without the query string, so hit the new host directly.
QLEVER_URL = "https://qlever.dev/api/wikidata"
USER_AGENT = "DifoolBot/1.0 (https://www.wikidata.org/wiki/User:DifoolBot)"

# A well-formed P3035 value: EAN + group (1-5 digits) + registrant (1-7 digits),
# nothing more. Deliberately looser than the full P3035 constraint regex, but a
# superset of it, so anything matching here is left untouched.
VALID_PREFIX = re.compile(r"^97[89]-\d{1,5}-\d{1,7}$")

# Non-ASCII dash/hyphen characters that show up in ISBN values pasted from word
# processors or web pages. They make an otherwise-correct value fail the format
# constraint, so normalise them to the ASCII hyphen-minus before anything else.
DASHES = "‐‑‒–—―−⁃﹘﹣－"


def normalize_dashes(value: str) -> str:
    return "".join("-" if ch in DASHES else ch for ch in value)

# Item P31 types for which a stray full ISBN safely belongs in P212. If an item
# carries any P31 outside this set (publisher, human, organisation, ...) the
# value is sent to review instead of moved. Verified 2026-07-26.
BIBLIOGRAPHIC_TYPES = {
    "Q571",       # book
    "Q7725634",   # literary work
    "Q47461344",  # written work
    "Q732577",    # publication
    "Q3331189",   # version, edition or translation
    "Q1261026",   # printed matter
    "Q13136",     # reference work
    "Q193495",    # monograph
    "Q87167",     # manuscript
    "Q35760",     # essay
}

HERE = Path(__file__).parent
ITEMS_FILE = HERE / "input" / "items.tsv"
OUTPUT_DIR = HERE / "output"
DONE_FILE = OUTPUT_DIR / "done.txt"
FAILED_FILE = OUTPUT_DIR / "failed.txt"
REVIEW_FILE = OUTPUT_DIR / "review.txt"

site = pywikibot.Site("wikidata", "wikidata")
repo = site.data_repository()


def compact_isbn(value: str) -> str | None:
    """stdnum.compact, but None instead of raising on junk input."""
    try:
        return stdnum_isbn.compact(value)
    except Exception:
        return None


def canonical_isbn13(value: str) -> str | None:
    """Return the hyphenated ISBN-13 for a value stdnum accepts as a valid ISBN
    (10 or 13), else None. The check digit is validated, so a wrong number is
    rejected rather than silently reformatted."""
    try:
        if not stdnum_isbn.is_valid(value):
            return None
        return stdnum_isbn.format(stdnum_isbn.to_isbn13(stdnum_isbn.compact(value)))
    except Exception:
        return None


def classify(value: str, p31: set[str], existing_isbn13: set[str]):
    """Return (action, detail). action is one of:
    'skip'      -- already a well-formed prefix, leave it;
    'fixprefix' -- a well-formed prefix except for non-ASCII dashes; set to <detail>;
    'move'      -- add P212 <detail> and remove this P3035;
    'drop'      -- P212 <detail> already present, just remove this P3035;
    'review'    -- log for a human, touch nothing.
    """
    original = value.strip()
    value = normalize_dashes(original)
    if VALID_PREFIX.match(value):
        # A genuine prefix; the only defect (if any) is exotic dash characters.
        return ("fixprefix", value) if value != original else ("skip", None)

    isbn13 = canonical_isbn13(value)
    if not isbn13:
        return "review", "not a valid ISBN"

    # A valid ISBN, but only movable onto a bibliographic (or untyped) item.
    if not p31 <= BIBLIOGRAPHIC_TYPES:
        return "review", f"valid ISBN but non-bibliographic item ({sorted(p31)})"

    if stdnum_isbn.compact(isbn13) in existing_isbn13:
        return "drop", isbn13
    return "move", isbn13


def process_item(item_id, edit_group: str, test: bool) -> tuple[bool, list[str]]:
    """Returns (changed, review_lines)."""
    item = pywikibot.ItemPage(repo, item_id)
    page = cwd.WikiDataPage(item, test=test)
    page.edit_group = edit_group
    reviews: list[str] = []

    prefixes = page.claims.get(wd.PID_ISBN_PUBLISHER_PREFIX, [])
    if not prefixes:
        return False, reviews

    p31 = {
        c.getTarget().getID()
        for c in page.claims.get("P31", [])
        if c.getTarget()
    }
    existing_isbn13: set[str] = set()
    for existing in page.claims.get(wd.PID_ISBN_13, []):
        target = existing.getTarget()
        if isinstance(target, str):
            comp = compact_isbn(target)
            if comp is not None:
                existing_isbn13.add(comp)

    did = set()
    for claim in prefixes:
        value = claim.getTarget()
        if not isinstance(value, str):
            continue
        action, detail = classify(value, p31, existing_isbn13)
        if action == "skip":
            continue
        if action == "review":
            reviews.append(f"{item_id}\t{value}\t{detail}")
            continue
        assert detail is not None  # skip/review handled above; detail is now a value
        if action == "fixprefix":
            # Correct prefix, wrong hyphen characters: fix in place, stay in P3035.
            print(f"  fix hyphens {value!r} -> {detail!r}", flush=True)
            page.change_claim(wd.PID_ISBN_PUBLISHER_PREFIX, claim, detail)
            did.add("fix")
            continue
        if action == "move":
            # copy P3035 -> P212 with the salvaged ISBN, keeping refs, delete P3035
            print(f"  move {value!r} -> P212 {detail}  (references kept)", flush=True)
            page.copy_claim(
                old_pid=wd.PID_ISBN_PUBLISHER_PREFIX, new_pid=wd.PID_ISBN_13,
                new_qid=None, claim_snak=claim.snak, delete_old=True,
                callback=None, new_value=detail,
            )
            existing_isbn13.add(stdnum_isbn.compact(detail))
        else:  # drop: P212 already present, just remove the malformed P3035
            print(f"  drop {value!r} (P212 {detail} already present)", flush=True)
            page.remove_property(wd.PID_ISBN_PUBLISHER_PREFIX, claim)
        did.add("move")

    page.summary = (
        "normalize ISBN publisher prefix hyphens"
        if did == {"fix"}
        else "move misfiled ISBN"
    )
    return page.apply(), reviews


def fetch_and_fill_items() -> int:
    """Query QLever for every P3035 value that fails the prefix format and write
    `QID<TAB>value` lines to ITEMS_FILE (newest item first)."""
    query = """PREFIX wdt: <http://www.wikidata.org/prop/direct/>
SELECT ?item ?prefix WHERE {
  ?item wdt:P3035 ?prefix .
  FILTER(!REGEX(STR(?prefix), "^97[89]-[0-9]{1,5}-[0-9]{1,7}$"))
}"""
    resp = requests.get(
        QLEVER_URL,
        params={"query": query},
        headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"},
        timeout=300,
    )
    resp.raise_for_status()
    rows = []
    for b in resp.json().get("results", {}).get("bindings", []):
        qid = b["item"]["value"].rsplit("/", 1)[-1]
        if qid.startswith("Q"):
            rows.append((qid, b["prefix"]["value"]))
    rows.sort(key=lambda r: int(r[0][1:]), reverse=True)
    ITEMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    # The value column is informational only (processing re-reads the item
    # live), and some malformed prefixes contain bytes that decode to lone
    # surrogates, so write defensively rather than crash the whole fetch.
    ITEMS_FILE.write_text(
        "".join(f"{qid}\t{value}\n" for qid, value in rows),
        encoding="utf-8",
        errors="replace",
    )
    print(f"Wrote {len(rows)} items to {ITEMS_FILE}")
    return len(rows)


def load_items_from_file(filename):
    with open(filename, encoding="utf-8") as f:
        return [line.split("\t", 1)[0].strip() for line in f if line.strip()]


def load_processed() -> set:
    processed = set()
    for path in (DONE_FILE, FAILED_FILE):
        if path.exists():
            with open(path, encoding="utf-8") as f:
                processed |= {line.split("\t", 1)[0].strip() for line in f if line.strip()}
    return processed


def load_review_qids() -> list[str]:
    """Unique QIDs recorded in review.txt (first tab-field), in file order."""
    if not REVIEW_FILE.exists():
        return []
    seen: set[str] = set()
    qids: list[str] = []
    with open(REVIEW_FILE, encoding="utf-8") as f:
        for line in f:
            qid = line.split("\t", 1)[0].strip()
            if qid and qid not in seen:
                seen.add(qid)
                qids.append(qid)
    return qids


def append_line(path: Path, line: str) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fix malformed ISBN publisher prefix (P3035) statements."
    )
    parser.add_argument("--save", action="store_true",
                        help="really edit Wikidata and record results (default: dry run)")
    parser.add_argument("--limit", type=int, metavar="N",
                        help="stop after processing N not-yet-done items")
    parser.add_argument("--qid", action="append", default=[], metavar="QID",
                        help="process only this QID, even if already processed (repeatable)")
    parser.add_argument("--fetch-items", action="store_true",
                        help=f"regenerate {ITEMS_FILE.name} from QLever and exit")
    parser.add_argument("--recheck-review", action="store_true",
                        help="re-run every QID currently in review.txt (with --save, "
                             "review.txt is rebuilt so it reflects the new results)")
    args = parser.parse_args()

    if args.fetch_items:
        fetch_and_fill_items()
        return

    edit_group = f"{random.randrange(0, 2**48):x}"
    print(f"editgroup={edit_group} ({'SAVE' if args.save else 'dry run'})", flush=True)

    if args.recheck_review:
        items = load_review_qids()
        force = True  # bypass the done.txt skip; these were logged as done
        print(f"Rechecking {len(items)} item(s) from {REVIEW_FILE.name}", flush=True)
        # A --save recheck re-logs current-state review lines, so start the file
        # empty; otherwise resolved items would keep their stale review entries.
        if args.save:
            REVIEW_FILE.write_text("", encoding="utf-8")
    else:
        force = bool(args.qid)
        items = args.qid or load_items_from_file(ITEMS_FILE)
    done = load_processed()
    processed = 0
    for qid in items:
        if args.limit is not None and processed >= args.limit:
            break
        if not force and qid in done:
            continue
        print(f"Processing {qid} ...", flush=True)
        processed += 1
        try:
            changed, reviews = process_item(qid, edit_group=edit_group, test=not args.save)
        except Exception as e:
            pywikibot.error(f"Error processing {qid}: {e}")
            if args.save:
                message = str(e).replace("\n", " ").replace("\t", " ")[:500]
                append_line(FAILED_FILE, f"{qid}\t{message}")
            continue
        for line in reviews:
            print(f"  REVIEW {line}", flush=True)
        # Dry runs record nothing, so they never block a later --save.
        if args.save:
            for line in reviews:
                append_line(REVIEW_FILE, line)
            note = "changed" if changed else "no-change"
            if reviews:
                note += f", review ({len(reviews)}x)"
            append_line(DONE_FILE, f"{qid}\t{note}")
    print(f"Done: {processed} item(s) processed.", flush=True)


if __name__ == "__main__":
    main()
