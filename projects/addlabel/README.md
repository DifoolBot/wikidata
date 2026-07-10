# addlabel

Adds missing labels, sex-or-gender and birth/death dates to Wikidata person
items, based on the authority-control records already linked from the item
(Library of Congress, BnF, IdRef, GND). Ported from the standalone
`D:\python\viaf` scripts (`call_addlabel.py` + `addlabel.py`).

For each candidate item the bot:

1. retrieves every linked LoC/BnF/IdRef/GND record (`*_page.py`),
2. merges them in the `Collector`: agreed sex value, most precise
   non-conflicting birth/death dates, candidate labels per language, and the
   person's countries/languages,
3. skips label changes when the person's locale suggests a non-latin script
   (Hebrew, Cyrillic, other) or an eastern/ambiguous name order,
4. queues edits through `shared_lib.change_wikidata` with a `stated in`
   reference to the record the value came from, and
5. tracks done/error/progress state in the Firebird database
   (`data/addlabel.json` points at `addlabel.fdb`).

## Usage

Run from the repo root (where `user-config.py` lives), with `projects` on the
path:

```
python -m addlabel.call_addlabel loop            # retry + todo, forever
python -m addlabel.call_addlabel retry           # only errors flagged for retry
python -m addlabel.call_addlabel todo            # only the QTODO queue
python -m addlabel.call_addlabel scan loc        # WDQS-scan one source (loc/bnf/idref/gnd)
python -m addlabel.call_addlabel item Q42        # dry-run a single item
python -m addlabel.call_addlabel item Q42 --live # actually edit
```

## Layout

| module | contents |
|---|---|
| `call_addlabel.py` | CLI entry point |
| `addlabel_bot.py` | `AddLabelBot`, `ReportBackend`/`NullReport`, source registry |
| `firebird_addlabel_reporting.py` | Firebird `ReportBackend` |
| `collector.py` | `Collector` + date merging helpers |
| `authority_page.py` | `AuthorityPage` base class |
| `loc_page.py`, `bnf_page.py`, `idref_page.py`, `gnd_page.py` | per-source record retrieval |
| `wikidata_page.py` | locale fallback from the item itself |
| `person_name.py` | `PersonName` parsing/rendering, name-order constants |
| `languages.py`, `countries.py` | locale lookups (QID → codes, scripts, name order) |
| `script_utils.py` | GlotScript-based script detection |
| `http_client.py`, `wdqs_client.py` | shared fetch helpers |
| `data/` | gitignored: db config, lookup caches, `idref_ignore.json` |

`data/` was seeded from the old project: `languages.json`, `scripts.json`,
`countries.json` (lookup caches; rebuilt via WDQS when deleted),
`idref_ignore.json` (IdRef records with known-bad data) and `addlabel.json`
(Firebird connection; `DB_USER`/`DB_PASSWORD` may move to the repo-root `.env`
as `WD_DB_USER`/`WD_DB_PASSWORD`).

The Firebird schema (tables `QERROR`, `QTODO`, `PDONE`, procedures `GET_DONE`,
`add_error`, `add_done`, `add_non_latin`, `add_pdone`) has no create script in
`schemas/` yet; the bot assumes the existing `addlabel.fdb`.

## Changes relative to the old code

Dropped, now provided by `shared_lib`:

- **`interface_statedin.IStatedIn` / `impl_statedin`** — the old code injected
  this (large) interface into its private copy of `change_wikidata.WikiDataPage`.
  The shared `WikiDataPage` no longer takes a `stated_in` collaborator (its two
  remaining uses are dead code), so the interface and its 1,600-line
  implementation disappear from this project entirely.
- **`authsource.py`** (~400 lines of VIAF id-matching logic) — the bot only
  ever used `auth_src.pid`. Replaced by the tiny `LabelSource(pid,
  label_language)` dataclass and the `SOURCES` registry.
- **`GenericReference`** → `cwd.StateInReference`; the ad-hoc reference dicts
  (`{"id_pid":…, "stated in":…, "id":…}`) became `AuthorityPage.create_reference()`
  plus typed `SexFinding`/`DateFinding` results.
- **`AddLabelBot.has_strong_source`/`is_weak_source`** → `cwd.has_strong_source`
  (identical VIAF-aware logic already lives in `shared_lib.change_wikidata`).
- local `database_handler.py` → `shared_lib.database_handler_firebird`,
  local `rate_limiter.py` → `shared_lib.rate_limiter`,
  local PID/QID constants → `shared_lib.constants`,
  site boilerplate → `shared_lib.wikidata_site`.

Dead code not ported: `FileReport` (superseded by the db backend; `NullReport`
covers test runs), `resolve_redirect_notfound`/`set_redirect`/`set_not_found`
(unreachable — guarded by an unconditional `raise`), `show_utf8_encoding`,
`BnfPage.run_old`, and the commented-out reporting strategy in the old
`call_addlabel.py`.

Bugs found during the port:

- `report.add_birth_death(...)` was called on suspicious lifespans but existed
  in **no** report implementation → `AttributeError` at runtime. It is now a
  `ReportBackend` method with a default implementation that prints; wire it to
  the database when wanted.
- The old `work()`/`test()`/`redirect()` helpers constructed
  `AddLabelBot(auth_src, "en")` without the required `stated_in`/`report`
  arguments → `TypeError` if ever called. Replaced by `call_addlabel item`.
- With `force_name_order` set, `Collector.name_orders` was never populated but
  `can_change_labels()` reads it → `AttributeError`. Now always collected.
- `test_name.py` defined `test_parentheses1` twice; the shadowed first test
  encodes behavior the code does not have (it raises). Pinned down in
  `test_person_name.py`.
- The future-date guard was hardcoded (`year > 2025`); now
  `date.today().year`.

Renames: `Name` → `PersonName` (`name.py` → `person_name.py`,
`extract_names` → `parse_authority_name`, `removeSuffix` → `remove_suffix`),
`AuthPage` → `AuthorityPage` (`authdata.py` split into `authority_page.py` +
`collector.py`; `stated_in` → `stated_in_qid`, `init_external_id` →
`initial_external_id`, `get_ref` → `create_reference`, `or_none_logic` →
`tri_state_or`, `get_name_order` → `determine_name_order`), `gnd2.py` →
`gnd_page.py`, `scriptutils` → `script_utils`, `IReport` → `ReportBackend`,
`iterate`/`iterate_index` → `scan`/`scan_slice`, and the
`DID_READ`/`DID_WRITE` strings → the `ExamineResult` enum. The repeated
requests/ConnectionError boilerplate of the four sources was factored into
`http_client.http_get`.
