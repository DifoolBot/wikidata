import json
import os.path
import re
from abc import ABC
from pathlib import Path

from firebird.driver import connect, create_database


def parse_firebird_script(script_text):
    statements = []
    current_term = ";"
    buffer = []

    # Normalize line endings
    lines = script_text.replace("\r\n", "\n").split("\n")

    for line in lines:
        line_strip = line.strip()

        # Detect SET TERM
        pattern = rf"^SET\s+TERM\s+(.+?)\s+{current_term}$"
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


class DatabaseHandler(ABC):
    def __init__(self, config_filename, create_script=None):
        if not os.path.exists(config_filename):
            if create_script:
                self.ask_and_create_config(config_filename, create_script)

        if os.path.exists(config_filename):
            # Initialize any required properties here
            with open(config_filename) as f:
                self.config = json.load(f)
        else:
            raise FileNotFoundError(
                f"Configuration file '{config_filename}' not found."
            )

    def get_connection(self):
        # Establish a connection
        conn = connect(
            self.config["DB_HOST"],
            user=self.config["DB_USER"],
            password=self.config["DB_PASSWORD"],
            charset="UTF8",
        )
        return conn

    def ask_and_create_config(self, config_filename: str, create_script):
        if os.path.exists(create_script):
            # Initialize any required properties here
            with open(create_script, "r", encoding="utf-8") as f:
                script = f.read()
        else:
            raise FileNotFoundError(f"Create script '{create_script}' not found.")

        print(
            f"Configuration file {config_filename} not found. Please provide the following details:"
        )
        example = Path(create_script).name.replace(".sql", ".fdb").lower()

        server = input("Server (e.g., localhost): ").strip()
        user = input("User name: ").strip()
        password = input("Password: ").strip()
        path = input(f"Database path (e.g. C:\\data\\{example}): ").strip()

        database = f"{server}:{path}"
        # Create the database if it doesn't exist
        try:
            conn = create_database(
                database=database, user=user, password=password, charset="UTF8"
            )
            print(f"Database '{path}' created successfully.")

            try:
                parsed_statements = parse_firebird_script(script)

                # Execute
                with conn.cursor() as cur:
                    for stmt in parsed_statements:
                        cur.execute(stmt)

                conn.commit()

            finally:
                conn.close()

        except Exception as e:
            print(f"Error creating database: {e}")
            return

        # Save the configuration to a file
        config_data = {
            "DB_HOST": f"{database}",
            "DB_USER": user,
            "DB_PASSWORD": password,
        }
        with open(config_filename, "w") as f:
            json.dump(config_data, f, indent=4)
        print(f"Configuration saved to {config_filename}.")

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
