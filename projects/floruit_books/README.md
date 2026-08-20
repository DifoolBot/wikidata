# floruit_books

Migrate the "inline book" floruit shape into a real book item.

## The shape it fixes

Mostly DifoolBot's own house style: a person's **floruit (P1317)** statement carries
qualifiers **title (P1476)** + **subject has role (P2868)**, and is sourced by a
*database* reference that points at the book by a bibliographic identifier.

```
person  P1317 floruit  <year>
          qualifier P1476 title            = "<book title>"
          qualifier P2868 subject has role = author / editor / illustrator / writer
          reference: stated in <database>  +  <bibliographic id>  +  retrieved [+ URL]
```

`migrate_floruit_book.py` turns that reference into a proper item:

```
CREATE Work    (P31 = written work, Q47461344): title, language, P50 author / P98 editor
CREATE Edition (P31 = version/edition, Q3331189): P629 -> Work, title, language,
                 P110 illustrator, and the bibliographic id(s) moved off the reference
EDIT person floruit:
   reference  ->  stated in (P248) = the new Edition        (keeps retrieved P813 + URL P854)
   drop qualifier P1476 (title)     keep qualifier P2868 (subject has role)
```

Publication date / publisher / pages are **not** guessed -- copy those from the
catalogue (archive.org, the DNB edition page, ...) by hand afterwards.

## Scope

Only references carrying one of the five **bibliographic edition** identifiers:

| property | source |
|----------|--------|
| P1292 | DNB edition ID |
| P1025 | SUDOC editions |
| P675  | Google Books ID |
| P648  | Open Library ID |
| P243  | OCLC control number |

Left untouched (a later/other pass): **P244** (that value is the person's *own* LC
name-authority record, not the book), **P268**, existing **P248**, and **URL-only**
sources (archive.org with no structured id). Roles other than author / writer /
editor / illustrator (composer, photographer, cartoonist, ...) are skipped -- those
sources are often music or film items, not books.

Candidates are pulled live from **QLever** (`https://qlever.dev/api/wikidata`).

## Usage

Repo root, with `PYTHONPATH=projects;projects/shared_lib` (via `.env`). Dry run by
default; pass `--save` to actually create items and edit.

```
python projects/floruit_books/migrate_floruit_book.py                  # dry run, all candidates
python projects/floruit_books/migrate_floruit_book.py --limit 5        # dry run, first 5
python projects/floruit_books/migrate_floruit_book.py --qid Q132997957 # dry run, one person
python projects/floruit_books/migrate_floruit_book.py --save           # really create + edit
```

Flags: `--qid QID`, `--file PATH` (one QID per line), `--limit N`, `--editgroup ID`
(override the per-day batch id).

Every run prints `editgroup=<id>`; each create/edit summary links to
<https://editgroups.toolforge.org> so the whole batch can be reviewed or reverted
there. Before creating, `find_existing_edition` looks the identifier up and reuses an
existing item rather than making a duplicate (books shared across people get one
edition). Item creation is irreversible-ish, so it stays behind `--save`.

## Tests

Offline unit tests for the pure helpers (parsing, grouping, spec-building); the
Wikidata-touching parts are exercised by the dry-run.

```
python -m pytest projects/floruit_books/test_migrate_floruit_book.py -v
```

Read model authority: `notes/isbn_bot.md` "Canonical book data model" (WORK/EDITION
split, edition-only properties). All edits go through `shared_lib.change_wikidata`
(User-Agent / maxlag / throttle).
