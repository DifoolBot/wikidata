import json
import random
import re
from enum import Enum
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pywikibot
from database_handler import DatabaseHandler
from pywikibot.data import sparql
from pywikibot.data.api import Request

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd

site = pywikibot.Site("wikidata", "wikidata")
repo = site.data_repository()

edit_group = "10eb4e0209a1"  # "{:x}".format(random.randrange(0, 2**48))

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
EDIT_SUMMARY = "Remove {lang} Wikipedia references for deleted/missing pages"

WIKIPEDIA_EDITIONS_CACHE_FILE = Path(__file__).parent / "wikipedia_editions_cache.txt"


# ---------------------------------------------------------------------------
# Database tracker
# ---------------------------------------------------------------------------


class FirebirdStatusTracker(DatabaseHandler):

    def __init__(self):
        file_path = Path(__file__).parent / "remove_sitelinks.json"
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
        self.execute_procedure(
            "UPDATE OR INSERT INTO qids (qid, status, error_msg) VALUES (?, ?, ?)",
            (qid, "failed", str(error)),
        )


# ---------------------------------------------------------------------------
# Wikipedia-editions QID map  (lang code -> QID, lazy-loaded once)
# ---------------------------------------------------------------------------

_wikipedia_editions: dict[str, str] = {}
_wikipedia_editions_loaded = False


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

    # Cache miss - query Wikidata
    query_object = sparql.SparqlQuery(repo=repo)
    query = """
    SELECT ?edition ?lang WHERE {
      ?edition wdt:P31 wd:Q10876391 ;
               wdt:P407 ?langItem .
      ?langItem wdt:P424 ?lang .
    }
    """
    results = query_object.select(query, full_data=False)
    if not results:
        pywikibot.warning("SPARQL query returned no results.")
        return

    for row in results:
        qid = row["edition"].replace(wd.BASE_URL, "")
        _wikipedia_editions[qid] = row["lang"]

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
    NEVER_EXISTED = "never_existed"


def get_page_status(title: str, lang: str) -> PageStatus:
    """Return the current status of a Wikipedia page."""
    wiki_site = pywikibot.Site(lang, "wikipedia")
    page = pywikibot.Page(wiki_site, title)

    if page.exists():
        return PageStatus.REDIRECT if page.isRedirectPage() else PageStatus.EXISTS

    # Not live - inspect the deletion log (newest entry first)
    log_entries = list(wiki_site.logevents(logtype="delete", page=page))
    if not log_entries:
        return PageStatus.NEVER_EXISTED

    for entry in log_entries:
        if entry.action() == "delete":
            return PageStatus.DELETED
        if entry.action() == "restore":
            return PageStatus.RESTORED

    return PageStatus.NEVER_EXISTED


def _parse_wikipedia_url(url: str) -> dict[str, str] | None:
    """
    Parse a Wikipedia URL and return {"language": ..., "title": ...}, or None
    if the URL is not a recognised Wikipedia article URL.

    Handles two URL formats:
      - /wiki/Andrew_Madoff
      - /w/index.php?title=Andrew_Madoff&oldid=...
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""

    # log the url to a file
    logfilePath = Path(__file__).parent / "url_log.txt"
    with open(logfilePath, "a", encoding="utf-8") as f:
        f.write(url + "\n")

    m = re.match(r"^(?:www\.)?([a-z\-]+)\.([a-z]+(?:\.[a-z]+)?)$", host)
    if not m:
        return None

    lang, project = m.group(1), m.group(2).split(".")[0]
    if lang == "wikidata" or project != "wikipedia":
        return None

    params = parse_qs(parsed.query)
    if "title" in params:
        title = params["title"][0].replace("_", " ")
    elif parsed.path.startswith("/wiki/"):
        title = parsed.path[len("/wiki/") :].replace("_", " ")
    else:
        return None

    return {"language": lang, "title": title}


# def _page_title_from_url(url: str) -> str | None:
#     """Return the article title from a Wikipedia /wiki/<title> URL."""
#     m = re.match(r"^/wiki/(.+)$", urlparse(url).path)
#     return m.group(1).replace("_", " ") if m else None


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


def _analyze_source(source: dict, sitelinks: dict) -> dict:
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
    }

    for qid in _source_get_qids(source, wd.PID_IMPORTED_FROM_WIKIMEDIA_PROJECT):
        lang = _wikipedia_editions.get(qid)
        if not lang:
            continue
        result["imported_from_qid"] = qid
        if result["language"] is None:
            result["language"] = lang
        if result["language"] != lang:
            raise ValueError(
                f"Multiple languages detected in one source: {result['language']} and {lang}"
            )
        if f"{lang}wiki" not in sitelinks:
            result["has_missing_sitelink"] = True

    for url in _source_get_urls(source, wd.PID_WIKIMEDIA_IMPORT_URL):
        info = _parse_wikipedia_url(url)
        if not info:
            raise ValueError(f"Unrecognized URL format: {url}")
        lang = info["language"]
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

    return result


def _get_ref_hash(source: dict) -> str | None:
    """Return the hash of the first reference claim found in *source*."""
    for claims in source.values():
        for claim in claims:
            return claim.hash
    return None


def collect_wikipedia_refs(item: pywikibot.ItemPage) -> dict[str, list[dict]]:
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
                analysis = _analyze_source(source, sitelinks)
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


def find_title_from_sources(lang: str, entries: list[dict]) -> str | None:
    titles = set()
    """Extract a page title directly from import-URL claims in the sources."""
    for entry in entries:
        for url in _source_get_urls(entry["source"], wd.PID_WIKIMEDIA_IMPORT_URL):
            info = _parse_wikipedia_url(url)
            if not info:
                raise ValueError(f"Unrecognized URL format: {url}")
            if info["language"] != lang:
                raise ValueError(
                    f"URL language mismatch: expected '{lang}', got '{info['language']}' in URL {url}"
                )
            title = info["title"]
            if title:
                titles.add(title)
    if len(titles) > 1:
        raise ValueError(
            f"Multiple distinct titles found in sources for {lang}: {titles}"
        )
    if titles:
        return titles.pop()
    return None


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

        # Keep only the last revision of each consecutive same-user run
        candidates = [
            rev
            for i, rev in enumerate(revisions)
            if i == len(revisions) - 1 or revisions[i + 1]["user"] != rev["user"]
        ]

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

        snapshot = json.loads(item.getOldVersion(rev["revid"]))
        sitelinks = snapshot.get("sitelinks", {})
        if wiki_key in sitelinks:
            title = sitelinks[wiki_key].get("title")
            if title:
                pywikibot.output(
                    f"  Found '{title}' in rev {rev['revid']} (user: {rev['user']})"
                )
                return title

    return None


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


def remove_wikipedia_refs_for_lang(
    page: cwd.WikiDataPage,
    lang_entries: list[dict],
) -> bool:
    """Queue removal of all reference sources in *lang_entries*. Returns True if any were queued."""
    did_something = False
    for entry in lang_entries:
        ref_hash = _get_ref_hash(entry["source"])
        if ref_hash:
            page.remove_reference(entry["claim"].snak, ref_hash)
            did_something = True
    return did_something


def process_lang(
    page: cwd.WikiDataPage,
    lang: str,
    lang_entries: list[dict],
    _revision_cache: dict[str, list[dict]],
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

    title = find_title_from_sources(lang, lang_entries)
    if not title:
        pywikibot.output(f"[{lang}] Title not in sources; checking revision history...")
        title = find_title_from_history(item, lang, _revision_cache=_revision_cache)

    if not title:
        pywikibot.output(f"[{lang}] Could not determine original title. Skipping.")
        return False

    pywikibot.output(f"[{lang}] Recovered title: '{title}'")

    status = get_page_status(title, lang)
    if status != PageStatus.DELETED:
        pywikibot.output(
            f"[{lang}] '{title}' on {lang}.wikipedia has status {status.name} - skipping."
        )
        return False

    pywikibot.output(f"[{lang}] '{title}' is deleted on {lang}.wikipedia.")
    return remove_wikipedia_refs_for_lang(page, lang_entries)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def process_item(
    qid: str,
    tracker: FirebirdStatusTracker,
    dry_run: bool = True,
) -> None:
    """Fetch a Wikidata item and run the full cleanup pipeline."""
    if tracker.is_processed(qid):
        pywikibot.output(f"Already processed {qid}, skipping.")
        return

    pywikibot.output(f"\n{'='*60}\nProcessing {qid}  (dry_run={dry_run})\n{'='*60}")
    _load_wikipedia_editions()

    try:
        item = pywikibot.ItemPage(repo, qid)
        item.get()

        wp_refs = collect_wikipedia_refs(item)
        if not wp_refs:
            pywikibot.output("No Wikipedia references with missing sitelinks found.")
            tracker.mark_success(qid, "Nothing to do")
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
            if process_lang(page, lang, wp_refs[lang], _revision_cache=revision_cache):
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


def iterate_text_file(tracker: FirebirdStatusTracker, dry_run: bool = True) -> None:
    """Process every QID listed (one per line) in items.txt."""
    items_file = Path(__file__).parent / "items.txt"
    with items_file.open(encoding="utf-8") as fh:
        for line in fh:
            qid = line.strip()
            if qid:
                process_item(qid, tracker, dry_run=dry_run)


def test():
    # Test URL parsing
    test_urls = [
        "https://en.wikipedia.org/w/index.php?title=Nenad_Zivkovic_(footballer,_born_2002)&oldid=973360753",
        "https://hu.wikipedia.org/w/index.php?title=George_Bruce&oldid=18268661",
        "https://www.wikidata.org/wiki/Q101079706#P2369",
        "https://ko.wikipedia.org/w/index.php?title=%ED%9B%84%EB%9E%AD%ED%82%A4%EB%B0%B0&oldid=34799705",
        "https://ko.wikipedia.org/w/index.php?title=후랭키배&oldid=34799705",
    ]
    for url in test_urls:
        info = _parse_wikipedia_url(url)
        print(f"URL: {url}\nParsed: {info}\n")


def main():
    # process_item("Q100408447", dry_run=True, ) # try 1
    # process_item("Q100418518", dry_run=True, )  # try 2
    # process_item("Q100226976", dry_run=True, )  # try 3 - permalink
    # process_item(
    #    "Q100534439", tracker=FirebirdStatusTracker(), dry_run=True
    # )  # try 4 - remove
    iterate_text_file(tracker=FirebirdStatusTracker(), dry_run=False)
    # test()
    # Q100226976 - permalink

    # print(get_page_status("Albert Einstein", "en"))
    # print(
    #     _parse_wikipedia_url(
    #         "https://en.wikipedia.org/wiki/Clint_Eastwood#Spiritual_beliefs"
    #     )
    # )


if __name__ == "__main__":
    main()
