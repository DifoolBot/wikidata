"""VIAF status page, mounted as a blueprint at /viaf by app.py.

Self-contained: it selects its own DB backend (Firebird locally, MariaDB on
Toolforge - same pattern as app.py) and reads the VIAF database. VIAF uses two
config files, one per backend (data/viaf.json vs data/viaf_mariadb.json).
"""

import json
import os
from pathlib import Path

from flask import Blueprint, render_template_string

# viaf_page.py -> webservice/ -> remove_sitelinks/ -> projects/ -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
VIAF_DATA = REPO_ROOT / "projects" / "viaf" / "data"
PROGRESS_FILE = VIAF_DATA / "viaf_progress.json"
DISPLAY_LIMIT = 500

viaf_bp = Blueprint("viaf", __name__)

STYLE = """
<style>
  body { font: 15px/1.5 system-ui, sans-serif; max-width: 760px; margin: 2rem auto; padding: 0 1rem; color: #222; }
  a { color: #1a5fb4; } h1 { font-size: 1.4rem; } h2 { font-size: 1.05rem; margin-top: 1.6rem; color: #555; }
  table { border-collapse: collapse; margin: .4rem 0; width: 100%; } td, th { padding: .25rem .8rem; text-align: left; }
  tr:nth-child(even) { background: #f6f6f6; } .num { text-align: right; font-variant-numeric: tabular-nums; }
  .big { font-size: 1.8rem; font-weight: 600; } .muted { color: #888; font-size: .85rem; }
  code { color: #666; } nav a { margin-right: 1rem; }
</style>
<nav class="muted"><a href="/">remove_sitelinks</a><a href="/viaf">viaf</a></nav>
"""


def _handler():
    """VIAF DB handler: MariaDB on Toolforge, else Firebird locally; falls back to
    MariaDB when the Firebird driver isn't installed (Toolforge webservice venv)."""
    backend = os.environ.get("WD_DB_BACKEND", "").lower()
    if backend == "mariadb":
        from database_handler_mariadb import MariaDbDatabaseHandler as handler
        return handler(VIAF_DATA / "viaf_mariadb.json")
    if backend == "firebird":
        from database_handler_firebird import FirebirdDatabaseHandler as handler
        return handler(VIAF_DATA / "viaf.json")
    try:
        from database_handler_firebird import FirebirdDatabaseHandler as handler
        return handler(VIAF_DATA / "viaf.json")
    except ImportError:
        from database_handler_mariadb import MariaDbDatabaseHandler as handler
        return handler(VIAF_DATA / "viaf_mariadb.json")


def _one(handler, sql: str) -> int:
    rows = handler.execute_query(sql)
    return rows[0][0] if rows and rows[0] else 0


def _date(value) -> str:
    """Just the calendar date, dropping the time."""
    if not value:
        return ""
    if hasattr(value, "date"):  # datetime -> date
        return value.date().isoformat()
    return str(value)[:10]  # 'YYYY-MM-DD HH:MM:SS' -> 'YYYY-MM-DD'


def _config():
    """The ViafConfig (order / ignore / settings), or None if PyYAML isn't
    installed in the webservice venv or the config can't be read."""
    try:
        from viaf.viaf_config import load_config

        return load_config()
    except Exception:
        return None


INDEX_TEMPLATE = STYLE + """
<h1>VIAF &mdash; status</h1>
{% if current_pid %}
<p class="muted">Active source: <b>{{ current_pid }}</b>{% if current_desc %} &mdash; {{ current_desc }}{% endif %}{% if cooldown_until %} &middot; in cooldown until {{ cooldown_until }}{% endif %}</p>
{% elif cooldown_until %}
<p class="muted">In cooldown until {{ cooldown_until }}.</p>
{% endif %}
<h2>Current session</h2>
<p><span class="big">{{ added | comma }}</span> added &nbsp;
   ({{ checked | comma }} checked, {{ errors | comma }} error(s) of which {{ not_found | comma }} not-found)</p>

<h2>Reports</h2>
<table>
  <tr><td><a href="{{ url_for('viaf.duplicates') }}">Duplicate items</a></td><td class="num">{{ duplicates | comma }}</td></tr>
  <tr><td>Duplicate local authority ids</td><td class="num">{{ dup_locals | comma }}</td></tr>
  <tr><td><a href="{{ url_for('viaf.errors') }}">Errors</a></td><td class="num">{{ errors | comma }}</td></tr>
  <tr><td>not-found cache</td><td class="num">{{ not_found_cache | comma }}</td></tr>
</table>
<p><a href="{{ url_for('viaf.config_page') }}">Settings &amp; processing order &rarr;</a></p>

<h2>Recent sessions</h2>
<table>
  <tr><th>Source</th><th>Description</th><th class="num">Checked</th><th class="num">Added</th><th class="num">Not found</th><th>Finished</th></tr>
  {% for pid, desc, checked, added, nf, done in pdone %}
  <tr><td>{{ pid }}</td><td>{{ desc }}</td><td class="num">{{ checked | comma }}</td><td class="num">{{ added | comma }}</td>
      <td class="num">{{ nf | comma }}</td><td>{{ done }}</td></tr>
  {% endfor %}
</table>
"""

LIST_TEMPLATE = STYLE + """
<p><a href="{{ url_for('viaf.index') }}">&larr; VIAF status</a></p>
<h1>{{ title }}</h1>
<p><b>{{ total | comma }}</b> row(s){% if total > shown %}, showing first {{ shown | comma }}{% endif %}.</p>
<table>
  <tr>{% for c in columns %}<th>{{ c }}</th>{% endfor %}</tr>
  {% for row in rows %}
  <tr>{% for cell in row %}<td>
    {%- if cell is string and cell.startswith('Q') and cell[1:].isdigit() -%}
      <a href="https://www.wikidata.org/wiki/{{ cell }}" target="_blank" rel="noopener">{{ cell }}</a>
    {%- else -%}{{ cell }}{%- endif -%}
  </td>{% endfor %}</tr>
  {% endfor %}
</table>
"""


CONFIG_TEMPLATE = STYLE + """
<p><a href="{{ url_for('viaf.index') }}">&larr; VIAF status</a></p>
<h1>VIAF &mdash; configuration</h1>
{% if settings_ok %}
<h2>Settings</h2>
<table>
  <tr><td>Max duplicates per source</td><td class="num">{{ max_duplicates if max_duplicates is not none else 'off' }}</td></tr>
  <tr><td>Cooldown after a full pass (days)</td><td class="num">{{ cooldown_days }}</td></tr>
  <tr><td>not-found cache (days)</td><td class="num">{{ not_found_cache_days if not_found_cache_days is not none else 'off' }}</td></tr>
</table>
{% endif %}

<h2>Processing order</h2>
<p class="muted">Sources in the order the bot processes them (from the CODES table;
order is empty until the bot or `python -m viaf.codes_sync` has run).</p>
<table>
  <tr><th class="num">#</th><th>PID</th><th>Description</th></tr>
  {% for pid, desc in order %}
  <tr><td class="num">{{ loop.index }}</td><td>{{ pid }}</td><td>{{ desc }}</td></tr>
  {% endfor %}
</table>

<h2>Skipped</h2>
<table>
  <tr><th>PID</th><th>Description</th></tr>
  {% for pid, desc in ignore %}
  <tr><td>{{ pid }}</td><td>{{ desc }}</td></tr>
  {% endfor %}
</table>
"""


def _progress() -> dict:
    if not PROGRESS_FILE.exists():
        return {}
    try:
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@viaf_bp.route("/viaf")
def index():
    h = _handler()
    added = _one(h, "SELECT COUNT(*) FROM ADDED")
    errors = _one(h, "SELECT COUNT(*) FROM ERRORS")
    not_found = _one(
        h, "SELECT COUNT(*) FROM ERRORS WHERE MESSAGE LIKE '%status not_found%'"
    )
    # PID -> description, for the active source and the PDONE table.
    codes = dict(h.execute_query("SELECT PID, DESCRIPTION FROM CODES"))
    pdone = h.execute_query(
        "SELECT PID, CHECKED, ADDED, NOT_FOUND, DONE_DATE FROM PDONE ORDER BY ID DESC"
    )
    progress = _progress()
    current_pid = progress.get("current_pid")
    return render_template_string(
        INDEX_TEMPLATE,
        added=added,
        errors=errors,
        not_found=not_found,
        checked=added + errors,
        duplicates=_one(h, "SELECT COUNT(*) FROM DUPLICATES"),
        dup_locals=_one(h, "SELECT COUNT(*) FROM DUPLICATE_LOCAL_AUTH_IDS"),
        not_found_cache=_one(h, "SELECT COUNT(*) FROM NOT_FOUND"),
        pdone=[
            (pid, codes.get(pid) or "", checked, add, nf, _date(done))
            for pid, checked, add, nf, done in pdone[:DISPLAY_LIMIT]
        ],
        current_pid=current_pid,
        current_desc=(codes.get(current_pid) or "") if current_pid else "",
        cooldown_until=progress.get("cooldown_until"),
    )


@viaf_bp.route("/viaf/duplicates")
def duplicates():
    h = _handler()
    rows = h.execute_query(
        "SELECT QID, DUPLICATE_QID, LOCAL_AUTH_ID, VIAF_ID FROM DUPLICATES "
        "ORDER BY VIAF_ID, QID"
    )
    return render_template_string(
        LIST_TEMPLATE,
        title="Duplicate items",
        columns=["Item", "Duplicate of", "Local auth id", "VIAF id"],
        total=len(rows),
        shown=min(len(rows), DISPLAY_LIMIT),
        rows=rows[:DISPLAY_LIMIT],
    )


@viaf_bp.route("/viaf/errors")
def errors():
    h = _handler()
    rows = h.execute_query(
        "SELECT QID, MESSAGE, ERROR_DATE FROM ERRORS ORDER BY ERROR_DATE DESC, QID"
    )
    return render_template_string(
        LIST_TEMPLATE,
        title="Errors",
        columns=["Item", "Message", "When"],
        total=len(rows),
        shown=min(len(rows), DISPLAY_LIMIT),
        rows=rows[:DISPLAY_LIMIT],
    )


@viaf_bp.route("/viaf/config")
def config_page():
    h = _handler()
    # Full processing order + skips come from CODES (SORT_ORDER / DO_IGNORE),
    # materialised from viaf_config.yaml by the bot / codes_sync.
    order = h.execute_query(
        "SELECT PID, DESCRIPTION FROM CODES WHERE NOT DO_IGNORE "
        "ORDER BY CASE WHEN SORT_ORDER IS NULL THEN 1 ELSE 0 END, SORT_ORDER, PID"
    )
    ignore = h.execute_query(
        "SELECT PID, DESCRIPTION FROM CODES WHERE DO_IGNORE ORDER BY PID"
    )
    cfg = _config()  # yaml-only settings; None if PyYAML missing
    return render_template_string(
        CONFIG_TEMPLATE,
        settings_ok=cfg is not None,
        max_duplicates=cfg.max_duplicates if cfg else None,
        cooldown_days=cfg.cooldown_days if cfg else None,
        not_found_cache_days=cfg.not_found_cache_days if cfg else None,
        order=[(pid, desc or "") for pid, desc in order],
        ignore=[(pid, desc or "") for pid, desc in ignore],
    )
