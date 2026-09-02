#!/usr/bin/env python3
"""gen_book_txt.py -- build a make_book.py paste file from an archive.org item and/or
Open Library IDs, so you never hand-type (or badly paste) the same metadata twice.

Give it any one of: an archive.org identifier, an Open Library edition (OL...M) or work
(OL...W) id, or an ISBN. It fetches the structured records, cross-links them (IA <-> OL),
resolves each author's Wikidata QID from Open Library's remote_ids, and writes a clean
labelled blob that book_paste.parse_metadata reads exactly:

    python projects/isbn_cleanup/gen_book_txt.py --ia yourbookidentifier -o book.txt
    python projects/isbn_cleanup/gen_book_txt.py --ol OL12345M -o book.txt
    python projects/isbn_cleanup/gen_book_txt.py --isbn 9780199535675 -o book.txt
    python projects/isbn_cleanup/gen_book_txt.py --ia foo            # -> stdout

Then feed it in:  python projects/isbn_cleanup/make_book.py --file book.txt

Authors resolved to a QID are written as ``Author: Name [Q1234]`` -- book_paste now seeds
that QID into its prompt (Enter accepts), the "QID + name" case the old paste couldn't
express. The Open Library / Internet Archive IDs (P648/P724/P953) are NOT parsed by
make_book; they are emitted as a trailing note + printed so you can add them by hand
afterwards (see notes/make_work_edition_howto.md).
"""

import argparse
import re
import sys
import xml.etree.ElementTree as ET

import requests
from stdnum import isbn as stdnum_isbn

USER_AGENT = "DifoolBot/1.0 (https://www.wikidata.org/wiki/User:DifoolBot)"
OL = "https://openlibrary.org"
GRP = "https://grp.isbn-international.org/piid_rest_api/piid_search"
NDL = "https://ndlsearch.ndl.go.jp/api/opensearch"   # National Diet Library (Japanese books)
TIMEOUT = 30

# A few full language names -> ISO code, for archive.org's free-text language field
# (Open Library gives a proper /languages/<iso> key, which we prefer).
LANG_NAME = {
    "english": "eng", "french": "fre", "german": "ger", "dutch": "dut",
    "spanish": "spa", "italian": "ita", "portuguese": "por", "russian": "rus",
    "latin": "lat", "greek": "grc", "japanese": "jpn", "chinese": "zh",
}


def get_json(url: str, _hops: int = 0) -> dict | None:
    """GET a JSON document, or None on 404 (a missing/renamed id). Follows Open Library
    ``/type/redirect`` records (a merged/renamed id points at its ``location``)."""
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    doc = r.json()
    if isinstance(doc, dict) and doc.get("type", {}).get("key") == "/type/redirect" \
            and doc.get("location") and _hops < 5:
        return get_json(f"{OL}{doc['location']}.json", _hops + 1)
    return doc


def _as_list(v) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _olid(key: str) -> str:
    """'/authors/OL1A' -> 'OL1A'."""
    return (key or "").rstrip("/").rsplit("/", 1)[-1]


# ---------------------------------------------------------------- fetch & resolve

def resolve_ids(ia: str, ol: str, isbn: str) -> tuple:
    """From whatever the user supplied, work out (ia_id, edition_id, work_id) by following
    the cross-links (archive.org metadata <-> Open Library ocaid/openlibrary_edition)."""
    ia_id = ia or ""
    edition_id = ol if (ol and ol.upper().endswith("M")) else ""
    work_id = ol if (ol and ol.upper().endswith("W")) else ""

    if isbn and not edition_id:
        ed = get_json(f"{OL}/isbn/{re.sub(r'[^0-9Xx]', '', isbn)}.json")
        if ed:
            edition_id = _olid(ed.get("key", ""))

    if ia_id and not edition_id:                       # IA item -> its OL edition
        meta = get_json(f"https://archive.org/metadata/{ia_id}") or {}
        m = meta.get("metadata", {})
        edition_id = _olid(m.get("openlibrary_edition", "")) or edition_id
        work_id = _olid(m.get("openlibrary_work", "")) or work_id

    if edition_id and not ia_id:                       # OL edition -> its IA scan (ocaid)
        ed = get_json(f"{OL}/books/{edition_id}.json") or {}
        ia_id = ed.get("ocaid", "") or ia_id
    return ia_id, edition_id, work_id


def grp_registrant(isbn: str) -> str | None:
    """One-line ISBN-registrant note from the Global Register of Publishers
    (grp.isbn-international.org, the authority on who a prefix belongs to). Derives the
    registrant prefix from the ISBN via stdnum's range hyphenation, then looks it up.
    Returns e.g. 'Avon Books - United States of America [978-0-380]', or None. Best-effort:
    the *registrant* only identifies the publisher; you still model it by hand per
    notes/isbn_publisher_guide.md (reseller/self-pub registrants are not real publishers)."""
    comp = stdnum_isbn.compact(isbn or "")
    if not stdnum_isbn.is_valid(comp):
        return None
    parts = stdnum_isbn.format(stdnum_isbn.to_isbn13(comp)).split("-")   # 978-0-380-00327-3
    if len(parts) < 4:
        return None
    prefix = "-".join(parts[:3])                                         # 978-0-380
    try:
        r = requests.get(GRP, params={"q": prefix, "wt": "json"},
                         headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        r.raise_for_status()
        docs = r.json().get("response", {}).get("docs", [])
    except Exception:
        return None
    # q= is a fuzzy search; keep the doc whose ISBNPrefix list holds the exact prefix.
    exact = next((d for d in docs if prefix in (d.get("ISBNPrefix") or [])), None)
    if not exact:
        if prefix.startswith("979-8"):
            return f"{prefix}: Amazon KDP free block -> self-published (no registrant)"
        return None
    name = exact.get("RegistrantName") or "?"
    country = exact.get("Country") or ""
    who = f"{name} - {country}" if country else name
    return f"{who} [{prefix}]"


def author_line(author_key: str) -> str:
    """'Author: Name [Qxxxx]' from an OL author key, QID via remote_ids.wikidata."""
    a = get_json(f"{OL}/authors/{_olid(author_key)}.json") or {}
    name = a.get("name") or a.get("personal_name") or _olid(author_key)
    qid = (a.get("remote_ids") or {}).get("wikidata", "")
    return f"{name} [{qid}]" if re.fullmatch(r"Q\d+", qid or "") else name


def collect(ia_id: str, edition_id: str, work_id: str) -> dict:
    """Merge the archive.org + Open Library records into flat fields. Open Library edition
    data wins (it is structured); archive.org fills gaps; the work supplies subjects."""
    f: dict = {"authors": [], "editors": [], "subjects": []}

    ia_meta = {}
    if ia_id:
        ia_meta = (get_json(f"https://archive.org/metadata/{ia_id}") or {}).get("metadata", {})

    ed = get_json(f"{OL}/books/{edition_id}.json") if edition_id else None
    ed = ed or {}
    if ed.get("key"):                                  # canonical id (after any redirect)
        edition_id = _olid(ed["key"])
    if not work_id and ed.get("works"):
        work_id = _olid(ed["works"][0].get("key", ""))
    work = get_json(f"{OL}/works/{work_id}.json") if work_id else None
    work = work or {}
    if work.get("key"):
        work_id = _olid(work["key"])

    # title / subtitle
    f["title"] = ed.get("title") or work.get("title") or ia_meta.get("title", "")
    f["subtitle"] = ed.get("subtitle") or work.get("subtitle") or ""

    # authors (prefer the edition's, fall back to the work's), with QID resolution
    author_keys = [a.get("key") for a in ed.get("authors", []) if a.get("key")]
    if not author_keys:
        author_keys = [a.get("author", {}).get("key")
                       for a in work.get("authors", []) if a.get("author")]
    f["authors"] = [author_line(k) for k in author_keys if k]
    if not f["authors"]:                               # no OL author record -> IA creator name
        f["authors"] = [c for c in _as_list(ia_meta.get("creator")) if c]

    # editors: OL "contributors" with an editor role (name only; no author record/QID)
    for c in ed.get("contributors", []):
        if "edit" in (c.get("role") or "").lower() and c.get("name"):
            f["editors"].append(c["name"])

    f["publisher"] = (ed.get("publishers") or [ia_meta.get("publisher", "")])[0] or ""
    f["place"] = (ed.get("publish_places") or [None])[0] or ""
    f["date"] = ed.get("publish_date") or ia_meta.get("date") or ia_meta.get("year", "")
    f["pages"] = ed.get("number_of_pages") or ""

    isbns = _as_list(ed.get("isbn_13")) + _as_list(ed.get("isbn_10"))
    if not isbns:
        isbns = [i for i in _as_list(ia_meta.get("isbn")) if i]
    f["isbn"] = ", ".join(dict.fromkeys(isbns))         # de-dupe, keep order

    # language: OL '/languages/eng' -> 'eng'; else map IA's free-text name
    lang = ""
    if ed.get("languages"):
        lang = _olid(ed["languages"][0].get("key", ""))
    elif ia_meta.get("language"):
        raw = _as_list(ia_meta["language"])[0].strip().lower()
        lang = LANG_NAME.get(raw, raw)
    f["lang"] = lang

    f["lccn"] = (_as_list(ed.get("lccn")) or [""])[0]
    f["oclc"] = (_as_list(ed.get("oclc_numbers")) or [""])[0]
    f["edition_no"] = ed.get("edition_name", "")
    f["series"] = (_as_list(ed.get("series")) or [""])[0]
    f["subjects"] = [s for s in _as_list(work.get("subjects"))][:12]

    f["_ia_id"] = ia_id
    f["_edition_id"] = edition_id
    f["_work_id"] = work_id
    return f


# ------------------------------------------------------ National Diet Library (fallback)

def _ndl_text(item, tag: str) -> list:
    return [e.text.strip() for e in item
            if e.tag.split("}")[-1] == tag and e.text and e.text.strip()]


def collect_ndl(isbn: str) -> dict | None:
    """Fallback source for a Japanese ISBN (978-4...) absent from Open Library: the National
    Diet Library (ndlsearch.ndl.go.jp OpenSearch). Returns a fields dict shaped like
    ``collect`` (or None if NDL has no record either)."""
    try:
        r = requests.get(NDL, params={"isbn": isbn},
                         headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        r.raise_for_status()
        item = ET.fromstring(r.content).find(".//item")
    except Exception:
        return None
    if item is None:
        return None
    titles = _ndl_text(item, "title")
    if not titles:
        return None

    f: dict = {"authors": [], "editors": [], "subjects": []}
    f["title"] = titles[0]
    f["subtitle"] = ""
    # <creator> is "surname, given"; for a Japanese name drop the comma -> 伊東剛史. Role
    # comes from the statement of responsibility (編 = editor, else author/著).
    creators = [c.replace(", ", "").replace(",", "") for c in _ndl_text(item, "creator")]
    resp = " ".join(_ndl_text(item, "author"))
    role = "editors" if ("編" in resp and "著" not in resp) else "authors"
    f[role] = creators
    f["publisher"] = (_ndl_text(item, "publisher") or [""])[0]
    f["place"] = ""                                        # NDL gives a country code, not a city
    issued = (_ndl_text(item, "issued") or [""])[0]        # '2017.3' -> '2017-03'
    m = re.match(r"(\d{4})(?:\.(\d{1,2}))?", issued)
    if m:
        f["date"] = f"{m.group(1)}-{int(m.group(2)):02d}" if m.group(2) else m.group(1)
    else:
        f["date"] = (_ndl_text(item, "date") or [""])[0]
    pm = re.search(r"\d+", (_ndl_text(item, "extent") or [""])[0])
    f["pages"] = pm.group(0) if pm else ""
    f["isbn"] = isbn
    f["lang"] = "ja"
    f["lccn"] = ""
    f["oclc"] = ""
    f["edition_no"] = ""
    f["series"] = ""
    f["title_en"] = ""                                     # NDL has no parallel title; add by hand
    f["subjects"] = _ndl_text(item, "subject")[:8]
    f["_ia_id"] = f["_edition_id"] = f["_work_id"] = ""
    return f


# --------------------------------------------------------------------- emit

def render(f: dict) -> str:
    """Fields -> a labelled blob book_paste.parse_metadata reads, plus a trailing ID note
    (parse_metadata ignores '#' lines) for the P648/P724/P953 you add by hand."""
    lines = []

    def put(label, value):
        if value:
            lines.append(f"{label}: {value}")

    put("Title", f["title"])
    put("English title", f.get("title_en"))
    put("Subtitle", f["subtitle"])
    for a in f["authors"]:
        put("Author", a)
    for e in f["editors"]:
        put("Editor", e)
    put("Publisher", f["publisher"])
    if f.get("_registrant"):                            # info only (make_book ignores '#')
        lines.append(f"# ISBN registrant (grp.isbn-international.org): {f['_registrant']}")
    put("Place", f["place"])
    put("Published", f["date"])
    put("ISBN", f["isbn"])
    put("Pages", f["pages"])
    put("Language", f["lang"])
    put("LCCN", f["lccn"])
    put("OCLC", f["oclc"])
    put("Edition", f["edition_no"])
    put("Series", f["series"])
    if f["subjects"]:
        put("Subjects", "; ".join(f["subjects"]))

    # Real labelled lines -> make_book parses these and creates them: Open Library work id
    # as P648 on the WORK, edition id as P648 + Internet Archive id as P724 on the EDITION.
    # (P953 full-work URL is left for the interactive prompt: only add it if freely readable.)
    if f["_work_id"] or f["_edition_id"] or f["_ia_id"]:
        lines.append("")
        lines.append("# make_book creates these as P648 (work), P648/P724 (edition):")
        put("Open Library work", f["_work_id"])
        put("Open Library edition", f["_edition_id"])
        put("Internet Archive", f["_ia_id"])
    return "\n".join(lines) + "\n"


def dup_check(f: dict) -> None:
    """Best-effort: warn if a Wikidata item already carries this Open Library id (P648),
    so you don't create a duplicate. Never fatal -- skipped if the query endpoint is down."""
    ids = [x for x in (f["_edition_id"], f["_work_id"]) if x]
    if not ids:
        return
    try:
        from shared_lib import qlever
    except Exception:
        return
    values = " ".join(f'"{i}"' for i in ids)
    query = (
        "PREFIX wdt: <http://www.wikidata.org/prop/direct/>\n"
        "SELECT ?item WHERE { VALUES ?ol { " + values + " } ?item wdt:P648 ?ol }"
    )
    try:
        hits = qlever.query_item_qids(query)
    except Exception as exc:                            # offline / rate-limited -> skip
        print(f"# (duplicate check skipped: {exc})", file=sys.stderr)
        return
    if hits:
        print("#\n# !! POSSIBLE DUPLICATE: an item already has one of these Open Library "
              "IDs:", file=sys.stderr)
        for q in hits:
            print(f"#    https://www.wikidata.org/wiki/{q}", file=sys.stderr)
        print("#    Check it before creating a new work/edition.", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Generate a make_book.py paste file from archive.org / Open Library.")
    ap.add_argument("--ia", metavar="ID", help="archive.org identifier (details/<ID>)")
    ap.add_argument("--ol", metavar="OLID", help="Open Library edition (OL..M) or work (OL..W)")
    ap.add_argument("--isbn", metavar="ISBN", help="ISBN (resolved via Open Library)")
    ap.add_argument("-o", "--out", metavar="PATH", help="write here (default: stdout)")
    args = ap.parse_args()
    if not (args.ia or args.ol or args.isbn):
        ap.error("give at least one of --ia / --ol / --isbn")

    ia_id, edition_id, work_id = resolve_ids(args.ia or "", args.ol or "", args.isbn or "")
    if ia_id or edition_id or work_id:
        f = collect(ia_id, edition_id, work_id)
    else:
        f = collect_ndl(args.isbn) if args.isbn else None  # Japanese ISBN not in Open Library
        if not f:
            sys.exit("could not resolve any archive.org / Open Library / NDL record from that "
                     "input")
        print(f"(not in Open Library; using NDL for {args.isbn})", file=sys.stderr)
    first_isbn = (f["isbn"].split(",")[0].strip() if f["isbn"] else "") or (args.isbn or "")
    f["_registrant"] = grp_registrant(first_isbn) if first_isbn else None
    dup_check(f)
    blob = render(f)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(blob)
        print(f"wrote {args.out}  (edition={f['_edition_id'] or '-'} "
              f"work={f['_work_id'] or '-'} ia={f['_ia_id'] or '-'})")
        print("next: python projects/isbn_cleanup/make_book.py --file " + args.out)
    else:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stdout.write(blob)


if __name__ == "__main__":
    main()
