import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd


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
        "variants": ["Dr.", "Dr"],
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
        "variants": ["Hon", "Hon."],
        "long": "Honorable",
        "statements": [
            {
                "class": cwd.HonorificPrefix,
                "qid": wd.QID_THE_HONOURABLE,
            }
        ],
    },
    {
        "variants": ["Jonkheer", "Jhr.", "Jhr"],
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
        "variants": ["Lt.-Col.", "Lt. Col."],
        "long": "Lieutenant Colonel",
    },
    {
        "variants": ["Maj."],
        "long": "Major",
    },
    {
        "variants": ["Mr", "Mr."],
    },
    {
        "variants": ["Mevr."],
    },
    {
        "variants": ["Prof.", "Professor"],
        "long": "Professor",
    },
    {
        "variants": ["Prof. Dr."],
        "compound": ["Prof.", "Dr."],
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
        "variants": ["Sgt", "Sgt."],
        "long": "Sergeant",
    },
    {
        "variants": ["Mrs."],
    },
    {
        "variants": ["Jhr. Mr. Dr."],
        "compound": ["Jhr.", "Mr.", "Dr."],
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
    # Add more as needed
]

SUFFIX_ENTRIES = [
    {
        "variants": ["Jr", "Jr."],
        "normalized": "Jr.",
    },
    {
        "variants": ["Sr", "Sr."],
        "normalized": "Sr.",
    },
    {
        "variants": ["I"],
    },
    {
        "variants": ["II"],
    },
    {
        "variants": ["III"],
    },
    {
        "variants": ["V"],
    },
    {
        "variants": ["MD"],
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
        if "compound" in entry:
            for sub in entry["compound"]:
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
        if "compound" in entry:
            for sub in entry["compound"]:
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
