"""
bot.py

Pywikibot bot class, generator setup and CLI for the WikidataCleanup bot.

Usage:
  python bot.py [pywikibot options] [bot options]

Bot options:
  -detector:NAME   Activate a specific detector. May be repeated.
                   Names: self_cite, empty_end_time, alias_equals_label
                   Default: all detectors in DETECTORS registry.
  -item:QXXX       Process a single item (useful for testing).
  -dry             Detect but do not submit any edits.

Examples:
  python bot.py -item:Q42 -dry
  python bot.py -detector:self_cite -detector:empty_end_time
  python bot.py -sparql:"SELECT ?item WHERE { ?item wdt:P2860 ?item }"
"""

import sys

import pywikibot
import pywikibot.bot
from cleanup.apply import apply_diffs
from cleanup.detectors import DETECTORS
from pywikibot import pagegenerators
from pywikibot.bot import Any, ExistingPageBot, SingleSiteBot, WikidataBot

# ==== Constants ==============================================================

TOOL_NAME = "WikidataCleanupBot"
TOOL_PAGE = "User:Difool/WikidataCleanup"
EDIT_SUMMARY_TPL = "Cleanup: {actions} ([[{tool_page}|bot]])"

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
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.active_detectors = active_detectors
        self.dry_run = dry_run
        self.stats = {
            "items_checked": 0,
            "items_changed": 0,
            "diffs_total": 0,
        }

    def treat_page(self) -> None:
        """
        Process one item:
          1. Fetch the raw entity JSON via the API.
          2. Run all active detectors against the raw JSON.
          3. Apply all diffs in a single editEntity call.
        """
        item = self.current_page
        try:
            item.get()
        except pywikibot.exceptions.IsRedirectPageError:
            return
        except Exception as e:
            pywikibot.error(f"Failed to load {item.id}: {e}")
            return

        self.stats["items_checked"] += 1

        # Fetch raw entity JSON — this is what the detectors work on.
        # item.get() has already populated item._content; toJSON() gives us
        # the same structure as wbgetentities.
        # raw = item.toJSON()
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
        # Run all active detectors and collect diffs.
        all_diffs: list[dict] = []
        for detector_id in self.active_detectors:
            detect_fn = DETECTORS[detector_id]
            try:
                diffs = detect_fn(raw)
                all_diffs.extend(diffs)
            except Exception as e:
                pywikibot.error(f"[{item.id}] detector {detector_id!r} failed: {e}")

        if not all_diffs:
            return

        self.stats["diffs_total"] += len(all_diffs)

        # Build a human-readable action list for the edit summary.
        detector_labels = {
            "self_cite": "remove self-citation",
            "empty_end_time": "remove empty end time",
            "alias_equals_label": "remove alias=label",
        }

        active_labels = sorted(
            {detector_labels.get(d["detector"]) or d["detector"] for d in all_diffs}
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
        """Print run statistics on exit."""
        pywikibot.output("\n=== WikidataCleanupBot run summary ===")
        pywikibot.output(f"  Items checked  : {self.stats['items_checked']}")
        pywikibot.output(f"  Items changed  : {self.stats['items_changed']}")
        pywikibot.output(f"  Diffs total    : {self.stats['diffs_total']}")
        if self.dry_run:
            pywikibot.output("  (dry run — no edits were submitted)")


# ==== Entry point ============================================================


def main(*args: str) -> None:
    all_detector_ids = set(DETECTORS.keys())

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
        generator=gen,
        site=repo,
    )
    bot.run()


def test() -> None:
    """
    Test the bot with a single item and all detectors enabled.
    """
    site = pywikibot.Site("wikidata", "wikidata")
    repo = site.data_repository()
    item = pywikibot.ItemPage(repo, "Q5593")

    bot = WikidataCleanupBot(
        active_detectors=set(DETECTORS.keys()),
        dry_run=True,
        generator=pagegenerators.PreloadingGenerator(iter([item])),
        site=repo,
    )
    bot.run()


if __name__ == "__main__":
    test()
