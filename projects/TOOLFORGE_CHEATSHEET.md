# Toolforge cheat sheet

Tool account: `difoolbot` &middot; repo: `~/wikidata` &middot; status site: https://difoolbot.toolforge.org

## Login
```bash
ssh difoolbot@login.toolforge.org     # lands on the bastion as the tool
# or, if you sshed as yourself:
become difoolbot
```

## Deploy code (git-pull-as-tool)
```bash
cd ~/wikidata && git pull
# then restart whatever consumes it (webservice / jobs), see below
```

## Webservice (Flask status site)
```bash
toolforge webservice python3.11 start     # first time
toolforge webservice python3.11 restart   # after a git pull
toolforge webservice status
toolforge webservice logs -f              # tail logs
toolforge webservice python3.11 shell     # shell inside the web container
                                          # (build the web venv in here)
```

## Jobs (the bots)
```bash
toolforge jobs list                       # show all jobs
toolforge jobs show <name>                # one job's details
toolforge jobs logs <name>                # its logs
toolforge jobs restart <name>
toolforge jobs delete <name>
toolforge jobs load ~/jobs.yaml           # (re)create jobs from the yaml
```

## Database (ToolsDB / MariaDB)
DB names are `s57805__<name>` (e.g. `s57805__viaf`). The **`sql`** wrapper is the easy way
in — it reads `~/replica.my.cnf` and picks the host:
```bash
sql tools              # open ToolsDB (our s57805__* databases)
sql wikidatawiki       # open the Wikidata replica (lands you in wikidatawiki_p)
```
Explicit form (needed to name the db up front, or to pipe a schema file):
```bash
# open a shell on a specific database
mariadb --defaults-file=~/replica.my.cnf -h tools.db.svc.wikimedia.cloud s57805__viaf

# run a schema / SQL file against a database
mariadb --defaults-file=~/replica.my.cnf -h tools.db.svc.wikimedia.cloud s57805__viaf < schemas/viaf_mariadb.sql
```

### View / inspect tables
`sql tools` opens with **no database selected** (`MariaDB [(none)]>`), so `USE <db>;` first
(or fully-qualify names as `db.table`). End statements with `;` (or `\G` for vertical output):
```sql
SHOW DATABASES LIKE 's57805%';     -- the tool's databases
USE s57805__viaf;                  -- pick one (prompt becomes [s57805__viaf])
SHOW TABLES;                       -- its tables
SHOW TABLE STATUS;                 -- tables + row counts + sizes
DESCRIBE codes;                    -- a table's columns
SHOW CREATE TABLE codes\G          -- full schema (vertical)
SELECT COUNT(*) FROM codes;        -- row count
SELECT * FROM codes LIMIT 20;      -- peek at rows  (\G for one row per block)
```
One-off from the command line — qualify with `db.` (or `FROM <db>`) since there's no default:
```bash
sql tools --execute="SHOW DATABASES LIKE 's57805%';"
sql tools --execute="SHOW TABLES FROM s57805__viaf;"
sql tools --execute="SELECT * FROM s57805__viaf.codes LIMIT 20;"
```

## Run a bot / sync manually
The bot venv is `~/venv`; use the MariaDB backend on Toolforge.
```bash
source ~/venv/bin/activate
cd ~/wikidata

# VIAF bot
WD_DB_BACKEND=mariadb PYTHONPATH=projects:projects/shared_lib python -m viaf.call_viaf

# push viaf_config.yaml order/skips into the CODES table
WD_DB_BACKEND=mariadb python projects/viaf/codes_sync.py
```

## Notes
- `python: command not found` &rarr; you forgot `source ~/venv/bin/activate`.
- `No module named 'viaf'` with `-m` &rarr; set `PYTHONPATH=projects` (or run the
  script directly: `python projects/viaf/codes_sync.py`, which fixes its own path).
- `WD_DB_BACKEND` unset &rarr; code tries Firebird, which isn't installed here; always
  set `WD_DB_BACKEND=mariadb` on Toolforge.
- scp'd (difool-owned) files can block `git pull` &rarr; remove them, then pull.
