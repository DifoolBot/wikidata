#!/bin/bash
# Toolforge launcher for clean_youtube.
#
# Invoke via `bash` so the file's executable bit is irrelevant (it is often
# lost when committed from Windows):
#
# Dry-run:
#   toolforge jobs run youtube --image python3.11 --wait \
#       --command "bash $HOME/wikidata/projects/clean_youtube/toolforge_run.sh --limit 5"
# Real edit (append --save):
#       --command "bash $HOME/wikidata/projects/clean_youtube/toolforge_run.sh --save"
#
# Assumes: repo cloned at $HOME/wikidata, venv at $HOME/venv, pywikibot config
# in $HOME/.pywikibot. Override with VENV / PYWIKIBOT_DIR env vars.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PYWIKIBOT_DIR="${PYWIKIBOT_DIR:-$HOME/.pywikibot}"
export PYTHONUNBUFFERED=1
export PYTHONPATH="$REPO_ROOT/projects"
export WD_DB_BACKEND=mariadb
source "${VENV:-$HOME/venv}/bin/activate"
cd "$REPO_ROOT"
exec python projects/clean_youtube/youtube_metadata.py "$@"
