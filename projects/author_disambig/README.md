# author_disambig

Generates a browser **bookmarklet** that pre-ticks a scholar's own papers on the
[author-disambiguator](https://author-disambiguator.toolforge.org/) work-listing
page, using that scholar's public ORCID article list as the source of truth.

Auto-ticks **only on an exact DOI match**; a title lookalike is highlighted but
never ticked, and nothing is submitted until you click the tool's own button.

## Usage

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

## What's in git

Only `generate_helper.py` (the generator) and this README are source. Everything
it produces under `authors/`, plus any top-level input pastes and built
artifacts, is generated/personal working data and is gitignored — regenerate it
from an ORCID iD as above.
