# floruit_books

Migrate the "inline book" floruit shape into a real book item, filling the edition
from catalogue metadata you paste.

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

For each such statement the tool:

1. prints the **source link(s)** (DNB edition / Open Library / Google Books / WorldCat /
   SUDOC, plus any archive.org URL on the reference) so you can open the title page;
2. runs the shared **make_book paste flow** (`shared_lib.book_paste`): you paste the
   Google Books / DNB / archive.org metadata, seeded with the floruit's title and
   language and with the person already credited in their role, and confirm
   publisher / date / ISBN / pages / ...;
3. creates a **Work** (P31 = written work) + **Edition** (P31 = version/edition,
   P629 → work) carrying the pasted facts and the bibliographic id **moved off the
   reference**, and links them (P747);
4. rewrites the floruit reference to **stated in (P248) → the new edition** (keeping
   retrieved P813 and any URL P854), drops the **P1476 title** qualifier and keeps the
   **P2868 subject has role** qualifier.

The paste/confirm/build core is shared with `isbn_cleanup/make_book.py` — this tool is
that same flow, seeded from the floruit and followed by the reference rewrite.

## Scope

References carrying one of the five **bibliographic edition** identifiers:

| property | source | link |
|----------|--------|------|
| P1292 | DNB edition ID | d-nb.info |
| P1025 | SUDOC editions | sudoc.fr |
| P675  | Google Books ID | books.google.com |
| P648  | Open Library ID | openlibrary.org |
| P243  | OCLC control number | worldcat.org |

Left untouched (handle with `--edition`, below): **P244** (that value is the person's
*own* LC name-authority record, not the book), **P268**, generic **stated in
<database>** references with no specific id (e.g. a bare "stated in Archive.org"), and
**URL-only** sources (incl. archive.org — QLever can't filter the `P854` URL relation
efficiently, so it isn't a candidate trigger). Roles other than author / writer /
editor / illustrator are skipped.

Candidates are pulled live from **QLever** (`https://qlever.dev/api/wikidata`).

## Usage

Repo root, with `PYTHONPATH=projects;projects/shared_lib` (via `.env`).

**Dry run (no `--save`)** just lists the pending candidates and their source links:

```
python projects/floruit_books/migrate_floruit_book.py            # the whole queue
python projects/floruit_books/migrate_floruit_book.py --limit 5  # first five
```

**`--save`** runs the interactive paste-and-create, one candidate at a time, then
rewrites the floruit reference:

```
python projects/floruit_books/migrate_floruit_book.py --qid Q132997957 --save
python projects/floruit_books/migrate_floruit_book.py --limit 5 --save
```

Flags: `--qid QID`, `--file PATH` (one QID per line), `--limit N`, `--editgroup ID`.

**`--edition QID`** points the given `--qid`/`--file` person(s) at an **existing** edition
you already have, for a floruit whose source can't be auto-identified (e.g. a bare
"stated in Archive.org") or a book **co-written / shared across several people**. It
finds the floruit statement by its title+role qualifiers (no QLever), sets the reference
to `stated in (P248) → QID` and drops the title qualifier; it creates nothing. If a
person has several floruit-book statements (multiple books), it picks the one whose
title qualifier matches the edition's title.

Co-authored book workflow: create the edition once with `make_book` (enter every
author's QID), then point all the co-authors at it with `--file` + `--edition`.

```
python projects/floruit_books/migrate_floruit_book.py --qid Q120481942 --edition Q123 --save
python projects/floruit_books/migrate_floruit_book.py --file robinsons.txt --edition Q123 --save
```

The written `output/candidates.txt` (QID is the first token of each line) is itself
valid input to `--file`.

Every run prints `editgroup=<id>`; each create/edit summary links to
<https://editgroups.toolforge.org> so the whole batch can be reviewed or reverted.
Before creating, `find_existing_edition` looks the identifier up and reuses an existing
item rather than making a duplicate (books shared across people get one edition).

## Tests

```
python -m pytest projects/floruit_books/test_migrate_floruit_book.py -v
python -m pytest projects/shared_lib/test_book_paste.py -v
```

Read model authority: `notes/isbn_bot.md` "Canonical book data model" (WORK/EDITION
split, edition-only properties). All edits go through `shared_lib.change_wikidata`
(User-Agent / maxlag / throttle).
