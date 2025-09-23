import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
from typing import Optional, Set

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
            "Cpl",
            "Cpl.",
        ],
        "long": "Colonel",
    },
    {"full": "Commander"},
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
    result = {}
    for entry in PREFIX_ENTRIES:
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
                if entry["long"] != existing["long"]:
                    raise ValueError(f"Duplicate prefix long: {entry['long']}")
            if "allowed" in entry and "allowed" in existing:
                if entry["allowed"] != existing["allowed"]:
                    raise ValueError(f"Duplicate prefix allowed: {entry['allowed']}")
            if "sequence" in entry and "sequence" in existing:
                if entry["sequence"] != existing["sequence"]:
                    raise ValueError(f"Duplicate prefix sequence: {entry['sequence']}")
            variants = set(existing.get("variants", []))
            variants.update(entry.get("variants", []))

            existing["full"] = existing.get("full") or entry.get("full")
            existing["long"] = existing.get("long") or entry.get("long")
            existing["allowed"] = existing.get("allowed") or entry.get("allowed")
            existing["sequence"] = existing.get("sequence") or entry.get("sequence")
            existing["variants"] = sorted(variants)
            # statements

    return result


def main():
    print(prefixes_to_json())
