# remove_import_ref

Removes `imported from Wikimedia project` (**P143**) references that a specific
(now banned) user added to Wikidata items, **when the item has no sitelink to
that Wikipedia** — neither now, nor at the moment the reference was added.

## Matching rule

A reference is removed only when **all** hold:

1. It is a P143 reference whose value is a Wikipedia edition (e.g. `Q8449` →
   Spanish Wikipedia → `eswiki`).
2. The target user added it (a `wbsetreference-add` revision by that user).
3. The item has **no sitelink** to that wiki — both **at the add-revision** and
   **currently**.

The reference must still be present unchanged on the live item (matched by
`(claim GUID, reference hash)`), so we never touch a reference someone edited.

## How it works (no DB — text files only)

Per item (cost scales with the list, not the user's 2.8M global edits, because
`rvuser` is applied per page):

1. `wikidata_api.user_revisions(qid, user)` → the user's revisions on that item;
   keep the `wbsetreference-add` ones. Revision id ⇒ timestamp **T**.
2. `entities_at_revisions([revid, parentid])` (one request) →
   `reference_checker.added_import_refs(...)` returns exactly the P143 refs that
   revision introduced (diff of `(claim, hash)` pairs), plus the **sitelinks at T**.
3. Condition 3 from the revision-T sitelinks; condition 2 from the live entity.
4. `remover.remove_reference(...)` deletes the matched reference (only on `--save`).

Reads use pywikibot's low-level `api.Request` (not `ItemPage`, which can't give
entity JSON at an old revision by user). Reads and the edit share one pywikibot
`Site`, so rate limiting (maxlag/retries/throttle) and User-Agent come from
pywikibot config — no hand-rolled limiter, no second HTTP stack.

## Run

```bash
pip install -r requirements.txt                       # needs a configured pywikibot
python -m projects.remove_import_ref.bot              # dry-run (default), all items
python -m projects.remove_import_ref.bot --limit 3    # dry-run, first 3
python -m projects.remove_import_ref.bot --save       # really edit
pytest projects/remove_import_ref/tests -q            # offline unit tests (no network/pywikibot)
```

Note: even a dry-run needs pywikibot configured (reads go through it too), but
reads are anonymous — only `--save` needs login/OAuth.

Input: `input/items.txt` (one QID per line). Outputs in `output/`:
`matched.csv`, `skipped.csv`, `run.log`, and `done.txt` (resumable — done QIDs
are skipped on rerun). `dbcode_cache.txt` caches resolved project→dbname lookups.

## Toolforge deployment

```bash
# 0. SSH in and become the tool
ssh login.toolforge.org
become <toolname>

# 1. Clone the repo into the tool home ($HOME = /data/project/<toolname>)
git clone <repo-url> $HOME/wikidata

# 2. Build the venv INSIDE a job so it matches the runtime image
toolforge jobs run venv --image python3.11 --wait \
  --command "python3 -m venv ~/venv && ~/venv/bin/pip install -r ~/wikidata/projects/remove_import_ref/requirements.txt"

# 3. pywikibot config in $HOME/.pywikibot/ (see below), then dry-run as a job
toolforge jobs run rmimport --image python3.11 --wait \
  --command "bash $HOME/wikidata/projects/remove_import_ref/toolforge_run.sh"

# 4. Inspect results, then run for real
cat $HOME/rmimport.out                     # stdout (or: toolforge jobs logs rmimport)
cat $HOME/wikidata/projects/remove_import_ref/output/matched.csv
toolforge jobs run rmimport --image python3.11 --wait \
  --command "bash $HOME/wikidata/projects/remove_import_ref/toolforge_run.sh --save"
```

`~/.pywikibot/user-config.py`:

```python
mylang = 'wikidata'
family = 'wikidata'
usernames['wikidata']['wikidata'] = 'DifoolBot'
password_file = 'user-password.py'   # BotPassword; or use OAuth
put_throttle = 1
maxlag = 5
```

`~/.pywikibot/user-password.py` (create a BotPassword at Special:BotPasswords):

```python
('DifoolBot', BotPassword('rmimport', 'the-generated-password'))
```

Notes: reads are anonymous so the dry-run works before auth is set up; `--save`
needs the login above. The launcher sets `PYTHONUNBUFFERED=1` so `~/rmimport.out`
updates live. `done.txt` makes the job resumable if it stops mid-batch.

## Decisions (resolved)

- **Multi-snak references**: never auto-removed. A P143 import ref that carries
  other snaks is logged to `skipped.csv` as `REVIEW_multi_snak_ref` for manual review.
- **Project map**: `project_map.KNOWN` holds only P1800-verified editions
  (en/es/ca/ru/pl); everything else resolves authoritatively via P1800 and is cached.
  Never add a guessed entry.

## EditGroups

Each run generates one batch id (printed as `editgroup=...`) and appends
`([[:toollabs:editgroups/b/CB/<id>|details]])` to every edit summary, so the whole
batch is reviewable/revertable at <https://editgroups.toolforge.org>.

## TODO

- **Unresolved project** (no dbcode found via map or P1800): currently skipped
  silently — add to `skipped.csv` for review in the full run.
- Swap `input/items.txt` for the full list export when ready (still a text file).
