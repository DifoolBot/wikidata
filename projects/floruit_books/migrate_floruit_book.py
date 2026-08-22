#!/usr/bin/env python3
"""migrate_floruit_book.py -- turn the "inline book" floruit shape into a real
book item, filling the edition from catalogue metadata you paste.

The old shape (mostly DifoolBot's own house style) is a person's floruit (P1317)
statement carrying qualifiers title (P1476) + subject has role (P2868), sourced by a
*database* reference that points at the book by a bibliographic identifier -- DNB
edition ID (P1292), SUDOC editions (P1025), Google Books (P675), Open Library (P648)
or OCLC (P243).

For each such statement this tool (interactively, under --save):
  * prints the source link(s) so you can open the catalogue / title page;
  * runs the shared make_book paste flow (shared_lib.book_paste) -- you paste the
    Google/DNB/archive.org metadata, it is seeded with the floruit's title/language and
    the person in their authorship role, you confirm publisher/date/ISBN/pages/...;
  * creates a WORK (P31 = written work) + EDITION (P31 = version/edition, P629 -> work,
    carrying the pasted facts and the bibliographic id moved off the reference), and
    links them (P747);
  * rewrites the floruit reference to stated in (P248) -> the new edition (keeping
    retrieved P813 + any URL P854), and drops the now-redundant title qualifier (P1476),
    keeping subject has role (P2868).

Without --save it just lists the pending candidates and their source links (dry run).

Scope: only references carrying one of the five bibliographic-edition identifiers above.
LC-authority (P244 = the person's own record), film-database and URL-only sources are
left untouched; roles other than author/writer/editor/illustrator are skipped.
Candidates come from QLever. All edits go through shared_lib.change_wikidata, in one
daily editgroups batch.

Usage (repo root, PYTHONPATH=projects;projects/shared_lib via .env):
    python projects/floruit_books/migrate_floruit_book.py                  # dry run: list the queue
    python projects/floruit_books/migrate_floruit_book.py --qid Q132997957 --save  # do one (paste)
    python projects/floruit_books/migrate_floruit_book.py --limit 5 --save          # do five
"""

import argparse
import io
import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pywikibot

import shared_lib.book_paste as bp
import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
from shared_lib.wikidata_site import ensure_login, get_repo

QLEVER = "https://qlever.dev/api/wikidata"
# Identify the client by the bot's user page, never a personal e-mail.
USER_AGENT = "DifoolBot/1.0 (https://www.wikidata.org/wiki/User:DifoolBot)"

QID_ILLUSTRATOR_ROLE = "Q644687"
# subject-has-role QID -> which make_book contributor list the person joins. Illustrator
# is handled separately (P110 on the edition). Roles absent here are out of scope --
# those sources are often music or film items, not books -- and are skipped.
ROLE_CONTRIB: Dict[str, str] = {
    "Q482980": "authors",    # author
    "Q36180": "authors",     # writer
    "Q33231": "authors",     # photographer (of a photo book) -> credited as P50 author
    "Q1114448": "authors",   # cartoonist -> credited as P50 author
    "Q1607826": "editors",   # editor
}

# The five bibliographic-edition identifiers we migrate, in the order the candidate
# query UNIONs them, each with the property it lives under and a catalogue URL template.
BOOK_ID_COLS: List[Tuple[str, str]] = [
    ("dnb", wd.PID_DNB_EDITION_ID),
    ("sudoc", wd.PID_SUDOC_EDITIONS),
    ("gbooks", wd.PID_GOOGLE_BOOKS_ID),
    ("openlib", wd.PID_OPEN_LIBRARY_ID),
    ("oclc", wd.PID_OCLC_CONTROL_NUMBER),
]
SOURCE_URL: Dict[str, str] = {
    wd.PID_DNB_EDITION_ID: "https://d-nb.info/{}",
    wd.PID_SUDOC_EDITIONS: "https://www.sudoc.fr/{}",
    wd.PID_GOOGLE_BOOKS_ID: "https://books.google.com/books?id={}",
    wd.PID_OPEN_LIBRARY_ID: "https://openlibrary.org/books/{}",
    wd.PID_OCLC_CONTROL_NUMBER: "https://search.worldcat.org/oclc/{}",
}
BOOK_ID_PROPS = {pid for _, pid in BOOK_ID_COLS}

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
    # an archive.org/details/ URL in the reference, if the book is pointed at that way
    ref_url: Optional[str] = None


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
    bibliographic-edition id."""
    values = ""
    if qids:
        values = "  VALUES ?person { " + " ".join(f"wd:{q}" for q in qids) + " }\n"
    # Only the five bibliographic-edition ids drive candidate selection. Matching an
    # archive.org P854 URL is deliberately NOT here: on QLever, filtering the huge P854
    # relation (CONTAINS, no usable index) times out even as an OPTIONAL. archive.org-only
    # sources are handled with --edition instead. No ORDER BY -- it forces a large sort.
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
}}"""

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
        if "refurl" in b and cand.ref_url is None:
            cand.ref_url = b["refurl"]["value"]
    return [by_snak[s] for s in order]


def _archive_id(url: Optional[str]) -> Optional[str]:
    """Internet Archive ID (P724) from an archive.org/details/<id> URL, else None.
    Ignores any trailing /page/... path so the bare item id is returned."""
    if not url:
        return None
    m = re.search(r"archive\.org/details/([^/?#]+)", url)
    return m.group(1) if m else None


def find_existing_edition(id_prop: str, id_value: str) -> Optional[str]:
    """QID of an item that already carries this identifier (reuse it instead of creating
    a duplicate), 'AMBIGUOUS' if more than one / an unexpected type, or None."""
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
    if types and bp.EDITION_TYPE not in types and bp.QID_WRITTEN_WORK not in types:
        return "AMBIGUOUS"   # holds the id but isn't a book/edition -- do not touch
    return qid


# ------------------------------------------------------------------ person edit

def _book_sources(sources, ids: List[Tuple[str, str]]):
    """From a claim's reference sources, the ones carrying one of ``ids``, plus every matched
    (property, value) across them (deduped, in source order). Pure -- offline-testable."""
    book_sources = []
    moved: List[Tuple[str, str]] = []
    for src in sources:
        src_ids = [(p, v) for (p, v) in ids
                   if p in src and any(s.getTarget() == v for s in src[p])]
        if src_ids:
            book_sources.append(src)
            for pair in src_ids:
                if pair not in moved:
                    moved.append(pair)
    return book_sources, moved


def _locate(cand: Candidate, test: bool, eg: str):
    """Load the person page and find its floruit claim, every reference source carrying one of
    the candidate's book ids, and all those ids. claim is None / book_sources is empty when the
    live data no longer matches the query."""
    person_item = pywikibot.ItemPage(get_repo(), cand.person_qid)
    page = cwd.WikiDataPage(item=person_item, test=test)
    page.edit_group = eg
    page.summary = "move floruit book source from an inline id to a work/edition item"

    claim = None
    for c in page.claims.get(wd.PID_FLORUIT, []):
        if c.snak and c.snak.upper() == cand.st_snak.upper():
            claim = c
            break
    if claim is None:
        return page, None, [], []
    book_sources, moved_ids = _book_sources(claim.sources, cand.ids)
    return page, claim, book_sources, moved_ids


def _apply_person_edit(page, claim, book_sources, edition_qid: str) -> None:
    """Drop the title qualifier; turn the first book reference into stated in (P248) -> the
    edition (dropping its book ids + old stated-in, keeping retrieved/URL); remove any other,
    now-redundant book references (their ids moved to the edition). Then push the edit."""
    if claim.qualifiers and wd.PID_TITLE in claim.qualifiers:
        claim.qualifiers.pop(wd.PID_TITLE)
        page.claim_changed(claim)

    primary = book_sources[0]
    for prop in BOOK_ID_PROPS:                          # ids now live on the edition
        primary.pop(prop, None)
    primary.pop(wd.PID_STATED_IN, None)                 # replace "stated in <database>"
    stated = pywikibot.Claim(get_repo(), wd.PID_STATED_IN, is_reference=True)
    stated.setTarget(pywikibot.ItemPage(get_repo(), edition_qid))
    primary[wd.PID_STATED_IN] = [stated]

    for extra in book_sources[1:]:                      # collapse duplicate book references
        claim.sources.remove(extra)

    page.reference_changed(claim)
    page.apply()


# --------------------------------------------------------- point at a known edition

def _floruit_with_qualifiers(page) -> list:
    """Floruit claims on the loaded page that carry both a title (P1476) and a subject
    has role (P2868) qualifier -- the inline-book shape, found without QLever."""
    out = []
    for claim in page.claims.get(wd.PID_FLORUIT, []):
        quals = claim.qualifiers or {}
        if wd.PID_TITLE in quals and wd.PID_SUBJECT_HAS_ROLE in quals:
            out.append(claim)
    return out


def _claim_titles(claim) -> set:
    """Lower-cased title (P1476) qualifier text(s) of a floruit claim."""
    return {q.getTarget().text.strip().lower()
            for q in (claim.qualifiers or {}).get(wd.PID_TITLE, [])
            if q.getTarget() is not None}


def _edition_titles(edition_qid: str) -> set:
    """Lower-cased titles of an edition item: its P1476 values and its labels."""
    ed = pywikibot.ItemPage(get_repo(), edition_qid)
    ed.get()
    titles = {c.getTarget().text.strip().lower()
              for c in ed.claims.get(wd.PID_TITLE, []) if c.getTarget() is not None}
    titles |= {lab.strip().lower() for lab in ed.labels.values()}
    return titles


def _titles_match(a: set, b: set) -> bool:
    """True if any title in a equals or is contained in one in b (or vice versa), so a
    floruit title with a subtitle still matches a shorter edition title."""
    return any(x == y or x in y or y in x for x in a for y in b)


def _pick_ref_source(claim):
    """The reference source to rewrite: the sole reference, else the one that carries a
    stated-in / bibliographic id / URL, else None (ambiguous -> skip)."""
    if not claim.sources:
        return None
    if len(claim.sources) == 1:
        return claim.sources[0]
    for src in claim.sources:
        if (wd.PID_STATED_IN in src or wd.PID_REFERENCE_URL in src
                or any(p in src for p in BOOK_ID_PROPS)):
            return src
    return None


def _bib_ids_in_source(source) -> List[Tuple[str, str]]:
    return [(p, snak.getTarget()) for p in BOOK_ID_PROPS if p in source
            for snak in source[p]]


def process_edition_mode(qid: str, edition_qid: str, eg: str, test: bool) -> str:
    """Point a person's floruit (matched by its title+role qualifiers) at an existing
    edition item: reference stated in (P248) -> edition, drop the title qualifier. No
    book is created and no QLever lookup is needed."""
    print(f"\n{qid} -> edition {edition_qid}")
    page = cwd.WikiDataPage(item=pywikibot.ItemPage(get_repo(), qid), test=test)
    page.edit_group = eg
    page.summary = "point floruit book source at a work/edition item"

    matches = _floruit_with_qualifiers(page)
    if not matches:
        print("  SKIP: no floruit statement with title+role qualifiers")
        return "skip-none"
    if len(matches) == 1:
        claim = matches[0]
    else:
        # a co-author with several books: pick the floruit whose title matches the edition
        by_title = [c for c in matches if _titles_match(_claim_titles(c),
                                                        _edition_titles(edition_qid))]
        if len(by_title) != 1:
            print(f"  SKIP: {len(matches)} floruit-book statements, "
                  f"{len(by_title)} match the edition title — can't disambiguate")
            return "skip-ambiguous"
        claim = by_title[0]
    source = _pick_ref_source(claim)
    if source is None:
        print("  SKIP: could not pick a single reference to rewrite")
        return "skip-no-ref"

    moved_ids = _bib_ids_in_source(source)
    if test:
        print(f"  (dry run) would set reference stated in (P248) -> {edition_qid}"
              f"{', remove ' + _ids_str(moved_ids) if moved_ids else ''}, "
              f"drop the title qualifier ({wd.PID_TITLE}).")
        return "dry-run"

    _apply_person_edit(page, claim, source, edition_qid, moved_ids)
    print(f"  pointed floruit reference -> {edition_qid}")
    return "done"


# ------------------------------------------------------------------ book create

def _prepend_person(people: list, entry: Tuple[str, Optional[str]]) -> list:
    """Put (person_qid, name) at the front of a make_book contributor list, dropping any
    duplicate of the same person (same QID, or a name-only entry with the same name)."""
    qid, name = entry
    kept = [(q, n) for (q, n) in people if q != qid and not (q is None and n == name)]
    return [entry] + kept


def _inject_person(facts: dict, cand: Candidate) -> None:
    """Credit the floruit person (with their QID) in the role the qualifier records."""
    entry = (cand.person_qid, cand.person_label or None)
    listname = ROLE_CONTRIB.get(cand.role)
    if listname:
        facts[listname] = _prepend_person(facts[listname], entry)
    # illustrator is added to the edition directly (see _extra_edition_specs)


def _extra_edition_specs(cand: Candidate, moved_ids: List[Tuple[str, str]]) -> list:
    """Edition specs beyond the make_book model: the bibliographic id(s) moved off the
    reference, an Internet Archive ID (P724) derived from an archive.org source URL, plus
    P110 when the person's role is illustrator."""
    extra = [(prop, value, "string") for prop, value in moved_ids]
    iaid = _archive_id(cand.ref_url)
    if iaid:
        extra.append((wd.PID_INTERNET_ARCHIVE_ID, iaid, "string"))
    if cand.role == QID_ILLUSTRATOR_ROLE:
        extra.append((wd.PID_ILLUSTRATOR, cand.person_qid, "item"))
    return extra


def _dedup_key(cand: Candidate,
               moved_ids: List[Tuple[str, str]]) -> Optional[Tuple[str, str]]:
    """The (property, value) used to find/reuse an existing edition: the first
    bibliographic id, else the archive.org id, else None (no dedup possible)."""
    if moved_ids:
        return moved_ids[0]
    iaid = _archive_id(cand.ref_url)
    return (wd.PID_INTERNET_ARCHIVE_ID, iaid) if iaid else None


def _moves_str(cand: Candidate, moved_ids: List[Tuple[str, str]]) -> str:
    parts = [f"{p}={v}" for p, v in moved_ids]
    iaid = _archive_id(cand.ref_url)
    if iaid:
        parts.append(f"{wd.PID_INTERNET_ARCHIVE_ID}={iaid}")
    return ", ".join(parts) or "(no id)"


def _link_edition(work_qid: str, ed_qid: str, quals: list, eg: str) -> None:
    work_page = cwd.WikiDataPage(item=pywikibot.ItemPage(get_repo(), work_qid), test=False)
    work_page.edit_group = eg
    link = pywikibot.Claim(get_repo(), wd.PID_HAS_EDITION_OR_TRANSLATION)
    link.setTarget(pywikibot.ItemPage(get_repo(), ed_qid))
    for qp, qv, qk in quals:
        q = pywikibot.Claim(get_repo(), qp, is_qualifier=True)
        q.setTarget(pywikibot.ItemPage(get_repo(), qv) if qk == "item" else qv)
        link.qualifiers.setdefault(qp, []).append(q)
    work_page.add_claim(wd.PID_HAS_EDITION_OR_TRANSLATION, link)
    work_page.apply()


def _create_book(facts: dict, extra_specs: list, eg: str) -> Optional[str]:
    """Preview and (after a confirm) create the WORK + EDITION + P747 link. Returns the
    edition QID, or None if the user declines."""
    wl, wdesc, wspecs = bp.build_work(facts)
    bp.preview("WORK", wl, wdesc, wspecs)
    el, edesc, especs = bp.build_edition(facts, "(the new work)")
    bp.preview("EDITION", el, edesc, especs + extra_specs)
    quals = bp.build_p747_quals(facts)
    print(f"    then: work P747 -> edition  {{{bp.quals_str(quals)}}}")
    if not bp.confirm("\nCREATE work + edition + rewrite the floruit reference?", True):
        return None

    work_qid = cwd.create_item(labels=wl, descriptions=wdesc, claim_specs=wspecs,
                               edit_group=eg, test=False, summary="create written work",
                               site=get_repo())
    if work_qid is None:
        raise RuntimeError("work creation returned no QID")
    print(f"  created work {work_qid}")
    especs = bp.build_edition(facts, work_qid)[2] + extra_specs   # real P629 target
    ed_qid = cwd.create_item(labels=el, descriptions=edesc, claim_specs=especs,
                             edit_group=eg, test=False,
                             summary=f"create edition of {work_qid}", site=get_repo())
    if ed_qid is None:
        raise RuntimeError("edition creation returned no QID")
    print(f"  created edition {ed_qid}")
    _link_edition(work_qid, ed_qid, quals, eg)
    return ed_qid


# ------------------------------------------------------------------ per item

def _ids_str(ids: List[Tuple[str, str]]) -> str:
    return ", ".join(f"{p}={v}" for p, v in ids)


def _print_sources(moved_ids: List[Tuple[str, str]], book_sources) -> None:
    for prop, value in moved_ids:
        tmpl = SOURCE_URL.get(prop)
        if tmpl:
            print(f"    source: {tmpl.format(value)}")
    for src in book_sources:
        for ref_url in src.get(wd.PID_REFERENCE_URL, []):
            print(f"    source: {ref_url.getTarget()}")


def _read_paste() -> str:
    print("  paste catalogue metadata (DNB / Google Books / archive.org), then a line "
          "with just '.'  (just '.' = skip fields, seed from the floruit only):")
    lines = []
    for line in sys.stdin:
        if line.rstrip("\n") == ".":
            break
        lines.append(line)
    return "".join(lines)


def process_item(cand: Candidate, test: bool, eg: str,
                 edition_cache: Dict[Tuple[str, str], str]) -> str:
    print(f"\n{cand.person_qid} ({cand.person_label}) — “{cand.title}” [{cand.lang}] "
          f"role {cand.role}  src: {_moves_str(cand, cand.ids)}")

    if cand.role not in ROLE_CONTRIB and cand.role != QID_ILLUSTRATOR_ROLE:
        print(f"  SKIP: role {cand.role} out of scope (music/film/other)")
        return "skip-role"

    page, claim, book_sources, moved_ids = _locate(cand, test, eg)
    if claim is None:
        print("  SKIP: floruit statement not found (data changed?)")
        return "skip-no-claim"
    if not book_sources:
        print("  SKIP: book identifier not found in any reference (data changed?)")
        return "skip-no-ref"

    _print_sources(moved_ids, book_sources)

    if test:
        role_word = "illustrator" if cand.role == QID_ILLUSTRATOR_ROLE else ROLE_CONTRIB[cand.role][:-1]
        print(f"  (dry run) would paste catalogue, create Work + Edition "
              f"(person as {role_word}, move {_moves_str(cand, moved_ids)}), "
              f"then rewrite the floruit reference. Run with --save.")
        return "dry-run"

    cache_key = _dedup_key(cand, moved_ids)             # dedup a shared book by its id
    edition_qid = edition_cache.get(cache_key) if cache_key else None
    if edition_qid is None and cache_key is not None:
        found = find_existing_edition(*cache_key)
        if found == "AMBIGUOUS":
            print(f"  SKIP: {cache_key[0]}={cache_key[1]} already on >1 item / wrong type")
            return "skip-ambiguous"
        edition_qid = found

    if edition_qid:
        if not bp.confirm(f"  reuse existing edition {edition_qid} for this floruit?", True):
            print("  skipped by user")
            return "skip-user"
    else:
        parsed = bp.parse_metadata(_read_paste())
        facts = bp.confirm_facts(parsed, seed_title=cand.title, seed_lang=cand.lang)
        _inject_person(facts, cand)
        edition_qid = _create_book(facts, _extra_edition_specs(cand, moved_ids), eg)
        if edition_qid is None:
            print("  declined")
            return "skip-declined"
        if cache_key:
            edition_cache[cache_key] = edition_qid

    _apply_person_edit(page, claim, book_sources, edition_qid)
    print(f"  rewrote floruit reference -> {edition_qid}"
          + (f" (collapsed {len(book_sources)} book references)" if len(book_sources) > 1 else ""))
    return "done"


# ---------------------------------------------------------------------------- main

def _read_qids(path: Optional[str], one: Optional[str]) -> Optional[List[str]]:
    if one:
        return [one]
    if path:
        with open(path, encoding="utf-8") as f:                 # first token per line is
            return [ln.split()[0] for ln in f                   # the QID, so the written
                    if ln.strip() and not ln.lstrip().startswith("#")]   # list round-trips
    return None


def _write_candidate_list(candidates: List[Candidate]) -> str:
    """Write the current candidates to output/candidates.txt (QID + context, one per
    line). The QID is the first token, so the file is itself valid input to --file."""
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "candidates.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {len(candidates)} floruit-book candidates  "
                "(QID <tab> role <tab> ids/url <tab> title); usable with --file\n")
        for c in candidates:
            f.write(f"{c.person_qid}\t{c.role}\t{_moves_str(c, c.ids)}\t{c.title}\n")
    return path


def _print_summary(counts: Dict[str, int], eg: str) -> None:
    print("\n=== summary ===")
    for status, n in sorted(counts.items()):
        print(f"  {status}: {n}")
    print(f"editgroup https://editgroups.toolforge.org/b/CB/{eg}/")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Migrate inline-book floruit references to work/edition items.")
    ap.add_argument("--save", action="store_true",
                    help="interactive create + edit (default: dry run, just list the queue)")
    ap.add_argument("--qid", metavar="QID", help="only this person")
    ap.add_argument("--file", metavar="PATH", help="read person QIDs from a file")
    ap.add_argument("--limit", type=int, metavar="N", help="process at most N candidates")
    ap.add_argument("--editgroup", metavar="ID", help="override the per-day batch id")
    ap.add_argument("--edition", metavar="QID",
                    help="point the --qid/--file person(s) at this existing edition and drop "
                         "the title qualifier; no book is created, no QLever lookup")
    args = ap.parse_args()

    # Book titles are international; Windows consoles default to cp1252.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    eg = args.editgroup or bp.daily_editgroup("migrate_floruit_book")
    print(f"editgroup={eg} ({'SAVE' if args.save else 'dry run'})", flush=True)

    if args.save:
        ensure_login()

    qids = _read_qids(args.file, args.qid)
    counts: Dict[str, int] = {}

    if args.edition:
        if not qids:
            ap.error("--edition requires --qid or --file")
        for qid in qids:
            try:
                status = process_edition_mode(qid, args.edition, eg, test=not args.save)
            except Exception as exc:                    # noqa: BLE001 -- report + continue
                status = "error"
                print(f"  ERROR: {exc}")
            counts[status] = counts.get(status, 0) + 1
        _print_summary(counts, eg)
        return

    candidates = fetch_candidates(args.limit, qids)
    print(f"{len(candidates)} candidate statement(s)")
    print(f"candidate list -> {_write_candidate_list(candidates)}")

    edition_cache: Dict[Tuple[str, str], str] = {}
    for cand in candidates:
        try:
            status = process_item(cand, test=not args.save, eg=eg, edition_cache=edition_cache)
        except Exception as exc:                        # noqa: BLE001 -- report + continue
            status = "error"
            print(f"  ERROR: {exc}")
        counts[status] = counts.get(status, 0) + 1

    _print_summary(counts, eg)


if __name__ == "__main__":
    main()
