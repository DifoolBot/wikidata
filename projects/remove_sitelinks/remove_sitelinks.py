import json
import random
import re
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pywikibot
import requests
from database_handler import DatabaseHandler
from pywikibot.data import sparql
from pywikibot.data.api import Request

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
from shared_lib.date_value import Date
from shared_lib.rate_limiter import rate_limit
from shared_lib.wikidata_site import REPO as repo
from shared_lib.wikidata_site import SITE as site

edit_group = "ece1e2aa4e61"  # "{:x}".format(random.randrange(0, 2**48))

# check remove message:
# https://www.wikidata.org/wiki/Q10266249#Q10266249$B9B396CF-EAE9-463E-B8E7-45CEB56D8AF0
# double removed titles:
# Q16231723
# Draft: Q112335988
# NEVER EXISTED: Q100707887 -> moved to draft
# EXISTS: Q9022737 -> I can't find de.wikipedia link in history << father/child
# Kosinsky edits: Q14120514 - language
# NEVER EXISTED: Q56871179 -> should be deleted

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


class FirebirdStatusTracker(DatabaseHandler):

    def __init__(self):
        file_path = DATA_DIR / "remove_sitelinks.json"
        create_script = Path("schemas/sitelinks.sql")
        super().__init__(file_path, create_script)

    def is_processed(self, qid: str) -> bool:
        """Return True if the QID has any existing record (success or failure)."""
        rows = self.execute_query("SELECT status FROM qids WHERE qid = ?", (qid,))
        return bool(rows)

    def mark_success(self, qid: str, summary: str = "") -> None:
        self.execute_procedure(
            "UPDATE OR INSERT INTO qids (qid, status, summary) VALUES (?, ?, ?)",
            (qid, "success", summary),
        )

    def mark_failed(self, qid: str, error: Exception) -> None:
        trimmed_error = str(error)[:255]
        self.execute_procedure(
            "UPDATE OR INSERT INTO qids (qid, status, error_msg) VALUES (?, ?, ?)",
            (qid, "failed", trimmed_error),
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
        self.execute_procedure(
            "UPDATE OR INSERT INTO wikimedia_cats (qid, is_wikimedia_cat) VALUES (?, ?)",
            (qid, 1 if is_wikimedia_cat else 0),
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
    NEVER_EXISTED = "never_existed"


_page_status_cache: dict[tuple[str, str], tuple[PageStatus, str | None]] = {}


@rate_limit(30)  # 1 call every 5 seconds
def _get_page_status(title: str, lang: str) -> tuple[PageStatus, str | None]:
    """Return the current status of a Wikipedia page and deletion date or draft target if applicable.

    Returns a tuple of (status, detail) where detail is either a deletion timestamp
    for deleted pages, a draft target title for moved-to-draft pages, or None.
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
        if action == "move":
            params = getattr(entry, "params", {})
            if isinstance(params, dict):
                target_ns = params.get("target_ns")
                if target_ns == 118:
                    move_date = (
                        str(entry.timestamp()) if hasattr(entry, "timestamp") else None
                    )
                    result = (PageStatus.MOVED_TO_DRAFT, move_date)
                    _page_status_cache[key] = result
                    return result

    result = (PageStatus.NEVER_EXISTED, None)
    _page_status_cache[key] = result
    return result


def get_page_status(title: str, lang: str) -> tuple[PageStatus, str | None]:
    key = (title, lang)
    if key in _page_status_cache:
        return _page_status_cache[key]
    return _get_page_status(title, lang)


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

    def _get_title_from_oldid(_lang: str, _oldid: str) -> str | None:
        key = (_lang, _oldid)
        if page_title_buffer is not None:
            if key not in page_title_buffer:
                page_title_buffer[key] = _get_page_title_from_revision(_lang, _oldid)
            return page_title_buffer[key]
        return _get_page_title_from_revision(_lang, _oldid)

    def _get_title_and_oldid_from_params():
        title = None
        oldid = None
        if "title" in params:
            title = params["title"][0].replace("_", " ")
        if "oldid" in params:
            oldid = params["oldid"][0]
        if not title and not oldid:
            if parsed.path.startswith("/wiki/"):
                if parsed.path.startswith("/wiki/Special:Permalink/"):
                    permalink = parsed.path[len("/wiki/Special:Permalink/") :]
                    # should be a number followed by an optional title, e.g. "973360753" or "973360753/Nenad_Zivkovic_(footballer,_born_2002)"
                    m = re.match(r"^(\d+)(?:/.*)?$", permalink)
                    if not m:
                        raise ValueError(
                            f"Unrecognized Wikipedia permalink format: {url}"
                        )
                    oldid = m.group(1)
                else:
                    title = (
                        parsed.path[len("/wiki/") :].replace("_", " ").replace("_", " ")
                    )
            elif parsed.path.startswith(f"/{lang}-"):
                # language variant like http://zh.wikipedia.org/zh-tw/%E9%AB%98%E7%AB%8B
                title = parsed.path.split("/", 2)[-1].replace("_", " ")

        return title, oldid

    has_invalid_oldid = False
    title, oldid = _get_title_and_oldid_from_params()
    if oldid:
        title = _get_title_from_oldid(lang, oldid)
        if not title:
            # invalid oldid, ignore the URL
            has_invalid_oldid = True

    if not has_invalid_oldid and not title:
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


def is_wikimedia_cat(qid: str, tracker: FirebirdStatusTracker) -> bool:
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
    tracker: FirebirdStatusTracker,
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


def is_user_page_url(lang: str, title: str) -> bool:
    if title.startswith("User:"):
        return True
    if lang == "de" and title.startswith("Benutzer:"):
        return True
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
    tracker: FirebirdStatusTracker,
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
        "has_user_url": False,
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
        if is_user_page_url(lang, title):
            # ignore user page URLs, they don't correspond to missing article sitelinks
            result["has_user_url"] = True
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

    if result["has_user_url"] and not result["import_url"]:
        # user urls don't need a sitelink
        result["has_missing_sitelink"] = False
    return result


def _get_ref_hash(source: dict) -> str | None:
    """Return the hash of the first reference claim found in *source*."""
    for claims in source.values():
        for claim in claims:
            return claim.hash
    return None


def collect_wikipedia_refs(
    item: pywikibot.ItemPage,
    tracker: FirebirdStatusTracker,
    page_title_buffer: dict[tuple[str, str], str | None] | None = None,
) -> dict[str, list[dict]]:
    """
    Scan all non-deprecated claims for sources that point to a Wikipedia edition
    whose sitelink is absent from the item.

    Returns a dict keyed by language code, each value being a list of
    {claim, source, analysis} entries.
    """
    by_lang: dict[str, list[dict]] = {}
    sitelinks = item.sitelinks

    for claim_list in item.claims.values():
        for claim in claim_list:
            if claim.getRank() == "deprecated":
                continue
            for source in claim.sources:
                analysis = _analyze_source(
                    source,
                    sitelinks,
                    page_title_buffer=page_title_buffer,
                    tracker=tracker,
                )
                if not analysis["has_missing_sitelink"]:
                    continue
                lang = analysis["language"] or "unknown"
                by_lang.setdefault(lang, []).append(
                    {"claim": claim, "source": source, "analysis": analysis}
                )

    return by_lang


# ---------------------------------------------------------------------------
# Title recovery
# ---------------------------------------------------------------------------


def find_title_from_sources(
    lang: str,
    entries: list[dict],
    page_title_buffer: dict[tuple[str, str], str | None] | None = None,
) -> str | None:
    titles = set()
    """Extract a page title directly from import-URL claims in the sources."""
    for entry in entries:
        for url in _source_get_urls(entry["source"], wd.PID_WIKIMEDIA_IMPORT_URL):
            info = _parse_wikipedia_url(url, page_title_buffer=page_title_buffer)
            if not info:
                raise ValueError(f"Unrecognized URL format: {url}")
            if info["language"] != lang:
                raise ValueError(
                    f"URL language mismatch: expected '{lang}', got '{info['language']}' in URL {url}"
                )
            title = info["title"]
            if not title:
                continue
            if is_user_page_url(lang, title):
                # ignore user page URLs, they don't correspond to missing article sitelinks
                continue
            titles.add(title)
    if len(titles) > 1:
        raise ValueError(
            f"Multiple distinct titles found in sources for {lang}: {titles}"
        )
    if titles:
        return titles.pop()
    return None


@rate_limit(5)  # 1 call every 5 seconds
def _get_old_version_snapshot(item: pywikibot.ItemPage, revid: int | str) -> dict:
    """Fetch an old revision snapshot from the MediaWiki API with rate limiting."""
    old_version = item.getOldVersion(revid)
    # some can return None, for example Q13407351 due to vandalism
    return json.loads(old_version) if old_version else {}


@rate_limit(10)  # 1 call every 10 seconds
def find_title_from_history(
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


def end_wikipedia_refs_for_lang(
    page: cwd.WikiDataPage, lang_entries: list[dict], end_date: cwd.Date
) -> bool:
    """Queue removal of all reference sources in *lang_entries*. Returns True if any were queued."""
    did_something = False
    for entry in lang_entries:
        ref_hash = _get_ref_hash(entry["source"])
        if ref_hash:
            page.end_reference(entry["claim"].snak, ref_hash, end_date=end_date)
            did_something = True
    return did_something


@rate_limit(10)
def process_lang(
    page: cwd.WikiDataPage,
    lang: str,
    lang_entries: list[dict],
    _revision_cache: dict[str, list[dict]],
    page_title_buffer: dict[tuple[str, str], str | None] | None = None,
) -> bool:
    """
    Full pipeline for one language edition:
      1. Skip if the sitelink already exists.
      2. Recover the original page title from sources or revision history.
      3. Verify the page is deleted on the target Wikipedia.
      4. Queue reference removal.
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

    title = find_title_from_sources(
        lang,
        lang_entries,
        page_title_buffer=page_title_buffer,
    )
    if not title:
        pywikibot.output(f"[{lang}] Title not in sources; checking revision history...")
        title = find_title_from_history(item, lang, _revision_cache=_revision_cache)

    if not title:
        pywikibot.output(f"[{lang}] Could not determine original title. Skipping.")
        return False

    pywikibot.output(f"[{lang}] Recovered title: '{title}'")

    status, deletion_date = get_page_status(title, lang)
    if status != PageStatus.DELETED and status != PageStatus.MOVED_TO_DRAFT:
        raise RuntimeError(
            f"Page '{title}' on {lang}.wikipedia is not deleted (status: {status.name})."
        )

    if not deletion_date:
        raise RuntimeError(f"Deletion date not found for '{title}' on {lang}.wikipedia")

    pywikibot.output(
        f"[{lang}] '{title}' is deleted on {lang}.wikipedia on {deletion_date}."
    )
    deletion_date_obj = None
    dt = datetime.fromisoformat(deletion_date.replace("Z", "+00:00"))
    deletion_date_obj = Date(year=dt.year, month=dt.month, day=dt.day)
    return end_wikipedia_refs_for_lang(page, lang_entries, end_date=deletion_date_obj)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def process_item(
    qid: str,
    tracker: FirebirdStatusTracker,
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
            tracker.mark_success(qid, "No refs found")
            return

        pywikibot.output(f"Languages with stale refs: {sorted(wp_refs.keys())}")

        page = cwd.WikiDataPage(item, test=dry_run)
        langs_done: set[str] = set()

        revision_cache: dict[str, list[dict]] = (
            {}
        )  # lives for this item's lifetime only

        for lang in sorted(wp_refs.keys()):
            if lang not in SUPPORTED_LANGS and lang != "unknown":
                pywikibot.output(f"[{lang}] Not in SUPPORTED_LANGS - skipping.")
                continue
            if process_lang(
                page,
                lang,
                wp_refs[lang],
                _revision_cache=revision_cache,
                page_title_buffer=page_title_buffer,
            ):
                langs_done.add(lang)

        page.summary = EDIT_SUMMARY.format(lang=", ".join(sorted(langs_done)))
        page.edit_group = edit_group
        if page.apply():
            summary = page.used_summary or ""
            if dry_run:
                summary = f"(DRY RUN) {summary}"
            tracker.mark_success(qid, summary)
        else:
            tracker.mark_success(qid, "Nothing done")

    except Exception as e:
        pywikibot.error(f"Error processing {qid}: {e}")
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


def iterate_text_file(tracker: FirebirdStatusTracker, dry_run: bool = True) -> None:
    """Process every QID listed (one per line) in items.txt."""
    with ITEMS_FILE.open(encoding="utf-8") as fh:
        qids = [line.strip() for line in fh if line.strip()]

    total = len(qids)
    start_time = datetime.now()
    for i, qid in enumerate(qids):
        pywikibot.output(_format_progress(i, total, start_time))
        process_item(qid, tracker, dry_run=dry_run)

    pywikibot.output(_format_progress(total, total, start_time))


def remove_processed_items_from_items_file(tracker: FirebirdStatusTracker) -> int:
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
    # Unrecognized Wikipedia URL format: https://ru.wikipedia.org/?oldid=101945374
    # print(_get_page_title_from_revision("ru", 101945374))

    # process_item(
    #     "Q5959278",
    #     tracker=FirebirdStatusTracker(),
    #     dry_run=True,
    # )  # try 1
    # process_item("Q100418518", dry_run=True, )  # try 2
    # process_item("Q100226976", dry_run=True, )  # try 3 - permalink
    # process_item(
    #    "Q100534439", tracker=FirebirdStatusTracker(), dry_run=True
    # )  # try 4 - remove

    # fetch_and_fill_items_txt_qlever_all()
    remove_processed_items_from_items_file(FirebirdStatusTracker())
    iterate_text_file(tracker=FirebirdStatusTracker(), dry_run=False)
    # fetch_and_fill_items_txt_qlever("no", append=True)

    # test()
    # Q100226976 - permalink

    # print(get_page_status("Albert Einstein", "en"))
    # print(
    #     _parse_wikipedia_url(
    #         "https://en.wikipedia.org/wiki/Clint_Eastwood#Spiritual_beliefs"
    #     )
    # )

    # check: Q101468124 - Mike Moradian - English page is deleted, recovered title = Westlake High School (California)
    # check: Q101248584
    # check: Q11500551 - en page is later created
    # check Q115633065 - 50 revisions -> 1 user-run candidates to inspect.


if __name__ == "__main__":
    main()
