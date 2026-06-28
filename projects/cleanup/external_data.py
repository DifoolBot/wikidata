"""
external_data.py

Fetches and parses the external data sources that back the bot's detectors.
All functions return fully constructed black-box objects that the detectors
consume without knowing where the data came from.

Four data sources:
  1. load_url_strip_rules()       — User:Difool/url_tracking_params
  2. load_wikipedia_editions()    — Wikidata:Database_reports/Wikipedia_versions
  3. load_source_category_rules() — User:Difool/reference-source-categories
                                    + SPARQL for obsolete ID properties
                                    + SPARQL for stated-in preferences
"""

from __future__ import annotations

import logging
import pathlib
import pickle
import re
import time

import pywikibot
from pywikibot.data import sparql

from cleanup.detectors import SourceCategoryRules, UrlStripRules, WikipediaEditions

log = logging.getLogger(__name__)

WD_ENTITY_PREFIX = "http://www.wikidata.org/entity/"

# Combined on-disk cache for the three external-data objects, used by debug
# entry points (e.g. call_bot.py) so repeated runs don't re-hit SPARQL and the
# wiki API.  Bump _CACHE_VERSION whenever the shape of the cached rule classes
# changes; delete the file to force a refresh.
_CACHE_FILE = pathlib.Path(__file__).parent / "external_data_cache.pkl"
_CACHE_VERSION = 1
_CACHE_MAX_AGE_SECONDS = 24 * 3600  # 1 day

# ==== Helpers ================================================================


def _sparql(query: str) -> list[dict]:
    """Run a SPARQL query and return the bindings list.

    Uses pywikibot's :class:`SparqlQuery`, which defaults to the Wikidata
    endpoint and supplies a compliant User-Agent and retry handling.
    """
    data = sparql.SparqlQuery().query(query)
    if not data:
        return []
    return data["results"]["bindings"]


def _qid(uri: str) -> str:
    return uri.replace(WD_ENTITY_PREFIX, "")


def _mediawiki_page(title: str) -> str:
    """Fetch the wikitext of a Wikidata wiki page via the API."""
    site = pywikibot.Site("wikidata", "wikidata")
    page = pywikibot.Page(site, title)
    return page.text


# ==== 1. URL strip rules =====================================================


def load_url_strip_rules() -> UrlStripRules:
    """
    Fetch User:Difool/url_tracking_params and parse it into a UrlStripRules
    object.  Falls back to hardcoded defaults on any error.
    """
    try:
        wikitext = _mediawiki_page("User:Difool/url_tracking_params")
        rules = UrlStripRules.from_wiki_text(wikitext)
        log.info(
            "Loaded URL strip rules: %d always, %d recognition",
            len(rules.always),
            len(rules.recognition),
        )
        return rules
    except Exception as e:
        log.warning("Failed to load URL strip rules, using defaults: %s", e)
        return UrlStripRules()


# ==== 2. Wikipedia editions ==================================================


def load_wikipedia_editions() -> WikipediaEditions:
    """
    Fetch the Wikipedia editions SPARQL report and build a WikipediaEditions
    object mapping language code → QID.

    Uses SPARQL rather than parsing the HTML report page, which is more
    reliable and matches what pywikibot already has access to.
    """
    query = """
        SELECT ?item ?lang WHERE {
          ?item wdt:P31 wd:Q10876391 ;
                wdt:P407 ?langItem .
          ?langItem wdt:P424 ?lang .
        }
    """
    try:
        rows = _sparql(query)
        lang_to_qid: dict[str, str] = {}
        for row in rows:
            qid = _qid(row["item"]["value"])
            lang = row["lang"]["value"]
            # First seen wins (same as JS langToQid)
            if lang not in lang_to_qid:
                lang_to_qid[lang] = qid
        log.info("Loaded Wikipedia editions: %d language codes", len(lang_to_qid))
        return WikipediaEditions(lang_to_qid)
    except Exception as e:
        log.warning("Failed to load Wikipedia editions: %s", e)
        return WikipediaEditions()


# ==== 3. Source category rules ===============================================

# ── 3a. Parse reference-source-categories wiki page ─────────────────────────


def _parse_source_category_page(
    wikitext: str,
) -> tuple[set[str], set[str], list[tuple[str, str]]]:
    """
    Parse User:Difool/reference-source-categories wikitext.

    Returns (aggregator_pids, community_pids, redundancy_pairs).

    The page uses {{P|Pxxx}} template syntax for PIDs and standard wikitable
    rows with || separators.  Sections are identified by === headings.

    Section headings (case-insensitive):
      "aggregator sources" → aggregator_pids
      "community sources"  → community_pids
      "redundant sources"  → redundancy_pairs (two PIDs per row)
    """
    aggregator: set[str] = set()
    community: set[str] = set()
    redundant: list[tuple[str, str]] = []

    current_section: str | None = None

    def extract_pids(text: str) -> list[str]:
        """Extract all Pxxx PIDs from a cell's text content."""
        # Match {{P|Pxxx}} template or bare Pxxx
        return re.findall(r"P\d+", text)

    for line in wikitext.splitlines():
        line = line.strip()

        # Section heading
        m = re.match(r"^===+\s*(.+?)\s*===+$", line)
        if m:
            heading = m.group(1).lower()
            if "aggregator" in heading:
                current_section = "aggregator"
            elif "community" in heading:
                current_section = "community"
            elif "redundant" in heading:
                current_section = "redundant"
            else:
                current_section = None
            continue

        if not current_section:
            continue

        # Table data row: starts with |, not |- or |!
        if not line.startswith("|") or line.startswith("|-") or line.startswith("|!"):
            continue

        # Split cells on ||
        cells = [c.strip() for c in line.lstrip("|").split("||")]
        if not cells:
            continue

        if current_section in ("aggregator", "community"):
            pids = extract_pids(cells[0])
            for pid in pids:
                if current_section == "aggregator":
                    aggregator.add(pid)
                else:
                    community.add(pid)

        elif current_section == "redundant":
            if len(cells) < 2:
                continue
            weak_pids = extract_pids(cells[0])
            strong_pids = extract_pids(cells[1])
            if weak_pids and strong_pids:
                redundant.append((weak_pids[0], strong_pids[0]))

    return aggregator, community, redundant


# ── 3b. Obsolete ID properties (MediaWiki search + SPARQL) ──────────────────


def _fetch_obsolete_id_props() -> set[str]:
    """
    Fetch all obsolete external-ID properties, mirroring
    api_fetchAllObsoleteIdProps() from WDCaches.js exactly.

    Step 1: MediaWiki search for properties with P31=Q108951239 or P31=Q60457486.
    Step 2: SPARQL to exclude partially-obsolete properties (those with P518).
    """
    site = pywikibot.Site("wikidata", "wikidata")
    api = site.simple_request(
        action="query",
        list="search",
        srsearch="haswbstatement:P31=Q108951239|P31=Q60457486",
        srnamespace=120,
        srlimit=50,
        srprop="",
        formatversion=2,
    )

    all_pids: list[str] = []
    cont = {}

    while True:
        result = api.submit()
        for hit in result.get("query", {}).get("search", []):
            pid = hit["title"].replace("Property:", "")
            all_pids.append(pid)
        if "continue" not in result:
            break
        # Rebuild request with continuation params
        cont = result["continue"]
        api = site.simple_request(
            action="query",
            list="search",
            srsearch="haswbstatement:P31=Q108951239|P31=Q60457486",
            srnamespace=120,
            srlimit=50,
            srprop="",
            formatversion=2,
            **cont,
        )

    log.info("Found %d obsolete ID property candidates", len(all_pids))

    # Exclude partially-obsolete (have P518 qualifier on the P31 statement)
    partial_query = """
        SELECT DISTINCT ?prop WHERE {
          ?prop p:P31 ?stmt.
          ?stmt ps:P31 wd:Q108951239.
          ?stmt pq:P518 [].
        }
    """
    try:
        partial = {_qid(r["prop"]["value"]) for r in _sparql(partial_query)}
        if partial:
            log.info(
                "Excluding %d partially-obsolete ID props (have P518): %s",
                len(partial),
                ", ".join(sorted(partial)),
            )
    except Exception as e:
        log.warning("Failed to fetch partially-obsolete props: %s", e)
        partial = set()

    return set(all_pids) - partial


# ── 3c. Property stated-in preferences (two SPARQL queries) ─────────────────


def _fetch_stated_in_preferences() -> dict[str, dict]:
    """
    Fetch P9073 (applicable stated in) values and related properties for all
    external-ID properties.  Mirrors api_fetchPropertyStatedInPreferences()
    from WDCaches.js exactly.

    Returns { pid: { preferred: str|None, allowed: set[str], not_allowed: set[str] } }
    """
    stated_in_query = """
        SELECT ?prop ?stated_in ?rank WHERE {
          ?prop wikibase:propertyType wikibase:ExternalId;
                p:P9073 ?stmt.
          ?stmt ps:P9073 ?stated_in;
                wikibase:rank ?rank.
          FILTER(?rank != wikibase:DeprecatedRank)
        }
    """
    related_query = """
        SELECT DISTINCT ?prop ?related WHERE {
          ?prop wikibase:propertyType wikibase:ExternalId.
          {
            ?prop wdt:P9073 ?stated_in.
            { ?stated_in wdt:P98 ?related. }
          } UNION {
            { ?prop wdt:P2378 ?related. }
            UNION { ?prop wdt:P126  ?related. }
            UNION { ?prop wdt:P10726 ?related. }
            UNION { ?prop wdt:P1629 ?related. }
          }
        }
    """
    stated_in_rows = _sparql(stated_in_query)
    related_rows = _sparql(related_query)

    by_prop: dict[str, dict] = {}
    for row in stated_in_rows:
        pid = _qid(row["prop"]["value"])
        stated_in_id = _qid(row["stated_in"]["value"])
        is_preferred = row["rank"]["value"].endswith("PreferredRank")
        by_prop.setdefault(pid, {"preferred": [], "normal": []})
        bucket = "preferred" if is_preferred else "normal"
        by_prop[pid][bucket].append(stated_in_id)

    related_by_prop: dict[str, set[str]] = {}
    for row in related_rows:
        pid = _qid(row["prop"]["value"])
        related_id = _qid(row["related"]["value"])
        related_by_prop.setdefault(pid, set()).add(related_id)

    result: dict[str, dict] = {}
    all_pids = set(by_prop.keys()) | set(related_by_prop.keys())
    for pid in all_pids:
        pref = by_prop.get(pid, {}).get("preferred", [])
        normal = by_prop.get(pid, {}).get("normal", [])
        has_pref = bool(pref)
        preferred = pref[0] if has_pref else (normal[0] if normal else None)
        allowed = set(pref + normal) if has_pref else set(normal)
        not_allowed = {
            qid for qid in related_by_prop.get(pid, set()) if qid not in allowed
        }
        if preferred or not_allowed:
            result[pid] = {
                "preferred": preferred,
                "allowed": allowed,
                "not_allowed": not_allowed,
            }

    log.info("Loaded stated-in preferences for %d properties", len(result))
    return result


# ── 3d. Top-level loader ─────────────────────────────────────────────────────


def load_source_category_rules() -> SourceCategoryRules:
    """
    Build a fully populated SourceCategoryRules from three data sources:
      - User:Difool/reference-source-categories (aggregator/community/redundant)
      - MediaWiki search + SPARQL (obsolete ID properties)
      - SPARQL (stated-in preferences)

    Each source is fetched independently; failures are logged and result in
    empty data for that source rather than aborting the whole load.
    """
    # Aggregator / community / redundant from wiki page
    aggregator: set[str] = set()
    community: set[str] = set()
    redundant: list[tuple[str, str]] = []
    try:
        wikitext = _mediawiki_page("User:Difool/reference-source-categories")
        aggregator, community, redundant = _parse_source_category_page(wikitext)
        log.info(
            "Source category rules: %d aggregator, %d community, %d redundant",
            len(aggregator),
            len(community),
            len(redundant),
        )
    except Exception as e:
        log.warning("Failed to load source category page: %s", e)

    # Obsolete ID properties
    obsolete: set[str] = set()
    try:
        obsolete = _fetch_obsolete_id_props()
        log.info("Loaded %d obsolete ID properties", len(obsolete))
    except Exception as e:
        log.warning("Failed to load obsolete ID properties: %s", e)

    # Stated-in preferences
    stated_in: dict[str, dict] = {}
    try:
        stated_in = _fetch_stated_in_preferences()
    except Exception as e:
        log.warning("Failed to load stated-in preferences: %s", e)

    return SourceCategoryRules(
        aggregator_pids=aggregator,
        community_pids=community,
        redundancy_pairs=redundant,
        stated_in=stated_in,
        obsolete_pids=obsolete,
    )


# ==== 4. Combined loader with optional on-disk cache =========================


def _looks_populated(
    rules: SourceCategoryRules, wp_eds: WikipediaEditions
) -> bool:
    """Heuristic: did the fetch return real data (vs an offline/failed run)?

    Used to avoid persisting an empty result to the cache.
    """
    return bool(
        wp_eds._lang_to_qid
        or rules.aggregator_pids
        or rules.community_pids
        or rules.obsolete_pids
        or rules.stated_in
    )


def load_all(
    *,
    use_cache: bool = False,
    cache_path: pathlib.Path | None = None,
    max_age_seconds: float = _CACHE_MAX_AGE_SECONDS,
) -> tuple[SourceCategoryRules, UrlStripRules, WikipediaEditions]:
    """Load the three external-data objects, optionally via an on-disk cache.

    Returns ``(source_category_rules, url_strip_rules, wikipedia_editions)`` —
    the same trio ``bot.main()`` builds inline.

    When ``use_cache`` is True a fresh-enough pickle is reused instead of
    re-running the SPARQL queries and wiki-page fetches; this keeps repeated
    debug runs from hammering the query service.  The cache is only written
    when the fetch produced non-empty data, so a failed/offline run is not
    persisted.  Delete the cache file (its path is logged) to force a refresh.
    """
    path = pathlib.Path(cache_path) if cache_path else _CACHE_FILE

    if use_cache and path.exists():
        age = time.time() - path.stat().st_mtime
        if age <= max_age_seconds:
            try:
                with path.open("rb") as fh:
                    blob = pickle.load(fh)
                if not isinstance(blob, dict) or blob.get("version") != _CACHE_VERSION:
                    raise ValueError("cache version mismatch")
                rules, url_rules, wp_eds = blob["data"]
                log.info(
                    "Loaded external data from cache %s (age %.0f min)",
                    path,
                    age / 60,
                )
                return rules, url_rules, wp_eds
            except Exception as e:
                log.warning(
                    "Could not read external-data cache %s (%s); refetching",
                    path,
                    e,
                )
        else:
            log.info(
                "External-data cache %s is stale (%.0f min old); refetching",
                path,
                age / 60,
            )

    rules = load_source_category_rules()
    url_rules = load_url_strip_rules()
    wp_eds = load_wikipedia_editions()

    if use_cache and _looks_populated(rules, wp_eds):
        try:
            with path.open("wb") as fh:
                pickle.dump(
                    {"version": _CACHE_VERSION, "data": (rules, url_rules, wp_eds)},
                    fh,
                )
            log.info("Wrote external-data cache %s", path)
        except Exception as e:
            log.warning("Could not write external-data cache %s: %s", path, e)

    return rules, url_rules, wp_eds
