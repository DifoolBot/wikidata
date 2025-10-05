from firebird.driver import connect

# from reporting import Reporting
# from filelock import FileLock
from ecartico.interface_ecartico_data import IEcarticoData


class EcarticoData(IEcarticoData):

    def get_connection(self):
        # Establish a connection
        conn = connect(
            r"localhost:D:\data\ecartico.fdb",
            user="sysdba",
            password="remko",
            charset="UTF8",
        )
        return conn

    def get_person_qid(self, ecartico_id: str) -> str:
        conn = self.get_connection()

        cur = conn.cursor()

        sql = f"SELECT QID FROM PERSONS WHERE ECARTICO_ID=?"
        t = (ecartico_id,)
        cur.execute(sql, t)

        res = None
        for row in cur.fetchall():
            res = row[0]
            break

        conn.close()

        return res

    def get_place_qid(self, place_id: str) -> str:
        conn = self.get_connection()

        cur = conn.cursor()

        sql = f"SELECT QID FROM PLACES WHERE PLACE_ID=?"
        t = (place_id,)
        cur.execute(sql, t)

        res = None
        for row in cur.fetchall():
            res = row[0]
            break

        conn.close()

        return res

    def get_occupation_qid(self, occupation_id: str) -> str:
        conn = self.get_connection()

        cur = conn.cursor()

        sql = f"SELECT QID FROM OCCUPATIONS WHERE OCCUPATION_ID=?"
        t = (occupation_id,)
        cur.execute(sql, t)

        res = None
        for row in cur.fetchall():
            res = row[0]
            break

        conn.close()

        return res

    def get_source_qid(self, source_id: str) -> str:
        conn = self.get_connection()

        cur = conn.cursor()

        sql = f"SELECT QID FROM SOURCES WHERE SOURCE_ID=?"
        t = (source_id,)
        cur.execute(sql, t)

        res = None
        for row in cur.fetchall():
            res = row[0]
            break

        conn.close()

        return res

    def get_religion_qid(self, text: str) -> str:
        conn = self.get_connection()

        cur = conn.cursor()

        sql = f"SELECT QID FROM RELIGIONS WHERE RELIGION=?"
        t = (text,)
        cur.execute(sql, t)

        res = None
        for row in cur.fetchall():
            res = row[0]
            break

        conn.close()

        return res

    def get_genre_qid(self, attribute: str, value: str) -> str:
        conn = self.get_connection()

        cur = conn.cursor()

        sql = f"SELECT QID FROM GENRES WHERE ATTRIBUTE=? AND TEXT=?"
        t = (
            attribute,
            value,
        )
        cur.execute(sql, t)

        res = None
        for row in cur.fetchall():
            res = row[0]
            break

        conn.close()

        return res

    def add_genre_qid(self, attribute: str, value: str, qid: str) -> None:
        conn = self.get_connection()
        cur = conn.cursor()

        sql = "execute procedure add_genre(?, ?, ?)"
        t = (attribute, value, qid)
        cur.execute(sql, t)

        # The changes will not be saved unless the transaction is committed explicitly:
        conn.commit()
        conn.close()

    def add_religion_qid(self, religion: str, qid: str) -> None:
        conn = self.get_connection()
        cur = conn.cursor()

        sql = "execute procedure add_religion(?, ?)"
        t = (religion, qid)
        cur.execute(sql, t)

        # The changes will not be saved unless the transaction is committed explicitly:
        conn.commit()
        conn.close()

    def get_patronym_qid(self, text: str) -> str:
        conn = self.get_connection()

        cur = conn.cursor()

        sql = f"SELECT QID FROM PATRONYMS WHERE PATRONYM=?"
        t = (text,)
        cur.execute(sql, t)

        res = None
        for row in cur.fetchall():
            res = row[0]
            break

        conn.close()

        return res

    def add_patronym_qid(self, text: str, qid: str) -> None:
        conn = self.get_connection()
        cur = conn.cursor()

        sql = "execute procedure add_patronym(?, ?)"
        t = (text, qid)
        cur.execute(sql, t)

        # The changes will not be saved unless the transaction is committed explicitly:
        conn.commit()
        conn.close()

    def get_occupation_type(self, qid: str) -> str:
        conn = self.get_connection()

        cur = conn.cursor()

        sql = f"SELECT OCCUPATION_TYPE FROM OCCUPATION_TYPES WHERE QID=?"
        t = (qid,)
        cur.execute(sql, t)

        res = None
        for row in cur.fetchall():
            res = row[0]
            break

        conn.close()

        return res

    def add_occupation_type(self, qid: str, description: str, text: str) -> None:
        conn = self.get_connection()
        cur = conn.cursor()

        if not description:
            sql = "execute procedure add_occupation_type(?, NULL, ?)"
            t = (qid, text)
        else:
            sql = "execute procedure add_occupation_type(?, ?, ?)"
            t = (qid, description, text)
        cur.execute(sql, t)

        # The changes will not be saved unless the transaction is committed explicitly:
        conn.commit()
        conn.close()

    def add_person_qid(self, ecartico_id, description: str, qid: str):
        conn = self.get_connection()
        cur = conn.cursor()

        if not description:
            sql = "execute procedure add_person(?, NULL, ?)"
            t = (int(ecartico_id), qid)
        else:
            sql = "execute procedure add_person(?, ?, ?)"
            t = (int(ecartico_id), description, qid)
        cur.execute(sql, t)

        # The changes will not be saved unless the transaction is committed explicitly:
        conn.commit()
        conn.close()

    def add_place_qid(self, place_id: str, description: str, qid: str):
        conn = self.get_connection()
        cur = conn.cursor()

        if not description:
            sql = "execute procedure add_place(?, NULL, ?)"
            t = (int(place_id), qid)
        else:
            sql = "execute procedure add_place(?, ?, ?)"
            t = (int(place_id), description, qid)
        cur.execute(sql, t)

        # The changes will not be saved unless the transaction is committed explicitly:
        conn.commit()
        conn.close()

    def add_occupation_qid(self, occupation_id, description: str, qid: str):
        conn = self.get_connection()
        cur = conn.cursor()

        if not description:
            sql = "execute procedure add_occupation(?, NULL, ?)"
            t = (int(occupation_id), qid)
        else:
            sql = "execute procedure add_occupation(?, ?, ?)"
            t = (int(occupation_id), description, qid)
        cur.execute(sql, t)

        # The changes will not be saved unless the transaction is committed explicitly:
        conn.commit()
        conn.close()

    def get_rkdimage_qid(self, rkdimage_id: str) -> str:
        conn = self.get_connection()

        cur = conn.cursor()

        sql = f"SELECT QID FROM RKDIMAGES WHERE RKDIMAGE_ID=?"
        t = (rkdimage_id,)
        cur.execute(sql, t)

        res = None
        for row in cur.fetchall():
            res = row[0]
            break

        conn.close()

        return res

    def add_rkdimage_qid(self, rkdimage_id: str, qid: str) -> None:
        conn = self.get_connection()
        cur = conn.cursor()

        sql = "execute procedure add_rkdimage(?, ?)"
        t = (int(rkdimage_id), qid)
        cur.execute(sql, t)

        # The changes will not be saved unless the transaction is committed explicitly:
        conn.commit()
        conn.close()

    def get_qid_from_rijksmuseum_inventory_number(self, inventory_number: str) -> str:
        conn = self.get_connection()

        cur = conn.cursor()

        sql = f"SELECT QID FROM INVENTORYNRS WHERE INVENTORYNR=?"
        t = (inventory_number,)
        cur.execute(sql, t)

        res = None
        for row in cur.fetchall():
            res = row[0]
            break

        conn.close()

        return res

    def add_rijksmuseum_inventory_number_qid(
        self, inventory_number: str, qid: str
    ) -> None:
        conn = self.get_connection()
        cur = conn.cursor()

        sql = "execute procedure add_inventorynr(?, ?)"
        t = (inventory_number, qid)
        cur.execute(sql, t)

        # The changes will not be saved unless the transaction is committed explicitly:
        conn.commit()
        conn.close()

    def get_qid_from_gutenberg_ebook_id(self, ebook_id: str) -> str:
        conn = self.get_connection()

        cur = conn.cursor()

        sql = f"SELECT QID FROM EBOOKIDS WHERE EBOOKID=?"
        t = (ebook_id,)
        cur.execute(sql, t)

        res = None
        for row in cur.fetchall():
            res = row[0]
            break

        conn.close()

        return res

    def add_gutenberg_ebook_id_qid(self, ebook_id: str, qid: str) -> None:
        conn = self.get_connection()
        cur = conn.cursor()

        sql = "execute procedure add_ebookid(?, ?)"
        t = (ebook_id, qid)
        cur.execute(sql, t)

        # The changes will not be saved unless the transaction is committed explicitly:
        conn.commit()
        conn.close()

    def add_source_qid(self, source_id: int, description: str, qid: str):
        conn = self.get_connection()
        cur = conn.cursor()

        if not description:
            sql = "execute procedure add_source(?, NULL, ?)"
            t = (int(source_id), qid)
        else:
            shortened_description = description[:255]
            sql = "execute procedure add_source(?, ?, ?)"
            t = (int(source_id), shortened_description, qid)
        cur.execute(sql, t)

        # The changes will not be saved unless the transaction is committed explicitly:
        conn.commit()
        conn.close()

    def add_error(self, qid: str, msg: str):
        conn = self.get_connection()
        cur = conn.cursor()

        shortened_msg = msg[:255]

        # new_data = [
        #     (qid,  shortened_msg),
        # ]

        sql = "execute procedure add_error(?, ?)"
        t = (
            qid,
            shortened_msg,
        )
        cur.execute(sql, t)
        # cur.executemany("INSERT INTO QERROR (QCODE,ERROR) VALUES (?, ?)",
        #     new_data
        # )
        # The changes will not be saved unless the transaction is committed explicitly:
        conn.commit()
        conn.close()

    def add_done(self, qid: str):
        conn = self.get_connection()
        cur = conn.cursor()

        sql = "execute procedure add_done(?)"
        t = (qid,)
        cur.execute(sql, t)
        conn.commit()
        conn.close()

    def has_error(self, qid: str) -> bool:
        conn = self.get_connection()
        cur = conn.cursor()

        sql = "SELECT QCODE FROM QERROR WHERE QCODE=?"
        t = (qid,)
        cur.execute(sql, t)

        is_done = False
        for row in cur.fetchall():
            found = row[0]
            is_done = found == qid
            break

        conn.close()

        return is_done

    def has_done(self, qid: str) -> bool:
        conn = self.get_connection()
        cur = conn.cursor()

        sql = "SELECT QCODE FROM QDONE WHERE QCODE=?"
        t = (qid,)
        cur.execute(sql, t)

        is_done = False
        for row in cur.fetchall():
            found = row[0]
            is_done = found == qid
            break

        conn.close()

        return is_done

    def add_is_possible(self, ecartico_id: str, qid: str):
        conn = self.get_connection()
        cur = conn.cursor()

        sql = "execute procedure add_is_person(?, ?)"
        t = (ecartico_id, qid)
        cur.execute(sql, t)
        conn.commit()
        conn.close()

    def is_possible(self, ecartico_id: str, qid: str) -> bool:
        conn = self.get_connection()
        cur = conn.cursor()

        sql = "SELECT POSSIBLE FROM IS_PERSON WHERE ecartico_id=? AND qid=?"
        t = (ecartico_id, qid)
        cur.execute(sql, t)

        b = True
        for row in cur.fetchall():
            b = row[0]
            break

        conn.close()

        return b
