"""clean_pd_works -- move edition-level publisher (P123) off public-domain *work* items.

Target 2 of the ISBN initiative: improve existing copyright-free book items by taking
edition-level statements off the FRBR *work* and leaving them on the *edition*.

Scope & why it's narrow. A measurement (2026-07-30) of works (items with P747 "has
edition or translation") that also carry an edition-level property directly found
~24,550 overall, ~1,061 of them public-domain (author died <= 1930). On the PD subset
the misplaced property is almost entirely **P123 (publisher)** -- 1,037 of them; real
ISBN/ASIN/format on the work are a handful each. So this bot only touches P123 on PD
works.

Even then, only ONE bucket is safe to auto-edit:

  C. a linked edition ALREADY carries the *same* P123 value  -> DROP it from the work.
     No judgement, no data loss: the value stays on the edition where it belongs (this
     is the Iamcarbon work/edition-split residue -- publisher left on both levels).
     Measured ~379 items. Verified pattern e.g. Q101423388 "Synopsis Filicum": work and
     edition Q101423389 both hold P123 = Robert Hardwicke (Q18576913).

Everything else is REVIEW, because it needs a human:
  B. exactly 1 edition and it has NO P123 -> looks moveable, but a PD work's P123 is
     often the *original* publisher while the single edition is a modern reprint; moving
     the wrong publisher onto it is worse than leaving it. Human must confirm the match.
  D. multiple editions -> which edition does the publisher belong to? Ambiguous.

Same skeleton as mark_selfpublished / fix_isbn_violations: dry-run default, --save,
--qid/--file, --limit, stable per-day editgroup, text-file state. Reuses
mark_selfpublished's live()/linked_editions() and constants. See notes/isbn_bot.md.
"""
import argparse
import hashlib
from datetime import date
from pathlib import Path

import pywikibot
import requests

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
import mark_selfpublished as msp  # reuse live()/linked_editions() + page conventions

QLEVER_URL = "https://qlever.dev/api/wikidata"
USER_AGENT = "DifoolBot/1.0 (https://www.wikidata.org/wiki/User:DifoolBot)"
PREFIXES = ("PREFIX wdt: <http://www.wikidata.org/prop/direct/>\n"
            "PREFIX wd: <http://www.wikidata.org/entity/>\n")

# Author dead by this year => the work is almost certainly public domain (life+70 with a
# safe margin; 2026-70 = 1956, so 1930 is deliberately conservative). Widen via --death-year.
DEFAULT_DEATH_YEAR = 1930

HERE = Path(__file__).parent
OUTPUT_DIR = HERE / "output"
DONE_FILE = OUTPUT_DIR / "pd_works_done.txt"
FAILED_FILE = OUTPUT_DIR / "pd_works_failed.txt"
REVIEW_FILE = OUTPUT_DIR / "pd_works_review.txt"
REPORT_FILE = OUTPUT_DIR / "pd_works_dryrun.txt"  # rewritten fresh each dry run

repo = msp.repo


def fetch_candidates(death_year: int) -> list[str]:
    """PD works carrying a publisher (P123) directly on the work item."""
    query = f"""SELECT DISTINCT ?item WHERE {{
  ?item wdt:{wd.PID_HAS_EDITION_OR_TRANSLATION} ?ed .
  ?item wdt:{wd.PID_PUBLISHER} ?pub .
  ?item wdt:{wd.PID_AUTHOR} ?a . ?a wdt:{wd.PID_DATE_OF_DEATH} ?dod .
  FILTER(YEAR(?dod) <= {death_year})
}}
ORDER BY ?item"""
    r = requests.post(QLEVER_URL, data={"query": PREFIXES + query},
                      headers={"User-Agent": USER_AGENT, "Accept": "text/tab-separated-values"},
                      timeout=300)
    r.raise_for_status()
    qids = []
    for line in r.text.splitlines()[1:]:
        qid = line.strip().rsplit("/", 1)[-1].rstrip(">")
        if qid.startswith("Q"):
            qids.append(qid)
    return qids


def _value_id(target):
    return target.getID() if hasattr(target, "getID") else target


def edition_holding(editions, pid: str, vstr: str) -> str | None:
    """QID of a linked edition that already carries pid=vstr (else None)."""
    for e in editions:
        for c in msp.live(e.claims.get(pid, [])):
            if c.getTarget() and _value_id(c.getTarget()) == vstr:
                return e.getID()
    return None


def process_item(qid: str, edit_group: str, test: bool) -> tuple[bool, str | None, str | None]:
    """Returns (changed, review_reason, action). Auto-drops only bucket-C publishers."""
    item = pywikibot.ItemPage(repo, qid)
    page = cwd.WikiDataPage(item, test=test)
    page.edit_group = edit_group

    editions = msp.linked_editions(page)
    if not editions:  # discovery guarantees P747, but a value may be deprecated
        return False, "no live edition (P747) -- not a work split", None

    ed_ids = ", ".join(e.getID() for e in editions)
    dropped, reasons = [], []
    for c in msp.live(page.claims.get(wd.PID_PUBLISHER, [])):
        if not c.getTarget():
            continue
        vstr = _value_id(c.getTarget())
        holder = edition_holding(editions, wd.PID_PUBLISHER, vstr)
        if holder:                                     # bucket C -> safe drop
            page.remove_property(wd.PID_PUBLISHER, c)
            dropped.append(f"{vstr} (already on {holder})")
        elif len(editions) == 1:                       # bucket B -> review
            reasons.append(f"P123 = {vstr} on work, not on the single edition {editions[0].getID()} "
                           f"-- may be original publisher vs a reprint edition; confirm before moving")
        else:                                          # bucket D -> review
            reasons.append(f"P123 = {vstr} on work with {len(editions)} editions ({ed_ids}) "
                           f"-- ambiguous which edition; move manually")

    if dropped:
        action = f"- work P123 {', '.join(dropped)}"
        changed = page.apply()
        # If some values dropped and others need review, surface both.
        return changed, ("; ".join(reasons) or None), action
    if reasons:
        return False, "; ".join(reasons), None
    return False, None, None


def load_processed(include_review: bool = True) -> set:
    processed = set()
    paths = [DONE_FILE, FAILED_FILE] + ([REVIEW_FILE] if include_review else [])
    for path in paths:
        if path.exists():
            with open(path, encoding="utf-8") as f:
                processed |= {line.split("\t", 1)[0].strip() for line in f if line.strip()}
    return processed


def append_line(path: Path, line: str) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def daily_editgroup(tag: str) -> str:
    return hashlib.sha1(f"{tag}:{date.today().isoformat()}".encode()).hexdigest()[:12]


def load_qids_file(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        return [tok for line in f if (tok := line.split("\t", 1)[0].strip()).startswith("Q")]


def main() -> None:
    p = argparse.ArgumentParser(
        description="Drop edition-level publisher (P123) off public-domain work items.")
    p.add_argument("--save", action="store_true",
                   help="really edit Wikidata and record results (default: dry run)")
    p.add_argument("--limit", type=int, metavar="N", help="stop after N not-yet-done items")
    p.add_argument("--qid", action="append", default=[], metavar="QID",
                   help="process only this QID, even if already done (repeatable)")
    p.add_argument("--file", metavar="PATH", help="file of QIDs (first token per line)")
    p.add_argument("--recheck-review", action="store_true",
                   help="re-examine items previously sent to review")
    p.add_argument("--death-year", type=int, default=DEFAULT_DEATH_YEAR, metavar="Y",
                   help=f"author-death cutoff for 'public domain' (default {DEFAULT_DEATH_YEAR})")
    p.add_argument("--editgroup", metavar="ID", help="override the per-day batch id")
    args = p.parse_args()

    edit_group = args.editgroup or daily_editgroup("clean_pd_works")
    print(f"editgroup={edit_group} ({'SAVE' if args.save else 'dry run'})", flush=True)

    if args.qid:
        items, force = args.qid, True
    elif args.file:
        items, force = load_qids_file(args.file), True
    else:
        items = fetch_candidates(args.death_year)
        force = False
        print(f"{len(items)} PD work(s) with a publisher on the work "
              f"(author d.<= {args.death_year})", flush=True)
    done = load_processed(include_review=not args.recheck_review)

    report = None
    if not args.save:
        OUTPUT_DIR.mkdir(exist_ok=True)
        report = open(REPORT_FILE, "w", encoding="utf-8")
        report.write(f"# dry-run preview  editgroup={edit_group}  {len(items)} candidate(s)\n")

    processed = 0
    try:
        for qid in items:
            if args.limit is not None and processed >= args.limit:
                break
            if not force and qid in done:
                continue
            print(f"Processing {qid} ...", flush=True)
            processed += 1
            try:
                changed, review, action = process_item(qid, edit_group=edit_group, test=not args.save)
            except Exception as e:
                pywikibot.error(f"Error on {qid}: {e}")
                if args.save:
                    append_line(FAILED_FILE, f"{qid}\t{str(e)[:400]}")
                if report:
                    report.write(f"{qid}\tERROR\t{str(e)[:400]}\n")
                continue

            if action and review:
                disposition, detail = "EDIT+REVIEW", f"{action} || {review}"
            elif action:
                disposition, detail = "EDIT", action
            elif review:
                disposition, detail = "REVIEW", review
            else:
                disposition, detail = "SKIP", "no publisher on work (nothing to do)"
            print(f"  {disposition} {qid}: {detail}", flush=True)
            if report:
                report.write(f"{qid}\t{disposition}\t{detail}\n")
            if args.save:
                if action:
                    append_line(DONE_FILE, f"{qid}\t{'changed' if changed else 'no-change'}\t{action}")
                if review:
                    append_line(REVIEW_FILE, f"{qid}\t{review}")
    finally:
        if report:
            report.close()
    print(f"Done. Processed {processed} item(s).", flush=True)


if __name__ == "__main__":
    main()
