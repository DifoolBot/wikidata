from pathlib import Path
from typing import Optional, Tuple

from pywikibot.data import sparql
from shared_lib.database_handler import DatabaseHandler
from shared_lib.lookups.interfaces.place_lookup_interface import (
    CountryLookupInterface,
    PlaceLookupInterface,
)


class DBCache(DatabaseHandler, PlaceLookupInterface, CountryLookupInterface):
    def __init__(self):
        file_path = Path(__file__).parent / "wd_cache.json"
        create_script = Path("schemas/wikidata_cache.sql")
        super().__init__(file_path, create_script)

    def get_place_by_qid(self, qid: str) -> Optional[Tuple[str, str, str]]:
        sql = f"SELECT FIRST 1 PLACE_QID, COUNTRY_QID, PLACE_LABEL FROM PLACES WHERE PLACE_QID=?"
        for row in self.execute_query(sql, (qid,)):
            return row[0], row[1], row[2]
        return None

    def normalized_place_text(self, text: str) -> str:
        text = text.replace(",", ", ")
        text = text.replace("  ", " ")
        return text.strip(" ,")

    def get_place_qid_by_desc(self, desc: str) -> Optional[Tuple[str, str, str]]:
        sql = """
                INSERT INTO place_external_descriptions (external_text)
                SELECT ?
                FROM RDB$DATABASE
                WHERE NOT EXISTS (
                    SELECT *
                    FROM place_external_descriptions
                    WHERE 
                    UPPER(external_text) = UPPER(?))
                    """
        normalized = self.normalized_place_text(desc)
        if not normalized:
            return None
        self.execute_procedure(sql, (normalized, normalized))
        sql = "SELECT FIRST 1 PLACE_QID FROM place_external_descriptions WHERE UPPER(external_text)=UPPER(?)"
        for row in self.execute_query(sql, (normalized,)):
            return row[0]
        return None

    def set_place(self, place_qid: str, country_qid: str, place_label: str):
        if not place_qid:
            raise RuntimeError("No place qid")
        sql = (
            f"INSERT INTO PLACES (PLACE_QID, COUNTRY_QID, PLACE_LABEL) VALUES (?, ?, ?)"
        )
        self.execute_procedure(sql, (place_qid, country_qid, place_label))

    def get_country_by_qid(self, qid: str) -> Optional[Tuple[str, str, str]]:
        if not qid:
            return None
        sql = "SELECT FIRST 1 COUNTRY_QID, COUNTRY_CODE, COUNTRY_LABEL FROM COUNTRIES WHERE COUNTRY_QID=?"
        for row in self.execute_query(sql, (qid,)):
            return row[0], row[1], row[2]
        return None

    def get_country_by_code(self, code: str) -> Optional[Tuple[str, str, str]]:
        if not code:
            return None
        sql = "SELECT FIRST 1 COUNTRY_QID, COUNTRY_CODE, COUNTRY_LABEL FROM COUNTRIES WHERE COUNTRY_CODE=?"
        for row in self.execute_query(sql, (code,)):
            return row[0], row[1], row[2]
        return None

    def set_country(
        self, country_qid: str, country_code: Optional[str], country_label: str
    ):
        if not country_qid:
            raise RuntimeError("No country qid")
        if not country_code:
            country_code = None
        sql = f"INSERT INTO COUNTRIES (COUNTRY_QID, COUNTRY_CODE, COUNTRY_LABEL) VALUES (?, ?, ?)"
        self.execute_procedure(sql, (country_qid, country_code, country_label))
