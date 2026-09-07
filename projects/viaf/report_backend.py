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


class WarmSkipReport:
    """Wraps a ReportBackend and serves the per-item skip checks from memory.

    process_record runs six existence checks on *every* qlever row before it
    does anything (has_done / has_duplicate / has_duplicate_local_auth_id /
    has_error / has_ignore / has_recent_not_found). Backed by the database each
    is a round-trip; over thousands of rows that dominates a run that is mostly
    cache hits. :meth:`preload` loads them once per source session into sets, so
    the checks become O(1) memory lookups.

    Writes pass through to the inner backend *and* update the sets, so a qid
    recorded earlier in the same run is still skipped if it recurs (an item with
    two local ids appears on two rows). The set updates mirror the stored
    procedures: ADD_DONE clears any earlier error, ADD_ERROR clears any earlier
    ADDED row. Everything else is delegated to the inner backend unchanged.

    Only used for the per-source bot; standalone backend users (status
    webservice, codes_sync) are unaffected.
    """

    def __init__(self, inner: "ReportBackend") -> None:
        self._inner = inner
        self._warm = False
        self._pid: str | None = None
        self._cutoff: datetime | None = None
        self._done: set[str] = set()
        self._duplicate: set[str] = set()
        self._dup_local: set[str] = set()
        self._error: set[str] = set()
        self._ignore: set[str] = set()
        self._not_found: set[str] = set()

    def __getattr__(self, name: str):
        # Reached only for names not found normally, i.e. everything this
        # wrapper doesn't override -> delegate to the wrapped backend. Guard
        # _inner so an access before __init__ finishes can't recurse forever.
        if name == "_inner":
            raise AttributeError(name)
        return getattr(self._inner, name)

    def preload(self, pid: str, not_found_cutoff: datetime | None) -> None:
        q = self._inner.execute_query
        self._done = {r[0] for r in q("SELECT QID FROM ADDED")}
        self._duplicate = set()
        for qid, dup in q("SELECT QID, DUPLICATE_QID FROM DUPLICATES"):
            self._duplicate.add(qid)
            self._duplicate.add(dup)
        self._dup_local = {
            r[0] for r in q("SELECT QID FROM DUPLICATE_LOCAL_AUTH_IDS")
        }
        # Mirror has_error's 'QID=? AND NOT RETRY': retry-flagged errors are due
        # to be re-tried, so they must NOT count as already-seen.
        self._error = {r[0] for r in q("SELECT QID FROM ERRORS WHERE NOT RETRY")}
        self._ignore = {r[0] for r in q("SELECT QID FROM IGNORED")}
        self._not_found = set()
        if not_found_cutoff is not None:
            self._not_found = {
                r[0]
                for r in q(
                    "SELECT QID FROM NOT_FOUND WHERE PID=? AND CHECKED_DATE >= ?",
                    (pid, not_found_cutoff),
                )
            }
        self._pid = pid
        self._cutoff = not_found_cutoff
        self._warm = True

    # ---- reads: served from the sets once warm -----------------------------
    def has_done(self, qid: str) -> bool:
        return qid in self._done if self._warm else self._inner.has_done(qid)

    def has_duplicate(self, qid: str) -> bool:
        return (
            qid in self._duplicate
            if self._warm
            else self._inner.has_duplicate(qid)
        )

    def has_duplicate_local_auth_id(self, qid: str) -> bool:
        return (
            qid in self._dup_local
            if self._warm
            else self._inner.has_duplicate_local_auth_id(qid)
        )

    def has_error(self, qid: str) -> bool:
        return qid in self._error if self._warm else self._inner.has_error(qid)

    def has_ignore(self, qid: str) -> bool:
        return qid in self._ignore if self._warm else self._inner.has_ignore(qid)

    def has_recent_not_found(self, qid: str, pid: str, cutoff: datetime) -> bool:
        # Only the (pid, cutoff) preloaded for is served from memory; any other
        # combination falls back to the DB so a mismatch can't read a stale set.
        if self._warm and pid == self._pid and cutoff == self._cutoff:
            return qid in self._not_found
        return self._inner.has_recent_not_found(qid, pid, cutoff)

    # ---- writes: keep the sets consistent, then persist --------------------
    def add_done(self, qid: str) -> None:
        self._done.add(qid)
        self._error.discard(qid)  # ADD_DONE deletes any earlier ERRORS row
        self._inner.add_done(qid)

    def add_error(self, qid: str, msg: str) -> None:
        self._error.add(qid)
        self._done.discard(qid)  # ADD_ERROR deletes any earlier ADDED row
        self._inner.add_error(qid, msg)

    def add_duplicate(
        self, qid: str, duplicate_qid: str, local_auth_id: str | None, viaf_id: str
    ) -> None:
        # has_duplicate matches either column, so both qids become 'seen'.
        self._duplicate.add(qid)
        self._duplicate.add(duplicate_qid)
        self._inner.add_duplicate(qid, duplicate_qid, local_auth_id, viaf_id)

    def add_duplicate_local_auth_id(
        self, qid: str, local_auth_id: str, viaf_cluster_id: str | None
    ) -> None:
        self._dup_local.add(qid)
        self._inner.add_duplicate_local_auth_id(qid, local_auth_id, viaf_cluster_id)

    def add_not_found(self, qid: str, pid: str) -> None:
        if pid == self._pid:
            self._not_found.add(qid)
        self._inner.add_not_found(qid, pid)
