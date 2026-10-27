# Copy new observatory day files from Toolforge, then update the deletion tracking locally.
#
#   powershell -File projects\detect_promo\sync_from_toolforge.ps1          # copy + track_deletions --days 14
#   powershell -File projects\detect_promo\sync_from_toolforge.ps1 -NoTrack # copy only
#
# Copies only day files that are missing locally (read-only on Toolforge; pruning happens there, in
# toolforge_run.sh). Logs in as your own account (difool), which can read the tool's files.
param([switch]$NoTrack)
$ErrorActionPreference = "Stop"
$remote = "difool@login.toolforge.org"
$remoteDir = "/data/project/difoolbot/wikidata/projects/detect_promo/data"
$repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$localDir = Join-Path $PSScriptRoot "data"

$remoteFiles = ssh $remote "ls $remoteDir" | Where-Object { $_ -match '^\d{4}-\d{2}-\d{2}\.json$' }
$missing = $remoteFiles | Where-Object { -not (Test-Path (Join-Path $localDir $_)) }
"{0} day files on Toolforge, {1} new" -f @($remoteFiles).Count, @($missing).Count
foreach ($f in $missing) {
    scp "${remote}:$remoteDir/$f" (Join-Path $localDir $f)
    "  copied $f"
}

if (-not $NoTrack) {
    Push-Location $repo
    $env:PYTHONPATH = "$repo\projects"
    & "$repo\.venv\Scripts\python.exe" projects\detect_promo\track_deletions.py --days 14
    Pop-Location
}
