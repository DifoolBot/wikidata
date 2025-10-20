from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Union

from pywikibot import ItemPage, Site, WbTime

import shared_lib.constants as wd
from shared_lib.date_value import Date

# ------------------------------
# Exceptions
# ------------------------------


class QualifierError(Exception):
    pass


class UnexpectedValueError(QualifierError):
    pass


class PolicyError(QualifierError):
    pass


# ------------------------------
# QID → PID rules
# ------------------------------

QID_PID_RULES: Dict[str, Dict[str, Any]] = {
    # Example: "circa"
    wd.QID_CIRCA: {
        "default": wd.PID_SOURCING_CIRCUMSTANCES,  # canonical PID
        "forbidden": {wd.PID_INSTANCE_OF},  # if found here, remap to default
    },
    # Add more QIDs as needed
}

# ------------------------------
# Policy configuration
# ------------------------------


@dataclass(frozen=True)
class PIDPolicy:
    overwrite: bool = False
    skip: bool = False
    prefer_wikidata: bool = True
    prefer_external: bool = False
    unique: bool = False
    ordered: bool = False


def default_policies() -> Dict[str, PIDPolicy]:
    return {
        wd.PID_SOURCING_CIRCUMSTANCES: PIDPolicy(ordered=True),
        wd.PID_NATURE_OF_STATEMENT: PIDPolicy(
            ordered=True
        ),  # but QID rules remap "circa"
        wd.PID_START_TIME: PIDPolicy(ordered=True, unique=True),
        wd.PID_END_TIME: PIDPolicy(ordered=True, unique=True),
        wd.PID_EARLIEST_DATE: PIDPolicy(ordered=True, unique=True),
        wd.PID_LATEST_DATE: PIDPolicy(ordered=True, unique=True),
        wd.PID_URL: PIDPolicy(unique=True),
        wd.PID_DESCRIBED_BY_SOURCE: PIDPolicy(unique=False),
        wd.PID_WORK_LOCATION: PIDPolicy(ordered=False),
    }


# ------------------------------
# Internal value representation
# ------------------------------


@dataclass(frozen=True)
class QValue:
    kind: str  # "DATE" | "QID" | "STRING"
    value: Any


@dataclass
class QualEntry:
    pid: str
    qvalue: QValue
    provenance: str  # "wikidata" | "external"
    active: bool = True


# ------------------------------
# QualifierHandler
# ------------------------------


class QualifierHandler:
    def __init__(
        self,
        recognized: Optional[Iterable[str]] = None,
        pid_policies: Optional[Dict[str, PIDPolicy]] = None,
        qid_pid_rules: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        self._recognized: Optional[Set[str]] = set(recognized) if recognized else None
        self._policies: Dict[str, PIDPolicy] = pid_policies or default_policies()
        self._qid_pid_rules: Dict[str, Dict[str, Any]] = qid_pid_rules or QID_PID_RULES
        self._quals: Dict[str, List[QualEntry]] = {}

    # -------------------------
    # Normalization
    # -------------------------

    @staticmethod
    def _normalize_qid(qid: str) -> str:
        if not isinstance(qid, str) or not qid.startswith("Q") or not qid[1:].isdigit():
            raise UnexpectedValueError(f"Invalid QID: {qid!r}")
        return qid

    @staticmethod
    def _normalize_str(value: str) -> str:
        if value is None:
            raise UnexpectedValueError("STRING value cannot be None")
        return str(value).strip()

    @staticmethod
    def _normalize_date(date: Union[Date, WbTime]) -> Date:
        if isinstance(date, Date):
            return date
        if isinstance(date, WbTime):
            return Date.create_from_WbTime(date)
        raise UnexpectedValueError(f"DATE must be Date or WbTime, got {type(date)}")

    def _resolve_pid_for_qid(
        self, qid: str, pid: Optional[str], provenance: str
    ) -> str:
        rules = self._qid_pid_rules.get(qid)
        if not rules:
            if pid is None:
                raise PolicyError(f"External add_qid requires PID for {qid}")
            return pid
        default_pid = rules["default"]
        forbidden = rules.get("forbidden", set())
        if pid is None:
            return default_pid
        if pid in forbidden:
            return default_pid
        return pid

    def _check_recognized(self, pid: str):
        if self._recognized is not None and pid not in self._recognized:
            raise PolicyError(f"Unrecognized PID in this context: {pid}")

    # -------------------------
    # Helper add methods
    # -------------------------

    def add_date(
        self, pid: str, date: Union[Date, WbTime], provenance: str = "external"
    ):
        nd = self._normalize_date(date)
        self._check_recognized(pid)
        qv = QValue(kind="DATE", value=nd)
        self._add(pid, qv, provenance)

    def add_qid(
        self, qid: str, pid: Optional[str] = None, provenance: str = "external"
    ):
        nq = self._normalize_qid(qid)
        resolved_pid = self._resolve_pid_for_qid(nq, pid, provenance)
        self._check_recognized(resolved_pid)
        qv = QValue(kind="QID", value=nq)
        self._add(resolved_pid, qv, provenance)

    def add_str(self, pid: str, value: str, provenance: str = "external"):
        ns = self._normalize_str(value)
        self._check_recognized(pid)
        qv = QValue(kind="STRING", value=ns)
        self._add(pid, qv, provenance)

    def has_qid(self, qid: str) -> bool:
        nq = self._normalize_qid(qid)
        for pid, entries in self._quals.items():
            for e in entries:
                if e.qvalue.kind == "QID" and e.qvalue.value == nq and e.active:
                    return True
        return False

    def remove_qid(self, qid: str):
        """
        Mark QID as removed (tombstone) under its PID:
        - Do not delete Wikidata-sourced entries.
        - External-only entries may be hard-removed if configured (unique + prefer_wikidata).
        """
        nq = self._normalize_qid(qid)
        found = False
        for pid, entries in self._quals.items():
            for e in entries:
                if e.qvalue.kind == "QID" and e.qvalue.value == nq:
                    found = True
                    if e.provenance == "wikidata":
                        e.active = False  # tombstone; do not delete
                    else:
                        # External: either tombstone or hard-remove if policy allows
                        pol = self._policies.get(pid, PIDPolicy())
                        if pol.unique and pol.prefer_wikidata and not pol.overwrite:
                            # External-only removal can delete
                            entries.remove(e)
                        else:
                            e.active = False
        if not found:
            # Nothing to remove, but log as unexpected to audit
            raise QualifierError(f"Attempted to remove unknown QID: {qid}")

    def _add(self, pid: str, qv: QValue, provenance: str):
        if provenance not in ("wikidata", "external"):
            raise PolicyError(f"Invalid provenance: {provenance}")
        pol = self._policies.get(pid, PIDPolicy())
        # Initialize list
        bucket = self._quals.setdefault(pid, [])
        # Uniqueness handling
        if pol.unique:
            # Check for existing active value equal
            for e in bucket:
                if e.active and self._qvalue_equal(pid, e.qvalue, qv, strict=True):
                    # Already present; do not duplicate
                    return
            # If overwrite is allowed and provenance is external, we can replace WD
            if pol.overwrite and provenance == "external":
                # Remove all existing values and set this one
                bucket.clear()
        # Append new entry
        bucket.append(QualEntry(pid=pid, qvalue=qv, provenance=provenance, active=True))
        # Apply ordering if configured
        if pol.ordered:
            self._order_pid_bucket(pid)

    # -------------------------
    # Equality and merge
    # -------------------------

    def from_claim(self, claim: Any):
        """
        Extract and normalize qualifiers from a Pywikibot claim.
        Expected sources:
        - WbTime -> Date
        - ItemPage -> item.id (QID string)
        - others -> str
        """
        quals = getattr(claim, "qualifiers", None)
        if not quals:
            return

        for pid, snaks in quals.items():
            for snak in snaks:
                val = getattr(snak, "target", None)

                if isinstance(val, WbTime):
                    # Dates: no QID remapping needed
                    self.add_date(pid, val, provenance="wikidata")

                elif isinstance(val, ItemPage):
                    # QIDs: resolve PID according to QID rules
                    qid = val.id
                    resolved_pid = self._resolve_pid_for_qid(
                        qid, pid, provenance="wikidata"
                    )
                    self.add_qid(qid, pid=resolved_pid, provenance="wikidata")

                elif isinstance(val, str):
                    self.add_str(pid, val, provenance="wikidata")

                else:
                    # Fallback: stringify
                    self.add_str(pid, str(val), provenance="wikidata")

    def is_equal(self, other: "QualifierHandler", strict: bool = False) -> bool:
        """
        strict=True: exact match after normalization (PID + values); order-independent.
        strict=False: allow mergeable differences:
            - Missing qualifier on one side is acceptable.
            - Mapped PID equivalence (P5102 ≡ P1480) treated as equal.
            - Date equality via Date.is_equal(ignore_calendar_model=True).
        """
        # Compare by PID considering mapping equivalences
        self_view = self._canonical_view()
        other_view = other._canonical_view()

        if strict:
            return self_view == other_view

        # Non-strict: for each PID, every value in the smaller set must be present or mergeable in the larger
        for pid in set(self_view.keys()).union(other_view.keys()):
            sv = self_view.get(pid, [])
            ov = other_view.get(pid, [])
            # If one side missing, acceptable
            if not sv or not ov:
                continue
            # Compare set containment by relaxed equality
            if not self._bidi_relaxed_equal(pid, sv, ov):
                return False
        return True

    def merge(self, other: "QualifierHandler") -> Dict[str, Any]:
        """
        Merge 'other' into self applying per-PID policies.
        Returns: {'changed': bool, 'notes': List[str]}
        """
        changed = False
        notes: List[str] = []

        for pid, o_bucket in other._quals.items():
            for o_entry in o_bucket:
                # Resolve PID for QID entries using QID rules
                if o_entry.qvalue.kind == "QID":
                    resolved_pid = self._resolve_pid_for_qid(
                        o_entry.qvalue.value, pid, o_entry.provenance
                    )
                else:
                    resolved_pid = pid

                pol = self._policies.get(resolved_pid, PIDPolicy())
                if pol.skip:
                    notes.append(f"Skip PID {resolved_pid} per policy")
                    continue

                s_bucket = self._quals.setdefault(resolved_pid, [])

                if o_entry.qvalue.kind == "QID":
                    changed |= self._merge_qid(
                        resolved_pid, s_bucket, o_entry, pol, notes
                    )
                else:
                    changed |= self._merge_value(
                        resolved_pid, s_bucket, o_entry, pol, notes
                    )

                if pol.ordered:
                    self._order_pid_bucket(resolved_pid)

        return {"changed": changed, "notes": notes}

    def recreate_qualifiers(self, claim: Any):
        """
        Convert internal qualifiers back into Pywikibot objects and set them on the claim.
        """
        # Clear existing qualifiers on claim and rebuild
        # This assumes claim.qualifiers is mutable; adjust to your pywikibot usage.
        setattr(claim, "qualifiers", {})
        for pid, entries in self._quals.items():
            active_entries = [e for e in entries if e.active]
            if not active_entries:
                continue
            snaks = []
            for e in active_entries:
                if e.qvalue.kind == "DATE":
                    snaks.append(e.qvalue.value.create_wikidata_item())
                elif e.qvalue.kind == "QID":
                    snaks.append(ItemPage(Site(), e.qvalue.value))
                elif e.qvalue.kind == "STRING":
                    snaks.append(e.qvalue.value)
                else:
                    raise UnexpectedValueError(f"Unknown kind: {e.qvalue.kind}")
            claim.qualifiers[pid] = snaks

    # -------------------------
    # Internal helpers
    # -------------------------

    def _canonical_view(self) -> Dict[str, List[Tuple[str, Any]]]:
        """
        Produce a canonical order-independent view for equality comparison:
        pid -> list of (kind, canonical_value)
        Only active entries count.
        """
        view: Dict[str, List[Tuple[str, Any]]] = {}
        for pid, entries in self._quals.items():
            active = [
                (e.qvalue.kind, self._canon_value(pid, e.qvalue))
                for e in entries
                if e.active
            ]
            # Sort for order-independence
            active.sort(key=lambda kv: (kv[0], str(kv[1])))
            if active:
                view[pid] = active
        return view

    def _canon_value(self, pid: str, qv: QValue) -> Any:
        if qv.kind == "DATE":
            # Canonicalize date as tuple for equality (precision-insensitive via Date.is_equal)
            return qv.value  # keep Date object; compare via is_equal when relaxed
        elif qv.kind in ("QID", "STRING"):
            return qv.value
        else:
            raise UnexpectedValueError(f"Unknown kind: {qv.kind}")

    def _qvalue_equal(self, pid: str, a: QValue, b: QValue, strict: bool) -> bool:
        if a.kind != b.kind:
            return False
        if strict:
            # Exact compare
            if a.kind == "DATE":
                # Strict uses calendar model-sensitive compare (assume Date equality by identity)
                return Date.is_equal(a.value, b.value, ignore_calendar_model=False)
            return a.value == b.value
        else:
            # Relaxed equality
            if a.kind == "DATE":
                return Date.is_equal(a.value, b.value, ignore_calendar_model=True)
            return a.value == b.value

    def _bidi_relaxed_equal(
        self, pid: str, sv: List[Tuple[str, Any]], ov: List[Tuple[str, Any]]
    ) -> bool:
        # sv/ov items are (kind, value); for DATE use relaxed compare
        def contains(all_items: List[Tuple[str, Any]], item: Tuple[str, Any]) -> bool:
            k, v = item
            for k2, v2 in all_items:
                if k2 != k:
                    continue
                if k == "DATE":
                    if Date.is_equal(v, v2, ignore_calendar_model=True):
                        return True
                else:
                    if v == v2:
                        return True
            return False

        # Each item in sv must be in ov or vice versa; allow missing
        # If both sides have values, require overlap; if completely disjoint with conflicts, unequal
        # Check sv items in ov
        overlap_sv = any(contains(ov, it) for it in sv)
        overlap_ov = any(contains(sv, it) for it in ov)
        return overlap_sv or overlap_ov

    def _merge_value(
        self,
        pid: str,
        s_bucket: List[QualEntry],
        o_entry: QualEntry,
        pol: PIDPolicy,
        notes: List[str],
    ) -> bool:
        """
        Merge non-QID values (DATE, STRING). Default: external fills gaps; do not overwrite WD.
        """
        changed = False
        # Try to find equal value
        for e in s_bucket:
            if e.active and self._qvalue_equal(
                pid, e.qvalue, o_entry.qvalue, strict=False
            ):
                # Already present; do not change
                return False

        # Conflicts (different values in unique PID)
        if pol.unique and s_bucket:
            # Decide overwrite vs prefer
            if pol.overwrite or pol.prefer_external:
                s_bucket.clear()
                s_bucket.append(
                    QualEntry(
                        pid=pid,
                        qvalue=o_entry.qvalue,
                        provenance=o_entry.provenance,
                        active=True,
                    )
                )
                notes.append(f"Overwrite unique PID {pid} with external value")
                changed = True
            elif pol.prefer_wikidata:
                notes.append(f"Prefer WD for unique PID {pid}; external ignored")
            else:
                # Keep both only if policy permits (not unique); but here unique=True
                notes.append(f"Conflict at unique PID {pid}; keeping WD")
            return changed

        # Non-unique or empty bucket: append external
        s_bucket.append(
            QualEntry(
                pid=pid,
                qvalue=o_entry.qvalue,
                provenance=o_entry.provenance,
                active=True,
            )
        )
        changed = True
        return changed

    def _merge_qid(
        self,
        pid: str,
        s_bucket: List[QualEntry],
        o_entry: QualEntry,
        pol: PIDPolicy,
        notes: List[str],
    ) -> bool:
        """
        Merge QID-as-Boolean:
        - WD QIDs win; external fills gaps only.
        - If both have same QID, keep WD’s PID and do not duplicate.
        - Do not overwrite WD with different QID unless overwrite/prefer_external.
        """
        changed = False
        # Check if same QID already present
        for e in s_bucket:
            if e.qvalue.kind == "QID" and e.qvalue.value == o_entry.qvalue.value:
                if e.active:
                    # Already present: prefer WD provenance, keep existing PID
                    return False
                else:
                    # Tombstoned: revive if external suggests present and policy allows
                    if (
                        o_entry.provenance == "wikidata"
                        or pol.prefer_external
                        or pol.overwrite
                    ):
                        e.active = True
                        notes.append(
                            f"Revived tombstoned QID {e.qvalue.value} at PID {pid}"
                        )
                        return True
                    else:
                        notes.append(
                            f"External suggested revival of {e.qvalue.value} denied per policy"
                        )
                        return False

        # Different QID conflict under unique PID?
        if pol.unique and any(e.qvalue.kind == "QID" and e.active for e in s_bucket):
            if pol.overwrite or pol.prefer_external:
                # Replace existing (even WD) with external
                s_bucket[:] = [e for e in s_bucket if not (e.qvalue.kind == "QID")]
                s_bucket.append(
                    QualEntry(
                        pid=pid,
                        qvalue=o_entry.qvalue,
                        provenance=o_entry.provenance,
                        active=True,
                    )
                )
                notes.append(
                    f"Overwrite unique QID at PID {pid} with {o_entry.qvalue.value}"
                )
                changed = True
            else:
                notes.append(
                    f"Prefer WD QID at PID {pid}; external {o_entry.qvalue.value} ignored"
                )
            return changed

        # Otherwise, external fills gaps
        s_bucket.append(
            QualEntry(
                pid=pid,
                qvalue=o_entry.qvalue,
                provenance=o_entry.provenance,
                active=True,
            )
        )
        changed = True
        return changed

    def _order_pid_bucket(self, pid: str):
        """
        Preserve WD-first, then external; apply semantic ordering within PID:
        - P580 before P582
        - P1319 before P1326
        """
        entries = self._quals.get(pid, [])
        if not entries:
            return

        # WD first, then external
        def prov_rank(pv: str) -> int:
            return 0 if pv == "wikidata" else 1

        def semantic_rank(pid: str, e: QualEntry) -> Tuple[int, str]:
            # Lower rank comes first
            # Default rank 10; adjust for known sequences
            r = 10
            if pid in (wd.PID_START_TIME, wd.PID_END_TIME):
                r = 0 if pid == wd.PID_START_TIME else 1
            elif pid in (wd.PID_EARLIEST_DATE, wd.PID_LATEST_DATE):
                r = 0 if pid == wd.PID_EARLIEST_DATE else 1
            return (r, e.qvalue.kind)

        entries.sort(
            key=lambda e: (
                prov_rank(e.provenance),
                semantic_rank(pid, e),
                str(e.qvalue.value),
            )
        )
        self._quals[pid] = entries
