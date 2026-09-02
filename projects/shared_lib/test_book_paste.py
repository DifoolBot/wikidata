"""Offline unit tests for book_paste.py (the shared paste->confirm->build core used by
make_book and the floruit_books migrator). The interactive confirm_facts and any path
that builds a WbQuantity (pages) need a live site, so they are left to the tools'
dry-runs; everything here is pure.

Run with:
    python -m pytest projects/shared_lib/test_book_paste.py -v
"""

import pywikibot

import shared_lib.constants as wd
from shared_lib.book_paste import (
    COMMON_PLACE,
    LANG_MONO,
    _classify_isbns,
    _extract_inline_qid,
    _extract_qids,
    _norm_place,
    _split_names,
    build_edition,
    build_work,
    parse_metadata,
)


def _facts(**over):
    facts = {
        "title": "T", "subtitle": None, "lang_code": "en", "lang_qid": "Q1860",
        "work_type_qid": "Q47461344", "authors": [], "editors": [],
        "publisher_qids": [], "pub_name": None, "place_qid": None, "date": None,
        "isbn10": [], "isbn13": [], "pages": None, "edition_no": None, "doi": None,
        "lccn": None, "is_ebook": False, "subject_qids": [], "series_qid": None,
    }
    facts.update(over)
    return facts


def _map(specs):
    return {pid: value for pid, value, *_ in specs}


# ------------------------------------------------------------------- parsing

def test_parse_tab_separated_labels():
    p = parse_metadata("Title\tThe Book\nAuthor\tA. Writer\nISBN\t9780470031117\n")
    assert p["title"] == ["The Book"]
    assert p["authors"] == ["A. Writer"]
    assert p["isbn"] == ["9780470031117"]


def test_parse_glued_publisher_label():
    p = parse_metadata("First Published2008")
    assert p["date"] == ["2008"]


def test_classify_isbns_splits_valid_and_bad():
    tens, thirteens, bad = _classify_isbns("9780470031117 not-an-isbn")
    assert thirteens == ["978-0-470-03111-7"]
    assert "not-an-isbn" in bad


def test_parse_lccn_label():
    assert parse_metadata("Lccn\t36011414")["lccn"] == ["36011414"]


def test_parse_french_auteur_s_label():
    # "Auteur(s)" (SUDOC/BnF) must yield the author, not a spurious "(s)"
    assert _split_names(parse_metadata("Auteur(s)\tMin Lin").get("authors")) == ["Min Lin"]


def test_split_names_drops_s_residue():
    assert _split_names(["Min Lin, (s)"]) == ["Min Lin"]
    assert _split_names(["(s)"]) == []


def test_extract_inline_qid():
    # a generated paste can carry the QID next to the name (bracket or paren)
    assert _extract_inline_qid("Jane Roe [Q1234]") == ("Jane Roe", "Q1234")
    assert _extract_inline_qid("Jane Roe (Q1234)") == ("Jane Roe", "Q1234")
    assert _extract_inline_qid("Q1234") == ("", "Q1234")          # bare QID -> no name
    assert _extract_inline_qid("Jane Roe") == ("Jane Roe", "")    # plain name, no QID
    assert _extract_inline_qid("E. E. Cummings") == ("E. E. Cummings", "")


def test_split_names_keeps_inline_qid_intact():
    # the "; " separator splits people; each [Qxxx] stays glued to its name
    assert _split_names(["Jane Roe [Q1]; John Doe [Q2]"]) == [
        "Jane Roe [Q1]", "John Doe [Q2]"]


def test_extract_qids_subjects():
    # bare QIDs, inline 'name [QID]', and plain names sorted apart
    qids, names = _extract_qids("Q589; black hole [Q589]; Stars", r";")
    assert qids == ["Q589", "Q589"]
    assert names == ["Stars"]
    # prompt input, comma- or semicolon-separated
    assert _extract_qids("Q1, Q2")[0] == ["Q1", "Q2"]
    assert _extract_qids("Q1; Q2")[0] == ["Q1", "Q2"]
    # a subject name with a parenthetical isn't mistaken for a QID
    assert _extract_qids("Black holes (Astronomy)", r";") == ([], ["Black holes (Astronomy)"])


# ----------------------------------------------------------------- build_work

def test_build_work_author_qid_to_p50():
    labels, _desc, specs = build_work(_facts(authors=[("Q7", "Ann")]))
    m = _map(specs)
    assert m[wd.PID_INSTANCE_OF] == "Q47461344"
    assert m[wd.PID_AUTHOR] == "Q7"
    assert m[wd.PID_LANGUAGE_OF_WORK_OR_NAME] == "Q1860"
    assert labels == {"mul": "T"}


def test_build_work_author_name_only_to_p2093():
    specs = build_work(_facts(authors=[(None, "Ann")]))[2]
    assert (wd.PID_AUTHOR_NAME_STRING, "Ann", "string") in specs


def test_build_work_parallel_english_title():
    # a foreign book with an English/parallel title -> label/en + a second P1476@en
    labels, _d, specs = build_work(
        _facts(title="日本語", title_en="English Title", lang_code="ja"))
    assert labels == {"mul": "日本語", "en": "English Title"}
    titles = [s[1] for s in specs if s[0] == wd.PID_TITLE]
    assert ("日本語", "ja") in titles and ("English Title", "en") in titles


def test_parse_english_title_label():
    assert parse_metadata("English title: Foo")["title_en"] == ["Foo"]


# -------------------------------------------------------------- build_edition

def test_build_edition_links_work_isbn_and_somevalue_publisher():
    facts = _facts(isbn13=["978-0-470-03111-7"], pub_name="Wiley",
                   date=pywikibot.WbTime(year=2007))
    specs = build_edition(facts, "Q500")[2]
    m = _map(specs)
    assert m[wd.PID_INSTANCE_OF] == "Q3331189"
    assert m[wd.PID_EDITION_OR_TRANSLATION_OF] == "Q500"
    assert m[wd.PID_PUBLICATION_DATE].year == 2007
    assert (wd.PID_ISBN_13, "978-0-470-03111-7", "string") in specs
    publisher = next(s for s in specs if s[0] == wd.PID_PUBLISHER)
    assert publisher[2] == "somevalue"


def test_build_edition_lccn_to_p1144():
    specs = build_edition(_facts(lccn="36011414"), "Q500")[2]
    assert (wd.PID_LCCN_BIBLIOGRAPHIC, "36011414", "string") in specs


def test_build_edition_oclc_to_p243():
    specs = build_edition(_facts(oclc="123333"), "Q500")[2]
    assert (wd.PID_OCLC_CONTROL_NUMBER, "123333", "string") in specs


def test_parse_oclc_label():
    assert parse_metadata("OCLC\t123333")["oclc"] == ["123333"]


# ---------------------------------------------------- external ids (P648/P724/P953)

def test_build_work_open_library_work_id_to_p648():
    specs = build_work(_facts(ol_work="OL450063W"))[2]
    assert (wd.PID_OPEN_LIBRARY_ID, "OL450063W", "string") in specs


def test_build_edition_open_library_and_archive_ids():
    specs = build_edition(_facts(
        ol_edition="OL26683337M", ia_id="frankensteinormo00shel_8",
        full_url="https://archive.org/details/frankensteinormo00shel_8"), "Q500")[2]
    assert (wd.PID_OPEN_LIBRARY_ID, "OL26683337M", "string") in specs
    assert (wd.PID_INTERNET_ARCHIVE_ID, "frankensteinormo00shel_8", "string") in specs
    assert (wd.PID_FULL_WORK_AVAILABLE_AT_URL,
            "https://archive.org/details/frankensteinormo00shel_8", "string") in specs


def test_build_work_omits_edition_only_ids():
    # the OL EDITION id / IA id belong on the edition, never the work
    specs = build_work(_facts(ol_edition="OL1M", ia_id="foo"))[2]
    assert wd.PID_INTERNET_ARCHIVE_ID not in _map(specs)


def test_parse_external_id_labels():
    p = parse_metadata(
        "Open Library work: OL450063W\n"
        "Open Library edition: OL26683337M\n"
        "Internet Archive: frankensteinormo00shel_8\n")
    assert p["ol_work"] == ["OL450063W"]
    assert p["ol_edition"] == ["OL26683337M"]
    assert p["ia_id"] == ["frankensteinormo00shel_8"]


# ------------------------------------------------------- common place defaults

def test_common_place_new_york():
    assert COMMON_PLACE["new york"] == "Q60"


# ---------------------------------------------- language code normalisation

def test_lang_mono_normalizes_three_letter_codes():
    # Wikidata monolingual text rejects 639-2 codes; 'eng' must become 'en'
    assert LANG_MONO["eng"] == "en"
    assert LANG_MONO["dut"] == "nl"
    assert LANG_MONO.get("en", "en") == "en"     # already short -> unchanged
    assert LANG_MONO.get("grc", "grc") == "grc"  # valid special -> unchanged


def test_build_work_title_monolingual_uses_lang_code():
    labels, _d, specs = build_work(_facts(lang_code="en", title="T"))
    ml = next(s for s in specs if s[0] == wd.PID_TITLE)
    assert ml[1] == ("T", "en") and ml[2] == "monolingual"


def test_norm_place_strips_region_suffix():
    assert COMMON_PLACE[_norm_place("New York, N.Y.")] == "Q60"
    assert COMMON_PLACE[_norm_place("London, UK")] == "Q84"
    assert COMMON_PLACE[_norm_place("Washington, D.C.")] == "Q61"  # kept whole via its key
