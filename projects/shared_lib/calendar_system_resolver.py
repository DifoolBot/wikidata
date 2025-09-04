import re
from calendar import monthrange
from pathlib import Path
from typing import Optional

import pywikibot as pwb
import yaml

import shared_lib.constants as wd
from shared_lib.lookups.interfaces.place_lookup_interface import CountryLookupInterface

YAML_DIR = Path("projects\\wikipedia\\")


def load_template_config(filename: str):
    path = YAML_DIR / filename
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


class CountryConfig:
    def __init__(self, key: Optional[str], config: dict):
        country_config = config.get(key, {})
        self.country_config = country_config or {}
        self.last_julian_date = self.country_config.get("last_julian_date")
        self.first_gregorian_date = self.country_config.get("first_gregorian_date")
        self.no_julian_calendar = self.country_config.get("no_julian_calendar")
        use = self.country_config.get("use")
        if use:
            for key, value in config.items():
                if value.get("code") == use:
                    self.last_julian_date = value.get("last_julian_date")
                    self.first_gregorian_date = value.get("first_gregorian_date")
                    self.no_julian_calendar = value.get("no_julian_calendar")
                    break
        if self.no_julian_calendar:
            # last_julian_date:
            #     year: 1582
            #     month: 10
            #     day: 4
            # first_gregorian_date:
            #     year: 1582
            #     month: 10
            #     day: 15
            self.last_julian_date = {"year": 1582, "month": 10, "day": 4}
            self.first_gregorian_date = {"year": 1582, "month": 10, "day": 15}


class CalendarSystemResolver:
    def __init__(self, last_julian_date, first_gregorian_date):
        self.last_julian_date = last_julian_date
        self.first_gregorian_date = first_gregorian_date

    def get_calendar_url(self, year, month, day) -> str:
        """
        Given a year, month, day, returns the calendar model URL.
        - If the date can be both Julian and Gregorian, returns URL_UNSPECIFIED_CALENDAR.
        - If only Julian, returns URL_PROLEPTIC_JULIAN_CALENDAR.
        - If only Gregorian, returns URL_PROLEPTIC_GREGORIAN_CALENDAR.
        - If neither, raises ValueError.
        Handles cases where only year or year+month are provided by checking both ends of the range.
        """

        def date_tuple(d):
            return (int(d.get("year", 0)), int(d.get("month", 0)), int(d.get("day", 0)))

        # If no transition info, cannot determine
        if not self.last_julian_date or not self.first_gregorian_date:
            return wd.URL_UNSPECIFIED_CALENDAR

        last_julian = date_tuple(self.last_julian_date)
        first_gregorian = date_tuple(self.first_gregorian_date)

        # If only year is provided
        if year and not month and not day:
            # Check 1 Jan and 31 Dec of that year
            y = int(year)
            # 1 Jan
            ymd1 = (y, 1, 1)
            # 31 Dec
            ymd2 = (y, 12, 31)
            cal1 = self._calendar_for_ymd(ymd1, last_julian, first_gregorian)
            cal2 = self._calendar_for_ymd(ymd2, last_julian, first_gregorian)
            if cal1 == cal2:
                return cal1
            else:
                return wd.URL_UNSPECIFIED_CALENDAR_ASSUMED_GREGORIAN
        # If year and month are provided
        if year and month and not day:
            y = int(year)
            m = int(month)
            # 1st of month
            ymd1 = (y, m, 1)
            # last day of month
            last_day = monthrange(y, m)[1]
            ymd2 = (y, m, last_day)
            cal1 = self._calendar_for_ymd(ymd1, last_julian, first_gregorian)
            cal2 = self._calendar_for_ymd(ymd2, last_julian, first_gregorian)
            if cal1 == cal2:
                return cal1
            else:
                return wd.URL_UNSPECIFIED_CALENDAR_ASSUMED_GREGORIAN
        # If year, month, and day are provided
        if year and month and day:
            ymd = (int(year), int(month), int(day))
            return self._calendar_for_ymd(ymd, last_julian, first_gregorian)
        raise ValueError("Insufficient date information for calendar determination.")

    def _calendar_for_ymd(self, ymd, last_julian, first_gregorian):
        """
        Helper to determine calendar for a given (year, month, day) tuple.
        """
        # Julian: date <= last_julian
        is_julian = ymd <= last_julian
        # Gregorian: date >= first_gregorian
        is_gregorian = ymd >= first_gregorian
        if is_julian and is_gregorian:
            return wd.URL_UNSPECIFIED_CALENDAR_ASSUMED_GREGORIAN
        elif is_julian:
            return wd.URL_PROLEPTIC_JULIAN_CALENDAR
        elif is_gregorian:
            return wd.URL_PROLEPTIC_GREGORIAN_CALENDAR
        else:
            raise ValueError(
                f"Date {ymd} is not valid for either Julian or Gregorian calendar in this context."
            )


class DateCalendarService:
    def __init__(
        self, country_qid: Optional[str], country_lookup: CountryLookupInterface
    ):
        self.country_qid = country_qid
        self.country_lookup = country_lookup

        if self.country_qid:
            country_config = CountryConfig(
                self.country_qid, load_template_config("countries.yaml")
            )
            if not country_config.first_gregorian_date:
                self.ensure_qid_in_yaml()
                raise RuntimeError(f"No first_gregorian_date for {self.country_qid}")

            self.last_julian_date = country_config.last_julian_date
            self.first_gregorian_date = country_config.first_gregorian_date
        else:
            self.last_julian_date = {"year": 1582, "month": 10, "day": 4}
            self.first_gregorian_date = {"year": 1582, "month": 10, "day": 15}

    def ensure_qid_in_yaml(self):
        if not self.country_qid:
            return

        path = YAML_DIR / "countries.yaml"
        with path.open("r", encoding="utf-8") as f:
            lines = f.readlines()

        # Check if any line starts with the QID followed by a colon
        qid_present = any(
            re.match(rf"^{re.escape(self.country_qid)}\s*:", line) for line in lines
        )

        if not qid_present:
            info = self.country_lookup.get_country_by_qid(self.country_qid)
            if info:
                country_qid, code, description = info

                block = f"\n{country_qid}:\n    code: {code}\n    description: {description}\n"
                with path.open("a", encoding="utf-8") as f:
                    f.write(block)

    def get_calendar_url(self, year, month, day) -> str:
        resolver = CalendarSystemResolver(
            self.last_julian_date, self.first_gregorian_date
        )
        return resolver.get_calendar_url(year, month, day)

    def get_wbtime(self, year, month, day) -> pwb.WbTime:
        resolver = CalendarSystemResolver(
            self.last_julian_date, self.first_gregorian_date
        )
        calendarmodel = resolver.get_calendar_url(year, month, day)
        date = pwb.WbTime(
            year=year, month=month, day=day, calendarmodel=calendarmodel
        ).normalize()

        return date
