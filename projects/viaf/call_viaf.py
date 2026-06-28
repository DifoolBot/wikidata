from collections.abc import Iterator

import pywikibot as pwb
import viaf.authsource
import viaf.viaf

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
from shared_lib.database_handler import DatabaseHandler

QID_INFERRED_FROM_VIAF_ID_CONTAINING_AN_ID_ALREADY_PRESENT_IN_THE_ITEM = "Q115111315"

# class ReportingKeepURLStrategy(impl_statedin.KeepURLStrategy):
#     def __init__(self, report: reporting.Reporting):
#         self.report = report

#     def keep_url(self, pid: str, pattern: str) -> bool:
#         return self.report.keep_url(pid, pattern)

# REPORT = firebird_reporting.FirebirdReporting()
# STA_IN = viaf.impl_statedin.StatedIn()
# STA_IN.keep_url_strategy = ReportingKeepURLStrategy(REPORT)


class ViafInferredFromReference(cwd.Reference):
    def __init__(self, pid: str, id: str):
        self.pid = pid
        self.external_id = id
        self.heuristic_qid = (
            QID_INFERRED_FROM_VIAF_ID_CONTAINING_AN_ID_ALREADY_PRESENT_IN_THE_ITEM
        )

    def is_equal_reference(self, src: dict) -> bool:
        if self.pid not in src:
            return False
        if len(src[self.pid]) != 1:
            raise RuntimeError("Multiple external ids")
        actual = src[self.pid][0].getTarget()
        return actual == self.external_id

    def create_source(self):
        # TODO
        pass

    def is_strong_reference(self) -> bool:
        return True


class FirebirdViafReporting(DatabaseHandler, viaf.viaf.IReport):
    def __init__(self) -> None:
        super().__init__("viaf.json")

    def has_done(self, qid: str) -> bool:
        return self.has_record("QDONE", "QCODE=?", (qid,))

    def has_duplicate(self, qid: str) -> bool:
        return self.has_record("QDUPLICATES", "(QID=? OR DUPLICATE_QID=?)", (qid, qid))

    def has_duplicate_local_auth_id(self, qid: str) -> bool:
        return self.has_record("QDUPLOCAL", "QID=?", (qid,))

    def has_error(self, qid: str) -> bool:
        return self.has_record("QERROR", "QCODE=? AND NOT RETRY", (qid,))

    def has_ignore(self, qid: str) -> bool:
        return self.has_record("QIGNORE", "QCODE=?", (qid,))

    def add_duplicate(
        self, qid: str, duplicate_qid: str, local_auth_id: str | None, viaf_id: str
    ) -> None:
        sql = "EXECUTE PROCEDURE add_duplicate(?, ?, ?, ?)"
        self.execute_procedure(sql, (qid, duplicate_qid, local_auth_id, viaf_id))

    def add_duplicate_local_auth_id(
        self, qid: str, local_auth_id: str, viaf_cluster_id: str | None
    ) -> None:
        sql = "EXECUTE PROCEDURE add_dup_local(?, ?, ?)"
        self.execute_procedure(sql, (qid, local_auth_id, viaf_cluster_id))

    def add_error(self, qid: str, msg: str) -> None:
        shortened_msg = msg[:255]
        sql = "EXECUTE PROCEDURE add_error(?, ?)"
        self.execute_procedure(sql, (qid, shortened_msg))

    def add_done(self, qid: str) -> None:
        sql = "EXECUTE PROCEDURE add_done(?)"
        self.execute_procedure(sql, (qid,))

    def get_duplicates(self) -> list[tuple[str, str, str, str]]:
        sql = "SELECT first 1000 skip 1000 QID, DUPLICATE_QID, LOCAL_AUTH_ID, VIAF_ID FROM QDUPLICATES ORDER BY 1, 2"
        return self.execute_query(sql)

    def get_dup_locals(self) -> Iterator[tuple[str, set[str], str]]:
        sql = "SELECT QID, LOCAL_AUTH_ID, VIAF_ID FROM QDUPLOCAL order by viaf_id,qid,local_auth_id"
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

    def end_session(self, pid: str) -> None:
        sql = "EXECUTE PROCEDURE start_new_session(?)"
        self.execute_procedure(sql, (pid,))

    def add_viaf(
        self,
        item: pwb.ItemPage,
        auth_src: viaf.authsource.AuthoritySource,
        viaf_cluster_id: str | None,
    ) -> None:
        if viaf_cluster_id is None:
            raise RuntimeError("Cannot add VIAF ID without a viaf_cluster_id")

        wdpage = cwd.WikiDataPage(item, test=False)
        wdpage.add_statement(
            cwd.ExternalIDStatement(prop=wd.PID_VIAF_ID, external_id=viaf_cluster_id),
            reference=ViafInferredFromReference(wd.PID_VIAF_ID, viaf_cluster_id),
        )
        wdpage.summary = f"Adding VIAF ID based on {auth_src.description}"
        wdpage.apply()


def main() -> None:

    authsrcs = viaf.authsource.AuthoritySources()
    # nothing found:
    #              : PID_FAST_ID
    #              : PID_CONOR_SI_ID
    #              : PID_PERSEUS_AUTHOR_ID
    # lots of not found: PID_BIBLIOTECA_NACIONAL_DE_ESPANA_ID; PID_ISNI
    # niets gevonden: PID_EGAXA_ID; PID_BNRM_ID
    # done; PID_IDREF_ID; PID_GND_ID; PID_SBN_AUTHOR_ID; PID_NL_CR_AUT_ID; PID_VATICAN_LIBRARY_VCBA_ID; PID_NATIONAL_LIBRARY_OF_KOREA_ID
    #       PID_BNMM_AUTHORITY_ID; PID_NSK_ID; PID_LIBRARIES_AUSTRALIA_ID; PID_NATIONAL_LIBRARY_OF_BRAZIL_ID
    #       PID_CANADIANA_NAME_AUTHORITY_ID; PID_RISM_ID; PID_NORAF_ID; PID_NATIONAL_LIBRARY_OF_IRELAND_ID
    #       PID_LEBANESE_NATIONAL_LIBRARY_ID; PID_NATIONAL_LIBRARY_OF_ICELAND_ID
    #       PID_NATIONALE_THESAURUS_VOOR_AUTEURSNAMEN_ID; PID_NDL_AUTHORITY_ID; PID_RERO_ID_OBSOLETE
    #       PID_PORTUGUESE_NATIONAL_LIBRARY_AUTHOR_ID; PID_PLWABN_ID; PID_CANTIC_ID; PID_BANQ_AUTHORITY_ID; PID_RILM_ID
    #       PID_ELNET_ID; PID_DBC_AUTHOR_ID; PID_CINII_BOOKS_AUTHOR_ID; PID_NATIONAL_LIBRARY_OF_RUSSIA_ID
    #       PID_CYT_CCS; PID_NATIONAL_LIBRARY_OF_LATVIA_ID; PID_LIBRIS_URI; PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID
    #       PID_SYRIAC_BIOGRAPHICAL_DICTIONARY_ID; PID_NUKAT_ID; PID_NATIONAL_LIBRARY_OF_CHILE_ID

    bot = viaf.viaf.ViafBot(
        authsrcs.get(viaf.authsource.PID_LIBRARY_OF_CONGRESS_AUTHORITY_ID),
        report=FirebirdViafReporting(),
    )
    bot.test = False
    bot.run()
    # bot.generate_dup_report()
    # bot.generate_report()
    # bot.end_session()


if __name__ == "__main__":
    main()
