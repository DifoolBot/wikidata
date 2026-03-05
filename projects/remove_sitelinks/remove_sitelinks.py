import json
import random
import re
from enum import Enum
from pathlib import Path
from urllib.parse import urlparse

import pywikibot
from database_handler import DatabaseHandler
from pywikibot.data import sparql
from pywikibot.data.api import Request

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd

site = pywikibot.Site("wikidata", "wikidata")
repo = site.data_repository()

edit_group = "{:x}".format(random.randrange(0, 2**48))

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

EDIT_SUMMARY = "Remove Wikipedia references for deleted/missing pages {lang}"

# File-based cache for the Wikipedia-editions QID map.
WIKIPEDIA_EDITIONS_CACHE_FILE = Path(__file__).parent / "wikipedia_editions_cache.txt"


class FirebirdStatusTracker(DatabaseHandler):

    def __init__(self):
        file_path = Path(__file__).parent / "remove_sitelinks.json"
        create_script = Path("schemas/sitelinks.sql")
        super().__init__(file_path, create_script)

    def is_processed(self, qid: str) -> bool:
        rows = self.execute_query("SELECT status FROM qids WHERE qid = ?", (qid,))
        if not rows:
            return False
        # For now, we treat any existing record as "processed", regardless of status.
        return True
        # status = rows[0][0]
        # return bool(status == "success")

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


_wikipedia_editions: dict[str, str] = {}
_wikipedia_editions_loaded = False


def _load_wikipedia_editions() -> None:
    global _wikipedia_editions, _wikipedia_editions_loaded
    if _wikipedia_editions_loaded:
        return

    if WIKIPEDIA_EDITIONS_CACHE_FILE.exists():
        with WIKIPEDIA_EDITIONS_CACHE_FILE.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                qid, lang = line.split("\t", 1)
                _wikipedia_editions[qid] = lang
        pywikibot.output(
            f"Loaded {len(_wikipedia_editions)} Wikipedia edition QIDs "
            f"from cache ({WIKIPEDIA_EDITIONS_CACHE_FILE})."
        )
        _wikipedia_editions_loaded = True
        return

    query_object = sparql.SparqlQuery(repo=repo)
    query = """
    SELECT ?edition ?lang WHERE {
      ?edition wdt:P31 wd:Q10876391 ;   # instance of: Wikimedia language edition of Wikipedia
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
        lang = row["lang"]
        _wikipedia_editions[qid] = lang
    pywikibot.output(
        f"Fetched {len(_wikipedia_editions)} Wikipedia edition QIDs via SPARQL."
    )

    if _wikipedia_editions:
        with WIKIPEDIA_EDITIONS_CACHE_FILE.open("w", encoding="utf-8") as fh:
            for qid, lang in sorted(_wikipedia_editions.items()):
                fh.write(f"{qid}\t{lang}\n")
        pywikibot.output(f"Saved editions cache to {WIKIPEDIA_EDITIONS_CACHE_FILE}.")

    _wikipedia_editions_loaded = True


class PageStatus(Enum):
    EXISTS = "exists"
    REDIRECT = "redirect"
    DELETED = "deleted"
    RESTORED = "restored"
    NEVER_EXISTED = "never_existed"


def get_page_status(title: str, lang: str) -> PageStatus:
    """Returns the status of a Wikipedia page."""

    site = pywikibot.Site(lang, "wikipedia")
    page = pywikibot.Page(site, title)

    # Check current page state first
    if page.exists():
        if page.isRedirectPage():
            return PageStatus.REDIRECT
        return PageStatus.EXISTS

    # Page doesn't currently exist — inspect the deletion log
    log_entries = list(site.logevents(logtype="delete", page=page))

    if not log_entries:
        return PageStatus.NEVER_EXISTED

    # Log entries are newest-first
    for entry in log_entries:
        if entry.action() == "delete":
            return PageStatus.DELETED
        if entry.action() == "restore":
            return PageStatus.RESTORED

    return PageStatus.NEVER_EXISTED


def _parse_wikipedia_lang_from_url(url: str) -> str | None:
    """Extract the language code from a Wikipedia URL"""
    host = urlparse(url).hostname or ""
    m = re.match(r"^(?:www\.)?([a-z\-]+)\.([a-z]+(?:\.[a-z]+)?)$", host)
    if not m:
        return None
    lang, project = m.group(1), m.group(2).split(".")[0]
    if lang == "wikidata":
        return None
    if project == "wikipedia":
        return lang
    return None


def _page_title_from_url(url: str) -> str | None:
    """
    Extract the article title from a Wikipedia URL.
    https://en.wikipedia.org/wiki/Albert_Einstein  ->  "Albert Einstein"
    """
    m = re.match(r"^/wiki/(.+)$", urlparse(url).path)
    if m:
        value = m.group(1).replace("_", " ")
        return value

    return None


def _source_get_qids(source: dict, pid: str) -> list[str]:
    """Return all QID targets for *pid* in a source dict."""
    result = []
    for claim in source.get(pid, []):
        target = claim.getTarget()
        if target and hasattr(target, "id"):
            result.append(target.id)
    return result


def _source_get_urls(source: dict, pid: str) -> list[str]:
    """Return all URL string targets for *pid* in a source dict."""
    result = []
    for claim in source.get(pid, []):
        url = claim.getTarget()
        if isinstance(url, str):
            result.append(url)
    return result


def _analyze_source(
    source: dict,
    sitelinks: dict,
) -> dict:
    result = {
        "language": None,
        "has_missing_sitelink": False,
        "imported_from_qid": None,
        "import_url": None,
    }

    for qid in _source_get_qids(source, wd.PID_IMPORTED_FROM_WIKIMEDIA_PROJECT):
        lang = _wikipedia_editions.get(qid)
        if lang:
            result["imported_from_qid"] = qid
            if result["language"] is None:
                result["language"] = lang
            if f"{lang}wiki" not in sitelinks:
                result["has_missing_sitelink"] = True

    for url in _source_get_urls(source, wd.PID_WIKIMEDIA_IMPORT_URL):
        lang = _parse_wikipedia_lang_from_url(url)
        result["import_url"] = url
        if lang:
            if result["language"] is None:
                result["language"] = lang
            if f"{lang}wiki" not in sitelinks:
                result["has_missing_sitelink"] = True

    return result


def collect_wikipedia_refs(
    item: pywikibot.ItemPage,
) -> dict[str, list[dict]]:
    by_lang: dict[str, list[dict]] = {}
    sitelinks = item.sitelinks  # dict: site_key -> SiteLink

    for pid, claim_list in item.claims.items():
        for claim in claim_list:
            if claim.getRank() == "deprecated":
                continue
            for source in claim.sources:
                analysis = _analyze_source(source, sitelinks)
                if not analysis["has_missing_sitelink"]:
                    continue
                lang = analysis["language"] or "unknown"
                by_lang.setdefault(lang, []).append(
                    {
                        "claim": claim,
                        "source": source,
                        "analysis": analysis,
                    }
                )

    return by_lang


def find_title_from_sources(entries: list[dict]) -> str | None:
    for entry in entries:
        source = entry["source"]

        for url in _source_get_urls(source, wd.PID_WIKIMEDIA_IMPORT_URL):
            title = _page_title_from_url(url)
            if title:
                return title

    return None


def find_title_from_history(
    item: pywikibot.ItemPage, lang: str, max_check_count: int = 5
) -> str | None:
    """
    Walk the item's revision history looking for an old sitelink for *lang*wiki.

    Strategy: fetch revisions oldest-first, group consecutive revisions by the
    same user into runs, then inspect only the *newest* revision of each run.
    This minimises getOldVersion() calls while still covering every distinct
    editing session.

    Example (oldest -> newest):
        rev 1  user0   <- run A
        rev 2  user0   <- newest of run A -> inspect
        rev 3  user1   <- run B
        rev 4  user1
        rev 5  user1   <- newest of run B -> inspect
        rev 6  user0   <- run C, newest of run C -> inspect
    """
    wiki_key = f"{lang}wiki"
    pywikibot.output(f"  Searching revision history for '{wiki_key}' sitelink...")

    params = {
        "action": "query",
        "prop": "revisions",
        "titles": item.title(),
        "rvprop": "ids|timestamp|user",
        "rvlimit": "50",
        "rvdir": "newer",  # oldest -> newest
    }
    req = Request(site=site, parameters=params)
    data = req.submit()

    revisions = []
    for _, page in data["query"]["pages"].items():
        revisions = page.get("revisions", [])

    # Keep only the newest revision of each consecutive same-user run.
    candidates = []
    for i, rev in enumerate(revisions):
        is_last = i == len(revisions) - 1
        next_user = revisions[i + 1]["user"] if not is_last else None
        if is_last or next_user != rev["user"]:
            candidates.append(rev)

    pywikibot.output(
        f"  {len(revisions)} revisions -> {len(candidates)} user-run candidates to inspect."
    )

    check_count = 0
    for rev in candidates:
        if check_count >= max_check_count:
            pywikibot.output(
                f"  Reached max check count ({max_check_count}). Stopping."
            )
            break
        check_count += 1
        revid = rev["revid"]

        snapshot = json.loads(item.getOldVersion(revid))
        sitelinks = snapshot.get("sitelinks", {})
        if wiki_key in sitelinks:
            title = sitelinks[wiki_key].get("title")
            if title:
                pywikibot.output(
                    f"  Found '{title}' in rev {revid} (user: {rev['user']})"
                )
                return title

    return None


# def _source_is_for_lang(source: dict, lang: str) -> bool:
#     for qid in _source_get_qids(source, wd.PID_IMPORTED_FROM_WIKIMEDIA_PROJECT):
#         if _wikipedia_editions.get(qid) == lang:
#             return True

#     for url in _source_get_urls(source, wd.PID_WIKIMEDIA_IMPORT_URL):
#         if _parse_wikipedia_lang_from_url(url) == lang:
#             return True

#     return False


def remove_wikipedia_refs_for_lang(
    page: cwd.WikiDataPage,
    lang_entries: list[dict],
) -> bool:

    def get_hash_for_ref(source):
        for pid, ref_list in source.items():
            for ref in ref_list:
                return ref.hash
        return None

    did_something = False
    for entry in lang_entries:
        source = entry["source"]
        claim = entry["claim"]
        ref_hash = get_hash_for_ref(source)
        if ref_hash:
            page.remove_reference(claim.snak, ref_hash)
            did_something = True

    return did_something


def process_lang(page: cwd.WikiDataPage, lang: str, lang_entries: list[dict]) -> bool:
    """
    Full pipeline for one language edition.

    1. Sitelink present -> nothing to do.
    2. Recover the original page title from sources or history.
    3. Check whether the page is deleted on the target Wikipedia.
    4. If deleted, call remove_wikipedia_refs_for_lang().
    """
    item: pywikibot.ItemPage = page.item
    wiki_key = f"{lang}wiki"
    sitelinks = item.sitelinks

    # Step 1 - already linked
    if wiki_key in sitelinks:
        pywikibot.output(
            f"[{lang}] Sitelink present ({sitelinks[wiki_key].canonical_title()}), skipping."
        )
        return False

    pywikibot.output(
        f"[{lang}] No sitelink - investigating {len(lang_entries)} source(s)..."
    )

    # Step 2 - recover title
    title = find_title_from_sources(lang_entries)
    if not title:
        pywikibot.output(f"[{lang}] Title not in sources; checking revision history...")
        title = find_title_from_history(item, lang)

    if not title:
        pywikibot.output(f"[{lang}] Could not determine original title. Skipping.")
        return False

    pywikibot.output(f"[{lang}] Recovered title: '{title}'")

    # Step 3 - check deletion status
    status = get_page_status(title, lang)
    if status != PageStatus.DELETED:
        pywikibot.output(
            f"[{lang}] '{title}' on {lang}.wikipedia - status is {status.name}."
        )
        return False

    pywikibot.output(f"[{lang}] '{title}' is deleted on {lang}.wikipedia.")

    # Step 4 - remove references
    did_something = remove_wikipedia_refs_for_lang(page, lang_entries)
    return did_something


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

        if not item.claims:
            pywikibot.output("No claims found on this item.")
            return

        # Collect sources with missing sitelinks, grouped by language
        wp_refs = collect_wikipedia_refs(item)

        if not wp_refs:
            pywikibot.output("No Wikipedia references with missing sitelinks found.")
            return

        pywikibot.output(f"Languages with stale refs: {sorted(wp_refs.keys())}")

        page = cwd.WikiDataPage(item, test=dry_run)

        langs_done = set()
        for lang in sorted(wp_refs.keys()):
            if lang not in SUPPORTED_LANGS and lang != "unknown":
                pywikibot.output(f"[{lang}] Not in SUPPORTED_LANGS - skipping.")
                continue
            if process_lang(page, lang, wp_refs[lang]):
                langs_done.add(lang)

        page.summary = EDIT_SUMMARY.format(lang=", ".join(sorted(langs_done)))
        if page.apply():
            tracker.mark_success(qid, page.used_summary or "")
        else:
            tracker.mark_success(qid, "Nothing done")
    except Exception as e:
        print(f"Error processing {qid}: {e}")
        tracker.mark_failed(qid, e)


def iterate_text_file(tracker: FirebirdStatusTracker, dry_run: bool = True):

    with open(Path(__file__).parent / "items.txt", "r", encoding="utf-8") as f:
        for line in f:
            qid = line.strip()
            if qid:
                process_item(qid, tracker, dry_run=dry_run)


def main():
    # process_item("Q100408447", dry_run=True, ) # try 1
    # process_item("Q100418518", dry_run=True, )  # try 2
    # process_item("Q100226976", dry_run=True, )  # try 3 - permalink
    # process_item(
    #    "Q100534439", tracker=FirebirdStatusTracker(), dry_run=True
    # )  # try 4 - remove
    iterate_text_file(tracker=FirebirdStatusTracker(), dry_run=True)
    # Q100226976 - permalink

    # print(get_page_status("Albert Einstein", "en"))


if __name__ == "__main__":
    main()
