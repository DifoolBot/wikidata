#!/usr/bin/env python3
"""make_book.py -- create a written work (+ one edition) on Wikidata from pasted
Google Books or publisher metadata.

Paste the metadata (via --file or interactively), the tool parses it, you confirm
each field, and it creates two linked items:
  * a WORK    -- P31 = written work (Q47461344): title/subtitle/language/authors/subjects
  * an EDITION -- P31 = version, edition or translation (Q3331189): P629 -> work, plus
    publisher/place/date/ISBN/pages/DOI/edition-no/editors/format
then links the work to the edition (P747, with summary qualifiers).

The paste -> confirm -> build core lives in shared_lib.book_paste (shared with the
floruit_books migrator); this file is the create-from-scratch CLI over it.

Read model authority: notes/isbn_bot.md "Canonical book data model" (WORK/EDITION
split, edition-only properties). All edits go through shared_lib.change_wikidata
(User-Agent/maxlag/throttle), dry-run by default in one daily editgroups batch.

Usage (repo root, PYTHONPATH=projects;projects/shared_lib via .env):
    python projects/isbn_cleanup/make_book.py --file book.txt        # dry run
    python projects/isbn_cleanup/make_book.py --file book.txt --save  # really create
    python projects/isbn_cleanup/make_book.py                         # paste, end with "."
"""

import argparse
import io
import sys

import pywikibot

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
from shared_lib.book_paste import (
    build_edition,
    build_p747_quals,
    build_work,
    confirm,
    confirm_facts,
    daily_editgroup,
    parse_metadata,
    preview,
    quals_str,
)
from shared_lib.wikidata_site import get_repo

repo = get_repo()  # builds the Wikidata site (as every isbn_cleanup entry point does)


def _read_blob(path) -> str:
    if path:
        with open(path, encoding="utf-8") as f:
            return f.read()
    print("Paste the book metadata, then a line containing just '.' :")
    lines = []
    for line in sys.stdin:
        if line.rstrip("\n") == ".":
            break
        lines.append(line)
    return "".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Create a written work + one edition on Wikidata from pasted metadata.")
    ap.add_argument("--save", action="store_true", help="really create (default: dry run)")
    ap.add_argument("--file", metavar="PATH", help="read the pasted metadata from a file")
    args = ap.parse_args()

    # Book titles/authors are international; Windows consoles default to cp1252 and would
    # raise UnicodeEncodeError at print time. Force UTF-8 out.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    dry_run = not args.save
    eg = daily_editgroup("make_book")

    parsed = parse_metadata(_read_blob(args.file))
    detected = ", ".join(k for k in parsed if not k.startswith("_") and parsed[k]) or "nothing"
    print(f"\nparsed fields: {detected}")
    facts = confirm_facts(parsed)

    wlabels, wdesc, wspecs = build_work(facts)
    preview("WORK", wlabels, wdesc, wspecs)
    elabels, edesc, especs = build_edition(facts, "(the new work)")
    preview("EDITION", elabels, edesc, especs)
    quals = build_p747_quals(facts)
    print(f"\n    then: work P747 -> edition  {{{quals_str(quals)}}}")
    if facts["pub_name"]:
        print(f"    note: publisher \"{facts['pub_name']}\" has no QID -> "
              "P123 = somevalue + object named as (P1932)")

    if dry_run:
        print("\n[dry run] nothing written. Re-run with --save to create.")
        return
    if not confirm("\nCREATE work + edition + link?", True):
        print("aborted.")
        return

    work_qid = cwd.create_item(labels=wlabels, descriptions=wdesc, claim_specs=wspecs,
                               edit_group=eg, test=False, summary="create written work",
                               site=repo)
    print(f"created work {work_qid}")
    especs = build_edition(facts, work_qid)[2]             # real P629 target now
    ed_qid = cwd.create_item(labels=elabels, descriptions=edesc, claim_specs=especs,
                             edit_group=eg, test=False,
                             summary=f"create edition of {work_qid}", site=repo)
    print(f"created edition {ed_qid}")

    work_page = cwd.WikiDataPage(item=pywikibot.ItemPage(repo, work_qid), test=False)
    work_page.edit_group = eg
    link = pywikibot.Claim(repo, wd.PID_HAS_EDITION_OR_TRANSLATION)
    link.setTarget(pywikibot.ItemPage(repo, ed_qid))
    for qp, qv, qk in quals:
        q = pywikibot.Claim(repo, qp, is_qualifier=True)
        q.setTarget(pywikibot.ItemPage(repo, qv) if qk == "item" else qv)
        link.qualifiers.setdefault(qp, []).append(q)
    work_page.add_claim(wd.PID_HAS_EDITION_OR_TRANSLATION, link)
    work_page.apply()
    print(f"linked {work_qid} P747 -> {ed_qid}  ([[toolforge:editgroups/b/CB/{eg}|batch]])")


if __name__ == "__main__":
    main()
