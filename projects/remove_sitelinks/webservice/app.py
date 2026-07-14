"""Minimal Toolforge webservice: a status page for remove_sitelinks.

Reads the same tracker DB and the data/ queue + review logs, and renders HTML.
Backend follows WD_DB_BACKEND (Firebird locally, MariaDB on Toolforge) exactly
like the bot, so it can be tested locally against the real data.

Local test:
    pip install flask            # firebird-driver is already installed locally
    python projects/remove_sitelinks/webservice/app.py
    -> http://127.0.0.1:5000/

Deploy (Toolforge, as the tool account):
    ln -s ~/wikidata/projects/remove_sitelinks/webservice ~/www/python/src
    python3 -m venv ~/www/python/venv
    ~/www/python/venv/bin/pip install -r ~/www/python/src/requirements.txt
    toolforge webservice python3.11 start
    -> https://<toolname>.toolforge.org/
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, abort, render_template_string

# app.py -> webservice/ -> remove_sitelinks/ -> projects/ -> repo root
PROJECT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_DIR / "data"
REPO_ROOT = Path(__file__).resolve().parents[3]

# Make the bare shared_lib-module imports work standalone (no PYTHONPATH needed).
sys.path.insert(0, str(REPO_ROOT / "projects"))
sys.path.insert(0, str(REPO_ROOT / "projects" / "shared_lib"))

if os.environ.get("WD_DB_BACKEND", "").lower() == "mariadb":
    from database_handler_mariadb import MariaDbDatabaseHandler as _DBHandler
else:
    from database_handler_firebird import FirebirdDatabaseHandler as _DBHandler

CONFIG = DATA_DIR / "remove_sitelinks.json"
DISPLAY_LIMIT = 500  # max QIDs listed on a /failed/<key> page

# key -> (label, filename, column headers). Each log is a tab-separated file.
REVIEW_LOGS = {
    "unresolved_p143": (
        "Unresolved P143 refs",
        "unresolved_p143_refs.txt",
        ["When", "Item", "Lang", "Property", "Ref hash"],
    ),
    "deleted_media": (
        "Deleted-media statements",
        "deleted_media_refs.txt",
        ["When", "Item", "Property", "File"],
    ),
    "renamed": (
        "Renamed, still exists",
        "renamed_still_exists_refs.txt",
        ["When", "Item", "Lang", "Title"],
    ),
}

# Failure categories, defined once and used for both the breakdown and the
# /failed/<key> filter. (key, human label, SQL condition on error_msg). The
# conditions are constants (never user input), so string-building is safe.
CATEGORIES = [
    ("exists", "Recovered page still exists on Wikipedia (category, spouse, list, …)",
     "error_msg LIKE '%status: EXISTS%'"),
    ("redirect", "Recovered page is now a redirect",
     "error_msg LIKE '%status: REDIRECT%'"),
    ("never_existed", "No page found (title never existed)",
     "error_msg LIKE '%status: NEVER_EXISTED%'"),
    ("none_deleted", "None of the recovered titles are deleted",
     "error_msg LIKE '%are deleted%'"),
    ("multiple_urls", "Multiple import URLs in one reference",
     "error_msg LIKE '%Multiple import URLs%'"),
    ("multiple_langs", "Multiple languages in one reference",
     "error_msg LIKE '%Multiple languages%'"),
    ("unrecognized", "Unrecognised import-URL format",
     "error_msg LIKE '%Unrecognized%'"),
]
CAT_BY_KEY = {key: (label, cond) for key, label, cond in CATEGORIES}
LABEL_BY_KEY = {key: label for key, label, _ in CATEGORIES}
LABEL_BY_KEY["other"] = "Other / uncategorised"

# One-line explanation shown on each /failed/<key> page.
DESCRIPTIONS = {
    "exists": "The Wikipedia page recovered for these items is still live (often a "
              "category, spouse or list article, or an article renamed and still "
              "existing), so the reference was left unchanged.",
    "redirect": "The recovered page is now a redirect, so it was treated as "
                "still-existing and left unchanged.",
    "never_existed": "No trace of the recovered title was found on Wikipedia - it "
                     "was never created, or the deletion log had nothing.",
    "none_deleted": "None of the titles recovered for the item resolved to a "
                    "deleted or moved-out page, so the item was failed for review.",
    "multiple_urls": "One reference carried more than one import URL, which the bot "
                     "does not try to disambiguate.",
    "multiple_langs": "One reference mixed more than one Wikipedia language edition.",
    "unrecognized": "The import URL did not parse as a recognised Wikipedia article "
                    "URL.",
    "other": "Failures that do not fall into any of the categories above.",
}

# One-line explanation shown on each /log/<key> page.
LOG_DESCRIPTIONS = {
    "unresolved_p143": "P143-only references that could not be tied to the item's "
                       "own deleted page (no sitelink-removal comment and no history "
                       "snapshot). Left unchanged.",
    "deleted_media": "Statements skipped because their Commons media file was "
                     "deleted - editing them would fail the whole save. Left "
                     "unchanged.",
    "renamed": "References whose source page was renamed within mainspace and still "
               "exists (often a missing sitelink or a duplicate item). Left "
               "unchanged.",
}

app = Flask(__name__)


@app.template_filter("comma")
def _comma(n) -> str:
    """Thousands separators: 142292 -> '142,292'."""
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())


def _breakdown_sql() -> str:
    whens = " ".join(f"WHEN {cond} THEN '{key}'" for key, _, cond in CATEGORIES)
    return (
        f"SELECT CASE {whens} ELSE 'other' END, COUNT(*) "
        f"FROM qids WHERE status = 'failed' GROUP BY 1 ORDER BY 2 DESC"
    )


STYLE = """
<style>
  body { font: 15px/1.5 system-ui, sans-serif; max-width: 760px; margin: 2rem auto; padding: 0 1rem; color: #222; }
  a { color: #1a5fb4; } h1 { font-size: 1.4rem; } h2 { font-size: 1.05rem; margin-top: 1.6rem; color: #555; }
  table { border-collapse: collapse; margin: .4rem 0; width: 100%; } td, th { padding: .25rem .8rem; text-align: left; }
  tr:nth-child(even) { background: #f6f6f6; } .num { text-align: right; font-variant-numeric: tabular-nums; }
  .big { font-size: 1.8rem; font-weight: 600; } .muted { color: #888; font-size: .85rem; }
  code { color: #666; }
</style>
"""

INDEX_TEMPLATE = STYLE + """
<h1>remove_sitelinks &mdash; status</h1>
<p><span class="big">{{ total | comma }}</span> items recorded &nbsp;
   ({{ success | comma }} success, {{ failed | comma }} failed) &middot;
   <b>{{ queue | comma }}</b> in the queue</p>

<h2>Failure breakdown</h2>
<table>
  <tr><th>Reason</th><th class="num">Count</th></tr>
  {% for key, label, n in errors %}
  <tr><td><a href="{{ url_for('failed', key=key) }}">{{ label }}</a></td>
      <td class="num">{{ n | comma }}</td></tr>
  {% endfor %}
</table>

<h2>Review logs</h2>
<table>
  {% for key, name, n in logs %}
  <tr><td><a href="{{ url_for('log', key=key) }}">{{ name }}</a></td>
      <td class="num">{{ n | comma }}</td></tr>
  {% endfor %}
</table>

<p class="muted">Last recorded edit: {{ last }} &middot; generated {{ now }} UTC</p>
"""

FAILED_TEMPLATE = STYLE + """
<p><a href="{{ url_for('index') }}">&larr; status</a></p>
<h1>{{ label }}</h1>
{% if description %}<p class="muted">{{ description }}</p>{% endif %}
<p><b>{{ total | comma }}</b> item(s){% if total > shown %}, showing first {{ shown | comma }}{% endif %}.</p>
<table>
  <tr><th>Item</th><th>Error</th></tr>
  {% for qid, error in rows %}
  <tr><td><a href="https://www.wikidata.org/wiki/{{ qid }}" target="_blank" rel="noopener">{{ qid }}</a></td>
      <td><code>{{ error }}</code></td></tr>
  {% endfor %}
</table>
"""

LOG_TEMPLATE = STYLE + """
<p><a href="{{ url_for('index') }}">&larr; status</a></p>
<h1>{{ label }}</h1>
{% if description %}<p class="muted">{{ description }}</p>{% endif %}
<p><b>{{ total | comma }}</b> entr(ies){% if total > shown %}, showing first {{ shown | comma }}{% endif %}.</p>
<table>
  <tr>{% for c in columns %}<th>{{ c }}</th>{% endfor %}</tr>
  {% for row in rows %}
  <tr>{% for cell in row %}<td>
    {%- if cell.startswith('Q') and cell[1:].isdigit() -%}
      <a href="https://www.wikidata.org/wiki/{{ cell }}" target="_blank" rel="noopener">{{ cell }}</a>
    {%- else -%}{{ cell }}{%- endif -%}
  </td>{% endfor %}</tr>
  {% endfor %}
</table>
"""


@app.route("/")
def index():
    handler = _DBHandler(CONFIG)
    counts = dict(handler.execute_query("SELECT status, COUNT(*) FROM qids GROUP BY status"))
    raw = handler.execute_query(_breakdown_sql())  # (key, count)
    # Firebird pads a CASE of unequal-length literals with trailing spaces.
    errors = [
        (k, LABEL_BY_KEY.get(k, k), n)
        for key, n in raw
        for k in [str(key).strip()]
    ]
    last_rows = handler.execute_query("SELECT MAX(created_at) FROM qids")
    last = last_rows[0][0] if last_rows and last_rows[0] else None

    return render_template_string(
        INDEX_TEMPLATE,
        total=sum(counts.values()),
        success=counts.get("success", 0),
        failed=counts.get("failed", 0),
        queue=_line_count(DATA_DIR / "items.txt"),
        errors=errors,
        logs=[
            (key, label, _line_count(DATA_DIR / fn))
            for key, (label, fn, _cols) in REVIEW_LOGS.items()
        ],
        last=last or "n/a",
        now=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
    )


@app.route("/failed/<key>")
def failed(key):
    key = key.strip()
    if key == "other":
        cond = "NOT (" + " OR ".join(c for _, _, c in CATEGORIES) + ")"
    elif key in CAT_BY_KEY:
        cond = CAT_BY_KEY[key][1]
    else:
        abort(404)

    handler = _DBHandler(CONFIG)
    rows = handler.execute_query(
        f"SELECT qid, error_msg FROM qids WHERE status = 'failed' AND {cond} "
        f"ORDER BY created_at DESC, qid"
    )
    return render_template_string(
        FAILED_TEMPLATE,
        label=LABEL_BY_KEY.get(key, key),
        description=DESCRIPTIONS.get(key, ""),
        total=len(rows),
        shown=min(len(rows), DISPLAY_LIMIT),
        rows=rows[:DISPLAY_LIMIT],
    )


@app.route("/log/<key>")
def log(key):
    if key not in REVIEW_LOGS:
        abort(404)
    label, filename, columns = REVIEW_LOGS[key]
    rows = []
    path = DATA_DIR / filename
    if path.exists():
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    rows.append(line.rstrip("\n").split("\t"))
    return render_template_string(
        LOG_TEMPLATE,
        label=label,
        description=LOG_DESCRIPTIONS.get(key, ""),
        columns=columns,
        total=len(rows),
        shown=min(len(rows), DISPLAY_LIMIT),
        rows=rows[:DISPLAY_LIMIT],
    )


if __name__ == "__main__":
    app.run(debug=True)
