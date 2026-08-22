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
    _classify_isbns,
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
