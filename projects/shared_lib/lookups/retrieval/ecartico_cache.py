from pathlib import Path
from typing import Optional, Tuple

from shared_lib.database_handler import DatabaseHandler
from shared_lib.lookups.interfaces.ecartico_lookup_interface import (
    EcarticoLookupAddInterface,
)


class EcarticoCache(DatabaseHandler, EcarticoLookupAddInterface):
    def __init__(self):
        file_path = Path(__file__).parent / "ecartico.json"
        create_script = Path("schemas/ecartico.sql")
        super().__init__(file_path, create_script)

    def get_person_qid(self, ecartico_id: str) -> Optional[str]:
        sql = f"SELECT QID FROM PERSONS WHERE ECARTICO_ID=?"
        for row in self.execute_query(sql, (ecartico_id,)):
            return row[0]
        return None

    def get_place_qid(self, place_id: str) -> Optional[str]:
        sql = f"SELECT QID FROM PLACES WHERE PLACE_ID=?"
        for row in self.execute_query(sql, (place_id,)):
            return row[0]
        return None

    def get_occupation_qid(self, occupation_id: str) -> Optional[str]:
        sql = f"SELECT QID FROM OCCUPATIONS WHERE OCCUPATION_ID=?"
        for row in self.execute_query(sql, (occupation_id,)):
            return row[0]
        return None

    def get_occupation(self, occupation_id: str) -> tuple[Optional[str], str]:
        sql = f"SELECT QID FROM OCCUPATIONS WHERE OCCUPATION_ID=?"
        for row in self.execute_query(sql, (occupation_id,)):
            return row[0]
        return None

    def get_source_qid(self, source_id: str) -> Optional[str]:
        sql = f"SELECT QID FROM SOURCES WHERE SOURCE_ID=?"
        for row in self.execute_query(sql, (source_id,)):
            return row[0]
        return None

    def get_religion_qid(self, text: str) -> Optional[str]:
        sql = f"SELECT QID FROM RELIGIONS WHERE RELIGION=?"
        for row in self.execute_query(sql, (text,)):
            return row[0]
        return None

    def get_genre_qid(self, attribute: str, value: str) -> Optional[str]:
        sql = f"SELECT QID FROM GENRES WHERE ATTRIBUTE=? AND TEXT=?"
        for row in self.execute_query(sql, (attribute, value)):
            return row[0]
        return None

    def add_genre(self, attribute: str, value: str, qid: str) -> None:

        sql = "execute procedure add_genre(?, ?, ?)"
        t = (attribute, value, qid)

        self.execute_procedure(sql, t)

    def add_religion(self, religion: str, qid: str) -> None:

        sql = "execute procedure add_religion(?, ?)"
        t = (religion, qid)

        self.execute_procedure(sql, t)

    def get_patronym_qid(self, text: str) -> Optional[str]:
        sql = f"SELECT QID FROM PATRONYMS WHERE PATRONYM=?"
        for row in self.execute_query(sql, (text,)):
            return row[0]
        return None

    def add_patronym(self, text: str, qid: str) -> None:

        sql = "execute procedure add_patronym(?, ?)"
        t = (text, qid)

        self.execute_procedure(sql, t)

    def get_occupation_type(self, qid: str) -> Optional[str]:
        sql = f"SELECT OCCUPATION_TYPE FROM OCCUPATION_TYPES WHERE QID=?"
        for row in self.execute_query(sql, (qid,)):
            return row[0]
        return None

    def add_occupation_type(self, qid: str, description: str, text: str) -> None:

        if not description:
            sql = "execute procedure add_occupation_type(?, NULL, ?)"
            t = (qid, text)
        else:
            sql = "execute procedure add_occupation_type(?, ?, ?)"
            t = (qid, description, text)

        self.execute_procedure(sql, t)

    def add_person_qid(
        self, ecartico_id: Optional[str], description: Optional[str], qid: Optional[str]
    ):

        if not description:
            sql = "execute procedure add_person(?, NULL, ?)"
            t = (ecartico_id, qid)
        else:
            sql = "execute procedure add_person(?, ?, ?)"
            t = (ecartico_id, description, qid)

        self.execute_procedure(sql, t)

    def add_place(self, place_id: str, description: str, qid: str):

        if not description:
            sql = "execute procedure add_place(?, NULL, ?)"
            t = (int(place_id), qid)
        else:
            sql = "execute procedure add_place(?, ?, ?)"
            t = (int(place_id), description, qid)

        self.execute_procedure(sql, t)

    def add_occupation(self, occupation_id, description: str, qid: str):

        if not description:
            sql = "execute procedure add_occupation(?, NULL, ?)"
            t = (int(occupation_id), qid)
        else:
            sql = "execute procedure add_occupation(?, ?, ?)"
            t = (int(occupation_id), description, qid)

        self.execute_procedure(sql, t)

    def get_rkdimage_qid(self, rkdimage_id: str) -> Optional[str]:
        sql = f"SELECT QID FROM RKDIMAGES WHERE RKDIMAGE_ID=?"
        for row in self.execute_query(sql, (rkdimage_id,)):
            return row[0]
        return None

    def add_rkdimage_qid(self, rkdimage_id: str, qid: str) -> None:

        sql = "execute procedure add_rkdimage(?, ?)"
        t = (int(rkdimage_id), qid)

        self.execute_procedure(sql, t)

    def get_qid_from_rijksmuseum_inventory_number(
        self, inventory_number: str
    ) -> Optional[str]:
        sql = f"SELECT QID FROM INVENTORYNRS WHERE INVENTORYNR=?"
        for row in self.execute_query(sql, (inventory_number,)):
            return row[0]
        return None

    def add_rijksmuseum_inventory_number_qid(
        self, inventory_number: str, qid: str
    ) -> None:

        sql = "execute procedure add_inventorynr(?, ?)"
        t = (inventory_number, qid)

        self.execute_procedure(sql, t)

    def get_qid_from_gutenberg_ebook_id(self, ebook_id: str) -> Optional[str]:
        sql = f"SELECT QID FROM EBOOKIDS WHERE EBOOKID=?"
        for row in self.execute_query(sql, (ebook_id,)):
            return row[0]
        return None

    def add_gutenberg_ebook_id_qid(self, ebook_id: str, qid: str) -> None:

        sql = "execute procedure add_ebookid(?, ?)"
        t = (ebook_id, qid)

        self.execute_procedure(sql, t)

    def add_source(self, source_id: int, description: str, qid: str):

        if not description:
            sql = "execute procedure add_source(?, NULL, ?)"
            t = (int(source_id), qid)
        else:
            shortened_description = description[:255]
            sql = "execute procedure add_source(?, ?, ?)"
            t = (int(source_id), shortened_description, qid)

        self.execute_procedure(sql, t)

    def add_error(self, qid: str, msg: str):

        shortened_msg = msg[:255]

        sql = "execute procedure add_error(?, ?)"
        t = (qid, shortened_msg)

        self.execute_procedure(sql, t)

    def add_done(self, qid: str):

        sql = "execute procedure add_done(?)"
        t = (qid,)

        self.execute_procedure(sql, t)

    def has_error(self, qid: str) -> bool:
        sql = "SELECT QCODE FROM QERROR WHERE QCODE=?"
        is_done = False
        for row in self.execute_query(sql, (qid,)):
            found = row[0]
            is_done = found == qid
            break
        return is_done

    def has_done(self, qid: str) -> bool:
        sql = "SELECT QCODE FROM QDONE WHERE QCODE=?"
        is_done = False
        for row in self.execute_query(sql, (qid,)):
            found = row[0]
            is_done = found == qid
            break
        return is_done

    def add_is_possible(self, ecartico_id: str, qid: str):

        sql = "execute procedure add_is_person(?, ?)"
        t = (ecartico_id, qid)

        self.execute_procedure(sql, t)

    def is_possible(self, ecartico_id: str, qid: str) -> bool:
        sql = "SELECT POSSIBLE FROM IS_PERSON WHERE ecartico_id=? AND qid=?"
        b = True
        for row in self.execute_query(sql, (ecartico_id, qid)):
            b = row[0]
            break
        return b

    def get_place(self, place_id: str) -> tuple[Optional[str], str]:
        pass

    def get_source(self, source_id: str) -> tuple[Optional[str], str]:
        pass

    def get_gutenberg_qid(self, ebook_id: Optional[str]):
        pass

    def get_rijksmuseum_qid(
        self, url: str, inventory_number: Optional[str]
    ) -> Optional[str]:
        pass
