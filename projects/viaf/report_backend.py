"""The reporting contract: what the bot needs from a database, and the state it
keeps there.

Deliberately free of pywikibot. The concrete backends (firebird_viaf_reporting,
mariadb_viaf_reporting) implement ReportBackend, and importing viaf_bot for
these two names used to drag in shared_lib.wikidata_site -- which logs in and
fetches a CSRF write token at import time. That made database-only tools
(codes_sync without --descriptions, migrate_progress_to_db) open an
authenticated Wikidata session just to talk to the database, and stall on
maxlag when Wikidata was busy.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class BotState:
    """The bot's place in its pass over the authority sources (the STATE row).

    current_pid          source to process next (None before the first ever run)
    cooldown_until       no work until this date, set after a full pass completes
    session_start        when current_pid's qlever file was fetched
    total_rows           rows that file held when fetched
    remaining_rows       rows still unprocessed
    descriptions_synced  when CODES.DESCRIPTION last came from Wikidata
    """

    current_pid: str | None = None
    cooldown_until: date | None = None
    session_start: date | None = None
    total_rows: int | None = None
    remaining_rows: int | None = None
    descriptions_synced: date | None = None


class ReportBackend(ABC):
    @abstractmethod
    def has_duplicate(self, qid: str) -> bool:
        pass

    @abstractmethod
    def has_duplicate_local_auth_id(self, qid: str) -> bool:
        pass

    @abstractmethod
    def has_done(self, qid: str) -> bool:
        pass

    @abstractmethod
    def has_error(self, qid: str) -> bool:
        pass

    @abstractmethod
    def has_ignore(self, qid: str) -> bool:
        pass

    @abstractmethod
    def add_duplicate(
        self, qid: str, duplicate_qid: str, local_auth_id: str | None, viaf_id: str
    ) -> None:
        pass

    @abstractmethod
    def add_duplicate_local_auth_id(
        self, qid: str, local_auth_id: str, viaf_cluster_id: str | None
    ) -> None:
        pass

    @abstractmethod
    def add_error(self, qid: str, msg: str) -> None:
        pass

    @abstractmethod
    def add_done(self, qid: str) -> None:
        pass

    @abstractmethod
    def add_not_found(self, qid: str, pid: str) -> None:
        pass

    @abstractmethod
    def has_recent_not_found(self, qid: str, pid: str, cutoff: datetime) -> bool:
        pass

    @abstractmethod
    def purge_not_found_before(self, cutoff: datetime) -> None:
        pass

    @abstractmethod
    def count_duplicates(self) -> int:
        pass

    @abstractmethod
    def get_duplicates(self) -> list[tuple[str, str, str, str]]:
        pass

    @abstractmethod
    def get_duplicate_local_auth_ids(self) -> Iterator[tuple[str, set[str], str]]:
        pass

    @abstractmethod
    def get_stats(self) -> tuple[int, int, int] | None:
        pass

    @abstractmethod
    def run_maintenance(self) -> None:
        """Housekeeping run at daily start and before publishing a report
        (retry transient errors, normalize/de-duplicate the duplicate-locals)."""
        pass

    @abstractmethod
    def end_session(self, pid: str) -> None:
        pass

    @abstractmethod
    def get_state(self) -> BotState:
        """The single STATE row: where the bot is in its pass over the sources."""
        pass

    @abstractmethod
    def save_progress(self, current_pid: str, cooldown_until: date | None) -> None:
        """Record which source to run next, and any cooldown before restarting."""
        pass

    @abstractmethod
    def start_source_session(self, pid: str, total_rows: int) -> None:
        """Record that a fresh qlever file of *total_rows* rows was just fetched
        for *pid*: the moment the row count is knowable, since later runs read an
        already-truncated file."""
        pass

    @abstractmethod
    def set_remaining_rows(self, remaining: int) -> None:
        """Update how many qlever rows are still unprocessed."""
        pass

    @abstractmethod
    def set_descriptions_synced(self, day: date) -> None:
        """Record that CODES.DESCRIPTION was just refreshed from Wikidata."""
        pass
