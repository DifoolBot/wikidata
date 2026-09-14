#!/bin/bash
# Toolforge launcher for viaf_deconflate (projects/viaf_deconflate/deconflate.py).
#
# Invoke via `bash` so the file's executable bit is irrelevant (it is often
# lost when committed from Windows). Pass deconflate.py's own flags through
# (--redirect-scan multi|long, --apply, --save, --only, --apply-limit, ...).
#
# The redirect-scan selection is read from output/selection_cache/redirect_<sub>.json
# (primed offline by extract_dump.py from the truthy dump), so no WDQS/qlever
# query is made -- do NOT pass --refresh-selection unless the live endpoints are
# healthy again.
#
# Preview multi (classify + fetch VIAF clusters, spends budget, writes nothing):
#   toolforge jobs run deconflate-multi --image python3.11 --wait \
#       --command "bash $HOME/wikidata/projects/viaf_deconflate/toolforge_run.sh --redirect-scan multi --apply"
#
# Real multi run (apply the edits):
#   toolforge jobs run deconflate-multi --image python3.11 --wait \
#       --command "bash $HOME/wikidata/projects/viaf_deconflate/toolforge_run.sh --redirect-scan multi --apply --save"
#
# Cautious first real run (cap the number of edited items):
#       --command "bash $HOME/wikidata/projects/viaf_deconflate/toolforge_run.sh --redirect-scan multi --apply --save --apply-limit 20"
#
# Two-quota split (Toolforge + a second machine each have their own 1000/day VIAF
# budget): --shard i/m keeps only the items whose QID number mod m == i, so the
# two runs cover disjoint halves with no overlap. Run this on Toolforge:
#       --command "bash $HOME/wikidata/projects/viaf_deconflate/toolforge_run.sh --redirect-scan multi --shard 0/2 --apply --save"
# and on the other machine run the same script with --shard 1/2. The output/*.txt
# state files union-merge across machines via git (see output/.gitattributes):
# git pull before each run, git push after. --shard is ignored with --only.
#
# Long subset is the same with --redirect-scan long (but ~903k items and
# diluted; prefer multi for the daily VIAF budget).
#
# Assumes: repo cloned at $HOME/wikidata, venv at $HOME/venv, pywikibot config
# in $HOME/.pywikibot. Override paths with the VENV / PYWIKIBOT_DIR env vars.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export PYWIKIBOT_DIR="${PYWIKIBOT_DIR:-$HOME/.pywikibot}"
export PYTHONUNBUFFERED=1
export PYTHONPATH="$REPO_ROOT/projects"
source "${VENV:-$HOME/venv}/bin/activate"
cd "$REPO_ROOT"
exec python projects/viaf_deconflate/deconflate.py "$@"
