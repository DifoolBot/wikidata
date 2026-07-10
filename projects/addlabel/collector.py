"""Combines the AuthorityPages retrieved for one Wikidata item into single
verdicts: which name to use per language, one sex value, and the most precise
non-conflicting birth/death dates — each paired with the page it came from so
the bot can build a 'stated in' reference.
"""

from dataclasses import dataclass
from datetime import date as datetime_date
from typing import List, Optional, Tuple

from shared_lib.date_value import CALENDAR_GREGORIAN, CALENDAR_JULIAN, Date

import addlabel.person_name as pn
import addlabel.script_utils as script_utils
from addlabel.authority_page import AuthorityPage, tri_state_or

QID_MALE = "Q6581097"
QID_FEMALE = "Q6581072"

SEX_QIDS = {
    "male": QID_MALE,
    "female": QID_FEMALE,
}

# split_date result: (year, month, day) with 0 for missing parts
YMD = Tuple[int, int, int]


@dataclass
class SexFinding:
    qid: str  # QID_MALE or QID_FEMALE
    page: AuthorityPage  # source, for the reference


@dataclass
class DateFinding:
    date: Date
    page: AuthorityPage  # source, for the reference


def split_date(date_str: str) -> Optional[YMD]:
    """Parse "YYYY[-MM[-DD]]" into (year, month, day), 0 for missing parts.
    Returns None for malformed strings (source typos)."""
    parts = date_str.split("-")
    for part in parts:
        if not part.isdigit():
            # typos: for example idref: 059640340 has a196; or "1521~"
            print(f"Invalid date string: {date_str}")
            return None

    if len(parts) == 1:
        return (int(parts[0]), 0, 0)
    elif len(parts) == 2:
        return (int(parts[0]), int(parts[1]), 0)
    elif len(parts) == 3:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    else:
        raise RuntimeError(f"Invalid date string: {date_str}")


USE_FIRST = "use_first"
USE_SECOND = "use_second"
DIFFERENT = "different"


def compare_dates(date1: YMD, date2: YMD) -> str:
    """Return which date has the most precision (USE_FIRST/USE_SECOND); if the
    dates contradict each other, return DIFFERENT."""
    y1, m1, d1 = date1
    y2, m2, d2 = date2

    if y2 == 0:
        return USE_FIRST
    if y1 == 0:
        return USE_SECOND
    if y1 != y2:
        return DIFFERENT
    if m2 == 0:
        return USE_FIRST
    if m1 == 0:
        return USE_SECOND
    if m1 != m2:
        return DIFFERENT
    if d2 == 0:
        return USE_FIRST
    if d1 == 0:
        return USE_SECOND
    if d1 != d2:
        return DIFFERENT
    return USE_FIRST


def get_most_precise_date(dates) -> Optional[YMD]:
    """Pick the most precise date from a set of (year, month, day) tuples, or
    None when they conflict or no date is usable."""
    best = (0, 0, 0)
    for date in dates:
        comparison_result = compare_dates(best, date)
        if comparison_result == DIFFERENT:
            return None
        if comparison_result == USE_SECOND:
            best = date

    if best == (0, 0, 0):
        return None
    return best


def create_date(ymd: YMD) -> Date:
    year, month, day = ymd
    if year < 1582:
        calendar = CALENDAR_JULIAN
    else:
        calendar = CALENDAR_GREGORIAN
    return Date(year=year, month=month, day=day, calendar=calendar)


class Collector:
    def __init__(self, force_name_order: str = pn.NAME_ORDER_UNDETERMINED):
        self.pages: List[AuthorityPage] = []
        self.name_order = pn.NAME_ORDER_UNDETERMINED
        self.name_orders: List[str] = []
        self.force_name_order = force_name_order

    def add(self, page: AuthorityPage):
        self.pages.append(page)

    def retrieve(self) -> None:
        for page in self.pages:
            page.run_once()

        self.resolve_name_order()

    def resolve_name_order(self):
        # distinct name orders proposed by the pages, without UNDETERMINED
        # entries; always collected (also when the order is forced) because
        # can_change_labels() inspects it
        self.name_orders = []
        for page in self.pages:
            if page.name_order == pn.NAME_ORDER_UNDETERMINED:
                continue
            if page.name_order not in self.name_orders:
                self.name_orders.append(page.name_order)

        if self.force_name_order != pn.NAME_ORDER_UNDETERMINED:
            self.name_order = self.force_name_order
        else:
            self.name_order = self.determine_name_order()

        for page in self.pages:
            page.set_name_order(self.name_order)

    def determine_name_order(self) -> str:
        if pn.NAME_ORDER_HUNGARIAN in self.name_orders:
            return pn.NAME_ORDER_HUNGARIAN

        if len(self.name_orders) > 1:
            print("conflicting name order")
            return pn.NAME_ORDER_UNDETERMINED
        elif len(self.name_orders) == 1:
            return self.name_orders[0]
        else:
            # default to western order
            return pn.NAME_ORDER_WESTERN

    def has_language_info(self) -> bool:
        return any(page.has_language_info() for page in self.pages)

    def can_change_labels(self) -> bool:
        # names from non Latin script? skip for now
        if self.has_hebrew_script():
            return False
        if self.has_cyrillic_script():
            return False
        if self.has_non_latin_script():
            return False

        # skip eastern order for now
        if self.name_order == pn.NAME_ORDER_HUNGARIAN:
            return True
        if pn.NAME_ORDER_EASTERN in self.name_orders:
            return False
        if len(self.name_orders) > 1:
            return False

        return True

    def has_duplicates(self) -> bool:
        # for example, multiple IdRef IDs; we skip those Wikidata items
        seen = set()
        for page in self.pages:
            short_desc = page.get_short_desc()
            if short_desc in seen:
                return True
            seen.add(short_desc)

        return False

    def has_hebrew_script(self) -> bool:
        return any(page.has_hebrew_script() for page in self.pages)

    def has_cyrillic_script(self) -> bool:
        return any(page.has_cyrillic_script() for page in self.pages)

    def has_non_latin_script(self) -> bool:
        # three-valued per page; unknown for all pages counts as non-latin
        result = None
        for page in self.pages:
            result = tri_state_or(result, page.has_non_latin_script())

        return result if result is not None else True

    def has_redirect(self) -> bool:
        return any(page.is_redirect or page.not_found for page in self.pages)

    def get_names(self, page_language: str):
        """All latin names offered by sources in the given language, in
        first-seen order, each with the pages that carry it."""
        name_dict = {}
        for page in self.pages:
            if page.page_language != page_language:
                continue
            if not page.latin_name:
                continue
            for name in page.latin_name.names():
                if not script_utils.is_latin_text(name):
                    continue
                name_dict.setdefault(name, []).append(page)

        return [
            {"name": name, "pages": pages} for name, pages in name_dict.items()
        ]

    def get_sex_info(self) -> Optional[SexFinding]:
        """The one sex value the sources agree on, or None; raises when the
        sources contradict each other."""
        sex_dict = {}
        for page in self.pages:
            if page.sex and page.sex != "notKnown":
                sex_dict.setdefault(page.sex, []).append(page)
        if len(sex_dict) > 1:
            raise RuntimeError(f"Multiple sex strings: {sex_dict}")
        if not sex_dict:
            return None
        sex, pages = next(iter(sex_dict.items()))
        if sex not in SEX_QIDS:
            raise RuntimeError(f"Unexpected sex: {sex}")
        return SexFinding(qid=SEX_QIDS[sex], page=pages[0])

    def get_date_info(self, date_type: str) -> Optional[DateFinding]:
        """The most precise birth or death date the sources agree on, or None.

        date_type is "birth" or "death".
        """
        date_dict = {}
        date_attr = "birth_date" if date_type == "birth" else "death_date"

        for page in self.pages:
            date_str = getattr(page, date_attr)
            if not date_str:
                continue

            if "," in date_str:
                # 1801, 1802
                print(f"Skipped date {date_str}")
                return None
            if "X" in date_str:
                # IdRef: 19XX
                print(f"Skipped date {date_str}")
                continue
            if "." in date_str:
                # 19..
                print(f"Skipped date {date_str}")
                continue
            ymd = split_date(date_str)
            if ymd:
                # idref 190096357
                if ymd[0] < 100:
                    raise RuntimeError(f"Year < 100: {date_str}")
                if ymd[0] > datetime_date.today().year:
                    raise RuntimeError(f"Year in the future: {date_str}")
                date_dict.setdefault(ymd, []).append(page)

        most_precise = get_most_precise_date(date_dict)
        if not most_precise:
            return None

        return DateFinding(
            date=create_date(most_precise), page=date_dict[most_precise][0]
        )
