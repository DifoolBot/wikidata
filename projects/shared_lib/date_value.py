from datetime import date
from typing import Optional

import pywikibot as pwb

import shared_lib.constants as wd

PRECISION_DAY = 11
PRECISION_MONTH = 10
PRECISION_YEAR = 9
PRECISION_DECADE = 8
PRECISION_CENTURY = 7
PRECISION_MILLENNIUM = 6


CALENDAR_JULIAN = "julian"
CALENDAR_GREGORIAN = "gregorian"
CALENDAR_ASSUMED_GREGORIAN = "assumed_gregorian"


class Date:
    def __init__(
        self,
        year: Optional[int],
        month: Optional[int] = 0,
        day: Optional[int] = 0,
        precision: Optional[int] = None,
        calendar: Optional[str] = None,
    ):
        self.year = year if year else 0
        self.month = month if month else 0
        self.day = day if day else 0
        self.precision = precision
        if not self.precision:
            if self.day:
                self.precision = PRECISION_DAY
            elif self.month:
                self.precision = PRECISION_MONTH
            elif self.year:
                self.precision = PRECISION_YEAR
            else:
                raise RuntimeError("Invalid date")
        self.calendar = calendar

    def __repr__(self):
        if self.day:
            return f"Date(year={self.year}, month={self.month}, day={self.day}, precision={self.precision}')"
        elif self.month:
            return f"Date(year={self.year}, month={self.month}, precision={self.precision}')"
        else:
            return f"Date(year={self.year}, precision={self.precision}')"

    def __hash__(self):
        return hash((self.year, self.month, self.day, self.precision, self.calendar))

    @classmethod
    def is_equal(cls, item1, item2, ignore_calendar_model: bool):
        if isinstance(item1, Date):
            w1 = item1.create_wikidata_item()
        else:
            w1 = item1
        if isinstance(item2, Date):
            w2 = item2.create_wikidata_item()
        else:
            w2 = item2
        if isinstance(w1, pwb.WbTime) and isinstance(w2, pwb.WbTime):
            norm1 = w1.normalize()
            norm2 = w2.normalize()
            if ignore_calendar_model:
                norm1.calendarmodel = norm2.calendarmodel
            return norm1 == norm2
        else:
            return False

    @classmethod
    def create_from_WbTime(cls, item: pwb.WbTime) -> "Date":
        if item.calendarmodel == wd.URL_PROLEPTIC_JULIAN_CALENDAR:
            calendar = CALENDAR_JULIAN
        elif item.calendarmodel == wd.URL_PROLEPTIC_GREGORIAN_CALENDAR:
            calendar = CALENDAR_GREGORIAN
        elif item.calendarmodel == wd.URL_UNSPECIFIED_CALENDAR:
            calendar = None
        elif item.calendarmodel == wd.URL_UNSPECIFIED_CALENDAR_ASSUMED_GREGORIAN:
            calendar = CALENDAR_ASSUMED_GREGORIAN
        else:
            raise RuntimeError(f"Unrecognized calendar {item.calendarmodel}")

        return Date(
            year=item.year,
            month=item.month,
            day=item.day,
            precision=item.precision,
            calendar=calendar,
        )

    @classmethod
    def get_decade(cls, year: int) -> int:
        # Any date in range 2010-2019 with precision 8 is interpreted as 2010s.
        return year // 10

    @classmethod
    def get_century(cls, year: int) -> int:
        # FIXME: +1?
        # Any date in range 1801-1900 with precision 7 is interpreted as 19th century.
        return (year - 1) // 100

    @classmethod
    def get_millennium(cls, year: int) -> int:
        # FIXME: +1?
        # Any date in range 1001-2000 with precision 6 is interpreted as second millennium
        return (year - 1) // 1000

    @classmethod
    def create_middle(cls, earliest, latest, do_strict: bool):
        if (
            earliest.precision >= PRECISION_MONTH
            and latest.precision >= PRECISION_MONTH
            and earliest.year == latest.year
            and earliest.month == latest.month
        ):
            year_mid = earliest.year
            month_mid = earliest.month
            precision = PRECISION_MONTH
        else:
            month_mid = 0

            if earliest.year > latest.year:
                raise RuntimeError("earliest.year > latest.year")

            year_mid = (latest.year + earliest.year) // 2
            year_len = latest.year - earliest.year + 1

            if do_strict:
                if earliest.year == latest.year:
                    precision = PRECISION_YEAR
                elif cls.get_decade(earliest.year) == cls.get_decade(latest.year):
                    precision = PRECISION_DECADE
                elif cls.get_century(earliest.year) == cls.get_century(latest.year):
                    precision = PRECISION_CENTURY
                elif cls.get_millennium(earliest.year) == cls.get_millennium(
                    latest.year
                ):
                    precision = PRECISION_MILLENNIUM
                else:
                    raise RuntimeError("invalid precision")
            else:
                if year_len <= 1:
                    precision = PRECISION_YEAR
                elif year_len <= 11:
                    precision = PRECISION_DECADE
                elif year_len <= 110:
                    precision = PRECISION_CENTURY
                else:
                    raise RuntimeError("invalid precision")

        return Date(year=year_mid, month=month_mid, day=0, precision=precision)

    def is_1_jan(self) -> bool:
        return (
            self.day == 1 and self.month == 1 and self.precision == PRECISION_DAY
        ) or (self.month == 1 and self.precision == PRECISION_MONTH)

    def is_31_dec(self) -> bool:
        return (
            self.day == 31 and self.month == 12 and self.precision == PRECISION_DAY
        ) or (self.month == 12 and self.precision == PRECISION_MONTH)

    def change_to_year(self):
        self.precision = PRECISION_YEAR
        self.month = 0
        self.day = 0

    def follows(self, other) -> bool:
        if self.precision != other.precision:
            raise RuntimeError("Different precision")
        if self.precision == PRECISION_YEAR:
            return self.year == other.year + 1
        else:
            raise RuntimeError("Unexpected precision")

    def get_calendarmodel(self) -> str:
        calendar = self.calendar
        if calendar is None:
            if self.year < 1582:
                calendar = CALENDAR_JULIAN
            else:
                calendar = CALENDAR_GREGORIAN
        if calendar == CALENDAR_JULIAN:
            return wd.URL_PROLEPTIC_JULIAN_CALENDAR
        if calendar == CALENDAR_GREGORIAN or calendar == CALENDAR_ASSUMED_GREGORIAN:
            return wd.URL_PROLEPTIC_GREGORIAN_CALENDAR

        raise RuntimeError(f"Unrecognized calendar {calendar}")

    def is_valid_date(self) -> bool:
        if self.day < 0 or self.day > 31:
            return False
        if self.month < 0 or self.month > 12:
            return False
        if self.day == 0:
            return True

        try:
            date(self.year, self.month, self.day)  # Try creating a date object
            return True  # If successful, the date is valid
        except ValueError:
            return False  # If an exception is raised, the date is invalid

    def create_wikidata_item(self) -> pwb.WbTime:
        if not self.is_valid_date():
            raise RuntimeError(
                f"Invalid date: y:{self.year} - m:{self.month} - d:{self.day}"
            )
        return pwb.WbTime(
            self.year,
            self.month,
            self.day,
            precision=self.precision,
            calendarmodel=self.get_calendarmodel(),
        )

    def __eq__(self, other):
        return Date.is_equal(self, other, ignore_calendar_model=False)

    def as_string(self) -> str:
        if self.precision == PRECISION_YEAR:
            return f"{self.year}"
        elif self.precision == PRECISION_MONTH:
            return f"{self.year}-{self.month}"
        elif self.precision == PRECISION_DAY:
            return f"{self.year}-{self.month}-{self.day}"
        else:
            return f"Unknown precision {self.precision}"
