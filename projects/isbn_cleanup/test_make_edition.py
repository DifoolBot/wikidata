"""Offline unit tests for make_edition.py's pure strip-matching logic (edition_values /
_norm). The interactive create/link/strip path needs a live site and is covered by the
tool's dry-run.

Run with:
    python -m pytest projects/isbn_cleanup/test_make_edition.py -v
"""

import shared_lib.constants as wd
from isbn_cleanup.make_edition import _norm, edition_values


class _Date:
    """Stand-in for pywikibot.WbTime (edition_values reads only .year); constructing a real
    WbTime fetches the site for its calendar model, which we avoid offline."""
    def __init__(self, year):
        self.year = year


def _facts(**over):
    f = dict(isbn13=[], isbn10=[], date=None, pages=None, place_qid=None,
             publisher_qids=[], edition_no=None, oclc=None, doi=None, lccn=None)
    f.update(over)
    return f


def test_norm_identifiers():
    assert _norm(wd.PID_ISBN_10, "0-7181-0788-8") == "0718107888"
    assert _norm(wd.PID_ISBN_13, "978-0-7181-0788-2") == "9780718107882"
    assert _norm(wd.PID_OCLC_CONTROL_NUMBER, "oclc/123333") == "123333"
    assert _norm(wd.PID_DOI, "10.1000/xyz") == "10.1000/XYZ"
    assert _norm(wd.PID_LCCN_BIBLIOGRAPHIC, "36-011414") == "36011414"


def test_edition_values_shape_of_minds():
    # the four edition-only facts misplaced on the Shape-of-Minds work
    ev = edition_values(_facts(isbn10=["0-7181-0788-8"], date=_Date(1971),
                               pages=278, place_qid="Q84", oclc="123333"))
    assert ev[wd.PID_ISBN_10] == {"0718107888"}
    assert ev[wd.PID_PUBLICATION_DATE] == {"1971"}
    assert ev[wd.PID_NUMBER_OF_PAGES] == {"278"}
    assert ev[wd.PID_PLACE_OF_PUBLICATION] == {"Q84"}
    assert ev[wd.PID_OCLC_CONTROL_NUMBER] == {"123333"}


def test_edition_values_omits_absent_props():
    # nothing to strip when the edition carries no edition-only identifiers
    assert edition_values(_facts()) == {}
    ev = edition_values(_facts(pages=200))
    assert set(ev) == {wd.PID_NUMBER_OF_PAGES}
