from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

import viaf.viaf_bot
from viaf.paths import DATA_DIR

from shared_lib.database_handler_firebird import FirebirdDatabaseHandler


def _as_date(value) -> date | None:
    """DATE columns come back as date (or datetime on some drivers)."""
    if isinstance(value, datetime):
        return value.date()
    return value


class FirebirdViafReporting(FirebirdDatabaseHandler, viaf.viaf_bot.ReportBackend):
    def __init__(self) -> None:
        config_filename = DATA_DIR / "viaf.json"
        create_script = Path("schemas/viaf.sql")
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
        sql = "EXECUTE PROCEDURE add_duplicate(?, ?, ?, ?)"
        self.execute_procedure(sql, (qid, duplicate_qid, local_auth_id, viaf_id))

    def add_duplicate_local_auth_id(
        self, qid: str, local_auth_id: str, viaf_cluster_id: str | None
    ) -> None:
        sql = "EXECUTE PROCEDURE add_duplicate_local_auth_id(?, ?, ?)"
        self.execute_procedure(sql, (qid, local_auth_id, viaf_cluster_id))

    def add_error(self, qid: str, msg: str) -> None:
        shortened_msg = msg[:255]
        sql = "EXECUTE PROCEDURE add_error(?, ?)"
        self.execute_procedure(sql, (qid, shortened_msg))

    def add_done(self, qid: str) -> None:
        sql = "EXECUTE PROCEDURE add_done(?)"
        self.execute_procedure(sql, (qid,))

    def add_not_found(self, qid: str, pid: str) -> None:
        sql = "EXECUTE PROCEDURE add_not_found(?, ?)"
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
        # cap the list at 1000 items to keep the wiki result page manageable
        sql = "SELECT first 1000 QID, DUPLICATE_QID, LOCAL_AUTH_ID, VIAF_ID FROM DUPLICATES ORDER BY 1, 2"
        return self.execute_query(sql)

    def get_duplicate_local_auth_ids(self) -> Iterator[tuple[str, set[str], str]]:
        sql = "SELECT QID, LOCAL_AUTH_ID, VIAF_ID FROM DUPLICATE_LOCAL_AUTH_IDS order by viaf_id,qid,local_auth_id"
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
        sql = "SELECT CHECKED, ADDED, NOT_FOUND FROM GET_STATS"
        for row in self.execute_query(sql):
            return row

        return None

    def run_maintenance(self) -> None:
        self.execute_procedure("EXECUTE PROCEDURE clean_up")
        self.execute_procedure("EXECUTE PROCEDURE cleanup_duplicate_local_auth_ids")

    def end_session(self, pid: str) -> None:
        sql = "EXECUTE PROCEDURE end_session(?)"
        self.execute_procedure(sql, (pid,))

    def get_state(self) -> viaf.viaf_bot.BotState:
        rows = self.execute_query(
            "SELECT CURRENT_PID, COOLDOWN_UNTIL, SESSION_START, TOTAL_ROWS, "
            "REMAINING_ROWS, DESCRIPTIONS_SYNCED FROM STATE WHERE ID = 1"
        )
        if not rows:
            return viaf.viaf_bot.BotState()
        (
            current_pid,
            cooldown_until,
            session_start,
            total_rows,
            remaining_rows,
            descriptions_synced,
        ) = rows[0]
        return viaf.viaf_bot.BotState(
            current_pid=current_pid.strip() if current_pid else None,
            cooldown_until=_as_date(cooldown_until),
            session_start=_as_date(session_start),
            total_rows=total_rows,
            remaining_rows=remaining_rows,
            descriptions_synced=_as_date(descriptions_synced),
        )

    def save_progress(self, current_pid: str, cooldown_until: date | None) -> None:
        self._upsert_state(
            "CURRENT_PID = ?, COOLDOWN_UNTIL = ?", (current_pid, cooldown_until)
        )

    def start_source_session(self, pid: str, total_rows: int) -> None:
        self._upsert_state(
            "CURRENT_PID = ?, SESSION_START = ?, TOTAL_ROWS = ?, REMAINING_ROWS = ?",
            (pid, date.today(), total_rows, total_rows),
        )

    def set_remaining_rows(self, remaining: int) -> None:
        self._upsert_state("REMAINING_ROWS = ?", (remaining,))

    def set_descriptions_synced(self, day: date) -> None:
        self._upsert_state("DESCRIPTIONS_SYNCED = ?", (day,))

    def _upsert_state(self, assignments: str, params: tuple) -> None:
        """Update the single STATE row, creating it if this is a fresh database."""
        self.execute_procedure("UPDATE OR INSERT INTO STATE (ID) VALUES (1) MATCHING (ID)")
        self.execute_procedure(f"UPDATE STATE SET {assignments} WHERE ID = 1", params)
