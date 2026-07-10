"""Entry point for the addlabel bot.

Usage (run from the projects directory):
  python -m addlabel.call_addlabel loop              # retry + todo, forever
  python -m addlabel.call_addlabel retry             # only flagged errors
  python -m addlabel.call_addlabel todo              # only the todo queue
  python -m addlabel.call_addlabel scan loc          # scan a source (loc/bnf/idref/gnd)
  python -m addlabel.call_addlabel item Q42          # dry-run one item
  python -m addlabel.call_addlabel item Q42 --live   # actually edit
"""

import argparse
import time

import addlabel.person_name as pn
from addlabel.addlabel_bot import SOURCES, AddLabelBot, NullReport
from addlabel.firebird_addlabel_reporting import FirebirdAddLabelReporting

SLEEP_AFTER_LOOP_ERROR = 10 * 60  # sec


def run_retry():
    bot = AddLabelBot(None, report=FirebirdAddLabelReporting())
    bot.retry()


def run_todo():
    bot = AddLabelBot(None, report=FirebirdAddLabelReporting())
    bot.todo()


def run_loop():
    while True:
        try:
            run_retry()
            run_todo()
        except Exception as e:
            print(f"Uncaught error: {e}")
            time.sleep(SLEEP_AFTER_LOOP_ERROR)


def run_scan(source_name: str):
    bot = AddLabelBot(SOURCES[source_name], report=FirebirdAddLabelReporting())
    bot.test = False
    bot.scan()


def run_single(
    qid: str,
    live: bool = False,
    skip_sex: bool = False,
    force_name_order: str = pn.NAME_ORDER_UNDETERMINED,
):
    report = FirebirdAddLabelReporting() if live else NullReport()
    bot = AddLabelBot(None, report=report)
    bot.test = not live
    bot.skip_sex = skip_sex
    bot.force_name_order = force_name_order
    try:
        bot.examine(qid)
    except RuntimeError as e:
        print(f"Runtime error: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Add labels/sex/dates from authority sources")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("loop", help="run retry + todo forever")
    subparsers.add_parser("retry", help="re-examine errors flagged for retry")
    subparsers.add_parser("todo", help="examine the queued todo items")

    scan_parser = subparsers.add_parser("scan", help="scan all items of one source")
    scan_parser.add_argument("source", choices=sorted(SOURCES))

    item_parser = subparsers.add_parser("item", help="examine a single item")
    item_parser.add_argument("qid")
    item_parser.add_argument("--live", action="store_true", help="apply edits (default: dry run)")
    item_parser.add_argument("--skip-sex", action="store_true")

    args = parser.parse_args()
    if args.command == "loop":
        run_loop()
    elif args.command == "retry":
        run_retry()
    elif args.command == "todo":
        run_todo()
    elif args.command == "scan":
        run_scan(args.source)
    elif args.command == "item":
        run_single(args.qid, live=args.live, skip_sex=args.skip_sex)


if __name__ == "__main__":
    main()
