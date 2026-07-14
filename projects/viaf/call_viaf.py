import json
import os
from datetime import date, datetime, timedelta

import pywikibot as pwb
import viaf.authority_sources
from viaf.paths import DATA_DIR
from viaf.viaf_bot import SessionOutcome, ViafBot
from viaf.viaf_config import load_config, order_pids

PROGRESS_FILE = DATA_DIR / "viaf_progress.json"


def _make_report():
    """Reporting backend: MariaDB on Toolforge (WD_DB_BACKEND=mariadb), else the
    local Firebird database. Only the selected backend is imported, so the other
    driver (firebird-driver / pymysql) need not be installed."""
    if os.environ.get("WD_DB_BACKEND", "").lower() == "mariadb":
        from viaf.mariadb_viaf_reporting import MariaDbViafReporting

        return MariaDbViafReporting()
    from viaf.firebird_viaf_reporting import FirebirdViafReporting

    return FirebirdViafReporting()


def _load_progress() -> dict:
    if not PROGRESS_FILE.exists():
        return {}
    try:
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_progress(current_pid: str, cooldown_until: date | None = None) -> None:
    data = {"current_pid": current_pid}
    if cooldown_until is not None:
        data["cooldown_until"] = cooldown_until.isoformat()
    PROGRESS_FILE.write_text(json.dumps(data), encoding="utf-8")


def _resume_index(ordered_pids: list[str], current_pid: str | None) -> int:
    if current_pid in ordered_pids:
        return ordered_pids.index(current_pid)
    return 0


def main() -> None:
    config = load_config()
    progress = _load_progress()

    cooldown_until = progress.get("cooldown_until")
    if cooldown_until and date.today() < date.fromisoformat(cooldown_until):
        pwb.output(f"In cooldown until {cooldown_until}; nothing to do.")
        return

    authority_sources = viaf.authority_sources.AuthoritySources()
    ignored = set(config.ignore)
    active_pids = [pid for pid in authority_sources.all_pids() if pid not in ignored]
    ordered_pids = order_pids(active_pids, config.order)
    if not ordered_pids:
        return

    index = _resume_index(ordered_pids, progress.get("current_pid"))

    # Items VIAF reported 'not_found' for are cached and skipped until this
    # cutoff; older cache entries are purged so they get re-checked.
    not_found_cutoff: datetime | None = None
    if config.not_found_cache_days is not None:
        not_found_cutoff = datetime.now() - timedelta(days=config.not_found_cache_days)

    # Daily housekeeping before any processing: retry transient errors,
    # normalize/de-duplicate the duplicate-locals report, and drop expired
    # not_found cache entries.
    maintenance = _make_report()
    maintenance.run_maintenance()
    if not_found_cutoff is not None:
        maintenance.purge_not_found_before(not_found_cutoff)

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

        if outcome == SessionOutcome.RATE_LIMITED:
            # used today's VIAF budget; resume this same source next run
            _save_progress(current_pid=pid)
            return

        if index == len(ordered_pids) - 1:
            resume_at = date.today() + timedelta(days=config.cooldown_days)
            _save_progress(current_pid=ordered_pids[0], cooldown_until=resume_at)
            pwb.output(
                f"Completed all authority sources; cooling down until {resume_at}."
            )
            return

        index += 1
        _save_progress(current_pid=ordered_pids[index])


if __name__ == "__main__":
    main()
