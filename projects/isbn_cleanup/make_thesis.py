#!/usr/bin/env python3
"""make_thesis.py -- create a THESIS item on Wikidata from a labelled text file (the
book.txt-style workflow, but for a thesis instead of a book).

A thesis is a SINGLE item -- P31 = doctoral thesis (Q187685) -- not a WORK + EDITION.
Empirically (110k+ doctoral-thesis items sampled) the person is linked only from the
thesis via P50 (author), which shows on the person's page as a backlink ("author of ...");
no statement is added to the person, so this tool never edits the person item.

    python projects/isbn_cleanup/make_thesis.py --file thesis.txt        # dry run
    python projects/isbn_cleanup/make_thesis.py --file thesis.txt --save  # really create

thesis.txt fields (labelled, one per line; blank lines and '#' comments ignored):
    Title:        thesis title in its own language     -> P1476  (+ label)
    Subtitle:     optional                             -> P1680
    Author:       Name [Qxxxx]                         -> P50 (or P2093 name string, no QID)
    Language:     ISO code (fr, en, de, ...)           -> P407
    Published:    YYYY / YYYY-MM / YYYY-MM-DD          -> P577
    Institution:  Qxxxx  (organisme de soutenance)     -> P4101 thesis submitted to
    Subjects:     Qxxxx; Qxxxx                         -> P921 (';'/','-separated QIDs)
    SUDOC:        the SUDOC bibliographic record id    -> P1025
    National thesis number: theses.fr id (optional)    -> P5005
    URL:          only if the full text is freely readable -> P953
    Pages:        optional (leave off for a leaf count) -> P1104
    Type:         P31 QID (default Q187685 doctoral thesis)

Read model authority: empirical check on Wikidata + notes/isbn_bot.md. Dry run by default;
edits go through shared_lib.change_wikidata in one daily editgroups batch.
"""

import argparse
import io
import re
import sys

import pywikibot
import requests

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
from shared_lib.book_paste import (
    COMMON_LANG,
    LANG_MONO,
    _extract_inline_qid,
    _extract_qids,
    _is_qid,
    _loose_date_iso,
    _parse_date,
    _split_names,
    confirm,
    daily_editgroup,
    parse_metadata,
    preview,
)
from shared_lib.wikidata_site import get_repo

repo = get_repo()


def _existing_theses(parsed: dict) -> dict:
    """Best-effort dedup: {qid: which-id-matched} for items already carrying this thesis's
    SUDOC (P1025) / national thesis number (P5005) / DOI (P356), via CirrusSearch
    haswbstatement (reliable, no SPARQL). Empty on any lookup failure -> never blocks blindly."""
    ua = {"User-Agent": "DifoolBot/1.0 (https://www.wikidata.org/wiki/User:DifoolBot)"}
    checks = [("P1025", (parsed.get("sudoc") or [""])[0].strip()),
              ("P5005", (parsed.get("thesis_no_fr") or [""])[0].strip()),
              ("P356", (parsed.get("doi") or [""])[0].strip().upper())]
    found = {}
    for pid, val in checks:
        if not val:
            continue
        try:
            r = requests.get("https://www.wikidata.org/w/api.php",
                             params={"action": "query", "list": "search",
                                     "srsearch": f"haswbstatement:{pid}={val}",
                                     "srlimit": 5, "format": "json"}, headers=ua, timeout=30)
            for h in r.json().get("query", {}).get("search", []):
                found.setdefault(h["title"], f"{pid}={val}")
        except Exception as exc:
            print(f"  (dedup check for {pid} skipped: {exc})")
    return found


def _read_blob(path) -> str:
    if path:
        with open(path, encoding="utf-8") as f:
            return f.read()
    print("Paste the thesis metadata, then a line containing just '.' :")
    lines = []
    for line in sys.stdin:
        if line.rstrip("\n") == ".":
            break
        lines.append(line)
    return "".join(lines)


def _people(vals) -> list:
    """[(qid_or_None, name_or_None)] from a labelled contributor value, taking inline QIDs
    ('Name [Qxxxx]' / bare 'Qxxxx') -- no interactive prompt (the file is authoritative)."""
    out = []
    for v in _split_names(vals):
        name, qid = _extract_inline_qid(v)
        out.append((qid if _is_qid(qid) else None, name or None))
    return out


def build_thesis(parsed: dict) -> tuple:
    """(labels, descriptions, claim_specs) for the thesis item."""
    lang_raw = (parsed.get("language") or [""])[0].strip()
    lang_qid = lang_raw if _is_qid(lang_raw) else COMMON_LANG.get(lang_raw.lower())
    lc = "" if _is_qid(lang_raw) else lang_raw.lower()
    lc = LANG_MONO.get(lc, lc)
    if lang_raw and not lang_qid:
        print(f"    (unknown language '{lang_raw}'; leaving P407 off)")

    title = (parsed.get("title") or [""])[0].strip()
    subtitle = (parsed.get("subtitle") or [""])[0].strip()
    if ":" in title and not subtitle:                      # split a colon title/subtitle
        title, subtitle = (x.strip() for x in title.split(":", 1))
    if not title:
        sys.exit("no Title: line found")

    authors = _people(parsed.get("authors"))

    inst_raw = (parsed.get("institution") or [""])[0].strip()
    inst_name, inst_qid = _extract_inline_qid(inst_raw)
    inst_qid = inst_qid if _is_qid(inst_qid) else (inst_raw if _is_qid(inst_raw) else None)
    if inst_raw and not inst_qid:
        print(f"    (institution '{inst_raw}' is not a QID; leaving P4101 off)")

    date_raw = (parsed.get("date") or [""])[0]
    pub_date = _parse_date(_loose_date_iso(date_raw)) if date_raw else None

    subject_qids = _extract_qids("; ".join(parsed.get("subjects", [])), r";")[0]
    sudoc = (parsed.get("sudoc") or [""])[0].strip()
    thesis_no = (parsed.get("thesis_no_fr") or [""])[0].strip()
    url = (parsed.get("full_url") or [""])[0].strip()
    doi = (parsed.get("doi") or [""])[0].strip()
    advisors = _people(parsed.get("advisor"))              # -> P184 on the author (below)
    pages_raw = (parsed.get("pages") or [""])[0]
    pages = int(re.search(r"\d+", pages_raw).group(0)) if re.search(r"\d+", pages_raw) else None
    type_raw = (parsed.get("type") or [""])[0].strip()
    type_qid = type_raw if _is_qid(type_raw) else wd.QID_DOCTORAL_THESIS

    specs = [
        (wd.PID_INSTANCE_OF, type_qid, "item"),
        (wd.PID_TITLE, (title, lc or "mul"), "monolingual"),
    ]
    if subtitle:
        specs.append((wd.PID_SUBTITLE, (subtitle, lc or "mul"), "monolingual"))
    for qid, name in authors:                              # P50 item, else P2093 name string
        specs.append((wd.PID_AUTHOR, qid, "item") if qid
                     else (wd.PID_AUTHOR_NAME_STRING, name, "string"))
    if lang_qid:
        specs.append((wd.PID_LANGUAGE_OF_WORK_OR_NAME, lang_qid, "item"))
    if pub_date:
        specs.append((wd.PID_PUBLICATION_DATE, pub_date, "time"))
    if inst_qid:
        specs.append((wd.PID_THESIS_SUBMITTED_TO, inst_qid, "item"))
    for sq in subject_qids:
        specs.append((wd.PID_MAIN_SUBJECT, sq, "item"))
    if sudoc:
        specs.append((wd.PID_SUDOC_EDITIONS, sudoc, "string"))
    if thesis_no:
        specs.append((wd.PID_NATIONAL_THESIS_NUMBER_FRANCE, thesis_no, "string"))
    if doi:
        specs.append((wd.PID_DOI, doi.upper(), "string"))  # P356 stores DOIs upper-case
    if url:
        specs.append((wd.PID_FULL_WORK_AVAILABLE_AT_URL, url, "string"))
    if pages:
        specs.append((wd.PID_NUMBER_OF_PAGES,
                      pywikibot.WbQuantity(amount=pages, site=repo), "quantity"))

    labels = {"mul": title}
    if lc:
        labels[lc] = title
    year = pub_date.year if pub_date else None
    who = ", ".join(n for _, n in authors if n)
    en = f"{year} doctoral thesis" if year else "doctoral thesis"
    if who:
        en += f" by {who}"
    author_qids = [qid for qid, _ in authors if qid]        # for the reciprocal P1026 link
    advisor_qids = [qid for qid, _ in advisors if qid]      # -> P184 doctoral advisor on author
    return labels, {"en": en}, specs, author_qids, type_qid, advisor_qids


def _item_has_value(item, pid: str, target_qid: str) -> bool:
    """True if ``item`` already has a statement pid -> target_qid (avoids duplicates)."""
    item.get()
    for c in item.claims.get(pid, []):
        t = c.getTarget()
        if isinstance(t, pywikibot.ItemPage) and t.id == target_qid:
            return True
    return False


def _add_academic_thesis(author_qid: str, thesis_qid: str, type_qid: str, eg: str) -> None:
    """On the author item, add P1026 (academic thesis) -> the new thesis, qualified with
    P3831 (object has role) = the thesis type (doctoral thesis by default) -- the statement
    that makes the thesis visible on the author's page (the dominant convention; the P50 on
    the thesis is only a backlink)."""
    item = pywikibot.ItemPage(repo, author_qid)
    if _item_has_value(item, wd.PID_ACADEMIC_THESIS, thesis_qid):
        print(f"  author {author_qid} already has P1026 -> {thesis_qid}; skipping")
        return
    page = cwd.WikiDataPage(item=item, test=False)
    page.edit_group = eg
    claim = pywikibot.Claim(repo, wd.PID_ACADEMIC_THESIS)
    claim.setTarget(pywikibot.ItemPage(repo, thesis_qid))
    role = pywikibot.Claim(repo, wd.PID_OBJECT_HAS_ROLE, is_qualifier=True)
    role.setTarget(pywikibot.ItemPage(repo, type_qid))
    claim.qualifiers.setdefault(wd.PID_OBJECT_HAS_ROLE, []).append(role)
    page.add_claim(wd.PID_ACADEMIC_THESIS, claim)
    page.apply()
    print(f"  linked author {author_qid} P1026 -> {thesis_qid}")


def _add_doctoral_advisor(author_qid: str, advisor_qid: str, eg: str) -> None:
    """On the author (the doctoral candidate), add P184 (doctoral advisor) -> the advisor."""
    item = pywikibot.ItemPage(repo, author_qid)
    if _item_has_value(item, wd.PID_DOCTORAL_ADVISOR, advisor_qid):
        print(f"  author {author_qid} already has P184 -> {advisor_qid}; skipping")
        return
    page = cwd.WikiDataPage(item=item, test=False)
    page.edit_group = eg
    claim = pywikibot.Claim(repo, wd.PID_DOCTORAL_ADVISOR)
    claim.setTarget(pywikibot.ItemPage(repo, advisor_qid))
    page.add_claim(wd.PID_DOCTORAL_ADVISOR, claim)
    page.apply()
    print(f"  added author {author_qid} P184 (doctoral advisor) -> {advisor_qid}")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Create a thesis item on Wikidata from a labelled text file.")
    ap.add_argument("--save", action="store_true", help="really create (default: dry run)")
    ap.add_argument("--file", metavar="PATH", help="read the thesis metadata from a file")
    ap.add_argument("--force", action="store_true",
                    help="create even if a thesis with the same SUDOC/NNT/DOI already exists")
    args = ap.parse_args()

    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    dry_run = not args.save
    eg = daily_editgroup("make_thesis")

    parsed = parse_metadata(_read_blob(args.file))
    detected = ", ".join(k for k in parsed if not k.startswith("_") and parsed[k]) or "nothing"
    print(f"\nparsed fields: {detected}")

    labels, desc, specs, author_qids, type_qid, advisor_qids = build_thesis(parsed)
    preview("THESIS", labels, desc, specs)

    dup = _existing_theses(parsed)
    if dup:
        print("\n  !! POSSIBLE DUPLICATE -- an item already carries this thesis's id(s):")
        for q, why in dup.items():
            print(f"       https://www.wikidata.org/wiki/{q}  ({why})")
        print("     The P1026/P184 reciprocals may already be set too. Use --force to create anyway.")
    if author_qids:
        print(f"\n    then, on each author {author_qids}: "
              f"P1026 (academic thesis) -> (the new thesis)  {{P3831 = {type_qid}}}")
        if advisor_qids:
            print(f"    and on each author: P184 (doctoral advisor) -> {advisor_qids}")
    else:
        print("\n    (no author has a QID -> no reciprocal P1026/P184 added; only the P50 backlink)")

    if dry_run:
        print("\n[dry run] nothing written. Re-run with --save to create"
              + (" (--force needed: duplicate)." if dup else "."))
        return
    if dup and not args.force:
        print("\nrefusing to create: a thesis with this id already exists (see above). "
              "Re-run with --force if you really want a new item.")
        return
    if not confirm("\nCREATE this thesis item + reciprocal P1026/P184 on the author(s)?", True):
        print("aborted.")
        return
    qid = cwd.create_item(labels=labels, descriptions=desc, claim_specs=specs,
                          edit_group=eg, test=False, summary="create thesis", site=repo)
    print(f"created thesis {qid}")
    for aq in author_qids:                                  # reciprocal: author P1026 -> thesis
        _add_academic_thesis(aq, qid, type_qid, eg)
        for adv in advisor_qids:                            # + doctoral advisor on the author
            _add_doctoral_advisor(aq, adv, eg)
    print(f"done ([[toolforge:editgroups/b/CB/{eg}|batch]])")


if __name__ == "__main__":
    main()
