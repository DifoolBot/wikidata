"""
call_bot.py

Debug entry point for the WikidataCleanup bot.

Runs the full per-item pipeline (detectors → diffs → payload → optional edit)
against a single Wikidata item, reusing the bot's real
``WikidataCleanupBot.treat_page_and_item`` so there is no logic drift from a
normal run.  Set a breakpoint anywhere in detectors.py / apply.py and step
through exactly one item.

How to use:
  1. Edit the constants in the CONFIG block below (at minimum, ITEM).
  2. Run / debug this file.  In VS Code the bundled "Python Debugger: Current
     File" config works as-is (the .env file puts ``projects`` on PYTHONPATH).
     From a terminal:  ``cd projects && python -m cleanup.call_bot``

Notes:
  - DRY_RUN=True never submits an edit; it builds the payload and logs every
    change it *would* make.  Flip to False to actually edit the live item.
  - LOAD_EXTERNAL_DATA=False skips all SPARQL / wiki-page fetches and runs with
    empty rules — fast, offline-ish iteration.  Detectors that depend on that
    data (clean_urls, low_precision_dates, obsolete_snaks, merge_wiki_import_refs,
    and the ref-category detectors) then behave as if no rules were configured.
    Set it to True for a faithful end-to-end run.
"""

import functools
import logging

import pywikibot

from cleanup.bot import REF_CATEGORY_DETECTORS, WikidataCleanupBot
from cleanup.detectors import (
    DETECTORS,
    ReferenceClassifier,
    SourceCategoryRules,
    UrlStripRules,
    WikipediaEditions,
    detect_clean_urls,
    detect_low_precision_dates,
    detect_merge_wiki_import_refs,
    detect_obsolete_snaks_in_references,
    detect_redundant_ref_url,
)

# ── CONFIG: edit these ───────────────────────────────────────────────────────
ITEM = "Q44228"  # the Wikidata item to debug
DRY_RUN = True  # True = detect only, never submit an edit
LOAD_EXTERNAL_DATA = True  # False = skip SPARQL/wiki fetches (fast)
CACHE_EXTERNAL_DATA = True  # buffer fetched external data to disk between runs
DETECTOR_IDS: set[str] | None = None  # None = all; or e.g. {"self_cite", "clean_urls"}
# ─────────────────────────────────────────────────────────────────────────────

# Q947058: Cleanup: remove aggregator+wikimedia refs; add mul alias; normalize text
# Q5593:   Cleanup: remove wikimedia refs; add mul alias; remove alias=label/mul; replace property
# Q296:    Cleanup: remove wikimedia refs; add mul alias; remove alias=label/mul; split multiple reference URLs
# Q4443694: Cleanup: remove wikimedia refs; downgrade preferred ranks

# test: Q117012, Q188375, Q5591180, Q18684239, Q183439, Q133311104, Q133311104
# precision check: Q133337881


def _build_external_data() -> (
    tuple[SourceCategoryRules, UrlStripRules, WikipediaEditions]
):
    """Either fetch the live external data or return empty (offline) rules.

    With LOAD_EXTERNAL_DATA and CACHE_EXTERNAL_DATA both on, the fetched data
    is buffered to disk so repeated debug runs reuse it instead of re-querying
    SPARQL.  Delete cleanup/external_data_cache.pkl to force a refresh.
    """
    if LOAD_EXTERNAL_DATA:
        from cleanup.external_data import load_all

        return load_all(use_cache=CACHE_EXTERNAL_DATA)
    return SourceCategoryRules(), UrlStripRules(), WikipediaEditions()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    rules, url_rules, wp_eds = _build_external_data()
    classifier = ReferenceClassifier(rules)

    # Register the detectors that need external data (same as bot.main()).
    DETECTORS["clean_urls"] = functools.partial(detect_clean_urls, rules=url_rules)
    DETECTORS["low_precision_dates"] = functools.partial(
        detect_low_precision_dates, classifier=classifier
    )
    DETECTORS["obsolete_snaks"] = functools.partial(
        detect_obsolete_snaks_in_references, rules=rules
    )
    DETECTORS["merge_wiki_import_refs"] = functools.partial(
        detect_merge_wiki_import_refs, wikipedia_editions=wp_eds
    )
    DETECTORS["redundant_ref_url"] = functools.partial(
        detect_redundant_ref_url, rules=url_rules
    )

    all_detector_ids = (
        set(DETECTORS.keys())
        | REF_CATEGORY_DETECTORS
        | {
            "clean_urls",
            "low_precision_dates",
            "obsolete_snaks",
            "merge_wiki_import_refs",
            "redundant_ref_url",
        }
    )
    active = DETECTOR_IDS if DETECTOR_IDS is not None else all_detector_ids

    # Shared, logged-in Wikidata session (same one the bot uses).
    from shared_lib.wikidata_site import REPO as repo

    item = pywikibot.ItemPage(repo, ITEM)

    bot = WikidataCleanupBot(
        active_detectors=active,
        dry_run=DRY_RUN,
        classifier=classifier,
        rules=rules,
        tracker=None,  # no DB tracking when debugging
        run_id="debug",
        generator=iter([]),  # unused: we drive a single item directly
        site=repo,
    )

    pywikibot.output(
        f"Debugging {ITEM} | dry_run={DRY_RUN} | "
        f"external_data={LOAD_EXTERNAL_DATA} | detectors={len(active)}"
    )

    # ↓↓↓ Set a breakpoint here, or inside any detect_* / build_payload ↓↓↓
    bot.treat_page_and_item(None, item)
    bot.exit()


if __name__ == "__main__":
    main()
