import json
from pathlib import Path
from typing import Optional

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd

JSON_DIR = Path("projects\\genealogics\\")

class_dict = {
    "AcademicDegree": cwd.AcademicDegree,
    "AwardReceived": cwd.AwardReceived,
    "HonorificPrefix": cwd.HonorificPrefix,
    "HonorificSuffix": cwd.HonorificSuffix,
    "MemberOf": cwd.MemberOf,
    "MilitaryBranch": cwd.MilitaryBranch,
    "NobleTitle": cwd.NobleTitle,
    "Occupation": cwd.Occupation,
    "PositionHeld": cwd.PositionHeld,
}

qid_dict = {
    "QID_AMERICAN_SOCIETY_OF_GENEALOGISTS": wd.QID_AMERICAN_SOCIETY_OF_GENEALOGISTS,
    "QID_BARON": wd.QID_BARON,
    "QID_BARONET": wd.QID_BARONET,
    "QID_COMMANDER_OF_THE_ORDER_OF_THE_BRITISH_EMPIRE": wd.QID_COMMANDER_OF_THE_ORDER_OF_THE_BRITISH_EMPIRE,
    "QID_COMPANION_OF_HONOUR": wd.QID_COMPANION_OF_HONOUR,
    "QID_COMPANION_OF_THE_ORDER_OF_ST_MICHAEL_AND_ST_GEORGE": wd.QID_COMPANION_OF_THE_ORDER_OF_ST_MICHAEL_AND_ST_GEORGE,
    "QID_COMPANION_OF_THE_ORDER_OF_THE_BATH": wd.QID_COMPANION_OF_THE_ORDER_OF_THE_BATH,
    "QID_COUNT": wd.QID_COUNT,
    "QID_DOCTOR_OF_DIVINITY": wd.QID_DOCTOR_OF_DIVINITY,
    "QID_DOCTOR_OF_MEDICINE": wd.QID_DOCTOR_OF_MEDICINE,
    "QID_ESQUIRE": wd.QID_ESQUIRE,
    "QID_FELLOW_OF_THE_AMERICAN_SOCIETY_OF_GENEALOGISTS": wd.QID_FELLOW_OF_THE_AMERICAN_SOCIETY_OF_GENEALOGISTS,
    "QID_FELLOW_OF_THE_ROYAL_SOCIETY_OF_CANADA": wd.QID_FELLOW_OF_THE_ROYAL_SOCIETY_OF_CANADA,
    "QID_FELLOW_OF_THE_ROYAL_SOCIETY": wd.QID_FELLOW_OF_THE_ROYAL_SOCIETY,
    "QID_JONKHEER": wd.QID_JONKHEER,
    "QID_KNIGHT_COMMANDER_OF_THE_ORDER_OF_THE_BRITISH_EMPIRE": wd.QID_KNIGHT_COMMANDER_OF_THE_ORDER_OF_THE_BRITISH_EMPIRE,
    "QID_LEGUM_DOCTOR": wd.QID_LEGUM_DOCTOR,
    "QID_MEMBER_OF_THE_ORDER_OF_THE_BRITISH_EMPIRE": wd.QID_MEMBER_OF_THE_ORDER_OF_THE_BRITISH_EMPIRE,
    "QID_OFFICER_OF_THE_ORDER_OF_THE_BRITISH_EMPIRE": wd.QID_OFFICER_OF_THE_ORDER_OF_THE_BRITISH_EMPIRE,
    "QID_PRIVATE": wd.QID_PRIVATE,
    "QID_RABBI": wd.QID_RABBI,
    "QID_REVEREND": wd.QID_REVEREND,
    "QID_ROYAL_NAVY": wd.QID_ROYAL_NAVY,
    "QID_SIR": wd.QID_SIR,
    "QID_THE_HONOURABLE": wd.QID_THE_HONOURABLE,
    "QID_THE_RIGHT_REVEREND": wd.QID_THE_RIGHT_REVEREND,
}


class PrefixSuffixLookup:
    """
    Loads and indexes prefix/suffix data from a JSON file for fast lookup.
    """

    def __init__(self, json_path: Optional[Path] = None):
        if json_path is None:
            json_path = JSON_DIR / "prefix_suffix.json"
        with open(json_path, encoding="utf-8") as f:
            affix_data = json.load(f)  # renamed from prefix_data

        # Build four lookup dicts: prefix/full, prefix/variant, suffix/full, suffix/variant
        self._prefix_full_lookup = {}
        self._prefix_variant_lookup = {}
        self._suffix_full_lookup = {}
        self._suffix_variant_lookup = {}

        for key, entry in affix_data.items():
            # Prefix lookups
            if "prefix_full" in entry and entry["prefix_full"]:
                self._prefix_full_lookup[entry["prefix_full"]] = entry
            for variant in entry.get("prefix_variants", []):
                self._prefix_variant_lookup[variant] = entry
            # Suffix lookups
            if "suffix_full" in entry and entry["suffix_full"]:
                self._suffix_full_lookup[entry["suffix_full"]] = entry
            for variant in entry.get("suffix_variants", []):
                self._suffix_variant_lookup[variant] = entry

    def _analyze_affix(
        self, affix: str, include_full: bool = False, affix_type: str = "prefix"
    ) -> list[tuple[type[cwd.ItemStatement], str]]:
        """
        Generalized method for analyzing prefix or suffix.
        """
        if affix_type == "prefix":
            full_lookup = self._prefix_full_lookup
            variant_lookup = self._prefix_variant_lookup
        else:
            full_lookup = self._suffix_full_lookup
            variant_lookup = self._suffix_variant_lookup

        entry = None
        if include_full:
            entry = full_lookup.get(affix)
        if not entry:
            entry = variant_lookup.get(affix)
        if not entry:
            raise ValueError(f"Unknown {affix_type}: {affix}")

        result = []
        # Handle sequence recursively
        if "sequence" in entry:
            for sub in entry["sequence"]:
                result.extend(
                    self._analyze_affix(sub, include_full=True, affix_type=affix_type)
                )
        elif "statements" in entry:
            for statement in entry["statements"]:
                class_str = statement.get("class")
                qid_str = statement.get("qid")
                if class_str and qid_str:
                    class_obj = class_dict.get(class_str)
                    if not class_obj:
                        raise ValueError(f"Unknown class: {class_str}")
                    qid = qid_dict.get(qid_str)
                    if not qid:
                        raise ValueError(f"Unknown QID: {qid_str}")
                    result.append((class_obj, qid))
        return result

    def analyze_prefix(
        self, prefix: str, include_full: bool = False
    ) -> list[tuple[type[cwd.ItemStatement], str]]:
        """
        Given a prefix string, return a list of (class, qid) if mapped, or an empty list if not mapped.
        Handles compound prefixes recursively.
        Raises ValueError if prefix is unknown.
        """
        return self._analyze_affix(
            prefix, include_full=include_full, affix_type="prefix"
        )

    def analyze_suffix(
        self, suffix: str, include_full: bool = False
    ) -> list[tuple[type[cwd.ItemStatement], str]]:
        """
        Given a suffix string, return a list of (class, qid) if mapped, or an empty list if not mapped.
        Handles compound suffixes recursively.
        Raises ValueError if suffix is unknown.
        """
        return self._analyze_affix(
            suffix, include_full=include_full, affix_type="suffix"
        )

    def get_prefixes(self):
        """
        Return all known prefix variants from the loaded data.
        """
        variants = set(self._prefix_variant_lookup.keys())
        return sorted(variants)

    def get_suffixes(self):
        """
        Return all known suffix variants from the loaded data.
        """
        variants = set(self._suffix_variant_lookup.keys())
        return sorted(variants)

    def get_allowed_suffix(
        self, suffix: str, include_full: bool = False
    ) -> Optional[str]:
        """
        Given a suffix string, return the allowed normalized suffix if known.
        Checks both variant and full lookups for suffix entries.
        """
        entry = None
        if include_full:
            entry = self._suffix_full_lookup.get(suffix)
        if not entry:
            entry = self._suffix_variant_lookup.get(suffix)
        if entry and "allowed" in entry:
            return entry["allowed"]
        return None


# Singleton/global instance for PrefixSuffixLookup
_prefix_suffix_lookup_instance = None


def get_prefix_suffix_lookup() -> PrefixSuffixLookup:
    """
    Returns a singleton instance of PrefixSuffixLookup.
    Only initializes once.
    """
    global _prefix_suffix_lookup_instance
    if _prefix_suffix_lookup_instance is None:
        _prefix_suffix_lookup_instance = PrefixSuffixLookup()
    return _prefix_suffix_lookup_instance


# Example usage:
# p = get_prefix_suffix_lookup()
# print("Known prefixes:", get_prefix_suffix_lookup().get_prefixes())
# print("Known suffixes:", get_prefix_suffix_lookup().get_suffixes())
