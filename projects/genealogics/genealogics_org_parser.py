import re
from pathlib import Path
from typing import List, cast

import requests
from bs4 import BeautifulSoup, Tag
from genealogics.genealogics_date import GenealogicsDate, DateModifier

CACHE_DIR = Path("genealogics_cache")
CACHE_DIR.mkdir(exist_ok=True)


_mod_map: dict[str, DateModifier] = {
    "abt": "about",
    "about": "about",
    "est": "estimated",
    "estimated": "estimated",
    "bef": "before",
    "before": "before",
    "aft": "after",
    "after": "after",
}

_month_map = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


def parse_genealogics_date(text: str) -> GenealogicsDate:
    raw = text.strip()
    if not raw:
        raise ValueError("Empty date string")

    parts = raw.split(maxsplit=1)
    modifier = None

    # Detect and validate modifier
    if parts[0].lower().rstrip(".") in _mod_map:
        modifier = _mod_map[parts[0].lower().rstrip(".")]
        date_part = parts[1] if len(parts) > 1 else ""
    elif re.match(r"^[A-Za-z]{3,}$", parts[0]):
        # Starts with something alphabetical but not recognised
        raise ValueError(f"Unknown modifier: {parts[0]}")
    else:
        date_part = raw

    # Parse tokens
    tokens = date_part.strip().split()
    day = month = year = None

    if len(tokens) == 3:
        if tokens[0].isdigit():
            day = int(tokens[0])
        if tokens[1][:3].lower() in _month_map:
            month = _month_map[tokens[1][:3].lower()]
        if re.match(r"^-?\d{1,4}$", tokens[2]):
            year = int(tokens[2])
    elif len(tokens) == 2:
        if tokens[0][:3].lower() in _month_map and tokens[1].isdigit():
            month = _month_map[tokens[0][:3].lower()]
            year = int(tokens[1])
        elif tokens[1][:3].lower() in _month_map and tokens[0].isdigit():
            year = int(tokens[0])
            month = _month_map[tokens[1][:3].lower()]
        elif (
            re.match(r"^-?\d{1,4}$", tokens[0])
            and not tokens[1][:3].lower() in _month_map
        ):
            # Something looks like a year followed by unexpected text
            raise ValueError(f"Unrecognised date format: {date_part}")
    elif len(tokens) == 1:
        if re.match(r"^-?\d{1,4}$", tokens[0]):
            year = int(tokens[0])
        else:
            raise ValueError(f"Unrecognised date format: {date_part}")

    # Final validation: must have at least a year
    if year is None:
        raise ValueError(f"Unable to parse year from: {raw}")

    return GenealogicsDate(year=year, month=month, day=day, modifier=modifier, raw=raw)


def fetch_genealogics(p1819_id: str, use_cache: bool = True):
    cache_file = CACHE_DIR / f"{p1819_id}.html"

    if use_cache and cache_file.exists():
        html = cache_file.read_text(encoding="utf-8")
    else:
        base_url = "https://www.genealogics.org/getperson.php"
        params = {"personID": p1819_id, "tree": "LEO"}
        r = requests.get(base_url, params=params, timeout=20)
        r.raise_for_status()
        html = r.text
        cache_file.write_text(html, encoding="utf-8")

    soup = BeautifulSoup(html, "html.parser")

    # ---- Name parts ----
    h1 = soup.select_one("div h1")
    name_parts: List[str] = []
    if h1:
        for part in h1.decode_contents().split("<br/>"):
            text = BeautifulSoup(part, "html.parser").get_text(" ", strip=True)
            cleaned = re.sub(r"\[\s*\d+(?:\s*,\s*\d+)*\s*\]", "", text).strip()
            if cleaned:
                name_parts.append(cleaned)

    def get_field_info(field_text: str, expect_date_place: bool = False):
        """
        Extracts a field value from the genealogics HTML table.
        If expect_date_place is True, returns a dict with 'date' and 'place' keys.
        Otherwise, returns a cleaned string or None.
        """

        def match_row(tag) -> bool:
            if getattr(tag, "name", None) != "tr":
                return False
            first_td = tag.find("td")
            if not first_td:
                return False
            # <span class="fieldname">Burial</span>
            return (
                first_td.find(
                    "span", string=re.compile(rf"^{re.escape(field_text)}\b", re.I)
                )
                is not None
            )

        tr = soup.find(match_row)
        if not tr:
            return None
        tr = cast(Tag, tr)
        tds = tr.find_all("td")
        if len(tds) < 2:
            return None

        if expect_date_place:
            # Try to extract date and place from the row
            date = place = modifiers = None
            if len(tds) == 3:
                date = parse_genealogics_date(tds[1].get_text(" ", strip=True))
                place = tds[2].get_text(" ", strip=True)
                if place == "(years before)":
                    place = None
                elif place == "(date will probated)" or place == "(date will proven)":
                    place = None
                    modifiers = "date of probate"
                elif place.startswith("("):
                    raise ValueError(f"Unexpected place format: {place}")
            elif len(tds) == 2:
                td_text = tds[1].get_text(" ", strip=True)
                td1 = cast(Tag, tds[1])
                if td1.find("a"):
                    # treat as place
                    place = td_text
                    if place == "(years before)":
                        place = None
                    elif place.startswith("("):
                        raise ValueError(f"Unexpected place format: {place}")
                else:
                    # treat as date
                    date = parse_genealogics_date(td_text)
            return {"date": date, "place": place, "modifiers": modifiers}
        else:
            # Just return the cleaned text for simple fields
            return tds[1].get_text(" ", strip=True)

    return {
        "label_parts": name_parts,
        "birth": get_field_info("Birth", expect_date_place=True),
        "christening": get_field_info("Christening", expect_date_place=True),
        "gender": get_field_info("Gender"),
        "lived_in": get_field_info("Lived In"),
        "honorific": get_field_info("Honorific"),
        "death": get_field_info("Death", expect_date_place=True),
        "burial": get_field_info("Burial", expect_date_place=True),
    }


# Example usage:
# print(fetch_genealogics("I00490861"))  # Bef, 2 lines
# print(fetch_genealogics("I00712891"))  # no birth/death, ", of" in name
# print(fetch_genealogics("I00699914"))  # ", of" in name, Female, question mark in name
# print(fetch_genealogics("I00040513"))  # burial
# print(fetch_genealogics("I00268892"))  # christening + birth; birth contains "est."
# print(fetch_genealogics("I00041404"))
# print(fetch_genealogics("I00488408"))
# print(fetch_genealogics("I00490842"))  # honorific in name
