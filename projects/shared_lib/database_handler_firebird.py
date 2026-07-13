import json
import re
from pathlib import Path

from firebird.driver import connect, create_database

from shared_lib.database_handler_base import DatabaseHandler


def parse_firebird_script(script_text: str) -> list[str]:
    statements = []
    current_term = ";"
    buffer = []

    # Normalize line endings
    lines = script_text.replace("\r\n", "\n").split("\n")

    for line in lines:
        line_strip = line.strip()

        # Detect SET TERM
        pattern = rf"^SET\s+TERM\s+(.+?)\s+\{current_term}$"
        match = re.match(pattern, line_strip, re.IGNORECASE)
        if match:
            current_term = match.group(1)
            continue

        is_empty = not line_strip or (
            line_strip.startswith("/*") and line_strip.endswith("*/")
        )
        if buffer or not is_empty:
            buffer.append(line)

        # Check if line ends with the current terminator
        if line_strip.endswith(current_term):
            # Remove terminator from the last line
            buffer[-1] = buffer[-1].rstrip(current_term).rstrip()
            statement = "\n".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []

    # Final flush
    if buffer:
        statement = "\n".join(buffer).strip()
        if statement:
            statements.append(statement)

    return statements


class FirebirdDatabaseHandler(DatabaseHandler):
    def get_connection(self):
        return connect(
            self.config["DB_HOST"],
            user=self.config["DB_USER"],
            password=self.config["DB_PASSWORD"],
            charset="UTF8",
        )

    def create_config(self, config_filename: Path, create_script: Path) -> None:
        if not create_script.exists():
            raise FileNotFoundError(f"Create script '{create_script}' not found.")
        script = create_script.read_text(encoding="utf-8")

        print(
            f"Configuration file {config_filename} not found. Please provide the following details:"
        )
        example = create_script.name.replace(".sql", ".fdb").lower()

        server = input("Server (e.g., localhost): ").strip()
        user = input("User name: ").strip()
        password = input("Password: ").strip()
        path = input(f"Database path (e.g. C:\\data\\{example}): ").strip()

        database = f"{server}:{path}"
        try:
            conn = create_database(
                database=database, user=user, password=password, charset="UTF8"
            )
            print(f"Database '{path}' created successfully.")

            try:
                with conn.cursor() as cur:
                    for stmt in parse_firebird_script(script):
                        cur.execute(stmt)
                conn.commit()
            finally:
                conn.close()

        except Exception as e:
            print(f"Error creating database: {e}")
            return

        config_data = {
            "DB_HOST": database,
            "DB_USER": user,
            "DB_PASSWORD": password,
        }
        config_filename.write_text(json.dumps(config_data, indent=4))
        print(f"Configuration saved to {config_filename}.")

    def has_record(self, table: str, condition: str, params: tuple) -> bool:
        sql = f"SELECT FIRST 1 * FROM {table} WHERE {condition}"
        result = self.execute_query(sql, params)
        return len(result) > 0

    def upsert(self, table: str, values: dict, key_columns: list[str]) -> None:
        """Insert a row, or update it if one with the same key already exists."""
        columns = list(values.keys())
        placeholders = ", ".join("?" for _ in columns)
        sql = (
            f"UPDATE OR INSERT INTO {table} ({', '.join(columns)}) "
            f"VALUES ({placeholders}) MATCHING ({', '.join(key_columns)})"
        )
        self.execute_procedure(sql, tuple(values.values()))
