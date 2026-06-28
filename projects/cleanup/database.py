"""
database.py

MariaDB-backed status tracker for the WikidataCleanup bot.

Follows the same DatabaseHandler / tool-specific subclass pattern as the
local Firebird tracker, adapted for the Toolforge MariaDB environment.

On Toolforge:
  - Connection credentials come from ~/replica.my.cnf (written by Toolforge).
  - The tool database is named  <user>__wikidata_cleanup  where <user> is the
    tool account name read from replica.my.cnf.
  - Run  python database.py --create-tables  once interactively on the bastion
    to initialise the schema before the first bot run.

Local development:
  - Pass explicit host/user/password/database to DatabaseHandler.__init__()
    or set WDCLEANUP_DB_* environment variables.
  - SQLite mode (db_path kwarg) is available for offline unit tests.
"""

from __future__ import annotations

import configparser
import logging
import os
import pathlib
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

# ==== Base class =============================================================


class DatabaseHandler:
    """
    Thin wrapper around a MariaDB (or SQLite) connection providing
    execute_query() and execute_procedure() primitives.

    Subclass this and call super().__init__() to get a working connection.
    Then define your schema via create_tables() and your business logic
    as ordinary methods.
    """

    def __init__(
        self,
        *,
        # MariaDB via Toolforge replica.my.cnf
        my_cnf: pathlib.Path | None = None,
        db_suffix: str = "wikidata_cleanup",
        # Explicit overrides (useful for local dev / CI)
        host: str | None = None,
        user: str | None = None,
        password: str | None = None,
        database: str | None = None,
        # SQLite fallback for offline tests
        db_path: pathlib.Path | None = None,
    ) -> None:
        self._sqlite = db_path is not None
        if self._sqlite:
            self._conn = sqlite3.connect(str(db_path))
            self._conn.row_factory = sqlite3.Row
            log.info("Connected to SQLite database at %s", db_path)
        else:
            self._conn = self._connect_mariadb(
                my_cnf=my_cnf,
                db_suffix=db_suffix,
                host=host,
                user=user,
                password=password,
                database=database,
            )

        self.create_tables()

    # ── Connection ────────────────────────────────────────────────────────────

    @staticmethod
    def _connect_mariadb(
        my_cnf: pathlib.Path | None,
        db_suffix: str,
        host: str | None,
        user: str | None,
        password: str | None,
        database: str | None,
    ):
        import pymysql

        # Read credentials from replica.my.cnf if not supplied explicitly.
        if not all((host, user, password)):
            cnf_path = my_cnf or pathlib.Path.home() / "replica.my.cnf"
            cfg = configparser.ConfigParser()
            cfg.read(cnf_path)
            client = cfg["client"]
            host = host or client.get("host", "tools.db.svc.wikimedia.cloud")
            user = user or client.get("user", "")
            password = password or client.get("password", "")

        database = database or f"{user}__{db_suffix}"

        conn = pymysql.connect(
            host=host,
            user=user,
            password=password or "",
            database=database,
            charset="utf8mb4",
            autocommit=True,
        )
        log.info("Connected to MariaDB %s/%s as %s", host, database, user)
        return conn

    # ── Primitives ────────────────────────────────────────────────────────────

    def execute_query(self, sql: str, params: tuple = ()) -> list[tuple]:
        """Run a SELECT and return all rows as a list of tuples."""
        if self._sqlite:
            sql = sql.replace("%s", "?")
            cur = self._conn.cursor()
            cur.execute(sql, params)
            return list(cur.fetchall())
        else:
            cur = self._conn.cursor()
            try:
                cur.execute(sql, params)
                return list(cur.fetchall())
            finally:
                cur.close()

    def execute_procedure(self, sql: str, params: tuple = ()) -> None:
        """Run an INSERT/UPDATE/DELETE/CREATE statement."""
        if self._sqlite:
            sql = sql.replace("%s", "?")
            cur = self._conn.cursor()
            cur.execute(sql, params)
            self._conn.commit()
        else:
            cur = self._conn.cursor()
            try:
                cur.execute(sql, params)
            finally:
                cur.close()

    def close(self) -> None:
        """Close the underlying connection."""
        try:
            self._conn.close()
        except Exception:
            pass

    # ── Schema hook ──────────────────────────────────────────────────────────

    def create_tables(self) -> None:
        """
        Called automatically after connecting.  Override in subclasses to
        issue CREATE TABLE IF NOT EXISTS statements for this tool's schema.
        """


# ==== WikidataCleanup tracker ================================================


class WikidataCleanupTracker(DatabaseHandler):
    """
    Status tracker for the WikidataCleanup bot.

    Schema
    ------
    qids table:
        qid          — Wikidata item ID (Q-number)
        run_id       — UUID of the bot run that processed this item
        status       — 'changed' | 'skipped' | 'error'
        diffs_count  — number of diffs applied (0 for skipped/error)
        edit_summary — summary text used for the Wikidata edit
        error_msg    — error message when status = 'error'
        touched_at   — timestamp of this record (auto-set by DB)

    The PRIMARY KEY is (qid, run_id) so the same item can be recorded across
    multiple runs while each run's record is distinct.  Use is_processed() to
    check whether an item was successfully handled within the last N days.
    """

    def create_tables(self) -> None:
        if self._sqlite:
            self.execute_procedure("""
                CREATE TABLE IF NOT EXISTS qids (
                    qid          TEXT     NOT NULL,
                    run_id       TEXT     NOT NULL DEFAULT '',
                    status       TEXT     NOT NULL CHECK(status IN
                                     ('changed', 'skipped', 'error')),
                    diffs_count  INTEGER  NOT NULL DEFAULT 0,
                    edit_summary TEXT     NOT NULL DEFAULT '',
                    error_msg    TEXT     NOT NULL DEFAULT '',
                    touched_at   DATETIME NOT NULL
                                 DEFAULT (datetime('now')),
                    PRIMARY KEY (qid, run_id)
                )
            """)
        else:
            self.execute_procedure("""
                CREATE TABLE IF NOT EXISTS qids (
                    qid          VARCHAR(16)   NOT NULL,
                    run_id       VARCHAR(64)   NOT NULL DEFAULT '',
                    status       ENUM('changed','skipped','error') NOT NULL,
                    diffs_count  INT           NOT NULL DEFAULT 0,
                    edit_summary TEXT,
                    error_msg    TEXT,
                    touched_at   DATETIME      NOT NULL
                                 DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY  (qid, run_id),
                    INDEX        idx_qid       (qid),
                    INDEX        idx_touched   (touched_at),
                    INDEX        idx_status    (status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """)

    # ── Guard: was this item recently processed? ──────────────────────────────

    def is_processed(self, qid: str, days: int = 7) -> bool:
        """
        Return True when the item was successfully changed within the last
        `days` days.  Items that errored or were skipped are re-eligible.
        """
        if self._sqlite:
            rows = self.execute_query(
                f"""
                SELECT 1 FROM qids
                WHERE qid = %s
                  AND status = 'changed'
                  AND touched_at > datetime('now', '-{days} days')
                LIMIT 1
                """,
                (qid,),
            )
        else:
            rows = self.execute_query(
                """
                SELECT 1 FROM qids
                WHERE qid = %s
                  AND status = 'changed'
                  AND touched_at > DATE_SUB(NOW(), INTERVAL %s DAY)
                LIMIT 1
                """,
                (qid, days),
            )
        return bool(rows)

    def get_processed_qids(self, days: int | None = None) -> set[str]:
        """
        Return all QIDs with status='changed', optionally limited to
        those touched within the last `days` days.
        """
        if days is None:
            rows = self.execute_query(
                "SELECT qid FROM qids WHERE status = %s", ("changed",)
            )
        elif self._sqlite:
            rows = self.execute_query(
                f"""
                SELECT qid FROM qids
                WHERE status = 'changed'
                  AND touched_at > datetime('now', '-{days} days')
                """,
                (),
            )
        else:
            rows = self.execute_query(
                """
                SELECT qid FROM qids
                WHERE status = 'changed'
                  AND touched_at > DATE_SUB(NOW(), INTERVAL %s DAY)
                """,
                (days,),
            )
        return {row[0] for row in rows}

    # ── Recording outcomes ────────────────────────────────────────────────────

    def mark_changed(
        self,
        qid: str,
        run_id: str = "",
        diffs_count: int = 0,
        edit_summary: str = "",
    ) -> None:
        """Record a successful edit."""
        summary = edit_summary[:2000]
        if self._sqlite:
            self.execute_procedure(
                """
                INSERT INTO qids (qid, run_id, status, diffs_count, edit_summary)
                VALUES (%s, %s, 'changed', %s, %s)
                ON CONFLICT(qid, run_id) DO UPDATE SET
                    status       = 'changed',
                    diffs_count  = excluded.diffs_count,
                    edit_summary = excluded.edit_summary,
                    touched_at   = datetime('now')
                """,
                (qid, run_id, diffs_count, summary),
            )
        else:
            self.execute_procedure(
                """
                INSERT INTO qids (qid, run_id, status, diffs_count, edit_summary)
                VALUES (%s, %s, 'changed', %s, %s)
                ON DUPLICATE KEY UPDATE
                    status       = 'changed',
                    diffs_count  = VALUES(diffs_count),
                    edit_summary = VALUES(edit_summary),
                    touched_at   = CURRENT_TIMESTAMP
                """,
                (qid, run_id, diffs_count, summary),
            )

    def mark_skipped(self, qid: str, run_id: str = "") -> None:
        """Record that the item was visited but no changes were needed."""
        if self._sqlite:
            self.execute_procedure(
                """
                INSERT OR IGNORE INTO qids (qid, run_id, status)
                VALUES (%s, %s, 'skipped')
                """,
                (qid, run_id),
            )
        else:
            self.execute_procedure(
                """
                INSERT IGNORE INTO qids (qid, run_id, status)
                VALUES (%s, %s, 'skipped')
                """,
                (qid, run_id),
            )

    def mark_error(
        self,
        qid: str,
        error: Exception,
        run_id: str = "",
    ) -> None:
        """Record a processing failure."""
        msg = str(error)[:2000]
        if self._sqlite:
            self.execute_procedure(
                """
                INSERT INTO qids (qid, run_id, status, error_msg)
                VALUES (%s, %s, 'error', %s)
                ON CONFLICT(qid, run_id) DO UPDATE SET
                    status     = 'error',
                    error_msg  = excluded.error_msg,
                    touched_at = datetime('now')
                """,
                (qid, run_id, msg),
            )
        else:
            self.execute_procedure(
                """
                INSERT INTO qids (qid, run_id, status, error_msg)
                VALUES (%s, %s, 'error', %s)
                ON DUPLICATE KEY UPDATE
                    status     = 'error',
                    error_msg  = VALUES(error_msg),
                    touched_at = CURRENT_TIMESTAMP
                """,
                (qid, run_id, msg),
            )

    # ── Diagnostics ──────────────────────────────────────────────────────────

    def summary(self) -> dict[str, int]:
        """Return counts of each status."""
        rows = self.execute_query("SELECT status, COUNT(*) FROM qids GROUP BY status")
        return {row[0]: row[1] for row in rows}


# ==== CLI: create tables =====================================================

if __name__ == "__main__":
    import argparse

    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )

    parser = argparse.ArgumentParser(description="WikidataCleanup database management")
    parser.add_argument(
        "--create-tables",
        action="store_true",
        help="Create the database schema (run once on the Toolforge bastion)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a summary of processed items",
    )
    parser.add_argument(
        "--sqlite",
        metavar="PATH",
        help="Use a local SQLite database instead of MariaDB",
    )
    args = parser.parse_args()

    kwargs = {}
    if args.sqlite:
        kwargs["db_path"] = pathlib.Path(args.sqlite)

    tracker = WikidataCleanupTracker(**kwargs)

    if args.create_tables:
        log.info("Tables created (or already existed).")

    if args.summary:
        counts = tracker.summary()
        for status, count in sorted(counts.items()):
            print(f"  {status:10s}: {count:,}")

    tracker.close()
