#!/usr/bin/env python3
"""migrate_floruit_book.py -- turn the "inline book" floruit shape into a real
book item referenced with P248 (stated in).

The old shape (mostly DifoolBot's own house style) is a person's floruit (P1317)
statement carrying qualifiers title (P1476) + subject has role (P2868), sourced by
a *database* reference that points at the book by a bibliographic identifier -- DNB
edition ID (P1292), SUDOC editions (P1025), Google Books (P675), Open Library (P648)
or OCLC (P243). This tool, per candidate:

  * creates a WORK    -- P31 = written work (Q47461344): title / language / the person
    in their authorship role (P50 author, P98 editor);
  * creates an EDITION -- P31 = version, edition or translation (Q3331189): P629 -> work,
    title / language, illustrator (P110) if that was the role, and the moved-off
    bibliographic identifier(s);
  * rewrites the floruit reference: stated in (P248) -> the new edition (dropping the
    old "stated in <database>" + the id snak), keeping retrieved (P813) and any
    reference URL (P854);
  * drops the now-redundant title qualifier (P1476), keeps subject has role (P2868).

Publication date / publisher / pages are NOT guessed -- you copy those from the
catalogue (archive.org, DNB edition page, ...) by hand afterwards.

Scope: only references that carry one of the five *bibliographic edition* identifiers
above. LC-authority (P244, which is the person's own record), film-database and
URL-only sources are left untouched. Candidates are pulled live from QLever.

Read model authority: notes/isbn_bot.md "Canonical book data model" (WORK/EDITION
split, edition-only properties). All edits go through shared_lib.change_wikidata
(User-Agent / maxlag / throttle), dry-run by default, in one daily editgroups batch.

Usage (repo root, PYTHONPATH=projects;projects/shared_lib via .env):
    python projects/floruit_books/migrate_floruit_book.py                 # dry run, all candidates
    python projects/floruit_books/migrate_floruit_book.py --limit 5       # dry run, first 5
    python projects/floruit_books/migrate_floruit_book.py --qid Q132997957 # dry run, one person
    python projects/floruit_books/migrate_floruit_book.py --save          # really create + edit
"""

import argparse
import hashlib
import io
import json
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

import pywikibot

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
from shared_lib.wikidata_site import ensure_login, get_repo

# get_repo() is called lazily (inside the functions that edit), so merely importing
# this module does no network I/O -- offline unit tests can import it freely.

QID_WRITTEN_WORK = "Q47461344"   # WORK P31 (authored book)
EDITION_TYPE = "Q3331189"        # EDITION P31 (version, edition or translation)

QLEVER = "https://qlever.dev/api/wikidata"
# Identify the client by the bot's user page, never a personal e-mail.
USER_AGENT = "DifoolBot/1.0 (https://www.wikidata.org/wiki/User:DifoolBot)"

# subject-has-role QID -> (authorship property, which item it belongs on). Roles not
# listed (composer/photographer/cartoonist/...) are out of scope: those sources are
# often music or film items, not books -- they go to the review file untouched.
ROLE_TO_PROP: Dict[str, Tuple[str, str]] = {
    "Q482980": (wd.PID_AUTHOR, "work"),        # author      -> P50 (work)
    "Q36180": (wd.PID_AUTHOR, "work"),         # writer      -> P50 (work)
    "Q1607826": (wd.PID_EDITOR, "work"),       # editor      -> P98 (work)
    "Q644687": (wd.PID_ILLUSTRATOR, "edition"),  # illustrator -> P110 (edition)
}
ROLE_DESC = {
    "Q482980": "book by", "Q36180": "book by",
    "Q1607826": "book edited by", "Q644687": "book illustrated by",
}

# The five bibliographic-edition identifiers we migrate, in the order the candidate
# query UNIONs them. Each maps its result column to the property it lives under.
BOOK_ID_COLS: List[Tuple[str, str]] = [
    ("dnb", wd.PID_DNB_EDITION_ID),
    ("sudoc", wd.PID_SUDOC_EDITIONS),
    ("gbooks", wd.PID_GOOGLE_BOOKS_ID),
    ("openlib", wd.PID_OPEN_LIBRARY_ID),
    ("oclc", wd.PID_OCLC_CONTROL_NUMBER),
]
BOOK_ID_PROPS = {pid for _, pid in BOOK_ID_COLS}

# Language code (from the title's lang tag) -> language-of-work (P407) item. Anything
# not here just leaves P407 off (you can add it by hand).
LANG_QID = {
    "en": "Q1860", "de": "Q188", "fr": "Q150", "nl": "Q7411", "es": "Q1321",
    "it": "Q652", "pt": "Q5146", "ru": "Q7737", "la": "Q397", "grc": "Q35497",
    "da": "Q9035", "sv": "Q9027", "no": "Q9043", "nb": "Q25167", "nn": "Q25164",
    "fi": "Q1412", "pl": "Q809", "cs": "Q9056", "az": "Q9292", "ko": "Q9176",
    "ja": "Q5287", "zh": "Q7850", "uk": "Q8798", "tr": "Q256",
}

PREFIXES = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX ps: <http://www.wikidata.org/prop/statement/>
PREFIX pq: <http://www.wikidata.org/prop/qualifier/>
PREFIX pr: <http://www.wikidata.org/prop/reference/>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
"""


@dataclass
class Candidate:
    person_qid: str
    person_label: str
    st_snak: str            # floruit statement GUID, e.g. "Q132997957$8F3C-..."
    title: str
    lang: str               # title language tag, e.g. "de"
    role: str               # subject-has-role QID
    # bibliographic ids found in the reference: [(property, value), ...]
    ids: List[Tuple[str, str]] = field(default_factory=list)


# ------------------------------------------------------------------------- QLever

def _qlever(query: str) -> List[dict]:
    """POST a SPARQL query to QLever, return the JSON result bindings."""
    req = urllib.request.Request(
        QLEVER,
        data=query.encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/sparql-query",
            "Accept": "application/sparql-results+json",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        payload = json.load(resp)
    return payload["results"]["bindings"]


def _last(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def _stmt_to_snak(stmt_uri: str) -> str:
    """.../statement/Q123-UUID  ->  Q123$UUID (the pywikibot claim id)."""
    sid = stmt_uri.rsplit("/statement/", 1)[-1]
    qid, _, rest = sid.partition("-")
    return f"{qid}${rest}"


def fetch_candidates(limit: Optional[int], qids: Optional[List[str]]) -> List[Candidate]:
    """Pull floruit statements in the inline-book shape whose reference carries a
    bibliographic-edition id. Rows are grouped into one Candidate per statement (a
    reference can hold more than one id)."""
    values = ""
    if qids:
        values = "  VALUES ?person { " + " ".join(f"wd:{q}" for q in qids) + " }\n"
    query = PREFIXES + f"""SELECT ?person ?personLabel ?stmt ?title ?role
       ?dnb ?sudoc ?gbooks ?openlib ?oclc WHERE {{
{values}  ?person p:P1317 ?stmt .
  ?stmt pq:P1476 ?title .
  ?stmt pq:P2868 ?role .
  ?stmt prov:wasDerivedFrom ?ref .
  {{ ?ref pr:P1292 ?dnb }} UNION {{ ?ref pr:P1025 ?sudoc }} UNION {{ ?ref pr:P675 ?gbooks }}
    UNION {{ ?ref pr:P648 ?openlib }} UNION {{ ?ref pr:P243 ?oclc }}
  OPTIONAL {{ ?person rdfs:label ?en . FILTER(LANG(?en) = "en") }}
  OPTIONAL {{ ?person rdfs:label ?mul . FILTER(LANG(?mul) = "mul") }}
  BIND(COALESCE(?en, ?mul) AS ?personLabel)
}}
ORDER BY ?person ?stmt"""

    candidates = _candidates_from_bindings(_qlever(query))
    if limit is not None:
        candidates = candidates[:limit]
    return candidates


def _candidates_from_bindings(bindings: List[dict]) -> List[Candidate]:
    """Group SPARQL result rows into one Candidate per floruit statement, collecting
    every bibliographic id found across that statement's rows (pure; offline-testable)."""
    by_snak: Dict[str, Candidate] = {}
    order: List[str] = []
    for b in bindings:
        snak = _stmt_to_snak(b["stmt"]["value"])
        cand = by_snak.get(snak)
        if cand is None:
            cand = Candidate(
                person_qid=_last(b["person"]["value"]),
                person_label=b.get("personLabel", {}).get("value", ""),
                st_snak=snak,
                title=b["title"]["value"],
                lang=b["title"].get("xml:lang", ""),
                role=_last(b["role"]["value"]),
            )
            by_snak[snak] = cand
            order.append(snak)
        for col, pid in BOOK_ID_COLS:
            if col in b:
                pair = (pid, b[col]["value"])
                if pair not in cand.ids:
                    cand.ids.append(pair)
    return [by_snak[s] for s in order]


def find_existing_edition(id_prop: str, id_value: str) -> Optional[str]:
    """Return the QID of an item that already carries this identifier (so we reuse it
    instead of creating a duplicate), 'AMBIGUOUS' if more than one / an unexpected
    type, or None if there is none."""
    query = PREFIXES + f"""SELECT ?e ?type WHERE {{
  ?e wdt:{id_prop} "{id_value}" .
  OPTIONAL {{ ?e wdt:P31 ?type }}
}}"""
    rows = _qlever(query)
    qids = {_last(r["e"]["value"]) for r in rows}
    if not qids:
        return None
    if len(qids) > 1:
        return "AMBIGUOUS"
    qid = next(iter(qids))
    types = {_last(r["type"]["value"]) for r in rows if "type" in r}
    if types and EDITION_TYPE not in types and QID_WRITTEN_WORK not in types:
        return "AMBIGUOUS"   # holds the id but isn't a book/edition -- do not touch
    return qid


# --------------------------------------------------------------------------- build

def _lang_spec(specs: list, lang: str) -> None:
    lq = LANG_QID.get(lang)
    if lq:
        specs.append((wd.PID_LANGUAGE_OF_WORK_OR_NAME, lq, "item"))


def build_work(cand: Candidate) -> Tuple[dict, dict, list]:
    specs = [
        (wd.PID_INSTANCE_OF, QID_WRITTEN_WORK, "item"),
        (wd.PID_TITLE, (cand.title, cand.lang), "monolingual"),
    ]
    _lang_spec(specs, cand.lang)
    prop, level = ROLE_TO_PROP[cand.role]
    if level == "work":
        specs.append((prop, cand.person_qid, "item"))
    who = cand.person_label or cand.person_qid
    desc = f"{ROLE_DESC.get(cand.role, 'book by')} {who}"
    return {"mul": cand.title}, {"en": desc}, specs


def build_edition(cand: Candidate, work_qid: str,
                  ids: List[Tuple[str, str]]) -> Tuple[dict, dict, list]:
    specs = [
        (wd.PID_INSTANCE_OF, EDITION_TYPE, "item"),
        (wd.PID_EDITION_OR_TRANSLATION_OF, work_qid, "item"),
        (wd.PID_TITLE, (cand.title, cand.lang), "monolingual"),
    ]
    _lang_spec(specs, cand.lang)
    prop, level = ROLE_TO_PROP[cand.role]
    if level == "edition":
        specs.append((prop, cand.person_qid, "item"))
    for id_prop, id_value in ids:                       # moved off the reference
        specs.append((id_prop, id_value, "string"))
    return {"mul": cand.title}, {"en": "edition"}, specs


# ------------------------------------------------------------------------ per item

def _locate(cand: Candidate, test: bool):
    """Load the person page and find (floruit claim, its book-reference source, the ids
    in that source). Returns (page, claim, source, moved_ids); claim/source are None if
    the live data no longer matches the query (skip to review)."""
    person_item = pywikibot.ItemPage(get_repo(), cand.person_qid)
    page = cwd.WikiDataPage(item=person_item, test=test)
    page.edit_group = EDIT_GROUP
    page.summary = "move floruit book source from an inline id to a work/edition item"

    claim = None
    for c in page.claims.get(wd.PID_FLORUIT, []):
        if c.snak and c.snak.upper() == cand.st_snak.upper():
            claim = c
            break
    if claim is None:
        return page, None, None, []

    for src in claim.sources:
        moved = []
        for id_prop, id_value in cand.ids:
            if id_prop in src and any(s.getTarget() == id_value for s in src[id_prop]):
                moved.append((id_prop, id_value))
        if moved:
            return page, claim, src, moved
    return page, claim, None, []


def _apply_person_edit(page, claim, source, edition_qid: str,
                       moved_ids: List[Tuple[str, str]]) -> None:
    """Drop the title qualifier and rewrite the located reference to point at the
    edition item, then push the batched edit."""
    if claim.qualifiers and wd.PID_TITLE in claim.qualifiers:
        claim.qualifiers.pop(wd.PID_TITLE)
        page.claim_changed(claim)

    for id_prop, _ in moved_ids:                        # id now lives on the edition
        source.pop(id_prop, None)
    source.pop(wd.PID_STATED_IN, None)                  # replace "stated in <database>"
    stated = pywikibot.Claim(get_repo(), wd.PID_STATED_IN, is_reference=True)
    stated.setTarget(pywikibot.ItemPage(get_repo(), edition_qid))
    source[wd.PID_STATED_IN] = [stated]
    page.reference_changed(claim)

    page.apply()


def _ids_str(ids: List[Tuple[str, str]]) -> str:
    return ", ".join(f"{p}={v}" for p, v in ids)


def process_item(cand: Candidate, test: bool,
                 edition_cache: Dict[Tuple[str, str], str]) -> str:
    """Migrate one floruit statement. Returns a short status string for the report."""
    print(f"\n{cand.person_qid} ({cand.person_label}) "
          f"fl. — “{cand.title}” [{cand.lang}] "
          f"role {cand.role}  ids: {_ids_str(cand.ids)}")

    if cand.role not in ROLE_TO_PROP:
        print(f"  SKIP: role {cand.role} out of scope (music/film/other)")
        return "skip-role"

    page, claim, source, moved_ids = _locate(cand, test)
    if claim is None:
        print("  SKIP: floruit statement not found (data changed?)")
        return "skip-no-claim"
    if source is None:
        print("  SKIP: book identifier not found in any reference (data changed?)")
        return "skip-no-ref"

    cache_key = moved_ids[0]                             # dedup a shared book by its id
    edition_qid = edition_cache.get(cache_key)
    if edition_qid is None:
        found = find_existing_edition(*cache_key)
        if found == "AMBIGUOUS":
            print(f"  SKIP: {_ids_str(moved_ids[:1])} already on >1 item / wrong type")
            return "skip-ambiguous"
        edition_qid = found

    wl, wdesc, wspecs = build_work(cand)
    elabels, edesc, especs = build_edition(cand, edition_qid or "(the new work)", moved_ids)

    if test:
        if edition_qid:
            print(f"  reuse existing edition {edition_qid}")
        else:
            cwd.create_item(labels=wl, descriptions=wdesc, claim_specs=wspecs,
                            edit_group=EDIT_GROUP, test=True, summary="create written work")
            cwd.create_item(labels=elabels, descriptions=edesc, claim_specs=especs,
                            edit_group=EDIT_GROUP, test=True,
                            summary="create edition of the work")
        print(f"  person edit: drop qualifier {wd.PID_TITLE} (title); "
              f"reference stated in (P248) -> {edition_qid or '(new edition)'}, "
              f"remove {_ids_str(moved_ids)}")
        return "dry-run"

    if edition_qid:
        print(f"  reuse existing edition {edition_qid}")
    else:
        work_qid = cwd.create_item(labels=wl, descriptions=wdesc, claim_specs=wspecs,
                                   edit_group=EDIT_GROUP, test=False,
                                   summary="create written work", site=get_repo())
        print(f"  created work {work_qid}")
        especs = build_edition(cand, work_qid, moved_ids)[2]   # real P629 target
        edition_qid = cwd.create_item(labels=elabels, descriptions=edesc, claim_specs=especs,
                                      edit_group=EDIT_GROUP, test=False,
                                      summary=f"create edition of {work_qid}", site=get_repo())
        print(f"  created edition {edition_qid}")
    edition_cache[cache_key] = edition_qid

    _apply_person_edit(page, claim, source, edition_qid, moved_ids)
    print(f"  rewrote floruit reference -> {edition_qid}")
    return "done"


# ---------------------------------------------------------------------------- main

EDIT_GROUP = ""   # set in main(); shared by every create_item / page edit in the run


def daily_editgroup(tag: str) -> str:
    return hashlib.sha1(f"{tag}:{date.today().isoformat()}".encode()).hexdigest()[:12]


def _read_qids(path: Optional[str], one: Optional[str]) -> Optional[List[str]]:
    if one:
        return [one]
    if path:
        with open(path, encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    return None


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Migrate inline-book floruit references to work/edition items.")
    ap.add_argument("--save", action="store_true", help="really edit (default: dry run)")
    ap.add_argument("--qid", metavar="QID", help="only this person")
    ap.add_argument("--file", metavar="PATH", help="read person QIDs from a file")
    ap.add_argument("--limit", type=int, metavar="N", help="process at most N candidates")
    ap.add_argument("--editgroup", metavar="ID", help="override the per-day batch id")
    args = ap.parse_args()

    # Book titles are international; Windows consoles default to cp1252.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    global EDIT_GROUP
    EDIT_GROUP = args.editgroup or daily_editgroup("migrate_floruit_book")
    print(f"editgroup={EDIT_GROUP} ({'SAVE' if args.save else 'dry run'})", flush=True)

    if args.save:
        ensure_login()

    qids = _read_qids(args.file, args.qid)
    candidates = fetch_candidates(args.limit, qids)
    print(f"{len(candidates)} candidate statement(s)")

    edition_cache: Dict[Tuple[str, str], str] = {}
    counts: Dict[str, int] = {}
    for cand in candidates:
        try:
            status = process_item(cand, test=not args.save, edition_cache=edition_cache)
        except Exception as exc:                        # noqa: BLE001 -- report + continue
            status = "error"
            print(f"  ERROR: {exc}")
        counts[status] = counts.get(status, 0) + 1

    print("\n=== summary ===")
    for status, n in sorted(counts.items()):
        print(f"  {status}: {n}")
    print(f"editgroup https://editgroups.toolforge.org/b/CB/{EDIT_GROUP}/")


if __name__ == "__main__":
    main()
