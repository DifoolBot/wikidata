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


def main() -> None:
    """Sync viaf_config.yaml's order + skips into CODES, without running the bot.

    Run from the repo root; the script puts projects/ on sys.path itself:
        python projects/viaf/codes_sync.py                        # local (Firebird)
        WD_DB_BACKEND=mariadb python projects/viaf/codes_sync.py   # Toolforge (MariaDB)
    (`python -m viaf.codes_sync` also works, but only with PYTHONPATH=projects set.)
    """
    import os
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

    from viaf.authority_sources import AuthoritySources
    from viaf.viaf_config import load_config, order_pids

    config = load_config()
    ignore = set(config.ignore)
    active = [pid for pid in AuthoritySources().all_pids() if pid not in ignore]
    ordered = order_pids(active, config.order)

    if os.environ.get("WD_DB_BACKEND", "").lower() == "mariadb":
        from viaf.mariadb_viaf_reporting import MariaDbViafReporting as Reporting
    else:
        from viaf.firebird_viaf_reporting import FirebirdViafReporting as Reporting

    push_order(Reporting(), ordered, ignore)
    print(f"Synced {len(ordered)} sources into CODES ({len(ignore)} ignored).")


if __name__ == "__main__":
    main()
