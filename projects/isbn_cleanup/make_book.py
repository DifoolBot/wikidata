#!/usr/bin/env python3
"""make_book.py -- create a written work (+ one edition) on Wikidata from pasted
Google Books or publisher metadata.

Paste the metadata (via --file or interactively), the tool parses it, you confirm
each field, and it creates two linked items:
  * a WORK    -- P31 = written work (Q47461344): title/subtitle/language/authors/subjects
  * an EDITION -- P31 = version, edition or translation (Q3331189): P629 -> work, plus
    publisher/place/date/ISBN/pages/DOI/edition-no/editors/format
then links the work to the edition (P747, with summary qualifiers).

Contributors without a QID fall back to P2093 (author name string) or, for editors,
P98 = somevalue + object named as (P1932) -- no entity lookups needed.

Read model authority: notes/isbn_bot.md "Canonical book data model" (WORK/EDITION
split, edition-only properties). All edits go through shared_lib.change_wikidata
(User-Agent/maxlag/throttle), dry-run by default in one daily editgroups batch.

Usage (repo root, PYTHONPATH=projects;projects/shared_lib via .env):
    python projects/isbn_cleanup/make_book.py --file book.txt        # dry run
    python projects/isbn_cleanup/make_book.py --file book.txt --save  # really create
    python projects/isbn_cleanup/make_book.py                         # paste, end with "."
"""

import argparse
import hashlib
import io
import re
import sys
from datetime import date

import pywikibot
from stdnum import isbn as stdnum_isbn

import curate_selfpub as csp
import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
from shared_lib.wikidata_site import get_repo

repo = get_repo()  # builds the Wikidata site (as every isbn_cleanup entry point does)

QID_WRITTEN_WORK = "Q47461344"   # WORK P31 default (authored book)
QID_EDITED_VOLUME = "Q1711593"   # WORK P31 for an editor-only book (92% of these carry P98)
EDITION_TYPE = "Q3331189"        # EDITION P31 (version, edition or translation)
QID_EBOOK = "Q128093"            # ebook (P437 distribution format)
QID_ENGLISH = "Q1860"            # default language

# A handful of common languages so the usual case needs no lookup; anything else,
# paste a QID. Keyed by ISO 639-1/639-2 code.
COMMON_LANG = {
    "en": QID_ENGLISH, "eng": QID_ENGLISH,
    "fr": "Q150", "fre": "Q150", "fra": "Q150",
    "de": "Q188", "ger": "Q188", "deu": "Q188",
    "nl": "Q7411", "dut": "Q7411", "nld": "Q7411",
    "es": "Q1321", "spa": "Q1321",
    "it": "Q652", "ita": "Q652",
    "pt": "Q5146", "por": "Q5146",
    "ru": "Q7737", "rus": "Q7737",
    "la": "Q397", "lat": "Q397",
}

_MONTHS = {}
for _i, _m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], 1):
    _MONTHS[_m.lower()] = _i
    _MONTHS[_m[:3].lower()] = _i

# Source label -> canonical field. Matched on a tab-separated label OR as a prefix
# of a label-glued-to-value line (publisher pages: "First Published2008"). Longest
# label wins, so "ebook isbn" beats "isbn" and "edited by" beats "editors".
LABELS = {
    "titel": "title", "title": "title",
    "ondertitel": "subtitle", "subtitle": "subtitle",
    "auteur": "authors", "auteurs": "authors", "author": "authors",
    "authors": "authors", "author(s)": "authors",
    "redacteur": "editors", "redacteurs": "editors", "editor": "editors",
    "editors": "editors", "edited by": "editors",
    "uitgever": "publisher", "publisher": "publisher", "imprint": "imprint",
    "pub. location": "place", "place of publication": "place",
    "place": "place", "plaats": "place",
    "first published": "date", "ebook published": "ebook_date",
    "published": "date", "publicatiedatum": "date", "datum": "date",
    "year": "date", "jaar": "date",
    "ebook isbn": "ebook_isbn", "e-book isbn": "ebook_isbn",
    "print isbn": "isbn", "isbn": "isbn",
    "lengte": "pages", "pages": "pages", "length": "pages",
    "aantal pagina's": "pages",
    "doi": "doi",
    "editie": "edition", "edition": "edition",
    "onderwerpen": "subjects", "subjects": "subjects", "subject": "subjects",
    "serie": "series", "series": "series",
}
_LABELS_BY_LEN = sorted(LABELS.items(), key=lambda kv: -len(kv[0]))


# --------------------------------------------------------------------------- parse

def parse_metadata(text: str) -> dict:
    """Pull labelled fields out of a pasted Google Books / publisher blob. Values are
    kept as raw strings (lists, since a label can repeat); leading unlabelled lines
    become ``_titleblock`` (publisher pages print the title/subtitle with no label)."""
    parsed: dict = {"_titleblock": []}
    seen_label = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        field = value = None
        if "\t" in line:                                   # Google Books: label<TAB>value
            lab, _, val = line.partition("\t")
            key = lab.strip().lower().rstrip(":")
            if key in LABELS:
                field, value = LABELS[key], val.strip()
        if field is None:                                  # publisher: "LabelValue" glued
            low = line.lower()
            for lab, f in _LABELS_BY_LEN:
                if low.startswith(lab):
                    field, value = f, line[len(lab):].strip(" :\t")
                    break
        if field is None:                                  # unlabelled line
            if not seen_label:
                parsed["_titleblock"].append(line)
            continue
        seen_label = True
        parsed.setdefault(field, [])
        if value:
            parsed[field].append(value)
    return parsed


def split_title(block: list) -> tuple:
    """(title, subtitle, series_lines) from the leading unlabelled lines. A colon in the
    first line splits title/subtitle; otherwise a second line is the subtitle."""
    if not block:
        return None, None, []
    title, subtitle, series = block[0], None, []
    if ":" in title:
        title, subtitle = (x.strip() for x in title.split(":", 1))
        series = block[1:]
    elif len(block) > 1:
        subtitle, series = block[1], block[2:]
    return title, subtitle, series


def _strip_year(s: str) -> tuple:
    """'CRC Press, 2019' -> ('CRC Press', '2019'); no trailing year -> (s, None)."""
    m = re.search(r",?\s*(\d{4})\s*$", s)
    if m:
        return s[:m.start()].strip().rstrip(","), m.group(1)
    return s.strip(), None


def _loose_date_iso(s: str) -> str:
    """Messy date -> ISO seed: '5 March 2008' -> '2008-03-05', 'March 2008' -> '2008-03',
    '2008' -> '2008'. Falls back to any 4-digit year, else ''."""
    s = s.strip()
    if re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", s):
        return s
    m = re.search(r"(?:(\d{1,2})\s+)?([A-Za-z]+)\.?\s+(\d{4})", s)
    if m and m.group(2).lower() in _MONTHS:
        mon = _MONTHS[m.group(2).lower()]
        if m.group(1):
            return f"{m.group(3)}-{mon:02d}-{int(m.group(1)):02d}"
        return f"{m.group(3)}-{mon:02d}"
    m = re.search(r"\d{4}", s)
    return m.group(0) if m else ""


def _parse_date(s: str):
    """ISO seed/user text -> WbTime at the right precision, else None."""
    s = s.strip()
    m = re.fullmatch(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", s)
    if not m:
        return None
    y, mo, d = m.group(1), m.group(2), m.group(3)
    if d:
        return pywikibot.WbTime(year=int(y), month=int(mo), day=int(d))
    if mo:
        return pywikibot.WbTime(year=int(y), month=int(mo))
    return pywikibot.WbTime(year=int(y))


def _qid_list(s: str) -> list:
    return [t.strip() for t in s.split(",")
            if t.strip().startswith("Q") and t.strip()[1:].isdigit()]


def _is_qid(s: str) -> bool:
    return s.startswith("Q") and s[1:].isdigit()


def _classify_isbns(text: str) -> tuple:
    """Split a string of ISBNs into (isbn10 hyphenated, isbn13 hyphenated, invalid)."""
    tens, thirteens, bad = [], [], []
    for tok in re.split(r"[,\s]+", text.strip()):
        if not tok:
            continue
        comp = stdnum_isbn.compact(tok)
        if not stdnum_isbn.is_valid(comp):
            bad.append(tok)
            continue
        fmt = stdnum_isbn.format(comp)
        bucket = thirteens if stdnum_isbn.isbn_type(comp) == "ISBN13" else tens
        if fmt not in bucket:
            bucket.append(fmt)
    return tens, thirteens, bad


# ------------------------------------------------------------------------- confirm

def _split_names(vals) -> list:
    names = []
    for v in vals or []:
        for part in re.split(r",| and |;|&", v):
            p = part.strip()
            if p:
                names.append(p)
    return names


def _people_prompt(role: str, vals) -> list:
    """Return [(qid_or_None, name_or_None)] for a contributor role, one prompt per parsed
    name (blank QID = fall back to a name string / named-as), then offer extras."""
    people = []
    for name in _split_names(vals):
        q = csp.ask(f"{role}: '{name}' -> QID (blank = keep as name)", "").strip()
        people.append((q if _is_qid(q) else None, name))
    while True:
        extra = csp.ask(f"add another {role}? name or QID (blank = done)", "").strip()
        if not extra:
            break
        if _is_qid(extra):
            people.append((extra, None))
        else:
            q = csp.ask(f"  QID for '{extra}' (blank = keep as name)", "").strip()
            people.append((q if _is_qid(q) else None, extra))
    return people


def ask_opt(prompt: str, default: str = "") -> str:
    """Prompt for an OPTIONAL field seeded with ``default``: Enter keeps the default, a
    single '-' clears it to blank, anything else replaces it. (csp.ask on its own returns
    the default on Enter, so with a seed shown there is otherwise no way to blank a field.)"""
    hint = "  (Enter = keep, - = none)" if default else ""
    v = csp.ask(prompt + hint, default).strip()
    return "" if v == "-" else v


def confirm_facts(parsed: dict) -> dict:
    """Interactively confirm/edit every field, seeded from the parse. Returns a flat facts
    dict consumed by build_work/build_edition. Optional fields use ask_opt: Enter keeps the
    seed, '-' clears it."""
    tb_title, tb_subtitle, tb_series = split_title(parsed.get("_titleblock", []))

    lang_in = ask_opt("language: ISO code (en, fr...) or QID", "en")
    lang_qid = lang_in if _is_qid(lang_in) else COMMON_LANG.get(lang_in.lower())
    if not lang_qid:
        print(f"    (unknown language '{lang_in}'; leaving P407 off)")
    lang_code = lang_in.lower() if lang_in and not _is_qid(lang_in) else "en"

    raw_title = (parsed.get("title") or [tb_title or ""])[0]
    sub_seed = (parsed.get("subtitle") or [tb_subtitle or ""])[0]
    if ":" in raw_title and not sub_seed:
        raw_title, sub_seed = (x.strip() for x in raw_title.split(":", 1))
    title = csp.ask(f"title [{lang_code}]", raw_title).strip()
    subtitle = ask_opt("subtitle", sub_seed) or None

    authors = _people_prompt("author", parsed.get("authors"))
    editors = _people_prompt("editor", parsed.get("editors"))

    # Work type: an editor-only book is an edited volume (Q1711593), where editor is the
    # norm (92% carry P98); anything else defaults to written work. Overridable per book.
    default_type = QID_EDITED_VOLUME if (editors and not authors) else QID_WRITTEN_WORK
    type_names = {QID_WRITTEN_WORK: "written work", QID_EDITED_VOLUME: "edited volume"}
    wt_in = csp.ask(f"work type QID ({QID_WRITTEN_WORK}=written work, "
                    f"{QID_EDITED_VOLUME}=edited volume)", default_type).strip()
    work_type_qid = wt_in if _is_qid(wt_in) else default_type
    print(f"    work P31 = {work_type_qid} {type_names.get(work_type_qid, '')}".rstrip())

    pub_seed = ""
    if parsed.get("publisher"):
        pub_seed = _strip_year(parsed["publisher"][0])[0]
    elif parsed.get("imprint"):
        pub_seed = parsed["imprint"][0]
    pub_in = ask_opt("publisher: QID(s) (comma-sep) or a name", pub_seed)
    publisher_qids = _qid_list(pub_in)
    pub_name = next((t.strip() for t in pub_in.split(",")
                     if t.strip() and t.strip() not in publisher_qids), None)

    date_seed = ""
    for k in ("date", "ebook_date"):
        if parsed.get(k):
            date_seed = _loose_date_iso(parsed[k][0])
            if date_seed:
                break
    if not date_seed and parsed.get("publisher"):
        date_seed = _strip_year(parsed["publisher"][0])[1] or ""
    date_in = ask_opt("publication date (YYYY / YYYY-MM / YYYY-MM-DD)", date_seed)
    pub_date = _parse_date(date_in) if date_in else None
    if date_in and not pub_date:
        print("    (unrecognised date; leaving it off)")

    place_hint = f" [{parsed['place'][0]} -- needs a QID]" if parsed.get("place") else ""
    place_in = csp.ask(f"place of publication QID or blank{place_hint}", "").strip()
    place_qid = place_in if _is_qid(place_in) else None

    isbn_seed = []
    for k in ("isbn", "ebook_isbn"):
        for v in parsed.get(k, []):
            isbn_seed += [t for t in re.split(r"[,\s]+", v) if t]
    isbn_in = ask_opt("ISBN(s) for THIS edition (comma/space-sep)", ", ".join(isbn_seed))
    isbn10, isbn13, bad = _classify_isbns(isbn_in)
    for b in bad:
        print(f"    ! ignoring invalid ISBN: {b}")

    pages_seed = ""
    if parsed.get("pages"):
        m = re.search(r"\d+", parsed["pages"][0])
        pages_seed = m.group(0) if m else ""
    pages_in = ask_opt("number of pages", pages_seed)
    pages = int(pages_in) if pages_in.isdigit() else None

    ed_seed = ""
    if parsed.get("edition"):
        m = re.search(r"\d+", parsed["edition"][0])
        ed_seed = m.group(0) if m else ""
    edition_no = ask_opt("edition number", ed_seed) or None

    doi_seed = ""
    if parsed.get("doi"):
        doi_seed = re.sub(r"(?i)^https?://(dx\.)?doi\.org/", "", parsed["doi"][0]).strip()
    doi = ask_opt("DOI (bare 10.xxxx/...)", doi_seed) or None

    ebook_seed = bool(parsed.get("ebook_isbn") or parsed.get("ebook_date"))
    is_ebook = csp.confirm("is this edition an e-book (P437 = ebook)?", ebook_seed)

    subj_hint = f" [{'; '.join(parsed['subjects'])}]" if parsed.get("subjects") else ""
    subject_qids = _qid_list(csp.ask(
        f"main subject QID(s) (comma-sep, blank = none){subj_hint}", "").strip())

    series_seed = (tb_series or parsed.get("series") or [""])[0]
    series_hint = f" [{series_seed}]" if series_seed else ""
    series_in = csp.ask(f"series (part of the series) QID or blank{series_hint}", "").strip()
    series_qid = series_in if _is_qid(series_in) else None

    return {
        "title": title, "subtitle": subtitle, "lang_code": lang_code, "lang_qid": lang_qid,
        "work_type_qid": work_type_qid, "authors": authors, "editors": editors,
        "publisher_qids": publisher_qids, "pub_name": pub_name,
        "place_qid": place_qid, "date": pub_date,
        "isbn10": isbn10, "isbn13": isbn13, "pages": pages,
        "edition_no": edition_no, "doi": doi, "is_ebook": is_ebook,
        "subject_qids": subject_qids, "series_qid": series_qid,
    }


# --------------------------------------------------------------------------- build

def _add_contributors(specs: list, people: list, role: str) -> None:
    """Append author/editor specs. With a QID -> P50/P98 item; name only -> P2093 for an
    author, or P98 = somevalue + object named as (P1932) for an editor (no name-string
    property exists for editors)."""
    for qid, name in people:
        if role == "author":
            specs.append((wd.PID_AUTHOR, qid, "item") if qid
                         else (wd.PID_AUTHOR_NAME_STRING, name, "string"))
        else:
            specs.append((wd.PID_EDITOR, qid, "item") if qid
                         else (wd.PID_EDITOR, None, "somevalue",
                               [(wd.PID_OBJECT_NAMED_AS, name, "string")]))


def _contrib_desc(facts: dict) -> str:
    if facts["authors"]:
        who = ", ".join(n for _, n in facts["authors"] if n)
        return f"book by {who}" if who else "book"
    who = ", ".join(n for _, n in facts["editors"] if n)
    return f"book edited by {who}" if who else "book"


def build_work(facts: dict) -> tuple:
    """(labels, descriptions, specs) for the WORK. Work-level facts only: title/subtitle/
    language/authors/editors/subjects/series -- no publication facts (those are edition-only).
    Both author (P50) and editor (P98) are work-level properties per WikiProject Books; the
    work classes used here (written work Q47461344 subclasses work Q386724; edited volume
    Q1711593 is explicitly allowed) both satisfy P98's type constraint."""
    lc = facts["lang_code"]
    specs = [
        (wd.PID_INSTANCE_OF, facts["work_type_qid"], "item"),
        (wd.PID_TITLE, (facts["title"], lc), "monolingual"),
    ]
    if facts["subtitle"]:
        specs.append((wd.PID_SUBTITLE, (facts["subtitle"], lc), "monolingual"))
    if facts["lang_qid"]:
        specs.append((wd.PID_LANGUAGE_OF_WORK_OR_NAME, facts["lang_qid"], "item"))
    _add_contributors(specs, facts["authors"], "author")   # P50/P2093 (work + edition)
    _add_contributors(specs, facts["editors"], "editor")   # P98 (work + edition)
    for sq in facts["subject_qids"]:
        specs.append((wd.PID_MAIN_SUBJECT, sq, "item"))
    if facts["series_qid"]:
        specs.append((wd.PID_PART_OF_THE_SERIES, facts["series_qid"], "item"))
    return {"mul": facts["title"]}, {"en": _contrib_desc(facts)}, specs


def build_edition(facts: dict, work_qid: str) -> tuple:
    """(labels, descriptions, specs) for the EDITION of ``work_qid``. Carries the
    publication facts (publisher/place/date/ISBN/pages/DOI/edition-no/editors/format)."""
    lc = facts["lang_code"]
    specs = [
        (wd.PID_INSTANCE_OF, EDITION_TYPE, "item"),
        (wd.PID_EDITION_OR_TRANSLATION_OF, work_qid, "item"),
        (wd.PID_TITLE, (facts["title"], lc), "monolingual"),
    ]
    if facts["subtitle"]:
        specs.append((wd.PID_SUBTITLE, (facts["subtitle"], lc), "monolingual"))
    if facts["lang_qid"]:
        specs.append((wd.PID_LANGUAGE_OF_WORK_OR_NAME, facts["lang_qid"], "item"))
    _add_contributors(specs, facts["authors"], "author")
    _add_contributors(specs, facts["editors"], "editor")
    for q in facts["publisher_qids"]:
        specs.append((wd.PID_PUBLISHER, q, "item"))
    if facts["pub_name"]:                                   # no item -> somevalue + named-as
        specs.append((wd.PID_PUBLISHER, None, "somevalue",
                      [(wd.PID_OBJECT_NAMED_AS, facts["pub_name"], "string")]))
    if facts["place_qid"]:
        specs.append((wd.PID_PLACE_OF_PUBLICATION, facts["place_qid"], "item"))
    if facts["date"]:
        specs.append((wd.PID_PUBLICATION_DATE, facts["date"], "time"))
    for v in facts["isbn13"]:
        specs.append((wd.PID_ISBN_13, v, "string"))
    for v in facts["isbn10"]:
        specs.append((wd.PID_ISBN_10, v, "string"))
    if facts["pages"]:
        specs.append((wd.PID_NUMBER_OF_PAGES,
                      pywikibot.WbQuantity(amount=facts["pages"], site=repo), "quantity"))
    if facts["edition_no"]:
        specs.append((wd.PID_EDITION_NUMBER, facts["edition_no"], "string"))
    if facts["doi"]:
        specs.append((wd.PID_DOI, facts["doi"].upper(), "string"))  # P356 stores DOIs upper-case
    if facts["is_ebook"]:
        specs.append((wd.PID_DISTRIBUTION_FORMAT, QID_EBOOK, "item"))
    year = facts["date"].year if facts["date"] else None
    kind = "e-book edition" if facts["is_ebook"] else "edition"
    return {"mul": facts["title"]}, {"en": f"{year} {kind}" if year else kind}, specs


def build_p747_quals(facts: dict) -> list:
    """Summary qualifiers for the work's P747 -> edition statement (language/date/
    publisher/place/format), mirroring curate_pd_works."""
    quals = []
    if facts["lang_qid"]:
        quals.append((wd.PID_LANGUAGE_OF_WORK_OR_NAME, facts["lang_qid"], "item"))
    if facts["date"]:
        quals.append((wd.PID_PUBLICATION_DATE, facts["date"], "time"))
    for q in facts["publisher_qids"]:
        quals.append((wd.PID_PUBLISHER, q, "item"))
    if facts["place_qid"]:
        quals.append((wd.PID_PLACE_OF_PUBLICATION, facts["place_qid"], "item"))
    if facts["is_ebook"]:
        quals.append((wd.PID_DISTRIBUTION_FORMAT, QID_EBOOK, "item"))
    return quals


# ------------------------------------------------------------------------- preview

def _fmt(pid, val, kind) -> str:
    if kind == "somevalue":
        return f"{pid} = (unknown value)"
    if kind == "monolingual":
        return f'{pid} = "{val[0]}"@{val[1]}'
    if kind == "time":
        iso = val.toTimestr(force_iso=True).lstrip("+").split("T")[0]
        p = getattr(val, "precision", 11)
        if p <= 9:                                          # year precision -> just the year
            iso = iso.split("-")[0]
        elif p == 10:                                       # month precision
            iso = "-".join(iso.split("-")[:2])
        return f"{pid} = {iso}"
    if kind == "quantity":
        return f"{pid} = {getattr(val, 'amount', val)}"
    return f"{pid} = {val}"


def preview(kind_label: str, labels: dict, descriptions: dict, specs: list) -> None:
    print(f"\n=== {kind_label} to create ===")
    for lang, val in labels.items():
        print(f"    label/{lang} = {val}")
    for lang, val in descriptions.items():
        print(f"    desc/{lang}  = {val}")
    for spec in specs:
        line = "    " + _fmt(spec[0], spec[1], spec[2])
        quals = spec[3] if len(spec) > 3 else ()
        if quals:
            line += "  {" + ", ".join(_fmt(*q) for q in quals) + "}"
        print(line)


def _quals_str(quals: list) -> str:
    return ", ".join(_fmt(*q) for q in quals) or "(none)"


# ---------------------------------------------------------------------------- main

def _read_blob(path) -> str:
    if path:
        with open(path, encoding="utf-8") as f:
            return f.read()
    print("Paste the book metadata, then a line containing just '.' :")
    lines = []
    for line in sys.stdin:
        if line.rstrip("\n") == ".":
            break
        lines.append(line)
    return "".join(lines)


def daily_editgroup(tag: str) -> str:
    return hashlib.sha1(f"{tag}:{date.today().isoformat()}".encode()).hexdigest()[:12]


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Create a written work + one edition on Wikidata from pasted metadata.")
    ap.add_argument("--save", action="store_true", help="really create (default: dry run)")
    ap.add_argument("--file", metavar="PATH", help="read the pasted metadata from a file")
    args = ap.parse_args()

    # Book titles/authors are international; Windows consoles default to cp1252 and would
    # raise UnicodeEncodeError at print time. Force UTF-8 out.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    dry_run = not args.save
    eg = daily_editgroup("make_book")

    parsed = parse_metadata(_read_blob(args.file))
    detected = ", ".join(k for k in parsed if not k.startswith("_") and parsed[k]) or "nothing"
    print(f"\nparsed fields: {detected}")
    facts = confirm_facts(parsed)

    wlabels, wdesc, wspecs = build_work(facts)
    preview("WORK", wlabels, wdesc, wspecs)
    elabels, edesc, especs = build_edition(facts, "(the new work)")
    preview("EDITION", elabels, edesc, especs)
    quals = build_p747_quals(facts)
    print(f"\n    then: work P747 -> edition  {{{_quals_str(quals)}}}")
    if facts["pub_name"]:
        print(f"    note: publisher \"{facts['pub_name']}\" has no QID -> "
              "P123 = somevalue + object named as (P1932)")

    if dry_run:
        print("\n[dry run] nothing written. Re-run with --save to create.")
        return
    if not csp.confirm("\nCREATE work + edition + link?", True):
        print("aborted.")
        return

    work_qid = cwd.create_item(labels=wlabels, descriptions=wdesc, claim_specs=wspecs,
                               edit_group=eg, test=False, summary="create written work",
                               site=repo)
    print(f"created work {work_qid}")
    especs = build_edition(facts, work_qid)[2]             # real P629 target now
    ed_qid = cwd.create_item(labels=elabels, descriptions=edesc, claim_specs=especs,
                             edit_group=eg, test=False,
                             summary=f"create edition of {work_qid}", site=repo)
    print(f"created edition {ed_qid}")

    work_page = cwd.WikiDataPage(item=pywikibot.ItemPage(repo, work_qid), test=False)
    work_page.edit_group = eg
    link = pywikibot.Claim(repo, wd.PID_HAS_EDITION_OR_TRANSLATION)
    link.setTarget(pywikibot.ItemPage(repo, ed_qid))
    for qp, qv, qk in quals:
        q = pywikibot.Claim(repo, qp, is_qualifier=True)
        q.setTarget(pywikibot.ItemPage(repo, qv) if qk == "item" else qv)
        link.qualifiers.setdefault(qp, []).append(q)
    work_page.add_claim(wd.PID_HAS_EDITION_OR_TRANSLATION, link)
    work_page.apply()
    print(f"linked {work_qid} P747 -> {ed_qid}  ([[toolforge:editgroups/b/CB/{eg}|batch]])")


if __name__ == "__main__":
    main()
