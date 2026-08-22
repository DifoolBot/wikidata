"""Offline unit tests for migrate_floruit_book.py.

Only the pure helpers are covered (parsing, grouping, contributor injection, edition
extras); the parts that touch Wikidata (locate/apply/create) and the interactive paste
flow need a live site and are exercised by the built-in dry-run. Importing the module
does no network I/O.

Run with:
    python -m pytest projects/floruit_books/test_migrate_floruit_book.py -v
"""

import shared_lib.constants as wd
from floruit_books.migrate_floruit_book import (
    Candidate,
    ROLE_CONTRIB,
    QID_ILLUSTRATOR_ROLE,
    _archive_id,
    _book_sources,
    _candidates_from_bindings,
    _dedup_key,
    _extra_edition_specs,
    _inject_person,
    _last,
    _prepend_person,
    _stmt_to_snak,
    _titles_match,
)

Q_AUTHOR = "Q482980"
Q_WRITER = "Q36180"
Q_EDITOR = "Q1607826"
Q_PHOTOGRAPHER = "Q33231"


def _cand(role=Q_AUTHOR, lang="en", ids=None, ref_url=None):
    return Candidate(
        person_qid="Q100",
        person_label="Jane Doe",
        st_snak="Q100$ABCD-1234",
        title="A Book",
        lang=lang,
        role=role,
        ids=ids if ids is not None else [(wd.PID_DNB_EDITION_ID, "111")],
        ref_url=ref_url,
    )


# --------------------------------------------------------------------- utilities

def test_last_takes_final_uri_segment():
    assert _last("http://www.wikidata.org/entity/Q482980") == "Q482980"


def test_stmt_to_snak_converts_statement_uri():
    uri = ("http://www.wikidata.org/entity/statement/"
           "Q132997957-8F3C0E4A-1B2C-3D4E-5F60-71829AB3CDEF")
    assert _stmt_to_snak(uri) == "Q132997957$8F3C0E4A-1B2C-3D4E-5F60-71829AB3CDEF"


# ----------------------------------------------------------------- row grouping

def _binding(stmt, role=Q_AUTHOR, title="T", lang="de", extra=None):
    b = {
        "person": {"value": "http://www.wikidata.org/entity/Q100"},
        "personLabel": {"value": "Jane Doe"},
        "stmt": {"value": f"http://www.wikidata.org/entity/statement/{stmt}"},
        "title": {"value": title, "xml:lang": lang},
        "role": {"value": f"http://www.wikidata.org/entity/{role}"},
    }
    if extra:
        b.update(extra)
    return b


def test_candidates_group_multiple_ids_per_statement():
    rows = [
        _binding("Q100-AAAA", extra={"dnb": {"value": "111"}}),
        _binding("Q100-AAAA", extra={"gbooks": {"value": "g222"}}),
    ]
    cands = _candidates_from_bindings(rows)
    assert len(cands) == 1
    c = cands[0]
    assert c.st_snak == "Q100$AAAA"
    assert c.title == "T" and c.lang == "de" and c.role == Q_AUTHOR
    assert (wd.PID_DNB_EDITION_ID, "111") in c.ids
    assert (wd.PID_GOOGLE_BOOKS_ID, "g222") in c.ids


def test_candidates_separate_statements_stay_separate():
    rows = [
        _binding("Q100-AAAA", extra={"dnb": {"value": "111"}}),
        _binding("Q100-BBBB", extra={"oclc": {"value": "999"}}),
    ]
    cands = _candidates_from_bindings(rows)
    assert [c.st_snak for c in cands] == ["Q100$AAAA", "Q100$BBBB"]


# ------------------------------------------------------------- prepend / inject

def test_prepend_person_dedups_same_qid():
    out = _prepend_person([("Q100", "Jane"), ("Q5", "Bob")], ("Q100", "Jane Doe"))
    assert out == [("Q100", "Jane Doe"), ("Q5", "Bob")]


def test_prepend_person_drops_nameonly_duplicate():
    out = _prepend_person([(None, "Jane Doe")], ("Q100", "Jane Doe"))
    assert out == [("Q100", "Jane Doe")]


def test_inject_person_author_prepends_to_authors():
    facts = {"authors": [], "editors": []}
    _inject_person(facts, _cand(role=Q_AUTHOR))
    assert facts["authors"] == [("Q100", "Jane Doe")]
    assert facts["editors"] == []


def test_inject_person_editor_prepends_to_editors():
    facts = {"authors": [], "editors": [("Q9", "Ed")]}
    _inject_person(facts, _cand(role=Q_EDITOR))
    assert facts["editors"][0] == ("Q100", "Jane Doe")


def test_inject_person_illustrator_leaves_contributors_untouched():
    facts = {"authors": [("Qx", "X")], "editors": []}
    _inject_person(facts, _cand(role=QID_ILLUSTRATOR_ROLE))
    assert facts["authors"] == [("Qx", "X")] and facts["editors"] == []


# ----------------------------------------------------------- edition extras

def test_extra_specs_moves_ids_as_strings():
    ids = [(wd.PID_DNB_EDITION_ID, "111"), (wd.PID_GOOGLE_BOOKS_ID, "g222")]
    assert _extra_edition_specs(_cand(ids=ids), ids) == [
        (wd.PID_DNB_EDITION_ID, "111", "string"),
        (wd.PID_GOOGLE_BOOKS_ID, "g222", "string"),
    ]


def test_extra_specs_illustrator_adds_p110():
    extra = _extra_edition_specs(_cand(role=QID_ILLUSTRATOR_ROLE),
                                 [(wd.PID_OPEN_LIBRARY_ID, "OL1M")])
    assert (wd.PID_OPEN_LIBRARY_ID, "OL1M", "string") in extra
    assert (wd.PID_ILLUSTRATOR, "Q100", "item") in extra


def test_extra_specs_archive_url_adds_p724():
    cand = _cand(role=Q_AUTHOR, ids=[], ref_url="https://archive.org/details/foo00bar")
    assert (wd.PID_INTERNET_ARCHIVE_ID, "foo00bar", "string") in _extra_edition_specs(cand, [])


# ----------------------------------------------------------- archive / dedup key

def test_archive_id_from_details_url():
    assert _archive_id("https://archive.org/details/danielyandeshisf00robi") == \
        "danielyandeshisf00robi"


def test_archive_id_ignores_trailing_path():
    url = "https://archive.org/details/diagnosismanagem0000meht/page/n7/mode/2up"
    assert _archive_id(url) == "diagnosismanagem0000meht"


def test_archive_id_none_for_other_urls():
    assert _archive_id("https://openlibrary.org/books/OL1M") is None
    assert _archive_id(None) is None


def test_dedup_key_prefers_bib_id_over_archive():
    cand = _cand(ids=[(wd.PID_DNB_EDITION_ID, "111")],
                 ref_url="https://archive.org/details/foo")
    assert _dedup_key(cand, [(wd.PID_DNB_EDITION_ID, "111")]) == (wd.PID_DNB_EDITION_ID, "111")


def test_dedup_key_falls_back_to_archive():
    cand = _cand(ids=[], ref_url="https://archive.org/details/foo00bar")
    assert _dedup_key(cand, []) == (wd.PID_INTERNET_ARCHIVE_ID, "foo00bar")


def test_dedup_key_none_when_no_id_or_url():
    assert _dedup_key(_cand(ids=[], ref_url=None), []) is None


# ------------------------------------------------------ book-source selection

class _FakeSnak:
    def __init__(self, target):
        self._t = target

    def getTarget(self):
        return self._t


def test_book_sources_single_reference():
    src = {wd.PID_DNB_EDITION_ID: [_FakeSnak("111")]}
    sources, moved = _book_sources([src], [(wd.PID_DNB_EDITION_ID, "111")])
    assert sources == [src]
    assert moved == [(wd.PID_DNB_EDITION_ID, "111")]


def test_book_sources_aggregates_across_two_references():
    # Jean Vincent: DNB id and SUDOC id live in separate reference blocks
    dnb = {wd.PID_DNB_EDITION_ID: [_FakeSnak("870030582")]}
    sudoc = {wd.PID_SUDOC_EDITIONS: [_FakeSnak("00950916X")]}
    other = {wd.PID_STATED_IN: [_FakeSnak("Q13219454")]}   # a non-book reference, ignored
    ids = [(wd.PID_DNB_EDITION_ID, "870030582"), (wd.PID_SUDOC_EDITIONS, "00950916X")]
    sources, moved = _book_sources([dnb, other, sudoc], ids)
    assert sources == [dnb, sudoc]                          # both book blocks, not `other`
    assert moved == ids                                    # every id, deduped


# --------------------------------------------------------- edition title match

def test_titles_match_handles_subtitle_difference():
    floruit = {"daniel yandes and his family : pioneers from pennsylvania to indiana, 1818"}
    edition = {"daniel yandes and his family"}
    assert _titles_match(floruit, edition)


def test_titles_match_exact():
    assert _titles_match({"the songs of the trees"}, {"the songs of the trees"})


def test_titles_match_rejects_different_titles():
    assert not _titles_match({"the songs of the trees"}, {"daniel yandes and his family"})


# ------------------------------------------------------------------ role table

def test_role_scope():
    # author/writer/photographer/cartoonist -> authors (P50); editor -> editors (P98)
    assert ROLE_CONTRIB[Q_AUTHOR] == "authors"
    assert ROLE_CONTRIB[Q_PHOTOGRAPHER] == "authors"       # real photo books are in scope
    assert ROLE_CONTRIB[Q_EDITOR] == "editors"
    assert QID_ILLUSTRATOR_ROLE not in ROLE_CONTRIB         # illustrator -> P110 (edition)


def test_inject_person_photographer_credited_as_author():
    facts = {"authors": [], "editors": []}
    _inject_person(facts, _cand(role=Q_PHOTOGRAPHER))
    assert facts["authors"] == [("Q100", "Jane Doe")]
