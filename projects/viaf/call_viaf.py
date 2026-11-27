import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pywikibot as pwb
import pywikibot.bot
from pywikibot.exceptions import MaxlagTimeoutError
import viaf.authority_sources
from viaf.codes_sync import push_order, sync_descriptions
from viaf.paths import DATA_DIR
from viaf.report_backend import WarmSkipReport
from viaf.viaf_bot import PAGE_TITLE, SessionOutcome, ViafBot
from viaf.viaf_config import load_config, order_pids

from shared_lib.wikidata_site import ensure_login, get_site


class _MaxLevelFilter(logging.Filter):
    """Pass only records at or below *level* (the complement of setLevel)."""

    def __init__(self, level: int) -> None:
        super().__init__()
        self.level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self.level


def _setup_logging() -> None:
    """Split pywikibot output by level: INFO and below to stdout, WARNING and
    above to stderr.

    By default pywikibot sends *everything* (info, warning, error) to stderr,
    so an unattended job's ``.err`` file fills with expected progress lines and
    the real errors are hard to spot. Routing the run's normal narrative to
    ``.out`` keeps ``.err`` for genuinely unexpected problems only.
    """
    pywikibot.bot.init_handlers()  # let pywikibot do its one-time handler setup
    logger = logging.getLogger("pywiki")
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    out = logging.StreamHandler(sys.stdout)
    out.addFilter(_MaxLevelFilter(logging.INFO))
    out.setFormatter(logging.Formatter("%(message)s"))

    err = logging.StreamHandler(sys.stderr)
    err.setLevel(logging.WARNING)
    err.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))

    logger.addHandler(out)
    logger.addHandler(err)
    logger.propagate = False


@dataclass
class _SourceRun:
    """One authority source's contribution to a single daily run, for the
    end-of-run summary."""

    pid: str
    description: str
    outcome: str
    checked: int
    added: int
    not_found: int


_DIVIDER = "=" * 70


def _emit_to_both(text: str) -> None:
    """Write *text* verbatim to both stdout (the job's .out log) and stderr
    (its .err log).

    The daily Toolforge job appends every run's output to the same two log
    files, so without a dated marker there is no way to tell where one day's
    run begins -- the very thing that makes the logs hard to read. Writing the
    marker to *both* streams means each file carries the date and the run's
    boundaries, including .err on a day that produced no warnings at all."""
    for stream in (sys.stdout, sys.stderr):
        print(text, file=stream, flush=True)


def _format_duration(delta: timedelta) -> str:
    total = int(delta.total_seconds())
    hours, rem = divmod(total, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _log_run_start(started: datetime) -> None:
    _emit_to_both(_DIVIDER)
    _emit_to_both(f"VIAF run started {started:%Y-%m-%d %H:%M:%S} UTC")
    _emit_to_both(_DIVIDER)


def _log_run_summary(
    started: datetime, rows: list[_SourceRun], disposition: str
) -> None:
    """Print a consolidated digest of the run: the dated boundary and a one-line
    disposition go to both logs; the per-source table goes to .out only.

    Counts are what *this run* did (see ViafBot.last_stats), not the running
    session totals -- for the latter see the sessions dashboard."""
    ended = datetime.now(timezone.utc)
    duration = _format_duration(ended - started)
    total_added = sum(r.added for r in rows)

    # Full table to .out (INFO -> stdout).
    pwb.output("---------------------- VIAF run summary ----------------------")
    pwb.output(f"Started : {started:%Y-%m-%d %H:%M:%S} UTC")
    pwb.output(f"Ended   : {ended:%Y-%m-%d %H:%M:%S} UTC ({duration})")
    if rows:
        pwb.output("Sources this run (counts are this run's own additions):")
        for r in rows:
            pwb.output(
                f"  {r.pid:<7}{r.description:<30} "
                f"checked={r.checked} added={r.added} not_found={r.not_found} "
                f"[{r.outcome}]"
            )
        pwb.output(
            "Totals  : checked="
            f"{sum(r.checked for r in rows)} added={total_added} "
            f"not_found={sum(r.not_found for r in rows)}"
        )
    else:
        pwb.output("Sources this run: none")
    pwb.output(f"Outcome : {disposition}")

    # One-line recap + closing boundary to both logs, so .err alone tells you
    # whether the run finished and how, without opening .out.
    _emit_to_both(
        f"VIAF run ended {ended:%Y-%m-%d %H:%M:%S} UTC ({duration}) "
        f"-- added {total_added}; {disposition}"
    )
    _emit_to_both(_DIVIDER)


def _make_report():
    """Reporting backend: MariaDB on Toolforge (WD_DB_BACKEND=mariadb), else the
    local Firebird database. Only the selected backend is imported, so the other
    driver (firebird-driver / pymysql) need not be installed."""
    if os.environ.get("WD_DB_BACKEND", "").lower() == "mariadb":
        from viaf.mariadb_viaf_reporting import MariaDbViafReporting

        return MariaDbViafReporting()
    from viaf.firebird_viaf_reporting import FirebirdViafReporting

    return FirebirdViafReporting()


# Property labels are stable, so re-reading them from Wikidata this often is
# plenty; it costs one API call per source on the days it does run.
DESCRIPTION_SYNC_DAYS = 30


def _descriptions_stale(last_synced: date | None) -> bool:
    return last_synced is None or (date.today() - last_synced).days >= (
        DESCRIPTION_SYNC_DAYS
    )


def _resume_index(ordered_pids: list[str], current_pid: str | None) -> int:
    if current_pid in ordered_pids:
        return ordered_pids.index(current_pid)
    return 0


def _worklist_file(pid: str) -> Path:
    return DATA_DIR / f"qlever_viaf_index_{pid}.txt"


# Marker for a backlog pass: the PIDs (one per line) that still had a leftover
# work list when the previous pass ended. While it exists, only those sources
# are processed and no cooldown starts. A file rather than a STATE column, so
# neither database schema needs a migration.
BACKLOG_FILE = DATA_DIR / "backlog_pass.txt"


def _load_backlog() -> list[str] | None:
    if not BACKLOG_FILE.exists():
        return None
    return [
        line.strip()
        for line in BACKLOG_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _save_backlog(pids: list[str]) -> None:
    BACKLOG_FILE.write_text("\n".join(pids) + "\n", encoding="utf-8")


def _clear_backlog() -> None:
    BACKLOG_FILE.unlink(missing_ok=True)


def _sources_with_backlog(pids: list[str]) -> list[str]:
    """Sources whose work list was cut short (by the max_duplicates cap): the
    unchecked rows are still in their qlever file. A source that finished its
    list has its file removed by iterate_qlever."""
    return [pid for pid in pids if _worklist_file(pid).exists()]


def _report_bytes() -> int:
    """Size of the published report page in bytes (UTF-8), the same figure
    the page history shows."""
    return len(pwb.Page(get_site(), PAGE_TITLE).text.encode("utf-8"))


def main() -> None:
    _setup_logging()
    # A daily run appends to the same .out/.err, so stamp the start of each run
    # into both logs; the finally below closes it with a matching summary.
    started = datetime.now(timezone.utc)
    _log_run_start(started)
    run_rows: list[_SourceRun] = []
    disposition = "nothing to do"
    report = None
    try:
        # Log in up front so a credential problem fails the run immediately
        # rather than after the first source's worth of VIAF lookups (pywikibot
        # would otherwise only log in on the first edit).
        ensure_login()
        config = load_config()
        # The bot's state lives in the database alongside the session tables it
        # describes, so the status webservice reads it from the same place and
        # the two cannot drift apart.
        report = _make_report()
        state = report.get_state()

        if state.cooldown_until and date.today() < state.cooldown_until:
            disposition = f"in cooldown until {state.cooldown_until}; nothing to do"
            pwb.output(f"In cooldown until {state.cooldown_until}; nothing to do.")
            return

        authority_sources = viaf.authority_sources.AuthoritySources()
        ignored = set(config.ignore)
        active_pids = [
            pid for pid in authority_sources.all_pids() if pid not in ignored
        ]
        ordered_pids = order_pids(active_pids, config.order)
        if not ordered_pids:
            disposition = "no active authority sources configured"
            return

        # A backlog pass covers only the sources listed in BACKLOG_FILE (in the
        # yaml order); a normal pass covers every active source.
        backlog = _load_backlog()
        pass_pids = ordered_pids
        pass_kind = "pass"
        if backlog is not None:
            pass_pids = [pid for pid in ordered_pids if pid in backlog]
            pass_kind = "backlog pass"
            if not pass_pids:
                # None of the listed sources is active any more.
                pwb.warning(
                    f"Backlog sources {backlog} are not active; "
                    "dropping the backlog pass."
                )
                _clear_backlog()
                pass_pids = ordered_pids
                pass_kind = "pass"

        index = _resume_index(pass_pids, state.current_pid)
        if state.current_pid is None:
            pwb.output(f"Starting a new {pass_kind} at {pass_pids[index]}.")
        elif pass_pids[index] == state.current_pid:
            pwb.output(
                f"Resuming {pass_kind} at {state.current_pid} "
                f"(source {index + 1}/{len(pass_pids)})."
            )
        else:
            # The saved source is no longer active (ignored, or dropped from
            # the authority sources): the pass restarts from the top.
            pwb.warning(
                f"Saved source {state.current_pid} is not active; "
                f"restarting the {pass_kind} at {pass_pids[index]}."
            )

        # Items VIAF reported 'not_found' for are cached and skipped until this
        # cutoff; older cache entries are purged so they get re-checked.
        not_found_cutoff: datetime | None = None
        if config.not_found_cache_days is not None:
            not_found_cutoff = datetime.now() - timedelta(
                days=config.not_found_cache_days
            )

        # Daily housekeeping before any processing: retry transient errors,
        # normalize/de-duplicate the duplicate-locals report, and drop expired
        # not_found cache entries.
        # Mirror the yaml-derived processing order + skips into CODES, so the bot
        # and the status webservice read a single place (the DB).
        push_order(report, ordered_pids, ignored)
        # Descriptions come from the property labels on Wikidata, so they follow
        # renames there instead of going stale. Occasional, not every run.
        if _descriptions_stale(state.descriptions_synced):
            changed = sync_descriptions(report, authority_sources.all_pids())
            report.set_descriptions_synced(date.today())
            for pid, old, new in changed:
                pwb.output(f"CODES description {pid}: {old!r} -> {new!r}")
            pwb.output(f"Synced descriptions from Wikidata; {len(changed)} changed.")
        report.run_maintenance()
        if not_found_cutoff is not None:
            report.purge_not_found_before(not_found_cutoff)

        # Process sources in order. A source that finishes (either its qlever
        # rows are exhausted or the duplicates cap is hit) publishes its report
        # and we advance to the next one; when the VIAF daily rate limit is hit
        # we stop and resume the same source on the next run. After the final
        # source finishes, enter a cooldown before starting the next full pass
        # from the top.
        for _ in range(len(pass_pids)):
            pid = pass_pids[index]

            # Don't grow the report page past what editors (and the viaf-score
            # job, which rescans every row daily) can handle. Checked before
            # every source, since each finished source appends its tables.
            if config.max_report_bytes is not None:
                size = _report_bytes()
                if size >= config.max_report_bytes:
                    report.save_progress(current_pid=pid, cooldown_until=None)
                    disposition = (
                        f"paused: report page is {size:,} bytes "
                        f"(limit {config.max_report_bytes:,}); will resume {pid} "
                        "once it is worked below the limit"
                    )
                    pwb.output(disposition)
                    return

            auth_src = authority_sources.get(pid)

            # Serve the per-item skip checks from memory: preload once here
            # rather than hitting the DB six times for every qlever row.
            source_report = WarmSkipReport(_make_report())
            source_report.preload(pid, not_found_cutoff)
            bot = ViafBot(auth_src, report=source_report)
            bot.test = False
            bot.not_found_cutoff = not_found_cutoff
            outcome = bot.run_session(
                output_file=str(DATA_DIR / f"qlever_viaf_index_{pid}.txt"),
                max_duplicates=config.max_duplicates,
            )
            checked, added, not_found = bot.last_stats
            run_rows.append(
                _SourceRun(
                    pid, auth_src.description, outcome.name, checked, added, not_found
                )
            )

            stop_reasons = {
                SessionOutcome.RATE_LIMITED: "VIAF daily rate limit reached",
                SessionOutcome.WDQS_UNAVAILABLE: "WDQS unavailable",
                SessionOutcome.QLEVER_UNAVAILABLE: "qlever unavailable",
            }
            if outcome in stop_reasons:
                # Today's VIAF budget is used up, or a service we depend on
                # (WDQS for the duplicate check, qlever for the work list) is
                # unreachable. In every case the source is unfinished: resume it
                # on the next run rather than advancing (which would eventually
                # trigger a bogus post-pass cooldown).
                report.save_progress(current_pid=pid, cooldown_until=None)
                disposition = f"{stop_reasons[outcome]}; will resume {pid} next run"
                return

            if index == len(pass_pids) - 1:
                # Sources cut short by the max_duplicates cap still have rows
                # left: go straight back to them instead of letting the backlog
                # wait out a whole cooldown (it would otherwise only shrink by
                # max_duplicates rows per pass).
                remaining = _sources_with_backlog(ordered_pids)
                if remaining:
                    _save_backlog(remaining)
                    report.save_progress(current_pid=None, cooldown_until=None)
                    disposition = (
                        f"{pass_kind} finished; backlog pass next for "
                        f"{', '.join(remaining)}"
                    )
                    pwb.output(disposition[0].upper() + disposition[1:] + ".")
                    return
                _clear_backlog()
                resume_at = date.today() + timedelta(days=config.cooldown_days)
                # No current source: the next pass starts at the top of the order
                # as the yaml has it *then*. Saving ordered_pids[0] here froze
                # today's order instead, so a yaml edit live at the end of a pass
                # (P691/P244 dropped, then restored) made the next pass resume
                # mid-order at P227 and silently skip the sources before it.
                report.save_progress(current_pid=None, cooldown_until=resume_at)
                disposition = (
                    f"completed all authority sources; cooling down until {resume_at}"
                )
                pwb.output(
                    f"Completed all authority sources; cooling down until {resume_at}."
                )
                return

            index += 1
            report.save_progress(current_pid=pass_pids[index], cooldown_until=None)
            disposition = f"advanced through sources; {pass_pids[index]} is next"
    except MaxlagTimeoutError as exc:
        # Wikidata replication lag stayed above maxlag for the whole retry
        # window. This is a transient, server-side, self-healing condition:
        # swallow it so the scheduled job exits 0 (does not report a failure and
        # email), and let the next daily run resume from where save_progress
        # left off. Logged at WARNING so it still shows in the .err file --
        # visibly handled, not a CRITICAL traceback.
        pwb.warning(f"Wikidata maxlag too high, aborting this run cleanly: {exc}")
        disposition = "aborted early: Wikidata maxlag too high (resumes next run)"
    except Exception:
        # Genuinely unexpected: record it for the summary, then re-raise so the
        # traceback still reaches .err and the job reports a failure.
        disposition = "aborted: unexpected error (see .err)"
        raise
    finally:
        # Release the reused DB connection (MariaDB backend keeps one open
        # across the run); a no-op on backends that reconnect per query.
        if report is not None:
            report.close()
        _log_run_summary(started, run_rows, disposition)


if __name__ == "__main__":
    main()
