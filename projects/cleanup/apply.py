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

import re
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    import pywikibot

from cleanup.detectors import (
    ACTION_ADD_MUL_ALIAS,
    ACTION_CHANGE_PROPERTY,
    ACTION_CLEAN_URL,
    ACTION_DOWNGRADE_PREFERRED,
    ACTION_MERGE_CLAIM,
    ACTION_MERGE_WIKI_IMPORT_REFS,
    ACTION_NORMALIZE,
    ACTION_REMOVE_ALIAS,
    ACTION_REMOVE_CLAIM,
    ACTION_REMOVE_OBSOLETE_SNAKS,
    ACTION_REMOVE_QUALIFIER,
    ACTION_REMOVE_REFS,
    ACTION_SET_MUL_LABEL,
    ACTION_SPLIT_REFERENCE_URLS,
    ACTION_UPGRADE_PRECISE_DATE,
    PID_ARCHIVE_DATE,
    PID_ARCHIVE_URL,
    PID_END_TIME,
    PID_IMPORTED_FROM,
    PID_INFERRED,
    PID_REASON_FOR_PREFERRED_RANK,
    PID_REASON_FOR_DEPRECATED_RANK,
    PID_REFERENCE_URL,
    PID_RETRIEVED,
    PID_WIKIMEDIA_IMPORT_URL,
    QID_MOST_PRECISE,
    normalize_text,
    _is_archive_url,
    _is_wikimedia_url,
)
from cleanup.labels import remove_claim_description, remove_refs_description

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


def _replace_property_in_reference(
    ref: dict, old_prop: str, new_prop: str, snak_hash: str | None
) -> None:
    """
    Move snaks from old_prop to new_prop in a reference, matching by snak_hash.
    Mirrors replacePropertyInReference() from WikidataCleanup.js exactly.
    """
    if old_prop not in ref.get("snaks", {}):
        return

    order = ref.setdefault("snaks-order", [])
    old_idx = order.index(old_prop) if old_prop in order else -1
    new_idx = order.index(new_prop) if new_prop in order else -1

    to_move = []
    keep_old = []
    for snak in ref["snaks"].get(old_prop, []):
        if snak.get("hash") == snak_hash:
            snak = dict(snak)
            snak["property"] = new_prop
            snak.pop("hash", None)
            to_move.append(snak)
        else:
            keep_old.append(snak)

    if not to_move:
        return

    ref["snaks"].setdefault(new_prop, [])
    if old_idx != -1 and new_idx != -1 and old_idx < new_idx:
        ref["snaks"][new_prop] = to_move + ref["snaks"][new_prop]
    else:
        ref["snaks"][new_prop] = ref["snaks"][new_prop] + to_move

    if old_idx != -1:
        order[old_idx] = new_prop
    # Deduplicate order preserving first occurrence.
    seen: set[str] = set()
    ref["snaks-order"] = [p for p in order if not (p in seen or seen.add(p))]

    if keep_old:
        ref["snaks"][old_prop] = keep_old
    else:
        del ref["snaks"][old_prop]


def _split_reference(ref: dict) -> list[dict]:
    """
    Split a reference containing multiple URL/wiki-import snaks into a list
    of single-URL references.
    Mirrors the ACTION_SPLIT_REFERENCE_URLS apply step from JS exactly.
    """
    snaks = ref.get("snaks") or {}
    METADATA = {PID_RETRIEVED, PID_ARCHIVE_DATE}
    WIKI_PIDS = {PID_INFERRED, PID_IMPORTED_FROM, PID_WIKIMEDIA_IMPORT_URL}
    URL_PIDS = {PID_REFERENCE_URL, PID_ARCHIVE_URL}

    # Collect all non-metadata entries.
    all_entries = [
        {"pid": pid, "snak": snak}
        for pid in snaks
        if pid not in METADATA
        for snak in snaks[pid]
    ]
    if len(all_entries) <= 1:
        return [ref]

    retrieved_snaks = snaks.get(PID_RETRIEVED, [])
    latest_retrieved = (
        max(
            retrieved_snaks,
            key=lambda s: s.get("datavalue", {}).get("value", {}).get("time", ""),
            default=None,
        )
        if retrieved_snaks
        else None
    )

    def make_ref(
        pid: str,
        snak: dict,
        extra_pid: str | None = None,
        extra_snak: dict | None = None,
    ) -> dict:
        s: dict = {pid: [snak]}
        o: list = [pid]
        if extra_pid and extra_snak:
            s[extra_pid] = [extra_snak]
            o.append(extra_pid)
        if latest_retrieved:
            s[PID_RETRIEVED] = [latest_retrieved]
            o.append(PID_RETRIEVED)
        return {"snaks": s, "snaks-order": o}

    # Case A1: multiple P143 only
    if all(e["pid"] == PID_IMPORTED_FROM for e in all_entries):
        return [make_ref(PID_IMPORTED_FROM, e["snak"]) for e in all_entries]

    # Case A2: multiple P4656 only
    if all(e["pid"] == PID_WIKIMEDIA_IMPORT_URL for e in all_entries):
        return [make_ref(PID_WIKIMEDIA_IMPORT_URL, e["snak"]) for e in all_entries]

    # Case A3: multiple P143 + multiple P4656
    p143_entries = [e for e in all_entries if e["pid"] == PID_IMPORTED_FROM]
    p4656_entries = [e for e in all_entries if e["pid"] == PID_WIKIMEDIA_IMPORT_URL]
    if (
        p143_entries
        and p4656_entries
        and all(
            e["pid"] in {PID_IMPORTED_FROM, PID_WIKIMEDIA_IMPORT_URL}
            for e in all_entries
        )
    ):
        def lang_from_p4656(snak: dict) -> str | None:
            url = snak.get("datavalue", {}).get("value", "")
            try:
                m = re.match(r"^([a-z-]+)\.wikipedia\.org$", urlparse(url).hostname or "")
                return m.group(1) if m else None
            except Exception:
                return None

        used_p143: set[int] = set()
        new_refs: list[dict] = []
        for p4656_e in p4656_entries:
            lang = lang_from_p4656(p4656_e["snak"])
            matched = next(
                (i for i, e in enumerate(p143_entries) if i not in used_p143),
                None,
            )
            if matched is not None:
                used_p143.add(matched)
                new_refs.append(
                    make_ref(
                        PID_IMPORTED_FROM,
                        p143_entries[matched]["snak"],
                        PID_WIKIMEDIA_IMPORT_URL,
                        p4656_e["snak"],
                    )
                )
            else:
                new_refs.append(make_ref(PID_WIKIMEDIA_IMPORT_URL, p4656_e["snak"]))
        for i, e in enumerate(p143_entries):
            if i not in used_p143:
                new_refs.append(make_ref(PID_IMPORTED_FROM, e["snak"]))
        return new_refs

    # Case B: wiki header + URL/archive snaks
    wiki_entries = [e for e in all_entries if e["pid"] in WIKI_PIDS]
    url_entries = [e for e in all_entries if e["pid"] in URL_PIDS]
    if wiki_entries and url_entries:
        wiki_snaks: dict = {}
        wiki_order: list = []
        url_snaks: dict = {}
        url_order: list = []
        for e in wiki_entries:
            wiki_snaks.setdefault(e["pid"], []).append(e["snak"])
            if e["pid"] not in wiki_order:
                wiki_order.append(e["pid"])
        for e in url_entries:
            url_snaks.setdefault(e["pid"], []).append(e["snak"])
            if e["pid"] not in url_order:
                url_order.append(e["pid"])
        if latest_retrieved:
            wiki_snaks[PID_RETRIEVED] = retrieved_snaks
            wiki_order.append(PID_RETRIEVED)
        return [
            {"snaks": wiki_snaks, "snaks-order": wiki_order},
            {"snaks": url_snaks, "snaks-order": url_order},
        ]

    # Main case: multiple P854/P1065 URLs
    ar_urls = snaks.get(PID_ARCHIVE_URL, [])
    ar_dates = snaks.get(PID_ARCHIVE_DATE, [])
    if len(ar_urls) > 1 or len(ar_dates) > 1:
        return [ref]

    archive_entry: dict | None = None
    remaining: list[dict] = []
    for e in all_entries:
        val = e["snak"].get("datavalue", {}).get("value", "")
        is_arc = e["pid"] == PID_ARCHIVE_URL or (
            isinstance(val, str) and _is_archive_url(val)
        )
        if is_arc and archive_entry is None:
            archive_entry = e
        elif is_arc:
            return [ref]  # more than one archive URL
        else:
            remaining.append(e)

    new_refs = []
    for e in remaining:
        val = e["snak"].get("datavalue", {}).get("value", "")
        if isinstance(val, str):
            if _is_archive_url(val):
                mapped = PID_ARCHIVE_URL
            elif _is_wikimedia_url(val):
                mapped = PID_WIKIMEDIA_IMPORT_URL
            else:
                mapped = PID_REFERENCE_URL
        else:
            mapped = e["pid"]

        if mapped == PID_ARCHIVE_URL and archive_entry:
            continue  # archive snak goes in the archive ref

        s: dict = {mapped: [e["snak"]]}
        o: list = [mapped]
        if latest_retrieved and mapped != PID_ARCHIVE_URL:
            s[PID_RETRIEVED] = [latest_retrieved]
            o.append(PID_RETRIEVED)
        new_refs.append({"snaks": s, "snaks-order": o})

    if archive_entry:
        ar_s: dict = {PID_ARCHIVE_URL: [archive_entry["snak"]]}
        ar_o: list = [PID_ARCHIVE_URL]
        if ar_dates:
            ar_s[PID_ARCHIVE_DATE] = [ar_dates[0]]
            ar_o.append(PID_ARCHIVE_DATE)
        new_refs.append({"snaks": ar_s, "snaks-order": ar_o})
    elif ar_urls:
        ar_s = {PID_ARCHIVE_URL: [ar_urls[0]]}
        ar_o = [PID_ARCHIVE_URL]
        if ar_dates:
            ar_s[PID_ARCHIVE_DATE] = [ar_dates[0]]
            ar_o.append(PID_ARCHIVE_DATE)
        new_refs.append({"snaks": ar_s, "snaks-order": ar_o})

    return new_refs if new_refs else [ref]


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
    alias_removals: dict[str, set[str]] = {}
    alias_normalizations: dict[str, list] = {}  # lang → list of alias strings
    mul_alias_additions: list[dict] = []  # new mul alias objects
    labels_payload: dict[str, dict] = {}
    descriptions_payload: dict[str, dict] = {}
    descriptions: list[str] = []
    payload: dict = {}

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
            descriptions.append(
                remove_claim_description(diff.get("detector", ""), diff["pid"])
            )

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
            # add_mul_alias emits hidden ACTION_REMOVE_ALIAS diffs (no reason);
            # those are represented by the paired add-mul-alias summary instead.
            if not diff.get("_hidden"):
                reason = diff.get("reason")
                suffix = f" ({reason})" if reason else ""
                descriptions.append(f"remove alias [{lang}] {value!r}{suffix}")

        elif action == ACTION_DOWNGRADE_PREFERRED:
            claim_id = diff["claim_id"]

            if claim_id in claim_payloads and "remove" in claim_payloads[claim_id]:
                continue

            claim = _find_claim(item, claim_id)
            if claim is None:
                continue

            if claim_id not in claim_payloads:
                claim_payloads[claim_id] = claim.toJSON()

            entry = claim_payloads[claim_id]
            entry["rank"] = "normal"

            # When called from upgrade_precise_date the source claim is deprecated
            # (from_deprecated=True) and carries P2241 rather than P7452.
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
            if diff.get("from_deprecated"):
                reason = "deprecated→normal (paired with upgrade)"
            elif detector == "expired_preferred":
                reason = "expired end time"
            else:
                reason = "redundant"
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

            descriptions.append(
                remove_refs_description(diff.get("detector", ""), diff["pid"])
            )

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

        elif action == ACTION_REMOVE_OBSOLETE_SNAKS:
            claim_id = diff["claim_id"]

            if claim_id in claim_payloads and "remove" in claim_payloads[claim_id]:
                continue

            claim = _find_claim(item, claim_id)
            if claim is None:
                continue

            if claim_id not in claim_payloads:
                claim_payloads[claim_id] = claim.toJSON()

            entry = claim_payloads[claim_id]
            obsolete_pids = diff.get("obsolete_pids", [])
            ref_hash = diff["ref_hash"]

            ref = next(
                (r for r in entry.get("references", []) if r.get("hash") == ref_hash),
                None,
            )
            if ref:
                snaks = ref.get("snaks", {})
                for obs_pid in obsolete_pids:
                    snaks.pop(obs_pid, None)
                order = ref.get("snaks-order", [])
                ref["snaks-order"] = [p for p in order if p not in obsolete_pids]

            descriptions.append(
                f"remove obsolete snaks {obsolete_pids} from reference "
                f"on {diff['pid']}"
            )

        elif action == ACTION_NORMALIZE:
            field = diff["field"]
            lang = diff["lang"]
            before = diff["before"]
            after = diff["after"]
            if field == "label":
                labels_payload.setdefault(lang, {})["value"] = after
                descriptions.append(
                    f"normalize {field} [{lang}]: {before!r} → {after!r}"
                )
            elif field == "description":
                descriptions_payload.setdefault(lang, {})["value"] = after
                descriptions.append(
                    f"normalize {field} [{lang}]: {before!r} → {after!r}"
                )
            elif field == "alias":
                # Replace the matching alias value in-place.
                current = alias_normalizations.setdefault(
                    lang, list(item.aliases.get(lang, []))
                )
                for i, a in enumerate(current):
                    v = a["value"] if isinstance(a, dict) else a
                    if v == before:
                        current[i] = after
                        break
                descriptions.append(f"normalize alias [{lang}]: {before!r} → {after!r}")

        elif action == ACTION_SET_MUL_LABEL:
            labels_payload["mul"] = {"value": diff["value"]}
            descriptions.append(f"set mul label: {diff['value']!r}")

        elif action == ACTION_ADD_MUL_ALIAS:
            norm_new = normalize_text(diff["value"])
            existing = mul_alias_additions[:]
            if not any(
                normalize_text(a.get("value") if isinstance(a, dict) else a) == norm_new
                for a in existing
            ):
                mul_alias_additions.append({"language": "mul", "value": diff["value"]})
            descriptions.append(f"add mul alias: {diff['value']!r}")

        elif action == ACTION_UPGRADE_PRECISE_DATE:
            claim_id = diff["claim_id"]
            if claim_id in claim_payloads and "remove" in claim_payloads[claim_id]:
                continue
            claim = _find_claim(item, claim_id)
            if claim is None:
                continue
            if claim_id not in claim_payloads:
                claim_payloads[claim_id] = claim.toJSON()
            entry = claim_payloads[claim_id]
            entry["rank"] = "preferred"
            entry.setdefault("qualifiers", {})
            entry.setdefault("qualifiers-order", [])
            if PID_REASON_FOR_PREFERRED_RANK not in entry["qualifiers"]:
                entry["qualifiers"][PID_REASON_FOR_PREFERRED_RANK] = [
                    {
                        "snaktype": "value",
                        "property": PID_REASON_FOR_PREFERRED_RANK,
                        "datavalue": {
                            "value": {
                                "entity-type": "item",
                                "numeric-id": int(QID_MOST_PRECISE.replace("Q", "")),
                                "id": QID_MOST_PRECISE,
                            },
                            "type": "wikibase-entityid",
                        },
                    }
                ]
                if PID_REASON_FOR_PREFERRED_RANK not in entry["qualifiers-order"]:
                    entry["qualifiers-order"].insert(0, PID_REASON_FOR_PREFERRED_RANK)
            descriptions.append(f"upgrade precise date on {diff['pid']}")

        elif action == ACTION_CHANGE_PROPERTY:
            if diff.get("context") != "reference":
                continue
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
            ref = next(
                (r for r in entry.get("references", []) if r.get("hash") == ref_hash),
                None,
            )
            if ref:
                _replace_property_in_reference(
                    ref,
                    diff["old_property"],
                    diff["new_property"],
                    diff.get("snak_hash"),
                )
            descriptions.append(
                f"replace {diff['old_property']} → {diff['new_property']} "
                f"in reference on {diff['pid']}"
            )

        elif action == ACTION_SPLIT_REFERENCE_URLS:
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
            refs = entry.get("references", [])
            idx = next(
                (
                    i
                    for i in range(len(refs) - 1, -1, -1)
                    if refs[i].get("hash") == ref_hash
                ),
                -1,
            )
            if idx == -1:
                continue
            before_refs = refs[:idx]
            after_refs = refs[idx + 1 :]
            ref_to_split = refs[idx]
            new_refs = _split_reference(ref_to_split)
            entry["references"] = before_refs + new_refs + after_refs
            descriptions.append(
                f"split {diff.get('url_count', '?')} URLs in reference on {diff['pid']}"
            )

        elif action == ACTION_MERGE_WIKI_IMPORT_REFS:
            claim_id = diff["claim_id"]
            if claim_id in claim_payloads and "remove" in claim_payloads[claim_id]:
                continue
            claim = _find_claim(item, claim_id)
            if claim is None:
                continue
            if claim_id not in claim_payloads:
                claim_payloads[claim_id] = claim.toJSON()
            entry = claim_payloads[claim_id]
            refs = entry.get("references", [])
            p143_ref = next(
                (r for r in refs if r.get("hash") == diff["p143_ref_hash"]), None
            )
            if p143_ref:
                p143_ref.setdefault("snaks", {})[PID_WIKIMEDIA_IMPORT_URL] = [
                    {
                        "snaktype": "value",
                        "property": PID_WIKIMEDIA_IMPORT_URL,
                        "datavalue": {"value": diff["p4656_url"], "type": "string"},
                    }
                ]
                order = p143_ref.setdefault("snaks-order", [])
                if PID_WIKIMEDIA_IMPORT_URL not in order:
                    order.append(PID_WIKIMEDIA_IMPORT_URL)
            # Remove the P4656-only reference (last match).
            for i in range(len(refs) - 1, -1, -1):
                if refs[i].get("hash") == diff["p4656_ref_hash"]:
                    refs.pop(i)
                    break
            descriptions.append(f"merge P4656 ref into P143 ref on {diff['pid']}")

    if claim_payloads:
        payload["claims"] = list(claim_payloads.values())

    # ── Labels / descriptions / aliases ──────────────────────────────────────
    if labels_payload:
        payload["labels"] = labels_payload

    if descriptions_payload:
        payload["descriptions"] = descriptions_payload

    # Aliases: merge removals, normalizations, and mul additions.
    all_alias_langs = (
        set(alias_removals.keys())
        | set(alias_normalizations.keys())
        | ({"mul"} if mul_alias_additions else set())
    )
    if all_alias_langs:
        aliases_payload: dict[str, list] = {}
        for lang in all_alias_langs:
            removals = alias_removals.get(lang, set())
            if lang == "mul":
                current_mul = list(item.aliases.get("mul", []))
                norms_existing = {
                    normalize_text(a.get("value") if isinstance(a, dict) else a)
                    for a in current_mul
                }
                for new_a in mul_alias_additions:
                    if normalize_text(new_a.get("value")) not in norms_existing:
                        current_mul.append(new_a)
                aliases_payload["mul"] = [
                    a
                    for a in current_mul
                    if (a.get("value") if isinstance(a, dict) else a) not in removals
                ]
            elif lang in alias_normalizations:
                aliases_payload[lang] = [
                    a
                    for a in alias_normalizations[lang]
                    if (a.get("value") if isinstance(a, dict) else a) not in removals
                ]
            else:
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

    # Show the exact edit summary that will be submitted, with its length so
    # the Wikidata summary limit is easy to keep an eye on.
    pywikibot.output(f"  [{item.id}] summary ({len(summary)} chars): {summary}")

    if dry_run:
        pywikibot.output(f"  [{item.id}] DRY RUN — no edit submitted")
        return True

    item.editEntity(payload, summary=summary)
    return True
