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
DB names are `s57805__<name>` (e.g. `s57805__viaf`), credentials in `~/replica.my.cnf`.
```bash
# open a shell on a database
mariadb --defaults-file=~/replica.my.cnf -h tools.db.svc.wikimedia.cloud s57805__viaf

# run a schema / SQL file against a database
mariadb --defaults-file=~/replica.my.cnf -h tools.db.svc.wikimedia.cloud s57805__viaf < schemas/viaf_mariadb.sql
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
