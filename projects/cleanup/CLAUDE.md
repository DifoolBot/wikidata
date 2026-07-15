# WikidataCleanup Bot

Python pywikibot bot mirroring User:Difool/WikidataCleanup.js for autonomous Wikidata cleanup at scale.

## File structure
- `detectors.py` — pure detection logic, no pywikibot dependency, operates on wbgetentities JSON dicts
- `apply.py` — builds a single wbeditentity payload from all diffs, one API call per item
- `bot.py` — pywikibot bot class, CLI, orchestration
- `external_data.py` — fetches url_tracking_params, wikipedia editions, source category rules (SPARQL + wiki pages)
- `generators.py` — SPARQL generators per detector group for Toolforge
- `database.py` — MariaDB/SQLite tracker; DatabaseHandler base + WikidataCleanupTracker subclass

## Key conventions
- Detectors return list[dict] with "action", "detector", and action-specific keys
- All diffs from all detectors are merged into one editEntity call in apply.py
- Hidden diffs (d["_hidden"] = True) are not shown in edit summaries
- External-data detectors registered via functools.partial in bot.py main()
- Ref-category detectors (wikimedia/aggregator/etc) run via detect_ref_categories() single pass
- Tests use plain dict fixtures matching wbgetentities JSON; SQLite for database tests

## Remaining work
- removeRedundantOccupation (P279 BFS traversal)
- removeRedundantAwards (P31 BFS + deprecate-vs-remove)
- Dry-run testing against real Wikidata items before Toolforge deployment