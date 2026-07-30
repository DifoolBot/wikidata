"""Build a browser bookmarklet that pre-ticks a scholar's own papers on the
author-disambiguator work-listing page, using his ORCID article list as truth.

Usage:
    python generate_helper.py <ORCID-iD> "<Author Name>"
    python generate_helper.py 0000-0001-6601-5967 "Paschoal Coelho Grossi"

For each author it creates  authors/<slug>/  containing:
    orcid_works.json  fetched from the ORCID public API
    his_dois.txt      his DOIs (uppercased) - the exact match key
    autocheck.js      readable source of the bookmarklet logic
    bookmarklet.txt   one-line javascript: URL to save as a bookmark
    HELP.md           how to install and use it
If a scholar_paste.txt is dropped into that folder, its titles are folded into
the soft (highlight-only) fallback for papers that have no DOI.

Matching on the page (see names_oauth.php source):
  checkbox  <input type=checkbox name='papers[QID:claim]'>
  DOI       DOI: <a href='https://doi.org/<doi>'>...
Auto-tick happens ONLY on an exact DOI match. A title lookalike is highlighted
but never auto-ticked. Nothing is submitted until the user clicks the tool's
own button.
"""

import json
import re
import sys
from pathlib import Path
from urllib.request import Request, urlopen

HERE = Path(__file__).parent

# ORCID asks API clients to identify via a contactable page, not a personal
# email; the bot's Wikidata user page is that contact point.
USER_AGENT = (
    "author-disambig-helper/1.0 "
    "(https://www.wikidata.org/wiki/User:DifoolBot)"
)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def fetch_orcid_works(orcid_id: str, dest: Path) -> None:
    url = f"https://pub.orcid.org/v3.0/{orcid_id}/works"
    req = Request(url, headers={"User-Agent": USER_AGENT,
                                "Accept": "application/json"})
    with urlopen(req, timeout=60) as resp:
        dest.write_bytes(resp.read())


def orcid_dois_and_titles(path: Path) -> tuple[set[str], set[str], int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    dois, titles = set(), set()
    for group in data["group"]:
        for ext in group["external-ids"]["external-id"]:
            if ext["external-id-type"].lower() == "doi":
                dois.add(ext["external-id-value"].strip().upper().rstrip("/"))
                break
        title = group["work-summary"][0]["title"]["title"]["value"]
        titles.add(norm_title(title))
    return dois, titles, len(data["group"])


def scholar_titles(path: Path) -> set[str]:
    """Conservative title pull from a Google Scholar copy-paste (fallback
    highlight only, so false matches only ever highlight, never tick)."""
    if not path.exists():
        return set()
    lines = [ln.rstrip() for ln in path.read_text(encoding="utf-8").splitlines()]
    lines = [ln for ln in lines if ln and not ln.lstrip().startswith("#")]
    titles = set()
    for i in range(len(lines) - 1):
        line, nxt = lines[i], lines[i + 1]
        if (len(line) > 25 and not re.fullmatch(r"[\d,*\s]+", line)
                and "," in nxt and re.search(r"\b[A-Z]{1,3}\b", nxt)
                and not line[0].islower()):
            titles.add(norm_title(line))
    return titles


def norm_title(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)          # strip HTML tags ORCID sometimes has
    s = s.lower().replace("&amp;", "&")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


JS_TEMPLATE = r"""(function(){
  var DOIS=new Set(__DOIS__);
  var TITLES=new Set(__TITLES__);
  function nt(s){return s.toLowerCase().replace(/&amp;/g,'&').replace(/[^a-z0-9]+/g,' ').trim();}
  var boxes=document.querySelectorAll("input[type=checkbox][name^='papers[']");
  var m=0,p=0,r=0;
  boxes.forEach(function(cb){
    var row=cb.closest('tr'); if(!row) return;
    var a=row.querySelector("a[href*='doi.org/']");
    var doi=a?decodeURIComponent(a.href.split('doi.org/')[1]||'').toUpperCase().replace(/\/+$/,''):null;
    var td=row.querySelector('td'); var title=td?nt(td.innerText):'';
    if(doi&&DOIS.has(doi)){ if(!cb.checked)cb.checked=true; row.style.background='#c8f7c5'; m++; }
    else if(title&&TITLES.has(title)){ row.style.background='#cfe8ff'; p++; }
    else if(cb.checked){ row.style.background='#fff3b0'; r++; }
  });
  var b=document.getElementById('__adhelp'); if(b)b.remove();
  b=document.createElement('div'); b.id='__adhelp';
  b.style.cssText='position:fixed;top:0;left:0;right:0;z-index:99999;background:#222;color:#fff;font:14px sans-serif;padding:8px 12px;text-align:center';
  b.innerHTML='Author-disambiguator helper (__NAME__) &mdash; found '+boxes.length+' papers. '+
    '<b style="color:#8f8">✔ '+m+' ORCID-confirmed (ticked)</b> &nbsp; '+
    '<b style="color:#9cf">? '+p+' title lookalike (review)</b> &nbsp; '+
    '<b style="color:#fd6">⚠ '+r+' pre-ticked, not in ORCID (review)</b> '+
    '&nbsp; <span style="cursor:pointer;text-decoration:underline" onclick="this.parentNode.remove()">dismiss</span>';
  document.body.appendChild(b);
})();"""


def build(name: str, outdir: Path) -> None:
    dois, orcid_titles, n_groups = orcid_dois_and_titles(outdir / "orcid_works.json")
    titles = orcid_titles | scholar_titles(outdir / "scholar_paste.txt")
    titles.discard("")

    (outdir / "his_dois.txt").write_text(
        "\n".join(sorted(dois)) + "\n", encoding="utf-8")

    js = (JS_TEMPLATE
          .replace("__DOIS__", json.dumps(sorted(dois)))
          .replace("__TITLES__", json.dumps(sorted(titles)))
          .replace("__NAME__", name.replace("'", "\\'")))
    (outdir / "autocheck.js").write_text(js, encoding="utf-8")

    bookmarklet = "javascript:" + re.sub(r"\n\s*", "", js)
    (outdir / "bookmarklet.txt").write_text(bookmarklet, encoding="utf-8")

    (outdir / "HELP.md").write_text(help_text(name, len(dois), n_groups),
                                    encoding="utf-8")

    print(f"{name}: {n_groups} ORCID works, {len(dois)} with DOI, "
          f"{len(titles)} titles; bookmarklet {len(bookmarklet)} chars")
    print(f"  -> {outdir}")


def help_text(name: str, n_dois: int, n_groups: int) -> str:
    return f"""# Author-disambiguator auto-tick helper - {name}

Pre-ticks {name}'s own papers on the tool's work-listing page, using his ORCID
list ({n_dois} of {n_groups} works carry a DOI) as the source of truth.

## Install (once)
1. Open your browser's **Bookmark Manager** (Ctrl+Shift+O in Chrome/Edge).
2. Add a new bookmark, name it e.g. `AD auto-tick {name.split()[0]}`.
3. Paste the entire contents of **bookmarklet.txt** into the URL field. Save.
   (It is long - use the bookmark manager, not the address bar.)

   Fallback if the bookmark will not save: on the work-listing page press F12,
   open the Console, paste the whole contents of **autocheck.js**, press Enter.
   (Chrome may ask you to type `allow pasting` the first time.)

## Use
1. Log in to author-disambiguator and open the work list for his name
   (names_oauth.php - the page with the Match? checkboxes).
2. Click the bookmark. A bar appears at the top with counts:
   - green rows  = exact DOI match to his ORCID -> ticked for you
   - blue rows   = title looks like his but no DOI match -> you decide
   - yellow rows = the tool pre-ticked it but it is NOT in his ORCID -> review
3. Review the blue/yellow rows, adjust ticks, then click the tool's own submit
   button. Re-click the bookmark after each page / "next" load.

If the bar says "found 0 papers", you are not on the work-listing step yet.

Regenerate:  python generate_helper.py <ORCID-iD> "{name}"
"""


def main(argv: list[str]) -> None:
    if len(argv) != 3:
        sys.exit('usage: python generate_helper.py <ORCID-iD> "<Author Name>"')
    orcid_id, name = argv[1], argv[2]
    outdir = HERE / "authors" / slugify(name)
    outdir.mkdir(parents=True, exist_ok=True)
    print(f"Fetching ORCID {orcid_id} ...")
    fetch_orcid_works(orcid_id, outdir / "orcid_works.json")
    build(name, outdir)


if __name__ == "__main__":
    main(sys.argv)
