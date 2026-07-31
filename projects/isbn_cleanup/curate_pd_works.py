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
import json
import re
import time
from datetime import date
from pathlib import Path

import pywikibot
import requests
from pywikibot.data import api as pwb_api

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
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
# gets move/deprecate only.
CREATE_TEMPLATES = {wd.PID_PROJECT_GUTENBERG_EBOOK_ID}


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


def _http(method: str, url: str, **kwargs):
    """requests with polite retry/backoff on HTTP 429 (rate limit) and transient errors.
    All the tool's direct HTTP (QLever, the Wikidata search API, Open Library) goes through
    here so a throttle backs off instead of hard-failing; pywikibot handles its own edit/read
    throttling separately. Returns the Response, or None if it kept failing."""
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
        if r.status_code == 429:
            wait = 10 * (attempt + 1)
            print(f"  (rate-limited 429; backing off {wait}s)", flush=True)
            time.sleep(wait)
            continue
        return r
    print(f"  ! gave up after repeated 429s for {url.split('?')[0]}")
    return None


_LANG_QID: dict | None = None


def language_qid(code: str) -> str | None:
    """ISO 639-1 code (e.g. 'en', 'de') -> the language item QID (Q1860, Q188 ...), via
    P218. Loaded once from QLever and cached. The Gutenberg catalog's per-ebook Language
    is authoritative for the *edition* -- a translation has a different language than the
    work, so we must NOT copy the work's language onto it."""
    global _LANG_QID
    if _LANG_QID is None:
        _LANG_QID = {}
        q = "SELECT ?c ?i WHERE { ?i wdt:P218 ?c }"
        r = _http("POST", QLEVER_URL, data={"query": PREFIXES + q},
                  headers={"User-Agent": USER_AGENT, "Accept": "text/tab-separated-values"}, timeout=120)
        if r is None:
            print("! could not load language codes; will fall back to the work's language")
        else:
            for line in r.text.splitlines()[1:]:
                parts = line.split("\t")
                if len(parts) >= 2:
                    c = parts[0].strip().strip('"')
                    qid = parts[1].strip().rsplit("/", 1)[-1].rstrip(">")
                    if c and qid.startswith("Q"):
                        _LANG_QID.setdefault(c, qid)
    return _LANG_QID.get(code)


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


def existing_gutenberg_edition(gid: str, exclude_qid: str) -> str | None:
    """QID of an EXISTING edition item that already carries this Gutenberg id, else None,
    so a re-run (e.g. after a partial-failure --save) REUSES the item instead of creating a
    duplicate. Uses the live MediaWiki search index (haswbstatement) -- the QLever dump is
    stale for freshly-created items. Excludes the work being processed (it still carries the
    id until its deprecation lands).

    Goes through pywikibot's authenticated API session (`api.Request`) so it rides the bot
    account's rate allowance + pywikibot's built-in throttling/429 handling, rather than an
    anonymous `requests` call that competes for the strict shared limit."""
    try:
        data = pwb_api.Request(site=repo, parameters={
            "action": "query", "list": "search", "srlimit": 20,
            "srsearch": f"haswbstatement:{wd.PID_PROJECT_GUTENBERG_EBOOK_ID}={gid}"}).submit()
    except Exception as e:
        print(f"  ! could not check for an existing edition of Gutenberg {gid} ({e}); assuming none")
        return None
    for hit in data.get("query", {}).get("search", []):
        qid = hit.get("title", "")
        if qid.startswith("Q") and qid != exclude_qid:
            return qid
    return None


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
    for c in live(page.claims.get(wd.PID_TITLE, [])):
        t = c.getTarget()
        if t:
            return (_clean_title(t.text), t.language)
    lab = item.labels.get("en")
    return (_clean_title(lab), "en") if lab else None


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


def build_gutenberg_specs(work_page, work_qid, gutenberg_id):
    """Return (labels, descriptions, claim_specs, p747_quals) for a new Gutenberg edition
    of the work. None if the work has no usable title. Pure -- no side effects (creation
    is deferred to after the confirm). Modeled on a well-formed example, Q106304446: a
    version item with P31/P629/P2034/P50/P123=Project Gutenberg/P407/P577/P1476, plus
    **P437 = ebook (Q128093)** and an en description **"<year> gutenberg version"**.

    ``p747_quals`` are (pid, value, kind) qualifiers summarising the edition inline on the
    work's P747 statement (dominant P747 qualifiers measured 2026-07-30: P407 language,
    P577 date, P123 publisher, P437 format)."""
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
            title = (_clean_title(entry["title"]), code)  # edition title in the edition's language
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

    specs = [
        (wd.PID_INSTANCE_OF, EDITION_TYPE, "item"),
        (wd.PID_EDITION_OR_TRANSLATION_OF, work_qid, "item"),
        (wd.PID_PROJECT_GUTENBERG_EBOOK_ID, gutenberg_id, "string"),
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
    return {title[1]: title[0]}, descriptions, specs, p747_quals


_VOLUME_RE = re.compile(r"\b(vol\.?|volume|tome|band|deel|tomo)\s*([ivxlcdm]+|\d+)\b"
                        r"|\bpart\s+(\d+|[ivxlcdm]+)\b", re.IGNORECASE)


def volume_marker(title: str) -> str | None:
    """Return the matched volume marker (e.g. 'vol. II') if a title looks like one volume of
    a multi-volume set, else None. Multi-volume needs manual per-volume (P478) modeling, so
    the tool must NOT auto-create a separate edition per volume (found via Q93673 'Memorie di
    Giuda, vol. I/II')."""
    m = _VOLUME_RE.search(title or "")
    return m.group(0) if m else None


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


def handle_identifier(work_page, work_qid, pid, claim, editions, edit_pages, descs,
                      pending_creates, dry_run, eg) -> None:
    value = claim.getTarget()
    plabel = EDITION_ONLY_IDS.get(pid, pid)
    has_template = pid in CREATE_TEMPLATES
    default = "c" if has_template else "d"
    # Guards that disable auto-create (-> manual handling, default keep):
    #  * non-Text Gutenberg id (Type=Sound=audiobook, Dataset, Image ...) -- the ebook
    #    template (P437=ebook) is wrong for it;
    #  * a volume title (one volume of a set) -- needs manual per-volume (P478) modelling.
    if has_template:
        entry = pg_catalog().get(str(value).strip())
        if entry and entry["type"] != "Text":
            print(f"  ⚠ Gutenberg {value} is Type={entry['type']} (not a text -- e.g. Sound=audiobook); "
                  "the ebook template doesn't fit -- model manually; not offering auto-create.")
            has_template, default = False, "k"
        elif entry and volume_marker(entry["title"]):
            vol = volume_marker(entry["title"])
            print(f"  ⚠ Gutenberg {value} = \"{entry['title']}\" looks like a VOLUME ({vol}); "
                  "multi-volume needs manual per-volume (P478) modelling -- not offering auto-create.")
            has_template, default = False, "k"
    opts = ("[c]reate version item / " if has_template else "") + \
           "[m]<Qid> move to edition / [d]eprecate on work / [k]eep"
    ans = csp.ask(f"{pid} ({plabel}) = {value}  ->  {opts}", default).strip()
    low = ans.lower()
    if low == "c" and has_template:
        built = build_gutenberg_specs(work_page, work_qid, value)
        if not built:
            print("  ! work has no title/label; cannot build an edition -- keeping.")
            return
        labels, descriptions, specs, p747_quals = built
        preview_edition(labels, descriptions, specs, p747_quals)
        # Reuse an already-existing edition for this id (idempotent re-run / partial-failure
        # recovery) instead of creating a duplicate.
        existing = existing_gutenberg_edition(value, work_qid)
        if existing:
            print(f"    -> edition for Gutenberg {value} already exists: {existing} (will REUSE, not create)")
        # Defer BOTH the creation and the deprecation until after the confirm: the new
        # edition's QID isn't known until it's created, and it becomes P8327 (intended
        # subject) on the deprecated id. The P747 link (+ its qualifiers) is added
        # post-create too.
        pending_creates.append((value, labels, descriptions, specs, p747_quals, pid, claim, existing))
        verb = f"REUSE {existing}" if existing else "create"
        descs.append(f"+ {verb} Gutenberg edition for {value} (P629 -> {work_qid}) + P747 link; "
                     f"then deprecate {pid} on work (P8327 -> the edition)")
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


def _assemble_first_edition(title, work_qid, publisher_qids, lang_qid, authors, date, place_qid,
                            pub_name=None):
    """Assemble (labels, descriptions, specs, p747_quals) for a first-edition item from the
    given facts. Marked BOTH ways (P393="1" and P31=first edition, per user). A publisher
    with no item (``pub_name``) is recorded as P123 = somevalue + object named as (P1932)."""
    specs = [
        (wd.PID_INSTANCE_OF, EDITION_TYPE, "item"),
        (wd.PID_INSTANCE_OF, QID_FIRST_EDITION, "item"),
        (wd.PID_EDITION_OR_TRANSLATION_OF, work_qid, "item"),
        (wd.PID_EDITION_NUMBER, "1", "string"),
        (wd.PID_TITLE, title, "monolingual"),
    ]
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
    specs.append((wd.PID_COPYRIGHT_STATUS, QID_PUBLIC_DOMAIN, "item"))

    year = date.year if date else None
    descriptions = {"en": f"{year} first edition" if year else "first edition"}

    p747_quals = [(wd.PID_EDITION_NUMBER, "1", "string")]
    if lang_qid:
        p747_quals.append((wd.PID_LANGUAGE_OF_WORK_OR_NAME, lang_qid, "item"))
    if date:
        p747_quals.append((wd.PID_PUBLICATION_DATE, date, "time"))
    for pub in publisher_qids:
        p747_quals.append((wd.PID_PUBLISHER, pub, "item"))
    if place_qid:
        p747_quals.append((wd.PID_PLACE_OF_PUBLICATION, place_qid, "item"))
    return {title[1]: title[0]}, descriptions, specs, p747_quals


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


def process_item(qid, edit_group, dry_run) -> bool:
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
    # is moved onto it, so skip the deprecate-based publisher rule.
    if not handle_first_edition(page, qid, editions, edit_pages, descs, pending_first_ed,
                                dry_run, edit_group):
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
        try:
            if existing:
                new_qid = existing
                print(f"  reusing existing edition {new_qid} for Gutenberg {value}")
            else:
                new_qid = cwd.create_item(labels=labels, descriptions=descriptions, claim_specs=specs,
                                          edit_group=edit_group, test=dry_run,
                                          summary=f"create Project Gutenberg edition of {qid}")
                if new_qid:
                    print(f"  created edition {new_qid} for Gutenberg {value}")
        except Exception as e:
            pywikibot.error(f"edition create failed for Gutenberg {value}: {e}")
            print(f"  ! SKIPPED Gutenberg {value} -- create failed; id left live on the work")
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
    p.add_argument("--editgroup", metavar="ID")
    args = p.parse_args()

    eg = args.editgroup or daily_editgroup("curate_pd_works")
    print(f"editgroup={eg} ({'SAVE' if args.save else 'dry run'})")

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
            changed = process_item(qid, eg, dry_run=not args.save)
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
