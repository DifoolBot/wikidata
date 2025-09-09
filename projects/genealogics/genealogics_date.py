from dataclasses import dataclass
from typing import Literal, Optional

DateModifier = Literal["about", "estimated", "before", "after"]


@dataclass
class GenealogicsDate:
    year: Optional[int] = None
    month: Optional[int] = None
    day: Optional[int] = None
    modifier: Optional[DateModifier] = None
    raw: Optional[str] = None
    is_decade: bool = False
    alt_year: Optional[int] = None
    place: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "year": self.year,
            "month": self.month,
            "day": self.day,
            "modifier": self.modifier,
            "raw": self.raw,
        }

    def precision(self) -> Literal["day", "month", "year", "decade", "none"]:
        if self.year and self.month and self.day:
            return "day"
        elif self.year and self.month:
            return "month"
        elif self.year:
            if self.is_decade:
                return "decade"
            return "year"
        return "none"

    def __str__(self) -> str:
        parts = []
        if self.modifier:
            parts.append(self.modifier.capitalize())
        date_str = ""
        if self.day:
            date_str += f"{self.day} "
        if self.month:
            from calendar import month_abbr

            date_str += f"{month_abbr[self.month]} "
        if self.year is not None:
            date_str += str(self.year)
        if date_str:
            parts.append(date_str.strip())
        return " ".join(parts) if parts else (self.raw or "")

    def get_deprecated_date_str(self) -> str:
        # (14 May 1694 - uncertain 1757)
        parts = []
        if self.modifier:
            if self.modifier == "estimated":
                parts.append("uncertain")
        date_str = ""
        if self.day:
            date_str += f"{self.day} "
        if self.month:
            from calendar import month_abbr

            date_str += f"{month_abbr[self.month]} "
        if self.year is not None:
            date_str += str(self.year)
        if date_str:
            parts.append(date_str.strip())
        return " ".join(parts) if parts else (self.raw or "")
