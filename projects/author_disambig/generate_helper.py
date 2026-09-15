"""Build browser bookmarklets that speed up author-disambiguator work.

Two workflows:

(A) Single scholar (original) -- one ORCID, one auto-tick bookmarklet:
        python generate_helper.py <ORCID-iD> "<Author Name>"
        python generate_helper.py 0000-0001-6601-5967 "Paschoal Coelho Grossi"
    Creates authors/<slug>/ with orcid_works.json, his_dois.txt, autocheck.js,
    bookmarklet.txt, HELP.md. A DOI in his ORCID auto-ticks (green); a title
    lookalike highlights (blue); a pre-ticked row not in ORCID warns (yellow).

(B) One name, MANY same-name items (Jie Zhang, Yan Lu, ...) -- one PICKER
    bookmarklet covering every candidate at once:
        1. On the names_oauth.php candidate page, run the COLLECTOR bookmarklet
           (generate it with:  python generate_helper.py --collector).
           It reads each candidate's QID (from the author_item_oauth.php?id=Q..
           name link), its ORCID(s) and description, and copies a clean
           QID<TAB>ORCID<TAB>label<TAB>description block to the clipboard.
        2. Feed that block in and name the group:
               Get-Clipboard | python generate_helper.py --name "Jie Zhang"
           (or  python generate_helper.py --name "Jie Zhang" --paste-file x.tsv)
           It fetches each ORCID's works (cached) and writes authors/<slug>/
           picker.js + picker_bookmarklet.txt + HELP.md.
        3. On the work-listing page, click the picker bookmarklet. A panel lists
           every person; clicking one ticks exactly that person's ORCID DOIs
           (green), unticks anyone else's (yellow), and shows their QID so you
           assign the batch and move to the next person -- no re-running Python.

Nothing is ever submitted; only the tool's own button does that.
"""

import json
import re
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

HERE = Path(__file__).parent

# Be a polite citizen of the free ORCID public API: pause between successive
# network fetches (cached ORCIDs are skipped, so re-runs stay instant). There is
# no hurry building a picker, so a whole second between calls is fine.
FETCH_DELAY_SEC = 5.0

# ORCID asks API clients to identify via a contactable page, not a personal
# email; the bot's Wikidata user page is that contact point.
USER_AGENT = (
    "author-disambig-helper/1.0 " "(https://www.wikidata.org/wiki/User:DifoolBot)"
)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def fetch_orcid_works(orcid_id: str, dest: Path) -> None:
    url = f"https://pub.orcid.org/v3.0/{orcid_id}/works"
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(req, timeout=60) as resp:
        dest.write_bytes(resp.read())


def norm_doi(s: str) -> str:
    """Canonicalise a DOI for exact matching. ORCID records are user-entered and
    sometimes carry a URL/`doi:` prefix or trailing junk (`10.1149/2.0051604JES]`,
    a stray `)`, `.`, quote, whitespace) - strip all of it. Must stay in sync
    with the JS `nd()` used on the page side."""
    s = (s or "").strip().upper()
    s = re.sub(r"^(HTTPS?://)?(DX\.)?DOI\.ORG/", "", s)  # URL prefix
    s = re.sub(r"^DOI:\s*", "", s)  # doi: prefix
    s = re.sub(r"[\s\].,;:)>'\"]+$", "", s)  # trailing junk
    return s.rstrip("/")


def orcid_dois_and_titles(path: Path) -> tuple[set[str], set[str], int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    dois, titles = set(), set()
    for group in data["group"]:
        for ext in group["external-ids"]["external-id"]:
            if ext["external-id-type"].lower() == "doi":
                doi = norm_doi(ext["external-id-value"])
                if doi:
                    dois.add(doi)
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
        if (
            len(line) > 25
            and not re.fullmatch(r"[\d,*\s]+", line)
            and "," in nxt
            and re.search(r"\b[A-Z]{1,3}\b", nxt)
            and not line[0].islower()
        ):
            titles.add(norm_title(line))
    return titles


def norm_title(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)  # strip HTML tags ORCID sometimes has
    s = s.lower().replace("&amp;", "&")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# --------------------------------------------------------------------------- #
# (A) single-scholar auto-tick bookmarklet (original behaviour)               #
# --------------------------------------------------------------------------- #

JS_TEMPLATE = r"""(function(){
  var DOIS=new Set(__DOIS__);
  var TITLES=new Set(__TITLES__);
  function nt(s){return s.toLowerCase().replace(/&amp;/g,'&').replace(/[^a-z0-9]+/g,' ').trim();}
  function nd(s){return (s||'').toUpperCase().replace(/[\s\].,;:)>'"]+$/,'').replace(/\/+$/,'');}
  var boxes=document.querySelectorAll("input[type=checkbox][name^='papers[']");
  var m=0,p=0,r=0;
  boxes.forEach(function(cb){
    var row=cb.closest('tr'); if(!row) return;
    var a=row.querySelector("a[href*='doi.org/']");
    var doi=a?nd(decodeURIComponent(a.href.split('doi.org/')[1]||'')):null;
    var td=row.querySelector('td'); var title=td?nt(td.innerText):'';
    if(doi&&DOIS.has(doi)){ if(!cb.checked)cb.checked=true; row.style.background='#c8f7c5'; m++; }
    else if(title&&TITLES.has(title)){ row.style.background='#cfe8ff'; p++; }
    else if(cb.checked){ row.style.background='#fff3b0'; r++; }
  });
  var b=document.getElementById('__adhelp'); if(b)b.remove();
  b=document.createElement('div'); b.id='__adhelp';
  b.style.cssText='position:fixed;top:0;left:0;right:0;z-index:99999;background:#222;color:#fff;font:14px sans-serif;padding:8px 12px;text-align:center';
  b.innerHTML='Author-disambiguator helper (__NAME__) &mdash; found '+boxes.length+' papers. '+
    '<b style="color:#8f8">&#10004; '+m+' ORCID-confirmed (ticked)</b> &nbsp; '+
    '<b style="color:#9cf">? '+p+' title lookalike (review)</b> &nbsp; '+
    '<b style="color:#fd6">&#9888; '+r+' pre-ticked, not in ORCID (review)</b> '+
    '&nbsp; <span style="cursor:pointer;text-decoration:underline" onclick="this.parentNode.remove()">dismiss</span>';
  document.body.appendChild(b);
})();"""


def build_single(name: str, outdir: Path) -> None:
    dois, orcid_titles, n_groups = orcid_dois_and_titles(outdir / "orcid_works.json")
    titles = orcid_titles | scholar_titles(outdir / "scholar_paste.txt")
    titles.discard("")

    (outdir / "his_dois.txt").write_text(
        "\n".join(sorted(dois)) + "\n", encoding="utf-8"
    )

    js = (
        JS_TEMPLATE.replace("__DOIS__", json.dumps(sorted(dois)))
        .replace("__TITLES__", json.dumps(sorted(titles)))
        .replace("__NAME__", name.replace("'", "\\'"))
    )
    (outdir / "autocheck.js").write_text(js, encoding="utf-8")

    bookmarklet = "javascript:" + re.sub(r"\n\s*", "", js)
    (outdir / "bookmarklet.txt").write_text(bookmarklet, encoding="utf-8")

    (outdir / "HELP.md").write_text(
        help_text(name, len(dois), n_groups), encoding="utf-8"
    )

    print(
        f"{name}: {n_groups} ORCID works, {len(dois)} with DOI, "
        f"{len(titles)} titles; bookmarklet {len(bookmarklet)} chars"
    )
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


# --------------------------------------------------------------------------- #
# (B1) collector bookmarklet -- scrape QID+ORCID+desc off the candidate page  #
# --------------------------------------------------------------------------- #

JS_COLLECTOR = r"""(function(){
  var out=[],seen={};
  /* Key off the "[Wikidata]" link (link text is literally 'Wikidata'): only
     candidate author items have one. Co-author name links go to
     author_item_oauth.php too but have no [Wikidata] link; affiliation links
     go to wikidata.org but their text is the institution label, not Wikidata. */
  document.querySelectorAll("a[href*='wikidata.org/wiki/Q']").forEach(function(w){
    if((w.textContent||'').trim()!=='Wikidata') return;
    var wm=w.href.match(/wiki\/(Q\d+)/); if(!wm) return;
    var qid=wm[1]; if(seen[qid]) return;
    var td=w.closest('td'), tr=w.closest('tr'); if(!td||!tr) return;
    var nameA=td.querySelector("a[href*='author_item_oauth.php?id=Q']");
    var name=nameA?(nameA.textContent||'').trim():'';
    var descTd=td.nextElementSibling;
    var desc=descTd?descTd.innerText.trim().replace(/\s+/g,' '):'';
    var orcids=[];
    tr.querySelectorAll("a[href*='orcid.org/']").forEach(function(o){
      var mm=o.href.match(/(\d{4}-\d{4}-\d{4}-\d{3}[\dX])/);
      if(mm&&orcids.indexOf(mm[1])<0) orcids.push(mm[1]);
    });
    seen[qid]=1;
    if(orcids.length===0) out.push([qid,'',name,desc].join('\t'));
    else orcids.forEach(function(o){ out.push([qid,o,name,desc].join('\t')); });
  });
  var text=out.join('\n');
  var old=document.getElementById('__adcollect'); if(old)old.remove();
  var box=document.createElement('div'); box.id='__adcollect';
  box.style.cssText='position:fixed;top:0;left:0;right:0;z-index:99999;background:#111;color:#fff;font:13px sans-serif;padding:8px 12px';
  var n=out.length, withid=out.filter(function(l){return l.split('\t')[1];}).length;
  box.innerHTML='<b>Collected '+n+' candidate rows ('+withid+' with an ORCID).</b> '+
    'Copied to clipboard as QID&#8594;ORCID&#8594;name&#8594;desc. '+
    'Run: <code>Get-Clipboard | python generate_helper.py --name "..."</code> '+
    '<span style="cursor:pointer;text-decoration:underline;float:right" onclick="this.parentNode.remove()">dismiss</span>';
  var ta=document.createElement('textarea');
  ta.value=text; ta.style.cssText='width:100%;height:120px;margin-top:6px;font:12px monospace';
  box.appendChild(ta); document.body.appendChild(box);
  ta.select();
  try{ navigator.clipboard.writeText(text); }catch(e){ try{document.execCommand('copy');}catch(e2){} }
})();"""


def write_collector() -> None:
    (HERE / "collector.js").write_text(JS_COLLECTOR, encoding="utf-8")
    bm = "javascript:" + re.sub(r"\n\s*", "", JS_COLLECTOR)
    (HERE / "collector_bookmarklet.txt").write_text(bm, encoding="utf-8")
    print(f"Collector written ({len(bm)} chars):")
    print(f"  {HERE / 'collector_bookmarklet.txt'}   (save as a bookmark, once)")
    print(f"  {HERE / 'collector.js'}                (or paste into F12 console)")
    print("Run it on the names_oauth.php candidate page, then:")
    print('  Get-Clipboard | python generate_helper.py --name "<the name>"')


# --------------------------------------------------------------------------- #
# (B2) picker bookmarklet -- one name, all same-name people at once           #
# --------------------------------------------------------------------------- #

JS_PICKER = r"""(function(){
  var PEOPLE=__PEOPLE__;
  var NAME=__NAME__;
  function nd(s){return (s||'').toUpperCase().replace(/^(https?:\/\/)?(dx\.)?doi\.org\//i,'').replace(/^doi:\s*/i,'').replace(/[\s\].,;:)>'"]+$/,'').replace(/\/+$/,'');}
  var boxes=[].slice.call(document.querySelectorAll("input[type=checkbox][name^='papers[']"));
  var rows=boxes.map(function(cb){
    var row=cb.closest('tr');
    var a=row?row.querySelector("a[href*='doi.org/']"):null;
    var doi=a?nd(decodeURIComponent(a.href.split('doi.org/')[1]||'')):'';
    return {cb:cb,row:row,doi:doi};
  });
  var pageDois={}; rows.forEach(function(r){ if(r.doi) pageDois[r.doi]=1; });
  PEOPLE.forEach(function(p){
    p._set={}; p._here=0;
    p.dois.forEach(function(d){ d=nd(d); p._set[d]=1; if(pageDois[d]) p._here++; });
  });
  function status(html){ var s=document.getElementById('__adpick_status'); if(s)s.innerHTML=html; }
  function apply(idx){
    var p=PEOPLE[idx], m=0, other=0;
    rows.forEach(function(r){
      if(r.doi && p._set[r.doi]){ r.cb.checked=true; if(r.row)r.row.style.background='#c8f7c5'; m++; }
      else { if(r.cb.checked){ r.cb.checked=false; if(r.row)r.row.style.background='#fff3b0'; other++; } else if(r.row) r.row.style.background=''; }
    });
    [].forEach.call(document.querySelectorAll('.__adperson'),function(el,i){
      el.style.background=(i===idx)?'#375a7f':'transparent'; });
    status('<b>'+p.label+'</b> ('+p.q+') &mdash; ticked <b style="color:#8f8">'+m+'</b>'+
      ' of '+p.dois.length+' ORCID DOIs. '+
      (other?('<b style="color:#fd6">unticked '+other+' not-his</b>. '):'')+
      'Assign the ticked papers to <b>'+p.q+'</b>, then pick the next person.');
  }
  function clearAll(){ rows.forEach(function(r){ r.cb.checked=false; if(r.row)r.row.style.background=''; });
    [].forEach.call(document.querySelectorAll('.__adperson'),function(el){el.style.background='transparent';});
    status('All ticks cleared.'); }
  var old=document.getElementById('__adpick'); if(old)old.remove();
  var box=document.createElement('div'); box.id='__adpick';
  box.style.cssText='position:fixed;top:0;right:0;bottom:0;width:360px;z-index:99999;background:#222;color:#eee;font:13px sans-serif;padding:8px;overflow:auto;box-shadow:-2px 0 8px rgba(0,0,0,.4)';
  var nHere=PEOPLE.filter(function(p){return p._here>0;}).length;
  var h='<div style="display:flex;justify-content:space-between;align-items:center">'+
    '<b>'+NAME+' &mdash; '+PEOPLE.length+' people</b>'+
    '<span style="cursor:pointer;text-decoration:underline" onclick="document.getElementById(\'__adpick\').remove()">close</span></div>'+
    '<div style="font-size:12px;color:#aaa;margin:4px 0">'+rows.length+' papers on this page. Click a person to tick only their ORCID DOIs.</div>'+
    '<div id="__adpick_status" style="background:#111;padding:6px;border-radius:4px;min-height:34px;margin-bottom:6px">Pick a person.</div>'+
    '<div style="margin-bottom:6px;display:flex;justify-content:space-between;align-items:center">'+
      '<label style="font-size:12px;cursor:pointer"><input type="checkbox" id="__adhide" checked> hide 0-here (<span id="__adcount"></span>)</label>'+
      '<button id="__adclear" style="cursor:pointer">Clear all ticks</button></div>'+
    '<div id="__adpeople"></div>';
  box.innerHTML=h;
  var list=box.querySelector('#__adpeople');
  PEOPLE.forEach(function(p,i){
    var d=document.createElement('div'); d.className='__adperson';
    d.setAttribute('data-here', p._here);
    d.style.cssText='cursor:pointer;padding:6px;border-bottom:1px solid #444;border-radius:4px';
    var badge=p._here?('<b style="color:#8f8">'+p._here+'</b>'):'<span style="color:#f88">0</span>';
    d.innerHTML='<div>'+badge+'/'+p.dois.length+' here &middot; <b>'+p.q+'</b></div>'+
      '<div style="font-size:12px;color:#cde">'+(p.label||'')+'</div>'+
      '<div style="font-size:11px;color:#9ab">'+(p.desc||'')+'</div>'+
      '<div style="font-size:11px;color:#789">'+(p.o||'no ORCID')+'</div>';
    d.onclick=function(){ apply(i); };
    list.appendChild(d);
  });
  function filter(){
    var hide=document.getElementById('__adhide').checked;
    [].forEach.call(document.querySelectorAll('.__adperson'),function(el){
      el.hidden = hide && el.getAttribute('data-here')==='0';
    });
    document.getElementById('__adcount').textContent =
      hide ? (nHere+' with papers here') : (PEOPLE.length+' total');
  }
  document.body.appendChild(box);
  document.getElementById('__adhide').onchange=filter;
  document.getElementById('__adclear').onclick=clearAll;
  filter();
  if(rows.length===0) status('<b style="color:#fd6">0 papers found</b> &mdash; open the work-listing step first.');
})();"""


def parse_paste(text: str) -> list[dict]:
    """Parse the collector's QID<TAB>ORCID<TAB>label<TAB>desc block.

    Also tolerant of hand-made lines: any line containing a Q-id and an ORCID
    in any order, tab- or multi-space-separated.
    """
    people: dict[str, dict] = {}
    order: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        qid = orcid = label = desc = ""
        if len(parts) >= 2 and re.fullmatch(r"Q\d+", parts[0].strip()):
            qid = parts[0].strip()
            orcid = parts[1].strip()
            label = parts[2].strip() if len(parts) > 2 else ""
            desc = parts[3].strip() if len(parts) > 3 else ""
        else:  # loose fallback
            qm = re.search(r"\bQ\d+\b", line)
            om = re.search(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", line)
            if not qm:
                continue
            qid = qm.group(0)
            orcid = om.group(0) if om else ""
        key = qid + "|" + orcid
        if key not in people:
            people[key] = {"q": qid, "o": orcid, "label": label, "desc": desc}
            order.append(key)
    return [people[k] for k in order]


def cached_orcid_dois(
    orcid: str, cache_dir: Path, pace: bool = False
) -> tuple[list[str], bool]:
    """Return (sorted DOIs, did_network_fetch). Cache hits never touch the
    network. When `pace` is set, wait FETCH_DELAY_SEC before a fetch, so callers
    can space out a long run of misses without a trailing pause."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / f"{orcid}.json"
    fetched = False
    if not dest.exists():
        if pace:
            time.sleep(FETCH_DELAY_SEC)
        print(f"  fetching ORCID {orcid} ...")
        fetch_orcid_works(orcid, dest)
        fetched = True
    dois, _titles, _n = orcid_dois_and_titles(dest)
    return sorted(dois), fetched


def build_picker(name: str, people: list[dict], outdir: Path) -> None:
    enriched = []
    fetched_before = False  # pace only between real network calls, not cache hits
    for p in people:
        if p["o"]:
            dois, fetched = cached_orcid_dois(
                p["o"], outdir / "orcid_cache", pace=fetched_before
            )
            fetched_before = fetched_before or fetched
        else:
            dois = []
        enriched.append(
            {
                "q": p["q"],
                "o": p["o"],
                "label": p["label"],
                "desc": p["desc"],
                "dois": dois,
            }
        )
    # heaviest first: put the people with the most works at the top of the panel
    enriched.sort(key=lambda x: len(x["dois"]), reverse=True)

    (outdir / "people.tsv").write_text(
        "\n".join("\t".join([p["q"], p["o"], p["label"], p["desc"]]) for p in people)
        + "\n",
        encoding="utf-8",
    )

    js = JS_PICKER.replace(
        "__PEOPLE__", json.dumps(enriched, ensure_ascii=False)
    ).replace("__NAME__", json.dumps(name, ensure_ascii=False))
    (outdir / "picker.js").write_text(js, encoding="utf-8")
    bm = "javascript:" + re.sub(r"\n\s*", "", js)
    (outdir / "picker_bookmarklet.txt").write_text(bm, encoding="utf-8")
    (outdir / "HELP.md").write_text(picker_help(name, enriched), encoding="utf-8")

    total = sum(len(p["dois"]) for p in enriched)
    noid = sum(1 for p in enriched if not p["o"])
    print(
        f"\n{name}: {len(enriched)} people, {total} ORCID DOIs total"
        + (f" ({noid} people have no ORCID)" if noid else "")
    )
    for p in enriched:
        print(
            f"  {p['q']:<11} {p['o'] or '(no orcid)':<19} "
            f"{len(p['dois']):>4} DOIs  {p['label']} - {p['desc'][:40]}"
        )
    print(f"picker bookmarklet {len(bm)} chars -> {outdir / 'picker_bookmarklet.txt'}")


def picker_help(name: str, people: list[dict]) -> str:
    rows = "\n".join(
        f"- **{p['q']}** {p['o'] or '(no orcid)'} - {len(p['dois'])} DOIs - "
        f"{p['label']} ({p['desc']})"
        for p in people
    )
    return f"""# Author-disambiguator PICKER - {name}

One bookmarklet for all {len(people)} same-name candidates. On the work-listing
page it shows a panel; click a person to tick exactly that person's ORCID DOIs.

## Install (once)
1. Bookmark manager (Ctrl+Shift+O), new bookmark `AD pick {name.split()[0]}`.
2. Paste all of **picker_bookmarklet.txt** into the URL field. Save.
   (Console fallback: F12 -> paste **picker.js** -> Enter.)

## Use
1. Open the work list (names_oauth.php - the page with the Match? checkboxes).
2. Click the bookmark. A panel appears on the right listing each person with
   `here/total` = how many of their ORCID DOIs are on this page. By default the
   panel hides everyone with **0 here** (no ORCID, or none of their works on this
   page); untick "hide 0-here" to see all {len(people)}.
3. Click a person:
   - green rows = their ORCID DOI -> ticked
   - yellow rows = were ticked but are NOT theirs -> unticked for you
4. Assign the ticked papers to that person's **QID** (shown in the panel) using
   the tool's own control, then click the next person. Re-click the bookmark
   after any "next page" load.

Note: author-disambiguator lists at most ~500 works (oldest first, mostly
pre-ORCID). If a person's `here` count is far below `total`, the rest are not on
this page - finish them another way.

## People
{rows}

Regenerate:  Get-Clipboard | python generate_helper.py --name "{name}"
"""


# --------------------------------------------------------------------------- #


def usage() -> None:
    sys.exit(
        "usage:\n"
        '  python generate_helper.py <ORCID-iD> "<Author Name>"   (single scholar)\n'
        "  python generate_helper.py --collector                  (write collector bookmarklet)\n"
        '  Get-Clipboard | python generate_helper.py --name "<Name>"   (multi-person picker)\n'
        '  python generate_helper.py --name "<Name>" --paste-file <file.tsv>'
    )


def main(argv: list[str]) -> None:
    if len(argv) >= 2 and argv[1] == "--collector":
        write_collector()
        return

    if len(argv) >= 3 and argv[1] == "--name":
        name = argv[2]
        text = ""
        if "--paste-file" in argv:
            pf = Path(argv[argv.index("--paste-file") + 1])
            text = pf.read_text(encoding="utf-8")
        elif not sys.stdin.isatty():
            text = sys.stdin.read()
        if not text.strip():
            sys.exit(
                "No paste supplied. Pipe the collector output in, e.g.:\n"
                f'  Get-Clipboard | python generate_helper.py --name "{name}"'
            )
        people = parse_paste(text)
        if not people:
            sys.exit("Could not parse any QID/ORCID rows from the paste.")
        outdir = HERE / "authors" / slugify(name)
        outdir.mkdir(parents=True, exist_ok=True)
        build_picker(name, people, outdir)
        return

    if len(argv) == 3:  # legacy single-scholar path
        orcid_id, name = argv[1], argv[2]
        outdir = HERE / "authors" / slugify(name)
        outdir.mkdir(parents=True, exist_ok=True)
        print(f"Fetching ORCID {orcid_id} ...")
        fetch_orcid_works(orcid_id, outdir / "orcid_works.json")
        build_single(name, outdir)
        return

    usage()


if __name__ == "__main__":
    main(sys.argv)
