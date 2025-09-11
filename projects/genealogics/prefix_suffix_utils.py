import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd


PREFIX_ENTRIES = [
    {
        "variants": ["Brig. Gen."],
        "normalized": "Brigadier General",
        "class": None,
        "qid": None,
    },
    {
        "variants": ["Capt", "Capt.", "Captain"],
        "normalized": "Captain",
        "class": None,
        "qid": None,
    },
    {
        "variants": ["Ensign"],
        "normalized": "Ensign",
        "class": None,
        "qid": None,
    },
    {
        "variants": ["Col.", "Col", "Colonel"],
        "normalized": "Colonel",
        "class": None,
        "qid": None,
    },
    {
        "variants": ["Count"],
        "normalized": "Count",
        "class": cwd.NobleTitle,
        "qid": wd.QID_COUNT,
    },
    {"variants": ["Deacon"], "normalized": "Deacon", "class": None, "qid": None},
    {"variants": ["Dr.", "Dr"], "normalized": "Dr", "class": None, "qid": None},
    {"variants": ["Gen."], "normalized": "General", "class": None, "qid": None},
    {
        "variants": ["Hon", "Hon."],
        "normalized": "Honorable",
        "class": cwd.HonorificPrefix,
        "qid": wd.QID_THE_HONOURABLE,
    },
    {
        "variants": ["Jonkheer"],
        "normalized": "Jonkheer",
        "class": cwd.NobleTitle,
        "qid": wd.QID_JONKHEER,
    },
    {"variants": ["Judge"], "normalized": "Judge", "class": None, "qid": None},
    {
        "variants": ["Lieut.", "Lieut", "Lt", "Lt.", "Lieutenant"],
        "normalized": "Lieutenant",
        "class": None,
        "qid": None,
    },
    {
        "variants": ["Lt. Deacon"],
        "normalized": "Lieutenant Deacon",
        "class": None,
        "qid": None,
    },
    {"variants": ["Maj."], "normalized": "Major", "class": None, "qid": None},
    {"variants": ["Mr", "Mr."], "normalized": "Mr", "class": None, "qid": None},
    {
        "variants": ["Prof.", "Professor"],
        "normalized": "Professor",
        "class": None,
        "qid": None,
    },
    {"variants": ["Prof. Dr."], "compound": ["Prof.", "Dr."]},
    {
        "variants": ["Rabbi"],
        "normalized": "Rabbi",
        "class": cwd.HonorificPrefix,
        "qid": wd.QID_RABBI,
    },
    {
        "variants": ["Rev.", "Rev", "Reverend"],
        "normalized": "Reverend",
        "class": cwd.HonorificPrefix,
        "qid": wd.QID_REVEREND,
    },
    {"variants": ["Sgt", "Sgt."], "normalized": "Sergeant", "class": None, "qid": None},
    {"variants": ["Mrs."], "normalized": "Mrs.", "class": None, "qid": None},
    {
        "variants": ["Sir"],
        "normalized": "Sir",
        "class": cwd.HonorificPrefix,
        "qid": wd.QID_SIR,
    },
    # Add more as needed
]

SUFFIX_ENTRIES = [
    {
        "variants": ["Jr", "Jr."],
        "normalized": "Jr.",
        "class": None,
        "qid": None,
    },
    {
        "variants": ["Sr", "Sr."],
        "normalized": "Sr.",
        "class": None,
        "qid": None,
    },
    {
        "variants": ["I"],
        "normalized": "I",
        "class": None,
        "qid": None,
    },
    {
        "variants": ["II"],
        "normalized": "II",
        "class": None,
        "qid": None,
    },
    {
        "variants": ["III"],
        "normalized": "III",
        "class": None,
        "qid": None,
    },
    {
        "variants": ["MD"],
        "normalized": "Doctor of Medicine",
        "class": cwd.AcademicDegree,
        "qid": wd.QID_DOCTOR_OF_MEDICINE,
    },
]


def analyze_prefix(prefix: str):
    """
    Given a prefix string, return a list [class, qid] if mapped, or an empty list if not mapped.
    Handles compound prefixes recursively.
    Raises ValueError if prefix is unknown.
    """
    for entry in PREFIX_ENTRIES:
        if prefix in entry["variants"]:
            # Handle compound prefixes (e.g., "Prof. Dr.")
            if "compound" in entry:
                result = []
                for sub in entry["compound"]:
                    sub_result = analyze_prefix(sub)
                    if sub_result:
                        result.extend(sub_result)
                return result

            clss = entry.get("class")
            qid = entry.get("qid")
            if clss and qid:
                item = (
                    clss,
                    qid,
                )
                return [item]
            return []
    raise ValueError(f"Unknown prefix: {prefix}")


def analyze_suffix(suffix: str):
    """
    Given a suffix string, return a list [class, qid] if mapped, or an empty list if not mapped.
    Handles compound suffixes recursively.
    Raises ValueError if suffix is unknown.
    """
    for entry in SUFFIX_ENTRIES:
        if suffix in entry["variants"]:
            # Handle compound suffixes (e.g., "Prof. Dr.")
            if "compound" in entry:
                result = []
                for sub in entry["compound"]:
                    sub_result = analyze_suffix(sub)
                    if sub_result:
                        result.extend(sub_result)
                return result

            clss = entry.get("class")
            qid = entry.get("qid")
            if clss and qid:
                item = (
                    clss,
                    qid,
                )
                return [item]
            return []
    raise ValueError(f"Unknown suffix: {suffix}")


def get_prefixes():
    return [variant for entry in PREFIX_ENTRIES for variant in entry["variants"]]


def get_suffixes():
    return [variant for entry in SUFFIX_ENTRIES for variant in entry["variants"]]


# # Maps normalized prefix to (class, qid) or None if not mapped
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
