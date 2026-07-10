"""Firebird-backed ReportBackend for the addlabel bot.

Uses the existing addlabel Firebird database (tables QERROR, QTODO, PDONE and
procedures GET_DONE, add_error, add_done, add_non_latin, add_pdone). The
connection details live in data/addlabel.json; DB_USER/DB_PASSWORD may be
omitted there and provided through the repo-root .env (WD_DB_USER /
WD_DB_PASSWORD) instead.
"""

from typing import List

from shared_lib.database_handler_firebird import FirebirdDatabaseHandler

from addlabel.addlabel_bot import ReportBackend
from addlabel.paths import DATA_DIR


class FirebirdAddLabelReporting(FirebirdDatabaseHandler, ReportBackend):

    def __init__(self):
        super().__init__(DATA_DIR / "addlabel.json")

    def has_error(self, qid: str) -> bool:
        return self.has_record("QERROR", "QCODE=? AND NOT RETRY", (qid,))

    def is_done(self, qid: str) -> bool:
        rows = self.execute_query("SELECT IS_DONE FROM GET_DONE (?)", (qid,))
        for row in rows:
            return bool(row[0])
        return False

    def add_non_latin(self, qid: str, locale: str) -> None:
        sql = "EXECUTE PROCEDURE add_non_latin(?, ?)"
        self.execute_procedure(sql, (qid, locale[:255]))

    def add_error(self, qid: str, msg: str) -> None:
        sql = "EXECUTE PROCEDURE add_error(?, ?)"
        self.execute_procedure(sql, (qid, msg[:255]))

    def add_done(self, qid: str) -> None:
        sql = "EXECUTE PROCEDURE add_done(?)"
        self.execute_procedure(sql, (qid,))

    def get_index(self, pid: str) -> int:
        rows = self.execute_query("SELECT INDX FROM PDONE WHERE PCODE=?", (pid,))
        for row in rows:
            return row[0]
        return 0

    def set_index(self, pid: str, index: int) -> None:
        sql = "EXECUTE PROCEDURE add_pdone(?, ?)"
        self.execute_procedure(sql, (pid, index))

    def get_retry(self) -> List[str]:
        sql = "SELECT QCODE FROM QERROR WHERE RETRY = TRUE ORDER BY 1"
        return [row[0] for row in self.execute_query(sql)]

    def get_todo(self) -> List[str]:
        sql = "SELECT FIRST 5000 QCODE FROM QTODO"
        return [row[0] for row in self.execute_query(sql)]
