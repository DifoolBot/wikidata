# remove_sitelinks

Bot that ends (adds a `P582` end time to) `P143`/`P4656` "imported from Wikipedia"
references whose source Wikipedia page was deleted, moved to draft, or userfied,
on items that lack the corresponding sitelink.

## Notes

### Data-entry recommendation: add P4656 when the source isn't the item's own page

When importing statements into Wikidata, add a **`P4656` (Wikimedia import URL)**
alongside **`P143`** whenever the source page is **not the item's own Wikipedia
article** — e.g. the fact comes from an award/list article, a related person's
article (spouse, parent), or a category page.

A bare `P143` ("imported from English Wikipedia") is only unambiguous when the
source *is* the item's own page. As soon as it cites a list/award/relative page,
the reference becomes unresolvable after the fact: you can't tell what it cited,
and cleanup can't distinguish a legitimate list-import (source still exists) from
a deleted-page import.

Example: an award (`P166`) statement on a person with no English article often
carries a bare `P143=enwiki` reference imported from the *award's* list article
(e.g. `Scott Kugle` → the "Stonewall Book Award" article, which lists him). Such
references are valid and must not be removed or end-dated — this bot correctly
leaves them alone and records them in `data/unresolved_p143_refs.txt`.

## Runtime data & review logs

Mutable state lives in `data/` (gitignored):

- `items.txt` — the work queue (QIDs to process).
- `remove_sitelinks.json` — DB connection details (non-secret; user/password come
  from the repo-root `.env`).
- `wikipedia_editions_cache.txt` — cached edition QID → subdomain map.
- Review logs (nothing was edited; look these over by hand):
  - `unresolved_p143_refs.txt` — P143-only refs with no removal comment / snapshot.
  - `deleted_media_refs.txt` — statements skipped because their Commons file is gone.
  - `renamed_still_exists_refs.txt` — source page renamed within mainspace and still
    exists (often a missing sitelink or a duplicate item).

## Running on Toolforge

The tracker supports two DB backends: **Firebird** locally (default) and
**MariaDB** on Toolforge (set `WD_DB_BACKEND=mariadb`).

### 1. Create the ToolsDB database (once)

```bash
ssh login.toolforge.org && become <toolname>
cat ~/replica.my.cnf             # note the user (sNNNNN) + password (same creds for ToolsDB)
sql tools                        # opens the MariaDB client on ToolsDB
```
```sql
CREATE DATABASE sNNNNN__remove_sitelinks;   -- must be prefixed with your DB user + __
```
Exit the client, then load the schema. `sql tools <db>` does not select the
database, so use the `mariadb` client directly (database as a positional arg):
```bash
mariadb --defaults-file=~/replica.my.cnf -h tools.db.svc.wikimedia.cloud \
    sNNNNN__remove_sitelinks < ~/wikidata/schemas/remove_sitelinks_mariadb.sql
# verify:
mariadb --defaults-file=~/replica.my.cnf -h tools.db.svc.wikimedia.cloud \
    sNNNNN__remove_sitelinks -e "SHOW TABLES;"
```

### 2. Config

`data/remove_sitelinks.json` (non-secret connection details only):
```json
{ "DB_HOST": "tools.db.svc.wikimedia.cloud", "DB_PORT": "3306", "DB_NAME": "sNNNNN__remove_sitelinks" }
```
Repo-root `.env` (secrets, gitignored):
```
WD_DB_USER=sNNNNN
WD_DB_PASSWORD=<from ~/replica.my.cnf>
```
Venv needs `pymysql`, `pywikibot`, `requests`, `python-dotenv` (no `firebird-driver`).

### 2b. Migrate the tracker data (once, before the first real run)

Copy the already-processed items from the local Firebird DB so Toolforge doesn't
edit them a second time. ToolsDB isn't reachable from outside Toolforge, so it's
export-locally / import-on-Toolforge, via `data/tracker_dump.json`:

```bash
# locally (Windows, Firebird). --include-failed carries the whole table so
# nothing reprocesses on the first Toolforge run; omit it to carry only the
# already-edited 'success' rows (then 'failed' items reprocess with current fixes).
python projects/remove_sitelinks/migrate_tracker_db.py --export --include-failed

# copy the dump to Toolforge
scp projects/remove_sitelinks/data/tracker_dump.json \
    <toolname>@login.toolforge.org:~/wikidata/projects/remove_sitelinks/data/

# on Toolforge (MariaDB config in place, DB + schema created):
python projects/remove_sitelinks/migrate_tracker_db.py --import
```

A `failed` item was never edited (failures always abort before `apply()`), so
copying it can't cause a double-edit — it just means that item won't be retried.
Most failures are benign "source still exists" cases (EXISTS / REDIRECT: a
category, spouse, list, or renamed article). To retry a category later, clear it
on MariaDB and let the next `--refresh` re-add those QIDs to `items.txt`:

```sql
-- e.g. retry the REDIRECT failures
DELETE FROM qids WHERE status = 'failed' AND error_msg LIKE '%status: REDIRECT%';
```

### 3. Run / schedule

`remove_sitelinks.py` has a small CLI (defaults to a safe dry-run):

- *(no flag)* — **dry-run**: no Wikidata edits and no DB writes, so it never
  blocks a later real run. Good for a first test.
- `--save` — actually edit Wikidata (and record progress in the DB).
- `--refresh` — refetch `items.txt` via qlever for all supported languages first
  (slow — occasional use, not every run).

`toolforge_run.sh` activates the venv, sets `WD_DB_BACKEND=mariadb` and
`PYTHONPATH`, and passes flags through. Test once, then schedule the real run:

```bash
# one-off dry-run test (no --save)
toolforge jobs run remove-sitelinks --image python3.11 --wait \
    --command "bash $HOME/wikidata/projects/remove_sitelinks/toolforge_run.sh"

# weekly real run, Monday 05:00 UTC (daily would be "0 5 * * *")
toolforge jobs run remove-sitelinks --image python3.11 \
    --schedule "0 5 * * 1" \
    --command "bash $HOME/wikidata/projects/remove_sitelinks/toolforge_run.sh --save"
```
`toolforge jobs list` / `toolforge jobs logs remove-sitelinks` to inspect. Invoke
via `bash …` so the script's executable bit doesn't matter.

### 4. Status page (optional webservice)

`webservice/app.py` is a small Flask page showing DB counts, the failure
breakdown, the queue size and the review-log counts. Deploy it as the tool's
webservice (separate venv from the bot):

```bash
mkdir -p ~/www/python
ln -s ~/wikidata/projects/remove_sitelinks/webservice ~/www/python/src

# Build the venv INSIDE the python3.11 container (the bastion's python is a
# different version and lacks venv/ensurepip):
toolforge webservice python3.11 shell
  python3 -m venv ~/www/python/venv
  ~/www/python/venv/bin/pip install --upgrade pip
  ~/www/python/venv/bin/pip install -r ~/www/python/src/requirements.txt
  exit

toolforge webservice python3.11 start      # restart / stop likewise
```
Then browse to `https://<toolname>.toolforge.org/`. It reads the same
`data/remove_sitelinks.json` + repo-root `.env` for the DB connection.
