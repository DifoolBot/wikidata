import argparse
import json
import os
import random
import re
from collections import Counter
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

import pywikibot
import requests
from pywikibot.data import sparql
from pywikibot.data.api import Request

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
from shared_lib.date_value import Date
from shared_lib.rate_limiter import rate_limit
from shared_lib.wikidata_site import REPO as repo
from shared_lib.wikidata_site import SITE as site

edit_group = format(random.randrange(0, 2**48))  # "ece1e2aa4e61"

# check remove message:
# https://www.wikidata.org/wiki/Q10266249#Q10266249$B9B396CF-EAE9-463E-B8E7-45CEB56D8AF0
# double removed titles:
# Q16231723
# Draft: Q112335988
# NEVER EXISTED: Q100707887 -> moved to draft
# EXISTS: Q9022737 -> I can't find de.wikipedia link in history << father/child
# Kosinsky edits: Q14120514 - language
# NEVER EXISTED: Q56871179 -> should be deleted
# Q873432 -> rename Ram Charan -> Ram Charan (consultant) daarna delete

SUPPORTED_LANGS = [
    "en",
    "fr",
    "it",
    "de",
    "es",
    "pt",
    "nl",
    "pl",
    "ru",
    "ja",
    "zh",
    "ar",
    "sv",
    "uk",
    "ca",
    "no",
    "fi",
    "cs",
    "hu",
    "ko",
]

# Template: format with lang=", ".join(sorted(langs_done))
EDIT_SUMMARY = "Update {lang} Wikipedia references for deleted/missing pages"

# Mutable runtime state (work queue, caches, DB) lives in a separate data/
# subfolder, kept out of the code repo (see .gitignore).
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

WIKIPEDIA_EDITIONS_CACHE_FILE = DATA_DIR / "wikipedia_editions_cache.txt"

# Output items file used by routines that write/read QID lists
ITEMS_FILE = DATA_DIR / "items.txt"

# Log of P143-only references we could not match to the item's own deleted page
# (no sitelink-removal comment and no history snapshot); for manual review.
UNRESOLVED_P143_LOG = DATA_DIR / "unresolved_p143_refs.txt"

# Log of statements skipped because their Commons media value was deleted (the
# statement can't be edited without the whole save failing); for manual review.
DELETED_MEDIA_LOG = DATA_DIR / "deleted_media_refs.txt"

# Log of references whose source page was renamed within mainspace and still
# exists (often a missing sitelink or duplicate); left unchanged, for review.
RENAMED_STILL_EXISTS_LOG = DATA_DIR / "renamed_still_exists_refs.txt"

# Projects that are not article namespaces we treat specially
NON_ARTICLE_PROJECTS = {
    "wikiversity",
    "wikimedia",
    "wikinews",
    "wikiquote",
    "wikisource",
    "mediawiki",  # www.mediawiki.org
}


# ---------------------------------------------------------------------------
# Database tracker
# ---------------------------------------------------------------------------

# Backend selection: MariaDB on Toolforge (set WD_DB_BACKEND=mariadb), else the
# local Firebird database. Both use the same StatusTracker below; only the
# connection details (data/remove_sitelinks.json) and schema differ.
_use_mariadb = os.environ.get("WD_DB_BACKEND", "").lower() == "mariadb"
_DB_CREATE_SCRIPT = Path(
    "schemas/remove_sitelinks_mariadb.sql"
    if _use_mariadb
    else "schemas/remove_sitelinks.sql"
)

if TYPE_CHECKING:
    # Give the type checker one concrete base; both backends share this interface.
    from database_handler_firebird import FirebirdDatabaseHandler as _DBHandler
elif _use_mariadb:
    from database_handler_mariadb import MariaDbDatabaseHandler as _DBHandler
else:
    from database_handler_firebird import FirebirdDatabaseHandler as _DBHandler


class StatusTracker(_DBHandler):

    def __init__(self):
        file_path = DATA_DIR / "remove_sitelinks.json"
        super().__init__(file_path, _DB_CREATE_SCRIPT)

    def is_processed(self, qid: str) -> bool:
        """Return True if the QID has any existing record (success or failure)."""
        rows = self.execute_query("SELECT status FROM qids WHERE qid = ?", (qid,))
        return bool(rows)

    def mark_success(self, qid: str, summary: str = "") -> None:
        self.upsert(
            "qids", {"qid": qid, "status": "success", "summary": summary}, ["qid"]
        )

    def mark_failed(self, qid: str, error: Exception) -> None:
        trimmed_error = str(error)[:255]
        self.upsert(
            "qids",
            {"qid": qid, "status": "failed", "error_msg": trimmed_error},
            ["qid"],
        )

    def is_wikimedia_cat(self, qid: str) -> bool | None:
        """Return True/False if we have a cached value for whether this QID is a Wikimedia category, else None."""
        rows = self.execute_query(
            "SELECT is_wikimedia_cat FROM wikimedia_cats WHERE qid = ?", (qid,)
        )
        if rows:
            return rows[0][0] == 1
        return None

    def get_processed_qids(self) -> set[str]:
        """Return a set of all QIDs that have been recorded as processed."""
        rows = self.execute_query("SELECT qid FROM qids")
        return {row[0] for row in rows}

    def set_wikimedia_cat(self, qid: str, is_wikimedia_cat: bool) -> None:
        """Cache the Wikimedia category status for a QID."""
        self.upsert(
            "wikimedia_cats",
            {"qid": qid, "is_wikimedia_cat": 1 if is_wikimedia_cat else 0},
            ["qid"],
        )


# ---------------------------------------------------------------------------
# Wikipedia-editions QID map  (lang code -> QID, lazy-loaded once)
# ---------------------------------------------------------------------------

_wikipedia_editions: dict[str, str] = {}
_wikipedia_editions_loaded = False


def _dbname_to_subdomain(dbname: str) -> str:
    """Convert a Wikimedia database name to a wiki subdomain.

    e.g. "arwiki" -> "ar", "simplewiki" -> "simple",
    "zh_min_nanwiki" -> "zh-min-nan".
    """
    if dbname.endswith("wiki"):
        dbname = dbname[: -len("wiki")]
    return dbname.replace("_", "-")


def _load_wikipedia_editions() -> None:
    """Populate _wikipedia_editions from disk cache or SPARQL, at most once."""
    global _wikipedia_editions, _wikipedia_editions_loaded
    if _wikipedia_editions_loaded:
        return

    if WIKIPEDIA_EDITIONS_CACHE_FILE.exists():
        with WIKIPEDIA_EDITIONS_CACHE_FILE.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    qid, lang = line.split("\t", 1)
                    _wikipedia_editions[qid] = lang
        pywikibot.output(
            f"Loaded {len(_wikipedia_editions)} Wikipedia edition QIDs "
            f"from cache ({WIKIPEDIA_EDITIONS_CACHE_FILE})."
        )
        _wikipedia_editions_loaded = True
        return

    # Cache miss - query Wikidata.
    # Use the Wikimedia database name (P1800), e.g. "arwiki" / "simplewiki",
    # which maps directly to the wiki subdomain. This is more reliable than the
    # Wikimedia language code (P424): P424 is missing for some editions (e.g.
    # Arabic) and differs from the subdomain for others (e.g. Simple English,
    # where P424 is "en-x-simple" but the subdomain is "simple").
    query_object = sparql.SparqlQuery(repo=repo)
    query = """
    SELECT ?edition ?dbname WHERE {
      ?edition wdt:P31 wd:Q10876391 ;
               wdt:P1800 ?dbname .
    }
    """
    results = query_object.select(query, full_data=False)
    if not results:
        pywikibot.warning("SPARQL query returned no results.")
        return

    for row in results:
        qid = row["edition"].replace(wd.BASE_URL, "")
        _wikipedia_editions[qid] = _dbname_to_subdomain(row["dbname"])

    pywikibot.output(
        f"Fetched {len(_wikipedia_editions)} Wikipedia edition QIDs via SPARQL."
    )

    # Persist for next run
    if _wikipedia_editions:
        with WIKIPEDIA_EDITIONS_CACHE_FILE.open("w", encoding="utf-8") as fh:
            for qid, lang in sorted(_wikipedia_editions.items()):
                fh.write(f"{qid}\t{lang}\n")
        pywikibot.output(f"Saved editions cache to {WIKIPEDIA_EDITIONS_CACHE_FILE}.")

    _wikipedia_editions_loaded = True


# ---------------------------------------------------------------------------
# Page-status helpers
# ---------------------------------------------------------------------------


class PageStatus(Enum):
    EXISTS = "exists"
    REDIRECT = "redirect"
    DELETED = "deleted"
    RESTORED = "restored"
    MOVED_TO_DRAFT = "moved_to_draft"
    MOVED_TO_USER = "moved_to_user"
    MOVED_OUT_OF_MAINSPACE = "moved_out_of_mainspace"
    RENAMED_IN_MAINSPACE = "renamed_in_mainspace"
    NEVER_EXISTED = "never_existed"


# Statuses that mean the page was removed from mainspace and its reference can be
# ended (with the associated date).
_REMOVED_STATUSES = (
    PageStatus.DELETED,
    PageStatus.MOVED_TO_DRAFT,
    PageStatus.MOVED_TO_USER,
    PageStatus.MOVED_OUT_OF_MAINSPACE,
)

# How many mainspace renames to follow before giving up (guards against cycles).
_MAX_RENAME_DEPTH = 10


_page_status_cache: dict[tuple[str, str], tuple[PageStatus, str | None]] = {}


@rate_limit(30)  # 1 call every 5 seconds
def _get_page_status(
    title: str, lang: str, _depth: int = 0
) -> tuple[PageStatus, str | None]:
    """Return the current status of a Wikipedia page and a date if applicable.

    Returns a tuple of (status, detail) where detail is a timestamp for deleted
    pages and for pages moved out of mainspace (to Draft or User space), or None.

    A page renamed *within* mainspace is followed to its final title: if that
    chain ends in a removal (delete/move-out) the removal status+date is
    returned; otherwise RENAMED_IN_MAINSPACE (the content still exists somewhere).
    """
    key = (title, lang)

    wiki_site = pywikibot.Site(lang, "wikipedia")
    page = pywikibot.Page(wiki_site, title)

    if page.exists():
        status = PageStatus.REDIRECT if page.isRedirectPage() else PageStatus.EXISTS
        result = (status, None)
        _page_status_cache[key] = result
        return result

    # Not live - inspect the deletion/move logs (newest entry first)
    log_entries = list(wiki_site.logevents(page=page, total=250))
    if not log_entries:
        result = (PageStatus.NEVER_EXISTED, None)
        _page_status_cache[key] = result
        return result

    for entry in log_entries:
        action = entry.action()
        if action == "delete":
            deletion_date = (
                str(entry.timestamp()) if hasattr(entry, "timestamp") else None
            )
            result = (PageStatus.DELETED, deletion_date)
            _page_status_cache[key] = result
            return result
        if action == "restore":
            result = (PageStatus.RESTORED, None)
            _page_status_cache[key] = result
            return result
        # "move" is a normal page move; "move_redir" is a move that overwrote an
        # existing redirect at the target (both mean the page was renamed). A move
        # out of the article namespace (0) removes the page from mainspace: to
        # Draft (ns 118) = draftified, to User (ns 2) = userfied, or to any other
        # namespace (e.g. hu.wiki parks candidates in the Wikipedia/Project ns 4).
        # A move within mainspace (ns 0) is a rename: follow the new title, since
        # the article may live on there (or have been deleted after the rename).
        if action in ("move", "move_redir"):
            params = getattr(entry, "params", {})
            if isinstance(params, dict):
                target_ns = params.get("target_ns")
                moved_status = None
                if target_ns == 118:
                    moved_status = PageStatus.MOVED_TO_DRAFT
                elif target_ns == 2:
                    moved_status = PageStatus.MOVED_TO_USER
                elif target_ns not in (0, None):
                    moved_status = PageStatus.MOVED_OUT_OF_MAINSPACE
                if moved_status is not None:
                    move_date = (
                        str(entry.timestamp()) if hasattr(entry, "timestamp") else None
                    )
                    result = (moved_status, move_date)
                    _page_status_cache[key] = result
                    return result

                # Rename within mainspace (ns 0): follow the new title.
                target_title = params.get("target_title")
                if target_title and _depth < _MAX_RENAME_DEPTH:
                    tgt_status, tgt_detail = get_page_status(
                        target_title, lang, _depth=_depth + 1
                    )
                    if tgt_status in _REMOVED_STATUSES:
                        result = (tgt_status, tgt_detail)  # renamed, then removed
                    else:
                        # content still exists (or unresolvable) under a new title
                        result = (PageStatus.RENAMED_IN_MAINSPACE, None)
                else:
                    result = (PageStatus.RENAMED_IN_MAINSPACE, None)
                _page_status_cache[key] = result
                return result

    result = (PageStatus.NEVER_EXISTED, None)
    _page_status_cache[key] = result
    return result


def get_page_status(
    title: str, lang: str, _depth: int = 0
) -> tuple[PageStatus, str | None]:
    key = (title, lang)
    if key in _page_status_cache:
        return _page_status_cache[key]
    return _get_page_status(title, lang, _depth=_depth)


@rate_limit(5)  # 1 call every 5 seconds
def _get_page_title_from_revision(lang: str, revid: int | str) -> str | None:

    if revid == 0:
        raise ValueError("Revision ID 0 is invalid and cannot be queried.")

    wiki_site = pywikibot.Site(lang, "wikipedia")

    result = wiki_site.simple_request(
        action="query",
        revids=revid,
        prop="info",
    ).submit()

    qry = result.get("query")
    if not qry or "pages" not in qry:
        # raise ValueError(f"Bad revision {lang}:{revid}")
        return None
    pages = qry["pages"]
    page_data = next(iter(pages.values()))
    return page_data["title"]


@rate_limit(5)  # 1 call every 5 seconds
def _get_page_title_from_pageid(lang: str, pageid: int | str) -> str | None:
    """Resolve a page id (curid) to its title, or None if the page is gone.

    A deleted page id comes back with a ``missing`` marker and no title (the
    public API cannot map a deleted id to its title), so we return None just as
    for an invalid revision id.
    """
    if str(pageid) == "0":
        raise ValueError("Page ID 0 is invalid and cannot be queried.")

    wiki_site = pywikibot.Site(lang, "wikipedia")

    result = wiki_site.simple_request(
        action="query",
        pageids=pageid,
        prop="info",
    ).submit()

    qry = result.get("query")
    if not qry or "pages" not in qry:
        return None
    pages = qry["pages"]
    page_data = next(iter(pages.values()))
    if "missing" in page_data:
        return None
    return page_data.get("title")


def _parse_wikipedia_url(
    url: str,
    page_title_buffer: dict[tuple[str, str], str | None] | None = None,
) -> dict[str, str | None] | None:
    """
    Parse a Wikipedia URL and return {"language": ..., "title": ...}, or None
    if the URL is not a recognised Wikipedia article URL.

    Handles two URL formats:
      - /wiki/Andrew_Madoff
      - /w/index.php?title=Andrew_Madoff&oldid=...
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""

    m = re.match(r"^(?:www\.)?([a-z\-]+)(?:\.m)?\.([a-z]+(?:\.[a-z]+)?)$", host)
    if not m:
        return None

    lang, project = m.group(1), m.group(2).split(".")[0]
    if lang == "wikidata" and project == "org":
        return {"language": None, "project": "wikidata", "title": None}

    if lang == "mediawiki" and project == "org":
        return {"language": None, "project": "mediawiki", "title": None}

    if project in NON_ARTICLE_PROJECTS:
        return {"language": lang, "project": project, "title": None}

    if project != "wikipedia":
        return None

    params = parse_qs(parsed.query)

    def _buffered_title(_lang: str, _key: str, resolver, _id: str) -> str | None:
        cache_key = (_lang, _key)
        if page_title_buffer is not None:
            if cache_key not in page_title_buffer:
                page_title_buffer[cache_key] = resolver(_lang, _id)
            return page_title_buffer[cache_key]
        return resolver(_lang, _id)

    def _get_title_from_oldid(_lang: str, _oldid: str) -> str | None:
        return _buffered_title(_lang, _oldid, _get_page_title_from_revision, _oldid)

    def _get_title_from_curid(_lang: str, _curid: str) -> str | None:
        return _buffered_title(
            _lang, f"curid:{_curid}", _get_page_title_from_pageid, _curid
        )

    def _get_title_and_ids_from_params():
        title = None
        oldid = None
        curid = None
        if "title" in params:
            title = params["title"][0].replace("_", " ")
        if "oldid" in params:
            oldid = params["oldid"][0]
        if "curid" in params:
            curid = params["curid"][0]
        if not title and not oldid and not curid:
            if parsed.path.startswith("/wiki/"):
                subpath = parsed.path[len("/wiki/") :]
                # Special:Permalink and its alias Special:PermanentLink, matched
                # case-insensitively (e.g. "Special:PermaLink"), optionally
                # followed by "/Some_Title" - a revision id followed by an
                # optional page-title hint.
                perma = re.match(
                    r"^Special:Perma(?:nent)?link/(\d+)(?:/.*)?$",
                    subpath,
                    re.IGNORECASE,
                )
                if perma:
                    oldid = perma.group(1)
                elif subpath.lower().startswith("special:"):
                    # Any other Special: page is not a normal article URL.
                    raise ValueError(f"Unrecognized Wikipedia URL format: {url}")
                else:
                    title = subpath.replace("_", " ")
            elif parsed.path.startswith(f"/{lang}-"):
                # language variant like http://zh.wikipedia.org/zh-tw/%E9%AB%98%E7%AB%8B
                title = parsed.path.split("/", 2)[-1].replace("_", " ")

        return title, oldid, curid

    has_invalid_id = False
    param_title, oldid, curid = _get_title_and_ids_from_params()
    title = param_title
    # oldid (a revision) and curid (a page id) are both numeric handles we try to
    # resolve to a title; when the page/revision is deleted they cannot be
    # resolved, so fall back to the title= param if present, else give up on the
    # URL (title stays None, no error).
    if oldid:
        resolved = _get_title_from_oldid(lang, oldid)
        if resolved:
            title = resolved
        else:
            has_invalid_id = True
            title = param_title
    elif curid:
        resolved = _get_title_from_curid(lang, curid)
        if resolved:
            title = resolved
        else:
            has_invalid_id = True
            title = param_title

    if not has_invalid_id and not title:
        raise ValueError(f"Unrecognized Wikipedia URL format: {url}")

    return {"language": lang, "project": "wikipedia", "title": title}


# ---------------------------------------------------------------------------
# Source / claim inspection
# ---------------------------------------------------------------------------


def _source_get_qids(source: dict, pid: str) -> list[str]:
    """Collect all QID targets for *pid* within a single source dict."""
    return [
        claim.getTarget().id
        for claim in source.get(pid, [])
        if (t := claim.getTarget()) and hasattr(t, "id")
    ]


def _source_get_urls(source: dict, pid: str) -> list[str]:
    """Collect all URL string targets for *pid* within a single source dict."""
    return [
        url
        for claim in source.get(pid, [])
        if isinstance(url := claim.getTarget(), str)
    ]


def is_wikimedia_cat(qid: str, tracker: StatusTracker) -> bool:
    b = tracker.is_wikimedia_cat(qid)
    if b is not None:
        return b

    # determine from sparql; instance of Wikimedia category (Q4167836)
    query = f"""
            SELECT ?result WHERE {{
            VALUES ?item {{ wd:{qid} }}
            OPTIONAL {{ ?item wdt:P31 wd:Q4167836 }}

            BIND(
                IF(!BOUND(?item), "not exists",
                IF(BOUND(?item), "yes", "no")
                ) AS ?result
            )
            }}
    """
    query_object = sparql.SparqlQuery(repo=repo)
    results = query_object.select(query, full_data=False)
    if not results:
        raise RuntimeError(
            f"SPARQL query returned no results for Wikimedia category check on {qid}."
        )

    for row in results:
        if "result" not in row:
            raise RuntimeError(
                f"SPARQL query missing 'result' field for Wikimedia category check on {qid}: {row}"
            )
        value = row["result"]
        if value == "yes":
            tracker.set_wikimedia_cat(qid, True)
            return True
        elif value == "no":
            tracker.set_wikimedia_cat(qid, False)
            return False

    raise RuntimeError(
        "Unexpected SPARQL result for Wikimedia category check on {qid}: {results}"
    )


def can_ignore_multiple_language_source(
    source: dict,
    tracker: StatusTracker,
) -> bool:
    # must include inferred from (P3452) with a Wikipedia cat
    # only these are allowed
    allowed = [
        wd.PID_INFERRED_FROM,
        wd.PID_RETRIEVED,
        wd.PID_IMPORTED_FROM_WIKIMEDIA_PROJECT,
        wd.PID_WIKIMEDIA_IMPORT_URL,
    ]
    if any(pid not in allowed for pid in source.keys()):
        return False
    inferred_qids = _source_get_qids(source, wd.PID_INFERRED_FROM)
    if not inferred_qids:
        return False
    for qid in inferred_qids:
        if not is_wikimedia_cat(qid, tracker):
            return False
    return True


def _title_is_non_article(lang: str, title: str) -> bool:
    """True if *title* on *lang*wiki is in a non-article (non-main) namespace.

    Import URLs sometimes point at a User page, a File/Archivo page, a Category,
    a Portal, etc. rather than an article; those don't correspond to a missing
    article sitelink and are ignored. The namespace is resolved from the wiki's
    own table, so it works for every language and every namespace alias
    (e.g. "Archivo:" = File on es.wiki). pywikibot caches the Site per language.
    """
    if ":" not in title:
        return False  # no prefix -> main namespace
    try:
        site = pywikibot.Site(lang, "wikipedia")
        return pywikibot.Page(site, title).namespace().id != 0
    except Exception:
        return False


LANG_NORMALIZATIONS = {
    "ms-my": "ms",  # Malay Wikipedia: P424 on edition says ms-my, subdomain is ms
    "nb": "no",  # Norwegian Bokmål Wikipedia: P424 says nb, subdomain is no
}

SUBDOMAIN_CORRECTIONS = {
    "jp": "ja",  # Q11414732
}


def _normalize_wiki_lang(lang: str) -> str:
    return LANG_NORMALIZATIONS.get(lang, lang)


def _analyze_source(
    source: dict,
    sitelinks: dict,
    tracker: StatusTracker,
    page_title_buffer: dict[tuple[str, str], str | None] | None = None,
) -> dict:
    """
    Examine one reference source for Wikipedia import signals.

    Returns a dict with:
      - language: first Wikipedia language code detected
      - has_missing_sitelink: True if that language has no sitelink on the item
      - imported_from_qid: QID of the Wikipedia edition (P143)
      - import_url: import URL (P4656 / P813 etc.)
    """
    result = {
        "language": None,
        "has_missing_sitelink": False,
        "imported_from_qid": None,
        "import_url": None,
        "has_non_article_url": False,
    }

    for qid in _source_get_qids(source, wd.PID_IMPORTED_FROM_WIKIMEDIA_PROJECT):
        lang = _wikipedia_editions.get(qid)
        if not lang:
            continue
        lang = _normalize_wiki_lang(lang)
        result["imported_from_qid"] = qid
        if result["language"] is None:
            result["language"] = lang
        if result["language"] != lang:
            if can_ignore_multiple_language_source(source, tracker):
                continue
            raise ValueError(
                f"Multiple languages detected in one source: {result['language']} and {lang}"
            )
        if f"{lang}wiki" not in sitelinks:
            result["has_missing_sitelink"] = True

    for url in _source_get_urls(source, wd.PID_WIKIMEDIA_IMPORT_URL):
        info = _parse_wikipedia_url(url, page_title_buffer=page_title_buffer)
        if not info:
            raise ValueError(f"Unrecognized wikimedia import URL format: {url}")
        lang = info["language"]
        project = info["project"]
        title = info["title"] or ""
        if lang in SUBDOMAIN_CORRECTIONS:
            lang = SUBDOMAIN_CORRECTIONS[lang]
        if project in (NON_ARTICLE_PROJECTS | {"wikidata"}):
            continue
        if project != "wikipedia":
            raise ValueError(f"Unrecognized wikimedia project in URL: {url}")
        if not lang:
            raise ValueError(f"Could not determine language from URL: {url}")
        if _title_is_non_article(lang, title):
            # ignore non-article URLs (User, File, Category, ...): they don't
            # correspond to a missing article sitelink
            result["has_non_article_url"] = True
            continue
        if result["import_url"]:
            raise ValueError(
                f"Multiple import URLs found in one source: {result['import_url']} and {url}"
            )
        result["import_url"] = url
        if lang:
            if result["language"] is None:
                result["language"] = lang
            if result["language"] != lang:
                raise ValueError(
                    f"Multiple languages detected in one source: {result['language']} and {lang}"
                )
            if f"{lang}wiki" not in sitelinks:
                result["has_missing_sitelink"] = True

    if result["has_non_article_url"] and not result["import_url"]:
        # non-article urls don't need a sitelink
        result["has_missing_sitelink"] = False
    return result


def _get_ref_hash(source: dict) -> str | None:
    """Return the hash of the first reference claim found in *source*."""
    for claims in source.values():
        for claim in claims:
            return claim.hash
    return None


def _deleted_commons_media(claim: pywikibot.Claim) -> str | None:
    """Return the filename if *claim* is a commonsMedia statement whose file was
    deleted from Commons, else None.

    Such a statement cannot be edited: Wikibase re-validates the media value on
    save and rejects the whole edit with `no-such-media`. Callers skip it so the
    item's other references can still be updated.
    """
    if getattr(claim, "type", None) != "commonsMedia":
        return None
    target = claim.getTarget()
    if target is None:
        return None
    try:
        if target.exists():
            return None
        return target.title(with_ns=False)
    except Exception:
        return None


def collect_wikipedia_refs(
    item: pywikibot.ItemPage,
    tracker: StatusTracker,
    page_title_buffer: dict[tuple[str, str], str | None] | None = None,
) -> dict[str, list[dict]]:
    """
    Scan all non-deprecated claims for sources that point to a Wikipedia edition
    whose sitelink is absent from the item.

    Statements whose Commons media value was deleted are skipped (and logged):
    they cannot be saved, and would fail the whole edit.

    Returns a dict keyed by language code, each value being a list of
    {claim, source, analysis} entries.
    """
    by_lang: dict[str, list[dict]] = {}
    sitelinks = item.sitelinks

    for claim_list in item.claims.values():
        for claim in claim_list:
            if claim.getRank() == "deprecated":
                continue

            collected = []
            for source in claim.sources:
                analysis = _analyze_source(
                    source,
                    sitelinks,
                    page_title_buffer=page_title_buffer,
                    tracker=tracker,
                )
                if not analysis["has_missing_sitelink"]:
                    continue
                collected.append((source, analysis))
            if not collected:
                continue

            deleted_file = _deleted_commons_media(claim)
            if deleted_file is not None:
                pywikibot.warning(
                    f"[{item.title()}] Skipping {claim.getID()} reference(s): "
                    f"Commons file '{deleted_file}' is deleted, so the statement "
                    f"cannot be edited (logged to {DELETED_MEDIA_LOG.name})."
                )
                _log_deleted_media(item.title(), claim.getID(), deleted_file)
                continue

            for source, analysis in collected:
                lang = analysis["language"] or "unknown"
                by_lang.setdefault(lang, []).append(
                    {"claim": claim, "source": source, "analysis": analysis}
                )

    return by_lang


# ---------------------------------------------------------------------------
# Title recovery
# ---------------------------------------------------------------------------


def titles_from_reference(
    lang: str,
    entry: dict,
    page_title_buffer: dict[tuple[str, str], str | None] | None = None,
) -> list[str]:
    """Return the article title(s) carried by one reference's P4656 import URLs.

    A reference that only has P143 (imported from) and no import URL yields an
    empty list. Non-article URLs (User, File, Category, ...) are ignored. Order
    is preserved, duplicates removed.
    """
    titles: list[str] = []
    for url in _source_get_urls(entry["source"], wd.PID_WIKIMEDIA_IMPORT_URL):
        info = _parse_wikipedia_url(url, page_title_buffer=page_title_buffer)
        if not info:
            raise ValueError(f"Unrecognized URL format: {url}")
        if info["project"] != "wikipedia":
            continue
        url_lang = info["language"]
        if url_lang in SUBDOMAIN_CORRECTIONS:
            url_lang = SUBDOMAIN_CORRECTIONS[url_lang]
        if url_lang != lang:
            raise ValueError(
                f"URL language mismatch: expected '{lang}', got '{url_lang}' in URL {url}"
            )
        title = info["title"]
        if not title:
            continue
        if _title_is_non_article(lang, title):
            # ignore non-article URLs (User, File, Category, ...)
            continue
        if title not in titles:
            titles.append(title)
    return titles


@rate_limit(5)  # 1 call every 5 seconds
def _get_old_version_snapshot(item: pywikibot.ItemPage, revid: int | str) -> dict:
    """Fetch an old revision snapshot from the MediaWiki API with rate limiting."""
    old_version = item.getOldVersion(revid)
    # some can return None, for example Q13407351 due to vandalism
    return json.loads(old_version) if old_version else {}


@rate_limit(10)  # 1 call every 10 seconds
def find_newest_sitelink_removal(
    item: pywikibot.ItemPage,
    lang: str,
    _comment_cache: dict[str, list[tuple[str, str]]] | None = None,
) -> tuple[str, str] | None:
    """
    Return the newest sitelink-removal (title, timestamp) for *lang*, or None.

    When a client-wiki page is deleted, Wikibase auto-removes the sitelink with a
    summary like ``/* clientsitelink-remove:1||enwiki */ <Title>``, where <Title>
    is the exact page title that was deleted and the revision timestamp is when
    the sitelink was removed. Scanning newest-first returns the *final* removal,
    which is what we want when a page was renamed before deletion (the old title
    may now be a different, live article). Compare with
    find_title_from_history_snapshots, which walks oldest-first and would return
    the pre-rename title.

    Only edit summaries/timestamps are inspected (one cheap API call), no
    per-revision snapshots are fetched.
    """
    wiki_key = f"{lang}wiki"
    pywikibot.output(f"  Searching removal comments for '{wiki_key}' sitelink...")

    qid = item.title()
    if _comment_cache is not None and qid in _comment_cache:
        revisions = _comment_cache[qid]
    else:
        req = Request(
            site=site,
            parameters={
                "action": "query",
                "prop": "revisions",
                "titles": qid,
                "rvprop": "comment|timestamp",
                "rvlimit": "500",
                "rvdir": "older",  # newest -> oldest
            },
        )
        data = req.submit()

        revisions = []
        for _, page in data["query"]["pages"].items():
            revisions = [
                (rev.get("comment", ""), rev.get("timestamp", ""))
                for rev in page.get("revisions", [])
            ]

        if _comment_cache is not None:
            _comment_cache[qid] = revisions

    # e.g. "/* clientsitelink-remove:1||enwiki */ Ram Charan (consultant)"
    pattern = re.compile(
        r"clientsitelink-remove:\d+\|\|" + re.escape(wiki_key) + r"\s*\*/\s*(.+?)\s*$"
    )
    for comment, timestamp in revisions:  # newest first
        m = pattern.search(comment)
        if m:
            title = m.group(1)
            pywikibot.output(
                f"  Found '{title}' removed on {timestamp} in sitelink-removal comment."
            )
            return title, timestamp

    return None


@rate_limit(10)  # 1 call every 10 seconds
def find_title_from_history_snapshots(
    item: pywikibot.ItemPage,
    lang: str,
    max_check_count: int = 5,
    _revision_cache: dict[str, list[dict]] | None = None,
) -> str | None:
    """
    Walk the item's revision history looking for an old sitelink for *lang*wiki.

    To minimise API calls, consecutive revisions by the same user are collapsed
    into a single "run", and only the newest revision of each run is fetched in
    full. This covers every distinct editing session with the fewest getOldVersion
    calls.

    This walks oldest-first and returns the earliest recorded title; for the
    title actually deleted (after any rename), try find_newest_sitelink_removal
    first.
    """
    wiki_key = f"{lang}wiki"
    pywikibot.output(f"  Searching revision history for '{wiki_key}' sitelink...")

    # Fetch revisions once per item, reuse across language calls
    qid = item.title()
    if _revision_cache is not None and qid in _revision_cache:
        candidates = _revision_cache[qid]
    else:
        req = Request(
            site=site,
            parameters={
                "action": "query",
                "prop": "revisions",
                "titles": item.title(),
                "rvprop": "ids|timestamp|user",
                "rvlimit": "50",
                "rvdir": "newer",  # oldest -> newest so we can group runs in order
            },
        )
        data = req.submit()

        revisions = []
        for _, page in data["query"]["pages"].items():
            revisions = page.get("revisions", [])

        # Keep only the last revision of each consecutive same-user run.
        # Some revisions may omit "user" if the username is removed.
        candidates = []
        for i, rev in enumerate(revisions):
            current_user = rev.get("user")
            next_user = revisions[i + 1].get("user") if i < len(revisions) - 1 else None
            if i == len(revisions) - 1 or current_user != next_user:
                candidates.append(rev)

        if _revision_cache is not None:
            _revision_cache[qid] = candidates

        pywikibot.output(
            f"  {len(revisions)} revisions -> {len(candidates)} user-run candidates to inspect."
        )

    for check_count, rev in enumerate(candidates):
        if check_count >= max_check_count:
            pywikibot.output(
                f"  Reached max check count ({max_check_count}). Stopping."
            )
            break

        snapshot = _get_old_version_snapshot(item, rev["revid"])
        sitelinks = snapshot.get("sitelinks", {})
        if wiki_key in sitelinks:
            title = sitelinks[wiki_key].get("title")
            if title:
                user = rev.get("user", "unknown")
                pywikibot.output(
                    f"  Found '{title}' in rev {rev['revid']} (user: {user})"
                )
                return title

    return None


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


def _iso_to_date(timestamp: str) -> cwd.Date:
    """Convert an ISO-8601 timestamp (e.g. '2022-06-25T19:39:13Z') to a Date."""
    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return Date(year=dt.year, month=dt.month, day=dt.day)


def _log_unresolved_p143(qid: str, lang: str, entry: dict) -> None:
    """Append an unmatchable P143-only reference to UNRESOLVED_P143_LOG for review."""
    prop = entry["claim"].getID()
    ref_hash = _get_ref_hash(entry["source"]) or "?"
    when = datetime.now().isoformat(timespec="seconds")
    with UNRESOLVED_P143_LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"{when}\t{qid}\t{lang}\t{prop}\t{ref_hash}\n")


def _log_deleted_media(qid: str, prop: str, filename: str) -> None:
    """Append a skipped deleted-Commons-media statement to DELETED_MEDIA_LOG."""
    when = datetime.now().isoformat(timespec="seconds")
    with DELETED_MEDIA_LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"{when}\t{qid}\t{prop}\t{filename}\n")


def _log_renamed_still_exists(qid: str, lang: str, title: str) -> None:
    """Append a renamed-but-still-existing source page to RENAMED_STILL_EXISTS_LOG."""
    when = datetime.now().isoformat(timespec="seconds")
    with RENAMED_STILL_EXISTS_LOG.open("a", encoding="utf-8") as fh:
        fh.write(f"{when}\t{qid}\t{lang}\t{title}\n")


@rate_limit(10)
def process_lang(
    page: cwd.WikiDataPage,
    lang: str,
    lang_entries: list[dict],
    _revision_cache: dict[str, list[dict]],
    _comment_cache: dict[str, list[tuple[str, str]]],
    page_title_buffer: dict[tuple[str, str], str | None] | None = None,
) -> bool:
    """
    Full pipeline for one language edition.

    P4656 and P143-only references are matched differently:
      * a P4656 import URL may point to a *different* page than the item (a
        spouse, relative, category, list), so it uses its own URL title and is
        ended on that title's deletion/move date only when that page is deleted;
      * a P143-only reference always refers to the item's own page, so it is
        ended on the date of the newest sitelink removal. When there is no
        removal comment, the item's own former title is recovered from the
        revision-history snapshot (then resolved via the deletion log). If
        neither yields a title, the reference is left unchanged and logged to
        UNRESOLVED_P143_LOG for manual review.
    """
    item: pywikibot.ItemPage = page.item
    wiki_key = f"{lang}wiki"

    if wiki_key in item.sitelinks:
        pywikibot.output(
            f"[{lang}] Sitelink present ({item.sitelinks[wiki_key].canonical_title()}), skipping."
        )
        return False

    pywikibot.output(
        f"[{lang}] No sitelink - investigating {len(lang_entries)} source(s)..."
    )

    # Newest sitelink removal (item's own page title + when it was removed),
    # used for P143-only references, which always refer to the item's own page.
    removal = find_newest_sitelink_removal(item, lang, _comment_cache=_comment_cache)
    removal_date = _iso_to_date(removal[1]) if removal else None

    # Collect the P4656 title(s) each reference carries. A P4656 URL may point to
    # a *different* page than the item (a spouse, relative, category, list), so
    # each is resolved on its own and never used to match a P143-only ref.
    entry_titles: list[tuple[dict, list[str]]] = []
    has_p143_only = False
    for entry in lang_entries:
        titles = titles_from_reference(lang, entry, page_title_buffer=page_title_buffer)
        entry_titles.append((entry, titles))
        if not titles:
            has_p143_only = True

    # The item's own former page title, for P143-only refs, when there is no
    # removal comment. Recovered from the item's own revision history (its former
    # sitelink) - never from P4656, which may be a different page.
    item_page_title = None
    if has_p143_only and removal is None:
        pywikibot.output(
            f"[{lang}] P143-only ref(s) without a removal comment; checking "
            f"revision history snapshots for the item's own page..."
        )
        item_page_title = find_title_from_history_snapshots(
            item, lang, _revision_cache=_revision_cache
        )

    # Build an end plan of (entry, title, forced_date):
    #   * P4656 ref           -> (entry, url_title, None): resolved via del. log.
    #   * P143-only + removal -> (entry, item_page, removal_date): removal date
    #     used directly (the page may since have been recreated).
    #   * P143-only + history -> (entry, item_page, None): resolved via del. log.
    #   * P143-only, neither  -> undeterminable: skip, warn, log for review.
    plan: list[tuple[dict, str, cwd.Date | None]] = []
    for entry, titles in entry_titles:
        if titles:
            for title in titles:
                plan.append((entry, title, None))
        elif removal is not None:
            plan.append((entry, removal[0], removal_date))
        elif item_page_title is not None:
            plan.append((entry, item_page_title, None))
        else:
            _log_unresolved_p143(item.title(), lang, entry)
            pywikibot.warning(
                f"[{lang}] P143-only reference on {entry['claim'].getID()} "
                f"cannot be matched to the item's own page (no removal comment, "
                f"no history snapshot); leaving it unchanged "
                f"(logged to {UNRESOLVED_P143_LOG.name})."
            )

    # Resolve each distinct title (forced_date is None) via the deletion log and
    # sort into: removed (-> end date), renamed-but-still-exists (-> leave + log),
    # and any other "not deleted" status (-> puzzling, may fail below).
    end_dates: dict[str, cwd.Date | None] = {}
    puzzling: dict[str, PageStatus] = {}
    for _, title, forced_date in plan:
        if forced_date is not None or title in end_dates:
            continue
        status, detail = get_page_status(title, lang)
        if status in _REMOVED_STATUSES:
            if not detail:
                raise RuntimeError(
                    f"Deletion date not found for '{title}' on {lang}.wikipedia"
                )
            pywikibot.output(
                f"[{lang}] '{title}' removed from {lang}.wikipedia on {detail}."
            )
            end_dates[title] = _iso_to_date(detail)
        elif status == PageStatus.RENAMED_IN_MAINSPACE:
            pywikibot.warning(
                f"[{lang}] '{title}' was renamed within mainspace and still "
                f"exists; leaving its reference(s) unchanged "
                f"(logged to {RENAMED_STILL_EXISTS_LOG.name})."
            )
            _log_renamed_still_exists(item.title(), lang, title)
            end_dates[title] = None
        else:
            pywikibot.warning(
                f"[{lang}] '{title}' is not deleted (status: {status.name}); "
                f"leaving its reference(s) unchanged."
            )
            end_dates[title] = None
            puzzling[title] = status

    # Safety: fail loudly only when nothing was ended AND at least one title is
    # "not deleted" for a puzzling reason. Renamed-but-still-exists titles are
    # benign (logged above) and don't count; a removal date on any reference
    # (forced or resolved) is enough to rescue the item.
    has_forced = any(forced_date is not None for _, _, forced_date in plan)
    ended_any = has_forced or any(d is not None for d in end_dates.values())
    if puzzling and not ended_any:
        if len(puzzling) == 1:
            title, status = next(iter(puzzling.items()))
            raise RuntimeError(
                f"Page '{title}' on {lang}.wikipedia is not deleted "
                f"(status: {status.name})."
            )
        status_counts = Counter(status.name for status in puzzling.values())
        summary = ", ".join(f"{name}: {n}" for name, n in sorted(status_counts.items()))
        raise RuntimeError(
            f"None of the {len(puzzling)} recovered titles on {lang}.wikipedia "
            f"are deleted ({summary})."
        )

    # End each reference that resolved to an end date.
    did_something = False
    for entry, title, forced_date in plan:
        end_date = forced_date if forced_date is not None else end_dates.get(title)
        if end_date is None:
            continue
        ref_hash = _get_ref_hash(entry["source"])
        if ref_hash:
            page.end_reference(entry["claim"].snak, ref_hash, end_date=end_date)
            did_something = True
    return did_something


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def process_item(
    qid: str,
    tracker: StatusTracker,
    dry_run: bool = True,
) -> None:
    """Fetch a Wikidata item and run the full cleanup pipeline."""
    if not dry_run and tracker.is_processed(qid):
        # pywikibot.output(f"Already processed {qid}, skipping.")
        return

    pywikibot.output(f"\n{'='*60}\nProcessing {qid}  (dry_run={dry_run})\n{'='*60}")
    _load_wikipedia_editions()

    try:
        item = pywikibot.ItemPage(repo, qid)
        item.get()

        page_title_buffer: dict[tuple[str, str], str | None] = {}
        wp_refs = collect_wikipedia_refs(
            item, page_title_buffer=page_title_buffer, tracker=tracker
        )
        if not wp_refs:
            pywikibot.output("No Wikipedia references with missing sitelinks found.")
            if not dry_run:
                tracker.mark_success(qid, "No refs found")
            return

        pywikibot.output(f"Languages with stale refs: {sorted(wp_refs.keys())}")

        page = cwd.WikiDataPage(item, test=dry_run)
        langs_done: set[str] = set()

        # These caches live for this item's lifetime only, shared across langs.
        revision_cache: dict[str, list[dict]] = {}
        comment_cache: dict[str, list[tuple[str, str]]] = {}

        for lang in sorted(wp_refs.keys()):
            if lang not in SUPPORTED_LANGS and lang != "unknown":
                pywikibot.output(f"[{lang}] Not in SUPPORTED_LANGS - skipping.")
                continue
            if process_lang(
                page,
                lang,
                wp_refs[lang],
                _revision_cache=revision_cache,
                _comment_cache=comment_cache,
                page_title_buffer=page_title_buffer,
            ):
                langs_done.add(lang)

        page.summary = EDIT_SUMMARY.format(lang=", ".join(sorted(langs_done)))
        page.edit_group = edit_group
        applied = page.apply()
        # Dry-run makes no Wikidata edits (WikiDataPage test=dry_run) and records
        # nothing, so a test run never blocks a later real run via is_processed.
        if not dry_run:
            if applied:
                tracker.mark_success(qid, page.used_summary or "")
            else:
                tracker.mark_success(qid, "Nothing done")

    except Exception as e:
        pywikibot.error(f"Error processing {qid}: {e}")
        if not dry_run:
            tracker.mark_failed(qid, e)


def _format_progress(done: int, total: int, start_time: datetime) -> str:
    """Build a 'percentage done + expected end time' progress line."""
    pct = (done / total * 100) if total else 0.0
    elapsed = (datetime.now() - start_time).total_seconds()
    if done > 0:
        avg = elapsed / done
        remaining = avg * (total - done)
        eta = datetime.now() + timedelta(seconds=remaining)
        eta_str = eta.strftime("%Y-%m-%d %H:%M:%S")
        rem_str = str(timedelta(seconds=int(remaining)))
    else:
        eta_str = "unknown"
        rem_str = "unknown"
    return (
        f"Progress: {done}/{total} ({pct:.1f}%) - "
        f"remaining ~{rem_str}, expected end {eta_str}"
    )


def iterate_text_file(tracker: StatusTracker, dry_run: bool = True) -> None:
    """Process every QID listed (one per line) in items.txt."""
    with ITEMS_FILE.open(encoding="utf-8") as fh:
        qids = [line.strip() for line in fh if line.strip()]

    total = len(qids)
    start_time = datetime.now()
    for i, qid in enumerate(qids):
        pywikibot.output(_format_progress(i, total, start_time))
        process_item(qid, tracker, dry_run=dry_run)

    pywikibot.output(_format_progress(total, total, start_time))


def remove_processed_items_from_items_file(tracker: StatusTracker) -> int:
    """Remove already-processed QIDs from ITEMS_FILE and return removed count."""
    if not ITEMS_FILE.exists():
        pywikibot.warning(f"{ITEMS_FILE} does not exist. No items removed.")
        return 0

    processed_qids = tracker.get_processed_qids()
    if not processed_qids:
        pywikibot.output("No processed QIDs found; leaving ITEMS_FILE unchanged.")
        return 0

    with ITEMS_FILE.open(encoding="utf-8") as fh:
        items = [line.strip() for line in fh if line.strip()]

    remaining_items = [qid for qid in items if qid not in processed_qids]
    removed_count = len(items) - len(remaining_items)
    if removed_count > 0:
        with ITEMS_FILE.open("w", encoding="utf-8") as fh:
            for qid in remaining_items:
                fh.write(f"{qid}\n")

    pywikibot.output(f"Removed {removed_count} processed item(s) from {ITEMS_FILE}.")
    return removed_count


def _lookup_wiki_qid(lang: str) -> str | None:
    """Load the Wikipedia edition QID for this language from cache."""
    cache_file = WIKIPEDIA_EDITIONS_CACHE_FILE
    if cache_file.exists():
        with cache_file.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    parts = line.split("\t")
                    if len(parts) == 2 and parts[1] == lang:
                        return parts[0]
    return None


def _execute_sparql_query(query: str) -> list[str]:
    """Execute a SPARQL query and return list of QIDs."""
    query_object = sparql.SparqlQuery(repo=repo)
    results = query_object.select(query, full_data=False)
    if not results:
        return []
    return [result["item"].replace(wd.BASE_URL, "") for result in results]


def build_missing_article_query(wiki_qid: str, lang: str) -> str:
    """Return a SPARQL query selecting items missing an article on `lang`wiki.

    The query expects `wiki_qid` (Wikidata QID for the Wikipedia edition)
    and `lang` (language code) and returns a query string.
    """
    return f"""
PREFIX schema: <http://schema.org/>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX pr: <http://www.wikidata.org/prop/reference/>
        SELECT DISTINCT ?item WHERE {{
            ?item wdt:P31 wd:Q5 .
            ?item ?some_prop ?statement .
            ?statement prov:wasDerivedFrom ?ref .
            ?ref pr:P143 wd:{wiki_qid} .
            OPTIONAL {{
                ?article schema:about ?item .
                ?article schema:isPartOf <https://{lang}.wikipedia.org/> .
            }}
            FILTER (!BOUND(?article))
        }}
        """


@rate_limit(60)  # 1 call every 60 seconds
def _execute_qlever_query(query: str) -> list[str]:
    """Execute a qlever query and return list of QIDs."""
    try:
        qlever_url = "https://qlever.cs.uni-freiburg.de/api/wikidata"
        response = requests.get(
            qlever_url,
            params={"query": query},
            timeout=300,  # 5 minutes timeout
        )
        response.raise_for_status()

        data = response.json()
        if "results" not in data or "bindings" not in data["results"]:
            return []

        bindings = data["results"]["bindings"]
        qids = []
        for binding in bindings:
            if "item" in binding:
                item_uri = binding["item"]["value"]
                # Extract QID from URI like http://www.wikidata.org/entity/Q123
                qid = item_uri.split("/")[-1]
                if qid.startswith("Q"):
                    qids.append(qid)
        return qids

    except requests.RequestException as e:
        pywikibot.error(f"Error querying qlever: {e}")
        return []
    except (KeyError, ValueError) as e:
        pywikibot.error(f"Error parsing qlever response: {e}")
        return []


def _fetch_and_fill_items_txt_generic(
    lang: str, query_executor, source_name: str, append: bool = False
) -> None:
    """Generic function to fetch QIDs using a strategy pattern.

    Args:
        lang: Language code
        query_executor: Callable that executes the query and returns list of QIDs
        source_name: Name of the source (e.g., 'SPARQL', 'qlever') for logging
        append: If True, keep the existing QIDs in ITEMS_FILE and add the new
            ones (de-duplicated, existing order preserved). If False (default),
            overwrite ITEMS_FILE with only the newly fetched QIDs.
    """
    wiki_qid = _lookup_wiki_qid(lang)
    if not wiki_qid:
        pywikibot.error(f"Could not find QID for language '{lang}' in cache.")
        return

    pywikibot.output(f"Resolved language '{lang}' to QID {wiki_qid}.")

    query = build_missing_article_query(wiki_qid, lang)

    qids = query_executor(query)
    if not qids:
        pywikibot.warning(f"{source_name} query returned no results.")
        return

    pywikibot.output(f"Fetched {len(qids)} QIDs from {source_name}.")

    existing: list[str] = []
    if append and ITEMS_FILE.exists():
        with ITEMS_FILE.open(encoding="utf-8") as fh:
            existing = [line.strip() for line in fh if line.strip()]

    combined = list(existing)
    seen = set(existing)
    added = 0
    for qid in qids:
        if qid in seen:
            continue
        seen.add(qid)
        combined.append(qid)
        added += 1

    with ITEMS_FILE.open("w", encoding="utf-8") as fh:
        for qid in combined:
            fh.write(f"{qid}\n")

    if append:
        pywikibot.output(
            f"Appended {added} new QID(s) to {ITEMS_FILE} "
            f"({len(existing)} existing, {len(combined)} total)."
        )
    else:
        pywikibot.output(f"Wrote {len(combined)} QIDs to {ITEMS_FILE}")


def fetch_and_fill_items_txt(lang: str = "en", append: bool = False) -> None:
    """Fetch QIDs matching the criteria from SPARQL and write them to items.txt.

    Args:
        lang: Language code (e.g., 'en' for English Wikipedia)
        append: If True, add to the existing items.txt instead of overwriting it.
    """
    pywikibot.output(f"Fetching QIDs from SPARQL query for language '{lang}'...")
    _fetch_and_fill_items_txt_generic(
        lang, _execute_sparql_query, "SPARQL", append=append
    )


def fetch_and_fill_items_txt_qlever(lang: str = "en", append: bool = False) -> None:
    """Fetch QIDs matching the criteria using qlever and write them to items.txt.

    Args:
        lang: Language code (e.g., 'en' for English Wikipedia)
        append: If True, add to the existing items.txt instead of overwriting it.
    """
    pywikibot.output(f"Fetching QIDs from qlever for language '{lang}'...")
    _fetch_and_fill_items_txt_generic(
        lang, _execute_qlever_query, "qlever", append=append
    )


def fetch_and_fill_items_txt_qlever_all(langs: list[str] | None = None) -> None:
    """Fetch QIDs via qlever for multiple languages and write a single items.txt.

    The function queries qlever for each language in `langs` (or
    `SUPPORTED_LANGS` if `langs` is None), preserves the language order,
    removes duplicate QIDs (keeps first occurrence), and writes the final
    combined list to `items.txt` once at the end (so the file is not
    cleared between language runs).
    """
    if langs is None:
        langs = SUPPORTED_LANGS

    combined: list[str] = []
    seen: set[str] = set()

    for lang in langs:
        pywikibot.output(f"Fetching QIDs from qlever for language '{lang}'...")

        wiki_qid = _lookup_wiki_qid(lang)
        if not wiki_qid:
            pywikibot.warning(
                f"Could not find QID for language '{lang}' in cache. Skipping."
            )
            continue

        query = build_missing_article_query(wiki_qid, lang)

        try:
            qids = _execute_qlever_query(query)
        except Exception as e:
            pywikibot.error(f"qlever query failed for {lang}: {e}")
            continue

        if not qids:
            pywikibot.warning(f"qlever query returned no results for {lang}.")
            continue

        pywikibot.output(f"Fetched {len(qids)} QIDs from qlever for {lang}.")

        for qid in qids:
            if qid in seen:
                continue
            seen.add(qid)
            combined.append(qid)

    with ITEMS_FILE.open("w", encoding="utf-8") as fh:
        for qid in combined:
            fh.write(f"{qid}\n")

    pywikibot.output(f"Wrote {len(combined)} unique QIDs to {ITEMS_FILE}")


def test():
    # Test URL parsing
    test_urls = [
        # "https://en.wikipedia.org/w/index.php?title=Nenad_Zivkovic_(footballer,_born_2002)&oldid=973360753",
        # "https://hu.wikipedia.org/w/index.php?title=George_Bruce&oldid=18268661",
        # "https://www.wikidata.org/wiki/Q101079706#P2369",
        # "https://ko.wikipedia.org/w/index.php?title=%ED%9B%84%EB%9E%AD%ED%82%A4%EB%B0%B0&oldid=34799705",
        # "https://ko.wikipedia.org/w/index.php?title=후랭키배&oldid=34799705",
        # "https://en.wikiversity.org/wiki/User:Cody_naccarato",
        # "https://ar.wikipedia.org/?oldid=61978517",
        "https://commons.wikimedia.org/wiki/File:M_Shahinoor_Rahman%27s_Photo.jpg",
        "https://en.m.wikipedia.org/wiki/Nigerian_National_Assembly_delegation_from_Anambra",
        "https://upload.wikimedia.org/wikipedia/commons/3/3a/ILuminate_and_Miral_Kotb.jpg",
    ]
    for url in test_urls:
        info = _parse_wikipedia_url(url)
        print(f"URL: {url}\nParsed: {info}\n")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "End 'imported from Wikipedia' references whose source page was "
            "deleted/moved, on items lacking the sitelink."
        )
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="actually edit Wikidata (default: dry-run - no edits, no DB writes)",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help=(
            "refetch items.txt via qlever (all supported languages) before "
            "processing; slow, so run it only occasionally"
        ),
    )
    args = parser.parse_args()

    dry_run = not args.save
    tracker = StatusTracker()

    if args.refresh:
        fetch_and_fill_items_txt_qlever_all()

    if not dry_run:
        # Drop already-processed QIDs from the queue before a real run.
        remove_processed_items_from_items_file(tracker)

    iterate_text_file(tracker=tracker, dry_run=dry_run)


if __name__ == "__main__":
    main()
