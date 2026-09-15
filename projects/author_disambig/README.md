# author_disambig

Generates a browser **bookmarklet** that pre-ticks a scholar's own papers on the
[author-disambiguator](https://author-disambiguator.toolforge.org/) work-listing
page, using that scholar's public ORCID article list as the source of truth.

Auto-ticks **only on an exact DOI match**; a title lookalike is highlighted but
never ticked, and nothing is submitted until you click the tool's own button.

## A) Single scholar

```bash
python generate_helper.py <ORCID-iD> "<Author Name>"
# e.g.
python generate_helper.py 0000-0001-6601-5967 "Paschoal Coelho Grossi"
```

This fetches the ORCID works and writes an `authors/<slug>/` folder containing
`orcid_works.json`, `his_dois.txt`, `autocheck.js`, `bookmarklet.txt`, and a
per-author `HELP.md` with install/use instructions. Drop a `scholar_paste.txt`
into that folder to fold Google Scholar titles into the highlight-only fallback,
then re-run.

## B) One common name, many same-name items (Jie Zhang, Yan Lu, ...)

Instead of running (A) once per ORCID, build a **single picker bookmarklet**
covering every same-name candidate at once. Two bookmarklets, one script run:

1. **Collector** (make once): `python generate_helper.py --collector` writes
   `collector_bookmarklet.txt` / `collector.js`. Save it as a bookmark. Run it
   on the `names_oauth.php` candidate page: it reads each candidate's QID (from
   its `[Wikidata]` link), ORCID(s) and description — skipping co-author and
   affiliation links — and copies a `QID<TAB>ORCID<TAB>label<TAB>desc` block to
   the clipboard.
2. **Build the picker**, piping the clipboard straight in and naming the group:
   ```powershell
   Get-Clipboard | python generate_helper.py --name "Jie Zhang"
   ```
   (or `--name "Jie Zhang" --paste-file rows.tsv`). It fetches each ORCID's works
   (cached under `authors/<slug>/orcid_cache/`) and writes `picker.js` /
   `picker_bookmarklet.txt` / `HELP.md`.
3. On the work-listing page, click the picker. A right-hand panel lists every
   person with a `here/total` count (how many of their ORCID DOIs are on this
   page). Click a person → ticks only their DOIs (green), unticks anyone else's
   (yellow), shows their QID to assign the batch, then move to the next person.
   The panel hides people with **0 here** by default (no ORCID, or nothing on
   this page); a "hide 0-here" checkbox toggles them back.

Note: author-disambiguator caps the work list at ~500 (oldest first, mostly
pre-ORCID). A low `here` vs `total` means the rest aren't on the page.

## What's in git

Only `generate_helper.py` (the generator) and this README are source. Everything
it produces under `authors/`, plus any top-level input pastes and built
artifacts, is generated/personal working data and is gitignored — regenerate it
from an ORCID iD as above.
