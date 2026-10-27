#!/bin/bash
# Toolforge launcher for the detect_promo observatory collector (read-only, no edits).
#
# Invoke via `bash` so the file's executable bit is irrelevant (it is often
# lost when committed from Windows):
#
#   toolforge jobs run detect-promo-test --image python3.11 --wait \
#       --command "bash $HOME/wikidata/projects/detect_promo/toolforge_run.sh --hours 1"
#
# Only the collector runs here: it needs no history (one day file per run) and a
# missed day is lost for good, so it belongs on an always-on host. The analysis
# (track_deletions.py, digest.py, score10_list.py) reads the whole history and
# runs locally after sync_from_toolforge.ps1 has copied the day files down.
#
# Day files older than KEEP_DAYS (default 30) are pruned here after the run, so
# Toolforge holds ~100 MB at most -- sync at least every few weeks.
#
# Assumes: repo cloned at $HOME/wikidata, venv at $HOME/venv. Override with VENV.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PYTHONUNBUFFERED=1
export PYTHONPATH="$REPO_ROOT/projects"
source "${VENV:-$HOME/venv}/bin/activate"
cd "$REPO_ROOT"
python projects/detect_promo/collect_new_items.py "$@"
find projects/detect_promo/data -maxdepth 1 -name '20??-??-??.json' -mtime +"${KEEP_DAYS:-30}" -print -delete
