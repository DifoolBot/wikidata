#!/usr/bin/env python3
"""make_edition.py -- create ONE edition for an EXISTING work on Wikidata and link it
(work P747 -> new edition, edition P629 -> work). The sibling of make_book (which builds a
work + edition from scratch): use this to *break out* an edition from a MIX item (a work
carrying edition-only facts), or to add a further edition/translation to an existing work.

Paste/‑‑file the edition metadata (same labelled format as make_book / gen_book_txt), the
tool seeds title+language from the work, confirms every field, then:
  * creates the EDITION (P31 = version, edition or translation, P629 -> the work),
  * adds the work's P747 -> edition with summary qualifiers,
  * with --strip, removes from the WORK the edition-only properties whose value now lives
    on the new edition (the misplaced facts you just moved).

    python projects/isbn_cleanup/make_edition.py --work Q116285162 --file ed.txt          # dry
    python projects/isbn_cleanup/make_edition.py --work Q116285162 --file ed.txt --save
    python projects/isbn_cleanup/make_edition.py --work Q116285162 --file ed.txt --save --strip

Read model authority: notes/isbn_bot.md / notes/make_work_edition_howto.md (WORK/EDITION
split, edition-only properties). Dry run by default.
"""

import argparse
import io
import re
import sys

import pywikibot
from stdnum import isbn as stdnum_isbn

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
from shared_lib.book_paste import (
    COMMON_LANG,
    EDITION_TYPE,
    build_edition,
    build_p747_quals,
    confirm,
    confirm_facts,
    daily_editgroup,
    parse_metadata,
    preview,
    quals_str,
)
from shared_lib.wikidata_site import get_repo

repo = None  # the Wikidata site; built lazily in main() so importing this module is offline

# code for a language QID (invert COMMON_LANG, preferring the shortest / ISO 639-1 form)
_QID_TO_LANG: dict = {}
for _code, _qid in COMMON_LANG.items():
    if _qid not in _QID_TO_LANG or len(_code) < len(_QID_TO_LANG[_qid]):
        _QID_TO_LANG[_qid] = _code

# The strict edition-only properties this tool will offer to strip off the work -- only
# those build_edition can carry, so a stripped value is never lost (it moved to the edition).
STRIP_PIDS = [
    wd.PID_ISBN_13, wd.PID_ISBN_10, wd.PID_PUBLICATION_DATE, wd.PID_NUMBER_OF_PAGES,
    wd.PID_PLACE_OF_PUBLICATION, wd.PID_PUBLISHER, wd.PID_EDITION_NUMBER,
    wd.PID_OCLC_CONTROL_NUMBER, wd.PID_DOI, wd.PID_LCCN_BIBLIOGRAPHIC,
]


def _read_blob(path) -> str:
    if path:
        with open(path, encoding="utf-8") as f:
            return f.read()
    print("Paste the edition metadata, then a line containing just '.' :")
    lines = []
    for line in sys.stdin:
        if line.rstrip("\n") == ".":
            break
        lines.append(line)
    return "".join(lines)


def _norm(pid: str, value: str) -> str:
    """Normalise an identifier value so the work's copy and the edition's copy compare equal
    (ISBN hyphenation, OCLC punctuation, DOI case, LCCN spacing)."""
    if pid in (wd.PID_ISBN_13, wd.PID_ISBN_10):
        return stdnum_isbn.compact(value)
    if pid == wd.PID_OCLC_CONTROL_NUMBER:
        return re.sub(r"\D", "", value)
    if pid == wd.PID_DOI:
        return value.upper()
    if pid == wd.PID_LCCN_BIBLIOGRAPHIC:
        return re.sub(r"[\s-]", "", value)
    return value


def edition_values(facts: dict) -> dict:
    """{pid: {normalised value, ...}} the new edition will carry, for the strict edition-only
    properties -- what the work is allowed to shed once it's on the edition."""
    v: dict = {}

    def put(pid, items):
        s = {_norm(pid, str(x)) for x in items if x not in (None, "")}
        if s:
            v[pid] = s

    put(wd.PID_ISBN_13, facts["isbn13"])
    put(wd.PID_ISBN_10, facts["isbn10"])
    put(wd.PID_PUBLICATION_DATE, [facts["date"].year] if facts["date"] else [])
    put(wd.PID_NUMBER_OF_PAGES, [facts["pages"]] if facts["pages"] else [])
    put(wd.PID_PLACE_OF_PUBLICATION, [facts["place_qid"]] if facts["place_qid"] else [])
    put(wd.PID_PUBLISHER, facts["publisher_qids"])
    put(wd.PID_EDITION_NUMBER, [facts["edition_no"]] if facts["edition_no"] else [])
    put(wd.PID_OCLC_CONTROL_NUMBER, [facts["oclc"]] if facts.get("oclc") else [])
    put(wd.PID_DOI, [facts["doi"]] if facts["doi"] else [])
    put(wd.PID_LCCN_BIBLIOGRAPHIC, [facts["lccn"]] if facts["lccn"] else [])
    return v


def _claim_token(pid: str, claim) -> str:
    """A work claim's value as a comparable string, normalised like edition_values."""
    t = claim.getTarget()
    if isinstance(t, pywikibot.ItemPage):
        return t.id
    if isinstance(t, pywikibot.WbTime):
        return str(t.year)
    if isinstance(t, pywikibot.WbQuantity):
        return str(int(float(t.amount)))
    return _norm(pid, str(t))


def strippable(work_claims: dict, facts: dict) -> list:
    """Work claims whose (pid, value) now lives on the new edition -> safe to remove from the
    work. Value-matched, so a differing value (a genuinely different printing) is left alone."""
    ev = edition_values(facts)
    out = []
    for pid, wanted in ev.items():
        for claim in work_claims.get(pid, []):
            if claim.getSnakType() == "value" and _claim_token(pid, claim) in wanted:
                out.append((pid, _claim_token(pid, claim), claim))
    return out


def _seed_from_work(work_item) -> tuple:
    """(title, lang_code) seeded from the work's P1476 / P407, for confirm_facts."""
    claims = work_item.get().get("claims", {})
    title = ""
    for c in claims.get(wd.PID_TITLE, []):
        t = c.getTarget()
        title = getattr(t, "text", "") or (t if isinstance(t, str) else "")
        if title:
            break
    if not title:
        labs = work_item.labels
        title = labs.get("en") or labs.get("mul") or ""
    lang_code = ""
    for c in claims.get(wd.PID_LANGUAGE_OF_WORK_OR_NAME, []):
        tgt = c.getTarget()
        lang_code = _QID_TO_LANG.get(getattr(tgt, "id", None), "")
        if lang_code:
            break
    return title, lang_code, claims


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Create one edition for an existing work and link it (work P747).")
    ap.add_argument("--work", required=True, metavar="QID", help="the existing work item")
    ap.add_argument("--file", metavar="PATH", help="read the edition metadata from a file")
    ap.add_argument("--save", action="store_true", help="really create (default: dry run)")
    ap.add_argument("--strip", action="store_true",
                    help="also remove edition-only props from the work once moved")
    args = ap.parse_args()

    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    global repo
    repo = get_repo()                                          # builds the site (network)
    dry_run = not args.save
    eg = daily_editgroup("make_edition")
    work_qid = args.work

    work_item = pywikibot.ItemPage(repo, work_qid)
    seed_title, seed_lang, work_claims = _seed_from_work(work_item)
    wtypes = [c.getTarget().id for c in work_claims.get(wd.PID_INSTANCE_OF, [])
              if c.getTarget()]
    if wtypes and wd.PID_HAS_EDITION_OR_TRANSLATION not in work_claims and \
            all(t == EDITION_TYPE for t in wtypes):
        print(f"  ! warning: {work_qid} looks like an EDITION (P31={wtypes}); "
              "you want the WORK item.")
    print(f"work {work_qid}: title seed {seed_title!r}, language seed {seed_lang or '(none)'}")

    parsed = parse_metadata(_read_blob(args.file))
    detected = ", ".join(k for k in parsed if not k.startswith("_") and parsed[k]) or "nothing"
    print(f"parsed fields: {detected}")
    facts = confirm_facts(parsed, seed_title=seed_title, seed_lang=seed_lang)

    elabels, edesc, especs = build_edition(facts, f"(work {work_qid})")
    preview("EDITION", elabels, edesc, especs)
    quals = build_p747_quals(facts)
    print(f"\n    then: {work_qid} P747 -> (the new edition)  {{{quals_str(quals)}}}")
    if facts["pub_name"]:
        print(f"    note: publisher \"{facts['pub_name']}\" has no QID -> "
              "P123 = somevalue + object named as (P1932)")

    to_strip = strippable(work_claims, facts) if args.strip else []
    if args.strip:
        if to_strip:
            print(f"\n    strip from {work_qid} (value now on the edition):")
            for pid, tok, _c in to_strip:
                print(f"        - {pid} = {tok}")
        else:
            print(f"\n    strip: nothing on {work_qid} matches the edition's values.")

    if dry_run:
        print("\n[dry run] nothing written. Re-run with --save to create"
              + (" + strip." if args.strip else "."))
        return
    if not confirm("\nCREATE edition + link"
                   + (" + strip work?" if args.strip else "?"), True):
        print("aborted.")
        return

    especs = build_edition(facts, work_qid)[2]                 # real P629 target
    ed_qid = cwd.create_item(labels=elabels, descriptions=edesc, claim_specs=especs,
                             edit_group=eg, test=False,
                             summary=f"create edition of {work_qid}", site=repo)
    print(f"created edition {ed_qid}")

    work_page = cwd.WikiDataPage(item=work_item, test=False)
    work_page.edit_group = eg
    link = pywikibot.Claim(repo, wd.PID_HAS_EDITION_OR_TRANSLATION)
    link.setTarget(pywikibot.ItemPage(repo, ed_qid))
    for qp, qv, qk in quals:
        q = pywikibot.Claim(repo, qp, is_qualifier=True)
        q.setTarget(pywikibot.ItemPage(repo, qv) if qk == "item" else qv)
        link.qualifiers.setdefault(qp, []).append(q)
    work_page.add_claim(wd.PID_HAS_EDITION_OR_TRANSLATION, link)
    work_page.apply()
    print(f"linked {work_qid} P747 -> {ed_qid}")

    if to_strip:
        claims = [c for _pid, _tok, c in to_strip]
        work_item.removeClaims(
            claims, summary=f"move edition-only statements to new edition {ed_qid} "
            f"([[:toolforge:editgroups/b/CB/{eg}|details]])")
        print(f"stripped {len(claims)} edition-only statement(s) from {work_qid}")
    print(f"done ([[toolforge:editgroups/b/CB/{eg}|batch]])")


if __name__ == "__main__":
    main()
