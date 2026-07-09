#!/bin/bash
# Toolforge launcher for viaf_score_upd.
#
# Invoke via `bash` so the file's executable bit is irrelevant (it is often
# lost when committed from Windows).  Pass viaf_score.py's own flags through
# (--rescore, --keep-done, --dry-run, --limit N).
#
# One-off dry-run (print result, do not save):
#   toolforge jobs run viafscore --image python3.11 --wait \
#       --command "bash $HOME/wikidata/projects/viaf_score_upd/toolforge_run.sh --dry-run"
#
# Daily add-only (score new sections, remove nothing; minor edit):
#   toolforge jobs run viafscore-daily --image python3.11 --schedule "17 3 * * *" \
#       --command "bash $HOME/wikidata/projects/viaf_score_upd/toolforge_run.sh --keep-done"
#
# Weekly recompute (rescore all, remove done rows; major edit):
#   toolforge jobs run viafscore-weekly --image python3.11 --schedule "17 4 * * 0" \
#       --command "bash $HOME/wikidata/projects/viaf_score_upd/toolforge_run.sh --rescore"
#
# Assumes: repo cloned at $HOME/wikidata, venv at $HOME/venv, pywikibot config
# in $HOME/.pywikibot. Override with VENV / PYWIKIBOT_DIR env vars.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PYWIKIBOT_DIR="${PYWIKIBOT_DIR:-$HOME/.pywikibot}"
export PYTHONUNBUFFERED=1
source "${VENV:-$HOME/venv}/bin/activate"
cd "$REPO_ROOT"
exec python -m projects.viaf_score_upd.viaf_score "$@"
