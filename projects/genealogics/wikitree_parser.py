import json
from pathlib import Path
from pprint import pprint
from typing import Optional
from shared_lib.rate_limiter import rate_limit
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
        elif "guess" == status_lower:
            modifier = "estimated"
        else:
            raise ValueError(f"Unknown status modifier: {status}")

    raw = date_str
    if status:
        raw += f" ({status})"

    return GenealogicsDate(year=year, month=month, day=day, modifier=modifier, raw=raw)


class NameBuilder:
    TITLE_STRINGS = [
        "Baronet",
        "Duchess",
        # Add more as needed
    ]

    ORDINAL_PATTERN = r"^(\d+(?:st|nd|rd|th))"

    def _extract_title(self, nicknames):
        if not nicknames:
            return None
        import re

        for title in self.TITLE_STRINGS:
            # Accepts either ordinal+title or bare title (possibly with 'of ...')
            ordinal_pattern = rf"{self.ORDINAL_PATTERN} {title}"
            bare_pattern = rf"^{title}(?: of .*)?$"
            if re.match(ordinal_pattern, nicknames) or re.match(
                bare_pattern, nicknames
            ):
                return nicknames
        raise RuntimeError(
            f"Nicknames field does not start with ordinal+title or bare title: {nicknames}"
        )

    def add_alias(self, alias):
        # Check for comma in alias
        if "," in alias:
            raise RuntimeError(f"Comma found in alias: {alias}")
        # Do not add display_name as alias
        if alias == self.display_name:
            return
        # Do not add duplicates, preserve order
        if alias not in self.aliases:
            self.aliases.append(alias)

    def __init__(self, profile: dict):
        self.profile = profile
        self.display_name = None
        self.bare_display_name = None
        self.aliases = []  # preserve order
        self.deprecated_names = set()
        self.title = None
        self._build()

    def _get_base_name(self, last_name, include_suffix: bool = False):
        first = self.profile.get("FirstName") or ""
        middle = self.profile.get("MiddleName") or ""
        middle_initial = self.profile.get("MiddleInitial") or ""
        # Check for commas in used values (except LastNameOther)
        for val, label in [
            (first, "FirstName"),
            (middle, "MiddleName"),
            (middle_initial, "MiddleInitial"),
            (last_name, "LastNameCurrent/AtBirth/Other"),
        ]:
            if label != "LastNameOther" and "," in val:
                raise RuntimeError(f"Comma found in {label}: {val}")
        parts = [first]
        if middle:
            parts.append(middle)
        elif middle_initial:
            parts.append(middle_initial)
        parts.append(last_name)
        name = " ".join(p for p in parts if p).strip()
        if include_suffix:
            suffix = self.profile.get("Suffix") or ""
            suffix = self.get_allowed_suffix(suffix)
            if suffix:
                if "," in suffix:
                    raise RuntimeError(f"Comma found in Suffix: {suffix}")
                name = f"{name} {suffix}"
        return name

    def get_prefix_suffix_variants(self, prefix: str) -> list[str]:
        if not prefix:
            return []
        # Dictionary of known prefix variants
        prefix_variants = [
            ["Lieutenant", "Lieut.", "Lieut", "Lt.", "Lt"],
            ["Reverend", "Rev.", "Rev"],
        ]
        for variants in prefix_variants:
            if prefix in variants:
                return variants
            
        variants = [prefix]
        if prefix.endswith("."):
            variants.append(prefix[:-1])
        return variants

    def get_allowed_suffix(self, suffix: str) -> Optional[str]:
        allowed_suffixes = {"Jr.", "Sr.", "II", "III", "IV", "V"}
        not_allowed_suffixes = {}
        if not suffix:
            return ""
        suffix = suffix.strip()
        if suffix == "Jr":
            suffix = "Jr."
        if suffix == "Sr":
            suffix = "Sr."

        if suffix in allowed_suffixes:
            return suffix
        elif suffix not in not_allowed_suffixes:
            raise RuntimeError(f"Unexpected suffix: {suffix}")

    def _build(self):
        p = self.profile
        nicknames = p.get("Nicknames")
        gender = (p.get("Gender") or "").lower()
        if gender not in ("male", "female"):
            raise RuntimeError(f"Gender must be 'male' or 'female', got: {gender}")
        last_name_current = p.get("LastNameCurrent") or ""
        last_name_at_birth = p.get("LastNameAtBirth") or ""
        last_name_other = p.get("LastNameOther") or ""
        prefix = p.get("Prefix") or ""
        suffix = p.get("Suffix") or ""

        if nicknames:
            self.title = self._extract_title(nicknames)

        # Display name: for female, use married name if present, else birth name
        if (
            # gender == "female"
            last_name_current
            and last_name_at_birth
            and last_name_current != last_name_at_birth
        ):
            self.display_name = self._get_base_name(
                last_name_current, include_suffix=True
            )
            self.bare_display_name = self._get_base_name(
                last_name_current, include_suffix=False
            )
            alias = self._get_base_name(last_name_at_birth)
            self.add_alias(alias)
        else:
            self.display_name = self._get_base_name(
                last_name_current or last_name_at_birth, include_suffix=True
            )
            self.bare_display_name = self._get_base_name(
                last_name_current or last_name_at_birth, include_suffix=False
            )

        # Aliases from LastNameOther (comma separated, preserve order)
        if last_name_other:
            for alt_last in [
                n.strip() for n in last_name_other.split(",") if n.strip()
            ]:
                alias = self._get_base_name(alt_last)
                self.add_alias(alias)

        # Deprecated names: display_name with prefix, suffix, or both
        if "," in prefix:
            raise RuntimeError(f"Comma found in Prefix: {prefix}")
        if "," in suffix:
            raise RuntimeError(f"Comma found in Suffix: {suffix}")

        deprecated = set()
        prefix_variants = self.get_prefix_suffix_variants(prefix)
        suffix_variants = self.get_prefix_suffix_variants(suffix)
        if prefix_variants or suffix_variants:
            prefix_variants.append("")
            suffix_variants.append("")
        for pr in prefix_variants:
            for su in suffix_variants:
                if pr or su:
                    deprecated.add(f"{pr} {self.bare_display_name} {su}".strip())
                    if su:
                        deprecated.add(f"{pr} {self.bare_display_name}, {su}".strip())
        self.deprecated_names = deprecated

        # Remove display_name from aliases and deprecated_names
        if self.display_name in self.aliases:
            self.aliases = [a for a in self.aliases if a != self.display_name]
        self.deprecated_names.discard(self.display_name)

    def get_title(self):
        return self.title

    def get_display_name(self):
        return self.display_name

    def get_aliases(self):
        return list(self.aliases)

    def get_deprecated_names(self):
        return list(self.deprecated_names)


def get_fields() -> str:
    return ",".join(
        [
            "IsPerson",  # 1 for Person profiles
            "FirstName",
            "MiddleName",
            "MiddleInitial",
            "LastNameAtBirth",
            "LastNameCurrent",
            # these can't be used as 'mul'
            "Nicknames",  # 4th Baronet Musgrave of Eden Hall, Duchess of Lancaster
            # comma separated list
            "LastNameOther",  # de Roet, Ruet, Rueth, Roelt, Swynford
            "RealName",  # The "Preferred" first name of the profile
            "Prefix",  # Lieutenant, Sir
            "Suffix",  # MP
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

@rate_limit(30) # 1 call every 30 seconds
def fetch_wikitree_api(wt_id: str, use_cache: bool = True):
    params = {
        "action": "getProfile",
        "key": wt_id,
        "fields": get_fields(),
        # "fields": "*",
        "appId": "DifoolBot-Wikidata",
    }

    print('Retrieving data from WIkiTree API for', wt_id)
    r = requests.get(API_URL, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()
    return data


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
        data = fetch_wikitree_api(wt_id, use_cache)
        # Save raw API result to cache file
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # Validate response
    if not isinstance(data, list) or not data:
        raise ValueError(f"Unexpected API response format: {data!r}")

    entry = data[0]
    profile = entry.get("profile", {})
    datastatus = profile.get("DataStatus", {})

    for date_type in ("Birth", "Death"):
        decade_value = profile.get(f"{date_type}DateDecade")
        date_str = profile.get(f"{date_type}Date")
        status = datastatus.get(f"{date_type}Date")
        date_value = parse_wikitree_date(date_str, status)
        if decade_value == "unknown" and date_value:
            raise RuntimeError("unknown decade with known date")
        if not date_value and decade_value and decade_value != "unknown":
            decade_year = decade_value.rstrip("s")
            date_value = GenealogicsDate(
                year=int(decade_year),
                is_decade=True,
                raw=decade_value,
            )
        if date_type == "Birth":
            birth_date = date_value
        else:
            death_date = date_value

    first_name = profile.get("FirstName")
    real_name = profile.get("RealName")

    is_date_guess = False
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
        if template.get("name") == "DateGuess":
            is_date_guess = True
    if len(findagrave_ids) > 1:
        raise RuntimeError("Multiple FindAGrave IDs found, unexpected")
    if len(findagrave_ids) > 0:
        findagrave_id = next(iter(findagrave_ids))
    else:
        findagrave_id = None

    if profile.get("IsPerson") != 1:
        raise RuntimeError("This one is not a person, needs special handling")
    # if real_name:
    #     if first_name != real_name:
    #         raise RuntimeError(
    #             "This one has diff FirstName, RealName field, needs special handling"
    #         )
    # if profile.get("Nicknames"):
    #     raise RuntimeError("This one has a Nicknames field, needs special handling")
    if profile.get("ColloquialName"):
        raise RuntimeError(
            "This one has a ColloquialName field, needs special handling"
        )
    # if profile.get("LastNameOther"):
    #     raise RuntimeError("This one has a LastNameOther field, needs special handling")
    if datastatus.get("BirthLocation") == 'guess':
        birth_location = None
    else:
        check_status(profile, datastatus, "BirthLocation")
        birth_location = profile.get("BirthLocation")
    if datastatus.get("DeathLocation") == 'guess':
        death_location = None
    else:
        check_status(profile, datastatus, "DeathLocation")
        death_location = profile.get("DeathLocation")
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

    # (14 May 1694 - uncertain 1757)
    depr_start = birth_date.get_deprecated_date_str() if birth_date else "?"
    depr_end = death_date.get_deprecated_date_str() if death_date else "?"
    deprecated_desc_date = f"({depr_start} - {depr_end})"

    name_builder = NameBuilder(profile)
    # Build result with all fields + DataStatus for dates and locations
    result = {
        "display_name": name_builder.get_display_name(),
        "aliases": name_builder.get_aliases(),
        "deprecated_names": name_builder.get_deprecated_names(),
        "deprecated_desc_date": deprecated_desc_date,
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
        "birth_location": birth_location, 
        "death_date": death_date,
        "death_location": death_location,
        "gender": profile.get("Gender"),
        "is_living": profile.get("IsLiving"),
        "findagrave_id": findagrave_id,
        "is_date_guess": is_date_guess,
        "data_status": profile.get("DataStatus"),
    }

    return result


# Example:
def test(wt_id: str):
    profile_data = fetch_wikitree_profiles(wt_id, use_cache=True)
    pprint(profile_data, sort_dicts=False)


if __name__ == "__main__":
    # test("Adams-57")  # birth date before; prefix
    # test("Unknown-488976")
    # test("Bååt-25")
    # test("Zu_Schwarzburg-Leutenberg-1")
    # test("Moton-5")
    # test("Duvall-727")  # guess date
    # test("Taylor-21104")
    # test("Taylor-21105")  # date decade; death = year, no status,
    # # text indicates range
    # test("Hutton-1476")  # prefix = sir, suffix = MP
    # test("Musgrave-741")  # prefix = sir, suffix = MP; nicknames
    # test("Roet-3")
    test("Roet-18")  # realname
