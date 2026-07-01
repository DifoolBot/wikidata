#!/bin/bash
# Toolforge launcher for remove_import_ref.
#
# Dry-run:
#   toolforge jobs run rmimport --image python3.11 --wait \
#       --command "$HOME/wikidata/projects/remove_import_ref/toolforge_run.sh"
# Real edit (append --save):
#       --command "$HOME/wikidata/projects/remove_import_ref/toolforge_run.sh --save"
#
# Assumes: repo cloned at $HOME/wikidata, venv at $HOME/venv, pywikibot config
# in $HOME/.pywikibot. Override with VENV / PYWIKIBOT_DIR env vars.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PYWIKIBOT_DIR="${PYWIKIBOT_DIR:-$HOME/.pywikibot}"
export PYTHONUNBUFFERED=1
source "${VENV:-$HOME/venv}/bin/activate"
cd "$REPO_ROOT"
exec python -m projects.remove_import_ref.bot "$@"
