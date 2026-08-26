"""Offline unit tests for deconflate.py.

Cover the query-free cluster classification helpers that decide whether a
deprecated VIAF cluster still holds a second person. They read only a cluster's
``source_mapping`` and the item's authority ids, so a stub cluster and the real
(config-free) base ``AuthoritySource`` are enough -- no network, no VIAF calls.

Run with:
    python -m pytest projects/viaf_deconflate/test_deconflate.py -v
"""
import types

from viaf.authority_sources import AuthoritySource
from viaf_deconflate.deconflate import (
    AuthId,
    _cluster_has_conflicting_id,
    _is_own_fragment,
)

GND = AuthoritySource("P227", "DNB", "GND")   # viaf source code DNB
LC = AuthoritySource("P244", "LC", "LCNAF")


def _cluster(mapping):
    """A stub with just the attribute the helpers read."""
    return types.SimpleNamespace(source_mapping=mapping)


# --- _cluster_has_conflicting_id: same source, different value = second party --

def test_conflicting_same_source_different_value():
    # item GND=G1, cluster carries GND=G2 -> a second person's GND is in it.
    assert _cluster_has_conflicting_id(
        "Q1", _cluster({"DNB": [("G2", "")]}), [AuthId(GND, "G1")]
    )


def test_conflicting_foreign_source_is_not_confirmed():
    # cluster's only extra record is an LC the item lacks -> ambiguous, not a
    # confirmed conflict (this is the PROBABLY_CONFLATED case, not STILL).
    assert not _cluster_has_conflicting_id(
        "Q1",
        _cluster({"DNB": [("G1", "")], "LC": [("L9", "")]}),
        [AuthId(GND, "G1")],
    )


def test_conflicting_matching_value_only():
    assert not _cluster_has_conflicting_id(
        "Q1", _cluster({"DNB": [("G1", "")]}), [AuthId(GND, "G1")]
    )


def test_conflicting_wkp_entries_ignored():
    # WKP (Wikidata) links are handled elsewhere; this helper skips them.
    assert not _cluster_has_conflicting_id(
        "Q1",
        _cluster({"WKP": [("Q999", "")], "DNB": [("G1", "")]}),
        [AuthId(GND, "G1")],
    )


def test_conflicting_item_has_the_clusters_value():
    # item carries both G1 and G2; cluster's G2 matches -> no conflict.
    assert not _cluster_has_conflicting_id(
        "Q1",
        _cluster({"DNB": [("G2", "")]}),
        [AuthId(GND, "G1"), AuthId(GND, "G2")],
    )


# --- _is_own_fragment: cluster holds nothing but this person's own records -----

def test_own_fragment_all_ids_on_item():
    assert _is_own_fragment(
        "Q1",
        _cluster({"DNB": [("G1", "")], "WKP": [("Q1", "")]}),
        [AuthId(GND, "G1")],
    )


def test_own_fragment_foreign_source_breaks_it():
    # an LC record the item doesn't have -> not purely this person's fragment.
    assert not _is_own_fragment(
        "Q1",
        _cluster({"DNB": [("G1", "")], "LC": [("L9", "")]}),
        [AuthId(GND, "G1")],
    )


def test_own_fragment_wkp_other_item_breaks_it():
    assert not _is_own_fragment(
        "Q1",
        _cluster({"DNB": [("G1", "")], "WKP": [("Q999", "")]}),
        [AuthId(GND, "G1")],
    )
