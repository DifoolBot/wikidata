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

ACTION_DOWNGRADE_PREFERRED:
  { "pid": str, "claim_id": str, "removed_qualifier": str | None }
  removed_qualifier is PID_REASON_FOR_PREFERRED_RANK when the claim carries
  a P7452 qualifier that should also be stripped, otherwise None.

ACTION_CLEAN_URL:
  { "pid": str, "claim_id": str, "context": str,
    "snak_pid": str, "before": str, "after": str,
    "snak_hash": str | None, "ref_hash": str | None }
  context is one of "claim", "qualifier", "reference".
  snak_hash and ref_hash are only present for qualifier/reference contexts.

ACTION_REMOVE_REFS:
  { "pid": str, "claim_id": str, "ref_hash": str }

ACTION_MERGE_CLAIM:
  { "pid": str, "from_claim_id": str, "to_claim_id": str }
  The "from" claim is removed; its references and qualifiers are
  transferred to the "to" claim.

ACTION_REMOVE_OBSOLETE_SNAKS:
  { "pid": str, "claim_id": str, "ref_hash": str, "obsolete_pids": list[str] }
  Removes only the listed obsolete-PID snaks from a reference, leaving
  the rest of the reference intact.

ACTION_NORMALIZE:
  { "field": str, "lang": str, "before": str, "after": str }
  field is one of "label", "description", "alias".

ACTION_SET_MUL_LABEL:
  { "value": str, "matching_langs": str }

ACTION_ADD_MUL_ALIAS:
  { "value": str, "source_langs": list[str], "lang_count": int }
  Paired with hidden ACTION_REMOVE_ALIAS diffs for each source language.

ACTION_UPGRADE_PRECISE_DATE:
  { "pid": str, "claim_id": str, "depr_claim_id": str }
  Paired with a hidden ACTION_DOWNGRADE_PREFERRED diff on depr_claim_id.

ACTION_CHANGE_PROPERTY:
  { "pid": str, "claim_id": str, "ref_hash": str, "snak_hash": str,
    "old_property": str, "new_property": str }

ACTION_SPLIT_REFERENCE_URLS:
  { "pid": str, "claim_id": str, "ref_hash": str, "url_count": int }

ACTION_MERGE_WIKI_IMPORT_REFS:
  { "pid": str, "claim_id": str,
    "p4656_ref_hash": str, "p4656_url": str,
    "p143_ref_hash": str, "p143_qid": str }
"""

from typing import Callable
from datetime import datetime, timezone
import json
import math
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse, unquote

# ==== Action constants =======================================================

ACTION_REMOVE_CLAIM = "remove_claim"
ACTION_REMOVE_QUALIFIER = "remove_qualifier"
ACTION_REMOVE_ALIAS = "remove_alias"
ACTION_DOWNGRADE_PREFERRED = "downgrade_preferred"
ACTION_CLEAN_URL = "clean_url"
ACTION_REMOVE_REFS = "remove_refs"
ACTION_MERGE_CLAIM = "merge_claim"
ACTION_REMOVE_OBSOLETE_SNAKS = "remove_obsolete_snaks"
ACTION_NORMALIZE = "normalize"
ACTION_SET_MUL_LABEL = "set_mul_label"
ACTION_ADD_MUL_ALIAS = "add_mul_alias"
ACTION_UPGRADE_PRECISE_DATE = "upgrade_precise_date"
ACTION_CHANGE_PROPERTY = "change_property"
ACTION_SPLIT_REFERENCE_URLS = "split_reference_urls"
ACTION_MERGE_WIKI_IMPORT_REFS = "merge_wiki_import_refs"

# ==== PIDs and QIDs ==========================================================

PID_CITES_WORK = "P2860"
PID_END_TIME = "P582"
PID_REASON_FOR_PREFERRED_RANK = "P7452"
PID_REASON_FOR_DEPRECATED_RANK = "P2241"
PID_WIKIMEDIA_IMPORT_URL = "P4656"
PID_RETRIEVED = "P813"
PID_TITLE = "P1476"
PID_SUBJECT_NAMED_AS = "P1810"
PID_STATED_IN = "P248"
PID_IMPORTED_FROM = "P143"
PID_INFERRED = "P3452"
PID_DETERMINATION_METHOD = "P459"
PID_MATCHED_BY_IDENTIFIER_FROM = "P11797"
PID_BASED_ON_HEURISTIC = "P887"
PID_REFERENCE_URL = "P854"
PID_ARCHIVE_URL = "P1065"
PID_ARCHIVE_DATE = "P2960"
PID_DATE_OF_BIRTH = "P569"
PID_DATE_OF_DEATH = "P570"
PID_URL = "P2699"

QID_LESS_PRECISE = "Q42727519"  # item/value with less precision
QID_MOST_PRECISE = "Q71536040"  # most precise value (P7452 reason)

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


def _parse_wikibase_time(time_str: str) -> "datetime | None":
    """
    Parse a Wikibase time string into a Python datetime, or None on failure.

    Mirrors parseWikibaseTime() from WikidataCleanup.js:
      timeStr.replace(/^\\+/, "").replace(/-00/g, "-01")
    The -00 → -01 substitution handles month/day "unknown" values that
    are not valid ISO 8601 but common in Wikidata.
    """
    if not time_str:
        return None
    t = time_str.lstrip("+").replace("-00", "-01")
    try:
        return datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
    except ValueError:
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


def detect_redundant_preferred(item: dict) -> list[dict]:
    """
    Detect preferred-rank claims where the preference is redundant — that is,
    when every claim for the same property is either preferred or deprecated,
    making the distinction meaningless.  The preferred claims are downgraded
    to normal rank, and the P7452 qualifier is removed if present.

    Mirrors detectRedundantPreferred() from WikidataCleanup.js:
      const allPreferred    = ranks.every(r => r === "preferred")
      const onlyPrefOrDepr  = ranks.every(r => r === "preferred" || r === "deprecated")
      if (allPreferred || onlyPrefOrDepr) → downgrade each preferred claim
    """
    diffs = []
    for pid, claims in item.get("claims", {}).items():
        if not claims:
            continue
        ranks = [c.get("rank") for c in claims]
        all_preferred = all(r == "preferred" for r in ranks)
        only_pref_depr = all(r in ("preferred", "deprecated") for r in ranks)
        if not (all_preferred or only_pref_depr):
            continue
        for claim in claims:
            if claim.get("rank") != "preferred":
                continue
            has_p7452 = bool(
                claim.get("qualifiers", {}).get(PID_REASON_FOR_PREFERRED_RANK)
            )
            diffs.append(
                {
                    "detector": "redundant_preferred",
                    "action": ACTION_DOWNGRADE_PREFERRED,
                    "pid": pid,
                    "claim_id": claim["id"],
                    "removed_qualifier": (
                        PID_REASON_FOR_PREFERRED_RANK if has_p7452 else None
                    ),
                }
            )
    return diffs


def detect_expired_preferred(item: dict) -> list[dict]:
    """
    Detect preferred-rank claims that have a P582 (end time) qualifier whose
    date is in the past.  The claim is downgraded to normal rank and the
    P7452 qualifier is removed if present.

    Mirrors detectExpiredPreferred() from WikidataCleanup.js:
      if c.rank !== "preferred" → skip
      val = c.qualifiers?.[PID_END_TIME][0]?.datavalue?.value
      if parseWikibaseTime(val.time) < new Date() → downgrade
    """
    now = datetime.now(tz=timezone.utc)
    diffs = []

    for pid, claims in item.get("claims", {}).items():
        for claim in claims:
            if claim.get("rank") != "preferred":
                continue
            end_time_snaks = claim.get("qualifiers", {}).get(PID_END_TIME, [])
            if not end_time_snaks:
                continue
            # Mirror JS: only check the first P582 snak
            time_str = (
                end_time_snaks[0].get("datavalue", {}).get("value", {}).get("time")
            )
            if not time_str:
                continue
            end_date = _parse_wikibase_time(time_str)
            if end_date is None or end_date >= now:
                continue
            has_p7452 = bool(
                claim.get("qualifiers", {}).get(PID_REASON_FOR_PREFERRED_RANK)
            )
            diffs.append(
                {
                    "detector": "expired_preferred",
                    "action": ACTION_DOWNGRADE_PREFERRED,
                    "pid": pid,
                    "claim_id": claim["id"],
                    "removed_qualifier": (
                        PID_REASON_FOR_PREFERRED_RANK if has_p7452 else None
                    ),
                }
            )
    return diffs


# ==== Date helpers ===========================================================

# Calendar model URLs used in Wikibase time values.
CALENDAR_GREGORIAN = "http://www.wikidata.org/entity/Q1985727"
CALENDAR_JULIAN = "http://www.wikidata.org/entity/Q1985786"


def _get_date_properties(item: dict) -> list[str]:
    """
    Return all PIDs that have at least one time-datatype claim.
    Mirrors getDateProperties() from WikidataCleanup.js.
    """
    return [
        pid
        for pid, claims in item.get("claims", {}).items()
        if any(c.get("mainsnak", {}).get("datatype") == "time" for c in claims)
    ]


def _normalize_date_value(val: dict, precision: int) -> dict | None:
    """
    Normalize a WbTime value object to the given precision level.
    Mirrors normalizeDateValue() from WikidataCleanup.js exactly.
    """
    if not val:
        return None

    m = re.match(r"^([+-]\d+)-", val.get("time", ""))
    if not m:
        return None
    year = int(m.group(1))

    def fmt_year(y: int) -> str:
        return f"+{y}" if y >= 0 else str(y)

    ny = year
    if precision <= 5:
        pow_ = 10 ** (9 - precision)
        ny = round(year / pow_) * pow_
    elif precision == 6:
        yf = year / 1000
        ny = (math.floor(yf) if yf < 0 else math.ceil(yf)) * 1000
    elif precision == 7:
        yf = year / 100
        ny = (math.floor(yf) if yf < 0 else math.ceil(yf)) * 100
    elif precision == 8:
        ny = math.trunc(year / 10) * 10
    # precision 9 (year): ny = year unchanged

    # Downgrade precision when month/day are "00"
    parts = val["time"].split("-")
    # parts[0] = sign+year, parts[1] = month, parts[2] = day+time
    if precision == 11 and (parts[1] == "00" or parts[2][:2] == "00"):
        precision = 9
    if precision == 10 and parts[1] == "00":
        precision = 9

    calendarmodel = val.get("calendarmodel", CALENDAR_GREGORIAN)

    if precision == 11:
        return {
            "time": f"{fmt_year(ny)}-{parts[1]}-{parts[2][:2]}",
            "precision": precision,
            "calendarmodel": calendarmodel,
        }
    if precision == 10:
        return {
            "time": f"{fmt_year(ny)}-{parts[1]}",
            "precision": precision,
            "calendarmodel": calendarmodel,
        }
    return {
        "time": f"{fmt_year(ny)}-01-01T00:00:00Z",
        "precision": precision,
        "calendarmodel": calendarmodel,
    }


def _has_same_normalized_date(
    c1: dict,
    c2: dict,
    at_lowest_precision: bool,
    ignore_calendarmodel: bool,
) -> bool:
    """
    Compare two date claims at the lowest common precision.
    Mirrors has_same_normalized_date() from WikidataCleanup.js exactly.
    """
    v1 = c1.get("mainsnak", {}).get("datavalue", {}).get("value")
    v2 = c2.get("mainsnak", {}).get("datavalue", {}).get("value")
    if not v1 and not v2:
        return True
    if not v1 or not v2:
        return False

    if at_lowest_precision:
        low_prec = min(v1["precision"], v2["precision"])
        if low_prec <= 9 or v1["precision"] != low_prec or v2["precision"] != low_prec:
            n1 = _normalize_date_value(v1, low_prec)
            n2 = _normalize_date_value(v2, low_prec)
            if n1 is None or n2 is None:
                return False
            # Mirror JS: n1.calendarmodel = n2.calendarmodel
            n1 = {**n1, "calendarmodel": n2["calendarmodel"]}
        else:
            n1 = _normalize_date_value(v1, low_prec)
            n2 = _normalize_date_value(v2, low_prec)
            if n1 is None or n2 is None:
                return False
    else:
        n1 = _normalize_date_value(v1, v1["precision"])
        n2 = _normalize_date_value(v2, v2["precision"])
        if n1 is None or n2 is None:
            return False

    return (
        n1["time"] == n2["time"]
        and n1["precision"] == n2["precision"]
        and (ignore_calendarmodel or n1["calendarmodel"] == n2["calendarmodel"])
    )


def _qualifiers_equal_except_p31(claim_a: dict, claim_b: dict) -> bool:
    """
    Compare qualifier dicts, ignoring P31 (instance of).
    Mirrors qualifiersEqualExceptP31() from WikidataCleanup.js.
    """
    qa = {k: v for k, v in (claim_a.get("qualifiers") or {}).items() if k != "P31"}
    qb = {k: v for k, v in (claim_b.get("qualifiers") or {}).items() if k != "P31"}
    return json.dumps(qa, sort_keys=True) == json.dumps(qb, sort_keys=True)


def _rank_order(rank: str) -> int:
    """Mirrors rankOrder() from WikidataCleanup.js."""
    return {"preferred": 2, "normal": 1, "deprecated": 0}.get(rank, -1)


def _choose_merge_target(claims: list[dict]) -> dict:
    """
    Pick the claim to keep when merging same-date duplicates.
    Mirrors chooseMergeTarget() without preferDeprecated (not needed here).
    """
    pool = [c for c in claims if c.get("rank") != "deprecated"] or claims

    def score(c: dict) -> tuple:
        return (
            _rank_order(c.get("rank", "normal")),
            len(c.get("references", [])),
            sum(len(v) for v in (c.get("qualifiers") or {}).values()),
        )

    # Higher score wins; ties broken by claim id descending (mirrors JS)
    return max(pool, key=lambda c: (score(c), c.get("id", "")))


def _parse_retrieved_timestamp(ref: dict) -> float:
    """
    Return the P813 (retrieved) timestamp as a float (seconds since epoch),
    or -inf when absent.  Mirrors parseRetrievedTimestamp() from JS.
    """
    try:
        snak = (ref.get("snaks", {}).get(PID_RETRIEVED) or [None])[0]
        if not snak:
            return float("-inf")
        time_str = snak.get("datavalue", {}).get("value", {}).get("time")
        dt = _parse_wikibase_time(time_str)
        return dt.timestamp() if dt else float("-inf")
    except Exception:
        return float("-inf")


def _build_ref_field_map(ref: dict) -> dict[str, list[str]]:
    """
    Build a canonical map of PID → sorted list of serialized values,
    ignoring metadata-only PIDs.  Mirrors buildFieldMap() from JS.
    """
    IGNORE = {PID_RETRIEVED, PID_TITLE, PID_SUBJECT_NAMED_AS}
    result: dict[str, list[str]] = {}
    for pid, snaks in (ref.get("snaks") or {}).items():
        if pid in IGNORE:
            continue
        vals = sorted(
            json.dumps(s.get("datavalue", {}).get("value"), sort_keys=True)
            for s in snaks
        )
        if vals:
            result[pid] = vals
    return result


def _is_subset(map_a: dict, map_b: dict) -> bool:
    """Return True when every entry in map_a is present in map_b."""
    for pid, vals in map_a.items():
        if pid not in map_b:
            return False
        set_b = set(map_b[pid])
        if not all(v in set_b for v in vals):
            return False
    return True


# ==== Detectors: date and reference ==========================================


def detect_duplicate_refs(item: dict) -> list[dict]:
    """
    Detect and remove duplicate references on the same statement.

    A reference is considered a duplicate when its field map (ignoring
    P813/P1476/P1810) is a subset of another reference's field map and its
    P813 timestamp is older or equal.  The newer/superset reference is kept;
    the older/subset reference is removed.

    Mirrors detectDuplicateRefs() from WikidataCleanup.js exactly.
    """
    diffs = []

    for pid, claims in item.get("claims", {}).items():
        for claim in claims:
            refs = claim.get("references", [])
            if len(refs) < 2:
                continue

            # Build metadata once per reference.
            meta: dict[str, dict] = {}
            for ref in refs:
                h = ref.get("hash", "")
                meta[h] = {
                    "map": _build_ref_field_map(ref),
                    "ts": _parse_retrieved_timestamp(ref),
                    "prop_count": sum(
                        1
                        for p in (ref.get("snaks") or {})
                        if p not in {PID_RETRIEVED, PID_TITLE, PID_SUBJECT_NAMED_AS}
                    ),
                }

            # Sort: newest first, most props first, superset before subset.
            def sort_key(ref: dict):
                h = ref.get("hash", "")
                m = meta[h]
                return (-m["ts"], -m["prop_count"], h)

            sorted_refs = sorted(refs, key=sort_key)

            groups: list[dict] = []
            for ref in sorted_refs:
                h = ref.get("hash", "")
                m = meta[h]
                if not m["prop_count"]:
                    continue
                anchor = next(
                    (
                        g
                        for g in groups
                        if _is_subset(
                            m["map"], meta[g["anchor"].get("hash", "")]["map"]
                        )
                        and m["ts"] <= meta[g["anchor"].get("hash", "")]["ts"]
                    ),
                    None,
                )
                if anchor:
                    anchor["members"].append(ref)
                else:
                    groups.append({"anchor": ref, "members": []})

            for group in groups:
                for ref in group["members"]:
                    diffs.append(
                        {
                            "detector": "dup_retrieved",
                            "action": ACTION_REMOVE_REFS,
                            "pid": pid,
                            "claim_id": claim["id"],
                            "ref_hash": ref.get("hash"),
                            "removed_keys": list((ref.get("snaks") or {}).keys()),
                        }
                    )

    return diffs


def detect_merge_same_date_claims(item: dict) -> list[dict]:
    """
    Detect date claims that represent the same value after normalisation and
    can be merged (same rank, same qualifiers except P31:Q26961029).

    Mirrors detectMergeSameDateClaims() from WikidataCleanup.js exactly.
    """
    diffs = []

    for pid in _get_date_properties(item):
        claims = item.get("claims", {}).get(pid, [])
        visited: set[str] = set()

        for i, base in enumerate(claims):
            if base["id"] in visited:
                continue
            group = [base]
            visited.add(base["id"])

            for cand in claims[i + 1 :]:
                if cand["id"] in visited:
                    continue
                if _has_same_normalized_date(
                    base, cand, at_lowest_precision=False, ignore_calendarmodel=False
                ):
                    group.append(cand)
                    visited.add(cand["id"])

            if len(group) < 2:
                continue

            # Sub-group by rank + qualifiers (ignoring P31:Q26961029).
            subgroups: list[dict] = []
            for claim in group:
                sg = next(
                    (
                        s
                        for s in subgroups
                        if s["rank"] == claim.get("rank")
                        and _qualifiers_equal_except_p31(s["claims"][0], claim)
                    ),
                    None,
                )
                if sg:
                    sg["claims"].append(claim)
                else:
                    subgroups.append({"rank": claim.get("rank"), "claims": [claim]})

            for sg in subgroups:
                sg_claims = sg["claims"]
                if len(sg_claims) < 2:
                    continue
                target = _choose_merge_target(sg_claims)
                for claim in sg_claims:
                    if claim["id"] != target["id"]:
                        diffs.append(
                            {
                                "detector": "merge_same_date_claims",
                                "action": ACTION_MERGE_CLAIM,
                                "pid": pid,
                                "from_claim_id": claim["id"],
                                "to_claim_id": target["id"],
                            }
                        )

    return diffs


def detect_julian_gregorian_dates(item: dict) -> list[dict]:
    """
    Remove unreferenced Julian/Gregorian duplicate date claims when the same
    date is present in the other calendar model with at least one reference.

    Mirrors detectJulianGregorianDuplicateDates() from WikidataCleanup.js.
    """
    diffs = []

    for pid in _get_date_properties(item):
        claims = item.get("claims", {}).get(pid, [])
        unref = [c for c in claims if not c.get("references")]
        with_refs = [c for c in claims if c.get("references")]

        for a in unref:
            a_val = a.get("mainsnak", {}).get("datavalue", {}).get("value")
            if not a_val:
                continue
            for b in with_refs:
                b_val = b.get("mainsnak", {}).get("datavalue", {}).get("value")
                if not b_val:
                    continue
                if a_val.get("calendarmodel") != b_val.get(
                    "calendarmodel"
                ) and _has_same_normalized_date(
                    a, b, at_lowest_precision=False, ignore_calendarmodel=True
                ):
                    diffs.append(
                        {
                            "detector": "julian_gregorian_dates",
                            "action": ACTION_REMOVE_CLAIM,
                            "pid": pid,
                            "claim_id": a["id"],
                            "keep_claim_id": b["id"],
                        }
                    )

    return diffs


# ==== Source category rules (black box) =====================================


class SourceCategoryRules:
    """
    Holds the parsed reference-source-category rules fetched from the wiki
    page User:Difool/reference-source-categories.

    This is a black box for the classifier — the bot fetches and constructs
    it; the classifier reads from it only through its interface.

    TODO: implement from_wiki_text(wikitext) to parse the live wiki page.
    For now, construct with empty rules (no aggregator/community/redundant
    classifications) so the classifier still works for wikimedia/inferred/etc.

    Fields:
      aggregator_pids  : set of PIDs classified as aggregator sources
      community_pids   : set of PIDs classified as community sources
      redundancy_pairs : list of (weak_pid, strong_pid) tuples
      stated_in        : dict mapping PID → { preferred, allowed: set, not_allowed: set }
    """

    def __init__(
        self,
        aggregator_pids: set[str] | None = None,
        community_pids: set[str] | None = None,
        redundancy_pairs: list[tuple[str, str]] | None = None,
        stated_in: dict | None = None,
        obsolete_pids: set[str] | None = None,
    ) -> None:
        self.aggregator_pids = aggregator_pids or set()
        self.community_pids = community_pids or set()
        self.redundancy_pairs = redundancy_pairs or []
        self.stated_in = stated_in or {}
        self.obsolete_pids = obsolete_pids or set()

    def get_property_stated_in(self, pid: str) -> dict | None:
        return self.stated_in.get(pid)

    def is_obsolete(self, pid: str) -> bool:
        return pid in self.obsolete_pids

    def is_aggregator(self, pid: str) -> bool:
        return pid in self.aggregator_pids

    def is_community(self, pid: str) -> bool:
        return pid in self.community_pids


# ==== Reference classification ===============================================

# Priority order: lower index = higher priority (stronger "weak" signal).
# Mirrors WEAK_CATEGORY_PRIORITY from WikidataCleanup.js exactly.
WEAK_CATEGORY_PRIORITY = [
    "external-id:error",
    "invalid",
    "obsolete",
    "aggregator",
    "community",
    "redundant",
    "inferred",
    "inferred+",
    "wikimedia+",
    "wikimedia_no_sitelinks",
    "wikimedia",
    "self_stated_in",
]

# PIDs for which Wikimedia-import references are always removed regardless
# of level (category/Commons-link properties).
# Mirrors ALWAYS_REMOVE_WIKIMEDIA_PIDS from WikidataCleanup.js exactly.
ALWAYS_REMOVE_WIKIMEDIA_PIDS: frozenset[str] = frozenset(
    [
        "P301",
        "P373",
        "P910",
        "P971",
        "P1200",
        "P1464",
        "P1465",
        "P1740",
        "P1753",
        "P1754",
        "P1791",
        "P1792",
        "P2033",
        "P2517",
        "P2875",
        "P3709",
        "P3713",
        "P3734",
        "P3876",
        "P4195",
        "P4224",
        "P4329",
        "P5996",
        "P6112",
        "P6186",
        "P6365",
        "P7084",
        "P7561",
        "P7782",
        "P7861",
        "P7867",
        "P8464",
        "P10280",
        "P12686",
        "P12687",
        "P935",
        "P1472",
        "P1612",
    ]
)


def _is_qid(s: str) -> bool:
    return bool(re.match(r"^Q\d+$", s or ""))


def _highest_level_category(codes: list[str | None]) -> str | None:
    """
    Given a list of category codes (None = strong), return None if any code
    is None, otherwise return the highest-priority weak code.
    Mirrors highestLevelCategory() from WikidataCleanup.js exactly.
    """
    if not codes:
        return None
    if any(c is None for c in codes):
        return None
    best = None
    for code in codes:
        if best is None:
            best = code
        else:
            best_idx = (
                WEAK_CATEGORY_PRIORITY.index(best)
                if best in WEAK_CATEGORY_PRIORITY
                else -1
            )
            code_idx = (
                WEAK_CATEGORY_PRIORITY.index(code)
                if code in WEAK_CATEGORY_PRIORITY
                else -1
            )
            if code_idx != -1 and (best_idx == -1 or code_idx < best_idx):
                best = code
    return best


def _is_splittable_reference(ref: dict) -> tuple[bool, int, str | None]:
    """
    Return (splittable, url_count, split_mode).
    Mirrors isSplittableReference() from WikidataCleanup.js exactly.
    split_mode: "multiP143", "multiP4656", "multiP143P4656",
                "wikiHeaderUrl", "multiUrl", or None.
    """
    snaks = ref.get("snaks") or {}
    pids = list(snaks.keys())
    METADATA = {PID_RETRIEVED, PID_ARCHIVE_DATE}
    WIKI_PIDS = {PID_INFERRED, PID_IMPORTED_FROM, PID_WIKIMEDIA_IMPORT_URL}
    URL_PIDS = {PID_REFERENCE_URL, PID_ARCHIVE_URL}
    ALLOWED = {
        PID_REFERENCE_URL,
        PID_RETRIEVED,
        PID_ARCHIVE_URL,
        PID_ARCHIVE_DATE,
        PID_IMPORTED_FROM,
        PID_WIKIMEDIA_IMPORT_URL,
    }

    if PID_REFERENCE_URL not in pids:
        # Case A1
        if PID_IMPORTED_FROM in pids and all(
            p == PID_IMPORTED_FROM or p in METADATA for p in pids
        ):
            c = len(snaks.get(PID_IMPORTED_FROM, []))
            if c >= 2:
                return (True, c, "multiP143")
        # Case A2
        if PID_WIKIMEDIA_IMPORT_URL in pids and all(
            p == PID_WIKIMEDIA_IMPORT_URL or p in METADATA for p in pids
        ):
            c = len(snaks.get(PID_WIKIMEDIA_IMPORT_URL, []))
            if c >= 2:
                return (True, c, "multiP4656")
        # Case A3
        if (
            PID_IMPORTED_FROM in pids
            and PID_WIKIMEDIA_IMPORT_URL in pids
            and all(
                p in {PID_IMPORTED_FROM, PID_WIKIMEDIA_IMPORT_URL} or p in METADATA
                for p in pids
            )
        ):
            c143 = len(snaks.get(PID_IMPORTED_FROM, []))
            c4656 = len(snaks.get(PID_WIKIMEDIA_IMPORT_URL, []))
            if c143 >= 2 and c4656 >= 2:
                return (True, c143 + c4656, "multiP143P4656")

    # Case B: wikipedia header + URL/archive pids
    has_wiki = bool(set(pids) & {PID_IMPORTED_FROM, PID_WIKIMEDIA_IMPORT_URL})
    has_url = bool(set(pids) & URL_PIDS)
    if has_wiki and has_url:
        all_ok = all(p in WIKI_PIDS or p in URL_PIDS or p in METADATA for p in pids)
        order = [p for p in (ref.get("snaks-order") or pids) if p not in METADATA]
        wi_idxs = [i for i, p in enumerate(order) if p in WIKI_PIDS]
        ur_idxs = [i for i, p in enumerate(order) if p in URL_PIDS]
        correct = max(wi_idxs, default=-1) < min(ur_idxs, default=float("inf"))
        uc = sum(len(snaks.get(p, [])) for p in URL_PIDS if p in pids)
        if all_ok and correct and uc >= 1:
            return (True, uc + 1, "wikiHeaderUrl")

    # Main case: multiple P854/P1065 URLs
    if PID_REFERENCE_URL not in pids:
        return (False, 0, None)
    if not all(p in ALLOWED for p in pids):
        return (False, 0, None)

    archive_count = wikimedia_count = url_count = 0
    for p in pids:
        if p in METADATA:
            continue
        for snak in snaks.get(p, []):
            if snak.get("datatype") == "url":
                v = snak.get("datavalue", {}).get("value", "")
                if not isinstance(v, str):
                    continue
                if p == PID_ARCHIVE_URL or _is_archive_url(v):
                    archive_count += 1
                elif _is_wikimedia_url(v):
                    wikimedia_count += 1
                else:
                    url_count += 1

    if archive_count > 1:
        return (False, 0, None)
    if len(snaks.get(PID_ARCHIVE_DATE, [])) > 1:
        return (False, 0, None)
    total = archive_count + wikimedia_count + url_count
    if total <= 1:
        return (False, 0, None)
    return (True, total, "multiUrl")


def _is_wikimedia_url(url: str) -> bool:
    """Check if a URL is a Wikimedia project URL."""
    try:
        host = urlparse(url).hostname or ""
        return bool(
            re.search(
                r"(mediawiki|wik(i(books|data|(m|p)edia|functions|news|"
                r"quote|source|species|versity|voyage)|tionary)|wmflabs)\.org$",
                host,
            )
        )
    except Exception:
        return False


def _is_archive_url(url: str) -> bool:
    """Check if a URL points to a web archive service."""
    ARCHIVE_DOMAINS = {"web.archive.org", "archive.is", "wayback.archive-it.org"}
    try:
        host = urlparse(url).hostname or ""
        return any(host == d or host.endswith("." + d) for d in ARCHIVE_DOMAINS)
    except Exception:
        return False


class ReferenceClassifier:
    """
    Classifies references into weak categories, mirroring the JS
    determineSourceCategory / getReferenceLevel pipeline.

    Constructed once by bot.py and passed into detect_ref_categories() and
    detect_low_precision_dates().  All external data is accessed through
    SourceCategoryRules.
    """

    def __init__(self, rules: "SourceCategoryRules") -> None:
        self.rules = rules

    def _classify_ext_id_snak(
        self, pid: str, value: str, has_retrieved: bool
    ) -> str | None:
        if not has_retrieved:
            if self.rules.is_obsolete(pid):
                return "obsolete"
            if self.rules.is_aggregator(pid):
                return "aggregator"
            if self.rules.is_community(pid):
                return "community"
        else:
            if self.rules.is_aggregator(pid):
                return "aggregator"
            if self.rules.is_community(pid):
                return "community"
        return None

    def _classify_stated_in_qid(self, qid: str) -> str | None:
        for agg_pid in self.rules.aggregator_pids:
            prefs = self.rules.get_property_stated_in(agg_pid)
            if prefs and qid in prefs.get("allowed", set()):
                return "aggregator"
        for com_pid in self.rules.community_pids:
            prefs = self.rules.get_property_stated_in(com_pid)
            if prefs and qid in prefs.get("allowed", set()):
                return "community"
        return None

    def _is_redundant_in_context(
        self,
        pid: str | None,
        stated_in_qids: list[str],
        all_refs: list[dict],
        ref: dict,
    ) -> bool:
        for weak_pid, strong_pid in self.rules.redundancy_pairs:
            weak_prefs = self.rules.get_property_stated_in(weak_pid)
            weak_qids = weak_prefs.get("allowed", set()) if weak_prefs else set()
            is_weak = pid == weak_pid or any(q in weak_qids for q in stated_in_qids)
            if not is_weak:
                continue
            strong_prefs = self.rules.get_property_stated_in(strong_pid)
            strong_qids = strong_prefs.get("allowed", set()) if strong_prefs else set()
            strong_present = any(
                r is not ref
                and (
                    strong_pid in (r.get("snaks") or {})
                    or any(
                        s.get("datavalue", {}).get("value", {}).get("id", "")
                        in strong_qids
                        for s in (r.get("snaks") or {}).get(PID_STATED_IN, [])
                    )
                )
                for r in all_refs
            )
            if strong_present:
                return True
        return False

    def determine_source_category(
        self,
        item: dict,
        ref: dict,
        all_refs: list[dict],
        claim: dict | None = None,
    ) -> str | None:
        snaks = ref.get("snaks") or {}
        pids = list(snaks.keys())
        METADATA = {PID_RETRIEVED, PID_TITLE, PID_SUBJECT_NAMED_AS}

        if pids and all(p in METADATA for p in pids):
            return "ignore"

        has_retrieved = PID_RETRIEVED in pids
        WIKIMEDIA_ALLOWED = {
            PID_INFERRED,
            PID_WIKIMEDIA_IMPORT_URL,
            PID_IMPORTED_FROM,
            PID_RETRIEVED,
        }

        if PID_IMPORTED_FROM in pids or PID_WIKIMEDIA_IMPORT_URL in pids:
            if PID_INFERRED in pids and all(p in WIKIMEDIA_ALLOWED for p in pids):
                return "wikimedia"
            if PID_DETERMINATION_METHOD in pids or PID_INFERRED in pids:
                return "wikimedia+"
            return "wikimedia"

        if PID_MATCHED_BY_IDENTIFIER_FROM in pids:
            return "inferred+"
        if (PID_INFERRED in pids or PID_BASED_ON_HEURISTIC in pids) and len(pids) == 1:
            return "inferred"

        if (
            not has_retrieved
            and claim is not None
            and claim.get("mainsnak", {}).get("datatype") == "external-id"
            and PID_STATED_IN in pids
            and all(p in {PID_STATED_IN, PID_TITLE, PID_SUBJECT_NAMED_AS} for p in pids)
        ):
            claim_pid = claim.get("mainsnak", {}).get("property")
            prefs = self.rules.get_property_stated_in(claim_pid or "")
            stated_in_qids = [
                s.get("datavalue", {}).get("value", {}).get("id")
                for s in snaks.get(PID_STATED_IN, [])
                if _is_qid(s.get("datavalue", {}).get("value", {}).get("id", ""))
            ]
            if (
                prefs
                and prefs.get("allowed")
                and any(q in prefs["allowed"] for q in stated_in_qids)
            ):
                return "self_stated_in"

        ext_id_snaks = [
            {"pid": pid, "value": snak.get("datavalue", {}).get("value")}
            for pid in pids
            for snak in snaks.get(pid, [])
            if snak.get("datatype") == "external-id"
            and snak.get("datavalue", {}).get("value")
        ]

        if ext_id_snaks:
            codes = [
                self._classify_ext_id_snak(s["pid"], s["value"], has_retrieved)
                for s in ext_id_snaks
            ]
            for s in ext_id_snaks:
                if self._is_redundant_in_context(s["pid"], [], all_refs, ref):
                    codes.append("redundant")
                    break
            return _highest_level_category(codes)
        else:
            stated_in_qids = [
                s.get("datavalue", {}).get("value", {}).get("id")
                for s in snaks.get(PID_STATED_IN, [])
                if _is_qid(s.get("datavalue", {}).get("value", {}).get("id", ""))
            ]
            if not stated_in_qids:
                return None
            codes = [self._classify_stated_in_qid(q) for q in stated_in_qids]
            if self._is_redundant_in_context(None, stated_in_qids, all_refs, ref):
                codes.append("redundant")
            return _highest_level_category(codes)

    def get_reference_level(
        self,
        item: dict,
        ref: dict,
        all_refs: list[dict],
        claim: dict | None = None,
    ) -> int:
        cat = self.determine_source_category(item, ref, all_refs, claim)
        if cat in {"wikimedia", "wikimedia_no_sitelinks", "ignore", "self_stated_in"}:
            return 0
        if cat in {
            "aggregator",
            "community",
            "inferred",
            "inferred+",
            "invalid",
            "obsolete",
            "redundant",
            "wikimedia+",
            "external-id:error",
        }:
            return 1
        return 2


def detect_normalize_labels(item: dict) -> list[dict]:
    """
    Detect labels, descriptions and aliases that need Unicode normalisation.
    Mirrors detectNormalizeLabels() exactly.
    For descriptions, also strips trailing semicolons/whitespace.
    """
    diffs = []

    for lang, entry in (item.get("labels") or {}).items():
        before = entry.get("value", "")
        after = normalize_text(before)
        if after and after != before:
            diffs.append(
                {
                    "detector": "normalize_labels",
                    "action": ACTION_NORMALIZE,
                    "field": "label",
                    "lang": lang,
                    "before": before,
                    "after": after,
                }
            )

    for lang, entry in (item.get("descriptions") or {}).items():
        before = entry.get("value", "")
        after = normalize_text(before)
        if after:
            after = re.sub(r"[;\s]+$", "", after).strip()
        if after and after != before:
            diffs.append(
                {
                    "detector": "normalize_labels",
                    "action": ACTION_NORMALIZE,
                    "field": "description",
                    "lang": lang,
                    "before": before,
                    "after": after,
                }
            )

    for lang, aliases in (item.get("aliases") or {}).items():
        for alias_obj in aliases:
            before = alias_obj.get("value", "")
            after = normalize_text(before)
            if after and after != before:
                diffs.append(
                    {
                        "detector": "normalize_labels",
                        "action": ACTION_NORMALIZE,
                        "field": "alias",
                        "lang": lang,
                        "before": before,
                        "after": after,
                    }
                )

    return diffs


def detect_add_mul_label(item: dict) -> list[dict]:
    """
    Detect items that should get a mul (multilingual) label.

    Guards (mirrors detectAddMulLabel() exactly):
      - Item must be a human (P31 = Q5)
      - No mul label present yet
      - en, de, fr labels all present and equal after normalisation
      - The normalised value must be Latin-script only
    """
    is_human = any(
        c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id") == "Q5"
        for c in (item.get("claims") or {}).get("P31", [])
    )
    if not is_human:
        return []

    labels = item.get("labels") or {}
    if labels.get("mul", {}).get("value"):
        return []

    required = ["en", "de", "fr"]
    raw_values = [labels.get(lang, {}).get("value") for lang in required]
    if any(v is None for v in raw_values):
        return []

    normalised = [normalize_text(v) for v in raw_values]
    if any(v != normalised[0] for v in normalised) or not normalised[0]:
        return []

    label_value = normalised[0]

    # Latin-script check: reject any letter character outside the Latin ranges.
    for ch in label_value:
        if not ch.isalpha():
            continue
        name = unicodedata.name(ch, "")
        # Accept letters whose Unicode name starts with "LATIN"
        if not name.startswith("LATIN"):
            return []

    return [
        {
            "detector": "add_mul_label",
            "action": ACTION_SET_MUL_LABEL,
            "value": label_value,
            "matching_langs": ", ".join(required),
        }
    ]


def detect_add_mul_alias(item: dict) -> list[dict]:
    """
    Detect alias values present in more than 5 languages that should be
    promoted to mul (multilingual) alias.

    Mirrors detectAddMulAlias() exactly, including:
      - Skip values already in aliases.mul
      - Skip values equal to the mul label
      - Threshold: strictly > 5 (i.e. ≥ 6 languages)
      - Paired with hidden ACTION_REMOVE_ALIAS diffs per source language
    """
    aliases = item.get("aliases") or {}
    labels = item.get("labels") or {}

    mul_alias_norms = {
        normalize_text(a.get("value")) for a in aliases.get("mul", []) if a.get("value")
    }
    mul_label_norm = (
        normalize_text(labels.get("mul", {}).get("value"))
        if labels.get("mul", {}).get("value")
        else None
    )

    value_map: dict[str, dict] = {}
    for lang, lang_aliases in aliases.items():
        if lang == "mul":
            continue
        for alias_obj in lang_aliases:
            raw = alias_obj.get("value", "")
            norm = normalize_text(raw)
            if not norm or norm in mul_alias_norms:
                continue
            if mul_label_norm and norm == mul_label_norm:
                continue
            if norm not in value_map:
                value_map[norm] = {"original": raw, "langs": {}}
            value_map[norm]["langs"][lang] = raw

    diffs = []
    for norm, entry in value_map.items():
        if len(entry["langs"]) <= 5:
            continue
        source_langs = list(entry["langs"].keys())
        row_id = f"addMulAlias_{norm}"
        diffs.append(
            {
                "detector": "add_mul_alias",
                "action": ACTION_ADD_MUL_ALIAS,
                "row_id": row_id,
                "value": entry["original"],
                "source_langs": source_langs,
                "lang_count": len(entry["langs"]),
            }
        )
        for lang, orig_value in entry["langs"].items():
            diffs.append(
                {
                    "detector": "add_mul_alias",
                    "action": ACTION_REMOVE_ALIAS,
                    "_hidden": True,
                    "row_id": row_id,
                    "lang": lang,
                    "value": orig_value,
                }
            )

    return diffs


def detect_upgrade_precise_date(item: dict) -> list[dict]:
    """
    Detect date properties with exactly one normal-rank and one deprecated-rank
    claim where the deprecated claim is less precise and tagged Q42727519 (or
    untagged), and propose upgrading the precise claim to preferred rank.

    Emits two diffs per matching pair:
      1. ACTION_UPGRADE_PRECISE_DATE on the precise (normal) claim
      2. Hidden ACTION_DOWNGRADE_PREFERRED on the deprecated (less-precise) claim

    Mirrors detectUpgradePreciseDate() from WikidataCleanup.js exactly.
    """
    diffs = []

    for pid in _get_date_properties(item):
        claims = item.get("claims", {}).get(pid, [])
        normal_cls = [c for c in claims if c.get("rank") == "normal"]
        depr_cls = [c for c in claims if c.get("rank") == "deprecated"]

        if len(normal_cls) != 1 or len(depr_cls) != 1:
            continue

        normal_cl = normal_cls[0]
        depr_cl = depr_cls[0]

        normal_prec = (
            normal_cl.get("mainsnak", {})
            .get("datavalue", {})
            .get("value", {})
            .get("precision", -1)
        )
        depr_prec = (
            depr_cl.get("mainsnak", {})
            .get("datavalue", {})
            .get("value", {})
            .get("precision", -1)
        )

        if normal_prec < 0 or depr_prec < 0 or normal_prec < depr_prec:
            continue
        if not _has_same_normalized_date(
            normal_cl, depr_cl, at_lowest_precision=True, ignore_calendarmodel=False
        ):
            continue
        if not normal_cl.get("references"):
            continue

        p2241_snaks = (depr_cl.get("qualifiers") or {}).get(
            PID_REASON_FOR_DEPRECATED_RANK, []
        )
        if p2241_snaks:
            if not all(
                s.get("datavalue", {}).get("value", {}).get("id") == QID_LESS_PRECISE
                for s in p2241_snaks
            ):
                continue

        row_id = f"upgradePreciseDate_{pid}_{normal_cl['id']}"

        diffs.append(
            {
                "detector": "upgrade_precise_date",
                "action": ACTION_UPGRADE_PRECISE_DATE,
                "row_id": row_id,
                "pid": pid,
                "claim_id": normal_cl["id"],
                "depr_claim_id": depr_cl["id"],
            }
        )
        diffs.append(
            {
                "detector": "upgrade_precise_date",
                "action": ACTION_DOWNGRADE_PREFERRED,
                "_hidden": True,
                "row_id": row_id,
                "pid": pid,
                "claim_id": depr_cl["id"],
                "removed_qualifier": (
                    PID_REASON_FOR_DEPRECATED_RANK if p2241_snaks else None
                ),
                "from_deprecated": True,
            }
        )

    return diffs


def detect_replace_wrong_property(item: dict) -> list[dict]:
    """
    Detect references where a URL snak is stored under the wrong property.

    Rules (mirrors detectWrongPropertyClaims() exactly):
      1. P2699 or P854 → P1065 when the URL is an archive URL
      2. P2699 or P854 → P4656 when the URL is a Wikimedia import URL
      3. P2699         → P854  unconditionally
    First matching rule wins.
    """
    RULES = [
        {
            "props": {PID_URL, PID_REFERENCE_URL},
            "new_prop": PID_ARCHIVE_URL,
            "check": _is_archive_url,
        },
        {
            "props": {PID_URL, PID_REFERENCE_URL},
            "new_prop": PID_WIKIMEDIA_IMPORT_URL,
            "check": _is_wikimedia_url,
        },
        {"props": {PID_URL}, "new_prop": PID_REFERENCE_URL, "check": None},
    ]
    diffs = []

    for pid, claims in (item.get("claims") or {}).items():
        for claim in claims:
            for ref in claim.get("references") or []:
                for wrong_prop, ref_snaks in (ref.get("snaks") or {}).items():
                    for snak in ref_snaks:
                        val = snak.get("datavalue", {}).get("value")
                        for rule in RULES:
                            if wrong_prop not in rule["props"]:
                                continue
                            matches = rule["check"] is None or (
                                isinstance(val, str) and rule["check"](val)
                            )
                            if not matches:
                                continue
                            diffs.append(
                                {
                                    "detector": "replace_wrong_property",
                                    "action": ACTION_CHANGE_PROPERTY,
                                    "context": "reference",
                                    "pid": pid,
                                    "claim_id": claim["id"],
                                    "ref_hash": ref.get("hash"),
                                    "snak_hash": snak.get("hash"),
                                    "old_property": wrong_prop,
                                    "new_property": rule["new_prop"],
                                }
                            )
                            break

    return diffs


def detect_split_reference_urls(item: dict) -> list[dict]:
    """
    Detect references that contain multiple URL snaks that should each become
    their own reference.  The split itself happens in apply.py.
    Mirrors detectMultipleReferenceUrls() from WikidataCleanup.js exactly.
    """
    diffs = []
    for pid, claims in (item.get("claims") or {}).items():
        for claim in claims:
            for ref in claim.get("references") or []:
                splittable, url_count, _ = _is_splittable_reference(ref)
                if not splittable:
                    continue
                diffs.append(
                    {
                        "detector": "split_reference_urls",
                        "action": ACTION_SPLIT_REFERENCE_URLS,
                        "pid": pid,
                        "claim_id": claim["id"],
                        "ref_hash": ref.get("hash"),
                        "url_count": url_count,
                    }
                )
    return diffs


def detect_merge_wiki_import_refs(
    item: dict,
    wikipedia_editions: "WikipediaEditions",
) -> list[dict]:
    """
    Detect pairs of references where one contains only P4656 (Wikimedia import
    URL) and another contains a matching P143 (imported from) snak, and propose
    merging the P4656 snak into the P143 reference.

    Requires a WikipediaEditions black box for language-code → QID lookup.
    Mirrors detectMergeWikiImportRefs() from WikidataCleanup.js exactly.
    """
    METADATA = {PID_RETRIEVED, PID_ARCHIVE_DATE}
    diffs = []

    for pid, claims in (item.get("claims") or {}).items():
        for claim in claims:
            if claim.get("rank") == "deprecated":
                continue
            refs = claim.get("references") or []
            if len(refs) < 2:
                continue

            for p4656_ref in refs:
                p4656_pids = list((p4656_ref.get("snaks") or {}).keys())
                if PID_WIKIMEDIA_IMPORT_URL not in p4656_pids:
                    continue
                if not all(
                    p == PID_WIKIMEDIA_IMPORT_URL or p in METADATA for p in p4656_pids
                ):
                    continue
                p4656_snaks = (p4656_ref.get("snaks") or {}).get(
                    PID_WIKIMEDIA_IMPORT_URL, []
                )
                if len(p4656_snaks) != 1:
                    continue

                p4656_url = p4656_snaks[0].get("datavalue", {}).get("value")
                if not isinstance(p4656_url, str):
                    continue

                p4656_lang = None
                try:
                    host = urlparse(p4656_url).hostname or ""
                    m = re.match(r"^([a-z-]+)\.wikipedia\.org$", host)
                    p4656_lang = m.group(1) if m else None
                except Exception:
                    pass
                if not p4656_lang:
                    continue

                expected_qid = wikipedia_editions.get_qid(p4656_lang)
                if not expected_qid:
                    continue

                for p143_ref in refs:
                    if p143_ref is p4656_ref:
                        continue
                    p143_snaks = (p143_ref.get("snaks") or {}).get(
                        PID_IMPORTED_FROM, []
                    )
                    if not p143_snaks:
                        continue
                    if (p143_ref.get("snaks") or {}).get(PID_WIKIMEDIA_IMPORT_URL):
                        continue
                    if not any(
                        s.get("datavalue", {}).get("value", {}).get("id")
                        == expected_qid
                        for s in p143_snaks
                    ):
                        continue

                    diffs.append(
                        {
                            "detector": "merge_wiki_import_refs",
                            "action": ACTION_MERGE_WIKI_IMPORT_REFS,
                            "pid": pid,
                            "claim_id": claim["id"],
                            "p4656_ref_hash": p4656_ref.get("hash"),
                            "p4656_url": p4656_url,
                            "p143_ref_hash": p143_ref.get("hash"),
                            "p143_qid": expected_qid,
                        }
                    )
                    break

    return diffs


# ==== Wikipedia editions (black box for detect_merge_wiki_import_refs) =======


class WikipediaEditions:
    """
    Maps Wikipedia language codes to Wikidata QIDs and vice versa.
    Black box for detect_merge_wiki_import_refs — bot.py fetches and constructs it.

    TODO: implement from_sparql() or from_wiki_page() to populate the map.
    For now construct with an empty map.
    """

    def __init__(self, lang_to_qid: dict[str, str] | None = None) -> None:
        self._lang_to_qid: dict[str, str] = lang_to_qid or {}
        self._qid_to_lang: dict[str, str] = {v: k for k, v in self._lang_to_qid.items()}

    def get_qid(self, lang_code: str) -> str | None:
        return self._lang_to_qid.get(lang_code)

    def get_lang(self, qid: str) -> str | None:
        return self._qid_to_lang.get(qid)

    def is_wikipedia_edition(self, qid: str) -> bool:
        return qid in self._qid_to_lang


def detect_ref_categories(
    item: dict,
    active_categories: set[str],
    classifier: ReferenceClassifier,
) -> dict[str, list[dict]]:
    """
    Single-pass reference categorisation for all active ref-category detectors.
    Each reference is classified exactly once.

    Mirrors detectRefCategories() from WikidataCleanup.js exactly, including
    the alwaysRemove / ignoreStrictCheck / level-gate logic.

    Returns a dict mapping category key → list of ACTION_REMOVE_REFS diffs.
    """
    results: dict[str, list[dict]] = {cat: [] for cat in active_categories}

    for pid, claims in (item.get("claims") or {}).items():
        for claim in claims:
            refs = claim.get("references") or []
            if not refs:
                continue

            levels = [
                classifier.get_reference_level(item, r, refs, claim) for r in refs
            ]
            max_level = max(levels) if levels else 0
            is_strict = claim.get("mainsnak", {}).get("datatype") != "external-id"

            for ri, ref in enumerate(refs):
                cat = classifier.determine_source_category(item, ref, refs, claim)
                if cat not in results:
                    continue

                level = levels[ri]

                always_remove = (
                    (cat == "wikimedia" and pid in ALWAYS_REMOVE_WIKIMEDIA_PIDS)
                    or (cat == "invalid" and not is_strict)
                    or cat == "wikimedia_no_sitelinks"
                    or (cat == "self_stated_in" and not is_strict)
                    or cat == "redundant"
                )
                ignore_strict_check = cat == "wikimedia"

                if _is_splittable_reference(ref)[0]:
                    continue

                if not always_remove:
                    if not ignore_strict_check and not is_strict:
                        continue
                    if level >= max_level:
                        continue

                results[cat].append(
                    {
                        "detector": cat,
                        "action": ACTION_REMOVE_REFS,
                        "pid": pid,
                        "claim_id": claim["id"],
                        "ref_hash": ref.get("hash"),
                        "removed_keys": list((ref.get("snaks") or {}).keys()),
                    }
                )

    return results


def detect_low_precision_dates(
    item: dict,
    classifier: ReferenceClassifier,
) -> list[dict]:
    """
    Detect birth/death date claims with lower precision that can be removed
    when a more precise, better-sourced claim is present.

    Two removal conditions (mirroring detectLowPrecisionDates() exactly):

    1. Strong-source removal: a less-precise claim whose references are all
       weak (or absent) is removed when a more precise claim with at least one
       strong (level-2) reference exists in the same group.

    2. No-reference removal: an unreferenced claim is removed when a higher-
       precision unreferenced claim exists in the same group.

    Groups are formed by same-date at the lowest common precision (ignoring
    calendar model differences).  Deprecated claims are excluded.

    Requires a ReferenceClassifier to determine reference strength.
    """
    diffs = []

    for pid in (PID_DATE_OF_BIRTH, PID_DATE_OF_DEATH):
        claims = [
            c
            for c in item.get("claims", {}).get(pid, [])
            if c.get("rank") != "deprecated"
            and (
                c.get("mainsnak", {})
                .get("datavalue", {})
                .get("value", {})
                .get("precision")
                or 0
            )
            <= 11
        ]

        # Group claims by same date at lowest common precision.
        groups: list[list[dict]] = []
        for c in claims:
            matched = next(
                (
                    g
                    for g in groups
                    if _has_same_normalized_date(
                        c, g[0], at_lowest_precision=True, ignore_calendarmodel=False
                    )
                ),
                None,
            )
            if matched is not None:
                matched.append(c)
            else:
                groups.append([c])

        for group in groups:
            if len(group) < 2:
                continue

            max_prec = max(
                c["mainsnak"]["datavalue"]["value"]["precision"] for c in group
            )

            # Find the best unreferenced claim (highest precision, no refs).
            best_no_ref_prec = 0
            best_no_ref_claim = None
            for c in group:
                prec = c["mainsnak"]["datavalue"]["value"]["precision"]
                refs = c.get("references", [])
                if not refs and prec > best_no_ref_prec:
                    best_no_ref_prec = prec
                    best_no_ref_claim = c

            # Find the most precise claim with at least one strong reference.
            precise_strong = next(
                (
                    c
                    for c in group
                    if c["mainsnak"]["datavalue"]["value"]["precision"] == max_prec
                    and c.get("references")
                    and any(
                        classifier.get_reference_level(
                            item, r, c.get("references", []), c
                        )
                        == 2
                        for r in c.get("references", [])
                    )
                ),
                None,
            )

            for c in group:
                prec = c["mainsnak"]["datavalue"]["value"]["precision"]
                refs = c.get("references", [])
                if prec >= max_prec:
                    continue

                # Condition 1: all refs weak (or none) + precise strong claim exists
                all_weak = not refs or all(
                    classifier.get_reference_level(item, r, refs, c) < 2 for r in refs
                )
                if precise_strong and all_weak:
                    diffs.append(
                        {
                            "detector": "low_precision_dates",
                            "action": ACTION_REMOVE_CLAIM,
                            "pid": pid,
                            "claim_id": c["id"],
                            "keep_claim_id": precise_strong["id"],
                        }
                    )
                    continue

                # Condition 2: no refs + lower precision than best unreferenced
                if (
                    not refs
                    and prec < best_no_ref_prec
                    and best_no_ref_claim is not None
                    and c["id"] != best_no_ref_claim["id"]
                ):
                    diffs.append(
                        {
                            "detector": "low_precision_dates",
                            "action": ACTION_REMOVE_CLAIM,
                            "pid": pid,
                            "claim_id": c["id"],
                            "keep_claim_id": best_no_ref_claim["id"],
                        }
                    )

    return diffs


def detect_obsolete_snaks_in_references(
    item: dict,
    rules: "SourceCategoryRules",
) -> list[dict]:
    """
    Detect references that contain obsolete external-ID snaks alongside at
    least one non-obsolete external-ID snak, and no P813 (retrieved) snak.
    Only the obsolete snaks are flagged for removal; the rest of the reference
    is preserved.

    Guards (mirrors detectObsoleteSnaksInReferences() from JS exactly):
      - The reference must have no P813 (retrieved) snak.
      - The reference must contain at least one obsolete external-ID snak.
      - The reference must contain at least one non-obsolete external-ID snak
        (the "surviving content" guard).
      - Deprecated claims are skipped.

    Requires SourceCategoryRules to identify obsolete PIDs.
    """
    diffs = []

    for pid, claims in item.get("claims", {}).items():
        for claim in claims:
            if claim.get("rank") == "deprecated":
                continue
            for ref in claim.get("references", []):
                snaks = ref.get("snaks") or {}
                ref_pids = list(snaks.keys())

                # Skip if P813 (retrieved) is present.
                if PID_RETRIEVED in ref_pids:
                    continue

                # Collect obsolete external-ID PIDs.
                obsolete_pids = [
                    p
                    for p in ref_pids
                    if rules.is_obsolete(p)
                    and any(
                        s.get("datatype") == "external-id"
                        and s.get("datavalue", {}).get("value")
                        for s in snaks.get(p, [])
                    )
                ]
                if not obsolete_pids:
                    continue

                # Require at least one surviving non-obsolete external-ID snak.
                has_other_ext_id = any(
                    p not in obsolete_pids
                    and any(
                        s.get("datatype") == "external-id"
                        and s.get("datavalue", {}).get("value")
                        for s in snaks.get(p, [])
                    )
                    for p in ref_pids
                )
                if not has_other_ext_id:
                    continue

                diffs.append(
                    {
                        "detector": "obsolete_snaks",
                        "action": ACTION_REMOVE_OBSOLETE_SNAKS,
                        "pid": pid,
                        "claim_id": claim["id"],
                        "ref_hash": ref.get("hash"),
                        "obsolete_pids": obsolete_pids,
                    }
                )

    return diffs


# ==== URL strip rules ========================================================


class UrlStripRules:
    """
    Holds the parsed url_tracking_params rules fetched from the wiki page.

    Mirrors the urlStripCache structure in WDCaches.js:
      { always: { hostname: [param, ...] }, recognition: { hostname: [...] } }

    The hardcoded defaults match WDCaches.js exactly and are always active.
    Wiki-sourced rules are merged on top.

    Hostname matching rules (same as JS paramsFor()):
      "example.com"    exact match after stripping leading www.
      ".example.com"   suffix match: matches example.com AND any subdomain
      "*"              global wildcard: applies to every hostname
      Fallback: base domain (last two segments) e.g. "linkedin.com" matches
                fr.linkedin.com, de.linkedin.com, etc.
    """

    HARDCODED_ALWAYS: dict[str, list[str]] = {
        "imdb.com": ["ref_"],
        "m.imdb.com": ["ref_"],
        "open.spotify.com": ["si"],
        "researchgate.net": ["ev"],
        "linkedin.com": ["originalSubdomain", "trk", "success", "original_referer"],
        ".scholar.google": ["oi", "view_op", "sortby", "authuser"],
    }

    HARDCODED_RECOGNITION: dict[str, list[str]] = {
        "youtube.com": ["t", "ab_channel", "mode"],
        "open.spotify.com": ["dl_branch", "nd"],
        "itunes.apple.com": ["mt"],
    }

    def __init__(
        self,
        always: dict[str, list[str]] | None = None,
        recognition: dict[str, list[str]] | None = None,
    ) -> None:
        # Merge wiki-sourced rules on top of hardcoded defaults.
        self.always = {**self.HARDCODED_ALWAYS, **(always or {})}
        self.recognition = {**self.HARDCODED_RECOGNITION, **(recognition or {})}

    @classmethod
    def from_wiki_text(cls, wikitext: str) -> "UrlStripRules":
        """
        Parse the url_tracking_params wiki page (plain wikitext, not HTML).
        Mirrors api_fetchUrlStripRules() in WDCaches.js.

        Table rows look like:
          | hostname || mode || param1, param2 || notes
        """
        always: dict[str, list[str]] = {}
        recognition: dict[str, list[str]] = {}

        for line in wikitext.splitlines():
            line = line.strip()
            if (
                not line.startswith("|")
                or line.startswith("|-")
                or line.startswith("|!")
            ):
                continue
            # Split on " || " — standard wikitable cell separator
            cells = [c.strip() for c in line.lstrip("|").split("||")]
            if len(cells) < 3:
                continue
            hostname, mode, params_raw = cells[0], cells[1].lower(), cells[2]
            params = [p.strip() for p in params_raw.split(",") if p.strip()]
            if not hostname or not params:
                continue
            if mode == "always":
                always.setdefault(hostname, []).extend(params)
            elif mode == "recognition":
                recognition.setdefault(hostname, []).extend(params)

        return cls(always=always, recognition=recognition)

    def params_for(self, map_: dict[str, list[str]], host: str) -> list[str]:
        """
        Resolve the strip-param list for a given hostname.
        Mirrors paramsFor() in cleanUrl() exactly.
        """
        wildcard = map_.get("*", [])
        specific: list[str] = []

        if host in map_:
            specific = map_[host]
        else:
            for key, params in map_.items():
                if key.startswith(".") and (
                    host == key[1:] or host.startswith(key[1:] + ".")
                ):
                    specific = params
                    break
            if not specific:
                base = ".".join(host.rsplit(".", 2)[-2:])
                specific = map_.get(base, [])

        return list(dict.fromkeys(wildcard + specific))  # deduplicate, preserve order


# ==== URL cleaning ===========================================================


def clean_url(raw_url: str, rules: UrlStripRules) -> str:
    """
    Remove tracking parameters from a URL string.
    Returns the cleaned URL, or the original if nothing changed.

    Mirrors cleanUrl(rawUrl, { recognitionMode: false }) in WDCaches.js.
    Only "always" mode stripping is applied — recognition mode is only
    used during URL→property matching, not during cleanup.
    """
    try:
        parsed = urlparse(raw_url)
    except Exception:
        return raw_url

    hostname = parsed.hostname or ""
    if hostname.startswith("www."):
        hostname = hostname[4:]

    params_to_strip = set(rules.params_for(rules.always, hostname))
    if not params_to_strip:
        return raw_url

    original_qs = parsed.query
    filtered = [
        (k, v)
        for k, v in parse_qsl(original_qs, keep_blank_values=True)
        if k not in params_to_strip
    ]

    new_qs = urlencode(filtered)
    if new_qs == original_qs:
        return raw_url

    cleaned = urlunparse(parsed._replace(query=new_qs))

    # Mirror JS: decode non-ASCII characters that may have been re-encoded.
    if any(ord(c) > 0x7F for c in raw_url):
        try:
            cleaned = unquote(cleaned, errors="surrogatepass")
        except Exception:
            pass

    return cleaned


def _normalize_wikimedia_import_url(raw: str | None) -> str | None:
    """
    Normalise a P4656 (Wikimedia import URL) value on a wikipedia.org domain:
      (a) http → https
      (b) remove mobile subdomain (xx.m.wikipedia.org → xx.wikipedia.org)
      (c) lowercase scheme+host (detected by comparing the raw prefix)

    Returns the normalised URL, or None if no change is needed or the URL
    is not on a wikipedia.org domain.

    Mirrors normalizeWikimediaImportUrl() in detectCleanUrls() exactly.
    """
    if not isinstance(raw, str):
        return None

    try:
        parsed = urlparse(raw)
    except Exception:
        return None

    hostname = parsed.hostname or ""
    if not (hostname.endswith(".wikipedia.org") or hostname == "wikipedia.org"):
        return None

    changed = False
    scheme = parsed.scheme
    netloc = parsed.netloc

    # (a) http → https
    if scheme == "http":
        scheme = "https"
        netloc = netloc  # netloc will be rebuilt below
        changed = True

    # (b) Remove mobile subdomain xx.m.wikipedia.org → xx.wikipedia.org
    m = re.match(r"^([a-z-]+)\.m\.wikipedia\.org$", hostname)
    if m:
        new_host = f"{m.group(1)}.wikipedia.org"
        # Rebuild netloc preserving any port (rare, but safe)
        port_part = f":{parsed.port}" if parsed.port else ""
        netloc = new_host + port_part
        changed = True

    # (c) Uppercase in scheme/host detected by raw comparison
    slash_idx = raw.find("/", raw.find("//") + 2)
    raw_prefix = raw[:slash_idx] if slash_idx != -1 else raw
    if raw_prefix != raw_prefix.lower():
        changed = True

    if not changed:
        return None

    result = urlunparse(
        (scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )

    # Decode non-ASCII chars the URL library may have re-encoded
    if any(ord(c) > 0x7F for c in raw):
        try:
            result = unquote(result, errors="surrogatepass")
        except Exception:
            pass

    return result


# ==== Detector: clean_urls ===================================================


def detect_clean_urls(item: dict, rules: UrlStripRules) -> list[dict]:
    """
    Detect URL values that contain tracking parameters that should be stripped,
    and P4656 (Wikimedia import URL) values that need normalisation.

    Covers four contexts, mirroring detectCleanUrls() in WikidataCleanup.js:
      1. Top-level URL-type claim mainsnaks
      2. URL-type qualifier snaks
      3. URL-type snaks in references (all PIDs, not just P854)
      4. P4656 snaks in references (http→https, mobile subdomain, case)

    The rules parameter carries the fetched url_tracking_params data and
    must be provided by the caller (bot.py) — detectors.py makes no network
    calls.
    """
    diffs = []

    def check_url(url_value: str, make_diff) -> dict | None:
        if not isinstance(url_value, str):
            return None
        cleaned = clean_url(url_value, rules)
        if cleaned == url_value:
            return None
        return make_diff(url_value, cleaned)

    claims = item.get("claims", {})

    # 1. Top-level URL claims (mainsnak)
    for pid, claim_list in claims.items():
        for claim in claim_list:
            if claim.get("rank") == "deprecated":
                continue
            mainsnak = claim.get("mainsnak", {})
            if mainsnak.get("datatype") != "url":
                continue
            url_value = mainsnak.get("datavalue", {}).get("value")
            diff = check_url(
                url_value,
                lambda before, after, pid=pid, claim=claim: {
                    "detector": "clean_urls",
                    "action": ACTION_CLEAN_URL,
                    "context": "claim",
                    "pid": pid,
                    "claim_id": claim["id"],
                    "snak_pid": pid,
                    "snak_hash": None,
                    "ref_hash": None,
                    "before": before,
                    "after": after,
                },
            )
            if diff:
                diffs.append(diff)

    # 2. Qualifier URL snaks
    for pid, claim_list in claims.items():
        for claim in claim_list:
            if claim.get("rank") == "deprecated":
                continue
            for q_pid, snaks in claim.get("qualifiers", {}).items():
                for snak in snaks:
                    if snak.get("datatype") != "url":
                        continue
                    url_value = snak.get("datavalue", {}).get("value")
                    diff = check_url(
                        url_value,
                        lambda before, after, pid=pid, claim=claim, q_pid=q_pid, snak=snak: {
                            "detector": "clean_urls",
                            "action": ACTION_CLEAN_URL,
                            "context": "qualifier",
                            "pid": pid,
                            "claim_id": claim["id"],
                            "snak_pid": q_pid,
                            "snak_hash": snak.get("hash"),
                            "ref_hash": None,
                            "before": before,
                            "after": after,
                        },
                    )
                    if diff:
                        diffs.append(diff)

    # 3. Reference URL snaks (all URL-datatype PIDs, not just P854)
    #    Mirrors mapReferences(): only the first matching snak per reference.
    for pid, claim_list in claims.items():
        for claim in claim_list:
            if claim.get("rank") == "deprecated":
                continue
            for ref in claim.get("references", []):
                for r_pid, snaks in (ref.get("snaks") or {}).items():
                    found = False
                    for snak in snaks:
                        if snak.get("datatype") != "url":
                            continue
                        url_value = snak.get("datavalue", {}).get("value")
                        diff = check_url(
                            url_value,
                            lambda before, after, pid=pid, claim=claim, ref=ref, r_pid=r_pid, snak=snak: {
                                "detector": "clean_urls",
                                "action": ACTION_CLEAN_URL,
                                "context": "reference",
                                "pid": pid,
                                "claim_id": claim["id"],
                                "snak_pid": r_pid,
                                "snak_hash": snak.get("hash"),
                                "ref_hash": ref.get("hash"),
                                "before": before,
                                "after": after,
                            },
                        )
                        if diff:
                            diffs.append(diff)
                            found = True
                            break  # first match per reference, mirrors mapReferences
                    if found:
                        break

    # 4. P4656 (Wikimedia import URL) normalisation in references
    for pid, claim_list in claims.items():
        for claim in claim_list:
            if claim.get("rank") == "deprecated":
                continue
            for ref in claim.get("references", []):
                for snak in (ref.get("snaks") or {}).get(PID_WIKIMEDIA_IMPORT_URL, []):
                    raw = snak.get("datavalue", {}).get("value")
                    normalized = _normalize_wikimedia_import_url(raw)
                    if normalized is None:
                        continue
                    diffs.append(
                        {
                            "detector": "clean_urls",
                            "action": ACTION_CLEAN_URL,
                            "context": "reference",
                            "pid": pid,
                            "claim_id": claim["id"],
                            "snak_pid": PID_WIKIMEDIA_IMPORT_URL,
                            "snak_hash": snak.get("hash"),
                            "ref_hash": ref.get("hash"),
                            "before": raw,
                            "after": normalized,
                        }
                    )

    return diffs


# ==== Detector registry ======================================================

#: Map detector id → detect function.
#: Used by bot.py to look up active detectors by name.
#: detect_clean_urls takes an extra `rules` argument and is registered
#: separately — bot.py wraps it with a functools.partial after fetching rules.
DETECTORS: dict[str, Callable] = {
    "self_cite": detect_self_cite,
    "empty_end_time": detect_empty_end_time,
    "alias_equals_label": detect_alias_equals_label,
    "redundant_preferred": detect_redundant_preferred,
    "expired_preferred": detect_expired_preferred,
    "dup_retrieved": detect_duplicate_refs,
    "merge_same_date_claims": detect_merge_same_date_claims,
    "julian_gregorian_dates": detect_julian_gregorian_dates,
    "normalize_labels": detect_normalize_labels,
    "add_mul_label": detect_add_mul_label,
    "add_mul_alias": detect_add_mul_alias,
    "upgrade_precise_date": detect_upgrade_precise_date,
    "replace_wrong_property": detect_replace_wrong_property,
    "split_reference_urls": detect_split_reference_urls,
    # Detectors requiring external data added dynamically by bot.py:
    #   "clean_urls"              → functools.partial(detect_clean_urls, rules=url_rules)
    #   "low_precision_dates"     → functools.partial(detect_low_precision_dates, classifier=clf)
    #   "obsolete_snaks"          → functools.partial(detect_obsolete_snaks_in_references, rules=rules)
    #   "merge_wiki_import_refs"  → functools.partial(detect_merge_wiki_import_refs, wikipedia_editions=we)
    # Ref-category detectors run via detect_ref_categories() (single shared pass):
    #   "wikimedia", "aggregator", "community", "redundant",
    #   "inferred", "obsolete", "self_stated_in"
}
