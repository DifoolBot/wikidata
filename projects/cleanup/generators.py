"""
generators.py

SPARQL-based item generators for Toolforge deployment.  Each function returns
a pywikibot generator that yields ItemPage objects likely to need the
corresponding detector.

Design principles:
  - Queries are conservative: they over-select rather than under-select.
    The detector itself is the authoritative filter; the generator just
    narrows the search space to avoid scanning all of Wikidata.
  - Each query is limited to a manageable batch size via LIMIT.
    For continuous operation on Toolforge, call the generator repeatedly
    with an OFFSET or use a Wikidata Query Service cursor.
  - All generators accept an optional `limit` parameter (default 500).
    Set to None to retrieve all matching items (use with care).

Usage in bot.py:
    from generators import generator_for_detectors
    gen = generator_for_detectors(active_detectors, repo, limit=1000)
"""

from __future__ import annotations

import logging
from typing import Generator, Iterator

import pywikibot
from pywikibot import pagegenerators
from pywikibot.site import DataSite

log = logging.getLogger(__name__)

# ==== SPARQL helper ==========================================================

def _sparql_generator(
    query: str,
    repo: DataSite,
) -> Iterator[pywikibot.ItemPage]:
    """Yield ItemPage objects from a SPARQL SELECT ?item query."""
    return pagegenerators.WikidataSPARQLPageGenerator(
        query,
        site=repo,
    )


# ==== Per-detector-group SPARQL queries ======================================

# Each query selects ?item and should return a manageable set.
# Queries use SERVICE wikibase:label only when needed for filtering;
# labels are fetched by the bot itself via item.get().

QUERIES: dict[str, str] = {

    # ── self_cite ─────────────────────────────────────────────────────────────
    # Items that cite themselves via P2860.
    "self_cite": """
        SELECT DISTINCT ?item WHERE {
          ?item wdt:P2860 ?item .
        }
        LIMIT {limit}
    """,

    # ── empty_end_time ────────────────────────────────────────────────────────
    # Items that have any claim with a novalue P582 qualifier.
    # Note: wikibase:novalue is used in SPARQL for novalue snaks.
    "empty_end_time": """
        SELECT DISTINCT ?item WHERE {
          ?item ?p ?statement .
          ?statement pq:P582 wikibase:novalue .
        }
        LIMIT {limit}
    """,

    # ── alias_equals_label ────────────────────────────────────────────────────
    # Items with at least one alias — the detector filters for equality.
    # Narrowing further in SPARQL is difficult without label service tricks,
    # so we select items with aliases and let the detector do the comparison.
    # Restrict to items modified recently to keep the set manageable.
    "alias_equals_label": """
        SELECT DISTINCT ?item WHERE {
          ?item schema:dateModified ?modified .
          FILTER(?modified > "2020-01-01T00:00:00Z"^^xsd:dateTime)
          ?item skos:altLabel ?alias .
        }
        LIMIT {limit}
    """,

    # ── redundant_preferred ───────────────────────────────────────────────────
    # Items with at least two preferred-rank claims on the same property.
    "redundant_preferred": """
        SELECT DISTINCT ?item WHERE {
          ?item ?p ?s1 .
          ?s1 wikibase:rank wikibase:PreferredRank .
          ?item ?p ?s2 .
          ?s2 wikibase:rank wikibase:PreferredRank .
          FILTER(?s1 != ?s2)
        }
        LIMIT {limit}
    """,

    # ── expired_preferred ────────────────────────────────────────────────────
    # Items with a preferred-rank claim that has a P582 (end time) qualifier.
    "expired_preferred": """
        SELECT DISTINCT ?item WHERE {
          ?item ?p ?statement .
          ?statement wikibase:rank wikibase:PreferredRank ;
                     pq:P582 ?endTime .
          FILTER(?endTime < NOW())
        }
        LIMIT {limit}
    """,

    # ── dup_retrieved ────────────────────────────────────────────────────────
    # Items with statements that have more than one reference — potential dups.
    # The detector itself checks for actual duplicates.
    "dup_retrieved": """
        SELECT DISTINCT ?item WHERE {
          ?item ?p ?statement .
          ?statement prov:wasDerivedFrom ?ref1 .
          ?statement prov:wasDerivedFrom ?ref2 .
          FILTER(?ref1 != ?ref2)
        }
        LIMIT {limit}
    """,

    # ── merge_same_date_claims ────────────────────────────────────────────────
    # Items with more than one date-of-birth or date-of-death claim.
    "merge_same_date_claims": """
        SELECT DISTINCT ?item WHERE {
          {
            ?item p:P569 ?s1 ; p:P569 ?s2 .
            FILTER(?s1 != ?s2)
          } UNION {
            ?item p:P570 ?s1 ; p:P570 ?s2 .
            FILTER(?s1 != ?s2)
          }
        }
        LIMIT {limit}
    """,

    # ── julian_gregorian_dates ────────────────────────────────────────────────
    # Items with both a Julian and Gregorian date claim on the same property.
    "julian_gregorian_dates": """
        SELECT DISTINCT ?item WHERE {
          {
            ?item p:P569 ?s1 ; p:P569 ?s2 .
            ?s1 psv:P569 ?v1 . ?v1 wikibase:timeCalendarModel wd:Q1985786 .
            ?s2 psv:P569 ?v2 . ?v2 wikibase:timeCalendarModel wd:Q1985727 .
          } UNION {
            ?item p:P570 ?s1 ; p:P570 ?s2 .
            ?s1 psv:P570 ?v1 . ?v1 wikibase:timeCalendarModel wd:Q1985786 .
            ?s2 psv:P570 ?v2 . ?v2 wikibase:timeCalendarModel wd:Q1985727 .
          }
        }
        LIMIT {limit}
    """,

    # ── low_precision_dates ───────────────────────────────────────────────────
    # Items with more than one birth or death date at different precisions.
    "low_precision_dates": """
        SELECT DISTINCT ?item WHERE {
          {
            ?item p:P569 ?s1 ; p:P569 ?s2 .
            ?s1 psv:P569 ?v1 . ?v1 wikibase:timePrecision ?p1 .
            ?s2 psv:P569 ?v2 . ?v2 wikibase:timePrecision ?p2 .
            FILTER(?s1 != ?s2 && ?p1 != ?p2)
          } UNION {
            ?item p:P570 ?s1 ; p:P570 ?s2 .
            ?s1 psv:P570 ?v1 . ?v1 wikibase:timePrecision ?p1 .
            ?s2 psv:P570 ?v2 . ?v2 wikibase:timePrecision ?p2 .
            FILTER(?s1 != ?s2 && ?p1 != ?p2)
          }
        }
        LIMIT {limit}
    """,

    # ── normalize_labels ─────────────────────────────────────────────────────
    # Items with labels or descriptions containing characters that need
    # normalisation (non-breaking space, Unicode hyphen).
    # REGEX on label values is supported in SPARQL.
    "normalize_labels": """
        SELECT DISTINCT ?item WHERE {
          ?item rdfs:label ?label .
          FILTER(
            CONTAINS(?label, "\\u2010") ||
            CONTAINS(?label, "\\u00A0")
          )
        }
        LIMIT {limit}
    """,

    # ── add_mul_label ────────────────────────────────────────────────────────
    # Human items (P31=Q5) with en+de+fr labels but no mul label.
    "add_mul_label": """
        SELECT DISTINCT ?item WHERE {
          ?item wdt:P31 wd:Q5 .
          FILTER NOT EXISTS { ?item rdfs:label ?mulLabel .
                              FILTER(LANG(?mulLabel) = "mul") }
          ?item rdfs:label ?enLabel . FILTER(LANG(?enLabel) = "en")
          ?item rdfs:label ?deLabel . FILTER(LANG(?deLabel) = "de")
          ?item rdfs:label ?frLabel . FILTER(LANG(?frLabel) = "fr")
        }
        LIMIT {limit}
    """,

    # ── add_mul_alias ────────────────────────────────────────────────────────
    # Items with aliases in many languages — let the detector check the threshold.
    "add_mul_alias": """
        SELECT DISTINCT ?item WHERE {
          ?item skos:altLabel ?a1, ?a2, ?a3, ?a4, ?a5, ?a6 .
          FILTER(
            LANG(?a1) != "mul" && LANG(?a2) != "mul" &&
            LANG(?a3) != "mul" && LANG(?a4) != "mul" &&
            LANG(?a5) != "mul" && LANG(?a6) != "mul"
          )
        }
        LIMIT {limit}
    """,

    # ── upgrade_precise_date ─────────────────────────────────────────────────
    # Items with one normal-rank and one deprecated-rank date claim.
    "upgrade_precise_date": """
        SELECT DISTINCT ?item WHERE {
          {
            ?item p:P569 ?sNormal ; p:P569 ?sDepr .
            ?sNormal wikibase:rank wikibase:NormalRank .
            ?sDepr   wikibase:rank wikibase:DeprecatedRank .
            FILTER(?sNormal != ?sDepr)
          } UNION {
            ?item p:P570 ?sNormal ; p:P570 ?sDepr .
            ?sNormal wikibase:rank wikibase:NormalRank .
            ?sDepr   wikibase:rank wikibase:DeprecatedRank .
            FILTER(?sNormal != ?sDepr)
          }
        }
        LIMIT {limit}
    """,

    # ── replace_wrong_property ────────────────────────────────────────────────
    # Items with references containing P2699 (URL) — always wrong in a ref.
    "replace_wrong_property": """
        SELECT DISTINCT ?item WHERE {
          ?item ?p ?statement .
          ?statement prov:wasDerivedFrom ?ref .
          ?ref pr:P2699 ?url .
        }
        LIMIT {limit}
    """,

    # ── split_reference_urls ──────────────────────────────────────────────────
    # Items with references containing more than one P854 (reference URL).
    "split_reference_urls": """
        SELECT DISTINCT ?item WHERE {
          ?item ?p ?statement .
          ?statement prov:wasDerivedFrom ?ref .
          ?ref pr:P854 ?url1 ; pr:P854 ?url2 .
          FILTER(?url1 != ?url2)
        }
        LIMIT {limit}
    """,

    # ── merge_wiki_import_refs ────────────────────────────────────────────────
    # Items with references containing P4656 (Wikimedia import URL).
    "merge_wiki_import_refs": """
        SELECT DISTINCT ?item WHERE {
          ?item ?p ?statement .
          ?statement prov:wasDerivedFrom ?ref .
          ?ref pr:P4656 ?url .
        }
        LIMIT {limit}
    """,

    # ── wikimedia / inferred / aggregator / community / redundant / obsolete ──
    # Items with references containing P143 (imported from) or P3452 (inferred).
    # These cover the most common weak reference patterns.
    "wikimedia": """
        SELECT DISTINCT ?item WHERE {
          ?item ?p ?statement .
          ?statement prov:wasDerivedFrom ?ref .
          { ?ref pr:P143 ?edition . }
          UNION
          { ?ref pr:P4656 ?url . }
        }
        LIMIT {limit}
    """,

    "inferred": """
        SELECT DISTINCT ?item WHERE {
          ?item ?p ?statement .
          ?statement prov:wasDerivedFrom ?ref .
          { ?ref pr:P3452 ?val . }
          UNION
          { ?ref pr:P887 ?val . }
          UNION
          { ?ref pr:P11797 ?val . }
        }
        LIMIT {limit}
    """,

    # aggregator, community, redundant, obsolete, self_stated_in:
    # These require knowledge of the specific PIDs (from SourceCategoryRules)
    # so their queries are built dynamically in generator_for_detectors().
    # The fallback is a broad query on all recently-modified items.
}

# Fallback query for detectors whose specific query requires runtime data
# (aggregator/community/redundant/obsolete/self_stated_in) or when no
# specific query exists.
_FALLBACK_QUERY = """
    SELECT DISTINCT ?item WHERE {
      ?item schema:dateModified ?modified .
      FILTER(?modified > "{since}"^^xsd:dateTime)
    }
    ORDER BY DESC(?modified)
    LIMIT {limit}
"""

_RECENT_SINCE = "2020-01-01T00:00:00Z"


def _fallback_query(limit: int) -> str:
    return (
        _FALLBACK_QUERY
        .replace("{since}", _RECENT_SINCE)
        .replace("{limit}", str(limit))
    )


# ==== Dynamic query builders =================================================

def _build_aggregator_query(pids: set[str], limit: int) -> str | None:
    """
    Build a SPARQL query for items with references containing any of the
    given aggregator/community PIDs as external-id snaks.
    Returns None when pids is empty.
    """
    if not pids:
        return None
    pid_values = " ".join(f"pr:{pid}" for pid in sorted(pids))
    return f"""
        SELECT DISTINCT ?item WHERE {{
          ?item ?p ?statement .
          ?statement prov:wasDerivedFrom ?ref .
          VALUES ?refProp {{ {pid_values} }}
          ?ref ?refProp ?val .
        }}
        LIMIT {limit}
    """


# ==== Public interface ========================================================

def generator_for_detectors(
    active_detectors: set[str],
    repo: DataSite,
    limit: int = 500,
    source_rules=None,
) -> Generator[pywikibot.ItemPage, None, None] | None:
    """
    Return a single deduplicated generator covering all active detectors.

    Merges per-detector SPARQL queries into a combined generator using
    pywikibot's DeduplicateGenerator.  Detectors that share a query
    (e.g. all ref-category detectors) contribute one query between them.

    Parameters
    ----------
    active_detectors : set of detector IDs
    repo             : DataSite (pywikibot.Site("wikidata").data_repository())
    limit            : SPARQL LIMIT per query (default 500)
    source_rules     : SourceCategoryRules instance, used to build dynamic
                       queries for aggregator/community/obsolete detectors.
                       Pass None to fall back to the recent-items query.

    Returns None when no applicable queries could be built.
    """
    generators = []
    seen_queries: set[str] = set()

    REF_CAT_DETECTORS = {
        "wikimedia", "aggregator", "community",
        "redundant", "obsolete", "self_stated_in",
    }

    def add_query(query: str) -> None:
        q = query.strip()
        if q not in seen_queries:
            seen_queries.add(q)
            try:
                gen = _sparql_generator(q, repo)
                generators.append(gen)
            except Exception as e:
                log.warning("Failed to build generator for query: %s", e)

    for det in active_detectors:
        if det in REF_CAT_DETECTORS:
            continue  # handled below as a group

        tmpl = QUERIES.get(det)
        if tmpl:
            add_query(tmpl.replace("{limit}", str(limit)))
        else:
            log.debug("No specific query for detector %r, using fallback", det)
            add_query(_fallback_query(limit)
                      .replace("{limit}", str(limit)))

    # Ref-category detectors — one query per flavour
    active_ref_cats = active_detectors & REF_CAT_DETECTORS
    if active_ref_cats:
        # wikimedia / inferred have static queries
        if "wikimedia" in active_ref_cats:
            add_query(QUERIES["wikimedia"].replace("{limit}", str(limit)))
        if "inferred" in active_ref_cats:
            add_query(QUERIES["inferred"].replace("{limit}", str(limit)))

        # aggregator / community / redundant / obsolete need runtime PID data
        dynamic_cats = active_ref_cats & {"aggregator", "community",
                                          "redundant", "obsolete", "self_stated_in"}
        if dynamic_cats and source_rules is not None:
            pids = (
                source_rules.aggregator_pids |
                source_rules.community_pids |
                source_rules.obsolete_pids |
                {wp for wp, sp in source_rules.redundancy_pairs}
            )
            dyn_query = _build_aggregator_query(pids, limit)
            if dyn_query:
                add_query(dyn_query)
            else:
                log.info(
                    "No PIDs available for dynamic ref-cat query, "
                    "using fallback (source category rules may be empty)"
                )
                add_query(_fallback_query(limit))
        elif dynamic_cats:
            # No source rules — use fallback
            add_query(_fallback_query(limit))

    if not generators:
        return None

    # Chain all sub-generators and deduplicate by item ID.
    import itertools

    def _deduplicated(gens):
        seen: set[str] = set()
        for item in itertools.chain.from_iterable(gens):
            item_id = item.id if hasattr(item, "id") else str(item)
            if item_id not in seen:
                seen.add(item_id)
                yield item

    return pagegenerators.PreloadingEntityGenerator(_deduplicated(generators))
