# VIAF — Toolforge / MariaDB deploy plan

Goal: run the VIAF bot on Toolforge against **MariaDB** (ToolsDB) instead of the
local **Firebird** DB, and expose a small status page — mirroring the
`remove_sitelinks` deployment. This is a plan; nothing here is done yet.

## Current state (starting point)

- `MariaDbViafReporting` (mariadb_viaf_reporting.py) exists but **cannot run yet**:
  it `CALL`s stored procedures that don't exist in MariaDB, and there is no
  MariaDB schema. It expects `data/viaf_mariadb.json` + `schemas/viaf_mariadb.sql`.
- Backend is **hardcoded to Firebird** in `call_viaf.py`
  (`FirebirdViafReporting()`); there is no env switch.
- `schemas/viaf.sql` is **Firebird**: 8 tables (ADDED, ERRORS, IGNORED,
  NOT_FOUND, DUPLICATES, DUPLICATE_LOCAL_AUTH_IDS, CODES, PDONE), 5 domains,
  3 indexes, and **9 stored procedures** (ADD_DONE, ADD_ERROR, ADD_NOT_FOUND,
  ADD_DUPLICATE, ADD_DUPLICATE_LOCAL_AUTH_ID, CLEAN_UP,
  CLEANUP_DUPLICATE_LOCAL_AUTH_IDS, GET_STATS, END_SESSION).
- `migrate_viaf_db.py` is an **old-Firebird → new-Firebird** schema copy, *not*
  Firebird → MariaDB. A new migration is needed.
- No webservice for VIAF yet.

## Work items

### 1. Port the schema — `schemas/viaf_mariadb.sql`  (code; the big one)
- Domains → inline types (`QID` → `VARCHAR(20)`, `PID` → `VARCHAR(20)`,
  `VIAF_ID`/`AUTH_ID`/`MESSAGE` → appropriate `VARCHAR`), each table with a
  `PRIMARY KEY`, InnoDB / utf8mb4, plus the 3 indexes.
- Translate the **9 stored procedures** from Firebird PSQL to MariaDB PSM
  (`DELIMITER $$ … $$`; `FOR SELECT … INTO … DO` → cursors or set-based SQL;
  `EXECUTE PROCEDURE` → `CALL`; upserts → `INSERT … ON DUPLICATE KEY UPDATE`).
  `GET_STATS` returns a row and is read via `CALL get_stats()`.
- **Loading note:** the DB handler's `create_config` splits on `;`, which breaks
  on procedure bodies. Load this schema with the **mariadb client** (it honours
  `DELIMITER`), not via the handler:
  ```bash
  mariadb --defaults-file=~/replica.my.cnf -h tools.db.svc.wikimedia.cloud \
      s57805__viaf < ~/wikidata/schemas/viaf_mariadb.sql
  ```

### 2. Env-selectable backend  (code; small)
- In `call_viaf.py` (and anywhere else that instantiates a reporting backend),
  pick Firebird vs MariaDB from `WD_DB_BACKEND` (mariadb on Toolforge, Firebird
  locally) — same pattern as `remove_sitelinks.StatusTracker`.

### 3. Firebird → MariaDB data migration  (code; DONE — `migrate_viaf_to_mariadb.py`)
Copies every table except IGNORED (empty), preserving surrogate IDs; `--import`
DELETEs each table first so it is re-runnable. Export the latest state right
before migrating (the session keeps growing ADDED):
```bash
# locally (Firebird)
python projects/viaf/migrate_viaf_to_mariadb.py --export      # -> data/viaf_dump.json
scp projects/viaf/data/viaf_dump.json \
    difool@login.toolforge.org:/data/project/difoolbot/wikidata/projects/viaf/data/
# on Toolforge (MariaDB config in place, schema loaded)
python projects/viaf/migrate_viaf_to_mariadb.py --import
```

### 4. Config  (Toolforge; small)
- `data/viaf_mariadb.json` (non-secret): `{ "DB_HOST": "tools.db.svc.wikimedia.cloud", "DB_PORT": "3306", "DB_NAME": "s57805__viaf" }`.
- Repo-root `.env` already has `WD_DB_USER` / `WD_DB_PASSWORD` (shared with
  remove_sitelinks) — no change needed.

### 5. Toolforge database  (Toolforge; small)
```bash
sql tools                                   # then: CREATE DATABASE s57805__viaf;
# load schema (step 1) and migrate data (step 3, --import)
```

### 6. Status website  (code; DONE — VIAF blueprint added to the webservice)
- One webservice per tool, so VIAF was added to the existing one rather than a
  second service: `remove_sitelinks/webservice/viaf_page.py` is a `viaf`
  blueprint (registered by `app.py`) at `/viaf`, `/viaf/duplicates`,
  `/viaf/errors`. remove_sitelinks stays at `/`; a nav links the two.
- Reads the VIAF DB directly (its own config + backend fallback), so it needs
  `data/viaf_mariadb.json` present on Toolforge (created for the bot anyway).
- Deploy: `git pull` + `toolforge webservice python3.11 restart` (same webservice
  dir/venv/symlink — no new setup; the venv already has pymysql).

### 7. Scheduling  (wrapper DONE — `toolforge_run.sh`)
- `projects/viaf/toolforge_run.sh` sets `WD_DB_BACKEND=mariadb`, `PYTHONPATH`,
  activates the venv, and runs `python -m viaf.call_viaf`. (Separate from
  `projects/viaf_score_upd/`, which has its own.)
- Venv needs `pymysql`, `pywikibot`, `requests`, `python-dotenv`, **`PyYAML`**
  (not `firebird-driver`). If missing: `pip install PyYAML`.
- Register: `toolforge jobs run viaf --image python3.11 --schedule "0 4 * * *"
  --command "bash $HOME/wikidata/projects/viaf/toolforge_run.sh"` (daily — VIAF
  has a small daily API budget).

## Gotchas carried over from remove_sitelinks

- Credentials live in `~/replica.my.cnf` (not `~/.my.cnf`); DB name must be
  prefixed with the ToolsDB user (`s57805__…`).
- Build the venv with a Python matching the runtime image (**python3.11**), not
  the bastion's default — inside a `toolforge webservice python3.11 shell` (web)
  or a python3.11 job (bot). The bastion venv may lack `ensurepip`/`pip`.
- Deploy code by **git pull as the tool** (files owned by `tools.difoolbot`),
  not `scp` (which leaves them owned by your personal account and unreadable to
  the tool). `scp` only the gitignored `data/` dump, then `chmod a+r` it.
- The shared DB handler passes `params or None`, so literal `%` in `LIKE`
  patterns is safe.

## Suggested order

1 (schema) → 2 (backend switch) → 3 (migration) → then Toolforge 4/5 → 6
(website) → 7 (schedule). Test locally with Firebird throughout; only 4–5 and 7
touch Toolforge.
