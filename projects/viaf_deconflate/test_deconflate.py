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
from viaf.viaf_api_client import ViafStatus
from viaf_deconflate.deconflate import (
    QID_CONFLATION,
    AuthId,
    _cluster_has_conflicting_id,
    _cluster_shared_id,
    _fold_candidates,
    _is_own_fragment,
    build_candidate_query_for_qids,
    classify,
)

GND = AuthoritySource("P227", "DNB", "GND")   # viaf source code DNB
LC = AuthoritySource("P244", "LC", "LCNAF")
ISNI = AuthoritySource("P213", "ISNI", "ISNI")


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


# --- --only selection: QID-targeted query + row folding ------------------------

def _binding(qid, viaf, retrieved=None):
    row = {
        "item": {"value": f"http://www.wikidata.org/entity/{qid}"},
        "viaf_dep": {"value": viaf},
    }
    if retrieved is not None:
        row["retrieved"] = {"value": retrieved}
    return row


def test_query_for_qids_scopes_to_values_no_source_filter():
    q = build_candidate_query_for_qids(["Q42", "Q1"])
    assert "VALUES ?item { wd:Q42 wd:Q1 }" in q
    assert QID_CONFLATION in q          # still only conflation-deprecated P214s
    assert "wdt:P227" not in q          # but no authority-source requirement


def test_fold_keeps_most_recent_retrieved():
    cands = _fold_candidates([
        _binding("Q42", "12345", "2019-01-01"),
        _binding("Q42", "12345", "2023-05-01"),
    ])
    assert len(cands) == 1
    assert cands[0].retrieved.isoformat() == "2023-05-01"


def test_fold_separates_distinct_clusters_and_skips_bad_rows():
    cands = _fold_candidates([
        _binding("Q42", "12345"),
        _binding("Q42", "67890"),        # same item, different dep cluster
        _binding("Q7", ""),              # no viaf_dep -> skipped
        {"item": {"value": "not-a-qid"}, "viaf_dep": {"value": "999"}},  # skipped
    ])
    keys = {(c.qid, c.viaf_dep) for c in cands}
    assert keys == {("Q42", "12345"), ("Q42", "67890")}


# --- shared-id overlap: old cluster still carries an id that applies to item ----

def _found(mapping):
    c = _cluster(mapping)
    c.status = ViafStatus.FOUND
    return c


def test_cluster_shared_id_matches_ignored_source_isni():
    # the item's (shared, ignored-source) ISNI is present in the old cluster.
    hit = _cluster_shared_id(
        "Q1",
        _cluster({"ISNI": [("0000000000875385", "0000000000875385")]}),
        [AuthId(ISNI, "0000000000875385")],
    )
    assert hit is not None and hit.value == "0000000000875385"


def test_cluster_shared_id_none_when_absent():
    assert _cluster_shared_id(
        "Q1",
        _cluster({"ISNI": [("0000000000000001", "0000000000000001")]}),
        [AuthId(ISNI, "0000000000875385")],
    ) is None


def _classify(**kw):
    """classify with harmless defaults; override what a case needs."""
    base = dict(
        qid="Q1", v_dep="OLD", retrieved=None, clusters_hit={"NEW"}, fetched={},
        old=_found({}), v_live={"NEW"}, v_all={"NEW"}, benign=set(),
        old_is_clean=False, confirmed=False, old_shared=None,
        old_owner_confirmed=False, do_wdqs=False,
    )
    base.update(kw)
    return classify(**base)


def test_shared_id_routes_to_review_instead_of_relabel():
    # live ids moved out of the old cluster, but it still carries the item's id.
    outcome, _, _ = _classify(old_shared="ISNI 0000000000875385")
    assert outcome == "AMBIGUOUS_SHARED_ID"


def test_no_shared_id_still_relabels():
    # same situation without the leftover overlap -> the old behaviour (relabel).
    outcome, _, _ = _classify(old_shared=None)
    assert outcome == "RELABEL_ONLY"


def test_shared_id_relabels_when_owner_confirmed():
    # the shared id overlaps, but a different item is confirmed to own the old
    # cluster (holds it as its own non-deprecated P214) -> relabel stands.
    outcome, _, _ = _classify(
        old_shared="ISNI 0000000000875385", old_owner_confirmed=True,
    )
    assert outcome == "RELABEL_ONLY"


def test_shared_id_reviews_when_wkp_owner_unconfirmed():
    # VIAF's WKP may point at another item, but if that ownership isn't confirmed
    # (a name/year guess) the shared overlap still routes to review.
    outcome, _, _ = _classify(
        old_shared="ISNI 0000000000875385", old_owner_confirmed=False,
    )
    assert outcome == "AMBIGUOUS_SHARED_ID"


# --- benign own-fragments: several unmerged clusters of one person -------------

def test_two_benign_fragments_not_inconsistent():
    # no live VIAF; ids land in two benign own-fragments (same person, VIAF hasn't
    # merged them) -> RELABEL_ONLY, NOT INCONSISTENT (the frags are added in
    # evaluate/apply, not decided here).
    outcome, new, _ = _classify(
        v_live=set(), clusters_hit={"A", "B"}, v_all=set(), benign={"A", "B"},
    )
    assert outcome == "RELABEL_ONLY"
    assert new is None


def test_one_rival_plus_benign_fragment_adds_the_rival():
    # a benign fragment alongside one real new cluster: the rival is the primary
    # ADD; the benign fragment does not make it INCONSISTENT.
    outcome, new, _ = _classify(
        v_live=set(), clusters_hit={"A", "B"}, v_all=set(), benign={"B"},
    )
    assert outcome == "ADD_AND_RELABEL"
    assert new == "A"


def test_two_rivals_still_inconsistent():
    # two non-benign clusters remain a genuine disagreement -> review.
    outcome, _, _ = _classify(
        v_live=set(), clusters_hit={"A", "B"}, v_all=set(), benign=set(),
    )
    assert outcome == "INCONSISTENT"


def test_shared_id_ignored_when_still_in_old_cluster():
    # if a live id still resolves to the old cluster, the still-conflated path
    # owns the decision; old_shared must not hijack it.
    outcome, _, _ = _classify(
        clusters_hit={"OLD"}, v_all={"OLD"}, old_shared="ISNI 0000000000875385",
        old_is_clean=True,
    )
    assert outcome == "CORRECT_AS_OF_NOW"


# --- stamping also removes a stray retrieved (P813) qualifier ------------------

def test_stamp_removes_stray_retrieved_qualifier(monkeypatch):
    import viaf_deconflate.deconflate as d

    class FakeRef:
        def __init__(self, repo, pid, is_reference=False):
            self.id = pid
        def setTarget(self, t):
            self.target = t

    monkeypatch.setattr(d, "get_repo", lambda: None)
    monkeypatch.setattr(d.pwb, "Claim", FakeRef)
    monkeypatch.setattr(d.pwb, "WbTime", lambda **k: ("wbtime", k))

    class FakeClaim:
        def __init__(self):
            self.qualifiers = {
                d.wd.PID_RETRIEVED: ["stray-retrieved-qualifier"],
                d.wd.PID_REASON_FOR_DEPRECATED_RANK: ["the-reason"],
            }
            self.sources = []

    c = FakeClaim()
    d._stamp_retrieved(c)
    # the misplaced retrieved qualifier is gone, the reason qualifier is untouched
    assert d.wd.PID_RETRIEVED not in c.qualifiers
    assert d.wd.PID_REASON_FOR_DEPRECATED_RANK in c.qualifiers
    # and retrieved is now recorded as a single reference block
    assert len(c.sources) == 1
    assert list(c.sources[0].keys()) == [d.wd.PID_RETRIEVED]
