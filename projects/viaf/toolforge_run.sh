#!/bin/bash
# Toolforge launcher for the VIAF bot (projects/viaf/call_viaf.py).
#
# Invoke via `bash` so the file's executable bit is irrelevant (it is often
# lost when committed from Windows):
#
#   # daily, 04:00 UTC (VIAF has a small daily API budget, so once a day)
#   toolforge jobs run viaf --image python3.11 \
#       --schedule "0 4 * * *" \
#       --command "bash $HOME/wikidata/projects/viaf/toolforge_run.sh"
#
#   # one-off run
#   toolforge jobs run viaf --image python3.11 --wait \
#       --command "bash $HOME/wikidata/projects/viaf/toolforge_run.sh"
#
# Assumes: repo cloned at $HOME/wikidata, venv at $HOME/venv (with pymysql,
# pywikibot, requests, python-dotenv, PyYAML), pywikibot config in
# $HOME/.pywikibot, a repo-root .env with WD_DB_USER / WD_DB_PASSWORD, and the
# ToolsDB database + schema + data/viaf_mariadb.json already set up (see
# DEPLOY.md). Override paths with the VENV / PYWIKIBOT_DIR env vars.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PYWIKIBOT_DIR="${PYWIKIBOT_DIR:-$HOME/.pywikibot}"
export PYTHONUNBUFFERED=1
export PYTHONPATH="$REPO_ROOT/projects:$REPO_ROOT/projects/shared_lib"
export WD_DB_BACKEND=mariadb
source "${VENV:-$HOME/venv}/bin/activate"
cd "$REPO_ROOT"
exec python -m viaf.call_viaf "$@"
