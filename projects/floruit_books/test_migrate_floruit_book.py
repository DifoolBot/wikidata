"""Offline unit tests for migrate_floruit_book.py.

Only the pure helpers are covered (parsing, grouping, spec-building); the parts that
touch Wikidata (locate/apply/create) need a live site and are exercised by the
built-in dry-run instead. Importing the module does no network I/O.

Run with:
    python -m pytest projects/floruit_books/test_migrate_floruit_book.py -v
"""

import shared_lib.constants as wd
from floruit_books.migrate_floruit_book import (
    Candidate,
    ROLE_TO_PROP,
    _candidates_from_bindings,
    _last,
    _stmt_to_snak,
    build_edition,
    build_work,
)

Q_AUTHOR = "Q482980"
Q_WRITER = "Q36180"
Q_EDITOR = "Q1607826"
Q_ILLUSTRATOR = "Q644687"
Q_PHOTOGRAPHER = "Q33231"


def _spec_map(specs):
    """{pid: value} for the simple (pid, value, kind) specs; last one wins."""
    return {pid: value for pid, value, *_ in specs}


def _cand(role=Q_AUTHOR, lang="en", ids=None):
    return Candidate(
        person_qid="Q100",
        person_label="Jane Doe",
        st_snak="Q100$ABCD-1234",
        title="A Book",
        lang=lang,
        role=role,
        ids=ids if ids is not None else [(wd.PID_DNB_EDITION_ID, "111")],
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


# ------------------------------------------------------------------ build_work

def test_build_work_author_goes_to_p50_on_work():
    labels, desc, specs = build_work(_cand(role=Q_AUTHOR, lang="de"))
    m = _spec_map(specs)
    assert m[wd.PID_INSTANCE_OF] == "Q47461344"
    assert m[wd.PID_LANGUAGE_OF_WORK_OR_NAME] == "Q188"   # de
    assert m[wd.PID_AUTHOR] == "Q100"
    assert labels == {"mul": "A Book"}
    assert desc["en"] == "book by Jane Doe"
    # title is a monolingual (text, lang) tuple
    title_spec = next(s for s in specs if s[0] == wd.PID_TITLE)
    assert title_spec[1] == ("A Book", "de") and title_spec[2] == "monolingual"


def test_build_work_editor_goes_to_p98_on_work():
    _, _, specs = build_work(_cand(role=Q_EDITOR))
    assert _spec_map(specs)[wd.PID_EDITOR] == "Q100"


def test_build_work_illustrator_has_no_contributor_on_work():
    # illustrator is edition-level, so the work carries no contributor property
    _, _, specs = build_work(_cand(role=Q_ILLUSTRATOR))
    m = _spec_map(specs)
    assert wd.PID_AUTHOR not in m and wd.PID_EDITOR not in m and wd.PID_ILLUSTRATOR not in m


def test_build_work_unknown_language_skips_p407():
    _, _, specs = build_work(_cand(lang="zz"))
    assert wd.PID_LANGUAGE_OF_WORK_OR_NAME not in _spec_map(specs)


# --------------------------------------------------------------- build_edition

def test_build_edition_links_work_and_moves_ids():
    ids = [(wd.PID_DNB_EDITION_ID, "111"), (wd.PID_GOOGLE_BOOKS_ID, "g222")]
    _, _, specs = build_edition(_cand(ids=ids), "Q500", ids)
    m = _spec_map(specs)
    assert m[wd.PID_INSTANCE_OF] == "Q3331189"
    assert m[wd.PID_EDITION_OR_TRANSLATION_OF] == "Q500"
    assert m[wd.PID_DNB_EDITION_ID] == "111"
    assert m[wd.PID_GOOGLE_BOOKS_ID] == "g222"


def test_build_edition_illustrator_goes_to_p110_on_edition():
    _, _, specs = build_edition(_cand(role=Q_ILLUSTRATOR), "Q500", [])
    assert _spec_map(specs)[wd.PID_ILLUSTRATOR] == "Q100"


def test_build_edition_author_not_repeated_on_edition():
    _, _, specs = build_edition(_cand(role=Q_AUTHOR), "Q500", [])
    assert wd.PID_AUTHOR not in _spec_map(specs)   # author is work-level here


# ------------------------------------------------------------------ role table

def test_role_to_prop_scope():
    assert set(ROLE_TO_PROP) == {Q_AUTHOR, Q_WRITER, Q_EDITOR, Q_ILLUSTRATOR}
    assert Q_PHOTOGRAPHER not in ROLE_TO_PROP   # out of scope -> skipped at runtime
