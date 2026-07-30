"""Fix the deterministic classes of P212/P957 format violations.

The P212/P957 format-constraint violators fall into several buckets (see
categorize_violations in notes/isbn_bot.md). This bot handles the three that
can be corrected without human judgement -- each preserves the data by moving it
to the right place rather than deleting it:

  * PIPE   -- two ISBNs crammed into one value, "A|B" (e.g. a thesis's print and
              electronic ISBN). Split into two separate statements, each in
              canonical hyphenation. Only when BOTH halves are valid ISBNs.
  * ASIN   -- an Amazon ASIN (`B0..`, sometimes with a bogus 978- prefix) stored
              as an ISBN. Move to Amazon Standard Identification Number (P5749).
  * ISMN   -- a music number (979-0-...) stored as an ISBN. Move to ISMN (P1208).

Everything else (invalid check digit, EAN/transposed prefix, plain
mis-hyphenation, range drift) is left untouched -- mis-hyphenation is the
existing formatter's job (Maxlath/DeltaBot); the rest need review.

Discovery is live each run (fetch the regex, QLever !REGEX). Main statements
only. Dry-run by default; --save to edit (requires pywikibot auth).

    python projects/isbn_cleanup/fix_isbn_violations.py            # dry run
    python projects/isbn_cleanup/fix_isbn_violations.py --limit 5  # dry run, 5 items
    python projects/isbn_cleanup/fix_isbn_violations.py --qid Q123 # one item
    python projects/isbn_cleanup/fix_isbn_violations.py --save     # really edit
"""

import argparse
import random
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

import pywikibot
import requests
from stdnum import isbn as stdnum_isbn
from stdnum import ismn as stdnum_ismn

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd

API_URL = "https://www.wikidata.org/w/api.php"
QLEVER_URL = "https://qlever.dev/api/wikidata"
USER_AGENT = "DifoolBot/1.0 (https://www.wikidata.org/wiki/User:DifoolBot)"
QID_FORMAT_CONSTRAINT = "Q21502404"
PROPS = [wd.PID_ISBN_13, wd.PID_ISBN_10]  # P212, P957
DASHES = "‐‑‒–—―−⁃﹘﹣－"
STRIP = "‎‏‪‫‬­​﻿ "
# Amazon ASINs are B0 + 8 alphanumerics. The B0 prefix distinguishes them from
# ISBN-10s ending in the "X" check digit, which are also 10 chars with a letter.
ASIN_RE = re.compile(r"^B0[0-9A-Z]{8}$")

HERE = Path(__file__).parent
OUTPUT_DIR = HERE / "output"
DONE_FILE = OUTPUT_DIR / "fixviol_done.txt"
FAILED_FILE = OUTPUT_DIR / "fixviol_failed.txt"
# bookish items whose only "ISBN" was an ASIN -> now have no ISBN; a human should
# check the Amazon page (add the real ISBN, or model it as a Kindle edition).
NO_ISBN_FILE = OUTPUT_DIR / "asin_no_isbn_review.txt"

site = pywikibot.Site("wikidata", "wikidata")
repo = site.data_repository()


def clean(value: str) -> str:
    """Strip directional/format marks and combining chars; normalise digits+dashes."""
    value = "".join(c for c in value if c not in STRIP and unicodedata.category(c) != "Mn")
    out = []
    for c in value:
        if c.isdigit() and not c.isascii():
            out.append(str(unicodedata.digit(c)))
        elif c in DASHES:
            out.append("-")
        else:
            out.append(c)
    return "".join(out).strip()


def canonical_isbn(prop: str, token: str) -> str | None:
    """Canonical hyphenation of token in the form required by prop, or None."""
    try:
        if not stdnum_isbn.is_valid(token):
            return None
        if prop == wd.PID_ISBN_13:
            return stdnum_isbn.format(stdnum_isbn.to_isbn13(stdnum_isbn.compact(token)))
        return stdnum_isbn.format(stdnum_isbn.to_isbn10(stdnum_isbn.compact(token)))
    except Exception:
        return None


def canonical_ismn(value: str) -> str | None:
    """ISMN in the fixed 979-0-DDDD-DDDD-D grouping that P1208's strict format
    constraint requires (NOT stdnum's variable publisher grouping, which fails it)."""
    try:
        if not stdnum_ismn.is_valid(value):
            return None
        c = stdnum_ismn.compact(value)  # 13 digits, 9790...
        if len(c) != 13:
            return None
        return f"979-0-{c[4:8]}-{c[8:12]}-{c[12]}"
    except Exception:
        return None


def plan(prop: str, value: str):
    """Classify a violating value. Returns (kind, payload) or None if not one of
    the three deterministic classes:
      ('pipe', [canon, canon, ...])  ('asin', 'B0......')  ('ismn', '979-0-..')
    """
    v = clean(value)

    if "|" in v:
        halves = [h.strip() for h in v.split("|") if h.strip()]
        canon = [canonical_isbn(prop, h) for h in halves]
        if len(canon) >= 2 and all(canon):
            return "pipe", canon
        return None  # a half didn't validate -> leave for review

    # ISMN (979-0) shares the EAN-13 checksum with ISBN, so stdnum.isbn.is_valid
    # accepts it -- check ISMN *before* the ISBN-validity skip below.
    ismn_canon = canonical_ismn(v)
    if ismn_canon:
        return "ismn", ismn_canon

    # a plain valid ISBN here is just mis-hyphenated -> not our job
    if canonical_isbn(prop, v):
        return None

    bare = re.sub(r"[-\s]", "", v)
    if len(bare) == 13 and bare[:3] in ("978", "979"):
        bare = bare[3:]
    if ASIN_RE.match(bare) and re.search(r"[A-Z]", bare):
        return "asin", bare

    return None


def process_item(qid, fixes, edit_group, test) -> bool:
    item = pywikibot.ItemPage(repo, qid)
    page = cwd.WikiDataPage(item, test=test)
    page.edit_group = edit_group

    def existing(pid):
        return {
            c.getTarget()
            for c in page.claims.get(pid, [])
            if isinstance(c.getTarget(), str)
        }

    for prop, value, kind, payload in fixes:
        claim = next(
            (c for c in page.claims.get(prop, []) if c.getTarget() == value), None
        )
        if claim is None:
            continue  # value changed since discovery
        if kind == "pipe":
            targets = [(prop, canon) for canon in payload]
        elif kind == "asin":
            targets = [(wd.PID_AMAZON_STANDARD_IDENTIFICATION_NUMBER, payload)]
        else:  # ismn
            targets = [(wd.PID_ISMN, payload)]
        added = False
        for tpid, tval in targets:
            if tval in existing(tpid):
                print(f"  {tval} already on {tpid}; not duplicating", flush=True)
                continue
            print(f"  {value!r} -> {tpid} {tval}  (references kept)", flush=True)
            # copy the malformed claim (with its refs/qualifiers) to the new
            # property/value and delete the original -- framework, one edit.
            page.copy_claim(
                old_pid=prop, new_pid=tpid, new_qid=None, claim_snak=claim.snak,
                delete_old=True, callback=None, new_value=tval,
            )
            added = True
        if not added:
            # target(s) already present -> just drop the malformed original
            page.remove_property(prop, claim)

    # Did an ASIN move leave the item with no ISBN at all? (page.claims still holds
    # the ASIN's P212 claim here -- the copy_claim delete applies later -- so
    # subtract the moved ASIN values.)
    moved_asins = {val for _, val, kind, _ in fixes if kind == "asin"}
    remaining_isbn = {
        c.getTarget()
        for pid in (wd.PID_ISBN_13, wd.PID_ISBN_10)
        for c in page.claims.get(pid, [])
        if isinstance(c.getTarget(), str)
    } - moved_asins
    no_isbn = bool(moved_asins) and not remaining_isbn

    page.summary = "move misfiled ISBN value to the correct property"
    return page.apply(), no_isbn


def fetch_format_regex(pid: str) -> str:
    r = requests.get(API_URL, params={
        "action": "wbgetclaims", "entity": pid, "property": "P2302", "format": "json"},
        headers={"User-Agent": USER_AGENT}, timeout=60)
    r.raise_for_status()
    for c in r.json()["claims"].get("P2302", []):
        if c["mainsnak"].get("datavalue", {}).get("value", {}).get("id") == QID_FORMAT_CONSTRAINT:
            for q in c.get("qualifiers", {}).get("P1793", []):
                return q["datavalue"]["value"]
    raise RuntimeError(f"no format-constraint regex for {pid}")


def fetch_violators(pid: str, regex: str):
    esc = regex.replace("\\", "\\\\")
    query = (
        "PREFIX p: <http://www.wikidata.org/prop/>\n"
        "PREFIX ps: <http://www.wikidata.org/prop/statement/>\n"
        f"SELECT ?item ?v WHERE {{ ?item p:{pid} ?st . ?st ps:{pid} ?v .\n"
        f'  FILTER(!REGEX(?v, "^(?:{esc})$")) }}'
    )
    r = requests.post(QLEVER_URL, data={"query": query},
                      headers={"User-Agent": USER_AGENT, "Accept": "text/tab-separated-values"},
                      timeout=180)
    r.raise_for_status()
    for line in r.text.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 2:
            qid = parts[0].rsplit("/", 1)[-1].rstrip(">")
            if qid.startswith("Q"):
                yield qid, parts[1].strip('"')


def build_worklist():
    work = defaultdict(list)
    for pid in PROPS:
        regex = fetch_format_regex(pid)
        for qid, value in fetch_violators(pid, regex):
            p = plan(pid, value)
            if p:
                work[qid].append((pid, value, p[0], p[1]))
    return work


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
    parser = argparse.ArgumentParser(description="Move misfiled ISBN values (pipe/ASIN/ISMN) to the right property.")
    parser.add_argument("--save", action="store_true",
                        help="really edit Wikidata and record results (default: dry run)")
    parser.add_argument("--limit", type=int, metavar="N", help="stop after N not-yet-done items")
    parser.add_argument("--qid", action="append", default=[], metavar="QID",
                        help="process only this QID, even if already processed (repeatable)")
    args = parser.parse_args()

    edit_group = f"{random.randrange(0, 2**48):x}"
    print(f"editgroup={edit_group} ({'SAVE' if args.save else 'dry run'})", flush=True)

    work = build_worklist()
    from collections import Counter
    kinds = Counter(k for fixes in work.values() for _, _, k, _ in fixes)
    print(f"{sum(len(v) for v in work.values())} fix(es) on {len(work)} item(s): {dict(kinds)}", flush=True)

    force = bool(args.qid)
    qids = args.qid if args.qid else list(work.keys())
    done = load_processed()
    processed = 0
    for qid in qids:
        if args.limit is not None and processed >= args.limit:
            break
        if not force and qid in done:
            continue
        if qid not in work:
            continue
        print(f"Processing {qid} ...", flush=True)
        processed += 1
        try:
            changed, no_isbn = process_item(qid, work[qid], edit_group=edit_group, test=not args.save)
        except Exception as e:
            pywikibot.error(f"Error on {qid}: {e}")
            if args.save:
                append_line(FAILED_FILE, f"{qid}\t{str(e)[:400]}")
            continue
        if no_isbn:
            print(f"  FLAG {qid}: no ISBN after ASIN move -- check Amazon "
                  f"(add real ISBN, or model as Kindle edition: P437=Amazon Kindle)", flush=True)
        if args.save:
            append_line(DONE_FILE, f"{qid}\t{'changed' if changed else 'no-change'}")
            if no_isbn:
                append_line(NO_ISBN_FILE, qid)
    print(f"Done: {processed} item(s) processed.", flush=True)


if __name__ == "__main__":
    main()
