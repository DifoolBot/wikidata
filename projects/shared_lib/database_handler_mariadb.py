import json
from pathlib import Path

import pymysql

from shared_lib.database_handler_base import DatabaseHandler


class MariaDbDatabaseHandler(DatabaseHandler):
    """MariaDB/MySQL backend, intended for running on Toolforge.

    Uses PyMySQL (pure Python, no compiled client library needed). Config
    keys: DB_HOST, DB_PORT (optional, default 3306), DB_USER, DB_PASSWORD,
    DB_NAME.
    """

    def get_connection(self):
        return pymysql.connect(
            host=self.config["DB_HOST"],
            port=int(self.config.get("DB_PORT", 3306)),
            user=self.config["DB_USER"],
            password=self.config["DB_PASSWORD"],
            database=self.config["DB_NAME"],
            charset="utf8mb4",
        )

    def create_config(self, config_filename: Path, create_script: Path) -> None:
        if not create_script.exists():
            raise FileNotFoundError(f"Create script '{create_script}' not found.")
        script = create_script.read_text(encoding="utf-8")

        print(
            f"Configuration file {config_filename} not found. Please provide the following details:"
        )

        server = input("Server (e.g., localhost or tools.db.svc.wikimedia.cloud): ").strip()
        port = input("Port (default 3306): ").strip() or "3306"
        user = input("User name: ").strip()
        password = input("Password: ").strip()
        database = input("Database name: ").strip()

        try:
            conn = pymysql.connect(
                host=server,
                port=int(port),
                user=user,
                password=password,
                charset="utf8mb4",
            )
            try:
                with conn.cursor() as cur:
                    cur.execute(f"CREATE DATABASE IF NOT EXISTS `{database}`")
                conn.commit()
                conn.select_db(database)

                # Naive statement split on ';'. Scripts using DELIMITER (e.g. to
                # define stored procedures) need to be applied manually instead.
                statements = [s.strip() for s in script.split(";") if s.strip()]
                with conn.cursor() as cur:
                    for stmt in statements:
                        cur.execute(stmt)
                conn.commit()
                print(f"Database '{database}' created successfully.")
            finally:
                conn.close()

        except Exception as e:
            print(f"Error creating database: {e}")
            return

        config_data = {
            "DB_HOST": server,
            "DB_PORT": port,
            "DB_USER": user,
            "DB_PASSWORD": password,
            "DB_NAME": database,
        }
        config_filename.write_text(json.dumps(config_data, indent=4))
        print(f"Configuration saved to {config_filename}.")

    def has_record(self, table: str, condition: str, params: tuple) -> bool:
        sql = f"SELECT 1 FROM {table} WHERE {condition} LIMIT 1"
        result = self.execute_query(sql, params)
        return len(result) > 0

    def upsert(self, table: str, values: dict, key_columns: list[str]) -> None:
        """Insert a row, or update it if one with the same key already exists."""
        columns = list(values.keys())
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join(
            f"{c}=VALUES({c})" for c in columns if c not in key_columns
        )
        if not updates:  # all columns are key columns -> no-op update
            updates = f"{key_columns[0]}={key_columns[0]}"
        sql = (
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON DUPLICATE KEY UPDATE {updates}"
        )
        self.execute_procedure(sql, tuple(values.values()))

    def _adapt_sql(self, sql: str) -> str:
        return sql.replace("?", "%s")
