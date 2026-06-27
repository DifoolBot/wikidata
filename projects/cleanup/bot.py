"""
bot.py

Pywikibot bot class, generator setup and CLI for the WikidataCleanup bot.

Usage:
  python bot.py [pywikibot options] [bot options]

Bot options:
  -detector:NAME   Activate a specific detector. May be repeated.
                   Names: self_cite, empty_end_time, alias_equals_label,
                           redundant_preferred, expired_preferred, clean_urls,
                           dup_retrieved, merge_same_date_claims,
                           julian_gregorian_dates,
                           wikimedia, aggregator, community, redundant,
                           inferred, obsolete, self_stated_in
                   Default: all detectors.
  -item:QXXX       Process a single item (useful for testing).
  -dry             Detect but do not submit any edits.

Examples:
  python bot.py -item:Q42 -dry
  python bot.py -detector:self_cite -detector:empty_end_time
  python bot.py -sparql:"SELECT ?item WHERE { ?item wdt:P2860 ?item }"
"""

import functools
import sys

import pywikibot
import pywikibot.bot
from cleanup.apply import apply_diffs
from cleanup.detectors import (
    DETECTORS,
    ReferenceClassifier,
    SourceCategoryRules,
    UrlStripRules,
    detect_clean_urls,
    detect_ref_categories,
)
from pywikibot import pagegenerators
from pywikibot.bot import ExistingPageBot, SingleSiteBot

# ==== Constants ==============================================================

TOOL_NAME = "WikidataCleanupBot"
TOOL_PAGE = "User:Difool/WikidataCleanup"
EDIT_SUMMARY_TPL = "Cleanup: {actions} ([[{tool_page}|bot]])"

# All reference-category detector keys handled via the single-pass
# detect_ref_categories(), not through DETECTORS directly.
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
    "wikimedia": "remove imported-from-Wikimedia references",
    "aggregator": "remove aggregator references",
    "community": "remove community references",
    "redundant": "remove redundant references",
    "inferred": "remove inferred references",
    "obsolete": "remove obsolete ID references",
    "self_stated_in": "remove tautological stated-in references",
}

# ==== External data loading (black boxes) ====================================


def load_source_category_rules() -> SourceCategoryRules:
    """
    Load reference source category rules.

    TODO: fetch and parse:
      - User:Difool/reference-source-categories  → aggregator/community/redundant
      - Wikidata SPARQL → obsolete ID properties
      - Wikidata SPARQL → stated-in preferences per property

    For now returns an empty SourceCategoryRules so the classifier handles
    wikimedia/inferred/self_stated_in correctly (those require no external
    data), while aggregator/community/redundant/obsolete fire on nothing.
    """
    return SourceCategoryRules()


def load_url_strip_rules() -> UrlStripRules:
    """
    Load URL strip rules for the clean_urls detector.

    TODO: fetch and parse User:Difool/url_tracking_params.
    For now returns hardcoded defaults only.
    """
    return UrlStripRules()


# ==== Bot class ==============================================================


class WikidataCleanupBot(SingleSiteBot, ExistingPageBot):
    """
    Runs the active detectors against each item and applies all resulting
    diffs in a single wbeditentity call per item.
    """

    use_redirects = False

    def __init__(
        self,
        active_detectors: set[str],
        dry_run: bool,
        classifier: ReferenceClassifier,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.active_detectors = active_detectors
        self.dry_run = dry_run
        self.classifier = classifier
        self.stats = {
            "items_checked": 0,
            "items_changed": 0,
            "diffs_total": 0,
        }

    def treat_page_and_item(self, page, item: pywikibot.ItemPage) -> None:
        """
        Process one item:
          1. Build raw entity dict from the already-fetched pywikibot item.
          2. Run all active detectors against the raw dict.
          3. Apply all diffs in a single editEntity call.
        """
        try:
            item.get()
        except pywikibot.exceptions.IsRedirectPageError:
            return
        except Exception as e:
            pywikibot.error(f"Failed to load {item.id}: {e}")
            return

        self.stats["items_checked"] += 1

        # Build the raw dict the detectors work on. Avoids item.toJSON() on
        # sitelinks (which can be large).
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

        # ── Standard detectors (one function per detector) ────────────────────
        standard_active = self.active_detectors - REF_CATEGORY_DETECTORS
        for detector_id in standard_active:
            detect_fn = DETECTORS.get(detector_id)
            if detect_fn is None:
                continue
            try:
                all_diffs.extend(detect_fn(raw))
            except Exception as e:
                pywikibot.error(f"[{item.id}] detector {detector_id!r} failed: {e}")

        # ── Reference-category detectors (single shared pass) ─────────────────
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
            return

        self.stats["diffs_total"] += len(all_diffs)

        active_labels = sorted(
            {DETECTOR_LABELS.get(d["detector"]) or d["detector"] for d in all_diffs}
        )
        summary = EDIT_SUMMARY_TPL.format(
            actions="; ".join(active_labels),
            tool_page=TOOL_PAGE,
        )

        try:
            changed = apply_diffs(item, all_diffs, summary, self.dry_run)
        except Exception as e:
            pywikibot.error(f"[{item.id}] apply_diffs failed: {e}")
            return

        if changed:
            self.stats["items_changed"] += 1

    def exit(self) -> None:
        pywikibot.output("\n=== WikidataCleanupBot run summary ===")
        pywikibot.output(f"  Items checked  : {self.stats['items_checked']}")
        pywikibot.output(f"  Items changed  : {self.stats['items_changed']}")
        pywikibot.output(f"  Diffs total    : {self.stats['diffs_total']}")
        if self.dry_run:
            pywikibot.output("  (dry run — no edits were submitted)")


# ==== Entry point ============================================================


def main(*args: str) -> None:
    # Build the complete set of available detector ids.
    all_detector_ids = set(DETECTORS.keys()) | REF_CATEGORY_DETECTORS | {"clean_urls"}

    local_args = pywikibot.handle_args(args)
    gen_factory = pagegenerators.GeneratorFactory()

    active_detectors: set[str] = set()
    dry_run = False
    single_item: str | None = None

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
        elif arg.startswith("-item:"):
            single_item = arg[len("-item:") :]
        else:
            gen_factory.handle_arg(arg)

    if not active_detectors:
        active_detectors = all_detector_ids

    # Load external data (black boxes).
    rules = load_source_category_rules()
    url_rules = load_url_strip_rules()
    classifier = ReferenceClassifier(rules)

    # Register clean_urls bound to the fetched url strip rules.
    DETECTORS["clean_urls"] = functools.partial(detect_clean_urls, rules=url_rules)

    site = pywikibot.Site("wikidata", "wikidata")
    repo = site.data_repository()

    if single_item:
        item = pywikibot.ItemPage(repo, single_item)
        gen = pagegenerators.PreloadingGenerator(iter([item]))
    else:
        gen = gen_factory.getCombinedGenerator(preload=True)
        if gen is None:
            pywikibot.bot.suggest_help(missing_generator=True)
            sys.exit(1)
        gen = pagegenerators.PreloadingGenerator(gen)

    pywikibot.output(
        f"Active detectors: {', '.join(sorted(active_detectors))}"
        + (" [DRY RUN]" if dry_run else "")
    )

    bot = WikidataCleanupBot(
        active_detectors=active_detectors,
        dry_run=dry_run,
        classifier=classifier,
        generator=gen,
        site=repo,
    )
    bot.run()


if __name__ == "__main__":
    main()
