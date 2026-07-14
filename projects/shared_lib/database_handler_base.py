import json
from abc import ABC, abstractmethod
from pathlib import Path

from shared_lib.config import get_env


class DatabaseHandler(ABC):
    """Backend-independent base for the small per-project tracking/reporting databases.

    Subclasses supply the actual driver connection plus the handful of things
    that aren't portable across backends: how to create a fresh database from
    a schema script, and how to ask "does at least one matching row exist"
    (Firebird's ``SELECT FIRST 1`` vs MariaDB's ``LIMIT 1``).

    Callers write SQL using ``?`` as the placeholder marker, regardless of
    backend; subclasses translate that to the underlying driver's paramstyle
    in :meth:`_adapt_sql`. This does NOT translate dialect-specific SQL such
    as Firebird's ``EXECUTE PROCEDURE`` / ``UPDATE OR INSERT`` statements or
    schema scripts (``SET TERM`` vs ``DELIMITER``) - callers that embed those
    still need backend-specific SQL strings.

    Credentials: config JSONs should only contain the non-secret connection
    details (DB_HOST, DB_PORT, DB_NAME). DB_USER and DB_PASSWORD are taken
    from the WD_DB_USER / WD_DB_PASSWORD variables in the repo-root .env
    when the JSON omits them; a JSON value, if present, still wins.
    """

    def __init__(
        self, config_filename: str | Path, create_script: str | Path | None = None
    ):
        config_path = Path(config_filename)

        if not config_path.exists() and create_script:
            self.create_config(config_path, Path(create_script))

        if not config_path.exists():
            raise FileNotFoundError(
                f"Configuration file '{config_filename}' not found."
            )

        with config_path.open(encoding="utf-8") as f:
            self.config = json.load(f)

        for config_key, env_var in (
            ("DB_USER", "WD_DB_USER"),
            ("DB_PASSWORD", "WD_DB_PASSWORD"),
        ):
            if config_key not in self.config:
                self.config[config_key] = get_env(env_var)

    @abstractmethod
    def get_connection(self):
        """Return a new DB-API 2.0 connection for the configured backend."""
        raise NotImplementedError

    @abstractmethod
    def create_config(self, config_filename: Path, create_script: Path) -> None:
        """Interactively create the database (if needed) and write config_filename."""
        raise NotImplementedError

    @abstractmethod
    def has_record(self, table: str, condition: str, params: tuple) -> bool:
        """Return True if at least one row matching condition exists in table."""
        raise NotImplementedError

    def _adapt_sql(self, sql: str) -> str:
        """Translate the '?' placeholder convention into the driver's paramstyle."""
        return sql

    def execute_query(self, sql: str, params: tuple = ()) -> list:
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            # Pass None (not an empty tuple) when there are no params: PyMySQL
            # only does '%' substitution when params is not None, and a literal
            # '%' in the SQL (e.g. a LIKE pattern) would otherwise raise.
            cur.execute(self._adapt_sql(sql), params or None)
            return cur.fetchall()
        finally:
            conn.close()

    def execute_procedure(self, sql: str, params: tuple = ()) -> None:
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(self._adapt_sql(sql), params or None)
            conn.commit()
        finally:
            conn.close()
