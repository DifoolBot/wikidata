"""
labels.py

Single source of truth for the human-readable phrasing used by the bot.

Two surfaces consume this vocabulary:
  - bot.py builds the wikidata edit *summary* from DETECTOR_LABELS.
  - apply.py builds the per-change *log lines* from REMOVE_REFS_KINDS /
    REMOVE_CLAIM_TEMPLATES.

Keeping them together means adding or renaming a detector only touches one
file.  This module is pure data + string formatting — it imports nothing from
the package, so both bot.py and apply.py can use it without an import cycle.
"""

from __future__ import annotations

# Edit-summary labels for the non-reference-category detectors (detector id →
# phrase).  Values mirror the JS `summaryLabel` strings so the Python summary
# matches the tool's audit trail.  Reference-category removals (and
# duplicate-reference removal) are summarised compactly via REF_SUMMARY_KEYS
# instead — see summary_parts() — so they are intentionally absent here.
DETECTOR_LABELS = {
    "self_cite": "remove self-citation",
    "empty_end_time": "remove empty end time qualifiers",
    "alias_equals_label": "remove alias=label/mul",
    "redundant_preferred": "downgrade preferred ranks",
    "expired_preferred": "downgrade expired preferred ranks",
    "clean_urls": "clean URLs",
    "merge_same_date_claims": "merge same-date claims",
    "julian_gregorian_dates": "remove Julian/Gregorian duplicate dates",
    "low_precision_dates": "remove redundant dates",
    "obsolete_snaks": "remove obsolete snaks from references",
    "normalize_labels": "normalize text",
    "add_mul_label": "add mul label",
    "add_mul_alias": "add mul alias",
    "upgrade_precise_date": "upgrade precise date to preferred rank",
    "replace_wrong_property": "replace property",
    "split_reference_urls": "split multiple reference URLs",
    "merge_wiki_import_refs": "merge Wikimedia import references",
}

# ── Per-change log phrasing (used by apply.py) ───────────────────────────────

# ACTION_REMOVE_REFS: detector id → short "kind" word for the log line.
REMOVE_REFS_KINDS = {
    "dup_retrieved": "duplicate",
    "wikimedia": "imported-from-Wikimedia",
    "aggregator": "aggregator",
    "community": "community",
    "redundant": "redundant",
    "inferred": "inferred",
    "obsolete": "obsolete-ID",
    "self_stated_in": "tautological stated-in",
}
DEFAULT_REMOVE_REFS_KIND = "weak"

# ACTION_REMOVE_CLAIM: detector id → log-line template ({pid} is substituted).
REMOVE_CLAIM_TEMPLATES = {
    "self_cite": "remove {pid} self-citation",
    "julian_gregorian_dates": "remove duplicate Julian/Gregorian {pid} date",
    "low_precision_dates": "remove redundant low-precision {pid} date",
}
DEFAULT_REMOVE_CLAIM_TEMPLATE = "remove {pid} self-citation"


def remove_refs_description(detector: str, pid: str) -> str:
    """Log line for an ACTION_REMOVE_REFS diff."""
    kind = REMOVE_REFS_KINDS.get(detector, DEFAULT_REMOVE_REFS_KIND)
    return f"remove {kind} reference on {pid}"


def remove_claim_description(detector: str, pid: str) -> str:
    """Log line for an ACTION_REMOVE_CLAIM diff."""
    template = REMOVE_CLAIM_TEMPLATES.get(detector, DEFAULT_REMOVE_CLAIM_TEMPLATE)
    return template.format(pid=pid)


# ── Edit-summary assembly ────────────────────────────────────────────────────

# Detectors whose reference removals collapse into one combined summary part,
# keyed by the short category name used in that part.  Mirrors the JS
# buildSummary(), where every isRemoveRefCategory detector (the seven ref
# categories plus dup_retrieved) contributes its summaryLabel/categoryKey to a
# single "remove A+B+... refs" entry.
REF_SUMMARY_KEYS = {
    "dup_retrieved": "duplicate",
    "wikimedia": "wikimedia",
    "aggregator": "aggregator",
    "community": "community",
    "redundant": "redundant",
    "inferred": "inferred",
    "obsolete": "obsolete",
    "self_stated_in": "self_stated_in",
}

EDIT_SUMMARY_PREFIX = "Cleanup: "
# Wikidata/Wikibase truncates long edit summaries; keep the user-supplied part
# comfortably under the limit so the bot attribution link is never cut off.
EDIT_SUMMARY_MAX_LEN = 255


def summary_parts(detector_ids) -> list[str]:
    """Build the human-readable summary parts for the active detectors.

    Reference-category removals (and duplicate-reference removals) are collapsed
    into a single ``remove A+B+... refs`` part, mirroring the JS buildSummary().
    Every other detector contributes its DETECTOR_LABELS entry (falling back to
    the raw id).  The ref part, if present, comes first; the rest are sorted.
    """
    ref_keys = sorted(
        REF_SUMMARY_KEYS[d] for d in detector_ids if d in REF_SUMMARY_KEYS
    )
    others = sorted(
        DETECTOR_LABELS.get(d, d) for d in detector_ids if d not in REF_SUMMARY_KEYS
    )

    parts: list[str] = []
    if ref_keys:
        parts.append("remove " + "+".join(ref_keys) + " refs")
    parts.extend(others)
    return parts


def build_edit_summary(
    detector_ids,
    tool_page: str,
    max_len: int = EDIT_SUMMARY_MAX_LEN,
) -> str:
    """Assemble the edit summary, capping its length at ``max_len`` characters.

    Format: ``Cleanup: <part>; <part>; ... ([[<tool_page>|bot]])``, where the
    ref-category removals are collapsed into one ``remove A+B refs`` part (see
    :func:`summary_parts`).

    When the joined parts would overflow, whole parts are dropped from the end
    and a ``(+N more)`` marker is appended, so the result always stays within
    ``max_len`` and the trailing bot-attribution link is preserved.
    """
    parts = summary_parts(detector_ids)

    suffix = f" ([[{tool_page}|bot]])"
    budget = max_len - len(EDIT_SUMMARY_PREFIX) - len(suffix)

    full = "; ".join(parts)
    if len(full) <= budget:
        return f"{EDIT_SUMMARY_PREFIX}{full}{suffix}"

    # Keep as many whole parts as fit alongside the "(+N more)" marker.
    included: list[str] = []
    for idx, part in enumerate(parts):
        n_more = len(parts) - idx - 1  # parts remaining after this one
        marker = f"; (+{n_more} more)" if n_more else ""
        trial = "; ".join([*included, part]) + marker
        if len(trial) <= budget:
            included.append(part)
        else:
            break

    if not included:
        # Not even one part plus a marker fits; hard-truncate the whole thing.
        return f"{EDIT_SUMMARY_PREFIX}{full}{suffix}"[:max_len]

    dropped = len(parts) - len(included)
    actions = "; ".join(included)
    if dropped:
        actions += f"; (+{dropped} more)"
    return f"{EDIT_SUMMARY_PREFIX}{actions}{suffix}"
