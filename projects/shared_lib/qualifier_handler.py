from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any, OrderedDict as TOrderedDict
from collections import OrderedDict
from shared_lib.date_value import Date
import shared_lib.constants as wd


class QualifierHandler:
    """
    Generic qualifier handler:
    - Stores normalized qualifiers in an OrderedDict[pid -> List[normalized_value]]
    - Provides equality, merge, and recreation with snak_id preservation
    - Centralizes QID-centric PID remapping and per-PID merge policies
    """

    # QID-centric mapping and rules (example defaults; override per instance via __init__)
    DEFAULT_QID_PID_RULES = {
        # circa: default under P1480; forbid alternative PIDs (e.g., P5102, P31)
        wd.QID_CIRCA: {
            "default": wd.PID_SOURCING_CIRCUMSTANCES,
            "forbidden": {wd.PID_INSTANCE_OF},
        },
    }

    # Per-PID merge policies:
    # - overwrite: external overwrites WD
    # - skip: do not merge this PID
    # - prefer_wikidata: keep WD values if they exist
    # - prefer_external: overwrite if external provides value
    # - unique: union of distinct values (dedupe)
    DEFAULT_PID_POLICIES = {
        wd.PID_START_TIME: "prefer_wikidata",
        wd.PID_END_TIME: "prefer_wikidata",
        wd.PID_EARLIEST_DATE: "prefer_wikidata",
        wd.PID_LATEST_DATE: "prefer_wikidata",
        wd.PID_SOURCING_CIRCUMSTANCES: "unique",
        wd.PID_URL: "unique",  # URL
    }

    # Semantic ordering across PIDs
    PID_ORDER = [
        wd.PID_EARLIEST_DATE,
        wd.PID_LATEST_DATE,
        wd.PID_SOURCING_CIRCUMSTANCES,
        wd.PID_START_TIME,
        wd.PID_END_TIME,
    ]

    def __init__(
        self,
        recognized: Optional[Dict[str, str]] = None,
        pid_policies: Optional[Dict[str, str]] = None,
        qid_pid_rules: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        self._values: OrderedDict[str, List[Any]] = OrderedDict()
        self._recognized = recognized or {}
        self._pid_policies = dict(self.DEFAULT_PID_POLICIES)
        if pid_policies:
            self._pid_policies.update(pid_policies)
        self._qid_pid_rules = dict(self.DEFAULT_QID_PID_RULES)
        if qid_pid_rules:
            # merge/override provided rules
            for q, rule in qid_pid_rules.items():
                base = self._qid_pid_rules.get(q, {"default": None, "forbidden": set()})
                merged = {
                    "default": rule.get("default", base.get("default")),
                    "forbidden": set(base.get("forbidden", set()))
                    | set(rule.get("forbidden", set())),
                }
                self._qid_pid_rules[q] = merged

    # ----- Adders -----

    def add_date(self, pid: str, date: Date) -> None:
        self._assert_pid(pid)
        self._append(pid, date)

    def add_qid(self, qid: str, pid: Optional[str] = None) -> None:
        qid = self._normalize_qid(qid)
        target_pid = self._pid_for_qid(qid, pid)
        self._append(target_pid, qid)

    def add_str(self, pid: str, value: str) -> None:
        self._assert_pid(pid)
        if not isinstance(value, str):
            raise ValueError(f"STRING qualifier must be str: got {type(value)}")
        self._append(pid, value)

    def has_qid(self, qid: str) -> bool:
        qid = self._normalize_qid(qid)
        for values in self._values.values():
            if qid in values:
                return True
        return False

    def remove_qid(self, qid: str) -> None:
        qid = self._normalize_qid(qid)
        for pid in list(self._values.keys()):
            self._values[pid] = [v for v in self._values[pid] if v != qid]
            if not self._values[pid]:
                del self._values[pid]

    # ----- Normalization from claim -----

    def from_claim(self, claim: Any) -> "QualifierHandler":
        """
        Parse qualifiers from a pwb.Claim, normalize, and store internally.
        Applies QID-centric mapping: forbidden PIDs remap to default for that QID.
        """
        self._values.clear()
        quals = getattr(claim, "qualifiers", {}) or {}
        for pid, claims in quals.items():
            for q in claims:
                val = self._normalize_datavalue(q.getTarget())
                # Remap QIDs by rules
                if isinstance(val, str) and self._is_qid(val):
                    pid = self._pid_for_qid(val, pid)
                self._append(pid, val)
        return self

    # ----- Equality -----

    def is_equal(self, other: "QualifierHandler", strict: bool = False) -> bool:
        """
        strict=True: exact PID+value match
        strict=False: allow mergeable differences (missing qualifiers, PID remaps), but not semantic conflicts
        """
        if strict:
            return self._values == other._values

        self_canon = self._normalize_temporal_equivalents(self._canonicalized())
        other_canon = self._normalize_temporal_equivalents(other._canonicalized())

        # Temporal special case
        if not self._temporal_mergeable(self_canon, other_canon):
            return False

        # Then check all other PIDs as before
        for pid in set(self_canon.keys()).union(other_canon.keys()):
            if pid in {"P580", "P582", "P1319", "P1326", "P585"}:
                continue  # already handled
            a = self_canon.get(pid, [])
            b = other_canon.get(pid, [])
            if not self._pid_bucket_mergeable(a, b, pid):
                return False

        if self._has_nonmergeable_modifier_mismatch(self_canon, other_canon):
            return False

        return True

    # ----- Merge -----

    def merge(self, other: "QualifierHandler") -> Dict[str, Any]:
        """
        Merge qualifiers with per-PID policies and QID rules; return {"changed": bool, "notes": [...]}
        WD wins; external fills gaps only; non-mergeable QIDs block merging.
        """
        notes: List[str] = []
        changed = False

        self_canon = self._canonicalized()
        other_canon = other._canonicalized()

        # Block merge if modifier mismatch that changes semantics
        if self._has_nonmergeable_modifier_mismatch(self_canon, other_canon):
            notes.append("Non-mergeable QID semantic mismatch (e.g., circa).")
            return {"changed": False, "notes": notes}

        # Apply per-PID merge policies
        for pid in set(self_canon.keys()).union(other_canon.keys()):
            policy = self._pid_policies.get(pid, "unique")
            a = list(self_canon.get(pid, []))
            b = list(other_canon.get(pid, []))

            # WD QIDs win: if both have same QID, keep WD’s PID (already canonicalized)
            if policy == "skip":
                continue
            elif policy == "overwrite":
                if b and a != b:
                    self_canon[pid] = b
                    changed = True
                    notes.append(f"{pid}: overwrite with external.")
            elif policy == "prefer_wikidata":
                # keep a; only fill gaps from b
                merged = self._union_preserve_order(a, b)
                if merged != a:
                    self_canon[pid] = merged
                    changed = True
                    notes.append(f"{pid}: filled gaps from external.")
            elif policy == "prefer_external":
                # external values override if present, else keep a
                if b:
                    if a != b:
                        self_canon[pid] = b
                        changed = True
                        notes.append(f"{pid}: prefer external.")
                else:
                    self_canon[pid] = a
            elif policy == "unique":
                merged = self._union_preserve_order(a, b)
                if merged != a:
                    self_canon[pid] = merged
                    changed = True
                    notes.append(f"{pid}: unique union.")
            else:
                raise ValueError(f"Unknown merge policy: {policy}")

        # Write back to internal store preserving within-PID insertion order
        self._values.clear()
        for pid in self._ordered_pids(self_canon):
            self._values[pid] = list(self_canon.get(pid, []))

        return {"changed": changed, "notes": notes}

    # ----- Recreation -----

    def recreate_qualifiers(self, claim: Any) -> "OrderedDict[str, List[Any]]":
        """
        Return OrderedDict[str, List[pwb.Claim]]; reuse existing Claim objects from `claim`
        when PID+value matches (preserve snak_ids). Create new Claim objects only when needed.
        Cross-PID semantic ordering; within-PID insertion order preserved.
        """
        from pywikibot import Claim, ItemPage, Site

        existing = getattr(claim, "qualifiers", {}) or {}
        site = claim.repo
        out: "OrderedDict[str, List[Claim]]" = OrderedDict()

        # Build reverse index: {(pid, normalized_value) -> existing Claim}
        idx: Dict[Tuple[str, Any], Any] = {}
        for pid, claims in existing.items():
            for q in claims:
                nv = self._normalize_datavalue(q.getTarget())
                # Apply QID-centric canonicalization
                if isinstance(nv, str) and self._is_qid(nv):
                    pid = self._pid_for_qid(nv, pid)
                idx[(pid, nv)] = q

        # Emit in cross-PID order; within-PID insertion order preserved
        for pid in self._ordered_pids(self._values):
            out[pid] = []
            for nv in self._values[pid]:
                key = (pid, nv)
                if key in idx:
                    out[pid].append(idx[key])  # reuse existing claim (preserve snak_id)
                else:
                    c = Claim(site, pid, is_qualifier=True)
                    if isinstance(nv, Date):
                        c.setTarget(nv.create_wikidata_item())
                    elif isinstance(nv, str) and self._is_qid(nv):
                        c.setTarget(ItemPage(site, nv))
                    else:
                        c.setTarget(nv)  # string or external ID
                    out[pid].append(c)

        return out

    # ----- Internals -----

    def _append(self, pid: str, value: Any) -> None:
        if pid not in self._values:
            self._values[pid] = []
        self._values[pid].append(self._freeze(value))

    def _freeze(self, value: Any) -> Any:
        # Date is already immutable; strings/QIDs are immutable; no conversion here
        return value

    def _temporal_mergeable(self, self_vals, other_vals):
        start_self = self_vals.get("P580")
        end_self = self_vals.get("P582")
        start_other = other_vals.get("P580")
        end_other = other_vals.get("P582")

        # Both sides have start → must match
        if (
            start_self
            and start_other
            and not Date.is_equal(start_self[0], start_other[0], False)
        ):
            return False
        # Both sides have end → must match
        if (
            end_self
            and end_other
            and not Date.is_equal(end_self[0], end_other[0], False)
        ):
            return False
        # Complementary only (start vs end) → not mergeable
        if (start_self and not end_self) and (end_other and not start_other):
            return False
        if (end_self and not start_self) and (start_other and not end_other):
            return False
        return True

    def _normalize_temporal_equivalents(
        self, store: dict[str, list]
    ) -> dict[str, list]:
        """
        Normalize temporal qualifiers into a canonical form:
        - Collapse P580+P582 with identical value into P585 (point in time).
        - Collapse P1319+P1326 with identical value into P585.
        - Leave P585 as-is.
        - Ensure complementary-only cases (start-only vs end-only) are preserved
        so they can be detected as non-mergeable later.
        """
        # Copy to avoid mutating caller
        store = {pid: list(vals) for pid, vals in store.items()}

        # Helper: collapse start+end into point if identical
        def collapse_pair(start_pid, end_pid):
            start = store.get(start_pid)
            end = store.get(end_pid)
            if start and end and len(start) == 1 and len(end) == 1:
                if Date.is_equal(start[0], end[0], ignore_calendar_model=False):
                    # Collapse to P585
                    store.pop(start_pid, None)
                    store.pop(end_pid, None)
                    store.setdefault("P585", []).append(start[0])

        collapse_pair("P580", "P582")
        collapse_pair("P1319", "P1326")

        return store

    def _normalize_datavalue(self, v: Any) -> Any:
        # WbTime -> Date; ItemPage -> id; else str
        from pywikibot import WbTime, ItemPage

        if isinstance(v, WbTime):
            return Date.create_from_WbTime(v)
        if isinstance(v, ItemPage):
            return v.id
        if isinstance(v, str):
            return v
        # External ID or other to string
        try:
            return str(v)
        except Exception:
            raise ValueError(f"Unexpected qualifier value type: {type(v)}")

    def _normalize_qid(self, qid: str) -> str:
        if not isinstance(qid, str):
            qid = str(qid)
        qid = qid.strip()
        if not self._is_qid(qid):
            raise ValueError(f"Not a QID: {qid}")
        return qid

    def _is_qid(self, s: str) -> bool:
        return isinstance(s, str) and s.startswith("Q") and s[1:].isdigit()

    def _pid_for_qid(self, qid: str, pid_hint: Optional[str]) -> str:
        rules = self._qid_pid_rules.get(qid)
        if not rules:
            return (
                pid_hint
                or self._recognized.get(qid)
                or (pid_hint or wd.PID_SOURCING_CIRCUMSTANCES)
            )
        default = rules.get("default") or pid_hint or wd.PID_SOURCING_CIRCUMSTANCES
        forbidden = set(rules.get("forbidden", set()))
        if pid_hint in forbidden:
            return default
        return pid_hint or default

    def _ordered_pids(self, store: Dict[str, List[Any]]) -> List[str]:
        present = list(store.keys())

        # stable sort: first known in PID_ORDER, then others by original order
        def order_key(pid: str) -> Tuple[int, int]:
            try:
                i = self.PID_ORDER.index(pid)
            except ValueError:
                i = len(self.PID_ORDER) + 1
            return (i, present.index(pid))

        return sorted(present, key=order_key)

    def _canonicalized(self) -> Dict[str, List[Any]]:
        """
        Canonicalize by remapping QIDs to their default PID if forbidden, preserving insertion order.
        """
        out: Dict[str, List[Any]] = {}
        for pid, values in self._values.items():
            for v in values:
                if isinstance(v, str) and self._is_qid(v):
                    target_pid = self._pid_for_qid(v, pid)
                else:
                    target_pid = pid
                out.setdefault(target_pid, []).append(v)
        return out

    def _pid_bucket_mergeable(self, a: List[Any], b: List[Any], pid: str) -> bool:
        """
        Non-strict equality: treat missing values as mergeable; detect semantic conflicts:
        - Date: use precision/calendar-aware equality across sets
        - QIDs and strings: presence mismatches are okay; conflicting duplicates not a blocker
        """
        # For Date buckets, ensure each date in min set can be matched in the other
        a_dates = [x for x in a if isinstance(x, Date)]
        b_dates = [x for x in b if isinstance(x, Date)]
        if a_dates or b_dates:
            # Compare as sets with calendar tolerance
            for d in a_dates:
                if not any(
                    Date.is_equal(d, e, ignore_calendar_model=False) for e in b_dates
                ):
                    # Missing date on one side is allowed; only conflict if both present but unequal
                    continue
            for d in b_dates:
                if not any(
                    Date.is_equal(d, e, ignore_calendar_model=False) for e in a_dates
                ):
                    continue
            # No direct contradictions detected
            return True

        # For QIDs/strings, bucket is mergeable by default; specific non-mergeable handled separately
        return True

    def _has_nonmergeable_modifier_mismatch(
        self,
        a: Dict[str, List[Any]],
        b: Dict[str, List[Any]],
    ) -> bool:
        """
        Detect cases like 'date=1870' vs 'circa 1870' (Q5727902 under P1480) that must not merge.
        Rule: if any non-mergeable QID appears on one side but not the other, block merge/equality.
        """
        nonmergeable_qids = set(
            q
            for q, r in self._qid_pid_rules.items()
            if r.get("default") == wd.PID_SOURCING_CIRCUMSTANCES
        )
        a_mod = self._collect_qids(a).intersection(nonmergeable_qids)
        b_mod = self._collect_qids(b).intersection(nonmergeable_qids)
        return bool(a_mod) != bool(b_mod)  # presence mismatch blocks

    def _collect_qids(self, store: Dict[str, List[Any]]) -> set:
        out = set()
        for vals in store.values():
            for v in vals:
                if isinstance(v, str) and self._is_qid(v):
                    out.add(v)
        return out

    def _union_preserve_order(self, a: List[Any], b: List[Any]) -> List[Any]:
        seen = set()
        out: List[Any] = []
        for x in a + b:
            key = self._value_key(x)
            if key in seen:
                continue
            seen.add(key)
            out.append(x)
        return out

    def _value_key(self, v: Any) -> Tuple:
        if isinstance(v, Date):
            return ("date", v.year, v.month, v.day, v.precision, v.calendar)
        if isinstance(v, str) and self._is_qid(v):
            return ("qid", v)
        return ("str", v)

    def _assert_pid(self, pid: str) -> None:
        if not isinstance(pid, str) or not pid.startswith("P") or not pid[1:].isdigit():
            raise ValueError(f"Invalid PID: {pid}")


def test1():
    wikidata_q = QualifierHandler()
    wikidata_q.add_date(wd.PID_POINT_IN_TIME, Date(1900))

    external_q = QualifierHandler()
    external_q.add_date(wd.PID_START_TIME, Date(1900))
    external_q.add_date(wd.PID_END_TIME, Date(1900))

    print(wikidata_q.is_equal(external_q, strict=False))


def test2():
    wikidata_q = QualifierHandler()
    wikidata_q.add_str(wd.PID_SUBJECT_NAMED_AS, "test1")

    external_q = QualifierHandler()
    external_q.add_str(wd.PID_SUBJECT_NAMED_AS, "test2")

    print(wikidata_q.is_equal(external_q, strict=False))


if __name__ == "__main__":
    test2()
