"""One-off migration of the remove_sitelinks tracker DB from Firebird (local) to
MariaDB (Toolforge).

ToolsDB is only reachable from inside Toolforge, so this runs in two steps:

  1. Locally (Firebird driver installed), export the tables to a portable file:
         python projects/remove_sitelinks/migrate_tracker_db.py --export
     -> writes data/tracker_dump.json

  2. Copy data/tracker_dump.json to Toolforge (scp), then on the bastion
     (MariaDB config in data/remove_sitelinks.json, DB + schema already created):
         python projects/remove_sitelinks/migrate_tracker_db.py --import
     -> upserts every row into MariaDB via ON DUPLICATE KEY UPDATE

Copying the `qids` table is what prevents already-processed items from being
edited a second time (is_processed() checks it). `wikimedia_cats` is just a
cache but is cheap to carry along.
"""

import argparse
import json
import sys
from pathlib import Path

# Make the bare shared_lib-module imports work standalone (no PYTHONPATH needed).
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "projects"))
sys.path.insert(0, str(_ROOT / "projects" / "shared_lib"))

DATA_DIR = Path(__file__).parent / "data"
CONFIG = DATA_DIR / "remove_sitelinks.json"
DUMP = DATA_DIR / "tracker_dump.json"

# table -> column list (qid is the primary key used for the upsert)
TABLES = {
    "qids": ["qid", "status", "error_msg", "summary"],
    "wikimedia_cats": ["qid", "is_wikimedia_cat"],
}


def export(include_failed: bool = False) -> None:
    from database_handler_firebird import FirebirdDatabaseHandler

    handler = FirebirdDatabaseHandler(CONFIG)
    dump: dict[str, list[dict]] = {}
    for table, cols in TABLES.items():
        # By default carry only successfully-processed qids: those are the items
        # already edited (must be skipped later). 'failed' items were never
        # edited, so leaving them out lets them reprocess with current fixes.
        where = ""
        if table == "qids" and not include_failed:
            where = " WHERE status = 'success'"
        rows = handler.execute_query(f"SELECT {', '.join(cols)} FROM {table}{where}")
        records = []
        for row in rows:
            record = dict(zip(cols, row))
            if "is_wikimedia_cat" in record:  # normalise Firebird bool -> 0/1
                record["is_wikimedia_cat"] = 1 if record["is_wikimedia_cat"] else 0
            records.append(record)
        dump[table] = records
        print(f"Read {len(records)} rows from {table}")

    DUMP.write_text(json.dumps(dump, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Exported to {DUMP}")


def import_() -> None:
    from database_handler_mariadb import MariaDbDatabaseHandler

    handler = MariaDbDatabaseHandler(CONFIG)
    dump = json.loads(DUMP.read_text(encoding="utf-8"))
    for table, cols in TABLES.items():
        rows = dump.get(table, [])
        for record in rows:
            handler.upsert(table, {c: record.get(c) for c in cols}, ["qid"])
        print(f"Imported {len(rows)} rows into {table}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--export", action="store_true", help="Firebird -> data/tracker_dump.json"
    )
    group.add_argument(
        "--import",
        dest="do_import",
        action="store_true",
        help="data/tracker_dump.json -> MariaDB",
    )
    parser.add_argument(
        "--include-failed",
        action="store_true",
        help="(with --export) also copy 'failed' qids instead of only 'success'",
    )
    args = parser.parse_args()

    if args.export:
        export(include_failed=args.include_failed)
    else:
        import_()


if __name__ == "__main__":
    main()
