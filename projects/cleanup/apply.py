"""
apply.py

Merges all diffs produced by the detectors into a single wbeditentity
payload and submits it in one API call — mirroring the JS mergeCleanupDiffs()
+ wbeditentity pattern exactly.

The entry point is apply_diffs(item, diffs, summary, dry_run).

Payload construction
--------------------
The wbeditentity API accepts:
  {
    "claims":  [ <claim JSON with optional "remove": "">, ... ],
    "aliases": { "<lang>": [ {"language": lang, "value": str}, ... ], ... }
  }

For ACTION_REMOVE_CLAIM we send:    { "id": claim_id, "remove": "" }
For ACTION_REMOVE_QUALIFIER we send the full claim JSON with the qualifier
  removed from its qualifiers dict.  We build this from the live pywikibot
  Claim object so we don't have to re-serialize everything from scratch.
For ACTION_REMOVE_ALIAS we collect all removals per language and send
  only the aliases that survive (pywikibot's AliasesDict.normalizeData
  converts a plain list of strings to the required API format).

All claim modifications are collected and deduplicated before the single
editEntity call is made.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pywikibot

from cleanup.detectors import (
    ACTION_CLEAN_URL,
    ACTION_DOWNGRADE_PREFERRED,
    ACTION_MERGE_CLAIM,
    ACTION_REMOVE_ALIAS,
    ACTION_REMOVE_CLAIM,
    ACTION_REMOVE_QUALIFIER,
    ACTION_REMOVE_REFS,
    PID_END_TIME,
    PID_REASON_FOR_PREFERRED_RANK,
)

# ==== Payload builders =======================================================


def _build_remove_claim(claim: "pywikibot.Claim") -> dict:
    """Return a wbeditentity claim entry that removes the claim."""
    return {"id": claim.snak, "remove": ""}


def _build_remove_qualifier(
    claim: "pywikibot.Claim",
    qualifier_pid: str,
    qualifier_hash: str,
) -> dict:
    """
    Return a wbeditentity claim entry with the target qualifier removed.
    The rest of the claim (rank, other qualifiers, references) is preserved
    by serializing via Claim.toJSON() and then stripping the matching
    qualifier snak.
    """
    data = claim.toJSON()

    qualifiers = data.get("qualifiers", {})
    if qualifier_pid in qualifiers:
        qualifiers[qualifier_pid] = [
            q for q in qualifiers[qualifier_pid] if q.get("hash") != qualifier_hash
        ]
        if not qualifiers[qualifier_pid]:
            del qualifiers[qualifier_pid]
            if "qualifiers-order" in data:
                data["qualifiers-order"] = [
                    p for p in data["qualifiers-order"] if p != qualifier_pid
                ]

    return data


# ==== Diff merger ============================================================


def _find_claim(item: "pywikibot.ItemPage", claim_id: str) -> "pywikibot.Claim | None":
    """Return the pywikibot Claim object matching claim_id, or None."""
    for pid, claims in item.claims.items():
        for claim in claims:
            if claim.snak == claim_id:
                return claim
    return None


def build_payload(
    item: "pywikibot.ItemPage",
    diffs: list[dict],
) -> tuple[dict, list[str]]:
    """
    Merge all diffs into a single wbeditentity data dict.

    Returns (payload, descriptions) where descriptions is a list of
    human-readable strings for the edit summary.

    Mirrors mergeCleanupDiffs() from WikidataCleanup.js.
    """
    # claim_id → payload entry; built up incrementally so multiple diffs
    # on the same claim are merged into one entry.
    claim_payloads: dict[str, dict] = {}

    # lang → set of values to remove
    alias_removals: dict[str, set[str]] = {}

    descriptions: list[str] = []

    for diff in diffs:
        action = diff["action"]

        if action == ACTION_REMOVE_CLAIM:
            claim_id = diff["claim_id"]
            if claim_id in claim_payloads:
                # Already marked for removal — skip.
                continue
            claim = _find_claim(item, claim_id)
            if claim is None:
                continue
            claim_payloads[claim_id] = _build_remove_claim(claim)
            descriptions.append(f"remove {diff['pid']} self-citation")

        elif action == ACTION_REMOVE_QUALIFIER:
            claim_id = diff["claim_id"]
            qual_pid = diff["qualifier_pid"]
            qual_hash = diff["qualifier_hash"]

            if claim_id in claim_payloads and "remove" in claim_payloads[claim_id]:
                # Claim already being removed entirely — qualifier removal
                # is redundant.
                continue

            claim = _find_claim(item, claim_id)
            if claim is None:
                continue

            if claim_id not in claim_payloads:
                # First diff on this claim: start from full serialization.
                claim_payloads[claim_id] = claim.toJSON()

            # Strip the target qualifier from the already-accumulated entry.
            entry = claim_payloads[claim_id]
            qualifiers = entry.get("qualifiers", {})
            if qual_pid in qualifiers:
                qualifiers[qual_pid] = [
                    q for q in qualifiers[qual_pid] if q.get("hash") != qual_hash
                ]
                if not qualifiers[qual_pid]:
                    del qualifiers[qual_pid]
                    if "qualifiers-order" in entry:
                        entry["qualifiers-order"] = [
                            p for p in entry["qualifiers-order"] if p != qual_pid
                        ]

            descriptions.append(f"remove novalue {qual_pid} qualifier on {diff['pid']}")

        elif action == ACTION_REMOVE_ALIAS:
            lang = diff["lang"]
            value = diff["value"]
            alias_removals.setdefault(lang, set()).add(value)
            descriptions.append(f"remove alias [{lang}] {value!r} ({diff['reason']})")

        elif action == ACTION_DOWNGRADE_PREFERRED:
            claim_id = diff["claim_id"]

            if claim_id in claim_payloads and "remove" in claim_payloads[claim_id]:
                # Claim already being removed entirely — skip.
                continue

            claim = _find_claim(item, claim_id)
            if claim is None:
                continue

            if claim_id not in claim_payloads:
                claim_payloads[claim_id] = claim.toJSON()

            entry = claim_payloads[claim_id]
            entry["rank"] = "normal"

            # Strip P7452 (reason for preferred rank) qualifier if present.
            qual_pid = diff.get("removed_qualifier")
            if qual_pid:
                qualifiers = entry.get("qualifiers", {})
                if qual_pid in qualifiers:
                    del qualifiers[qual_pid]
                    if "qualifiers-order" in entry:
                        entry["qualifiers-order"] = [
                            p for p in entry["qualifiers-order"] if p != qual_pid
                        ]

            detector = diff.get("detector", "")
            reason = (
                "expired end time" if detector == "expired_preferred" else "redundant"
            )
            descriptions.append(f"downgrade preferred rank on {diff['pid']} ({reason})")

        elif action == ACTION_CLEAN_URL:
            claim_id = diff["claim_id"]

            if claim_id in claim_payloads and "remove" in claim_payloads[claim_id]:
                continue

            claim = _find_claim(item, claim_id)
            if claim is None:
                continue

            if claim_id not in claim_payloads:
                claim_payloads[claim_id] = claim.toJSON()

            entry = claim_payloads[claim_id]
            context = diff["context"]
            before = diff["before"]
            after = diff["after"]

            if context == "claim":
                # Top-level mainsnak URL value
                ms = entry.get("mainsnak", {})
                if ms.get("datavalue", {}).get("value") == before:
                    ms["datavalue"]["value"] = after
                    ms.pop("hash", None)

            elif context == "qualifier":
                # Qualifier snak identified by snak_pid + snak_hash
                q_pid = diff["snak_pid"]
                q_hash = diff["snak_hash"]
                for snak in entry.get("qualifiers", {}).get(q_pid, []):
                    if (
                        snak.get("hash") == q_hash
                        and snak.get("datavalue", {}).get("value") == before
                    ):
                        snak["datavalue"]["value"] = after
                        snak.pop("hash", None)
                        break

            else:
                # Reference snak (context == "reference")
                ref_hash = diff["ref_hash"]
                snak_pid = diff["snak_pid"]
                ref = next(
                    (
                        r
                        for r in entry.get("references", [])
                        if r.get("hash") == ref_hash
                    ),
                    None,
                )
                if ref:
                    for snak in ref.get("snaks", {}).get(snak_pid, []):
                        if snak.get("datavalue", {}).get("value") == before:
                            snak["datavalue"]["value"] = after
                            snak.pop("hash", None)
                            break

            descriptions.append(
                f"clean URL on {diff['pid']} {context}: " f"{before!r} → {after!r}"
            )

        elif action == ACTION_REMOVE_REFS:
            claim_id = diff["claim_id"]

            if claim_id in claim_payloads and "remove" in claim_payloads[claim_id]:
                continue

            claim = _find_claim(item, claim_id)
            if claim is None:
                continue

            if claim_id not in claim_payloads:
                claim_payloads[claim_id] = claim.toJSON()

            entry = claim_payloads[claim_id]
            ref_hash = diff["ref_hash"]
            # Remove last matching reference by hash, mirroring JS findLastIndex.
            refs = entry.get("references", [])
            for i in range(len(refs) - 1, -1, -1):
                if refs[i].get("hash") == ref_hash:
                    refs.pop(i)
                    break

            descriptions.append(f"remove duplicate reference on {diff['pid']}")

        elif action == ACTION_MERGE_CLAIM:
            from_id = diff["from_claim_id"]
            to_id = diff["to_claim_id"]

            # If the "from" claim is already being fully removed, skip.
            if from_id in claim_payloads and "remove" in claim_payloads[from_id]:
                continue

            from_claim = _find_claim(item, from_id)
            to_claim = _find_claim(item, to_id)
            if from_claim is None or to_claim is None:
                continue

            if from_id not in claim_payloads:
                claim_payloads[from_id] = from_claim.toJSON()
            if to_id not in claim_payloads:
                claim_payloads[to_id] = to_claim.toJSON()

            from_entry = claim_payloads[from_id]
            to_entry = claim_payloads[to_id]

            # Merge references: transfer any refs not already on the target.
            to_ref_hashes = {r.get("hash") for r in to_entry.get("references", [])}
            for ref in from_entry.get("references", []):
                if ref.get("hash") not in to_ref_hashes:
                    to_entry.setdefault("references", []).append(ref)
                    to_ref_hashes.add(ref.get("hash"))

            # Merge qualifiers: transfer snaks not already on the target.
            for q_pid, snaks in (from_entry.get("qualifiers") or {}).items():
                to_hashes = {
                    s.get("hash") for s in to_entry.get("qualifiers", {}).get(q_pid, [])
                }
                new_snaks = [s for s in snaks if s.get("hash") not in to_hashes]
                if new_snaks:
                    to_entry.setdefault("qualifiers", {}).setdefault(q_pid, []).extend(
                        new_snaks
                    )

            # Mark the "from" claim for removal.
            from_entry["remove"] = ""

            descriptions.append(f"merge duplicate date claim on {diff['pid']}")

    payload: dict = {}

    if claim_payloads:
        payload["claims"] = list(claim_payloads.values())

    if alias_removals:
        # Build per-language alias lists with the removed values stripped out.
        # pywikibot's AliasesDict.normalizeData accepts plain strings; we pass
        # the surviving alias values directly.
        aliases_payload: dict[str, list[str]] = {}
        for lang, removals in alias_removals.items():
            current = [
                a["value"] if isinstance(a, dict) else a
                for a in item.aliases.get(lang, [])
            ]
            aliases_payload[lang] = [v for v in current if v not in removals]
        payload["aliases"] = aliases_payload

    return payload, descriptions


# ==== Public entry point =====================================================


def apply_diffs(
    item: "pywikibot.ItemPage",
    diffs: list[dict],
    summary: str,
    dry_run: bool = False,
) -> bool:
    """
    Apply all diffs to the item in a single wbeditentity call.

    Returns True when an edit was made (or would have been made in dry-run
    mode), False when there was nothing to do.
    """
    import pywikibot

    if not diffs:
        return False

    payload, descriptions = build_payload(item, diffs)

    if not payload:
        return False

    # Log each change.
    for desc in descriptions:
        pywikibot.output(f"  [{item.id}] {desc}")

    if dry_run:
        pywikibot.output(f"  [{item.id}] DRY RUN — no edit submitted")
        return True

    item.editEntity(payload, summary=summary)
    return True
