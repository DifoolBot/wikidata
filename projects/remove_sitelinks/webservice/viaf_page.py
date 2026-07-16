"""VIAF status page, mounted as a blueprint at /viaf by app.py.

Self-contained: it selects its own DB backend (Firebird locally, MariaDB on
Toolforge - same pattern as app.py) and reads the VIAF database. VIAF uses two
config files, one per backend (data/viaf.json vs data/viaf_mariadb.json).
"""

import math
import os
from datetime import date
from pathlib import Path

from flask import Blueprint, render_template_string, request

# viaf_page.py -> webservice/ -> remove_sitelinks/ -> projects/ -> repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
VIAF_DATA = REPO_ROOT / "projects" / "viaf" / "data"
DISPLAY_LIMIT = 500
# Sessions shown on the status page; the rest are one click away.
RECENT_SESSIONS = 5

viaf_bp = Blueprint("viaf", __name__)

STYLE = """
<style>
  body { font: 15px/1.5 system-ui, sans-serif; max-width: 760px; margin: 2rem auto; padding: 0 1rem; color: #222; }
  a { color: #1a5fb4; } h1 { font-size: 1.4rem; } h2 { font-size: 1.05rem; margin-top: 1.6rem; color: #555; }
  table { border-collapse: collapse; margin: .4rem 0; width: 100%; } td, th { padding: .25rem .8rem; text-align: left; }
  tr:nth-child(even) { background: #f6f6f6; } .num { text-align: right; font-variant-numeric: tabular-nums; }
  .big { font-size: 1.8rem; font-weight: 600; } .muted { color: #888; font-size: .85rem; }
  code { color: #666; } nav a { margin-right: 1rem; }
  .bar { background: #eee; border-radius: 3px; height: 8px; overflow: hidden; margin: .3rem 0; }
  .bar span { background: #3584e4; display: block; height: 100%; }
  .source { font-size: 1.05rem; }
  .pie-wrap { display: flex; align-items: center; gap: 1.4rem; flex-wrap: wrap; margin: .6rem 0 1rem; }
  .pie { width: 110px; height: 110px; border-radius: 50%; flex: none; }
  .legend { width: auto; } .legend tr:nth-child(even) { background: none; }
  .legend td { padding: .1rem .6rem .1rem 0; }
  .swatch { display: inline-block; width: .7rem; height: .7rem; border-radius: 2px;
            vertical-align: middle; margin-right: .45rem; }
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
    """The settings from viaf_config.yaml, or the reason they can't be read.

    Returns (config, None) or (None, reason). The reason is surfaced on the page
    instead of being swallowed: a silently missing Settings block looks exactly
    like one that was never meant to be there. Needs PyYAML in the webservice
    venv, which is not the same venv the bot runs from.
    """
    try:
        from viaf.viaf_config import load_config

        return load_config(), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


# Shared by the index (most recent few) and the full sessions page.
SESSIONS_TABLE = """
<table>
  <tr><th>Source</th><th>Description</th><th class="num">Checked</th><th class="num">Added</th><th class="num">Not found</th><th>Finished</th></tr>
  {% for pid, desc, checked, added, nf, done in pdone %}
  <tr><td><a href="https://www.wikidata.org/wiki/Property:{{ pid }}" target="_blank" rel="noopener">{{ pid }}</a></td>
      <td>{{ desc }}</td><td class="num">{{ checked | comma }}</td><td class="num">{{ added | comma }}</td>
      <td class="num">{{ nf | comma }}</td><td>{{ done }}</td></tr>
  {% endfor %}
</table>
"""

INDEX_TEMPLATE = STYLE + """
<h1>VIAF &mdash; status</h1>
{% if not current_pid and cooldown_until %}
<p class="muted">In cooldown until {{ cooldown_until }}.</p>
{% endif %}

<h2>Current session</h2>
{% if current_pid %}
<p class="source"><a href="https://www.wikidata.org/wiki/Property:{{ current_pid }}" target="_blank" rel="noopener"><b>{{ current_pid }}</b></a>
  {%- if current_desc %} &mdash; <b>{{ current_desc }}</b>{% endif -%}
  {%- if cooldown_until %} <span class="muted">&middot; in cooldown until {{ cooldown_until }}</span>{% endif %}</p>
{% endif %}
<p><span class="big">{{ added | comma }}</span> added of {{ checked | comma }} checked</p>
{% if pie_legend %}
<div class="pie-wrap">
  <div class="pie" style="background: {{ pie_gradient }}"></div>
  <table class="legend">
    {% for s in pie_legend %}
    <tr><td><span class="swatch" style="background: {{ s.colour }}"></span>{{ s.label }}</td>
        <td class="num">{{ s.count | comma }}</td>
        <td class="num muted">{{ '%.1f' % s.pct }}%</td></tr>
    {% endfor %}
  </table>
</div>
{% endif %}
{% if total_rows %}
<p>{{ done_rows | comma }} of {{ total_rows | comma }} rows done{% if pct is not none %} ({{ '%.1f' % pct }}%){% endif %},
   {{ remaining_rows | comma }} to go.</p>
<div class="bar"><span style="width: {{ '%.1f' % (pct or 0) }}%"></span></div>
<p class="muted">
  {%- if session_start %}Started {{ session_start }}{% endif -%}
  {%- if eta_days is not none %} &middot; ~{{ eta_days }} more day(s) at the current rate{% endif -%}
</p>
{% endif %}

<h2>Reports</h2>
<table>
  <tr><td><a href="{{ url_for('viaf.duplicates') }}">Duplicate items</a></td><td class="num">{{ duplicates | comma }}</td></tr>
  <tr><td><a href="{{ url_for('viaf.duplicate_locals') }}">Duplicate local authority ids</a></td><td class="num">{{ dup_locals | comma }}</td></tr>
  <tr><td><a href="{{ url_for('viaf.errors', kind='not_found') }}">Not found</a></td><td class="num">{{ not_found | comma }}</td></tr>
  <tr><td><a href="{{ url_for('viaf.errors', kind='other') }}">Other errors</a></td><td class="num">{{ other_errors | comma }}</td></tr>
  <tr><td>not-found cache</td><td class="num">{{ not_found_cache | comma }}</td></tr>
</table>
<p><a href="{{ url_for('viaf.config_page') }}">Settings &amp; processing order &rarr;</a></p>

<h2>Recent sessions</h2>
""" + SESSIONS_TABLE + """
{% if pdone_total > pdone | length %}
<p><a href="{{ url_for('viaf.sessions') }}">All {{ pdone_total | comma }} sessions &rarr;</a></p>
{% endif %}
"""

SESSIONS_TEMPLATE = STYLE + """
<p><a href="{{ url_for('viaf.index') }}">&larr; VIAF status</a></p>
<h1>VIAF &mdash; sessions</h1>
<p><b>{{ pdone_total | comma }}</b> finished session(s), newest first.</p>
""" + SESSIONS_TABLE

LIST_TEMPLATE = STYLE + """
<p><a href="{{ url_for('viaf.index') }}">&larr; VIAF status</a></p>
<h1>{{ title }}</h1>
<p><b>{{ total | comma }}</b> row(s){% if total > shown %}, showing first {{ shown | comma }}{% endif %}.</p>
<table>
  <tr>{% for c in columns %}<th>{{ c.label }}</th>{% endfor %}</tr>
  {% for row in rows %}
  <tr>{% for cell in row %}<td>
    {%- set col = columns[loop.index0] -%}
    {%- if cell and col.url -%}
      <a href="{{ col.url }}{{ cell }}" target="_blank" rel="noopener">{{ cell }}</a>
    {%- elif cell is string and cell.startswith('Q') and cell[1:].isdigit() -%}
      <a href="https://www.wikidata.org/wiki/{{ cell }}" target="_blank" rel="noopener">{{ cell }}</a>
    {%- else -%}{{ cell }}{%- endif -%}
  </td>{% endfor %}</tr>
  {% endfor %}
</table>
"""


CONFIG_TEMPLATE = STYLE + """
<p><a href="{{ url_for('viaf.index') }}">&larr; VIAF status</a></p>
<h1>VIAF &mdash; configuration</h1>
<h2>Settings</h2>
{% if settings_ok %}
<table>
  <tr><td>Max duplicates per source</td><td class="num">{{ max_duplicates if max_duplicates is not none else 'off' }}</td></tr>
  <tr><td>Cooldown after a full pass (days)</td><td class="num">{{ cooldown_days }}</td></tr>
  <tr><td>not-found cache (days)</td><td class="num">{{ not_found_cache_days if not_found_cache_days is not none else 'off' }}</td></tr>
</table>
<p class="muted">From <code>viaf_config.yaml</code>, which is also what the bot reads.</p>
{% else %}
<p class="muted">Unavailable &mdash; <code>viaf_config.yaml</code> could not be read: {{ settings_error }}</p>
{% endif %}

<h2>Processing order</h2>
<p class="muted">Sources in the order the bot processes them.</p>
<table>
  <tr><th class="num">#</th><th>PID</th><th>Description</th><th>Last run</th></tr>
  {% for pid, desc, last in order %}
  <tr><td class="num">{{ loop.index }}</td>
      <td><a href="https://www.wikidata.org/wiki/Property:{{ pid }}" target="_blank" rel="noopener">{{ pid }}</a></td>
      <td>{{ desc }}</td><td>{{ last }}</td></tr>
  {% endfor %}
</table>

<h2>Skipped</h2>
<table>
  <tr><th>PID</th><th>Description</th></tr>
  {% for pid, desc in ignore %}
  <tr><td><a href="https://www.wikidata.org/wiki/Property:{{ pid }}" target="_blank" rel="noopener">{{ pid }}</a></td><td>{{ desc }}</td></tr>
  {% endfor %}
</table>
"""


def _state(handler) -> dict:
    """The bot's STATE row: which source is running, and how far along.

    Empty when the bot has never run. Read from the database (not a file) so this
    page needs no access to the bot's runtime directory.
    """
    rows = handler.execute_query(
        "SELECT CURRENT_PID, COOLDOWN_UNTIL, SESSION_START, TOTAL_ROWS, "
        "REMAINING_ROWS FROM STATE WHERE ID = 1"
    )
    if not rows:
        return {}
    pid, cooldown_until, session_start, total, remaining = rows[0]
    return {
        "current_pid": pid.strip() if pid else None,
        "cooldown_until": _date(cooldown_until),
        "session_start": _date(session_start),
        "total_rows": total,
        "remaining_rows": remaining,
    }


VIAF_URL = "https://viaf.org/viaf/"

# VIAF not knowing an item is routine and is most of the ERRORS table; anything
# else is worth reading. The bot writes "status not_found" for the former (see
# ViafBot.process_record), so the message is what separates them.
NOT_FOUND_CLAUSE = "MESSAGE LIKE '%status not_found%'"


def _col(label: str, url: str | None = None) -> dict:
    """A column of a list table.

    *url* is a prefix the cell's value is appended to. Without it the cell is
    plain text, unless it looks like a QID. Linking has to be declared per
    column rather than sniffed from the value: a VIAF id and an IdRef id are
    both bare numbers, so guessing would point local authority ids at viaf.org.
    """
    return {"label": label, "url": url}


def _pie(slices: list[tuple[str, int, str]]):
    """A CSS conic-gradient plus its legend, for a small pie chart.

    Takes (label, count, colour) and returns (gradient, legend rows). A plain
    gradient keeps this dependency-free: no JS, no charting library, no external
    request. Returns ('', []) when there is nothing to chart.
    """
    total = sum(count for _, count, _ in slices)
    if total <= 0:
        return "", []
    stops, legend, running = [], [], 0.0
    for label, count, colour in slices:
        pct = count / total * 100
        # each slice spans from where the last one ended to its own end
        stops.append(f"{colour} {running:.2f}% {running + pct:.2f}%")
        legend.append({"label": label, "count": count, "pct": pct, "colour": colour})
        running += pct
    return f"conic-gradient({', '.join(stops)})", legend


def _session_rows(pdone, codes: dict) -> list[tuple]:
    """PDONE rows with the source's description filled in and the date trimmed."""
    return [
        (pid, codes.get(pid) or "", checked, added, nf, _date(done))
        for pid, checked, added, nf, done in pdone
    ]


def _eta_days(state: dict) -> int | None:
    """Whole days until the current source finishes, from its rate so far.

    None while there is nothing to extrapolate from: no counts, nothing done
    yet, or the session started today (no elapsed time to measure a rate over).
    """
    total, remaining = state.get("total_rows"), state.get("remaining_rows")
    start = state.get("session_start")
    if not total or remaining is None or not start:
        return None
    done = total - remaining
    if done <= 0 or remaining <= 0:
        return None
    elapsed = (date.today() - date.fromisoformat(start)).days
    if elapsed < 1:
        return None
    per_day = done / elapsed
    return math.ceil(remaining / per_day) if per_day else None


@viaf_bp.route("/viaf")
def index():
    h = _handler()
    added = _one(h, "SELECT COUNT(*) FROM ADDED")
    errors = _one(h, "SELECT COUNT(*) FROM ERRORS")
    # Same clause the /viaf/errors filter uses, so a row's count and the page it
    # links to cannot drift apart.
    not_found = _one(h, f"SELECT COUNT(*) FROM ERRORS WHERE {NOT_FOUND_CLAUSE}")
    other_errors = errors - not_found
    # PID -> description, for the active source and the PDONE table.
    codes = dict(h.execute_query("SELECT PID, DESCRIPTION FROM CODES"))
    pdone = h.execute_query(
        "SELECT PID, CHECKED, ADDED, NOT_FOUND, DONE_DATE FROM PDONE ORDER BY DONE_DATE DESC, ID DESC"
    )
    state = _state(h)
    current_pid = state.get("current_pid")
    total, remaining = state.get("total_rows"), state.get("remaining_rows")
    done_rows = (total - remaining) if total and remaining is not None else None
    # What became of the items checked this session: every checked item is either
    # added or an error, and most errors are VIAF simply not knowing the item.
    pie_gradient, pie_legend = _pie(
        [
            ("added", added, "#2ec27e"),
            ("not found", not_found, "#f5c211"),
            ("other errors", other_errors, "#e01b24"),
        ]
    )
    return render_template_string(
        INDEX_TEMPLATE,
        added=added,
        errors=errors,
        not_found=not_found,
        other_errors=other_errors,
        checked=added + errors,
        duplicates=_one(h, "SELECT COUNT(*) FROM DUPLICATES"),
        dup_locals=_one(h, "SELECT COUNT(*) FROM DUPLICATE_LOCAL_AUTH_IDS"),
        not_found_cache=_one(h, "SELECT COUNT(*) FROM NOT_FOUND"),
        pdone=_session_rows(pdone[:RECENT_SESSIONS], codes),
        pdone_total=len(pdone),
        current_pid=current_pid,
        current_desc=(codes.get(current_pid) or "") if current_pid else "",
        cooldown_until=state.get("cooldown_until"),
        session_start=state.get("session_start"),
        total_rows=total,
        remaining_rows=remaining,
        done_rows=done_rows,
        pct=(done_rows / total * 100) if total and done_rows is not None else None,
        eta_days=_eta_days(state),
        pie_gradient=pie_gradient,
        pie_legend=pie_legend,
    )


@viaf_bp.route("/viaf/sessions")
def sessions():
    h = _handler()
    codes = dict(h.execute_query("SELECT PID, DESCRIPTION FROM CODES"))
    # Newest first. ID is the tie-break, not the sort: the migration from
    # Firebird carried the old surrogate ids over, so they need not run in
    # date order.
    pdone = h.execute_query(
        "SELECT PID, CHECKED, ADDED, NOT_FOUND, DONE_DATE FROM PDONE "
        "ORDER BY DONE_DATE DESC, ID DESC"
    )
    return render_template_string(
        SESSIONS_TEMPLATE,
        pdone=_session_rows(pdone, codes),
        pdone_total=len(pdone),
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
        columns=[
            _col("Item"),
            _col("Duplicate of"),
            _col("Local auth id"),
            _col("VIAF id", VIAF_URL),
        ],
        total=len(rows),
        shown=min(len(rows), DISPLAY_LIMIT),
        rows=rows[:DISPLAY_LIMIT],
    )


@viaf_bp.route("/viaf/duplicate-locals")
def duplicate_locals():
    h = _handler()
    # Same order the wiki report uses, so the two read alike.
    rows = h.execute_query(
        "SELECT QID, LOCAL_AUTH_ID, VIAF_ID FROM DUPLICATE_LOCAL_AUTH_IDS "
        "ORDER BY VIAF_ID, QID, LOCAL_AUTH_ID"
    )
    return render_template_string(
        LIST_TEMPLATE,
        title="Duplicate local authority ids",
        columns=[_col("Item"), _col("Local auth id"), _col("VIAF id", VIAF_URL)],
        total=len(rows),
        shown=min(len(rows), DISPLAY_LIMIT),
        rows=rows[:DISPLAY_LIMIT],
    )


@viaf_bp.route("/viaf/errors")
def errors():
    h = _handler()
    # ?kind=not_found / ?kind=other split the table the same way the pie does;
    # without it, the page lists every error as before.
    kind = request.args.get("kind")
    if kind == "not_found":
        where, title = f"WHERE {NOT_FOUND_CLAUSE}", "Not found"
    elif kind == "other":
        where, title = f"WHERE NOT ({NOT_FOUND_CLAUSE})", "Other errors"
    else:
        where, title = "", "Errors"
    rows = h.execute_query(
        f"SELECT QID, MESSAGE, ERROR_DATE FROM ERRORS {where} "
        "ORDER BY ERROR_DATE DESC, QID"
    )
    return render_template_string(
        LIST_TEMPLATE,
        title=title,
        columns=[_col("Item"), _col("Message"), _col("When")],
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
    # Latest finished date per source, to show when each was last run.
    last_done = dict(
        h.execute_query("SELECT PID, MAX(DONE_DATE) FROM PDONE GROUP BY PID")
    )
    cfg, settings_error = _config()  # settings live only in the yaml
    return render_template_string(
        CONFIG_TEMPLATE,
        settings_ok=cfg is not None,
        settings_error=settings_error,
        max_duplicates=cfg.max_duplicates if cfg else None,
        cooldown_days=cfg.cooldown_days if cfg else None,
        not_found_cache_days=cfg.not_found_cache_days if cfg else None,
        order=[(pid, desc or "", _date(last_done.get(pid))) for pid, desc in order],
        ignore=[(pid, desc or "") for pid, desc in ignore],
    )
