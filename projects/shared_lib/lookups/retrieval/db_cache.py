from pathlib import Path
from typing import Optional, Tuple

from shared_lib.database_handler import DatabaseHandler
from shared_lib.lookups.interfaces.place_lookup_interface import (
    CountryLookupInterface,
    LanguageLookupInterface,
    PlaceLookupInterface,
)


class DBCache(
    DatabaseHandler,
    PlaceLookupInterface,
    CountryLookupInterface,
    LanguageLookupInterface,
):
    def __init__(self) -> None:
        file_path = Path(__file__).parent / "wd_cache.json"
        create_script = Path("schemas/wikidata_cache.sql")
        super().__init__(file_path, create_script)
        self.ask = True

    def get_place_by_qid(self, qid: str) -> Optional[Tuple[str, str, str]]:
        sql = "SELECT FIRST 1 place_qid, country_qid, place_label FROM places WHERE place_qid=?"
        for row in self.execute_query(sql, (qid,)):
            return row[0], row[1], row[2]
        return None

    def normalized_place_text(self, text: str) -> str:
        text = text.replace(";", ",")
        text = text.replace(",", ", ")
        text = text.replace("  ", " ")
        return text.strip(" ,")

    def get_place_qid_by_desc(self, desc: str) -> Optional[str]:
        sql = """
                INSERT INTO place_external_descriptions (external_text)
                SELECT ?
                FROM rdb$database
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
        sql = "SELECT FIRST 1 place_qid FROM place_external_descriptions WHERE UPPER(external_text)=UPPER(?) AND NOT has_error"
        for row in self.execute_query(sql, (normalized,)):
            qid = row[0]
            if qid and qid.startswith("Q"):
                return qid
        if self.ask:
            qid = input("Enter qid for place description: " + desc + ": ")
            if qid and qid.startswith("Q"):
                sql = "UPDATE place_external_descriptions SET place_qid=? WHERE UPPER(external_text)=UPPER(?)"
                self.execute_procedure(sql, (qid, normalized))
                return qid
        return None

    def set_place(self, place_qid: str, country_qid: str, place_label: str) -> None:
        if not place_qid:
            raise RuntimeError("No place qid")

        data = self.get_place_by_qid(place_qid)
        if data:
            # because of an error, the data in the database might not have a country_qid
            if not country_qid:
                return
            data_place_qid, data_country_qid, data_place_label = data
            if data_country_qid:
                return
            sql = "UPDATE places SET country_qid=? WHERE place_qid=?"
            self.execute_procedure(sql, (country_qid, place_qid))
            return

        sql = (
            "INSERT INTO places (place_qid, country_qid, place_label) VALUES (?, ?, ?)"
        )
        self.execute_procedure(sql, (place_qid, country_qid, place_label))

    def get_country_by_qid(self, qid: str) -> Optional[Tuple[str, str, str]]:
        if not qid:
            return None
        sql = "SELECT FIRST 1 country_qid, country_code, country_label FROM countries WHERE country_qid=?"
        for row in self.execute_query(sql, (qid,)):
            return row[0], row[1], row[2]
        return None

    def get_country_by_code(self, code: str) -> Optional[Tuple[str, str, str]]:
        if not code:
            return None
        sql = "SELECT FIRST 1 country_qid, country_code, country_label FROM countries WHERE country_code=?"
        for row in self.execute_query(sql, (code,)):
            return row[0], row[1], row[2]
        return None

    def set_country(
        self, country_qid: str, country_code: Optional[str], country_label: str
    ) -> None:
        if not country_qid:
            raise RuntimeError("No country qid")
        if not country_code:
            country_code = None
        sql = "INSERT INTO countries (country_qid, country_code, country_label) VALUES (?, ?, ?)"
        self.execute_procedure(sql, (country_qid, country_code, country_label))

    def get_languages_for_country(self, country_qid: str) -> list[str]:
        rows = self.execute_query(
            "SELECT language FROM get_languages(?)", (country_qid,)
        )
        results = []
        for row in rows:
            results.append(row[0])
        return results

    def get_sorted_languages(self) -> list[str]:
        rows = self.execute_query(
            "SELECT language FROM wikis WHERE sort_order IS NOT NULL ORDER BY sort_order"
        )
        result = []
        for row in rows:
            result.append(row[0])
        return result

    def get_wikipedia_qid(self, lang: str) -> Optional[str]:
        rows = self.execute_query(
            "SELECT wikipedia FROM wikis WHERE language=?", (lang,)
        )
        for row in rows:
            return row[0]

        return None
