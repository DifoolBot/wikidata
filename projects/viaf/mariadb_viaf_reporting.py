from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from viaf.paths import DATA_DIR
from viaf.viaf_bot import ReportBackend

from shared_lib.database_handler_mariadb import MariaDbDatabaseHandler


class MariaDbViafReporting(MariaDbDatabaseHandler, ReportBackend):
    """MariaDB counterpart of FirebirdViafReporting (see firebird_viaf_reporting.py).

    Assumes a MariaDB schema mirroring schemas/viaf.sql (same ADDED / DUPLICATES /
    DUPLICATE_LOCAL_AUTH_IDS / ERRORS / IGNORED tables and add_done / add_error /
    add_duplicate / add_duplicate_local_auth_id / clean_up /
    cleanup_duplicate_local_auth_ids / get_stats / end_session procedures). That
    schema still needs to be ported to MariaDB (CREATE PROCEDURE / DELIMITER
    syntax) before this class can run against a real database.
    """

    def __init__(self) -> None:
        config_filename = DATA_DIR / "viaf_mariadb.json"
        create_script = Path("schemas/viaf_mariadb.sql")
        super().__init__(config_filename, create_script)

    def has_done(self, qid: str) -> bool:
        return self.has_record("ADDED", "QID=?", (qid,))

    def has_duplicate(self, qid: str) -> bool:
        return self.has_record("DUPLICATES", "(QID=? OR DUPLICATE_QID=?)", (qid, qid))

    def has_duplicate_local_auth_id(self, qid: str) -> bool:
        return self.has_record("DUPLICATE_LOCAL_AUTH_IDS", "QID=?", (qid,))

    def has_error(self, qid: str) -> bool:
        return self.has_record("ERRORS", "QID=? AND NOT RETRY", (qid,))

    def has_ignore(self, qid: str) -> bool:
        return self.has_record("IGNORED", "QID=?", (qid,))

    def add_duplicate(
        self, qid: str, duplicate_qid: str, local_auth_id: str | None, viaf_id: str
    ) -> None:
        sql = "CALL add_duplicate(?, ?, ?, ?)"
        self.execute_procedure(sql, (qid, duplicate_qid, local_auth_id, viaf_id))

    def add_duplicate_local_auth_id(
        self, qid: str, local_auth_id: str, viaf_cluster_id: str | None
    ) -> None:
        sql = "CALL add_duplicate_local_auth_id(?, ?, ?)"
        self.execute_procedure(sql, (qid, local_auth_id, viaf_cluster_id))

    def add_error(self, qid: str, msg: str) -> None:
        shortened_msg = msg[:255]
        sql = "CALL add_error(?, ?)"
        self.execute_procedure(sql, (qid, shortened_msg))

    def add_done(self, qid: str) -> None:
        sql = "CALL add_done(?)"
        self.execute_procedure(sql, (qid,))

    def add_not_found(self, qid: str, pid: str) -> None:
        sql = "CALL add_not_found(?, ?)"
        self.execute_procedure(sql, (qid, pid))

    def has_recent_not_found(self, qid: str, pid: str, cutoff: datetime) -> bool:
        return self.has_record(
            "NOT_FOUND", "QID=? AND PID=? AND CHECKED_DATE >= ?", (qid, pid, cutoff)
        )

    def purge_not_found_before(self, cutoff: datetime) -> None:
        self.execute_procedure(
            "DELETE FROM NOT_FOUND WHERE CHECKED_DATE < ?", (cutoff,)
        )

    def count_duplicates(self) -> int:
        rows = self.execute_query("SELECT COUNT(*) FROM DUPLICATES")
        return rows[0][0] if rows else 0

    def get_duplicates(self) -> list[tuple[str, str, str, str]]:
        sql = (
            "SELECT QID, DUPLICATE_QID, LOCAL_AUTH_ID, VIAF_ID FROM DUPLICATES "
            "ORDER BY 1, 2 LIMIT 1000"
        )
        return self.execute_query(sql)

    def get_duplicate_local_auth_ids(self) -> Iterator[tuple[str, set[str], str]]:
        sql = "SELECT QID, LOCAL_AUTH_ID, VIAF_ID FROM DUPLICATE_LOCAL_AUTH_IDS ORDER BY viaf_id, qid, local_auth_id"
        rows = self.execute_query(sql)
        last_viaf_id: str | None = None
        last_qid: str | None = None
        local_auth_ids: set[str] = set()
        for row in rows:
            qid, local_auth_id, viaf_id = row
            if viaf_id == last_viaf_id and qid == last_qid:
                local_auth_ids.add(local_auth_id)
                continue
            if last_viaf_id is not None:
                assert last_qid is not None
                yield (last_qid, local_auth_ids, last_viaf_id)
                local_auth_ids = set()
            last_viaf_id = viaf_id
            last_qid = qid
            local_auth_ids.add(local_auth_id)

    def get_stats(self) -> tuple[int, int, int] | None:
        sql = "CALL get_stats()"
        for row in self.execute_query(sql):
            return row

        return None

    def run_maintenance(self) -> None:
        self.execute_procedure("CALL clean_up()")
        self.execute_procedure("CALL cleanup_duplicate_local_auth_ids()")

    def end_session(self, pid: str) -> None:
        sql = "CALL end_session(?)"
        self.execute_procedure(sql, (pid,))
