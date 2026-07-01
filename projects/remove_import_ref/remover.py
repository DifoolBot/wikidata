"""The single edit operation, isolated so the rest of the project stays
network/auth-free and testable. Only imported on the --save path.
"""

from __future__ import annotations

import pywikibot as pwb

SUMMARY = "Remove [[Property:P143]] reference"

# EditGroups marker -- groups every edit of a run so the whole batch is
# reviewable/revertable in one click at editgroups.toolforge.org.
# "CB" = generic custom batch; batch_id is constant for the run.
EDITGROUP_SUFFIX = " ([[:toollabs:editgroups/b/CB/{batch_id}|details]])"


def remove_reference(
    site, qid: str, claim_id: str, ref_hash: str, dbcode: str, batch_id: str
) -> None:
    repo = site.data_repository()
    item = pwb.ItemPage(repo, qid)
    item.get()

    target_claim = None
    for claims in item.claims.values():
        for claim in claims:
            if claim.snak == claim_id or getattr(claim, "snak", None) == claim_id:
                target_claim = claim
                break
        if target_claim:
            break
    if target_claim is None:
        print(f"  {qid}: claim {claim_id} not found, skipping")
        return

    target_ref = None
    for source in target_claim.sources:
        # source is an OrderedDict {prop: [Claim, ...]}; match by hash.
        for snak_list in source.values():
            for snak in snak_list:
                if getattr(snak, "hash", None) == ref_hash:
                    target_ref = source
                    break
            if target_ref:
                break
        if target_ref:
            break
    if target_ref is None:
        print(f"  {qid}: reference {ref_hash} no longer present, skipping")
        return

    summary = SUMMARY.format(
        dbcode=dbcode
    )  # + EDITGROUP_SUFFIX.format(batch_id=batch_id)
    target_claim.removeSources(
        [snak for snaks in target_ref.values() for snak in snaks],
        summary=summary,
    )
    print(f"  {qid}: removed reference {ref_hash}")
