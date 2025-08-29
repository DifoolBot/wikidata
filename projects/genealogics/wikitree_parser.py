import json
from pathlib import Path
from pprint import pprint

import requests
from genealogics.genealogics_date import DateModifier, GenealogicsDate

API_URL = "https://api.wikitree.com/api.php"
CACHE_DIR = Path("wikitree_cache")
CACHE_DIR.mkdir(exist_ok=True)

# documentation: https://github.com/wikitree/wikitree-api


def parse_wikitree_date(
    date_str: str | None, status: str | None
) -> GenealogicsDate | None:
    """
    Parse a WikiTree date string (YYYY-MM-DD) and status into a GenealogicsDate.
    Status may contain modifiers like "about", "before", "after", "estimated".
    Returns None if date_str is None or empty.
    """
    if not date_str:
        return None

    date_str = date_str.strip()
    if not date_str or date_str == "0000-00-00":
        return None

    parts = date_str.split("-")
    if len(parts) != 3:
        raise ValueError(f"Invalid date format: {date_str}")

    year = int(parts[0]) if parts[0] != "0000" else None
    month = int(parts[1]) if parts[1] != "00" else None
    day = int(parts[2]) if parts[2] != "00" else None

    modifier: DateModifier | None = None
    if status:
        status_lower = status.lower()
        if "certain" == status_lower:
            modifier = None
        elif "before" == status_lower:
            modifier = "before"
        elif "after" == status_lower:
            modifier = "after"
        else:
            raise ValueError(f"Unknown status modifier: {status}")

    raw = date_str
    if status:
        raw += f" ({status})"

    return GenealogicsDate(year=year, month=month, day=day, modifier=modifier, raw=raw)


def construct_display_name(profile):
    """
    Construct a name with the following rules:
    - First name always included
    - Use middle name if present, else middle initial
    - Use last_name_current if present, else last_name_at_birth
    - No prefix/suffix
    """
    first = profile.get("FirstName") or ""
    middle = profile.get("MiddleName") or ""
    middle_initial = profile.get("MiddleInitial") or ""
    last = profile.get("LastNameCurrent") or profile.get("LastNameAtBirth") or ""

    parts = [first]

    if middle:
        parts.append(middle)
    elif middle_initial:
        parts.append(middle_initial)

    parts.append(last)

    # Join with spaces and strip stray whitespace
    return " ".join(p for p in parts if p).strip()


def get_fields() -> str:
    return ",".join(
        [
            "IsPerson",  # 1 for Person profiles
            "FirstName",
            "MiddleName",
            "MiddleInitial",
            "LastNameAtBirth",
            "LastNameCurrent",
            "Nicknames",
            "LastNameOther",
            "RealName",  # The "Preferred" first name of the profile
            "Prefix",  # Lieutenant
            "Suffix",
            "ColloquialName",
            "BirthDate",  # The date of birth, YYYY-MM-DD. The Month (MM) and Day (DD) may be zeros.
            "DeathDate",  # The date of death, YYYY-MM-DD. The Month (MM) and Day (DD) may be zeros.
            "BirthLocation",
            "DeathLocation",
            "BirthDateDecade",
            "DeathDateDecade",
            "Gender",  # Male or Female
            "IsLiving",  # 1 if the person is considered "living", 0 otherwise
            "DataStatus",
            "Templates",
        ]
    )


def check_status(profile, datastatus, key: str):
    if profile.get(key) and datastatus.get(key) and datastatus.get(key) != "certain":
        raise RuntimeError(f"{key} not certain: {datastatus.get(key)}")


def fetch_wikitree_profiles(wt_id: str, use_cache: bool = True):
    """
    Fetch WikiTree profile(s) for the given ID.
    Caches the raw API response in its own JSON file using the page_name.
    Loads from cache if available and use_cache=True.
    """
    cache_file = CACHE_DIR / f"{wt_id}.json"

    # Serve from cache if present and allowed
    if use_cache and cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        params = {
            "action": "getProfile",
            "key": wt_id,
            "fields": get_fields(),
            # "fields": "*",
            "appId": "DifoolBot-Wikidata",
        }

        r = requests.get(API_URL, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()

        # Save raw API result to cache file
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # Validate response
    if not isinstance(data, list) or not data:
        raise ValueError(f"Unexpected API response format: {data!r}")

    entry = data[0]
    profile = entry.get("profile", {})
    datastatus = profile.get("DataStatus", {})

    birth_date = parse_wikitree_date(
        profile.get("BirthDate"), datastatus.get("BirthDate")
    )
    death_date = parse_wikitree_date(
        profile.get("DeathDate"), datastatus.get("DeathDate")
    )

    first_name = profile.get("FirstName")
    real_name = profile.get("RealName")

    findagrave_ids = set()
    for template in profile.get("Templates", []):
        if template.get("name") == "FindAGrave":
            # {'name': 'FindAGrave', 'params': {'39387590': ''}}
            params = template.get("params", {})
            if len(params) != 1:
                raise RuntimeError("Unexpected FindAGrave template format")
            findagrave_id = next(iter(params.keys()))
            findagrave_ids.add(findagrave_id)
            break
    if len(findagrave_ids) > 1:
        raise RuntimeError("Multiple FindAGrave IDs found, unexpected")
    if len(findagrave_ids) > 0:
        findagrave_id = next(iter(findagrave_ids))
    else:
        findagrave_id = None

    if profile.get("IsPerson") != 1:
        raise RuntimeError("This one is not a person, needs special handling")
    if real_name:
        if first_name != real_name:
            raise RuntimeError(
                "This one has diff FirstName, RealName field, needs special handling"
            )
    if profile.get("Nicknames"):
        raise RuntimeError("This one has a Nicknames field, needs special handling")
    if profile.get("LastNameOther"):
        raise RuntimeError("This one has a LastNameOther field, needs special handling")
    if profile.get("Suffix"):
        raise RuntimeError("This one has a Suffix field, needs special handling")
    if profile.get("BirthDateDecade") and not birth_date:
        raise RuntimeError(
            "This one has a BirthDateDecade field and no birth_date, needs special handling"
        )
    if profile.get("DeathDateDecade") and not death_date:
        raise RuntimeError(
            "This one has a DeathDateDecade field and no death_date, needs special handling"
        )
    check_status(profile, datastatus, "BirthLocation")
    check_status(profile, datastatus, "DeathLocation")
    check_status(profile, datastatus, "FirstName")
    check_status(profile, datastatus, "MiddleName")
    check_status(profile, datastatus, "LastNameCurrent")
    check_status(profile, datastatus, "RealName")
    check_status(profile, datastatus, "LastNameOther")
    check_status(profile, datastatus, "LastNameAtBirth")
    check_status(profile, datastatus, "ColloquialName")
    check_status(profile, datastatus, "Prefix")
    check_status(profile, datastatus, "Suffix")
    check_status(profile, datastatus, "Nicknames")

    # Build result with all fields + DataStatus for dates and locations
    result = {
        "display_name": construct_display_name(profile),
        "first_name": profile.get("FirstName"),
        "middle_name": profile.get("MiddleName"),
        "middle_initial": profile.get("MiddleInitial"),
        "last_name_at_birth": profile.get("LastNameAtBirth"),
        "last_name_current": profile.get("LastNameCurrent"),
        "nicknames": profile.get("Nicknames"),
        "last_name_other": profile.get("LastNameOther"),
        "real_name": profile.get("RealName"),
        "prefix": profile.get("Prefix"),
        "suffix": profile.get("Suffix"),
        "colloquial_name": profile.get("ColloquialName"),
        "birth_date": birth_date,
        "birth_location": profile.get("BirthLocation"),
        # "birth_location_status": datastatus.get("BirthLocation"),
        "death_date": death_date,
        "death_location": profile.get("DeathLocation"),
        # "death_location_status": datastatus.get("DeathLocation"),
        "gender": profile.get("Gender"),
        "is_living": profile.get("IsLiving"),
        "findagrave_id": findagrave_id,
        "data_status": profile.get("DataStatus"),
    }

    return result


# Example:
def test(wt_id: str):
    profile_data = fetch_wikitree_profiles(wt_id, use_cache=True)
    pprint(profile_data, sort_dicts=False)


if __name__ == "__main__":
    test("Adams-57")  # birth date before; prefix
    # test("Unknown-488976")
    # test("Bååt-25")
    # test("Zu_Schwarzburg-Leutenberg-1")
    # test("Moton-5")
