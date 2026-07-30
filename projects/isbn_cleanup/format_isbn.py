"""Fix wrongly-hyphenated ISBN-13 (P212) / ISBN-10 (P957) main statements.

Wikidata's P212/P957 format constraint rejects wrong or missing hyphens. This
bot reformats such values to the canonical hyphenation from `python-stdnum`,
but only when it is *safe*:

  * the stored value FAILS the live format-constraint regex, AND
  * stdnum's canonical form PASSES it, AND
  * the number is a valid ISBN (check digit included).

That guard is essential. Most values stdnum would "reformat" already satisfy the
constraint (Wikidata accepts that hyphenation) or fall in a range where stdnum's
data lags Wikidata's regex -- reformatting those is churn or drift. Requiring
stored-fails-and-canonical-passes leaves only genuine violations (in practice a
small set, dominated by 979-8 codes the existing hyphenation bot doesn't cover).

Invalid ISBNs (bad check digit) are never touched -- silently re-hyphenating a
wrong number hides a data error; they are logged for review instead.

Discovery is live each run: it fetches the current P212/P957 regex and asks
QLever for values that fail it, so new violations are picked up automatically.
Only MAIN statements are handled; P212/P957 also occur as qualifiers/references
(far rarer) -- a possible follow-up.

Dry-run by default. Pass --save to actually edit (requires pywikibot auth).

    python projects/isbn_cleanup/format_isbn.py             # dry run, whole worklist
    python projects/isbn_cleanup/format_isbn.py --limit 5   # dry run, 5 items
    python projects/isbn_cleanup/format_isbn.py --qid Q123  # one item, even if done
    python projects/isbn_cleanup/format_isbn.py --save      # really edit
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

API_URL = "https://www.wikidata.org/w/api.php"
QLEVER_URL = "https://qlever.dev/api/wikidata"
USER_AGENT = "DifoolBot/1.0 (https://www.wikidata.org/wiki/User:DifoolBot)"
QID_FORMAT_CONSTRAINT = "Q21502404"

PROPS = [wd.PID_ISBN_13, wd.PID_ISBN_10]  # P212, P957
DASHES = "‐‑‒–—―−⁃﹘﹣－"

HERE = Path(__file__).parent
OUTPUT_DIR = HERE / "output"
DONE_FILE = OUTPUT_DIR / "format_done.txt"
FAILED_FILE = OUTPUT_DIR / "format_failed.txt"
REVIEW_FILE = OUTPUT_DIR / "format_review.txt"

site = pywikibot.Site("wikidata", "wikidata")
repo = site.data_repository()


def normalize_dashes(value: str) -> str:
    return "".join("-" if ch in DASHES else ch for ch in value)


def fetch_format_regex(pid: str) -> str:
    """Return the live format-constraint (P1793) regex for a property."""
    r = requests.get(API_URL, params={
        "action": "wbgetclaims", "entity": pid, "property": "P2302",
        "format": "json"}, headers={"User-Agent": USER_AGENT}, timeout=60)
    r.raise_for_status()
    for c in r.json()["claims"].get("P2302", []):
        snak = c["mainsnak"].get("datavalue", {}).get("value", {})
        if snak.get("id") == QID_FORMAT_CONSTRAINT:
            for q in c.get("qualifiers", {}).get("P1793", []):
                return q["datavalue"]["value"]
    raise RuntimeError(f"no format-constraint regex found for {pid}")


def fetch_violating_values(pid: str, regex: str) -> list[tuple[str, str]]:
    """QLever: main-statement values of pid that FAIL the format regex."""
    esc = regex.replace("\\", "\\\\")
    query = (
        "PREFIX p: <http://www.wikidata.org/prop/>\n"
        "PREFIX ps: <http://www.wikidata.org/prop/statement/>\n"
        "SELECT ?item ?v WHERE {\n"
        f"  ?item p:{pid} ?st . ?st ps:{pid} ?v .\n"
        f'  FILTER(!REGEX(?v, "^(?:{esc})$"))\n'
        "}"
    )
    r = requests.post(QLEVER_URL, data={"query": query},
                      headers={"User-Agent": USER_AGENT,
                               "Accept": "text/tab-separated-values"}, timeout=180)
    r.raise_for_status()
    out = []
    for line in r.text.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        qid = parts[0].rsplit("/", 1)[-1].rstrip(">")
        value = parts[1].strip('"')
        if qid.startswith("Q"):
            out.append((qid, value))
    return out


def build_worklist() -> tuple[dict, list]:
    """Return ({qid: [(pid, current, canonical)]}, review_lines)."""
    work = defaultdict(list)
    review = []
    for pid in PROPS:
        regex = fetch_format_regex(pid)
        pat = re.compile("^(?:" + regex + ")$")
        candidates = fetch_violating_values(pid, regex)
        print(f"{pid}: {len(candidates)} value(s) fail the format constraint", flush=True)
        for qid, value in candidates:
            vn = normalize_dashes(value)
            try:
                valid = stdnum_isbn.is_valid(vn)
            except Exception:
                valid = False
            if not valid:
                review.append(f"{qid}\t{pid}\t{value}\tinvalid ISBN (bad check digit / not an ISBN)")
                continue
            canon = stdnum_isbn.format(vn)
            if pat.match(value):
                continue  # already fine (shouldn't reach here)
            if not pat.match(canon):
                review.append(f"{qid}\t{pid}\t{value}\tcanonical {canon} also fails constraint (range drift)")
                continue
            work[qid].append((pid, value, canon))
    return work, review


def process_item(qid: str, fixes: list, edit_group: str, test: bool) -> bool:
    item = pywikibot.ItemPage(repo, qid)
    page = cwd.WikiDataPage(item, test=test)
    page.edit_group = edit_group
    for pid, current, canon in fixes:
        for claim in page.claims.get(pid, []):
            if claim.getTarget() == current:
                # Don't reformat a deprecated value: it's kept deliberately wrong
                # (e.g. a Kindle edition carrying the paperback's ISBN, deprecated
                # because it belongs to the sibling edition) -- re-hyphenating it is
                # a pointless edit on a value that shouldn't be presented as canonical.
                if claim.rank == "deprecated":
                    print(f"  {pid}: {current!r} skipped (deprecated rank)", flush=True)
                    break
                print(f"  {pid}: {current!r} -> {canon!r}", flush=True)
                page.change_claim(pid, claim, canon)
                break
    page.summary = "format ISBN"
    return page.apply()


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


def daily_editgroup(tag: str) -> str:
    """Stable per-day editgroups batch id (tag+date), so repeated runs in a day group
    into one reviewable/undoable batch instead of a new random id per run."""
    return hashlib.sha1(f"{tag}:{date.today().isoformat()}".encode()).hexdigest()[:12]


def main() -> None:
    parser = argparse.ArgumentParser(description="Fix wrongly-hyphenated ISBN (P212/P957) statements.")
    parser.add_argument("--save", action="store_true",
                        help="really edit Wikidata and record results (default: dry run)")
    parser.add_argument("--limit", type=int, metavar="N",
                        help="stop after processing N not-yet-done items")
    parser.add_argument("--qid", action="append", default=[], metavar="QID",
                        help="process only this QID, even if already processed (repeatable)")
    parser.add_argument("--editgroup", metavar="ID",
                        help="override the batch id (default: a stable per-day id)")
    args = parser.parse_args()

    edit_group = args.editgroup or daily_editgroup("format_isbn")
    kind = "override" if args.editgroup else "daily; groups today's runs"
    print(f"editgroup={edit_group} ({kind}) ({'SAVE' if args.save else 'dry run'})", flush=True)

    work, review = build_worklist()
    print(f"{sum(len(v) for v in work.values())} fix(es) on {len(work)} item(s); "
          f"{len(review)} logged for review", flush=True)

    force = bool(args.qid)
    qids = args.qid if args.qid else list(work.keys())
    done = load_processed()
    processed = 0
    for qid in qids:
        if args.limit is not None and processed >= args.limit:
            break
        if not force and qid in done:
            continue
        fixes = work.get(qid, [])
        if not fixes:
            continue
        print(f"Processing {qid} ...", flush=True)
        processed += 1
        try:
            changed = process_item(qid, fixes, edit_group=edit_group, test=not args.save)
        except Exception as e:
            pywikibot.error(f"Error on {qid}: {e}")
            if args.save:
                append_line(FAILED_FILE, f"{qid}\t{str(e)[:400]}")
            continue
        if args.save:
            append_line(DONE_FILE, f"{qid}\t{'changed' if changed else 'no-change'}")
    if args.save:
        for line in review:
            append_line(REVIEW_FILE, line)
    print(f"Done: {processed} item(s) processed.", flush=True)


if __name__ == "__main__":
    main()
