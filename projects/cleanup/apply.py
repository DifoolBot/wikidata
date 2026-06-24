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
    ACTION_REMOVE_ALIAS,
    ACTION_REMOVE_CLAIM,
    ACTION_REMOVE_QUALIFIER,
    PID_END_TIME,
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

    # ── Assemble the payload ─────────────────────────────────────────────────
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
