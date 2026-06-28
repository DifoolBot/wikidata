"""
bot.py

Pywikibot bot class, generator setup and CLI for the WikidataCleanup bot.

Usage:
  python bot.py [pywikibot options] [bot options]

Bot options:
  -detector:NAME   Activate a specific detector. May be repeated.
                   Default: all detectors.
  -item:QXXX       Process a single item (useful for testing).
  -dry             Detect but do not submit any edits.
"""

import functools
import logging
import pathlib
import sys

import pywikibot
from pywikibot import pagegenerators
from pywikibot.bot import SingleSiteBot, ExistingPageBot

from cleanup.detectors import (
    DETECTORS,
    SourceCategoryRules,
    ReferenceClassifier,
    UrlStripRules,
    WikipediaEditions,
    detect_clean_urls,
    detect_low_precision_dates,
    detect_obsolete_snaks_in_references,
    detect_merge_wiki_import_refs,
    detect_ref_categories,
)
from cleanup.apply import apply_diffs
from cleanup.database import WikidataCleanupTracker
from cleanup.external_data import (
    load_source_category_rules,
    load_url_strip_rules,
    load_wikipedia_editions,
)
from cleanup.generators import generator_for_detectors

# ==== Constants ==============================================================

TOOL_NAME = "WikidataCleanupBot"
TOOL_PAGE = "User:Difool/WikidataCleanup"
EDIT_SUMMARY_TPL = "Cleanup: {actions} ([[{tool_page}|bot]])"

REF_CATEGORY_DETECTORS = frozenset(
    {
        "wikimedia",
        "aggregator",
        "community",
        "redundant",
        "inferred",
        "obsolete",
        "self_stated_in",
    }
)

DETECTOR_LABELS = {
    "self_cite": "remove self-citation",
    "empty_end_time": "remove empty end time",
    "alias_equals_label": "remove alias=label",
    "redundant_preferred": "downgrade redundant preferred ranks",
    "expired_preferred": "downgrade expired preferred ranks",
    "clean_urls": "clean URLs",
    "dup_retrieved": "remove duplicate references",
    "merge_same_date_claims": "merge same-date claims",
    "julian_gregorian_dates": "remove Julian/Gregorian duplicate dates",
    "low_precision_dates": "remove redundant low-precision dates",
    "obsolete_snaks": "remove obsolete snaks from references",
    "normalize_labels": "normalize labels/descriptions/aliases",
    "add_mul_label": "add mul label",
    "add_mul_alias": "add mul alias",
    "upgrade_precise_date": "upgrade precise date to preferred",
    "replace_wrong_property": "replace wrong property in references",
    "split_reference_urls": "split multiple reference URLs",
    "merge_wiki_import_refs": "merge P4656 into P143 reference",
    "wikimedia": "remove imported-from-Wikimedia references",
    "aggregator": "remove aggregator references",
    "community": "remove community references",
    "redundant": "remove redundant references",
    "inferred": "remove inferred references",
    "obsolete": "remove obsolete ID references",
    "self_stated_in": "remove tautological stated-in references",
}

# ==== Bot class ==============================================================


class WikidataCleanupBot(SingleSiteBot, ExistingPageBot):

    use_redirects = False

    def __init__(
        self,
        active_detectors: set[str],
        dry_run: bool,
        classifier: ReferenceClassifier,
        rules: SourceCategoryRules,
        tracker: WikidataCleanupTracker | None,
        run_id: str,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.active_detectors = active_detectors
        self.dry_run = dry_run
        self.classifier = classifier
        self.rules = rules
        self.tracker = tracker
        self.run_id = run_id
        self.stats = {
            "items_checked": 0,
            "items_changed": 0,
            "items_skipped": 0,
            "diffs_total": 0,
        }

    def treat_page_and_item(self, page, item: pywikibot.ItemPage) -> None:
        try:
            item.get()
        except pywikibot.exceptions.IsRedirectPageError:
            return
        except Exception as e:
            pywikibot.error(f"Failed to load {item.id}: {e}")
            if self.tracker:
                self.tracker.mark_error(item.id, e, self.run_id)
            return

        # Skip items processed successfully in the last 7 days.
        if self.tracker and self.tracker.is_processed(item.id, days=7):
            self.stats["items_skipped"] += 1
            return

        self.stats["items_checked"] += 1

        raw = {
            "id": item.id,
            "claims": {
                pid: [c.toJSON() for c in claims] for pid, claims in item.claims.items()
            },
            "labels": {lang: {"value": v} for lang, v in item.labels.items()},
            "descriptions": {
                lang: {"value": v} for lang, v in item.descriptions.items()
            },
            "aliases": {
                lang: [{"value": v} for v in vals]
                for lang, vals in item.aliases.items()
            },
        }

        all_diffs: list[dict] = []

        # Standard detectors
        standard_active = self.active_detectors - REF_CATEGORY_DETECTORS
        for detector_id in standard_active:
            detect_fn = DETECTORS.get(detector_id)
            if detect_fn is None:
                continue
            try:
                all_diffs.extend(detect_fn(raw))
            except Exception as e:
                pywikibot.error(f"[{item.id}] detector {detector_id!r} failed: {e}")

        # Reference-category detectors (single shared pass)
        ref_cat_active = self.active_detectors & REF_CATEGORY_DETECTORS
        if ref_cat_active:
            try:
                cat_results = detect_ref_categories(
                    raw, ref_cat_active, self.classifier
                )
                for diffs in cat_results.values():
                    all_diffs.extend(diffs)
            except Exception as e:
                pywikibot.error(f"[{item.id}] detect_ref_categories failed: {e}")

        if not all_diffs:
            if self.tracker:
                self.tracker.mark_skipped(item.id, self.run_id)
            return

        self.stats["diffs_total"] += len(all_diffs)

        active_labels = sorted(
            {
                DETECTOR_LABELS.get(d["detector"]) or d["detector"]
                for d in all_diffs
                if not d.get("_hidden")
            }
        )
        summary = EDIT_SUMMARY_TPL.format(
            actions="; ".join(active_labels),
            tool_page=TOOL_PAGE,
        )

        try:
            changed = apply_diffs(item, all_diffs, summary, self.dry_run)
        except Exception as e:
            pywikibot.error(f"[{item.id}] apply_diffs failed: {e}")
            if self.tracker:
                self.tracker.mark_error(item.id, e, self.run_id)
            return

        if changed:
            self.stats["items_changed"] += 1
            if self.tracker:
                self.tracker.mark_changed(
                    item.id,
                    run_id=self.run_id,
                    diffs_count=len(all_diffs),
                    edit_summary=summary,
                )
        else:
            if self.tracker:
                self.tracker.mark_skipped(item.id, self.run_id)

    def exit(self) -> None:
        pywikibot.output("\n=== WikidataCleanupBot run summary ===")
        pywikibot.output(f"  Items checked  : {self.stats['items_checked']}")
        pywikibot.output(f"  Items skipped  : {self.stats['items_skipped']}")
        pywikibot.output(f"  Items changed  : {self.stats['items_changed']}")
        pywikibot.output(f"  Diffs total    : {self.stats['diffs_total']}")
        if self.dry_run:
            pywikibot.output("  (dry run — no edits were submitted)")
        if self.tracker:
            db_summary = self.tracker.summary()
            pywikibot.output("\n  Database totals:")
            for status, count in sorted(db_summary.items()):
                pywikibot.output(f"    {status:10s}: {count:,}")
            self.tracker.close()


# ==== Entry point ============================================================

log = logging.getLogger(__name__)


def main(*args: str) -> None:
    import uuid

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    all_detector_ids = (
        set(DETECTORS.keys())
        | REF_CATEGORY_DETECTORS
        | {
            "clean_urls",
            "low_precision_dates",
            "obsolete_snaks",
            "merge_wiki_import_refs",
        }
    )

    local_args = pywikibot.handle_args(args)
    gen_factory = pagegenerators.GeneratorFactory()

    active_detectors: set[str] = set()
    dry_run = False
    single_item: str | None = None
    no_db = False
    sqlite_path: str | None = None

    for arg in local_args:
        if arg.startswith("-detector:"):
            name = arg[len("-detector:") :]
            if name not in all_detector_ids:
                pywikibot.error(
                    f"Unknown detector {name!r}. "
                    f"Valid: {', '.join(sorted(all_detector_ids))}"
                )
                sys.exit(1)
            active_detectors.add(name)
        elif arg == "-dry":
            dry_run = True
        elif arg == "-no-db":
            no_db = True
        elif arg.startswith("-sqlite:"):
            sqlite_path = arg[len("-sqlite:") :]
        elif arg.startswith("-item:"):
            single_item = arg[len("-item:") :]
        else:
            gen_factory.handle_arg(arg)

    if not active_detectors:
        active_detectors = all_detector_ids

    # Load external data
    rules = load_source_category_rules()
    url_rules = load_url_strip_rules()
    wp_eds = load_wikipedia_editions()
    classifier = ReferenceClassifier(rules)

    # Register detectors requiring external data
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

    # Database tracker
    tracker: WikidataCleanupTracker | None = None
    if not no_db and not dry_run:
        try:
            db_kwargs: dict = {}
            if sqlite_path:
                db_kwargs["db_path"] = pathlib.Path(sqlite_path)
            tracker = WikidataCleanupTracker(**db_kwargs)
            log.info("Database tracker initialised")
        except Exception as e:
            log.warning("Could not connect to database, running without tracker: %s", e)

    run_id = str(uuid.uuid4())
    log.info("Run ID: %s", run_id)

    site = pywikibot.Site("wikidata", "wikidata")
    repo = site.data_repository()

    if single_item:
        item = pywikibot.ItemPage(repo, single_item)
        gen = pagegenerators.PreloadingEntityGenerator(iter([item]))
    else:
        gen = gen_factory.getCombinedGenerator(preload=True)
        if gen is None:
            log.info(
                "No generator specified; building SPARQL generator "
                "for active detectors."
            )
            gen = generator_for_detectors(
                active_detectors,
                repo,
                limit=500,
                source_rules=rules,
            )
        if gen is None:
            pywikibot.error(
                "Could not build a generator. "
                "Specify one with -sparql:, -item:, etc."
            )
            sys.exit(1)
        gen = pagegenerators.PreloadingEntityGenerator(gen)

    pywikibot.output(
        f"Active detectors: {', '.join(sorted(active_detectors))}"
        + (" [DRY RUN]" if dry_run else "")
        + (" [NO DB]" if no_db else "")
    )

    bot = WikidataCleanupBot(
        active_detectors=active_detectors,
        dry_run=dry_run,
        classifier=classifier,
        rules=rules,
        tracker=tracker,
        run_id=run_id,
        generator=gen,
        site=repo,
    )
    bot.run()


if __name__ == "__main__":
    main()
