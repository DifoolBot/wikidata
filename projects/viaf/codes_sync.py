"""Materialize the processing order + skip list into the CODES table.

viaf_config.yaml stays the editable source: call_viaf computes the full order
(prioritised sources first, then the rest) and calls push_order() so CODES
mirrors it. The bot and the status webservice then read that single place.

Uses only portable SQL (TRUE/FALSE/NULL literals and '?' placeholders), so it
works through either reporting backend's execute_procedure.
"""

from collections.abc import Iterable


def push_order(report, ordered_pids: list[str], ignore: Iterable[str]) -> None:
    """Write the processing order and skip flags into CODES.

    ``ordered_pids`` are the active sources in processing order (their index
    becomes SORT_ORDER); ``ignore`` are the skipped PIDs (DO_IGNORE = TRUE).
    Rows not covered are reset (SORT_ORDER NULL, DO_IGNORE FALSE).
    """
    report.execute_procedure("UPDATE CODES SET SORT_ORDER = NULL, DO_IGNORE = FALSE")
    for position, pid in enumerate(ordered_pids):
        report.execute_procedure(
            "UPDATE CODES SET SORT_ORDER = ? WHERE PID = ?", (position, pid)
        )
    for pid in ignore:
        report.execute_procedure(
            "UPDATE CODES SET DO_IGNORE = TRUE WHERE PID = ?", (pid,)
        )


def sync_descriptions(
    report, pids: Iterable[str], dry_run: bool = False
) -> list[tuple[str, str, str]]:
    """Refresh CODES.DESCRIPTION from each property's English label on Wikidata.

    Returns the (pid, old, new) rows that changed - or that would change, with
    *dry_run*. Property labels move rarely (a rename like P271 'CiNii Books
    author ID' -> 'NACSIS-CAT author ID'), so callers should do this
    occasionally, not on every run: it costs one API call per source.

    Only CODES is touched. AuthoritySource.description stays as written in the
    code, because it also heads the wiki reports and their edit summaries.
    """
    import pywikibot as pwb

    from shared_lib.wikidata_site import REPO

    current = {
        pid: (desc or "").strip()
        for pid, desc in report.execute_query("SELECT PID, DESCRIPTION FROM CODES")
    }
    changed: list[tuple[str, str, str]] = []
    for pid in pids:
        try:
            labels = pwb.PropertyPage(REPO, pid).get().get("labels", {})
        except Exception as e:
            pwb.warning(f"Could not read the label of {pid}: {e}")
            continue
        # 'mul' is Wikidata's language-agnostic label, for names that read the
        # same in every language; a property carrying only that has no 'en'.
        label = labels.get("en") or labels.get("mul")
        if not label or current.get(pid) == label:
            continue
        if not dry_run:
            report.execute_procedure(
                "UPDATE CODES SET DESCRIPTION = ? WHERE PID = ?", (label, pid)
            )
        changed.append((pid, current.get(pid, ""), label))
    return changed


def main() -> None:
    """Sync viaf_config.yaml's order + skips into CODES, without running the bot.

    Run from the repo root; the script puts projects/ on sys.path itself:
        python projects/viaf/codes_sync.py                        # local (Firebird)
        WD_DB_BACKEND=mariadb python projects/viaf/codes_sync.py   # Toolforge (MariaDB)
    (`python -m viaf.codes_sync` also works, but only with PYTHONPATH=projects set.)

    Add --descriptions to also refresh CODES.DESCRIPTION from the property labels
    on Wikidata. The bot does that by itself every DESCRIPTION_SYNC_DAYS; this is
    for when you don't want to wait. Add --dry-run to see what would change.
    """
    import argparse
    import os
    import sys
    from datetime import date
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    parser = argparse.ArgumentParser(description="Sync viaf_config.yaml into CODES.")
    parser.add_argument(
        "--descriptions",
        action="store_true",
        help="also refresh CODES.DESCRIPTION from Wikidata property labels",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="with --descriptions: report the differences without writing",
    )
    args = parser.parse_args()

    from viaf.authority_sources import AuthoritySources
    from viaf.viaf_config import load_config, order_pids

    config = load_config()
    ignore = set(config.ignore)
    sources = AuthoritySources()
    active = [pid for pid in sources.all_pids() if pid not in ignore]
    ordered = order_pids(active, config.order)

    if os.environ.get("WD_DB_BACKEND", "").lower() == "mariadb":
        from viaf.mariadb_viaf_reporting import MariaDbViafReporting as Reporting
    else:
        from viaf.firebird_viaf_reporting import FirebirdViafReporting as Reporting

    report = Reporting()
    push_order(report, ordered, ignore)
    print(f"Synced {len(ordered)} sources into CODES ({len(ignore)} ignored).")

    if not args.descriptions:
        return
    changed = sync_descriptions(report, sources.all_pids(), dry_run=args.dry_run)
    for pid, old, new in changed:
        print(f"  {pid}: {old!r} -> {new!r}")
    if args.dry_run:
        print(f"--dry-run: {len(changed)} description(s) would change.")
        return
    report.set_descriptions_synced(date.today())
    print(f"Synced descriptions from Wikidata; {len(changed)} changed.")


if __name__ == "__main__":
    main()
