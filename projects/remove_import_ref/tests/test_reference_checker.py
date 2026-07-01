"""Offline unit tests for the matching logic. Fixtures mirror the real shape
of Wikidata entity JSON (see Q7160034 rev 418853797: P143 -> Q8449 eswiki)."""

from projects.remove_import_ref.reference_checker import (
    AddedImportRef,
    added_import_refs,
    has_sitelink,
    import_ref_project_qid,
    reference_is_sole_import,
    reference_present,
)


def _import_ref(hash_, project_qid="Q8449", extra=False):
    snaks = {
        "P143": [{
            "snaktype": "value",
            "property": "P143",
            "datavalue": {"type": "wikibase-entityid",
                          "value": {"id": project_qid}},
        }]
    }
    if extra:
        snaks["P813"] = [{"snaktype": "value", "property": "P813"}]
    return {"hash": hash_, "snaks": snaks, "snaks-order": list(snaks)}


def _entity(refs, sitelinks=None):
    return {
        "id": "Q7160034",
        "sitelinks": {k: {"site": k} for k in (sitelinks or [])},
        "claims": {
            "P1559": [{
                "id": "Q7160034$abc",
                "mainsnak": {"property": "P1559"},
                "references": refs,
            }]
        },
    }


def test_import_ref_project_qid():
    assert import_ref_project_qid(_import_ref("h1")) == "Q8449"
    assert import_ref_project_qid({"snaks": {}}) is None


def test_sole_import():
    assert reference_is_sole_import(_import_ref("h1")) is True
    assert reference_is_sole_import(_import_ref("h1", extra=True)) is False


def test_added_import_ref_detected():
    rev = _entity([_import_ref("hNEW")])
    parent = _entity([])
    added = added_import_refs(rev, parent)
    assert added == [AddedImportRef("P1559", "Q7160034$abc", "hNEW", "Q8449", True)]


def test_preexisting_ref_not_flagged():
    ref = _import_ref("hOLD")
    rev = _entity([ref])
    parent = _entity([ref])  # already there in parent -> not "added"
    assert added_import_refs(rev, parent) == []


def test_sitelink_and_presence_helpers():
    ent = _entity([_import_ref("hNEW")], sitelinks=["enwiki"])
    assert has_sitelink(ent, "enwiki") is True
    assert has_sitelink(ent, "eswiki") is False
    assert reference_present(ent, "Q7160034$abc", "hNEW") is True
    assert reference_present(ent, "Q7160034$abc", "nope") is False
    assert reference_present(ent, "other$claim", "hNEW") is False


def test_same_hash_on_two_claims_both_detected():
    """Regression: identical import ref added to a second claim must NOT be
    treated as pre-existing just because the hash already appears elsewhere."""
    shared = _import_ref("hSHARED")
    parent = {
        "id": "Q1", "sitelinks": {},
        "claims": {
            "P1412": [{"id": "Q1$a", "references": [shared]}],   # already has it
            "P1559": [{"id": "Q1$b", "references": []}],          # not yet
        },
    }
    rev = {
        "id": "Q1", "sitelinks": {},
        "claims": {
            "P1412": [{"id": "Q1$a", "references": [shared]}],
            "P1559": [{"id": "Q1$b", "references": [shared]}],    # added here
        },
    }
    added = added_import_refs(rev, parent)
    assert [a.claim_id for a in added] == ["Q1$b"]
