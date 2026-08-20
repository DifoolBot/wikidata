"""curate_pd_works -- interactive cleanup of public-domain *work* items that carry
edition-level identifiers (Target 2).

Like curate_selfpub.py but for the FRBR work/edition problem on copyright-free works:
iterate public-domain works (author died <= cutoff) that hold edition-only IDENTIFIERS
directly on the work (ISBN, Project Gutenberg ID, HathiTrust, …), and for each one ask
the human what to do:

  [c] CREATE a new edition item to hold it  -- a Project Gutenberg etext *is* a distinct
      digital edition, so the right fix is a new `version, edition or translation` item
      (P629 -> work, P747 <- work) carrying the ID, not just deleting it. Built to the
      convention the 823 existing Gutenberg editions follow (see notes/isbn_bot.md):
      P31=Q3331189, P629, P2034, P1476 (title copied), P407 (language copied), P50
      (authors copied), P123=Project Gutenberg (Q22673), P6216=public domain (Q19652).
  [m] MOVE to an existing linked edition -- add the ID there, deprecate it on the work.
  [d] DEPRECATE on the work only -- belongs to a version not (yet) in Wikidata.
  [k] KEEP.

Identifiers are NEVER deleted by the bot -- they are deprecated (rank=deprecated +
P2241 = Q51845721 "applies to a different version of this work"); a human verifies and
deletes (see memory deprecate-not-delete-ids). Publisher (P123) is not an identifier and
uses the first-edition heuristic (offer to move to the earliest-dated edition).

Reuses curate_selfpub's ask/confirm/label/page_for/_deprecate/edition_with and
mark_selfpublished's live()/linked_editions(); creates items via
change_wikidata.create_item. Dry-run default (`--save`), `--qid`/`--file`/`--limit`,
`--death-year`, stable per-day editgroup, `pd_curate_done.txt` state.
"""
import argparse
import csv
import gzip
import hashlib
import html
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import pywikibot
import requests
from pywikibot.data import api as pwb_api
from stdnum import isbn as stdnum_isbn

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
from shared_lib.config import get_env
from shared_lib.date_value import Date
import mark_selfpublished as msp
import curate_selfpub as csp

QLEVER_URL = "https://qlever.dev/api/wikidata"
USER_AGENT = "DifoolBot/1.0 (https://www.wikidata.org/wiki/User:DifoolBot)"
PREFIXES = ("PREFIX wdt: <http://www.wikidata.org/prop/direct/>\n"
            "PREFIX wd: <http://www.wikidata.org/entity/>\n")

EDITION_TYPE = "Q3331189"        # version, edition or translation
QID_PUBLIC_DOMAIN = "Q19652"     # public domain (P6216 value)
QID_EBOOK = "Q128093"            # ebook (P437 distribution format value)
QID_FIRST_EDITION = "Q10898227"  # first edition (P31 value / a subclass of edition)
QID_REDIRECT = "Q45403344"       # P2241 reason: identifier redirects to another identifier
DEFAULT_DEATH_YEAR = 1930

HERE = Path(__file__).parent
DATA_FILE = HERE / "data" / "edition_only_identifiers.tsv"
# Project Gutenberg's bulk catalog (their sanctioned metadata source -- do NOT scrape the
# site). Columns: Text#, Type, Issued, Title, Language, Authors, Subjects, LoCC,
# Bookshelves. `Issued` is the ebook release date (-> P577); `Text#` is the P2034 id.
PG_CATALOG_FILE = HERE / "data" / "pg_catalog.csv.gz"
OUTPUT_DIR = HERE / "output"
DONE_FILE = OUTPUT_DIR / "pd_curate_done.txt"

repo = msp.repo
live = msp.live

# Properties for which we have a "create a new edition item" template. Everything else
# gets move/deprecate only. Project Gutenberg builds from its bulk catalog; Internet Archive
# builds from the scan's linked Open Library *edition* record (see build_openlibrary_specs).
CREATE_TEMPLATES = {wd.PID_PROJECT_GUTENBERG_EBOOK_ID, wd.PID_INTERNET_ARCHIVE_ID}


def load_edition_only_ids() -> dict[str, str]:
    """pid -> label for the external-id edition-only properties (from the collected TSV).
    These are the identifiers that trigger the 'should be an edition' constraint on a
    work; the per-work handler only acts on the ones actually present."""
    ids = {}
    if DATA_FILE.exists():
        for i, line in enumerate(open(DATA_FILE, encoding="utf-8")):
            if i == 0:
                continue
            f = line.rstrip("\n").split("\t")
            if len(f) >= 3 and f[2] == "ExternalId":
                ids[f[0]] = f[1]
    # ISBN-13/10 are ExternalId edition-only too; ensure present
    ids.setdefault(wd.PID_ISBN_13, "ISBN-13")
    ids.setdefault(wd.PID_ISBN_10, "ISBN-10")
    # A few edition-level ids use a *conflicts-with P747* constraint (not a type
    # constraint), so they aren't in the tsv -- add them explicitly:
    #   P243 OCLC *number* (vs P5331 OCLC work ID, obsolete/work-level -- left alone),
    #   P675 Google Books ID (a Google Books volume = one scanned edition).
    ids.setdefault(wd.PID_OCLC_CONTROL_NUMBER, "OCLC number")
    ids.setdefault(wd.PID_GOOGLE_BOOKS_ID, "Google Books ID")
    # Internet Archive scan id (P724): one archive.org item = one scanned edition, so it's
    # edition-only. Not in the tsv (its constraint is conflicts-with P747, not a type
    # constraint). The break-out template fills the new edition from Open Library.
    ids.setdefault(wd.PID_INTERNET_ARCHIVE_ID, "Internet Archive ID")
    return ids


EDITION_ONLY_IDS = load_edition_only_ids()

_PG_CATALOG: dict | None = None


def pg_catalog() -> dict:
    """Lazy-load the Project Gutenberg catalog into {Text#: {issued, title, language,
    type}}. Empty (with a warning) if the dump isn't present -- the tool still works, it
    just can't fill P577 / cross-check titles."""
    global _PG_CATALOG
    if _PG_CATALOG is None:
        _PG_CATALOG = {}
        if PG_CATALOG_FILE.exists():
            with gzip.open(PG_CATALOG_FILE, "rt", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    _PG_CATALOG[row["Text#"].strip()] = {
                        "issued": row["Issued"].strip(),
                        "title": row["Title"].strip(),
                        "language": row["Language"].strip(),
                        "type": row["Type"].strip(),
                    }
            print(f"loaded Project Gutenberg catalog: {len(_PG_CATALOG)} ebooks")
        else:
            print(f"! {PG_CATALOG_FILE.name} not found -- P577 (release date) will be omitted")
    return _PG_CATALOG


def _http(method: str, url: str, retry_429: bool = True, **kwargs):
    """requests with polite retry/backoff on HTTP 429 (rate limit) and transient errors.
    All the tool's direct HTTP (QLever, the Wikidata search API, Open Library) goes through
    here so a throttle backs off instead of hard-failing; pywikibot handles its own edit/read
    throttling separately. Returns the Response, or None if it kept failing.

    ``retry_429=False`` returns the 429 response immediately without backing off -- for APIs
    whose 429 is a *daily quota* (Google Books, no key) rather than a short-term throttle, where
    waiting 10-50s is pointless and the caller just falls back to manual entry."""
    kwargs.setdefault("headers", {"User-Agent": USER_AGENT})
    for attempt in range(5):
        try:
            r = requests.request(method, url, **kwargs)
        except requests.RequestException as e:
            if attempt == 4:
                print(f"  ! HTTP error for {url.split('?')[0]}: {e}")
                return None
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code == 429 and retry_429:
            wait = 10 * (attempt + 1)
            print(f"  (rate-limited 429; backing off {wait}s)", flush=True)
            time.sleep(wait)
            continue
        return r
    print(f"  ! gave up after repeated 429s for {url.split('?')[0]}")
    return None


_LANG_QID: dict | None = None
_CODE_BY_QID: dict = {}


def _run_lang_query(pid: str, code_to_qid: bool):
    """Load a `?item wdt:<pid> ?code` map from QLever into _LANG_QID (code -> qid). When
    ``code_to_qid`` also fills _CODE_BY_QID (qid -> code) -- only from P218, so language_code
    keeps returning the ISO 639-1 code (used as a monolingual-text language)."""
    q = f"SELECT ?c ?i WHERE {{ ?i wdt:{pid} ?c }}"
    r = _http("POST", QLEVER_URL, data={"query": PREFIXES + q},
              headers={"User-Agent": USER_AGENT, "Accept": "text/tab-separated-values"}, timeout=120)
    if r is None:
        print(f"! could not load language codes ({pid}); will fall back to the work's language")
        return
    for line in r.text.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) >= 2:
            c = parts[0].strip().strip('"')
            qid = parts[1].strip().rsplit("/", 1)[-1].rstrip(">")
            if c and qid.startswith("Q"):
                _LANG_QID.setdefault(c, qid)
                if code_to_qid:
                    _CODE_BY_QID.setdefault(qid, c)


def _load_language_map() -> None:
    """Load language code -> QID (and the reverse for 639-1), once, from QLever. Loads
    ISO 639-1 (P218) plus 639-2 (P219) and 639-3 (P220) so Open Library codes like 'fre'
    resolve (OL uses MARC/639-2, not the 2-letter codes)."""
    global _LANG_QID
    if _LANG_QID is not None:
        return
    _LANG_QID = {}
    _run_lang_query("P218", code_to_qid=True)     # ISO 639-1, 2-letter (title language)
    _run_lang_query("P219", code_to_qid=False)    # ISO 639-2, 'fre'/'eng' (Open Library)
    _run_lang_query("P220", code_to_qid=False)    # ISO 639-3


def language_qid(code: str) -> str | None:
    """ISO 639-1 code (e.g. 'en', 'de') -> the language item QID (Q1860, Q188 ...), via P218.
    The Gutenberg catalog's per-ebook Language is authoritative for the *edition* -- a
    translation has a different language than the work, so we must NOT copy the work's
    language onto it."""
    _load_language_map()
    return _LANG_QID.get(code) if _LANG_QID else None


def language_code(qid: str) -> str | None:
    """Language-item QID -> ISO 639-1 code (Q1860 -> 'en'). Used to pick the work's title in
    its OWN language (a work can carry a translation's title in P1476/labels)."""
    _load_language_map()
    return _CODE_BY_QID.get(qid)


def move_p747_first(work_qid: str, target_qid: str, edit_group: str) -> bool:
    """Move the work's `P747 -> target_qid` statement to the TOP of the P747 group, so a
    newly created first edition sorts first. Uses the API's `wbsetclaim` with `index=0`
    (editEntity/add_claim can only append). Best-effort: returns False if the statement isn't
    found; raises on API failure (caller wraps it)."""
    item = pywikibot.ItemPage(repo, work_qid)
    item.get(force=True)
    for c in item.claims.get(wd.PID_HAS_EDITION_OR_TRANSLATION, []):
        t = c.getTarget()
        if t and t.getID() == target_qid:
            summary = "move first edition to top of has edition or translation (P747)"
            if edit_group:
                summary += f" ([[:toolforge:editgroups/b/CB/{edit_group}|details]])"
            pwb_api.Request(site=repo, parameters={
                "action": "wbsetclaim",
                "claim": json.dumps(c.toJSON()),
                "index": 0,                       # position within the P747 group
                "summary": summary,
                "bot": True,
                "token": repo.tokens["csrf"],
            }).submit()
            return True
    return False


def _first_time(item, pid):
    """First live P577-style WbTime target on an item (None if none)."""
    for c in live(item.claims.get(pid, [])):
        t = c.getTarget()
        if t is not None and hasattr(t, "year"):
            return t
    return None


def _p747_sort_key(wbtime):
    """Sort key for a P747 edition by publication date; undated editions sort last."""
    if wbtime is None:
        return (9999, 99, 99)
    return (wbtime.year or 9999, wbtime.month or 0, wbtime.day or 0)


def _reorder_p747(work_qid, desired_qids, edit_group) -> int:
    """Reorder the work's P747 group into ``desired_qids`` in a SINGLE edit, via the
    remove-then-re-add technique the RearrangeValues gadget uses: one wbeditentity whose claims
    array first removes every P747 statement, then re-adds them all (full JSON, same GUIDs so
    qualifiers/references/ranks are preserved) in the desired order -- Wikibase applies the array
    in sequence, so that order becomes the stored order. Re-fetches first so the JSON is current
    (post qualifier-edits). Returns 1 if an edit was submitted, else 0."""
    item = pywikibot.ItemPage(repo, work_qid)
    item.get(force=True)
    jclaims = [c.toJSON() for c in item.claims.get(wd.PID_HAS_EDITION_OR_TRANSLATION, [])]
    if not jclaims:
        return 0
    by_qid = {}
    for j in jclaims:
        try:
            q = j["mainsnak"]["datavalue"]["value"]["id"]      # target QID (item value)
        except (KeyError, TypeError):
            continue
        by_qid.setdefault(q, j)
    ordered, seen = [], set()
    for q in desired_qids:                          # desired order first
        j = by_qid.get(q)
        if j and j["id"] not in seen:
            ordered.append(j)
            seen.add(j["id"])
    for j in jclaims:                               # any leftovers (novalue/somevalue) keep order, at end
        if j["id"] not in seen:
            ordered.append(j)
            seen.add(j["id"])
    remove = [{"id": j["id"], "remove": ""} for j in ordered]
    data = {"claims": remove + ordered}             # remove all, then re-add in the new order
    summary = "sort has edition or translation (P747) by publication date"
    if edit_group:
        summary += f" ([[:toolforge:editgroups/b/CB/{edit_group}|details]])"
    pwb_api.Request(site=repo, parameters={
        "action": "wbeditentity",
        "id": work_qid,
        "data": json.dumps(data),
        "summary": summary,
        "bot": True,
        "token": repo.tokens["csrf"],
    }).submit()
    return 1


def refresh_p747(work_qid, edit_group, dry_run) -> bool:
    """For a work (--refresh-p747), add summary qualifiers to each 'has edition or translation'
    (P747) statement -- P407 (language), P577 (publication date), and P123 (publisher) or, only
    when the edition has no publisher, P291 (place of publication) -- read from the linked
    edition, and sort the P747 statements by the edition's publication date (ascending; undated
    last). Qualifiers already present are left untouched (add-if-missing; mismatches are only
    reported, never overwritten). Returns True if anything was applied."""
    item = pywikibot.ItemPage(repo, work_qid)
    page = cwd.WikiDataPage(item, test=dry_run)
    page.edit_group = edit_group
    p747 = list(page.claims.get(wd.PID_HAS_EDITION_OR_TRANSLATION, []))
    if not p747:
        print(f"  {work_qid}: no P747 (has edition or translation) statements.")
        return False
    print(f"\n=== {work_qid}  \"{item.labels.get('en', work_qid)}\"  -- {len(p747)} edition(s)")

    order = []       # (sortkey, ed_qid) in current claim order
    changed = False
    for claim in p747:
        target = claim.getTarget()
        if not target or not hasattr(target, "getID"):
            continue
        ed_qid = target.getID()
        try:
            target.get()                          # load the edition's own claims
        except Exception as e:
            print(f"  ! could not load edition {ed_qid} ({e}); leaving as-is")
            order.append(((9999, 99, 99), ed_qid))
            continue
        lang = first_item(target, wd.PID_LANGUAGE_OF_WORK_OR_NAME)
        date = _first_time(target, wd.PID_PUBLICATION_DATE)
        pub = first_item(target, wd.PID_PUBLISHER)
        place = None if pub else first_item(target, wd.PID_PLACE_OF_PUBLICATION)

        wanted = [(wd.PID_LANGUAGE_OF_WORK_OR_NAME, lang, "item"),
                  (wd.PID_PUBLICATION_DATE, date, "time"),
                  (wd.PID_PUBLISHER, pub, "item") if pub else
                  (wd.PID_PLACE_OF_PUBLICATION, place, "item")]
        adds, present = [], []
        for qpid, val, kind in wanted:
            if not val:
                continue
            if qpid in claim.qualifiers:
                present.append(qpid)
                continue
            q = (cwd.DateQualifier(qpid, Date.create_from_WbTime(val)) if kind == "time"
                 else cwd.ItemQualifier(qpid, val))
            page.add_qualifier(wd.PID_HAS_EDITION_OR_TRANSLATION, claim, q)
            adds.append(f"{qpid}={val.year if kind == 'time' else val}")

        yr = date.year if date else "?"
        print(f"  {ed_qid} \"{csp.label(ed_qid)[:34]:34}\" P577={yr}"
              + (f"  + {', '.join(adds)}" if adds else "  (qualifiers already present)"))
        if adds:
            changed = True
        order.append((_p747_sort_key(date), ed_qid))

    current = [ed for _, ed in order]
    desired = [ed for _, ed in sorted(order, key=lambda t: (t[0], t[1]))]

    page.apply()                                  # commit the qualifier additions first
    if desired != current:
        print("  sort P747 by date (1 edit):")
        print(f"     {' , '.join(current)}")
        print(f"  -> {' , '.join(desired)}")
        if not dry_run:
            _reorder_p747(work_qid, desired, edit_group)
        changed = True
    else:
        print("  P747 already in date order.")
    return changed


def existing_edition_with_id(pid: str, value, exclude_qid: str) -> str | None:
    """QID of an EXISTING item that already carries ``pid = value`` (excluding
    ``exclude_qid``), else None -- so a re-run (e.g. after a partial-failure --save) REUSES
    the item instead of creating a duplicate. Uses the live MediaWiki search index
    (haswbstatement) -- the QLever dump is stale for freshly-created items. Excludes the work
    being processed (it still carries the id until its deprecation lands).

    Goes through pywikibot's authenticated API session (`api.Request`) so it rides the bot
    account's rate allowance + pywikibot's built-in throttling/429 handling, rather than an
    anonymous `requests` call that competes for the strict shared limit."""
    try:
        data = pwb_api.Request(site=repo, parameters={
            "action": "query", "list": "search", "srlimit": 20,
            "srsearch": f"haswbstatement:{pid}={value}"}).submit()
    except Exception as e:
        print(f"  ! could not check for an existing edition with {pid}={value} ({e}); assuming none")
        return None
    for hit in data.get("query", {}).get("search", []):
        qid = hit.get("title", "")
        if qid.startswith("Q") and qid != exclude_qid:
            return qid
    return None


def existing_gutenberg_edition(gid: str, exclude_qid: str) -> str | None:
    """QID of an existing edition carrying this Gutenberg id (else None). Thin wrapper over
    existing_edition_with_id."""
    return existing_edition_with_id(wd.PID_PROJECT_GUTENBERG_EBOOK_ID, gid, exclude_qid)


def fetch_candidates(death_year: int) -> list[str]:
    vals = " ".join(f"wdt:{p}" for p in EDITION_ONLY_IDS)
    query = f"""SELECT DISTINCT ?item WHERE {{
  ?item wdt:{wd.PID_HAS_EDITION_OR_TRANSLATION} ?ed .
  ?item wdt:{wd.PID_AUTHOR} ?a . ?a wdt:{wd.PID_DATE_OF_DEATH} ?dod .
  FILTER(YEAR(?dod) <= {death_year})
  ?item ?p [] . VALUES ?p {{ {vals} }}
}}
ORDER BY ?item"""
    r = _http("POST", QLEVER_URL, data={"query": PREFIXES + query},
              headers={"User-Agent": USER_AGENT, "Accept": "text/tab-separated-values"}, timeout=300)
    if r is None:
        raise SystemExit("could not fetch candidates (rate-limited); wait a bit and retry")
    return [q for line in r.text.splitlines()[1:]
            if (q := line.strip().rsplit("/", 1)[-1].rstrip(">")).startswith("Q")]


# ---- helpers -------------------------------------------------------------------------

def _clean_title(s: str) -> str:
    """Normalise a title for use as a Wikidata label / monolingual value. Collapses ALL
    whitespace -- including newlines and tabs, which Wikidata forbids in labels/mono-text
    (PG catalog titles sometimes span lines: title + subtitle, e.g. ebook 47584) -- to
    single spaces, and drops a stray surrounding straight-double-quote pair (e.g. Q890170)."""
    s = " ".join(s.split())
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1].strip()
    return s


def work_title(item, page):
    """(text, lang) for the work's title in its OWN language. A work can carry a *translation's*
    title (P1476/label in another language, e.g. Q1156969 "Daddy-Long-Legs" has a stray
    P1476='papaito piernas largas'@es) -- picking the first P1476 blindly produced a
    Spanish-titled English edition. So prefer the P1476 whose language matches the work's P407,
    then the label in that language, then the English label, and only then any P1476/en label."""
    titles = [(t.text, t.language) for c in live(page.claims.get(wd.PID_TITLE, []))
              if (t := c.getTarget())]
    work_lang = first_item(page, wd.PID_LANGUAGE_OF_WORK_OR_NAME)
    want = language_code(work_lang) if work_lang else None
    if want:
        for text, lang in titles:
            if lang == want:
                return (_clean_title(text), lang)
        if item.labels.get(want):
            return (_clean_title(item.labels[want]), want)
    if item.labels.get("en"):
        return (_clean_title(item.labels["en"]), "en")
    if titles:
        return (_clean_title(titles[0][0]), titles[0][1])
    return None


def first_item(page, pid) -> str | None:
    for c in live(page.claims.get(pid, [])):
        t = c.getTarget()
        if t and hasattr(t, "getID"):
            return t.getID()
    return None


def show_state(qid, item, page, editions) -> None:
    lab = item.labels.get("en", "(no label)")
    p31 = ", ".join(csp.label(c.getTarget().getID())
                    for c in live(page.claims.get("P31", [])) if c.getTarget())
    print(f"\n=== {qid}  \"{lab}\"  ({p31})")
    authors = [c.getTarget().getID() for c in live(page.claims.get(wd.PID_AUTHOR, [])) if c.getTarget()]
    print(f"  authors : {', '.join(f'{csp.label(a)} ({a})' for a in authors) or '(none)'}")
    first_ids = {e.getID() for e in first_version_editions(editions)}
    print(f"  editions ({len(editions)}):")
    for e in editions:
        yr = next((str(c.getTarget().year) for c in live(e.claims.get(wd.PID_PUBLICATION_DATE, []))
                   if c.getTarget()), "?")
        ids = [p for p in EDITION_ONLY_IDS if live(e.claims.get(p, []))]
        pubs = ",".join(csp.label(x.getTarget().getID()) for x in live(e.claims.get(wd.PID_PUBLISHER, []))
                        if x.getTarget()) or "-"
        mark = " [FIRST]" if e.getID() in first_ids else ""
        print(f"     {e.getID():11} \"{e.labels.get('en','')[:30]:30}\" P577={yr}  "
              f"P123={pubs}  ids={','.join(ids) or '-'}{mark}")
    if not first_ids:
        print("  (no edition marked as first version [P393=1 / P31=first edition])")
    print("  -- edition-only IDENTIFIERS sitting on the WORK:")
    for pid, plabel in EDITION_ONLY_IDS.items():
        for c in live(page.claims.get(pid, [])):
            print(f"     {pid} ({plabel}) = {c.getTarget()}")


def build_gutenberg_specs(work_page, work_qid, gutenberg_id, volume=None):
    """Return (labels, descriptions, claim_specs, p747_quals) for a new Gutenberg edition
    of the work. None if the work has no usable title. Pure -- no side effects (creation
    is deferred to after the confirm). Modeled on a well-formed example, Q106304446: a
    version item with P31/P629/P2034/P50/P123=Project Gutenberg/P407/P577/P1476, plus
    **P437 = ebook (Q128093)** and an en description **"<year> gutenberg version"**.

    ``p747_quals`` are (pid, value, kind) qualifiers summarising the edition inline on the
    work's P747 statement (dominant P747 qualifiers measured 2026-07-30: P407 language,
    P577 date, P123 publisher, P437 format).

    ``volume``: for a multi-volume set, the volume number (e.g. "1") -- the P2034 statement
    is then qualified with P478 (volume) and the volume marker is stripped from the title,
    so this item can hold all volumes' ids (add the rest by hand)."""
    authors = [c.getTarget().getID() for c in live(work_page.claims.get(wd.PID_AUTHOR, [])) if c.getTarget()]

    # The catalog is authoritative for THIS ebook's language/title/date -- crucial for a
    # translation, whose language differs from the work's (e.g. an English Gutenberg
    # translation of a German play). Fall back to the work only when the id isn't listed.
    entry = pg_catalog().get(str(gutenberg_id).strip())
    issued = None
    title = None
    lang_qid = None
    if entry:
        print(f"    PG catalog: \"{entry['title']}\" ({entry['language']}) "
              f"issued {entry['issued']} [{entry['type']}]")
        if entry["type"] == "Text":
            issued = csp.parse_wbtime(entry["issued"])
        code = entry["language"].split(";")[0].strip()  # ISO 639-1, usually a single code
        lang_qid = language_qid(code)
        if entry["title"]:
            ct = entry["title"]
            if volume:                                     # drop 'Vol. N' -> work-level title
                mk = volume_marker(ct)
                if mk:
                    ct = _strip_volume(ct, mk)
            title = (_clean_title(ct), code)               # edition title in the edition's language
        work_lang = first_item(work_page, wd.PID_LANGUAGE_OF_WORK_OR_NAME)
        if lang_qid and work_lang and lang_qid != work_lang:
            print(f"    -> translation: edition language {code} ({lang_qid}) "
                  f"differs from the work ({work_lang})")
    else:
        print(f"    ! Gutenberg {gutenberg_id} not in the catalog -- using the work's title/language")
    if title is None:
        title = work_title(work_page.item, work_page)
    if not title:
        return None
    if lang_qid is None:
        lang_qid = first_item(work_page, wd.PID_LANGUAGE_OF_WORK_OR_NAME)

    p2034 = (wd.PID_PROJECT_GUTENBERG_EBOOK_ID, gutenberg_id, "string")
    if volume:                                             # P2034 = id {P478 = volume}
        p2034 = (wd.PID_PROJECT_GUTENBERG_EBOOK_ID, gutenberg_id, "string",
                 [(wd.PID_VOLUME, volume, "string")])
    specs = [
        (wd.PID_INSTANCE_OF, EDITION_TYPE, "item"),
        (wd.PID_EDITION_OR_TRANSLATION_OF, work_qid, "item"),
        p2034,
        (wd.PID_TITLE, title, "monolingual"),
    ]
    if lang_qid:
        specs.append((wd.PID_LANGUAGE_OF_WORK_OR_NAME, lang_qid, "item"))
    for a in authors:
        specs.append((wd.PID_AUTHOR, a, "item"))
    specs.append((wd.PID_PUBLISHER, wd.QID_PROJECT_GUTENBERG, "item"))
    specs.append((wd.PID_DISTRIBUTION_FORMAT, QID_EBOOK, "item"))  # a Gutenberg etext is an ebook
    if issued:
        specs.append((wd.PID_PUBLICATION_DATE, issued, "time"))
    specs.append((wd.PID_COPYRIGHT_STATUS, QID_PUBLIC_DOMAIN, "item"))

    # en description "<year> Gutenberg version" (per the Q106304446 example + user's edit)
    year = issued.year if issued else None
    descriptions = {"en": f"{year} Gutenberg version" if year else "Project Gutenberg version"}

    p747_quals = []
    if lang_qid:
        p747_quals.append((wd.PID_LANGUAGE_OF_WORK_OR_NAME, lang_qid, "item"))
    if issued:
        p747_quals.append((wd.PID_PUBLICATION_DATE, issued, "time"))
    p747_quals.append((wd.PID_PUBLISHER, wd.QID_PROJECT_GUTENBERG, "item"))
    p747_quals.append((wd.PID_DISTRIBUTION_FORMAT, QID_EBOOK, "item"))
    return {"mul": title[0]}, descriptions, specs, p747_quals  # mul = language-agnostic title label


_VOLUME_RE = re.compile(r"\b(vol\.?|volume|tome|band|deel|tomo)\s*([ivxlcdm]+|\d+)\b"
                        r"|\bpart\s+(\d+|[ivxlcdm]+)\b", re.IGNORECASE)


def volume_marker(title: str) -> str | None:
    """Return the matched volume marker (e.g. 'vol. II') if a title looks like one volume of
    a multi-volume set, else None. Multi-volume needs manual per-volume (P478) modeling, so
    the tool must NOT auto-create a separate edition per volume (found via Q93673 'Memorie di
    Giuda, vol. I/II')."""
    m = _VOLUME_RE.search(title or "")
    return m.group(0) if m else None


_ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}


def volume_number(marker: str) -> str | None:
    """Extract the volume number as an arabic string from a marker ('vol. II' -> '2')."""
    m = re.search(r"([ivxlcdm]+|\d+)\s*$", (marker or "").strip(), re.IGNORECASE)
    if not m:
        return None
    tok = m.group(1)
    if tok.isdigit():
        return tok
    total = prev = 0
    for ch in reversed(tok.lower()):
        v = _ROMAN.get(ch, 0)
        total += -v if v < prev else v
        prev = max(prev, v)
    return str(total) if total else None


def _strip_volume(title: str, marker: str) -> str:
    """Drop the volume marker (+ a preceding separator) from a title: 'Melmoth …, Vol. 1'
    -> 'Melmoth …' -- so the multi-volume edition item carries the work-level title."""
    i = title.lower().rfind(marker.lower())
    if i == -1:
        return title
    return title[:i].rstrip(" ,:;-—–") or title


def _fmt_val(val, kind) -> str:
    if kind == "somevalue":
        return "(unknown value)"
    if kind == "monolingual":
        return f'"{val[0]}"@{val[1]}'
    if kind == "time":
        return val.toTimestr() if hasattr(val, "toTimestr") else str(val)
    return str(val)


def preview_edition(labels, descriptions, specs, p747_quals) -> None:
    print("    would create edition:")
    for lang, val in labels.items():
        print(f"       label/{lang} = {val}")
    for lang, val in descriptions.items():
        print(f"       desc/{lang}  = {val}")
    for spec in specs:
        pid, val, kind = spec[0], spec[1], spec[2]
        line = f"       {pid} = {_fmt_val(val, kind)}"
        quals = spec[3] if len(spec) > 3 else ()
        if quals:
            line += "  {" + ", ".join(f"{qp}={_fmt_val(qv, qk)}" for qp, qv, qk in quals) + "}"
        print(line)
    quals = ", ".join(f"{p}={_fmt_val(v, k)}" for p, v, k in p747_quals)
    print(f"    work P747 -> new edition, qualifiers: {quals or '(none)'}")


def deprecate_id(work_page, pid, claim, value, descs, intended_qid=None) -> None:
    """Deprecate an identifier on the work (rank=deprecated + P2241 = Q51845721, never
    delete). If ``intended_qid`` is given, also record P8327 (intended subject of
    deprecated statement) = the item the id really belongs to (the new/target edition)."""
    work_page.deprecate_claim(pid, claim, csp.QID_DIFFERENT_VERSION, intended_subject_qid=intended_qid)
    extra = f", P8327 -> {intended_qid}" if intended_qid else ""
    descs.append(f"deprecate {pid} = {value} (P2241 = {csp.QID_DIFFERENT_VERSION}{extra})")


def move_id_to_edition(work_page, pid, claim, value, ed_qid, edit_pages, descs, dry_run, eg) -> None:
    c = pywikibot.Claim(repo, pid)
    c.setTarget(value)
    csp.page_for(edit_pages, ed_qid, dry_run, eg).add_claim(pid, c)
    deprecate_id(work_page, pid, claim, value, descs, intended_qid=ed_qid)  # P8327 -> edition
    descs.append(f"-> add {pid} = {value} to edition {ed_qid}")


def _queue_gutenberg_create(work_page, work_qid, pid, value, claim, pending_creates, descs,
                            volume=None) -> None:
    """Build + queue a Gutenberg edition (deferred past the confirm), reusing an existing one
    if the id is already on some edition. ``volume`` qualifies P2034 with P478 for one volume
    of a multi-volume set."""
    built = build_gutenberg_specs(work_page, work_qid, value, volume=volume)
    if not built:
        print("  ! work has no title/label; cannot build an edition -- keeping.")
        return
    labels, descriptions, specs, p747_quals = built
    preview_edition(labels, descriptions, specs, p747_quals)
    existing = existing_gutenberg_edition(value, work_qid)
    if existing:
        print(f"    -> edition for Gutenberg {value} already exists: {existing} (will REUSE, not create)")
    pending_creates.append((value, labels, descriptions, specs, p747_quals, pid, claim, existing))
    verb = f"REUSE {existing}" if existing else "create"
    vtxt = f" (volume {volume}; add the other volumes' ids to it by hand)" if volume else ""
    descs.append(f"+ {verb} Gutenberg edition{vtxt} for {value} (P629 -> {work_qid}) + P747 link; "
                 f"then deprecate {pid} on work (P8327 -> the edition)")


# ---- Internet Archive -> Open Library "break out edition" template --------------------

def openlibrary_edition_for_ia(ia_id: str):
    """(ol_edition_dict, olid) for an Internet Archive scan id, resolved via the IA item's
    ``openlibrary_edition`` field -> the Open Library *edition* (…M) record. (None, None) if
    the scan isn't on IA or has no linked OL edition. We want the specific edition, not the OL
    work (…W): it carries THIS manifestation's date/publisher/place/language.

    Two hops, both through _http (polite backoff): archive.org metadata, then the OL edition."""
    r = _http("GET", f"https://archive.org/metadata/{ia_id}", timeout=30)
    if r is None:
        return None, None
    try:
        meta = r.json().get("metadata", {}) or {}
    except ValueError:
        return None, None
    olid = meta.get("openlibrary_edition")
    if isinstance(olid, list):
        olid = olid[0] if olid else None
    if not olid:
        print(f"    ! IA {ia_id} has no linked Open Library edition -- cannot auto-fill; keep/deprecate instead.")
        return None, None
    r2 = _http("GET", f"https://openlibrary.org/books/{olid}.json", timeout=30)
    if r2 is None:
        return None, None
    try:
        return r2.json(), olid
    except ValueError:
        return None, None


def _ol_year(s: str) -> str | None:
    m = re.search(r"\d{4}", s or "")
    return m.group(0) if m else None


def parse_ol_date(s: str):
    """Open Library publish_date -> WbTime. Exact 'YYYY-MM-DD'/'YYYY-MM'/'YYYY' first, then
    fall back to any 4-digit year in a messy value ('[1867?]', 'c1867', 'January 1867')."""
    d = _parse_date((s or "").strip())
    if d:
        return d
    y = _ol_year(s)
    return pywikibot.WbTime(year=int(y)) if y else None


def _ol_language_qid(ol: dict) -> str | None:
    """First OL language ('…/languages/fre') -> language-item QID (via 639-2/639-3/639-1)."""
    for l in ol.get("languages") or []:
        code = str(l.get("key", "")).rsplit("/", 1)[-1]
        qid = language_qid(code)
        if qid:
            return qid
    return None


def build_openlibrary_specs(work_page, work_qid, ia_id, ol, publisher_qids, pub_name, place_qid):
    """(labels, descriptions, claim_specs, p747_quals) for a new edition broken out of an
    Internet Archive scan, auto-filled from its Open Library edition record ``ol``. None if
    there's no usable title. Pure -- the interactive publisher/place choices are passed in
    (gathered by _queue_openlibrary_create). Mirrors build_gutenberg_specs' return shape so the
    same pending-create execution path links (P747) + deprecates the id (P8327).

    Fills what OL states reliably: title (+ subtitle P1680), language, publication date, and
    the scan id itself (P724). Authors are copied from the work (OL author->QID is unreliable);
    publisher (P123) / place (P291) come from the caller's prompt (OL gives names, not items).
    Number of pages is left out (P1104 is a quantity, unsupported by create_item) -- surfaced
    as a hint for manual add. P6216 = public domain (the tool's whole scope)."""
    authors = [c.getTarget().getID() for c in live(work_page.claims.get(wd.PID_AUTHOR, []))
               if c.getTarget()]
    lang_qid = _ol_language_qid(ol) or first_item(work_page, wd.PID_LANGUAGE_OF_WORK_OR_NAME)
    title_code = language_code(lang_qid) if lang_qid else None
    title_text = _clean_title(ol.get("title") or "")
    if not title_text or not title_code:                 # fall back to the work's own title
        wt = work_title(work_page.item, work_page)
        if not wt:
            return None
        title_text = title_text or wt[0]
        title_code = title_code or wt[1]
    title = (title_text, title_code)
    date = parse_ol_date(ol.get("publish_date", ""))

    specs = [
        (wd.PID_INSTANCE_OF, EDITION_TYPE, "item"),
        (wd.PID_EDITION_OR_TRANSLATION_OF, work_qid, "item"),
        (wd.PID_TITLE, title, "monolingual"),
    ]
    subtitle = _clean_title(ol.get("subtitle") or "")
    if subtitle:
        specs.append((wd.PID_SUBTITLE, (subtitle, title_code), "monolingual"))
    if lang_qid:
        specs.append((wd.PID_LANGUAGE_OF_WORK_OR_NAME, lang_qid, "item"))
    for a in authors:
        specs.append((wd.PID_AUTHOR, a, "item"))
    for pub in publisher_qids:
        specs.append((wd.PID_PUBLISHER, pub, "item"))
    if pub_name and not publisher_qids:                  # no item -> somevalue + named-as
        specs.append((wd.PID_PUBLISHER, None, "somevalue",
                      [(wd.PID_OBJECT_NAMED_AS, pub_name, "string")]))
    if place_qid:
        specs.append((wd.PID_PLACE_OF_PUBLICATION, place_qid, "item"))
    if date:
        specs.append((wd.PID_PUBLICATION_DATE, date, "time"))
    specs.append((wd.PID_INTERNET_ARCHIVE_ID, str(ia_id), "string"))  # the scan lives here now
    specs.append((wd.PID_COPYRIGHT_STATUS, QID_PUBLIC_DOMAIN, "item"))

    year = date.year if date else None
    descriptions = {"en": f"{year} edition" if year else "edition"}

    p747_quals = []
    if lang_qid:
        p747_quals.append((wd.PID_LANGUAGE_OF_WORK_OR_NAME, lang_qid, "item"))
    if date:
        p747_quals.append((wd.PID_PUBLICATION_DATE, date, "time"))
    for pub in publisher_qids:
        p747_quals.append((wd.PID_PUBLISHER, pub, "item"))
    if place_qid:
        p747_quals.append((wd.PID_PLACE_OF_PUBLICATION, place_qid, "item"))
    return {"mul": title[0]}, descriptions, specs, p747_quals


def _gather_openlibrary_edition(parent_page, parent_qid, ia_id, exclude_qid):
    """Resolve an IA scan -> its OL edition, prompt for publisher/place (OL states names, not
    QIDs; pre-filled from ``parent_page``), and build + preview a new edition parented to
    ``parent_qid`` (P629). ``exclude_qid`` is the item that currently holds the id, so a
    self-match isn't mistaken for a pre-existing duplicate. Returns
    ``(labels, descriptions, specs, p747_quals, existing, olid)`` or None. Shared by the
    work-loop [b] path and the edition-level --break-out-ia mode."""
    ol, olid = openlibrary_edition_for_ia(str(ia_id).strip())
    if not ol:
        print(f"  ! no Open Library edition for IA {ia_id} -- cannot break out (deprecate/move by hand).")
        return None
    pubs = ", ".join(ol.get("publishers") or []) or "-"
    places = ", ".join(ol.get("publish_places") or []) or "-"
    pages = ol.get("number_of_pages")
    print(f"    OL edition {olid}: \"{ol.get('title', '')}\" -- {ol.get('publish_date', '?')}, "
          f"publisher: {pubs}, place: {places}" + (f", {pages}p" if pages else ""))
    if pages:
        print(f"    (P1104 number of pages = {pages} not auto-added -- add by hand if wanted)")
    parent_pubs = list(dict.fromkeys(
        c.getTarget().getID() for c in live(parent_page.claims.get(wd.PID_PUBLISHER, []))
        if c.getTarget() and hasattr(c.getTarget(), "getID")))
    parent_place = first_item(parent_page, wd.PID_PLACE_OF_PUBLICATION)
    pub_in = csp.ask(f"    publisher QID(s) Q… (comma-sep), a name, or blank [OL: {pubs}]",
                     ",".join(parent_pubs)).strip()
    publisher_qids = _qid_list(pub_in)
    pub_name = next((t.strip() for t in pub_in.split(",")
                     if t.strip() and t.strip() not in publisher_qids), None)
    place_in = csp.ask(f"    place of publication QID Q… or blank [OL: {places}]",
                       parent_place or "").strip()
    place_qid = place_in if (place_in.startswith("Q") and place_in[1:].isdigit()) else None

    built = build_openlibrary_specs(parent_page, parent_qid, ia_id, ol, publisher_qids, pub_name, place_qid)
    if not built:
        print("  ! neither OL nor the parent work has a usable title; cannot build an edition.")
        return None
    labels, descriptions, specs, p747_quals = built
    if pub_name:
        print(f"    publisher \"{pub_name}\" has no item -> P123 = somevalue + object named as (P1932)")
    preview_edition(labels, descriptions, specs, p747_quals)
    existing = existing_edition_with_id(wd.PID_INTERNET_ARCHIVE_ID, ia_id, exclude_qid)
    if existing:
        print(f"    -> edition with IA {ia_id} already exists: {existing} (will REUSE, not create)")
    return labels, descriptions, specs, p747_quals, existing, olid


def _queue_openlibrary_create(work_page, work_qid, pid, value, claim, pending_creates, descs) -> None:
    """[b]reak out an edition from an Internet Archive scan id (P724) sitting on a WORK,
    auto-filled from its linked Open Library edition. Queues the create with the same tuple
    shape as the Gutenberg path, so process_item's execution loop links + deprecates it."""
    got = _gather_openlibrary_edition(work_page, work_qid, value, work_qid)
    if not got:
        return
    labels, descriptions, specs, p747_quals, existing, olid = got
    pending_creates.append((value, labels, descriptions, specs, p747_quals, pid, claim, existing))
    verb = f"REUSE {existing}" if existing else "create"
    descs.append(f"+ {verb} edition from Open Library {olid} for IA {value} (P629 -> {work_qid}) "
                 f"+ P747 link; then deprecate {pid} on work (P8327 -> the edition)")


def gutenberg_original_publication(gid: str):
    """(place, publisher, date) from the Gutenberg per-book RDF's MARC 260 imprint -- the
    'Original Publication' shown on the ebook page (the PRINT edition the etext was made from).
    (None, None, None) if absent. Uses the sanctioned per-book RDF (/cache/epub/<n>/pg<n>.rdf),
    not HTML scraping; this field is NOT in the bulk catalog CSV. MARC 260 is
    '<place> : $b <publisher>, $c <date>'."""
    r = _http("GET", f"https://www.gutenberg.org/cache/epub/{gid}/pg{gid}.rdf", timeout=30)
    if r is None:
        return None, None, None
    m = re.search(r"<pgterms:marc260>(.*?)</pgterms:marc260>", r.text, re.S)
    if not m:
        return None, None, None
    raw = html.unescape(m.group(1)).strip()
    place = (raw.split("$b", 1)[0].split("$c", 1)[0]).strip().rstrip(" :") or None
    pub = (mb.group(1).strip().rstrip(" ,") or None) if (mb := re.search(r"\$b(.*?)(?:\$c|$)", raw, re.S)) else None
    dt = (mc.group(1).strip().rstrip(" .") or None) if (mc := re.search(r"\$c(.*)$", raw, re.S)) else None
    return place, pub, dt


def _gather_gutenberg_edition(work_page, work_qid, gid, exclude_qid):
    """Build + preview a Gutenberg *ebook* edition (build_gutenberg_specs) for the edition-level
    break-out, plus offer a P144 (based on) link to the PRINT edition it was digitized from
    (from the RDF 'Original Publication'). Returns the common gather tuple, or None. The P144
    target is prompted blank -- it is the etext's print source, which is usually a DIFFERENT
    edition than the one you're breaking the id out of, so it is never auto-filled."""
    built = build_gutenberg_specs(work_page, work_qid, gid)
    if not built:
        print(f"  ! cannot build a Gutenberg edition for {gid} (no title) -- skipping.")
        return None
    labels, descriptions, specs, p747_quals = built
    place, pub, dt = gutenberg_original_publication(gid)
    if place or pub or dt:
        imprint = ", ".join(x for x in (pub, place, dt) if x)
        print(f"    Gutenberg 'Original Publication' (marc260): {imprint}")
        print("    -> the etext is a digitization of THAT print edition (may differ from this one).")
        ans = csp.ask("       P144 (based on) that source-edition QID Q… , or blank to skip").strip().upper()
        if ans.startswith("Q") and ans[1:].isdigit():
            specs.append((wd.PID_BASED_ON, ans, "item"))
            print(f"       + P144 (based on) -> {ans}")
    preview_edition(labels, descriptions, specs, p747_quals)
    existing = existing_edition_with_id(wd.PID_PROJECT_GUTENBERG_EBOOK_ID, gid, exclude_qid)
    if existing:
        print(f"    -> edition with Gutenberg {gid} already exists: {existing} (will REUSE, not create)")
    return labels, descriptions, specs, p747_quals, existing, "the Project Gutenberg catalog"


def _gather_ia_edition(work_page, work_qid, value, exclude_qid):
    """Adapter: _gather_openlibrary_edition with a source-description string for the break-out."""
    got = _gather_openlibrary_edition(work_page, work_qid, value, exclude_qid)
    if not got:
        return None
    labels, descriptions, specs, p747_quals, existing, olid = got
    return labels, descriptions, specs, p747_quals, existing, f"Open Library {olid}"


def _google_books_key() -> str | None:
    """Optional Books API key from .env (GOOGLE_BOOKS_API_KEY). Lifts the shared anonymous quota
    to the project's (~1,000/day). The key's Google Cloud project must have the Books API enabled
    and the key must not be API-restricted away from it; absent/empty -> keyless."""
    try:
        return get_env("GOOGLE_BOOKS_API_KEY", required=False) or None
    except Exception:
        return None


def google_books_volume(vol_id: str) -> dict | None:
    """volumeInfo dict for a Google Books volume id (best-effort; None on quota/miss). Google
    Books metadata is unreliable and daily-quota-limited, so it is only ever a HINT the user
    confirms/overrides -- never trusted as authoritative. Uses GOOGLE_BOOKS_API_KEY if set."""
    key = _google_books_key()
    params = {"country": "US"}
    if key:
        params["key"] = key
    r = _http("GET", f"https://www.googleapis.com/books/v1/volumes/{vol_id}", timeout=30,
              retry_429=False, params=params)  # a Google 429 is a daily quota; don't back off
    if r is None or r.status_code in (429, 403):
        tip = "" if key else " (set GOOGLE_BOOKS_API_KEY in .env to lift the quota)"
        print(f"    (Google Books API rate/quota-limited -- enter the facts by hand{tip})")
        return None
    try:
        j = r.json()
    except ValueError:
        return None
    if "error" in j:
        print(f"    (Google Books API unavailable: {j['error'].get('message', 'error')} "
              "-- enter the facts by hand)")
        return None
    return j.get("volumeInfo", {})


_MODS_NS = {"m": "http://www.loc.gov/mods/v3"}


def lccn_metadata(lccn: str) -> dict | None:
    """Bibliographic facts for a Library of Congress Control Number, from the LC permalink's
    MODS record (lccn.loc.gov/<lccn>/mods). Returns {lccn, title, subtitle, date, publisher,
    place, language} (any may be None) or None if unavailable. Unlike the Gutenberg/IA sources,
    an LCCN can describe a modern, in-copyright edition -- the caller must NOT assume PD."""
    norm = re.sub(r"\s+", "", str(lccn).strip())
    r = _http("GET", f"https://lccn.loc.gov/{norm}/mods", timeout=30)
    if r is None:
        return None
    try:
        root = ET.fromstring(r.content)
    except ET.ParseError:
        print(f"    ! could not parse the LC MODS record for LCCN {norm}")
        return None
    title = subtitle = None
    for ti in root.findall("m:titleInfo", _MODS_NS):     # main title = first titleInfo w/o a type
        if ti.get("type"):
            continue
        nonsort = (ti.findtext("m:nonSort", default="", namespaces=_MODS_NS) or "")
        main = (ti.findtext("m:title", default="", namespaces=_MODS_NS) or "")
        title = _clean_title(nonsort + main) or None
        subtitle = _clean_title(ti.findtext("m:subTitle", default="", namespaces=_MODS_NS) or "") or None
        if title:
            break
    date = publisher = place = None
    origin = root.find("m:originInfo", _MODS_NS)
    if origin is not None:
        dates = origin.findall("m:dateIssued", _MODS_NS)
        date = (next((d.text for d in dates if d.get("keyDate") == "yes" and d.text), None)
                or next((d.text for d in dates if d.text), None))
        publisher = (origin.findtext("m:publisher", default="", namespaces=_MODS_NS) or "").strip() or None
        if not publisher:                            # RDA-style records use <agent><namePart>
            publisher = (origin.findtext("m:agent/m:namePart", default="", namespaces=_MODS_NS) or "").strip() or None
        for pl in origin.findall("m:place/m:placeTerm", _MODS_NS):
            if pl.get("type") == "text" and pl.text:     # skip MARC country codes (type="code")
                place = pl.text.strip().split(";")[0].strip().rstrip(" :") or None
                break
    language = None
    for lt in root.findall("m:language/m:languageTerm", _MODS_NS):
        if lt.get("type") == "code" and lt.text:         # ISO 639-2, e.g. 'eng'
            language = lt.text.strip()
            break
    return {"lccn": norm, "title": title, "subtitle": subtitle, "date": date,
            "publisher": publisher, "place": place, "language": language}


def _gather_google_edition(work_page, work_qid, vol_id, exclude_qid):
    """Break out a Google Books volume (P675) into an edition of the work. Google's metadata is
    unreliable + quota-limited, so it is shown only as a hint and the facts are entered/confirmed
    interactively (seeded from the work); the new edition carries P675 = the volume id. Returns
    the common break-out tuple, or None."""
    vi = google_books_volume(str(vol_id).strip()) or {}
    if vi:
        print(f"    Google Books hint: \"{vi.get('title', '')}\" -- {vi.get('publishedDate', '?')}, "
              f"publisher: {vi.get('publisher', '-')}, language: {vi.get('language', '-')}")
    facts = _prompt_edition_facts(work_page, work_qid, seed_title=vi.get("title"),
                                  seed_date=vi.get("publishedDate"), seed_pub_name=vi.get("publisher"),
                                  src_hint="Google")
    if not facts:
        return None
    title, lang_qid, authors, date, publisher_qids, pub_name, place_qid = facts
    labels, descriptions, specs, p747_quals = _assemble_edition(
        title, work_qid, publisher_qids, lang_qid, authors, date, place_qid, pub_name=pub_name)
    specs.append((wd.PID_GOOGLE_BOOKS_ID, str(vol_id), "string"))   # the volume lives here now
    if pub_name:
        print(f"    publisher \"{pub_name}\" has no item -> P123 = somevalue + object named as (P1932)")
    preview_edition(labels, descriptions, specs, p747_quals)
    existing = existing_edition_with_id(wd.PID_GOOGLE_BOOKS_ID, vol_id, exclude_qid)
    if existing:
        print(f"    -> edition with Google Books {vol_id} already exists: {existing} (will REUSE, not create)")
    return labels, descriptions, specs, p747_quals, existing, "Google Books"


# pid -> gather function for the edition-level break-out (--break-out). Each returns the common
# tuple (labels, descriptions, specs, p747_quals, existing, srcdesc) or None.
BREAKOUT_GATHER = {
    wd.PID_PROJECT_GUTENBERG_EBOOK_ID: _gather_gutenberg_edition,
    wd.PID_INTERNET_ARCHIVE_ID: _gather_ia_edition,
    wd.PID_GOOGLE_BOOKS_ID: _gather_google_edition,
}


def _p747_targets(page) -> set:
    return {t.getID() for c in live(page.claims.get(wd.PID_HAS_EDITION_OR_TRANSLATION, []))
            if (t := c.getTarget()) and hasattr(t, "getID")}


def _link_edition(parent_page, new_qid, p747_quals) -> None:
    """Add ``parent P747 -> new_qid`` (with the summary qualifiers), unless already linked."""
    if new_qid in _p747_targets(parent_page):
        print(f"  {new_qid} is already a P747 edition of {parent_page.item.getID()} -- not re-linking")
        return
    link = pywikibot.Claim(repo, wd.PID_HAS_EDITION_OR_TRANSLATION)
    link.setTarget(pywikibot.ItemPage(repo, new_qid))
    for qpid, qval, qkind in p747_quals:
        q = pywikibot.Claim(repo, qpid, is_qualifier=True)
        q.setTarget(pywikibot.ItemPage(repo, qval) if qkind == "item" else qval)
        link.qualifiers.setdefault(qpid, []).append(q)
    parent_page.add_claim(wd.PID_HAS_EDITION_OR_TRANSLATION, link)


def break_out_from_edition(edition_qid, edit_group, dry_run, pids) -> bool:
    """Edition-level break-out (--break-out / --break-out-ia): point at an EDITION item that
    carries scan/edition identifiers actually belonging to *different* editions -- e.g. the
    Osgood edition Q51491134 whose Gutenberg/IA/Google ids are each a different printing.

    For each identifier of a property in ``pids`` (Gutenberg P2034 -> ebook edition; Internet
    Archive P724 -> Open Library edition), live OR already-deprecated, it creates a NEW edition
    parented to the edition's WORK (its P629 target), links it from the WORK (P747), and, if the
    id is still live, deprecates it on the source edition (P8327 -> the new edition). An
    already-deprecated id is left as-is (never re-touched) with a note to add P8327 by hand.
    Returns True if anything was applied."""
    item = pywikibot.ItemPage(repo, edition_qid)
    edition_page = cwd.WikiDataPage(item, test=dry_run)
    edition_page.edit_group = edit_group

    work_qid = first_item(edition_page, wd.PID_EDITION_OR_TRANSLATION_OF)
    if not work_qid:
        print(f"  {edition_qid}: no P629 (edition or translation of) -- can't tell which work to "
              "parent the new edition to.")
        ans = csp.ask("    work QID Q… to parent to (blank = abort)").strip().upper()
        if not (ans.startswith("Q") and ans[1:].isdigit()):
            print("    (aborted)")
            return False
        work_qid = ans

    todo = [(pid, c) for pid in pids for c in edition_page.claims.get(pid, [])]  # all ranks
    if not todo:
        labels_wanted = ", ".join(EDITION_ONLY_IDS.get(p, p) for p in pids)
        print(f"  {edition_qid}: no {labels_wanted} to break out.")
        return False

    lab = item.labels.get("en", "(no label)")
    print(f"\n=== {edition_qid}  \"{lab}\"  (edition of {work_qid})")
    for pid_link, lname in (("P1957", "Wikisource index page"), ("P996", "Commons file")):
        vals = [c.getTarget() for c in live(edition_page.claims.get(pid_link, [])) if c.getTarget()]
        if vals:
            print(f"  note: {pid_link} ({lname}) present -- it describes THIS edition; leave it here "
                  f"unless it's a broken-out id's: {', '.join(str(v) for v in vals)}")

    work_item = pywikibot.ItemPage(repo, work_qid)
    work_page = cwd.WikiDataPage(work_item, test=dry_run)
    work_page.edit_group = edit_group

    descs: list[str] = []
    pending: list = []   # (pid, value, labels, descriptions, specs, p747_quals, existing, claim, was_live)
    for pid, claim in todo:
        value = claim.getTarget()
        plabel = EDITION_ONLY_IDS.get(pid, pid)
        is_live = claim.getRank() != "deprecated"
        tag = "" if is_live else " [already deprecated]"
        if not csp.confirm(f"  break out {plabel} {value}{tag} into its own edition?", True):
            continue
        got = BREAKOUT_GATHER[pid](work_page, work_qid, value, edition_qid)
        if not got:
            continue
        labels, descriptions, specs, p747_quals, existing, srcdesc = got
        pending.append((pid, value, labels, descriptions, specs, p747_quals, existing, claim, is_live))
        verb = f"REUSE {existing}" if existing else "create"
        dep = (f"deprecate {pid} on {edition_qid} (P8327 -> the edition)" if is_live
               else f"{pid} on {edition_qid} already deprecated -- add P8327 -> the edition by hand")
        descs.append(f"+ {verb} edition from {srcdesc} for {plabel} {value} (P629 -> {work_qid}); "
                     f"link P747 on {work_qid}; {dep}")

    if not pending:
        print("  (nothing selected)")
        return False
    print("\n  planned edits:")
    for d in descs:
        print(f"    {d}")
    if not csp.confirm("apply?", default=True):
        print("  skipped.")
        return False

    for pid, value, labels, descriptions, specs, p747_quals, existing, claim, is_live in pending:
        plabel = EDITION_ONLY_IDS.get(pid, pid)
        try:
            if existing:
                new_qid = existing
                print(f"  reusing existing edition {new_qid} for {plabel} {value}")
            else:
                new_qid = cwd.create_item(labels=labels, descriptions=descriptions, claim_specs=specs,
                                          edit_group=edit_group, test=dry_run,
                                          summary=f"break out edition of {work_qid} from {edition_qid} "
                                                  f"({pid} = {value})")
                if new_qid:
                    print(f"  created edition {new_qid} for {plabel} {value}")
        except Exception as e:
            pywikibot.error(f"edition create failed for {plabel} {value}: {e}")
            print(f"  ! SKIPPED {plabel} {value} -- create failed; id left on {edition_qid}")
            continue
        if new_qid:
            _link_edition(work_page, new_qid, p747_quals)          # P747 on the WORK
        if is_live:                                                # deprecate the id on the EDITION
            deprecate_id(edition_page, pid, claim, value, [], intended_qid=new_qid)
        elif new_qid:
            print(f"  {plabel} {value} already deprecated on {edition_qid} -- "
                  f"add P8327 -> {new_qid} by hand if missing (not re-touched)")
    edition_page.apply()
    work_page.apply()
    return True


def handle_identifier(work_page, work_qid, pid, claim, editions, edit_pages, descs,
                      pending_creates, dry_run, eg) -> None:
    value = claim.getTarget()
    plabel = EDITION_ONLY_IDS.get(pid, pid)
    has_template = pid in CREATE_TEMPLATES
    is_gutenberg = pid == wd.PID_PROJECT_GUTENBERG_EBOOK_ID
    is_ia = pid == wd.PID_INTERNET_ARCHIVE_ID
    default = "c" if is_gutenberg else ("b" if is_ia else "d")
    vol = None
    # Guards that disable plain auto-create (Gutenberg only):
    #  * non-Text Gutenberg id (Type=Sound=audiobook, Dataset, Image ...) -- the ebook
    #    template (P437=ebook) is wrong for it -> manual, default keep;
    #  * a volume title (one of a set) -- offer [v] to create ONE edition for this volume
    #    (P478-qualified) that the rest are added to by hand; default keep.
    if is_gutenberg:
        entry = pg_catalog().get(str(value).strip())
        if entry and entry["type"] != "Text":
            print(f"  ⚠ Gutenberg {value} is Type={entry['type']} (not a text -- e.g. Sound=audiobook); "
                  "the ebook template doesn't fit -- model manually; not offering auto-create.")
            has_template, default = False, "k"
        elif entry and volume_marker(entry["title"]):
            vol = volume_marker(entry["title"])
            print(f"  ⚠ Gutenberg {value} = \"{entry['title']}\" is a VOLUME ({vol}); "
                  "[v] creates ONE edition for this volume (P478-qualified) -- add the other volumes to it manually.")
            has_template, default = False, "k"
    # OCLC number: look up its ISBN (via Open Library) and, if a linked edition already has
    # that ISBN, default to moving the OCLC straight onto that edition (matched by ISBN).
    if pid == wd.PID_OCLC_CONTROL_NUMBER:
        isbns = oclc_isbns(str(value))
        match = edition_with_isbn(editions, isbns) if isbns else None
        if match:
            print(f"    OCLC {value} -> ISBN {', '.join(sorted(isbns))}, already on edition {match} "
                  "-> move it there (default).")
            default = f"m{match}"
    opts = ("[c]reate version item / " if (is_gutenberg and has_template) else "") + \
           ("[v]create edition for THIS volume / " if vol else "") + \
           ("[b]reak out edition (from Open Library) / " if is_ia else "") + \
           "[m]<Qid> move to edition / [d]eprecate on work / [k]eep"
    ans = csp.ask(f"{pid} ({plabel}) = {value}  ->  {opts}", default).strip()
    low = ans.lower()
    if low == "c" and is_gutenberg and has_template:
        _queue_gutenberg_create(work_page, work_qid, pid, value, claim, pending_creates, descs)
    elif low == "b" and is_ia:
        _queue_openlibrary_create(work_page, work_qid, pid, value, claim, pending_creates, descs)
    elif low == "v" and vol:
        _queue_gutenberg_create(work_page, work_qid, pid, value, claim, pending_creates, descs,
                                volume=volume_number(vol))
    elif low.startswith("m") or (low.startswith("q") and low[1:].isdigit()):
        qid = ans[1:] if low.startswith("m") else ans
        qid = qid.strip().upper()
        if not qid.startswith("Q"):
            print("  (no edition QID given; keeping)")
            return
        move_id_to_edition(work_page, pid, claim, value, qid, edit_pages, descs, dry_run, eg)
    elif low == "d":
        deprecate_id(work_page, pid, claim, value, descs)  # no known intended subject
    else:
        print("  (keep)")


def first_version_editions(editions) -> list:
    """Editions explicitly marked as the first edition -- P393 (edition number) == "1" or
    P31 = first edition (Q10898227). A stronger, deliberate signal than earliest-by-date."""
    out = []
    for e in editions:
        nums = {c.getTarget() for c in live(e.claims.get(wd.PID_EDITION_NUMBER, []))}
        types = {c.getTarget().getID() for c in live(e.claims.get("P31", [])) if c.getTarget()}
        if "1" in nums or QID_FIRST_EDITION in types:
            out.append(e)
    return out


def ol_redirect_target(ol_id: str) -> str | None:
    """If an Open Library id is a *redirect* (the two OL records were merged), return the
    canonical id it points to; else None. Uses the OL API (`/works/<id>.json` returns a
    `/type/redirect` object with a `location`). Network/parse errors -> None (fall back to
    flagging, never a false 'redirect')."""
    r = _http("GET", f"https://openlibrary.org/works/{ol_id}.json", timeout=30, allow_redirects=False)
    if r is None:
        return None
    try:
        j = r.json()
        if j.get("type", {}).get("key") == "/type/redirect":
            return (j.get("location") or "").rsplit("/", 1)[-1] or None
    except ValueError:
        pass
    return None


def _isbn13(s: str) -> str | None:
    """Normalise an ISBN-10/13 (any hyphenation) to a compact ISBN-13 for comparison."""
    try:
        return stdnum_isbn.to_isbn13(stdnum_isbn.compact(s))
    except Exception:
        return None


def oclc_isbns(oclc: str) -> set:
    """ISBN-13s an OCLC number maps to, via Open Library (`bibkeys=OCLC:<n>`) -- the free
    route now that OCLC's xISBN is gone. Empty on a miss (OL lacks that record)."""
    r = _http("GET", "https://openlibrary.org/api/books",
              params={"bibkeys": f"OCLC:{oclc}", "format": "json", "jscmd": "data"}, timeout=30)
    if r is None:
        return set()
    out = set()
    try:
        for _, v in r.json().items():
            ids = v.get("identifiers", {})
            for key in ("isbn_13", "isbn_10"):
                for isbn in ids.get(key, []):
                    n = _isbn13(isbn)
                    if n:
                        out.add(n)
    except (ValueError, AttributeError):
        pass
    return out


def edition_with_isbn(editions, isbns: set) -> str | None:
    """QID of a linked edition carrying one of ``isbns`` (compact ISBN-13), else None."""
    for e in editions:
        for pid in (wd.PID_ISBN_13, wd.PID_ISBN_10):
            for c in live(e.claims.get(pid, [])):
                v = c.getTarget()
                if isinstance(v, str) and _isbn13(v) in isbns:
                    return e.getID()
    return None


def ol_edition_work(ol_id: str) -> str | None:
    """The Open Library WORK id (OL…W) an edition id (OL…M) belongs to, via the OL API
    (`/books/<id>.json` -> works[0].key), e.g. OL7182315M -> OL660397W. None on error."""
    r = _http("GET", f"https://openlibrary.org/books/{ol_id}.json", timeout=30)
    if r is None:
        return None
    try:
        works = r.json().get("works", [])
        if works:
            return works[0].get("key", "").rsplit("/", 1)[-1] or None
    except (ValueError, AttributeError, IndexError):
        pass
    return None


def handle_openlibrary(work_page, work_qid, editions, edit_pages, descs,
                       pending_creates, dry_run, eg) -> None:
    """Open Library ids (P648) encode the FRBR level in the id suffix: ...W = work,
    ...M = edition (manifestation), ...A = author. So P648 can't be a blanket edition-only
    property -- handle per value:
      - ...M on a work -> edition-level -> deprecate/move like any misplaced id;
      - ...W that is an OL *redirect* (merged record) -> deprecate (P2241 = Q45403344);
      - remaining live ...W -> keep; but >=2 means the work maps to several OL *work*
        records (a different work such as an adaptation) -> flag for a human;
      - ...A / other -> leave (not an edition id)."""
    all_values = {c.getTarget() for c in live(work_page.claims.get(wd.PID_OPEN_LIBRARY_ID, []))
                  if isinstance(c.getTarget(), str)}
    live_w = []
    for c in list(live(work_page.claims.get(wd.PID_OPEN_LIBRARY_ID, []))):
        v = c.getTarget()
        if not isinstance(v, str):
            continue
        suffix = v[-1:].upper()
        if suffix == "M":
            print(f"  P648 = {v} (…M = edition manifestation) -> edition-level")
            # The …M records its OL work (…W); offer to add that work id to the WORK item.
            wk = ol_edition_work(v)
            if wk and wk not in all_values:
                if csp.confirm(f"    add the OL work id P648 = {wk} to the work (from edition {v})?", True):
                    wc = pywikibot.Claim(repo, wd.PID_OPEN_LIBRARY_ID)
                    wc.setTarget(wk)
                    work_page.add_claim(wd.PID_OPEN_LIBRARY_ID, wc)
                    descs.append(f"+ P648 = {wk} (OL work id, from edition {v})")
                    all_values.add(wk)   # a second …M mapping to the same work won't re-offer
            handle_identifier(work_page, work_qid, wd.PID_OPEN_LIBRARY_ID, c, editions,
                              edit_pages, descs, pending_creates, dry_run, eg)
        elif suffix == "W":
            target = ol_redirect_target(v)
            if target:  # a merged/redirected OL work record -> stale
                work_page.deprecate_claim(wd.PID_OPEN_LIBRARY_ID, c, QID_REDIRECT)
                descs.append(f"deprecate P648 = {v} (P2241 = {QID_REDIRECT}, redirect -> {target})")
                if target not in all_values:
                    print(f"    note: canonical OL id {target} not on the item -- consider adding it")
            else:
                live_w.append(v)
        else:
            print(f"  P648 = {v} (…{suffix}) -> not an edition id; leaving")
    if len(live_w) >= 2:
        print(f"  ⚠ {len(live_w)} live (non-redirect) Open Library WORK ids: {', '.join(live_w)}")
        print("    distinct OL *work* records (a different work — e.g. a comic/film "
              "adaptation). Review on Open Library; keep the canonical one, drop the other. "
              "NOT auto-changed.")


def _assemble_edition(title, work_qid, publisher_qids, lang_qid, authors, date, place_qid,
                      pub_name=None, first=False, public_domain=True):
    """Assemble (labels, descriptions, specs, p747_quals) for an edition item of a work from the
    given facts. ``first`` marks it as the first edition (P393="1" + P31=first edition, per
    user); otherwise it's a plain edition. A publisher with no item (``pub_name``) is recorded
    as P123 = somevalue + object named as (P1932). ``public_domain`` appends P6216 = public
    domain (default True for the PD-scoped Gutenberg/first-edition paths; the LCCN path passes
    False since an LCCN edition may be modern/in-copyright)."""
    specs = [
        (wd.PID_INSTANCE_OF, EDITION_TYPE, "item"),
        (wd.PID_EDITION_OR_TRANSLATION_OF, work_qid, "item"),
        (wd.PID_TITLE, title, "monolingual"),
    ]
    if first:
        specs.insert(1, (wd.PID_INSTANCE_OF, QID_FIRST_EDITION, "item"))
        specs.append((wd.PID_EDITION_NUMBER, "1", "string"))
    for pub in publisher_qids:
        specs.append((wd.PID_PUBLISHER, pub, "item"))
    if pub_name:                                           # no item -> somevalue + named-as
        specs.append((wd.PID_PUBLISHER, None, "somevalue",
                      [(wd.PID_OBJECT_NAMED_AS, pub_name, "string")]))
    if lang_qid:
        specs.append((wd.PID_LANGUAGE_OF_WORK_OR_NAME, lang_qid, "item"))
    for a in authors:
        specs.append((wd.PID_AUTHOR, a, "item"))
    if date:
        specs.append((wd.PID_PUBLICATION_DATE, date, "time"))
    if place_qid:
        specs.append((wd.PID_PLACE_OF_PUBLICATION, place_qid, "item"))
    if public_domain:
        specs.append((wd.PID_COPYRIGHT_STATUS, QID_PUBLIC_DOMAIN, "item"))

    year = date.year if date else None
    kind = "first edition" if first else "edition"
    descriptions = {"en": f"{year} {kind}" if year else kind}

    p747_quals = [(wd.PID_EDITION_NUMBER, "1", "string")] if first else []
    if lang_qid:
        p747_quals.append((wd.PID_LANGUAGE_OF_WORK_OR_NAME, lang_qid, "item"))
    if date:
        p747_quals.append((wd.PID_PUBLICATION_DATE, date, "time"))
    for pub in publisher_qids:
        p747_quals.append((wd.PID_PUBLISHER, pub, "item"))
    if place_qid:
        p747_quals.append((wd.PID_PLACE_OF_PUBLICATION, place_qid, "item"))
    return {"mul": title[0]}, descriptions, specs, p747_quals  # mul = language-agnostic title label


def _assemble_first_edition(title, work_qid, publisher_qids, lang_qid, authors, date, place_qid,
                            pub_name=None):
    """Thin wrapper: _assemble_edition marked as the first edition."""
    return _assemble_edition(title, work_qid, publisher_qids, lang_qid, authors, date, place_qid,
                             pub_name=pub_name, first=True)


def _prompt_edition_facts(work_page, work_qid, *, seed_title=None, seed_date=None,
                          seed_pub_name=None, seed_place_txt=None, seed_lang=None, src_hint="source"):
    """Interactively gather an edition's language/title/date/publisher/place, seeded from the
    work's own facts, with optional external-source seeds (Gutenberg imprint, Google volume,
    LCCN record) shown as hints/defaults. ``seed_lang`` (a QID or ISO code, e.g. 'eng') presets
    the language default -- important for a translation edition whose language differs from the
    work. Returns (title, lang_qid, authors, date, publisher_qids, pub_name, place_qid), or None
    if the work has no usable title."""
    work_item = work_page.item
    title = work_title(work_item, work_page)
    if not title:
        print(f"  {work_qid}: no usable title -- cannot seed an edition.")
        return None
    authors = [c.getTarget().getID() for c in live(work_page.claims.get(wd.PID_AUTHOR, [])) if c.getTarget()]
    lang_qid = first_item(work_page, wd.PID_LANGUAGE_OF_WORK_OR_NAME)
    work_pubs = list(dict.fromkeys(
        c.getTarget().getID() for c in live(work_page.claims.get(wd.PID_PUBLISHER, []))
        if c.getTarget() and hasattr(c.getTarget(), "getID")))
    work_place = first_item(work_page, wd.PID_PLACE_OF_PUBLICATION)
    work_date = next((c.getTarget() for c in live(work_page.claims.get(wd.PID_PUBLICATION_DATE, []))
                      if c.getTarget()), None)

    # Language first: a translation edition has a different language + title than the work, so
    # both must be overridable, not copied blindly. A source seed (e.g. LCCN 'eng') presets it.
    seed_code = None
    if seed_lang:
        sq = seed_lang if str(seed_lang).startswith("Q") else language_qid(seed_lang)
        seed_code = language_code(sq) if sq else None
    lang_default = seed_code or language_code(lang_qid) or ""
    lang_in = csp.ask("    language: ISO code (en, fr…) or QID Q…", lang_default).strip()
    if lang_in:
        if lang_in.startswith("Q") and lang_in[1:].isdigit():
            lang_qid = lang_in
        elif (resolved := language_qid(lang_in)):
            lang_qid = resolved
        else:
            print(f"    (unknown language '{lang_in}'; keeping {lang_qid})")
    title_code = language_code(lang_qid) or title[1]
    title_default = seed_title or title[0]
    title_in = csp.ask(f"    title [{title_code}]", title_default).strip()
    title = (_clean_title(title_in) if title_in else _clean_title(title_default), title_code)

    date_default = seed_date or (str(work_date.year) if work_date else "")
    yr = csp.ask("    publication date (YYYY / YYYY-MM / YYYY-MM-DD; blank = none)", date_default).strip()
    date = None
    if yr:
        if work_date and yr == str(work_date.year):
            date = work_date                                   # keep the work's fuller precision
        else:
            date = _parse_date(yr)
            if not date:
                print("    (unrecognised date; leaving it off)")

    pub_default = ",".join(work_pubs) or (seed_pub_name or "")
    pub_hint = f" [{src_hint}: {seed_pub_name}]" if seed_pub_name else ""
    pub_in = csp.ask(f"    publisher QID(s) Q… (comma-sep), a name, or blank{pub_hint}", pub_default).strip()
    publisher_qids = _qid_list(pub_in)
    pub_name = next((t.strip() for t in pub_in.split(",")
                     if t.strip() and t.strip() not in publisher_qids), None)

    place_hint = f" [{src_hint}: {seed_place_txt} -- needs a QID]" if seed_place_txt else ""
    place_in = csp.ask(f"    place of publication QID Q… or blank{place_hint}", work_place or "").strip()
    place_qid = place_in if (place_in.startswith("Q") and place_in[1:].isdigit()) else None
    return title, lang_qid, authors, date, publisher_qids, pub_name, place_qid


def create_edition_of_work(work_qid, edit_group, dry_run, seed_gutenberg=None,
                           seed_lccn=None) -> str | None:
    """Interactively create an edition item of a work (--create-edition), seeded from the work's
    own facts (authors/title/language) plus prompted publisher/place/date, and link it from the
    work (P747). Two optional external seeds:
      ``seed_gutenberg`` -- publisher/place/date from a Gutenberg id's 'Original Publication'
        (marc260); the created edition is PD (mints an ebook's P144 print source).
      ``seed_lccn`` -- title/date/publisher/place/language from the Library of Congress MODS
        record; the created edition carries P1144 = the LCCN and is NOT auto-marked public
        domain (an LCCN edition may be a modern, in-copyright translation/reprint).
    Returns the new QID (None in dry run / on abort)."""
    work_item = pywikibot.ItemPage(repo, work_qid)
    work_page = cwd.WikiDataPage(work_item, test=dry_run)
    work_page.edit_group = edit_group

    seed_title = seed_pub_name = seed_place_txt = seed_date = seed_lang = None
    extra_specs = []                                 # extra identifier claims (e.g. P1144 = LCCN)
    public_domain = True
    src_hint = "source"
    if seed_gutenberg:
        seed_place_txt, seed_pub_name, seed_date = gutenberg_original_publication(str(seed_gutenberg).strip())
        src_hint = "Gutenberg"
        if seed_place_txt or seed_pub_name or seed_date:
            print(f"  seed from Gutenberg {seed_gutenberg} 'Original Publication': "
                  f"{', '.join(x for x in (seed_pub_name, seed_place_txt, seed_date) if x)}")
    elif seed_lccn:
        md = lccn_metadata(seed_lccn)
        if not md:
            print(f"  ! no Library of Congress record for LCCN {seed_lccn}; enter the facts by hand.")
            md = {"lccn": re.sub(r"\s+", "", str(seed_lccn).strip())}
        src_hint = "LCCN"
        seed_title = ": ".join(x for x in (md.get("title"), md.get("subtitle")) if x) or None
        seed_date, seed_pub_name = md.get("date"), md.get("publisher")
        seed_place_txt, seed_lang = md.get("place"), md.get("language")
        public_domain = False                        # LCCN edition may be modern/in-copyright
        extra_specs.append((wd.PID_LIBRARY_OF_CONGRESS_CONTROL_NUMBER_LCCN_BIBLIOGRAPHIC,
                            md["lccn"], "string"))
        print(f"  seed from LCCN {md['lccn']}: \"{seed_title or '?'}\" -- {seed_date or '?'}, "
              f"publisher: {seed_pub_name or '-'}, place: {seed_place_txt or '-'}, lang: {seed_lang or '-'}")

    print(f"\n=== create an edition of {work_qid}  \"{work_item.labels.get('en', work_qid)}\"")
    facts = _prompt_edition_facts(work_page, work_qid, seed_title=seed_title, seed_date=seed_date,
                                  seed_pub_name=seed_pub_name, seed_place_txt=seed_place_txt,
                                  seed_lang=seed_lang, src_hint=src_hint)
    if not facts:
        return None
    title, lang_qid, authors, date, publisher_qids, pub_name, place_qid = facts
    labels, descriptions, specs, p747_quals = _assemble_edition(
        title, work_qid, publisher_qids, lang_qid, authors, date, place_qid, pub_name=pub_name,
        public_domain=public_domain)
    specs += extra_specs                             # attach the LCCN (P1144) if seeded
    if pub_name:
        print(f"    publisher \"{pub_name}\" has no item -> P123 = somevalue + object named as (P1932)")
    if not public_domain:
        print("    note: P6216 (copyright status) NOT set -- an LCCN edition may be modern/"
              "copyrighted; add the right status (public domain / copyrighted) by hand.")
    print("  would create edition:")
    preview_edition(labels, descriptions, specs, p747_quals)
    if not csp.confirm("create this edition + link P747 on the work?", True):
        print("  skipped.")
        return None
    try:
        new_qid = cwd.create_item(labels=labels, descriptions=descriptions, claim_specs=specs,
                                  edit_group=edit_group, test=dry_run,
                                  summary=f"create edition of {work_qid}")
    except Exception as e:
        pywikibot.error(f"edition create failed: {e}")
        return None
    if new_qid:
        print(f"  created edition {new_qid}")
        _link_edition(work_page, new_qid, p747_quals)
        work_page.apply()
    else:
        print("  (dry run) would create the edition + link P747 on the work")
    return new_qid


def _qid_list(s: str) -> list[str]:
    return [t.strip() for t in s.split(",") if t.strip().startswith("Q") and t.strip()[1:].isdigit()]


def _parse_date(s: str):
    """Parse YYYY / YYYY-MM / YYYY-MM-DD into a WbTime at the right precision, else None."""
    s = s.strip()
    if re.fullmatch(r"\d{4}", s):
        return pywikibot.WbTime(year=int(s))
    m = re.fullmatch(r"(\d{4})-(\d{2})", s)
    if m:
        return pywikibot.WbTime(year=int(m.group(1)), month=int(m.group(2)))
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return pywikibot.WbTime(year=int(m.group(1)), month=int(m.group(2)), day=int(m.group(3)))
    return None


def _edition_publishers(edition) -> set:
    return {c.getTarget().getID() for c in live(edition.claims.get(wd.PID_PUBLISHER, []))
            if c.getTarget() and hasattr(c.getTarget(), "getID")}


def mark_edition_first(edition, work_page, pub_claims, edit_pages, descs, dry_run, eg) -> None:
    """Mark an EXISTING edition as the first edition (add P393="1" + P31=first edition) rather
    than creating a duplicate, and resolve the work's publisher against it (remove if the
    edition already has it, else deprecate)."""
    ed_qid = edition.getID()
    ep = csp.page_for(edit_pages, ed_qid, dry_run, eg)
    if "1" not in {c.getTarget() for c in live(edition.claims.get(wd.PID_EDITION_NUMBER, []))}:
        c = pywikibot.Claim(repo, wd.PID_EDITION_NUMBER)
        c.setTarget("1")
        ep.add_claim(wd.PID_EDITION_NUMBER, c)
    if QID_FIRST_EDITION not in {c.getTarget().getID() for c in live(edition.claims.get("P31", []))
                                 if c.getTarget()}:
        c = pywikibot.Claim(repo, wd.PID_INSTANCE_OF)
        c.setTarget(pywikibot.ItemPage(repo, QID_FIRST_EDITION))
        ep.add_claim(wd.PID_INSTANCE_OF, c)
    descs.append(f"mark existing edition {ed_qid} as FIRST (P393=1 + P31=first edition)")
    ed_pubs = _edition_publishers(edition)
    for c in pub_claims:                                   # resolve the work's publisher against it
        vstr = c.getTarget().getID()
        if vstr in ed_pubs:
            work_page.remove_property(wd.PID_PUBLISHER, c)
            descs.append(f"- work P123 = {vstr} (already on first edition {ed_qid})")
        else:
            csp._deprecate(work_page, wd.PID_PUBLISHER, c, vstr, descs)
            descs.append(f"  (first edition {ed_qid} has a different publisher)")


def handle_first_edition(work_page, work_qid, editions, edit_pages, descs, pending_first_ed,
                         dry_run, eg) -> bool:
    """Handle the work's first edition when none is marked. First checks whether an EXISTING
    edition already looks like the first (its P577 year == the work's first-pub year) and, if
    so, offers to MARK it (P393=1 + P31=first edition) instead of creating a duplicate. Else
    offers to CREATE one, prompting for year / publisher / place (from Wikipedia), pre-filled
    from the work's P577/P123/P291. Blank year = skip. Returns True if handled (caller then
    skips handle_publisher)."""
    if first_version_editions(editions):
        return False
    item = work_page.item
    title = work_title(item, work_page)
    if not title:
        return False
    lang_qid = first_item(work_page, wd.PID_LANGUAGE_OF_WORK_OR_NAME)
    authors = [c.getTarget().getID() for c in live(work_page.claims.get(wd.PID_AUTHOR, [])) if c.getTarget()]
    pub_claims = [c for c in live(work_page.claims.get(wd.PID_PUBLISHER, []))
                  if c.getTarget() and hasattr(c.getTarget(), "getID")]
    work_pubs = list(dict.fromkeys(c.getTarget().getID() for c in pub_claims))
    work_date = next((c.getTarget() for c in live(work_page.claims.get(wd.PID_PUBLICATION_DATE, []))
                      if c.getTarget()), None)
    place_claims = [c for c in live(work_page.claims.get(wd.PID_PLACE_OF_PUBLICATION, []))
                    if c.getTarget() and hasattr(c.getTarget(), "getID")]
    work_place = place_claims[0].getTarget().getID() if place_claims else None

    # Does an existing edition already look like the first? (its P577 year == the work's)
    work_year = work_date.year if work_date else None
    matches = [e for e in editions if work_year and work_year in
               {c.getTarget().year for c in live(e.claims.get(wd.PID_PUBLICATION_DATE, [])) if c.getTarget()}]
    if matches:
        for e in matches:
            pubs = ", ".join(csp.label(p) for p in _edition_publishers(e)) or "no publisher"
            print(f"  edition {e.getID()} (P577={work_year}, {pubs}) matches the work's first-publication "
                  "year -- may already BE the first edition.")
        if len(matches) == 1:
            tgt = matches[0]
        else:
            q = csp.ask("    which existing edition is the first? QID (blank = none)").strip().upper()
            tgt = next((e for e in matches if e.getID() == q), None)
        if tgt and csp.confirm(f"    mark {tgt.getID()} as the FIRST edition (not create a new one)?", True):
            mark_edition_first(tgt, work_page, pub_claims, edit_pages, descs, dry_run, eg)
            return True

    print(f"  no first edition item for \"{item.labels.get('en', title[0])}\" -- create one? "
          "(details from Wikipedia; blank = skip)")
    yr = csp.ask("    first-edition date (YYYY / YYYY-MM / YYYY-MM-DD)",
                 str(work_date.year) if work_date else "").strip()
    if not yr or yr.lower() in ("skip", "n", "no"):
        print("    (not creating a first edition)")
        return False
    if work_date and yr == str(work_date.year):
        date = work_date                                   # keep the work's fuller precision
    else:
        date = _parse_date(yr)
        if not date:
            print("    (unrecognised date; skipping)")
            return False

    # Title override -- the first edition's title can differ from the work's (a retitled or
    # serialised-then-booked first edition, e.g. Manon Lescaut's 1733 "Les Avantures du
    # chevalier Des Grieux…"). Default = the work's own-language title; keep its language.
    title_in = csp.ask(f"    title [{title[1]}]", title[0]).strip()
    if title_in and title_in != title[0]:
        title = (_clean_title(title_in), title[1])

    pub_in = csp.ask("    publisher QID(s) Q… (comma-sep), a name, or blank", ",".join(work_pubs)).strip()
    publisher_qids = _qid_list(pub_in)
    pub_name = next((t.strip() for t in pub_in.split(",")
                     if t.strip() and t.strip() not in publisher_qids), None)
    place_in = csp.ask("    place of publication QID Q… or blank", work_place or "").strip()
    place_qid = place_in if (place_in.startswith("Q") and place_in[1:].isdigit()) else None

    built = _assemble_first_edition(title, work_qid, publisher_qids, lang_qid, authors, date,
                                    place_qid, pub_name=pub_name)
    labels, descriptions, specs, p747_quals = built
    if pub_name:
        print(f"    publisher \"{pub_name}\" has no item -> P123 = somevalue + object named as (P1932)")
    print("  would create first edition:")
    preview_edition(labels, descriptions, specs, p747_quals)
    if not csp.confirm("create this first edition?", True):
        return False
    # Move off the work only the P123/P291 values that actually went onto the edition (so a
    # user-entered publisher that wasn't on the work doesn't cause an unrelated removal).
    remove_claims = [(wd.PID_PUBLISHER, c) for c in pub_claims if c.getTarget().getID() in publisher_qids]
    remove_claims += [(wd.PID_PLACE_OF_PUBLICATION, c) for c in place_claims
                      if c.getTarget().getID() == place_qid]
    pending_first_ed.append((labels, descriptions, specs, p747_quals, remove_claims))
    descs.append("+ create FIRST edition (P393=1 + P31=first edition); "
                 "move matching P123/P291 off the work (P577 kept on work too)")
    return True


def handle_publisher(work_page, editions, edit_pages, descs, dry_run, eg) -> None:
    """Publisher on the work trips the 'publisher on literary work' constraint. Resolve it
    only against an explicitly-marked FIRST edition (P393=1 / P31=first edition):
      (1) that first edition already has THIS publisher -> remove from work (redundant);
      (2) it has ANOTHER publisher -> deprecate on the work (P2241 = Q51845721, applies to
          a different version) -- kept, not deleted, for a human to relocate;
      (3) no marked first edition, or it carries no publisher -> skip (leave for manual).
    Deliberately does NOT auto-move (per the agreed rule) -- publisher placement on a
    non-first edition is a human call."""
    first_eds = first_version_editions(editions)
    first_pubs = {}  # publisher qid -> the first-edition qid holding it
    for e in first_eds:
        for c in live(e.claims.get(wd.PID_PUBLISHER, [])):
            t = c.getTarget()
            if t and hasattr(t, "getID"):
                first_pubs.setdefault(t.getID(), e.getID())

    for c in live(work_page.claims.get(wd.PID_PUBLISHER, [])):
        t = c.getTarget()
        if not t or not hasattr(t, "getID"):
            continue
        vstr = t.getID()
        vlabel = csp.label(vstr)
        if not first_eds:
            print(f"  P123 = {vstr} ({vlabel}): no edition marked as the first version -> skip")
            continue
        if not first_pubs:
            print(f"  P123 = {vstr} ({vlabel}): first edition has no publisher -> skip")
            continue
        if vstr in first_pubs:                                   # (1) redundant -> remove
            work_page.remove_property(wd.PID_PUBLISHER, c)
            descs.append(f"- work P123 = {vstr} ({vlabel}) — redundant, "
                         f"first edition {first_pubs[vstr]} already has it")
        else:                                                    # (2) conflict -> deprecate
            others = ", ".join(f"{p} on {q}" for p, q in first_pubs.items())
            csp._deprecate(work_page, wd.PID_PUBLISHER, c, vstr, descs)  # P2241 = Q51845721
            descs.append(f"  (first edition's publisher differs: {others})")


def process_item(qid, edit_group, dry_run, no_first_ed=False) -> bool:
    item = pywikibot.ItemPage(repo, qid)
    page = cwd.WikiDataPage(item, test=dry_run)
    page.edit_group = edit_group
    variant, editions = csp.classify_structure(page)
    if variant != "work":
        print(f"  {qid}: not a strict work (variant={variant}); skipping (use curate_selfpub).")
        return False

    show_state(qid, item, page, editions)
    descs: list[str] = []
    edit_pages: dict = {}
    pending_creates: list = []  # (value, labels, specs) -- executed only after confirm
    pending_first_ed: list = []  # (labels, descriptions, specs, p747_quals) for a first edition
    for pid in EDITION_ONLY_IDS:
        for c in list(live(page.claims.get(pid, []))):
            handle_identifier(page, qid, pid, c, editions, edit_pages, descs,
                              pending_creates, dry_run, edit_group)
    handle_openlibrary(page, qid, editions, edit_pages, descs, pending_creates, dry_run, edit_group)
    # Offer to mint a first-edition item from the work's own facts; if taken, the publisher
    # is moved onto it, so skip the deprecate-based publisher rule. --no-first-edition skips
    # the (research-heavy) first-edition prompt for a fast Gutenberg-only batch pass.
    if no_first_ed or not handle_first_edition(page, qid, editions, edit_pages, descs,
                                               pending_first_ed, dry_run, edit_group):
        handle_publisher(page, editions, edit_pages, descs, dry_run, edit_group)

    if not descs:
        print("  (nothing selected)")
        return False
    print("\n  planned edits:")
    for d in descs:
        print(f"    {d}")
    if not csp.confirm("apply?", default=True):
        print("  skipped.")
        return False

    # Create (or reuse) the edition item(s) FIRST (so we have a QID to link + record as
    # P8327), then apply the work's deferred actions (P747 links, deprecations) and touched
    # editions. Each create is isolated: if one fails (e.g. a bad title), the id is left
    # live on the work and the others still land -- no orphaned, unlinked items.
    already_linked = {e.getID() for e in editions}
    for value, labels, descriptions, specs, p747_quals, id_pid, id_claim, existing in pending_creates:
        idlabel = EDITION_ONLY_IDS.get(id_pid, id_pid)
        try:
            if existing:
                new_qid = existing
                print(f"  reusing existing edition {new_qid} for {idlabel} {value}")
            else:
                new_qid = cwd.create_item(labels=labels, descriptions=descriptions, claim_specs=specs,
                                          edit_group=edit_group, test=dry_run,
                                          summary=f"create edition of {qid} ({id_pid} = {value})")
                if new_qid:
                    print(f"  created edition {new_qid} for {idlabel} {value}")
        except Exception as e:
            pywikibot.error(f"edition create failed for {idlabel} {value}: {e}")
            print(f"  ! SKIPPED {idlabel} {value} -- create failed; id left live on the work")
            continue
        # Link the edition from the work -- but only if it isn't already a P747 edition (a
        # reused pre-existing edition, e.g. one that already carried the id, is linked; its
        # own facts, not the Gutenberg-ebook qualifiers, describe it).
        if new_qid and new_qid not in already_linked:
            link = pywikibot.Claim(repo, wd.PID_HAS_EDITION_OR_TRANSLATION)
            link.setTarget(pywikibot.ItemPage(repo, new_qid))
            for qpid, qval, qkind in p747_quals:  # summarise the edition inline on P747
                q = pywikibot.Claim(repo, qpid, is_qualifier=True)
                q.setTarget(pywikibot.ItemPage(repo, qval) if qkind == "item" else qval)
                link.qualifiers.setdefault(qpid, []).append(q)
            page.add_claim(wd.PID_HAS_EDITION_OR_TRANSLATION, link)
        elif new_qid in already_linked:
            print(f"  {new_qid} is already a P747 edition of the work -- not re-linking")
        # deprecate the id on the work, pointing P8327 at the edition (None in dry run w/o reuse)
        deprecate_id(page, id_pid, id_claim, value, [], intended_qid=new_qid)

    # Mint the first-edition item from the work's harvested facts, link it, and only THEN
    # move P123/P291 off the work (skip the moves if the create failed, so they aren't lost).
    first_ed_created = []
    for labels, descriptions, specs, p747_quals, remove_claims in pending_first_ed:
        try:
            new_qid = cwd.create_item(labels=labels, descriptions=descriptions, claim_specs=specs,
                                      edit_group=edit_group, test=dry_run,
                                      summary=f"create first edition of {qid}")
        except Exception as e:
            pywikibot.error(f"first-edition create failed: {e}")
            print("  ! SKIPPED first edition -- create failed; P123/P291 left on the work")
            continue
        if new_qid:
            print(f"  created first edition {new_qid}")
            link = pywikibot.Claim(repo, wd.PID_HAS_EDITION_OR_TRANSLATION)
            link.setTarget(pywikibot.ItemPage(repo, new_qid))
            for qpid, qval, qkind in p747_quals:
                q = pywikibot.Claim(repo, qpid, is_qualifier=True)
                q.setTarget(pywikibot.ItemPage(repo, qval) if qkind == "item" else qval)
                link.qualifiers.setdefault(qpid, []).append(q)
            page.add_claim(wd.PID_HAS_EDITION_OR_TRANSLATION, link)
            for pid, claim in remove_claims:      # move P123/P291 off the work (edition has them now)
                page.remove_property(pid, claim)
            first_ed_created.append(new_qid)
        else:
            print("  (dry run) would create the first edition, link P747 (moved to top), move P123/P291")
    page.apply()
    for p in edit_pages.values():
        p.apply()
    # A first edition should sort first in P747 -- reorder after the append-only edit lands.
    for fe in first_ed_created:
        try:
            if move_p747_first(qid, fe, edit_group):
                print(f"  moved first edition {fe} to the top of P747")
        except Exception as e:
            pywikibot.warning(f"could not reorder P747 for {fe}: {e}")
    return True


def load_done() -> set:
    if DONE_FILE.exists():
        return {l.split("\t", 1)[0].strip() for l in open(DONE_FILE, encoding="utf-8") if l.strip()}
    return set()


def daily_editgroup(tag: str) -> str:
    return hashlib.sha1(f"{tag}:{date.today().isoformat()}".encode()).hexdigest()[:12]


def main() -> None:
    p = argparse.ArgumentParser(description="Interactive PD-work edition-ID cleanup.")
    p.add_argument("--save", action="store_true", help="really edit (default: dry run)")
    p.add_argument("--limit", type=int, metavar="N")
    p.add_argument("--qid", action="append", default=[], metavar="QID")
    p.add_argument("--file", metavar="PATH")
    p.add_argument("--death-year", type=int, default=DEFAULT_DEATH_YEAR, metavar="Y")
    p.add_argument("--no-first-edition", action="store_true",
                   help="skip the first-edition prompt (fast Gutenberg-only batch pass)")
    p.add_argument("--break-out", action="append", default=[], metavar="EDITION_QID",
                   help="edition-level mode: break out ALL supported ids (Gutenberg P2034 + "
                        "Internet Archive P724) on an EDITION item into their own edition(s) of "
                        "its work. Repeatable.")
    p.add_argument("--break-out-ia", action="append", default=[], metavar="EDITION_QID",
                   help="like --break-out but Internet Archive (P724) only. Repeatable.")
    p.add_argument("--break-out-google", action="append", default=[], metavar="EDITION_QID",
                   help="like --break-out but Google Books (P675) only. Repeatable.")
    p.add_argument("--create-edition", metavar="WORK_QID",
                   help="create a plain edition of a work (seeded from the work's facts) and link "
                        "it (P747); combine with --seed-gutenberg to prefill publisher/place/date "
                        "from a Gutenberg id's 'Original Publication'.")
    p.add_argument("--seed-gutenberg", metavar="GID",
                   help="seed --create-edition from this Gutenberg id's imprint (marc260)")
    p.add_argument("--seed-lccn", metavar="LCCN",
                   help="seed --create-edition from this LCCN's Library of Congress record and "
                        "attach P1144 (edition is NOT auto-marked public domain)")
    p.add_argument("--refresh-p747", action="append", default=[], metavar="WORK_QID",
                   help="add summary qualifiers (P407/P577/P123 or P291) to a work's P747 "
                        "statements from each linked edition, and sort them by date. Repeatable.")
    p.add_argument("--editgroup", metavar="ID")
    args = p.parse_args()

    eg = args.editgroup or daily_editgroup("curate_pd_works")
    print(f"editgroup={eg} ({'SAVE' if args.save else 'dry run'})")

    # Refresh a work's P747 qualifiers + sort (targeted).
    if args.refresh_p747:
        for wq in args.refresh_p747:
            try:
                refresh_p747(wq, eg, dry_run=not args.save)
            except Exception as e:
                pywikibot.error(f"Error on {wq}: {e}")
        print("Done.")
        return

    # Create a plain edition of a work (targeted; e.g. the print source for an ebook's P144,
    # or an edition seeded from an LCCN's Library of Congress record).
    if args.create_edition:
        new = create_edition_of_work(args.create_edition, eg, dry_run=not args.save,
                                     seed_gutenberg=args.seed_gutenberg, seed_lccn=args.seed_lccn)
        if new:
            print(f"New edition: {new}  (use it as the P144 'based on' target when breaking out the ebook)")
        print("Done.")
        return

    # Edition-level break-out mode: targeted, no candidate loop / done-file. --break-out does
    # all supported ids (Gutenberg + IA); --break-out-ia restricts to Internet Archive.
    if args.break_out or args.break_out_ia or args.break_out_google:
        targets = ([(q, set(BREAKOUT_GATHER)) for q in args.break_out]
                   + [(q, {wd.PID_INTERNET_ARCHIVE_ID}) for q in args.break_out_ia]
                   + [(q, {wd.PID_GOOGLE_BOOKS_ID}) for q in args.break_out_google])
        for ed_qid, pids in targets:
            try:
                break_out_from_edition(ed_qid, eg, dry_run=not args.save, pids=pids)
            except Exception as e:
                pywikibot.error(f"Error on {ed_qid}: {e}")
        print("Done.")
        return

    if args.qid:
        items = args.qid
    elif args.file:
        items = [t for line in open(args.file, encoding="utf-8")
                 if (t := line.split("\t", 1)[0].strip()).startswith("Q")]
    else:
        items = fetch_candidates(args.death_year)
        print(f"{len(items)} PD work(s) with an edition-only ID (author d.<= {args.death_year})")

    done = load_done()
    processed = 0
    for qid in items:
        if args.limit is not None and processed >= args.limit:
            break
        if qid in done and not args.qid:
            continue
        processed += 1
        try:
            changed = process_item(qid, eg, dry_run=not args.save, no_first_ed=args.no_first_edition)
        except Exception as e:
            pywikibot.error(f"Error on {qid}: {e}")
            continue
        if args.save:
            OUTPUT_DIR.mkdir(exist_ok=True)
            with open(DONE_FILE, "a", encoding="utf-8") as f:
                f.write(f"{qid}\t{'changed' if changed else 'skip'}\n")
    print(f"Done. Processed {processed}.")


if __name__ == "__main__":
    main()
