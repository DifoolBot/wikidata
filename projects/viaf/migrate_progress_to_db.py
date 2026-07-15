"""One-time import of viaf_progress.json (+ qlever row counts) into STATE.

The bot's progress used to live in projects/viaf/data/viaf_progress.json and the
row counts only in the qlever files. This seeds the STATE table from them so an
in-flight pass keeps its place, then the json file can be deleted.

Run once per database, from the repo root:

    python projects/viaf/migrate_progress_to_db.py                    # Firebird
    WD_DB_BACKEND=mariadb python projects/viaf/migrate_progress_to_db.py   # ToolsDB

TOTAL_ROWS cannot be recovered exactly: the qlever file is truncated to the rows
still to do, so its current length is the *remaining* count. We seed TOTAL_ROWS
with that same number, which makes the status page read 0% done for the rest of
this source; it self-corrects when the next source fetches a fresh file. Pass
--total N if you know the original count and want the progress bar to be right.
"""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from viaf.paths import DATA_DIR

PROGRESS_FILE = DATA_DIR / "viaf_progress.json"


def _count_rows(pid: str) -> int | None:
    """Rows left in this source's qlever file, ignoring the '# pid=' header."""
    path = DATA_DIR / f"qlever_viaf_index_{pid}.txt"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return sum(
            1 for line in fh if line.strip() and not line.startswith("# pid=")
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--total", type=int, help="original qlever row count, if you know it"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="show what would be written"
    )
    args = parser.parse_args()

    if not PROGRESS_FILE.exists():
        print(f"No {PROGRESS_FILE}; nothing to migrate.")
        return
    progress = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))

    current_pid = progress.get("current_pid")
    cooldown = progress.get("cooldown_until")
    cooldown_until = date.fromisoformat(cooldown) if cooldown else None
    if not current_pid:
        print("No current_pid in the progress file; nothing to migrate.")
        return

    remaining = _count_rows(current_pid)
    total = args.total if args.total is not None else remaining

    print(f"current_pid    : {current_pid}")
    print(f"cooldown_until : {cooldown_until}")
    print(f"remaining rows : {remaining}")
    print(f"total rows     : {total}" + ("" if args.total else "  (assumed = remaining)"))
    if args.dry_run:
        print("\n--dry-run: nothing written.")
        return

    if os.environ.get("WD_DB_BACKEND", "").lower() == "mariadb":
        from viaf.mariadb_viaf_reporting import MariaDbViafReporting as Reporting
    else:
        from viaf.firebird_viaf_reporting import FirebirdViafReporting as Reporting

    report = Reporting()
    if total is not None:
        # seeds SESSION_START = today, TOTAL_ROWS and REMAINING_ROWS = total
        report.start_source_session(current_pid, total)
        if remaining is not None and remaining != total:
            report.set_remaining_rows(remaining)
    report.save_progress(current_pid=current_pid, cooldown_until=cooldown_until)

    print(f"\nWritten to STATE. {PROGRESS_FILE.name} can now be deleted.")


if __name__ == "__main__":
    main()
