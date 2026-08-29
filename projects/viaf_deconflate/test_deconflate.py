"""Offline unit tests for deconflate.py.

Cover the query-free cluster classification helpers that decide whether a
deprecated VIAF cluster still holds a second person. They read only a cluster's
``source_mapping`` and the item's authority ids, so a stub cluster and the real
(config-free) base ``AuthoritySource`` are enough -- no network, no VIAF calls.

Run with:
    python -m pytest projects/viaf_deconflate/test_deconflate.py -v
"""
import types

import viaf_deconflate.deconflate as d
from shared_lib.constants import QID_CONFLATION
from viaf.authority_sources import AuthoritySource
from viaf.viaf_api_client import ViafLookupResult, ViafStatus
from viaf_deconflate.deconflate import (
    AuthId,
    Result,
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
        old_owner_confirmed=False, foreign_ids=[], do_wdqs=False,
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


def test_new_cluster_with_foreign_id_routes_to_review():
    # the sole new cluster carries a NUKAT the item deprecated as a different
    # person -> conflated cluster -> review, not adopted.
    nukat = AuthoritySource("P1207", "NUKAT", "NUKAT")
    cl = _found({"NUKAT": [("n2004250575", "n2004250575")]})
    outcome, new, _ = _classify(
        v_live=set(), clusters_hit={"NEW"}, v_all=set(), benign=set(),
        fetched={"NEW": cl}, foreign_ids=[AuthId(nukat, "n2004250575")],
    )
    assert outcome == "NEW_CLUSTER_CONFLATED"
    assert new == "NEW"


def test_two_rivals_still_inconsistent():
    # two non-benign clusters remain a genuine disagreement -> review.
    outcome, _, _ = _classify(
        v_live=set(), clusters_hit={"A", "B"}, v_all=set(), benign=set(),
    )
    assert outcome == "INCONSISTENT"


def test_clean_old_cluster_with_rival_undeprecates_and_notes_rival():
    # the deprecated cluster is a clean own-fragment, but an id also lands in a
    # foreign rival -> un-deprecate (CORRECT_AS_OF_NOW), rival noted for review.
    outcome, _, detail = _classify(
        clusters_hit={"OLD", "RIVAL"}, v_all={"OLD"}, benign=set(),
        old_is_clean=True,
    )
    assert outcome == "CORRECT_AS_OF_NOW"
    assert "RIVAL" in detail


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


# --- processed-item state files -----------------------------------------------

import pytest


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(d, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(d, "DONE_FILE", tmp_path / "done.txt")
    monkeypatch.setattr(d, "REVIEW_FILE", tmp_path / "review.txt")
    monkeypatch.setattr(d, "ERROR_FILE", tmp_path / "error.txt")
    return tmp_path


def _res(qid, dep, outcome, frag=None):
    return Result(qid, dep, outcome, frag_clusters=frag or [])


def test_review_outcome_recorded_on_dry_run(state_dir):
    d.record_state([_res("Q1", "111", "INCONSISTENT")], edited_qids=set())
    assert d.load_skip_set() == {("Q1", "111")}
    # ...but not skipped when we ask to recheck review
    assert d.load_skip_set(include_review=False) == set()


def test_undeprecate_with_rival_review_lands_in_both_files(state_dir):
    # un-deprecate (edit) + a rival to review -> after saving, recorded to BOTH
    # done.txt (the un-deprecate) and review.txt (the rival worklist).
    r = Result("Q8", "888", "CORRECT_AS_OF_NOW", rival_review=["RIVAL"])
    d.record_state([r], edited_qids=set())      # not saved yet -> pending
    assert d.load_skip_set() == set()
    d.record_state([r], edited_qids={"Q8"})     # saved
    assert ("Q8", "888") in d._load_state_keys(d.DONE_FILE)
    assert ("Q8", "888") in d._load_state_keys(d.REVIEW_FILE)


def test_duplicate_rank_is_a_review_outcome(state_dir):
    # the same-value-both-ranks contradiction is review-only (recorded, no edit)
    assert "DUPLICATE_RANK" in d._REVIEW_OUTCOMES
    assert "DUPLICATE_RANK" not in d._EDIT_OUTCOMES
    d.record_state([_res("Q9", "24581184", "DUPLICATE_RANK")], edited_qids=set())
    assert ("Q9", "24581184") in d._load_state_keys(d.REVIEW_FILE)


def test_edit_outcome_pending_until_saved(state_dir):
    # a dry run (no edited qids) must NOT record an edit outcome
    d.record_state([_res("Q2", "222", "ADD_AND_RELABEL")], edited_qids=set())
    assert d.load_skip_set() == set()
    # once actually saved, it lands in done and is skipped
    d.record_state([_res("Q2", "222", "ADD_AND_RELABEL")], edited_qids={"Q2"})
    assert d.load_skip_set() == {("Q2", "222")}


def test_review_with_frag_is_pending_then_both_files(state_dir):
    r = _res("Q3", "333", "INCONSISTENT", frag=["999"])
    d.record_state([r], edited_qids=set())          # frag not saved -> pending
    assert d.load_skip_set() == set()
    d.record_state([r], edited_qids={"Q3"})         # frag saved
    assert ("Q3", "333") in d.load_skip_set()       # skipped now
    assert ("Q3", "333") in d._load_state_keys(d.DONE_FILE)
    assert ("Q3", "333") in d._load_state_keys(d.REVIEW_FILE)  # still on worklist


def test_error_recorded_but_never_skipped(state_dir):
    d.record_state([_res("Q4", "444", "ERROR")], edited_qids=set())
    assert d.load_skip_set() == set()
    assert ("Q4", "444") in d._load_state_keys(d.ERROR_FILE)


def test_recording_is_deduplicated(state_dir):
    r = _res("Q5", "555", "PROBABLY_CONFLATED")
    d.record_state([r], edited_qids=set())
    d.record_state([r], edited_qids=set())
    assert (d.REVIEW_FILE).read_text().count("Q5") == 1


# --- stale live P214s: redirect / withdrawn detection -------------------------

def test_redirect_target_string_dict_and_invalid():
    assert d._redirect_target(ViafLookupResult(ViafStatus.REDIRECT, "12345")) == "12345"
    assert d._redirect_target(
        ViafLookupResult(ViafStatus.REDIRECT, {"#text": "678"})) == "678"
    assert d._redirect_target(ViafLookupResult(ViafStatus.REDIRECT, "")) == ""
    assert d._redirect_target(ViafLookupResult(ViafStatus.REDIRECT, "12x")) == ""


class _FakeViaf:
    def __init__(self, mapping):
        self.mapping = mapping

    def cluster(self, v):
        return self.mapping[v]


def test_live_redirect_target_added_when_unused():
    viaf = _FakeViaf({"OLD": ViafLookupResult(ViafStatus.REDIRECT, "999")})
    red, wdn, rev = d.resolve_live_status(viaf, "Q1", ["OLD"], v_all={"OLD"}, do_wdqs=False)
    assert red == [("OLD", "999")] and not wdn and not rev


def test_live_redirect_target_already_on_item():
    viaf = _FakeViaf({"OLD": ViafLookupResult(ViafStatus.REDIRECT, "999")})
    red, wdn, rev = d.resolve_live_status(
        viaf, "Q1", ["OLD"], v_all={"OLD", "999"}, do_wdqs=False)
    assert red == [("OLD", None)]          # target present -> just deprecate old


def test_live_redirect_target_on_other_item_goes_to_review(monkeypatch):
    monkeypatch.setattr(d, "_items_with_viaf", lambda cid, qid: {"Q2"})
    viaf = _FakeViaf({"OLD": ViafLookupResult(ViafStatus.REDIRECT, "999")})
    red, wdn, rev = d.resolve_live_status(viaf, "Q1", ["OLD"], v_all={"OLD"}, do_wdqs=True)
    assert rev == ["OLD"] and not red and not wdn


def test_live_withdrawn_and_found():
    viaf = _FakeViaf({
        "A": ViafLookupResult(ViafStatus.ABANDONED),
        "B": ViafLookupResult(ViafStatus.FOUND),
    })
    red, wdn, rev = d.resolve_live_status(viaf, "Q1", ["A", "B"], v_all=set(), do_wdqs=False)
    assert wdn == ["A"] and not red and not rev   # FOUND is left alone


def test_deprecate_with_reason(monkeypatch):
    class FakeQ:
        def __init__(self, repo, pid, is_qualifier=False):
            self.id = pid
        def setTarget(self, t):
            self.target = t
    monkeypatch.setattr(d, "get_repo", lambda: None)
    monkeypatch.setattr(d.pwb, "Claim", FakeQ)
    monkeypatch.setattr(d.pwb, "ItemPage", lambda repo, qid: qid)

    class FakeClaim:
        def __init__(self):
            self.rank = "normal"
            self.qualifiers = {}
    c = FakeClaim()
    d._deprecate_with_reason(c, d.wd.QID_REDIRECT)
    assert c.rank == "deprecated"
    q = c.qualifiers[d.wd.PID_REASON_FOR_DEPRECATED_RANK]
    assert len(q) == 1 and q[0].target == d.wd.QID_REDIRECT
