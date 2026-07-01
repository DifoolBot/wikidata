"""Pure matching logic -- no network, no pywikibot. Unit-testable."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

IMPORT_PROPERTY = "P143"


def import_ref_project_qid(reference: Dict) -> Optional[str]:
    """If `reference` is an 'imported from Wikimedia project' (P143) reference,
    return the project's QID (e.g. 'Q8449'); else None."""
    snaks = reference.get("snaks", {}).get(IMPORT_PROPERTY)
    if not snaks:
        return None
    for snak in snaks:
        dv = snak.get("datavalue", {})
        if dv.get("type") == "wikibase-entityid":
            return dv["value"].get("id")
    return None


def reference_is_sole_import(reference: Dict) -> bool:
    """True if the reference contains only the P143 import snak (the typical
    QuickStatements shape). Used to decide safe whole-reference removal."""
    props = set(reference.get("snaks", {}).keys())
    return props == {IMPORT_PROPERTY}


def _claim_ref_pairs(entity: Dict) -> Set[Tuple[str, str]]:
    """(claim GUID, reference hash) pairs. Identical reference *content* shares
    a hash, so we must key on the claim too -- otherwise the same import ref
    added to a second claim looks 'pre-existing' and gets missed."""
    pairs: Set[Tuple[str, str]] = set()
    for claims in entity.get("claims", {}).values():
        for claim in claims:
            cid = claim.get("id", "")
            for ref in claim.get("references", []):
                if "hash" in ref:
                    pairs.add((cid, ref["hash"]))
    return pairs


@dataclass(frozen=True)
class AddedImportRef:
    claim_property: str   # e.g. "P1559"
    claim_id: str         # statement GUID
    ref_hash: str
    project_qid: str      # e.g. "Q8449"
    sole_import: bool     # reference contains only the P143 snak


def added_import_refs(entity_rev: Dict, entity_parent: Dict) -> List[AddedImportRef]:
    """References that exist in `entity_rev` but not its parent AND are P143
    Wikimedia-project imports. This pinpoints exactly what a wbsetreference-add
    revision introduced."""
    parent_pairs = _claim_ref_pairs(entity_parent)
    out: List[AddedImportRef] = []
    for prop, claims in entity_rev.get("claims", {}).items():
        for claim in claims:
            cid = claim.get("id", "")
            for ref in claim.get("references", []):
                h = ref.get("hash")
                if not h or (cid, h) in parent_pairs:
                    continue
                project_qid = import_ref_project_qid(ref)
                if project_qid is None:
                    continue
                out.append(AddedImportRef(
                    claim_property=prop,
                    claim_id=claim.get("id", ""),
                    ref_hash=h,
                    project_qid=project_qid,
                    sole_import=reference_is_sole_import(ref),
                ))
    return out


def has_sitelink(entity: Dict, dbcode: str) -> bool:
    return dbcode in (entity.get("sitelinks") or {})


def reference_present(entity: Dict, claim_id: str, ref_hash: str) -> bool:
    return (claim_id, ref_hash) in _claim_ref_pairs(entity)
