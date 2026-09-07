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

    def __init__(
        self, config_filename: str | Path, create_script: str | Path | None = None
    ) -> None:
        # Reused across execute_* calls so the hot path (the bot runs ~6 skip
        # checks per item) doesn't pay a fresh TCP + auth handshake per query.
        self._conn = None
        super().__init__(config_filename, create_script)

    def get_connection(self):
        return pymysql.connect(
            host=self.config["DB_HOST"],
            port=int(self.config.get("DB_PORT", 3306)),
            user=self.config["DB_USER"],
            password=self.config["DB_PASSWORD"],
            database=self.config["DB_NAME"],
            charset="utf8mb4",
        )

    def _acquire_connection(self):
        # Keep one connection alive across calls instead of reconnecting per
        # query. ping(reconnect=True) transparently revives a connection the
        # server dropped (idle timeout), so callers still see a live handle.
        # autocommit keeps each statement in its own transaction, so reads
        # always see the latest committed data -- matching the old
        # connection-per-query behaviour now that the connection is reused.
        # (get_connection itself is left non-autocommit: migration scripts use
        # it directly and rely on their own explicit transactions.)
        if self._conn is None:
            conn = self.get_connection()
            conn.autocommit(True)
            self._conn = conn
        else:
            self._conn.ping(reconnect=True)
        return self._conn

    def _release_connection(self, conn) -> None:
        # Leave the reused connection open; close() disposes of it.
        pass

    def _drain(self, cur) -> None:
        # A CALL to a stored procedure leaves a trailing (empty) result set
        # that, on a reused connection, would otherwise trip 'commands out of
        # sync' on the next statement.
        try:
            while cur.nextset():
                pass
        except Exception:
            pass

    def close(self) -> None:
        conn = getattr(self, "_conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._conn = None

    def __del__(self):
        # Safety net so a forgotten close() doesn't leak the connection.
        self.close()

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
