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
    "QID_COMPANION_OF_THE_ORDER_OF_ST_MICHAEL_AND_ST_GEORGE": wd.QID_COMPANION_OF_THE_ORDER_OF_ST_MICHAEL_AND_ST_GEORGE,
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

PREFIX_ENTRIES = [
    {"full": "Admiral"},
    {
        "variants": ["Baron"],
        "statements": [{"class": cwd.NobleTitle, "qid": wd.QID_BARON}],
    },
    {"full": "Bishop"},
    {"variants": ["Brig. Gen."], "long": "Brigadier General"},
    {"variants": ["Brig Gen", "BRIG GEN"], "long": "Brigadier General"},
    {"full": "Brigadier"},
    {
        "variants": ["Capt", "Capt.", "Captain", "Cpt.", "Capt .", "Cpt", "Cptn."],
        "long": "Captain",
    },
    {"full": "Capitain"},
    {"full": "Cannon"},
    {
        "variants": [
            "Col.",
            "Col",
            "Colonel",
            "Col. (USA)",
            "Col. (USA),",
        ],
        "long": "Colonel",
    },
    {
        "full": "Corporal",
        "variants": [
            "Cpl",
            "Cpl.",
        ],
    },
    {"full": "Commodore"},
    {"full": "Conte"},
    {"full": "Corporal"},
    {
        "variants": ["Count"],
        "statements": [{"class": cwd.NobleTitle, "qid": wd.QID_COUNT}],
    },
    {"variants": ["Dea."], "long": "Deacon", "full": "Deacon"},
    {"variants": ["Dr.", "Dr", "dr."]},
    {"variants": ["Dr.-Ing."], "long": "Doctor of Engineering"},
    {"variants": ["Dr. iur.", "Dr. jur."], "long": "Doctor of Law"},
    {"variants": ["Dr. Med."], "long": "Doctor of Medicine"},
    {"variants": ["Dr. med.", "Dr. Med."], "long": "Doctor of Medicine"},
    {"variants": ["Dr. Phil."], "long": "Doctor of Philosophy"},
    {"variants": ["Dr. theol."], "long": "Doctor of Theology"},
    {"variants": ["Drs."]},
    {"full": "Elder"},
    {"variants": ["Ens.", "Ens"], "long": "Ensign", "full": "Ensign"},
    {"variants": ["Esq.", "Esq"], "long": "Esquire"},
    {"variants": ["Fr."], "long": "Father/Friar"},
    {"full": "Don"},
    {"variants": ["Gov", "Gov."], "full": "Governor"},
    {"variants": ["Gen."], "full": "General"},
    {"full": "Graf"},
    {
        "variants": ["Hon", "Hon.", "Honorable"],
        "long": "Honorable",
        "statements": [{"class": cwd.HonorificPrefix, "qid": wd.QID_THE_HONOURABLE}],
    },
    {"variants": ["Ir."], "long": "Engineer"},
    {"variants": ["Ing.", "Ing"], "long": "Engineer"},
    {"full": "Kolonel"},
    {"variants": ["Corp."], "long": "Corporal"},
    {"variants": ["Judge"], "long": "Judge"},
    {
        "variants": ["Jonkheer", "Jhr.", "Jhr", "Jhvr.", "Jhvr", "Jkvr."],
        "long": "Jonkheer",
        "statements": [{"class": cwd.NobleTitle, "qid": wd.QID_JONKHEER}],
    },
    {
        "variants": [
            "Lieut.",
            "Lieut",
            "Lt",
            "Lt.",
            "Lieutenant",
            "Lieu.",
            "LT.",
            "Liet.",
        ],
        "long": "Lieutenant",
    },
    {"variants": ["Lt. Deacon"], "long": "Lieutenant Deacon"},
    {"variants": ["Lt.-Gen."], "long": "Lieutenant General"},
    {"variants": ["Lt.-Gen.", "Lt.-Gen"], "long": "Lieutenant General"},
    {
        "variants": [
            "Lt.-Col.",
            "Lt. Col.",
            "Lt Col",
            "LtCol",
            "Lieut-Col",
            "Lt.Col",
            "Lieut-Col.",
            "Lieut.-Col.",
            "Lt Colonel",
            "Lt.Col.",
        ],
        "long": "Lieutenant Colonel",
    },
    {"variants": ["Maj."], "long": "Major", "full": "Major"},
    {"variants": ["Maj Gen", "Maj-Gen", "Maj-Gen.", "MajGen"], "long": "Major General"},
    {"variants": ["Maj-Gen.", "Maj Gen", "Maj-Gen", "MajGen"], "long": "Major General"},
    {"variants": ["Maj. Sir", "Major Sir"], "sequence": ["Maj.", "Sir"]},
    {"variants": ["Mevr."]},
    {"variants": ["Mr", "Mr.", "mr."]},
    {"variants": ["Mr. Dr."], "sequence": ["Mr.", "Dr."]},
    {"variants": ["Mrs."]},
    {"variants": ["Nob.", "Nob. Huomo"], "long": "Noble"},
    # misspelling of Mr.
    {"variants": ["Nr."]},
    {
        "variants": ["Pvt.", "Pvt"],
        "long": "Private",
        "statements": [{"class": cwd.HonorificPrefix, "qid": wd.QID_PRIVATE}],
    },
    {"full": "Prince"},
    {"variants": ["Prof.", "Professor", "Prof"], "long": "Professor"},
    {
        "variants": ["Rabbi"],
        "statements": [{"class": cwd.HonorificPrefix, "qid": wd.QID_RABBI}],
    },
    {
        "variants": ["Rev.", "Rev", "Reverend"],
        "long": "Reverend",
        "statements": [{"class": cwd.HonorificPrefix, "qid": wd.QID_REVEREND}],
    },
    {
        "variants": ["Rt. Rev.", "Rt.Rev", "Rt.Rev."],
        "long": "Right Reverend",
        "statements": [
            {"class": cwd.HonorificPrefix, "qid": wd.QID_THE_RIGHT_REVEREND}
        ],
    },
    {"variants": ["Sgt", "Sgt.", "SGT", "Sergeant"], "long": "Sergeant"},
    {
        "variants": ["Sir"],
        "statements": [{"class": cwd.HonorificPrefix, "qid": wd.QID_SIR}],
    },
    {"variants": ["Surg.-Capt."], "long": "Surgeon Captain"},
    {"full": "Sheriff"},
    {"variants": ["Rep."], "long": "Representative"},
    {"variants": ["R Adm", "Rear Adm"], "long": "Rear Admiral"},
    {"variants": ["Rt-Hon."], "long": "Right Honourable"},
    {"variants": ["Sen."], "long": "Senator"},
    # ---- All "sequence" entries at the end ----
    {"variants": ["Prof. Dr.-Ing."], "sequence": ["Prof.", "Dr.-Ing."]},
    {"variants": ["Prof. Ds."], "sequence": ["Prof.", "Ds."]},
    {"variants": ["Prof. Jhr. Dr."], "sequence": ["Prof.", "Jhr.", "Dr."]},
    {"variants": ["Prof. Mr."], "sequence": ["Prof.", "Mr."]},
    {"variants": ["Prof. Dr."], "sequence": ["Prof.", "Dr."]},
    {"variants": ["Col Hon"], "sequence": ["Col", "Hon."]},
    {"variants": ["Col. Sir"], "sequence": ["Col", "Sir"]},
    {"variants": ["Jhr. Dr."], "sequence": ["Jhr.", "Dr."]},
    {"variants": ["Jhr. Ir."], "sequence": ["Jhr.", "Ir."]},
    {"variants": ["Jhr. Mr."], "sequence": ["Jhr.", "Mr."]},
    {"variants": ["Jhr. Mr. Dr."], "sequence": ["Jhr.", "Mr.", "Dr."]},
    {"variants": ["Maj. Sir", "Major Sir"], "sequence": ["Maj.", "Sir"]},
    {"variants": ["Mr. Dr."], "sequence": ["Mr.", "Dr."]},
    {"variants": ["Prof. Dr.-Ing."], "sequence": ["Prof.", "Dr.-Ing."]},
    {"variants": ["Prof. Ds."], "sequence": ["Prof.", "Ds."]},
    {"variants": ["Prof. Jhr. Dr."], "sequence": ["Prof.", "Jhr.", "Dr."]},
    {"variants": ["Prof. Mr."], "sequence": ["Prof.", "Mr."]},
    {"variants": ["Prof. Dr."], "sequence": ["Prof.", "Dr."]},
    {"variants": ["Rev. Canon"], "sequence": ["Rev.", "Canon"]},
    {"variants": ["Rev. Dr."], "sequence": ["Rev.", "Dr."]},
    {"variants": ["Rev. Dr. magister"], "sequence": ["Rev.", "Dr.", "magister"]},
    {"variants": ["Rev. Pastor"], "sequence": ["Rev.", "Pastor"]},
    {"variants": ["Rev. Sir"], "sequence": ["Rev.", "Sir"]},
]


SUFFIX_ENTRIES = [
    {
        "variants": ["Jr", "Jr."],
        "allowed": "Jr.",
    },
    {
        "variants": ["Sr", "Sr."],
        "allowed": "Sr.",
    },
    {
        "variants": ["I"],
        "allowed": "I",
    },
    {
        "variants": ["II"],
        "allowed": "II",
    },
    {
        "variants": ["III"],
        "allowed": "III",
    },
    {
        "variants": ["IV"],
        "allowed": "IV",
    },
    {
        "variants": ["V"],
        "allowed": "V",
    },
    {
        "variants": ["MD", "M.D."],
        "long": "Doctor of Medicine",
        "statements": [
            {
                "class": cwd.AcademicDegree,
                "qid": wd.QID_DOCTOR_OF_MEDICINE,
            }
        ],
    },
    {
        "variants": ["FASG"],
        "long": "Fellow of the American Society of Genealogists",
        "statements": [
            {
                "class": cwd.MemberOf,
                "qid": wd.QID_AMERICAN_SOCIETY_OF_GENEALOGISTS,
            },
            {
                "class": cwd.AwardReceived,
                "qid": wd.QID_FELLOW_OF_THE_AMERICAN_SOCIETY_OF_GENEALOGISTS,
            },
        ],
    },
    {
        "variants": ["OBE", "O.B.E."],
        "long": "Officer of the Order of the British Empire",
        "statements": [
            {
                "class": cwd.AwardReceived,
                "qid": wd.QID_OFFICER_OF_THE_ORDER_OF_THE_BRITISH_EMPIRE,
            },
        ],
    },
    {
        "variants": ["CBE", "C.B.E."],
        "long": "Commander of the Order of the British Empire",
        "statements": [
            {
                "class": cwd.AwardReceived,
                "qid": wd.QID_COMMANDER_OF_THE_ORDER_OF_THE_BRITISH_EMPIRE,
            },
        ],
    },
    {
        "variants": ["MBE", "M.B.E."],
        "long": "Member of the Order of the British Empire",
        "statements": [
            {
                "class": cwd.AwardReceived,
                "qid": wd.QID_MEMBER_OF_THE_ORDER_OF_THE_BRITISH_EMPIRE,
            },
        ],
    },
    {
        "variants": ["KBE", "K.B.E."],
        "long": "Knight Commander of the Order of the British Empire",
        "statements": [
            {
                "class": cwd.AwardReceived,
                "qid": wd.QID_KNIGHT_COMMANDER_OF_THE_ORDER_OF_THE_BRITISH_EMPIRE,
            },
        ],
    },
    {
        "variants": ["FRS"],
        "long": "Fellow of the Royal Society",
        "statements": [
            {
                "class": cwd.AwardReceived,
                "qid": wd.QID_FELLOW_OF_THE_ROYAL_SOCIETY,
            },
        ],
    },
    {
        "variants": ["FRSC"],
        "long": "Fellow of the Royal Society of Canada",
        "statements": [
            {
                "class": cwd.AwardReceived,
                "qid": wd.QID_FELLOW_OF_THE_ROYAL_SOCIETY_OF_CANADA,
            },
        ],
    },
    {
        "variants": ["CMG"],
        "long": "Companion of the Order of St Michael and St George",
        "statements": [
            {
                "class": cwd.AwardReceived,
                "qid": wd.QID_COMPANION_OF_THE_ORDER_OF_ST_MICHAEL_AND_ST_GEORGE,
            },
        ],
    },
    {
        "variants": ["D.D."],
        "long": "Doctor of Divinity",
        "statements": [
            {
                "class": cwd.AcademicDegree,
                "qid": wd.QID_DOCTOR_OF_DIVINITY,
            },
        ],
    },
    {
        "variants": ["M.A.", "MA"],
        "long": "Master of Arts",
    },
    {
        "variants": ["LL.D."],
        "long": "Legum Doctor (Doctor of Laws)",
        "statements": [
            {
                "class": cwd.AwardReceived,
                "qid": wd.QID_LEGUM_DOCTOR,
            },
        ],
    },
    {
        "variants": ["RN"],
        "long": "Royal Navy",
        "statements": [
            {
                "class": cwd.MilitaryBranch,
                "qid": wd.QID_ROYAL_NAVY,
            },
        ],
    },
    {
        "variants": ["Esq", "Esq."],
        "statements": [
            {
                "class": cwd.HonorificSuffix,
                "qid": wd.QID_ESQUIRE,
            }
        ],
    },
    {
        "variants": ["AB"],
        "long": "Artium Baccalaureus” (Bachelor of Arts) - Latin",
    },
    {
        "variants": ["Bt", "5th Bt"],
        "long": "Baronet",
        "statements": [
            {
                "class": cwd.NobleTitle,
                "qid": wd.QID_BARONET,
            },
        ],
    },
]


def _analyze_affix(
    affix: str, entries, include_full: bool = False, affix_type: str = "affix"
):
    """
    Generic function to analyze a prefix or suffix.
    """
    for entry in entries:
        if include_full and "full" in entry and affix == entry["full"]:
            pass
        elif affix not in entry.get("variants", []):
            continue

        result = []
        if "sequence" in entry:
            for sub in entry["sequence"]:
                sub_result = _analyze_affix(
                    sub, entries, include_full=True, affix_type=affix_type
                )
                if sub_result:
                    result.extend(sub_result)
        else:
            statements = entry.get("statements")
            if statements:
                for statement in statements:
                    clss = statement.get("class")
                    qid = statement.get("qid")
                    if clss and qid:
                        item = (clss, qid)
                        result.append(item)
        return result
    raise ValueError(f"Unknown {affix_type}: {affix}")


def analyze_prefix(prefix: str, include_full: bool = False):
    """
    Given a prefix string, return a list [class, qid] if mapped, or an empty list if not mapped.
    Handles compound prefixes recursively.
    Raises ValueError if prefix is unknown.
    """
    return _analyze_affix(
        prefix, PREFIX_ENTRIES, include_full=include_full, affix_type="prefix"
    )


def analyze_suffix(suffix: str, include_full: bool = False):
    """
    Given a suffix string, return a list [class, qid] if mapped, or an empty list if not mapped.
    Handles compound suffixes recursively.
    Raises ValueError if suffix is unknown.
    """
    return _analyze_affix(
        suffix, SUFFIX_ENTRIES, include_full=include_full, affix_type="suffix"
    )


def get_prefixes():
    return [
        variant for entry in PREFIX_ENTRIES for variant in entry.get("variants", [])
    ]


def get_suffixes():
    return [
        variant for entry in SUFFIX_ENTRIES for variant in entry.get("variants", [])
    ]


def get_allowed_suffix(suffix: str, include_full: bool = False) -> Optional[str]:
    """
    Given a suffix string, return the allowed normalized suffix if known
    """
    if not suffix:
        return None
    for entry in SUFFIX_ENTRIES:
        if suffix in entry["variants"]:
            return entry.get("allowed")
    raise ValueError(f"Unknown suffix: {suffix}")


def prefixes_to_json():
    # Build a JSON-serializable dictionary of prefix entries, merging duplicates.
    result = {}
    for list in (PREFIX_ENTRIES, SUFFIX_ENTRIES):
        for entry in list:
            if "full" in entry:
                key = entry["full"]
            elif "long" in entry:
                key = entry["long"]
            elif "variants" in entry and entry["variants"]:
                key = entry["variants"][0]
            else:
                raise ValueError(f"Invalid prefix entry: {entry}")
            existing = result.get(key)
            if existing:
                if "full" in entry and "full" in existing:
                    if entry["full"] != existing["full"]:
                        raise ValueError(f"Duplicate prefix full: {entry['full']}")
                if "long" in entry and "long" in existing:
                    if existing["long"]:
                        if entry["long"] != existing["long"]:
                            raise ValueError(f"Duplicate prefix long: {entry['long']}")
                if "allowed" in entry and "allowed" in existing:
                    if entry["allowed"] != existing["allowed"]:
                        raise ValueError(
                            f"Duplicate prefix allowed: {entry['allowed']}"
                        )
                if "sequence" in entry and "sequence" in existing:
                    if entry["sequence"] != existing["sequence"]:
                        raise ValueError(
                            f"Duplicate prefix sequence: {entry['sequence']}"
                        )
                variants = set(existing.get("variants", []))
                variants.update(entry.get("variants", []))

                existing["full"] = existing.get("full") or entry.get("full")
                existing["long"] = existing.get("long") or entry.get("long")
                existing["allowed"] = existing.get("allowed") or entry.get("allowed")
                existing["sequence"] = existing.get("sequence") or entry.get("sequence")
                existing["variants"] = sorted(variants)
                # statements handled below
            else:
                # Only include serializable fields and initialize statements as empty list
                result[key] = {
                    "full": entry.get("full"),
                    "long": entry.get("long"),
                    "allowed": entry.get("allowed"),
                    "sequence": entry.get("sequence"),
                    "variants": entry.get("variants", []),
                    "statements": [],
                }
            if list is SUFFIX_ENTRIES:
                result[key]["suffix"] = True
            if list is PREFIX_ENTRIES:
                result[key]["prefix"] = True

            # Add statements in a JSON-serializable way
            for statement in entry.get("statements", []):
                clss = statement.get("class")
                qid = statement.get("qid")
                if clss and qid:
                    class_name = clss.__name__
                    if class_name not in class_dict:
                        raise RuntimeError(f"Class {class_name} not in class_dict")
                    qid_c = None
                    for p in qid_dict:
                        if qid == qid_dict[p]:
                            qid_c = p
                            break
                    if not qid_c:
                        raise RuntimeError(f"QID {qid} not in qid_dict")
                    item = {"class": class_name, "qid": qid_c}
                    statements = result[key].get("statements", [])
                    if item not in statements:
                        statements.append(item)
                        result[key]["statements"] = statements

            # Remove statements key if empty for cleaner output
            # if not result[key]["statements"]:
            #     del result[key]["statements"]

    for key in result:
        # Sort variants for consistency
        if "variants" in result[key]:
            result[key]["variants"] = sorted(result[key]["variants"])
        # Sort statements by class name and qid for consistency
        if "statements" in result[key]:
            statements = result[key]["statements"]
            statements.sort(key=lambda x: (x["class"], x["qid"]))

        if not result[key]["statements"]:
            del result[key]["statements"]
        if not result[key]["full"]:
            del result[key]["full"]
        if not result[key]["long"]:
            del result[key]["long"]
        if not result[key]["allowed"]:
            del result[key]["allowed"]
        if not result[key]["sequence"]:
            del result[key]["sequence"]
        if not result[key]["variants"]:
            del result[key]["variants"]
    return result


def main():
    print(json.dumps(prefixes_to_json(), indent=2))
    # save to json file
    path = JSON_DIR / "prefix_suffix.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(prefixes_to_json(), f, indent=2, ensure_ascii=False)


class PrefixSuffixLookup:
    """
    Loads and indexes prefix/suffix data from a JSON file for fast lookup.
    """

    def __init__(self, json_path: Optional[Path] = None):
        if json_path is None:
            json_path = JSON_DIR / "prefix_suffix.json"
        with open(json_path, encoding="utf-8") as f:
            prefix_data = json.load(f)
        # Build two lookup dicts: one for 'full', one for 'variants'
        self._full_lookup = {}
        self._variant_lookup = {}
        for key, entry in prefix_data.items():
            # Add the 'full' field if present and unique
            if "full" in entry and entry["full"]:
                self._full_lookup[entry["full"]] = entry
            # Add all variants
            for variant in entry.get("variants", []):
                self._variant_lookup[variant] = entry

    def analyze_prefix(
        self, prefix: str, include_full: bool = False
    ) -> list[tuple[str, str]]:
        """
        Given a prefix string, return a list of (class, qid) if mapped, or an empty list if not mapped.
        Handles compound prefixes recursively.
        Raises ValueError if prefix is unknown.
        """
        entry = None
        if include_full:
            entry = self._full_lookup.get(prefix)
        if not entry:
            entry = self._variant_lookup.get(prefix)
        if not entry:
            raise ValueError(f"Unknown prefix: {prefix}")

        result = []
        # Handle sequence recursively
        if "sequence" in entry:
            for sub in entry["sequence"]:
                result.extend(self.analyze_prefix(sub, include_full=True))
        elif "statements" in entry:
            for statement in entry["statements"]:
                clss = statement.get("class")
                qid = statement.get("qid")
                if clss and qid:
                    result.append((clss, qid))
        return result


if __name__ == "__main__":
    main()
