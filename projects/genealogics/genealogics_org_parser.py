import re
import time
from pathlib import Path
from typing import List, Optional, cast

import genealogics.nameparser as np
import genealogics.prefix_suffix_utils as psu
import requests
from bs4 import BeautifulSoup, Tag
from genealogics.genealogics_date import DateModifier, GenealogicsDate
from genealogics.rules import Field

BACKOFF_SECS = 5 * 60

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


def _strip_modifier(text: str) -> tuple[Optional[DateModifier], str]:
    """
    If a leading modifier is present (abt., bef., aft., etc.), return (modifier, rest).
    Otherwise return (None, text).
    """
    parts = text.split(maxsplit=1)
    if not parts:
        return None, ""

    head = parts[0].lower().rstrip(".")
    if head in _mod_map:
        return _mod_map[head], (parts[1] if len(parts) > 1 else "").strip()
    # If it looks like a word but is not recognized as a modifier, keep as-is;
    # your original behavior raised here — preserve your preference if desired.
    return None, text.strip()


# Strict date-place pattern:
# - Optional day
# - Optional month (3+ letters)
# - Required base year: 3–4 digits
# - Optional slash + 1–2 digits for the alt year
# - Optional trailing punctuation/space and then place
_DATE_PLACE_RE = re.compile(
    r"""
    ^\s*
    (?:(?P<day>\d{1,2})\s+)?                                 # optional day
    (?:(?P<month>[A-Za-z]{3,})\s+)?                           # optional month
    (?P<year>\d{3,4})(?:/(?P<alt>\d{1,2}))?                   # year and optional /alt
    \b
    (?:[,.\s]+(?P<place>.+))?                                 # optional trailing place
    \s*$
    """,
    re.VERBOSE,
)


def _normalize_alt_year(y1: int, y2_short: int) -> int:
    """
    Expand a short alt year (e.g., 1707/8) to full year (1708).
    If expansion would produce a year < y1, roll into next century.
    """
    base_century = (y1 // 100) * 100
    y2 = base_century + y2_short
    if y2 < y1:
        y2 += 100
    return y2


def parse_genealogics_date(text: str) -> GenealogicsDate:
    raw = text.strip()
    if not raw:
        raise ValueError("Empty date string")

    modifier, date_str = _strip_modifier(raw)
    if not date_str:
        # Modifier only, no date
        raise ValueError(f"Unable to parse date after modifier: {raw}")

    m = _DATE_PLACE_RE.match(date_str)
    if not m:
        # If it failed, try a pure-year fallback to avoid misreads like "37"
        pure = re.fullmatch(r"\s*(\d{3,4})(?:/(\d{1,2}))?\s*", date_str)
        if not pure:
            raise ValueError(f"Unrecognised date format: {date_str}")
        day = None
        month = None
        year = int(pure.group(1))
        alt_year = (
            _normalize_alt_year(year, int(pure.group(2))) if pure.group(2) else None
        )
        place = None
    else:
        gd = m.groupdict()
        day = int(gd["day"]) if gd["day"] else None

        if gd["month"]:
            mon_key = gd["month"][:3].lower()
            if mon_key not in _month_map:
                raise ValueError(f"Unknown month: {gd['month']}")
            month = _month_map[mon_key]
        else:
            month = None

        year = int(gd["year"])  # base year requires 3–4 digits
        if gd["alt"]:
            alt_year = _normalize_alt_year(year, int(gd["alt"]))
        else:
            alt_year = None

        place = gd["place"].strip() if gd["place"] else None

    # Final validation
    if year is None:
        raise ValueError(f"Unable to parse year from: {raw}")

    # Return with additional fields if your dataclass supports them
    return GenealogicsDate(
        year=year,
        month=month,
        day=day,
        modifier=modifier,
        raw=raw,
        alt_year=alt_year,  # optional in your model
        place=place,  # optional in your model
    )


# def parse_genealogics_date(text: str) -> GenealogicsDate:
#     raw = text.strip()
#     if not raw:
#         raise ValueError("Empty date string")

#     parts = raw.split(maxsplit=1)
#     modifier = None

#     # Detect and validate modifier
#     if parts[0].lower().rstrip(".") in _mod_map:
#         modifier = _mod_map[parts[0].lower().rstrip(".")]
#         date_str = parts[1] if len(parts) > 1 else ""
#     elif re.match(r"^[A-Za-z]{3,}$", parts[0]):
#         raise ValueError(f"Unknown modifier: {parts[0]}")
#     else:
#         date_str = raw

#     # --- NEW: split date and place ---
#     # Match: day month year[/year] [rest as place]
#     m = re.match(
#         r"^(\d{1,2})?\s*([A-Za-z]{3,})?\s*(\d{1,4}(?:/\d{1,4})?)\s*(.*)$",
#         date_str.strip(),
#     )
#     if not m:
#         raise ValueError(f"Unrecognised date format: {date_str}")

#     day_str, month_str, year_str, place_str = m.groups()
#     day = int(day_str) if day_str else None
#     month = _month_map[month_str[:3].lower()] if month_str else None

#     # Handle dual years like 1707/8
#     if "/" in year_str:
#         y1, y2 = year_str.split("/")
#         year = int(y1)
#         alt_year = int(y2)
#     else:
#         year = int(year_str)
#         alt_year = None

#     place = place_str.strip() or None

#     # Final validation
#     if year is None:
#         raise ValueError(f"Unable to parse year from: {raw}")

#     return GenealogicsDate(
#         year=year,
#         month=month,
#         day=day,
#         modifier=modifier,
#         raw=raw,
#         alt_year=alt_year,  # optional extra field
#         place=place,  # optional extra field
#     )


def fetch_genealogics(p1819_id: str, use_cache: bool = True):
    cache_file = CACHE_DIR / f"{p1819_id}.html"

    if use_cache and cache_file.exists():
        html = cache_file.read_text(encoding="utf-8")
    else:
        try:
            base_url = "https://www.genealogics.org/getperson.php"
            params = {"personID": p1819_id, "tree": "LEO"}
            r = requests.get(base_url, params=params, timeout=20)
            r.raise_for_status()
            html = r.text
            cache_file.write_text(html, encoding="utf-8")
        except Exception as ex:
            template = "An exception of type {0} occurred. Arguments:\n{1!r}"
            message = template.format(type(ex).__name__, ex.args)
            print("*** Uncaught Error ***")
            print(message)
            time.sleep(BACKOFF_SECS)
            raise RuntimeError("genealogics.org Connection error" + message)

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

    def get_tds(field_text: str):
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
        return tds

    def get_date_place_field(field_text: str):
        tds = get_tds(field_text)
        if not tds:
            return
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
                if date.place:
                    place = date.place
        return {"date": date, "place": place, "modifiers": modifiers}

    def get_str_field(field_text: str):
        tds = get_tds(field_text)
        if not tds:
            return None
        # Just return the cleaned text for simple fields
        return tds[1].get_text(" ", strip=True)

    birth = get_date_place_field("Birth")
    christening = get_date_place_field("Christening")
    death = get_date_place_field("Death")
    probate = None
    if death:
        if death.get("modifiers") == "date of probate":
            probate = death
            # keep death as is, date is in the form 'before' probate date
    burial = get_date_place_field("Burial")
    if len(name_parts) not in [1, 2]:
        raise RuntimeError("Unexpected name parts length")
    depr_names = []
    depr_descs = []
    names = np.NameParser(name_parts[0], psu.get_prefixes(), psu.get_suffixes())
    depr_names.append(name_parts[0])
    if len(name_parts) == 2:
        title = name_parts[1]
        depr_names.append(f"{name_parts[0]}, {title}")
    else:
        title = None
    if not names.cleaned_name:
        raise RuntimeError("No cleaned name found")
    lived_in = get_str_field("Lived In")
    if names.location:
        if lived_in:
            residence = f"{names.location}, {lived_in}"
        else:
            residence = f"{names.location}"
    else:
        residence = None
    dob = birth.get("date") if birth else None
    dod = death.get("date") if death else None
    pob = birth.get("place") if birth else None
    pod = death.get("place") if death else None
    if dob or dod:
        sdob = dob.raw if dob else ""
        sdod = dod.raw if dod else ""
        spob = pob if pob else ""
        spod = pod if pod else ""
        sbirth = sdob.strip()
        sdeath = sdod.strip()
        desc = f"{sbirth} - {sdeath}".strip()
        depr_descs.append(desc)
        if spob or spod:
            sbirth = f"{sdob} {spob}".strip()
            sdeath = f"{sdod} {spod}".strip()
            desc = f"{sbirth} - {sdeath}".strip()
            if desc not in depr_descs:
                depr_descs.append(desc)

    if pob and lived_in:
        pob = f"{pob}, {lived_in}"
    if pod and lived_in:
        pod = f"{pod}, {lived_in}"

    if christening:
        raise RuntimeError("Need to check: christening")
    if burial:
        raise RuntimeError("Need to check: burial")
    if probate:
        raise RuntimeError("Need to check: probate")
    return {
        Field.DISPLAY_NAME: names.cleaned_name,
        Field.TITLE: title,
        Field.DATE_OF_BIRTH: dob,
        Field.PLACE_OF_BIRTH: pob,
        Field.DATE_OF_DEATH: dod,
        Field.PLACE_OF_DEATH: pod,
        Field.PLACE_OF_RESIDENCE: residence,
        Field.DATE_OF_BAPTISM: christening.get("date") if christening else None,
        Field.DATE_OF_BURIAL: burial.get("date") if burial else None,
        Field.DATE_OF_PROBATE: probate.get("date") if probate else None,
        Field.GENDER: get_str_field("Gender"),
        Field.PREFIX: get_str_field("Honorific"),
        Field.DEPRECATED_NAMES: depr_names,
        Field.DEPRECATED_DESCS: depr_descs,
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
