import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
from typing import Optional, Set


PREFIX_ENTRIES = [
    {
        "variants": ["Brig. Gen."],
        "long": "Brigadier General",
    },
    {
        "variants": ["Capt", "Capt.", "Captain"],
        "long": "Captain",
    },
    {
        "variants": ["Ensign", "Ens."],
        "long": "Ensign",
    },
    {
        "variants": ["Col.", "Col", "Colonel", "Col. (USA)", "Col. (USA),"],
        "long": "Colonel",
    },
    {
        "variants": ["Count"],
        "statements": [
            {
                "class": cwd.NobleTitle,
                "qid": wd.QID_COUNT,
            }
        ],
    },
    {
        "variants": ["Deacon", "Dea."],
        "long": "Deacon",
    },
    {
        "variants": ["Dr.", "Dr", "dr."],
    },
    {
        "variants": ["Brig Gen", "BRIG GEN"],
        "long": "Brigadier General",
    },
    {
        "variants": ["Gen."],
        "long": "General",
    },
    {
        "variants": ["Pvt."],
        "long": "Private",
        "statements": [
            {
                "class": cwd.HonorificPrefix,
                "qid": wd.QID_PRIVATE,
            }
        ],
    },
    {
        "variants": ["Hon", "Hon.", "Honorable"],
        "long": "Honorable",
        "statements": [
            {
                "class": cwd.HonorificPrefix,
                "qid": wd.QID_THE_HONOURABLE,
            }
        ],
    },
    {
        "variants": ["Jonkheer", "Jhr.", "Jhr", "Jhvr.", "Jhvr"],
        "long": "Jonkheer",
        "statements": [
            {
                "class": cwd.NobleTitle,
                "qid": wd.QID_JONKHEER,
            }
        ],
    },
    {
        "variants": ["Judge"],
        "long": "Judge",
    },
    {
        "variants": ["Lieut.", "Lieut", "Lt", "Lt.", "Lieutenant", "Lieu."],
        "long": "Lieutenant",
    },
    {
        "variants": ["Lt. Deacon"],
        "long": "Lieutenant Deacon",
    },
    {
        "variants": ["Lt.-Col.", "Lt. Col.", "Lt Col", "LtCol", "Lieut-Col", "Lt.Col"],
        "long": "Lieutenant Colonel",
    },
    {
        "variants": ["Maj."],
        "long": "Major",
    },
    {
        "variants": ["Maj Gen", "Maj-Gen"],
        "long": "Major General",
    },
    {
        "variants": ["Mr", "Mr.", "mr."],
    },
    {
        "variants": ["Dr.-Ing."],
        "long": "Doctor of Engineering",
    },
    {
        "variants": ["Dr. iur.", "Dr. jur."],
        "long": "Doctor of Law",
    },
    
    {
        "variants": ["Mr. Dr."],
        "sequence": ["Mr.", "Dr."],
    },
    {
        "variants": ["Rev. Dr."],
        "sequence": ["Rev.", "Dr."],
    },
    {
        "variants": ["Prof. Dr.-Ing."],
        "sequence": ["Prof.", "Dr.-Ing."],
    },
    {
        "variants": ["Prof. Ds."],
        "sequence": ["Prof.", "Ds."],
    },
    {
        "variants": ["Prof. Jhr. Dr."],
        "sequence": ["Prof.", "Jhr.", "Dr."],
    },
    {
        "variants": ["Prof. Mr."],
        "sequence": ["Prof.", "Mr."],
    },
    {
        "variants": ["Mevr."],
    },
    {
        "variants": ["Prof.", "Professor", "Prof"],
        "long": "Professor",
    },
    {
        "variants": ["Prof. Dr."],
        "sequence": ["Prof.", "Dr."],
    },
    {
        "variants": ["Rabbi"],
        "statements": [
            {
                "class": cwd.HonorificPrefix,
                "qid": wd.QID_RABBI,
            }
        ],
    },
    {
        "variants": ["Rev.", "Rev", "Reverend"],
        "long": "Reverend",
        "statements": [
            {
                "class": cwd.HonorificPrefix,
                "qid": wd.QID_REVEREND,
            }
        ],
    },
    {
        "variants": ["Rt. Rev."],
        "long": "Right Reverend",
        "statements": [
            {
                "class": cwd.HonorificPrefix,
                "qid": wd.QID_THE_RIGHT_REVEREND,
            }
        ],
    },
    {
        "variants": ["Surg.-Capt."],
        "long": "Surgeon Captain",
    },
    {
        "variants": ["Sgt", "Sgt.", "SGT", "Sergeant"],
        "long": "Sergeant",
    },
    {
        "variants": ["Mrs."],
    },
    {
        "variants": ["Gov."],
    },
    {
        "variants": ["Ds."],
    },
    {
        "variants": ["Ir."],
    },
    {
        "variants": ["Jhr. Mr. Dr."],
        "sequence": ["Jhr.", "Mr.", "Dr."],
    },
    {
        "variants": ["Jhr. Mr."],
        "sequence": ["Jhr.", "Mr."],
    },
    {
        "variants": ["Jhr. Ir."],
        "sequence": ["Jhr.", "Ir."],
    },
    {
        "variants": ["Sir"],
        "statements": [
            {
                "class": cwd.HonorificPrefix,
                "qid": wd.QID_SIR,
            }
        ],
    },
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
        "long": "Order of the British Empire",
        "statements": [
            {
                "class": cwd.AwardReceived,
                "qid": wd.QID_OFFICER_OF_THE_ORDER_OF_THE_BRITISH_EMPIRE,
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
        "variants": ["RN"],
        "long": "Doctor of Divinity",
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
]


def analyze_prefix(prefix: str):
    """
    Given a prefix string, return a list [class, qid] if mapped, or an empty list if not mapped.
    Handles compound prefixes recursively.
    Raises ValueError if prefix is unknown.
    """
    for entry in PREFIX_ENTRIES:
        if prefix not in entry["variants"]:
            continue

        # Handle compound prefixes (e.g., "Prof. Dr.")
        result = []
        if "sequence" in entry:
            for sub in entry["sequence"]:
                sub_result = analyze_prefix(sub)
                if sub_result:
                    result.extend(sub_result)
        else:
            statements = entry.get("statements")
            if statements:
                for statement in statements:
                    clss = statement.get("class")
                    qid = statement.get("qid")
                    if clss and qid:
                        item = (
                            clss,
                            qid,
                        )
                        result.append(item)
        return result
    raise ValueError(f"Unknown prefix: {prefix}")


def analyze_suffix(suffix: str):
    """
    Given a suffix string, return a list [class, qid] if mapped, or an empty list if not mapped.
    Handles compound suffixes recursively.
    Raises ValueError if suffix is unknown.
    """
    for entry in SUFFIX_ENTRIES:
        if suffix not in entry["variants"]:
            continue

        # Handle compound suffixes (e.g., "Prof. Dr.")
        result = []
        if "sequence" in entry:
            for sub in entry["sequence"]:
                sub_result = analyze_suffix(sub)
                if sub_result:
                    result.extend(sub_result)
        else:
            statements = entry.get("statements")
            if statements:
                for statement in statements:
                    clss = statement.get("class")
                    qid = statement.get("qid")
                    if clss and qid:
                        item = (
                            clss,
                            qid,
                        )
                        result.append(item)
        return result
    raise ValueError(f"Unknown suffix: {suffix}")

def get_allowed_suffix(suffix: str) -> Optional[str]:
    """
    Given a suffix string, return the allowed normalized suffix if known
    """
    if not suffix:
        return None
    for entry in SUFFIX_ENTRIES:
        if suffix in entry["variants"]:
            return entry.get("allowed")
    raise ValueError(f"Unknown suffix: {suffix}")


def get_prefixes():
    return [variant for entry in PREFIX_ENTRIES for variant in entry["variants"]]


def get_suffixes():
    return [variant for entry in SUFFIX_ENTRIES for variant in entry["variants"]]


# # Maps long prefix to (class, qid) or None if not mapped
# PREFIX_TO_CLASS_QID = {
#     "Brigadier General": None,
#     "Captain": None,
#     "Colonel": None,
#     "Count": (cwd.NobleTitle, wd.QID_COUNT),
#     "Deacon": None,
#     "Dr": None,
#     "General": None,
#     "Honorable": (cwd.HonorificPrefix, wd.QID_THE_HONOURABLE),
#     "Jonkheer": (cwd.NobleTitle, wd.QID_JONKHEER),
#     "Judge": None,
#     "Lieutenant": None,
#     "Lieutenant Deacon": None,
#     "Major": None,
#     "Mr": None,
#     "Professor": None,
#     "Rabbi": (cwd.HonorificPrefix, wd.QID_RABBI),
#     "Reverend": (cwd.HonorificPrefix, wd.QID_REVEREND),
#     "Sergeant": None,
#     "Sir": (cwd.HonorificPrefix, wd.QID_SIR),
# }
