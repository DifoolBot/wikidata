import re
import shared_lib.constants as wd
import shared_lib.change_wikidata as cwd
from shared_lib.lookups.interfaces.place_lookup_interface import PlaceLookupInterface

TITLE_ENTRIES = [
    {
        "variants": ["Minister"],
        "occupation": wd.QID_CHRISTIAN_MINISTER,
        "place_class": cwd.WorkLocation,
        "error_if_number": True,
    },
    {
        "variants": ["Rector"],
        # can be academic or religious
        # "occupation": wd.QID_CHRISTIAN_MINISTER,
        "place_class": cwd.WorkLocation,
        "error_if_number": True,
    },
    {"variants": ["Heer"], "error_if_number": True},
    {
        "variants": ["Baronet"],
        "noble_title": wd.QID_BARONET,
    },
    {
        "variants": ["Duke"],
        "noble_title": wd.QID_DUKE,
    },
]


def parse_title_text(text: str):
    # english
    pattern = r"^(?:(\d+(?:st|nd|rd|th))\s+)?([A-Z][a-z]+)\s*(?:of\s+(.+))?$"
    match = re.match(pattern, text)
    if not match:
        # dutch
        pattern = r"^(?:(\d+(?:st|nd|rd|th))\s+)?([A-Z][a-z]+)(?:\s+van\s+(.+))?$"
        match = re.match(pattern, text)
    if match:
        number = match.group(1)  # May be None
        title = match.group(2)
        place = match.group(3)  # May be None
        return number, title, place
    return None


def extract_title(text):
    info = parse_title_text(text)
    if info:
        return text
    return None


def analyze_title(place_lookup: PlaceLookupInterface, text: str, lived_in: str):
    result = []
    info = parse_title_text(text)
    if not info:
        raise ValueError(f"Unknown title: {text}")

    number, title, place = info
    for entry in TITLE_ENTRIES:
        if title not in entry["variants"]:
            continue
        b = entry.get("error_if_number", False)
        if b and number:
            raise ValueError(f"Unexpected number in title: {text}")
        occupation = entry.get("occupation")
        if occupation:
            result.append(cwd.Occupation(qid=occupation))
        noble_title = entry.get("noble_title")
        if noble_title:
            result.append(cwd.NobleTitle(qid=noble_title))
        place_class = entry.get("place_class")
        if place_class and place:
            if lived_in:
                place = f"{place}, {lived_in}"
            place_qid = place_lookup.get_place_qid_by_desc(place)
            if not place_qid:
                raise ValueError(f"Unknown place in title: {place}")
            result.append(place_class(qid=place_qid))
        return result

    raise ValueError(f"Unknown title: {text}")
