"""
detectors.py

Pure detection logic for the WikidataCleanup bot.

Each detector takes a plain dict representation of a Wikidata item
(matching the wbgetentities JSON structure) and returns a list of diff
dicts describing what should be changed.  No pywikibot dependency;
no network calls.  This makes the detectors independently testable
with JSON fixtures that can also be used by the JS test suite.

Diff dict structure
-------------------
Every diff has at least:
  { "detector": str,   # which detector produced this diff
    "action":   str,   # what kind of change: see ACTION_* constants below
    ... }              # action-specific fields

ACTION_REMOVE_CLAIM:
  { "pid": str, "claim_id": str }

ACTION_REMOVE_QUALIFIER:
  { "pid": str, "claim_id": str, "qualifier_pid": str, "qualifier_hash": str }

ACTION_REMOVE_ALIAS:
  { "lang": str, "value": str, "reason": str }
"""

from typing import Callable
import re

# ==== Action constants =======================================================

ACTION_REMOVE_CLAIM = "remove_claim"
ACTION_REMOVE_QUALIFIER = "remove_qualifier"
ACTION_REMOVE_ALIAS = "remove_alias"

# ==== PIDs ===================================================================

PID_CITES_WORK = "P2860"
PID_END_TIME = "P582"

# ==== Text normalisation (mirrors JS normalizeText exactly) ==================


def normalize_text(s: str | None) -> str | None:
    """
    Normalise display text: replace fancy characters, collapse whitespace,
    strip leading/trailing commas or spaces.

    Mirrors normalizeText() from WikidataCleanup.js exactly:
      .replace(/\\u2010/g, "-")
      .replace(/\\u00A0/g, " ")
      .replace(/^[,\\s]+|[,\\s]+$/g, "")
      .replace(/\\s+/g, " ")
    """
    if not s:
        return s
    s = s.replace("\u2010", "-")  # Unicode hyphen → ASCII hyphen
    s = s.replace("\u00a0", " ")  # non-breaking space → space
    s = re.sub(r"^[,\s]+|[,\s]+$", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


# ==== Helpers ================================================================


def _claim_target_qid(claim: dict) -> str | None:
    """
    Return the QID of the item-type mainsnak value, or None.
    Works on the raw wbgetentities JSON structure.
    """
    try:
        return claim["mainsnak"]["datavalue"]["value"]["id"]
    except (KeyError, TypeError):
        return None


# ==== Detectors ==============================================================


def detect_self_cite(item: dict) -> list[dict]:
    """
    Detect P2860 (cites work) claims where the cited item is the
    item itself.

    Mirrors detectSelfCite() from WikidataCleanup.js:
      (entity.claims?.[PID_CITES_WORK] || [])
        .filter(claim => claim.mainsnak?.datavalue?.value?.id === currentQid)
    """
    qid = item.get("id")
    if not qid:
        return []

    diffs = []
    for claim in item.get("claims", {}).get(PID_CITES_WORK, []):
        if claim.get("rank") == "deprecated":
            continue
        if _claim_target_qid(claim) == qid:
            diffs.append(
                {
                    "detector": "self_cite",
                    "action": ACTION_REMOVE_CLAIM,
                    "pid": PID_CITES_WORK,
                    "claim_id": claim["id"],
                }
            )
    return diffs


def detect_empty_end_time(item: dict) -> list[dict]:
    """
    Detect P582 (end time) qualifiers set to novalue on any non-deprecated
    claim.

    Mirrors detectEmptyEndTime() from WikidataCleanup.js:
      for snak of c.qualifiers?.[PID_END_TIME] || []:
        if snak.snaktype === "novalue"
    """
    diffs = []
    for pid, claims in item.get("claims", {}).items():
        for claim in claims:
            if claim.get("rank") == "deprecated":
                continue
            for qualifier in claim.get("qualifiers", {}).get(PID_END_TIME, []):
                if qualifier.get("snaktype") == "novalue":
                    diffs.append(
                        {
                            "detector": "empty_end_time",
                            "action": ACTION_REMOVE_QUALIFIER,
                            "pid": pid,
                            "claim_id": claim["id"],
                            "qualifier_pid": PID_END_TIME,
                            "qualifier_hash": qualifier.get("hash"),
                        }
                    )
    return diffs


def detect_alias_equals_label(item: dict) -> list[dict]:
    """
    Detect aliases that are redundant because they duplicate:
      (a) the label in the same language         → reason "alias_equals_label"
      (b) the mul label                           → reason "alias_equals_mul_label"
      (c) a mul alias                             → reason "alias_equals_mul_alias"
      (d) another alias in the same language      → reason "duplicate"

    Mirrors detectRemoveDuplicateAliases() from WikidataCleanup.js exactly,
    including priority order: (a) → (b) → (c) → (d).
    """
    diffs = []

    labels = item.get("labels", {})
    aliases = item.get("aliases", {})

    # Build normalised set of mul aliases and the mul label.
    mul_alias_norms = {
        normalize_text(a["value"]) for a in aliases.get("mul", []) if a.get("value")
    }
    mul_label_value = labels.get("mul", {}).get("value", "")
    mul_label_norm = normalize_text(mul_label_value) if mul_label_value else None

    for lang, lang_aliases in aliases.items():
        if lang == "mul":
            continue

        label_norm = normalize_text(labels.get(lang, {}).get("value", ""))
        seen: set[str] = set()

        for alias_obj in lang_aliases:
            value = alias_obj.get("value", "")
            if not value:
                continue
            norm = normalize_text(value)
            if not norm:
                norm = ""

            # (a) Alias equals same-language label
            if norm == label_norm:
                diffs.append(
                    {
                        "detector": "alias_equals_label",
                        "action": ACTION_REMOVE_ALIAS,
                        "lang": lang,
                        "value": value,
                        "reason": "alias_equals_label",
                    }
                )
                continue

            # (b) Alias equals mul label
            if mul_label_norm and norm == mul_label_norm:
                diffs.append(
                    {
                        "detector": "alias_equals_label",
                        "action": ACTION_REMOVE_ALIAS,
                        "lang": lang,
                        "value": value,
                        "reason": "alias_equals_mul_label",
                    }
                )
                continue

            # (c) Alias equals a mul alias
            if norm in mul_alias_norms:
                diffs.append(
                    {
                        "detector": "alias_equals_label",
                        "action": ACTION_REMOVE_ALIAS,
                        "lang": lang,
                        "value": value,
                        "reason": "alias_equals_mul_alias",
                    }
                )
                continue

            # (d) Duplicate within same language
            if norm in seen:
                diffs.append(
                    {
                        "detector": "alias_equals_label",
                        "action": ACTION_REMOVE_ALIAS,
                        "lang": lang,
                        "value": value,
                        "reason": "duplicate",
                    }
                )
            else:
                seen.add(norm)

    return diffs


# ==== Detector registry ======================================================

#: Map detector id → detect function.
#: Used by bot.py to look up active detectors by name.
DETECTORS: dict[str, Callable] = {
    "self_cite": detect_self_cite,
    "empty_end_time": detect_empty_end_time,
    "alias_equals_label": detect_alias_equals_label,
}
