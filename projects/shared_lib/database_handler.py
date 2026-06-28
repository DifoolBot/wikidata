"""Backwards-compatible alias for existing call sites.

New code should import the variant it actually needs:
- shared_lib.database_handler_base.DatabaseHandler (abstract base)
- shared_lib.database_handler_firebird.FirebirdDatabaseHandler
- shared_lib.database_handler_mariadb.MariaDbDatabaseHandler
"""

from shared_lib.database_handler_firebird import FirebirdDatabaseHandler as DatabaseHandler

__all__ = ["DatabaseHandler"]
