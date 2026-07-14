"""One-off migration of the VIAF database from Firebird (local) to MariaDB
(Toolforge). Mirrors remove_sitelinks/migrate_tracker_db.py.

ToolsDB is only reachable from inside Toolforge, so this runs in two steps:

  1. Locally (Firebird driver installed), export every table to a portable file:
         python -m viaf.migrate_viaf_to_mariadb --export
     -> data/viaf_dump.json

  2. Copy data/viaf_dump.json to Toolforge (scp), then on the bastion (MariaDB
     config in data/viaf_mariadb.json, DB + schema/viaf_mariadb.sql already
     loaded):
         python -m viaf.migrate_viaf_to_mariadb --import

Copies everything except IGNORED (empty). Surrogate IDs (DUPLICATES.ID,
DUPLICATE_LOCAL_AUTH_IDS.ID, PDONE.ID) are carried over so the data is identical;
MariaDB's AUTO_INCREMENT counter advances past them for new rows.

--import DELETEs each target table first, so it is safe to re-run.
"""

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

# Make `viaf` / `shared_lib` importable when run standalone (no PYTHONPATH).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from viaf.paths import DATA_DIR  # noqa: E402

DUMP = DATA_DIR / "viaf_dump.json"
FIREBIRD_CONFIG = DATA_DIR / "viaf.json"
MARIADB_CONFIG = DATA_DIR / "viaf_mariadb.json"

# table -> columns. IGNORED is skipped (empty). IDs are included so surrogate
# keys survive the copy.
TABLES = {
    "ADDED": ["QID", "ADDED_DATE"],
    "ERRORS": ["QID", "MESSAGE", "ERROR_DATE", "RETRY", "NOTE"],
    "NOT_FOUND": ["QID", "PID", "CHECKED_DATE"],
    "DUPLICATES": ["ID", "QID", "DUPLICATE_QID", "LOCAL_AUTH_ID", "VIAF_ID"],
    "DUPLICATE_LOCAL_AUTH_IDS": ["ID", "QID", "LOCAL_AUTH_ID", "VIAF_ID"],
    "CODES": ["PID", "CODE", "DESCRIPTION", "DO_IGNORE", "IS_EMPTY"],
    "PDONE": ["ID", "PID", "CHECKED", "ADDED", "NOT_FOUND", "DONE_DATE"],
}


def _cell(value):
    """Make a Firebird value JSON- and MariaDB-friendly."""
    if isinstance(value, bool):
        return int(value)  # BOOLEAN -> 0/1 for TINYINT
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")  # drop microseconds
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return value


def export() -> None:
    from shared_lib.database_handler_firebird import FirebirdDatabaseHandler

    handler = FirebirdDatabaseHandler(FIREBIRD_CONFIG)
    dump: dict[str, list[list]] = {}
    for table, cols in TABLES.items():
        rows = handler.execute_query(f"SELECT {', '.join(cols)} FROM {table}")
        dump[table] = [[_cell(v) for v in row] for row in rows]
        print(f"Read {len(dump[table])} rows from {table}")

    DUMP.write_text(json.dumps(dump, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Exported to {DUMP}")


def import_(batch_size: int = 5000) -> None:
    from shared_lib.database_handler_mariadb import MariaDbDatabaseHandler

    handler = MariaDbDatabaseHandler(MARIADB_CONFIG)
    dump = json.loads(DUMP.read_text(encoding="utf-8"))

    conn = handler.get_connection()
    try:
        cur = conn.cursor()
        for table, cols in TABLES.items():
            rows = [tuple(r) for r in dump.get(table, [])]
            cur.execute(f"DELETE FROM {table}")  # clear -> re-runnable
            placeholders = ", ".join(["%s"] * len(cols))
            sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
            for i in range(0, len(rows), batch_size):
                cur.executemany(sql, rows[i : i + batch_size])
            conn.commit()
            print(f"Imported {len(rows)} rows into {table}")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--export", action="store_true", help="Firebird -> data/viaf_dump.json"
    )
    group.add_argument(
        "--import",
        dest="do_import",
        action="store_true",
        help="data/viaf_dump.json -> MariaDB",
    )
    args = parser.parse_args()

    if args.export:
        export()
    else:
        import_()


if __name__ == "__main__":
    main()
