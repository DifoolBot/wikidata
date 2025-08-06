import json
from abc import ABC

from firebird.driver import connect


class DatabaseHandler(ABC):
    def __init__(self, config_filename):
        # Initialize any required properties here
        with open(config_filename) as f:
            self.config = json.load(f)

    def get_connection(self):
        # Establish a connection
        conn = connect(
            self.config["DB_HOST"],
            user=self.config["DB_USER"],
            password=self.config["DB_PASSWORD"],
            charset="UTF8",
        )
        return conn

    def execute_query(self, sql: str, params: tuple = ()) -> list:
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            result = cur.fetchall()
        finally:
            conn.close()
        return result

    def execute_procedure(self, sql: str, params: tuple = ()):
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(sql, params)
            conn.commit()
        finally:
            conn.close()

    def has_record(self, table: str, condition: str, params: tuple) -> bool:
        sql = f"SELECT FIRST 1 * FROM {table} WHERE {condition}"
        result = self.execute_query(sql, params)
        return len(result) > 0
