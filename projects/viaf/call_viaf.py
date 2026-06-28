import json
from pathlib import Path

import viaf.authority_sources
import viaf.viaf_bot
from viaf.firebird_viaf_reporting import FirebirdViafReporting

PROGRESS_FILE = Path(__file__).parent / "viaf_progress.json"


def _load_current_pid_index(pids: list[str]) -> int:
    """Return the index in pids to resume from, based on the last saved progress."""
    if not PROGRESS_FILE.exists():
        return 0
    try:
        data = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    current_pid = data.get("current_pid")
    if current_pid in pids:
        return pids.index(current_pid)
    return 0


def _save_current_pid_index(pids: list[str], index: int) -> None:
    PROGRESS_FILE.write_text(json.dumps({"current_pid": pids[index]}), encoding="utf-8")


def main() -> None:
    authsrcs = viaf.authority_sources.AuthoritySources()
    pids = authsrcs.all_pids()

    index = _load_current_pid_index(pids)

    # viaf.org allows only a limited number of API calls per day, so we work
    # through the authority sources one at a time, persisting which one to
    # resume from next time. A run stops as soon as one source reports its
    # pass was cut short (i.e. the rate limit was hit); otherwise it moves on
    # to the next source, for at most one full cycle through all sources.
    for _ in range(len(pids)):
        pid = pids[index]
        auth_src = authsrcs.get(pid)

        bot = viaf.viaf_bot.ViafBot(auth_src, report=FirebirdViafReporting())
        bot.test = False
        finished = bot.run_session(output_file=f"qlever_viaf_index_{pid}.txt")

        if not finished:
            # continue next day
            break

        index = (index + 1) % len(pids)
        _save_current_pid_index(pids, index)


if __name__ == "__main__":
    main()
