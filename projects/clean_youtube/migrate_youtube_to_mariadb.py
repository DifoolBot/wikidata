"""One-off migration of the clean_youtube tracker DB from Firebird (local) to
MariaDB (Toolforge).

ToolsDB is only reachable from inside Toolforge, so this runs in two steps:

  1. Locally (Firebird driver installed), export the tables to a portable file:
         python projects/clean_youtube/migrate_youtube_to_mariadb.py --export
     -> writes data/youtube_dump.json

  2. Copy data/youtube_dump.json to Toolforge (scp), then on the bastion
     (MariaDB config in channel_handles.json, DB + schema already created from
     schemas/youtube_mariadb.sql):
         python projects/clean_youtube/migrate_youtube_to_mariadb.py --import
     -> upserts every row into MariaDB via ON DUPLICATE KEY UPDATE

Copying the `qids` table is what prevents already-processed items from being
edited a second time (is_processed() checks it). `channel_handles` and
`channel_publishers` are caches that save YouTube API quota and SPARQL lookups.
Existing created_at values are carried over; rows without one stay NULL (the
MariaDB columns are declared TIMESTAMP NULL so the server does not coerce an
explicit NULL into the insert time).
"""

import argparse
import datetime
import json
import sys
from pathlib import Path

# Make the bare shared_lib-module imports work standalone (no PYTHONPATH needed).
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "projects"))
sys.path.insert(0, str(_ROOT / "projects" / "shared_lib"))

CONFIG = Path(__file__).parent / "channel_handles.json"
DUMP = Path(__file__).parent / "data" / "youtube_dump.json"

# table -> (key column used for the upsert, column list)
TABLES = {
    "qids": ("qid", ["qid", "status", "error_msg", "summary", "created_at"]),
    "channel_handles": (
        "channel_id",
        ["channel_id", "handle", "status", "created_at"],
    ),
    "channel_publishers": (
        "channel_key",
        ["channel_key", "publisher_qid", "status", "created_at"],
    ),
}


def _jsonable(value):
    if isinstance(value, datetime.datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return value


def export(include_failed: bool = False) -> None:
    from database_handler_firebird import FirebirdDatabaseHandler

    handler = FirebirdDatabaseHandler(CONFIG)
    dump: dict[str, list[dict]] = {}
    for table, (_key, cols) in TABLES.items():
        # By default carry only successfully-processed qids: those are the items
        # already edited (must be skipped later). 'failed' items were never
        # edited, so leaving them out lets them reprocess with current fixes.
        where = ""
        if table == "qids" and not include_failed:
            where = " WHERE status = 'success'"
        rows = handler.execute_query(f"SELECT {', '.join(cols)} FROM {table}{where}")
        records = [{c: _jsonable(v) for c, v in zip(cols, row)} for row in rows]
        dump[table] = records
        print(f"Read {len(records)} rows from {table}")

    DUMP.parent.mkdir(exist_ok=True)
    DUMP.write_text(json.dumps(dump, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Exported to {DUMP}")


def import_(batch_size: int = 5000) -> None:
    from database_handler_mariadb import MariaDbDatabaseHandler

    handler = MariaDbDatabaseHandler(CONFIG)
    dump = json.loads(DUMP.read_text(encoding="utf-8"))

    # One connection, batched executemany (pymysql collapses each batch into a
    # single multi-row INSERT ... ON DUPLICATE KEY UPDATE) - far faster than a
    # connection per row.
    conn = handler.get_connection()
    try:
        cur = conn.cursor()
        for table, (key, cols) in TABLES.items():
            rows = dump.get(table, [])
            if not rows:
                continue
            placeholders = ", ".join(["%s"] * len(cols))
            updates = ", ".join(f"{c}=VALUES({c})" for c in cols if c != key)
            sql = (
                f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
                f"ON DUPLICATE KEY UPDATE {updates}"
            )
            data = [tuple(r.get(c) for c in cols) for r in rows]
            for i in range(0, len(data), batch_size):
                cur.executemany(sql, data[i : i + batch_size])
                conn.commit()
                done = min(i + batch_size, len(data))
                print(f"{table}: {done}/{len(data)}")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--export", action="store_true", help="Firebird -> data/youtube_dump.json"
    )
    group.add_argument(
        "--import",
        dest="do_import",
        action="store_true",
        help="data/youtube_dump.json -> MariaDB",
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
