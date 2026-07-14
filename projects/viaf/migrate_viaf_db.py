"""One-off migration: copy data from the OLD VIAF Firebird database into the NEW
one (created from schemas/viaf.sql).

Both databases are reached via their JSON config (same format as data/viaf.json:
{"DB_HOST": "server:/path/to.fdb", "DB_USER": "...", "DB_PASSWORD": "..."}).

Steps:
  1. Keep the old database file, and put its config in data/viaf_old.json.
  2. Create the new (empty) database from schemas/viaf.sql -> data/viaf.json
     (e.g. run call_viaf once, or FirebirdViafReporting(), which builds it).
  3. python -m viaf.migrate_viaf_db

Re-running it will duplicate rows, so only run it against a fresh new database.
Historical QDONE rows (CURRENT_SESSION = FALSE) are intentionally not copied.
"""

import json
from datetime import datetime, timezone

from firebird.driver import connect

from viaf.paths import DATA_DIR

OLD_CONFIG = DATA_DIR / "viaf_old.json"
NEW_CONFIG = DATA_DIR / "viaf.json"


def _connect(config_path):
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    return connect(
        cfg["DB_HOST"],
        user=cfg["DB_USER"],
        password=cfg["DB_PASSWORD"],
        charset="UTF8",
    )


def _copy(old, new, label, select_sql, insert_sql, transform=None):
    rows = old.cursor().execute(select_sql).fetchall()
    values = [transform(row) if transform else tuple(row) for row in rows]
    if values:
        new.cursor().executemany(insert_sql, values)
        new.commit()
    print(f"{label}: {len(values)} row(s)")


def _now():
    return datetime.now(timezone.utc)


def main() -> None:
    old = _connect(OLD_CONFIG)
    new = _connect(NEW_CONFIG)
    try:
        # --- permanent / reference data -----------------------------------
        _copy(
            old, new, "IGNORED",
            "SELECT QCODE FROM QIGNORE",
            "INSERT INTO IGNORED (QID) VALUES (?)",
        )
        _copy(
            old, new, "CODES",
            "SELECT PID, CODE, DESCRIPTION, DO_IGNORE, IS_EMPTY FROM CODES",
            "INSERT INTO CODES (PID, CODE, DESCRIPTION, DO_IGNORE, IS_EMPTY) "
            "VALUES (?, ?, ?, ?, ?)",
        )
        _copy(
            old, new, "PDONE",
            "SELECT PID, CHECKED, ADDED, NOT_FOUND, DONE_DATE FROM PDONE ORDER BY ID",
            "INSERT INTO PDONE (PID, CHECKED, ADDED, NOT_FOUND, DONE_DATE) "
            "VALUES (?, ?, ?, ?, ?)",
            transform=lambda r: (r[0], r[1], r[2], r[3], r[4] or _now()),
        )

        # --- current-session working data (history dropped) ----------------
        _copy(
            old, new, "ADDED",
            "SELECT QCODE, DONE_DATE FROM QDONE WHERE CURRENT_SESSION",
            "INSERT INTO ADDED (QID, ADDED_DATE) VALUES (?, ?)",
            transform=lambda r: (r[0], r[1] or _now()),
        )
        _copy(
            old, new, "ERRORS",
            "SELECT QCODE, ERROR, ERROR_DATE, RETRY, COMMENT_STR FROM QERROR",
            "INSERT INTO ERRORS (QID, MESSAGE, ERROR_DATE, RETRY, NOTE) "
            "VALUES (?, ?, ?, ?, ?)",
            transform=lambda r: (r[0], r[1], r[2] or _now(), bool(r[3]), r[4]),
        )
        _copy(
            old, new, "DUPLICATES",
            "SELECT QID, DUPLICATE_QID, LOCAL_AUTH_ID, VIAF_ID FROM QDUPLICATES",
            "INSERT INTO DUPLICATES (QID, DUPLICATE_QID, LOCAL_AUTH_ID, VIAF_ID) "
            "VALUES (?, ?, ?, ?)",
        )
        _copy(
            old, new, "DUPLICATE_LOCAL_AUTH_IDS",
            "SELECT QID, LOCAL_AUTH_ID, VIAF_ID FROM QDUPLOCAL",
            "INSERT INTO DUPLICATE_LOCAL_AUTH_IDS (QID, LOCAL_AUTH_ID, VIAF_ID) "
            "VALUES (?, ?, ?)",
        )
    finally:
        old.close()
        new.close()


if __name__ == "__main__":
    main()
