import os
from datetime import date, datetime, timedelta

import pywikibot as pwb
import viaf.authority_sources
from viaf.codes_sync import push_order
from viaf.paths import DATA_DIR
from viaf.viaf_bot import SessionOutcome, ViafBot
from viaf.viaf_config import load_config, order_pids


def _make_report():
    """Reporting backend: MariaDB on Toolforge (WD_DB_BACKEND=mariadb), else the
    local Firebird database. Only the selected backend is imported, so the other
    driver (firebird-driver / pymysql) need not be installed."""
    if os.environ.get("WD_DB_BACKEND", "").lower() == "mariadb":
        from viaf.mariadb_viaf_reporting import MariaDbViafReporting

        return MariaDbViafReporting()
    from viaf.firebird_viaf_reporting import FirebirdViafReporting

    return FirebirdViafReporting()


def _resume_index(ordered_pids: list[str], current_pid: str | None) -> int:
    if current_pid in ordered_pids:
        return ordered_pids.index(current_pid)
    return 0


def main() -> None:
    config = load_config()
    # The bot's state lives in the database alongside the session tables it
    # describes, so the status webservice reads it from the same place and the
    # two cannot drift apart.
    report = _make_report()
    state = report.get_state()

    if state.cooldown_until and date.today() < state.cooldown_until:
        pwb.output(f"In cooldown until {state.cooldown_until}; nothing to do.")
        return

    authority_sources = viaf.authority_sources.AuthoritySources()
    ignored = set(config.ignore)
    active_pids = [pid for pid in authority_sources.all_pids() if pid not in ignored]
    ordered_pids = order_pids(active_pids, config.order)
    if not ordered_pids:
        return

    index = _resume_index(ordered_pids, state.current_pid)

    # Items VIAF reported 'not_found' for are cached and skipped until this
    # cutoff; older cache entries are purged so they get re-checked.
    not_found_cutoff: datetime | None = None
    if config.not_found_cache_days is not None:
        not_found_cutoff = datetime.now() - timedelta(days=config.not_found_cache_days)

    # Daily housekeeping before any processing: retry transient errors,
    # normalize/de-duplicate the duplicate-locals report, and drop expired
    # not_found cache entries.
    # Mirror the yaml-derived processing order + skips into CODES, so the bot and
    # the status webservice read a single place (the DB).
    push_order(report, ordered_pids, ignored)
    report.run_maintenance()
    if not_found_cutoff is not None:
        report.purge_not_found_before(not_found_cutoff)

    # Process sources in order. A source that finishes (either its qlever rows
    # are exhausted or the duplicates cap is hit) publishes its report and we
    # advance to the next one; when the VIAF daily rate limit is hit we stop and
    # resume the same source on the next run. After the final source finishes,
    # enter a cooldown before starting the next full pass from the top.
    for _ in range(len(ordered_pids)):
        pid = ordered_pids[index]
        auth_src = authority_sources.get(pid)

        bot = ViafBot(auth_src, report=_make_report())
        bot.test = False
        bot.not_found_cutoff = not_found_cutoff
        outcome = bot.run_session(
            output_file=str(DATA_DIR / f"qlever_viaf_index_{pid}.txt"),
            max_duplicates=config.max_duplicates,
        )

        if outcome in (
            SessionOutcome.RATE_LIMITED,
            SessionOutcome.WDQS_UNAVAILABLE,
        ):
            # Either today's VIAF budget is used up, or WDQS is unreachable and
            # every further item would spend a VIAF lookup we cannot verify.
            # Either way: resume this same source on the next run.
            report.save_progress(current_pid=pid, cooldown_until=None)
            return

        if index == len(ordered_pids) - 1:
            resume_at = date.today() + timedelta(days=config.cooldown_days)
            report.save_progress(current_pid=ordered_pids[0], cooldown_until=resume_at)
            pwb.output(
                f"Completed all authority sources; cooling down until {resume_at}."
            )
            return

        index += 1
        report.save_progress(current_pid=ordered_pids[index], cooldown_until=None)


if __name__ == "__main__":
    main()
