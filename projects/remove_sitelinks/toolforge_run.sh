#!/bin/bash
# Toolforge launcher for remove_sitelinks.
#
# Invoke via `bash` so the file's executable bit is irrelevant (it is often
# lost when committed from Windows). Pass the bot's own flags through:
#   --save     actually edit Wikidata (default is dry-run: no edits, no DB writes)
#   --refresh  refetch items.txt via qlever first (slow; occasional use)
#
#   # weekly real run, Monday 05:00 UTC
#   toolforge jobs run remove-sitelinks --image python3.11 \
#       --schedule "0 5 * * 1" \
#       --command "bash $HOME/wikidata/projects/remove_sitelinks/toolforge_run.sh --save"
#
#   # one-off dry-run test (no --save)
#   toolforge jobs run remove-sitelinks --image python3.11 --wait \
#       --command "bash $HOME/wikidata/projects/remove_sitelinks/toolforge_run.sh"
#
# Assumes: repo cloned at $HOME/wikidata, venv at $HOME/venv (with pymysql,
# pywikibot, requests, python-dotenv), pywikibot config in $HOME/.pywikibot,
# a repo-root .env with WD_DB_USER / WD_DB_PASSWORD, and the ToolsDB database +
# data/remove_sitelinks.json already set up (see README). Override paths with
# the VENV / PYWIKIBOT_DIR env vars.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PYWIKIBOT_DIR="${PYWIKIBOT_DIR:-$HOME/.pywikibot}"
export PYTHONUNBUFFERED=1
# remove_sitelinks uses bare shared_lib-module imports, so both dirs on the path.
export PYTHONPATH="$REPO_ROOT/projects:$REPO_ROOT/projects/shared_lib"
export WD_DB_BACKEND=mariadb
source "${VENV:-$HOME/venv}/bin/activate"
cd "$REPO_ROOT"
exec python projects/remove_sitelinks/remove_sitelinks.py "$@"
