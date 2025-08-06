import abc
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional

import pywikibot as pwb

import shared_lib.constants as wd

URL_PROLEPTIC_JULIAN_CALENDAR = "http://www.wikidata.org/entity/Q1985786"
URL_PROLEPTIC_GREGORIAN_CALENDAR = "http://www.wikidata.org/entity/Q1985727"

PRECISION_DAY = 11
PRECISION_MONTH = 10
PRECISION_YEAR = 9
PRECISION_DECADE = 8
PRECISION_CENTURY = 7
PRECISION_MILLENNIUM = 6

# TODO: move naar constants
PID_NATURE_OF_STATEMENT = "P5102"
PID_REASON_FOR_PREFERRED_RANK = "P7452"
PID_SOURCING_CIRCUMSTANCES = "P1480"
QID_CIRCA = "Q5727902"
QID_MOST_PRECISE_VALUE = "Q71536040"
QID_POSSIBLY = "Q30230067"

MAX_LAG_BACKOFF_SECS = 10 * 60

SITE = pwb.Site("wikidata", "wikidata")
SITE.login()
SITE.get_tokens("csrf")
REPO = SITE.data_repository()


class TextColor:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


def sort_pids(pids):
    return sorted(pids, key=lambda x: int(x[1:]))


class Reference(abc.ABC):
    @abc.abstractmethod
    def is_equal_reference(self, src) -> bool:
        raise NotImplementedError

    @abc.abstractmethod
    def create_source(self):
        raise NotImplementedError

    def has_equal_reference(self, claim) -> bool:
        for src in claim.sources:
            if self.is_equal_reference(src):
                return True

        return False


class WikipediaReference(Reference):
    def __init__(self, wikipedia_qid: str):
        self.wikipedia_qid = wikipedia_qid

    def is_equal_reference(self, src) -> bool:
        if wd.PID_IMPORTED_FROM_WIKIMEDIA_PROJECT in src:
            for claim in src[wd.PID_IMPORTED_FROM_WIKIMEDIA_PROJECT]:
                actual = claim.getTarget()
                if actual == self.wikipedia_qid:
                    return True
        return False

    def create_source(self):
        source = OrderedDict()

        imported_from_claim = pwb.Claim(
            REPO, wd.PID_IMPORTED_FROM_WIKIMEDIA_PROJECT, is_reference=True
        )
        imported_from_claim.setTarget(pwb.ItemPage(REPO, self.wikipedia_qid))
        source[wd.PID_IMPORTED_FROM_WIKIMEDIA_PROJECT] = [imported_from_claim]

        return source


class WikidataEntity(abc.ABC):
    wd_page: "WikiDataPage"
    reference: Optional[Reference]

    # TODO : rename? can_apply
    def can_add(self) -> bool:
        return True

    # TODO : rename? apply
    @abc.abstractmethod
    def add(self):
        raise NotImplementedError

    def post_add(self):
        pass


class Action:
    @abc.abstractmethod
    def prepare(self):
        raise NotImplementedError

    @abc.abstractmethod
    def apply(self):
        raise NotImplementedError

    @abc.abstractmethod
    def post_apply(self):
        raise NotImplementedError


class Statement(WikidataEntity):

    # TODO : rename?
    def add(self):
        prop = self.get_prop()
        if prop in self.wd_page.claims:
            for claim in self.wd_page.claims[prop]:
                if self.can_attach_to_claim(claim, strict=True):
                    if claim.rank == "deprecated":
                        raise RuntimeError("claim is deprecated; strict = True")
                    if self.reference:
                        if self.reference.has_equal_reference(claim):
                            print(" already added")
                        else:
                            print(
                                TextColor.OKCYAN + " reference added" + TextColor.ENDC
                            )
                            self.add_reference(claim)
                    return

        if prop in self.wd_page.claims:
            for claim in self.wd_page.claims[prop]:
                if self.can_attach_to_claim(claim, strict=False):
                    if claim.rank == "deprecated":
                        raise RuntimeError("claim is deprecated; strict = False")
                    did_delete_ref = False
                    if self.reference:
                        if self.reference.has_equal_reference(claim):
                            print(" reference deleted")
                            self.delete_reference(claim, is_update=True)
                            did_delete_ref = True

                    print(TextColor.OKBLUE + " statement changed" + TextColor.ENDC)
                    self.update_statement(claim)

                    if self.reference:
                        print(" reference added")
                        self.add_reference(claim, is_update=did_delete_ref)
                    return

        if self.can_add_claim:
            print(TextColor.OKGREEN + " statement added" + TextColor.ENDC)
            claim = self.add_statement()

            if self.reference:
                print(" reference added")
                self.add_reference(claim)

    @abc.abstractmethod
    def can_add_claim(self) -> bool:
        raise NotImplementedError

    @abc.abstractmethod
    # TODO: waarom optional
    def get_prop(self) -> Optional[str]:
        raise NotImplementedError

    @abc.abstractmethod
    def can_attach_to_claim(self, claim, strict: bool) -> bool:
        raise NotImplementedError

    def add_reference(self, claim: pwb.Claim, is_update: bool = False):
        if not self.reference:
            return

        source = self.reference.create_source()

        claim.sources.append(source)
        if is_update:
            self.wd_page.reference_changed(claim)
        else:
            self.wd_page.reference_added(claim)

    def delete_reference(self, claim: pwb.Claim, is_update: bool = False):
        if not self.reference:
            return

        new_sources = []
        found = False
        for source in claim.sources:
            if self.reference.is_equal_reference(source):
                found = True
            else:
                new_sources.append(source)

        if found:
            claim.sources = new_sources
            if not is_update:
                self.wd_page.reference_deleted(claim)

    @abc.abstractmethod
    def update_statement(self, claim: pwb.Claim):
        raise NotImplementedError

    @abc.abstractmethod
    def add_statement(self) -> pwb.Claim:
        raise NotImplementedError

    def has_equal_qualifier(self, search_value, claim, qualifier) -> bool:
        if search_value is None:
            return False
        if claim.qualifiers is None:
            return False
        if qualifier in claim.qualifiers:
            for q in claim.qualifiers[qualifier]:
                value = q.getTarget()
                if value == search_value:
                    return True

        return False


class Date:
    def __init__(
        self,
        year: int,
        month: int = 0,
        day: int = 0,
        precision: Optional[int] = None,
        calendar: Optional[str] = None,
    ):
        self.year = year
        self.month = month
        self.day = day
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
        if item.calendarmodel == URL_PROLEPTIC_JULIAN_CALENDAR:
            calendar = "julian"
        elif item.calendarmodel == URL_PROLEPTIC_GREGORIAN_CALENDAR:
            calendar = "gregorian"
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
                if cls.get_millennium(earliest.year) == cls.get_millennium(latest.year):
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
            raise RuntimeError("Unexpeced precision")

    def get_calendarmodel(self) -> str:
        calendar = self.calendar
        if calendar is None:
            if self.year < 1582:
                calendar = "julian"
            else:
                calendar = "gregorian"
        if calendar == "julian":
            return URL_PROLEPTIC_JULIAN_CALENDAR
        if calendar == "gregorian":
            return URL_PROLEPTIC_GREGORIAN_CALENDAR

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
        # if isinstance(other, Date):
        #     return (
        #         self.year == other.year
        #         and self.month == other.month
        #         and self.day == other.day
        #         and self.precision == other.precision
        #     )
        # if isinstance(other, pwb.WbTime):
        #     # FIXME calendarmodel
        #     this = self.create_wikidata_item()
        #     return this.normalize() == other.normalize()
        # return False

    def as_string(self) -> str:
        if self.precision == PRECISION_YEAR:
            return f"{self.year}"
        elif self.precision == PRECISION_MONTH:
            return f"{self.year}-{self.month}"
        elif self.precision == PRECISION_DAY:
            return f"{self.year}-{self.month}-{self.day}"
        else:
            return f"Unknown precision {self.precision}"


class AddStatement(Action):
    def __init__(self, statement: Statement):
        self.statement = statement
        self.ignore = False

    def prepare(self):
        if not self.statement.can_add():
            self.ignore = True

    def apply(self):
        if not self.ignore:
            self.statement.add()

    def post_apply(self):
        if not self.ignore:
            self.statement.post_add()


class DeleteStatement(Action):
    def __init__(self, statement: Statement):
        self.statement = statement

    def prepare(self):
        pass

    def apply(self):
        # claim = self.statement.find_claim()
        # self.statement.wd_page.save_deleted_claim(claim)
        pass

    def post_apply(self):
        pass


class MoveReferences(Action):
    def __init__(self, from_statement: Statement, to_statement: Statement):
        self.from_statement = from_statement
        self.to_statement = to_statement

    def prepare(self):
        pass

    def apply(self):
        # from_claim = self.from_statement.find_claim()
        # to_claim = self.to_statement.find_claim()
        # todo
        pass

    def post_apply(self):
        pass


class CheckDateStatements(Action):
    def __init__(self, wd_page: "WikiDataPage", prop: str):
        self.wd_page = wd_page
        self.prop = prop

    def is_sourced(self, claim: pwb.Claim):
        """Check if the claim has at least one reference."""
        return bool(claim.sources)

    def precision_level(self, claim: pwb.Claim):
        """Return numeric precision level: year=9, month=10, day=11"""
        t = claim.getTarget()
        if t:
            return t.precision
        else:
            return 0

    def has_same_normalized_date(self, claim1: pwb.Claim, claim2: pwb.Claim):
        """
        return True if the dates are the same on the lowest precision
        So   1955   == 2 Mar 1955
        and  1590s  == 1591
        """
        # can be None
        target1 = claim1.getTarget()
        target2 = claim2.getTarget()
        if target1 is None and target2 is None:
            return True
        if target1 is None or target2 is None:
            return False
        normalized1 = target1.normalize()
        normalized2 = target2.normalize()
        low_prec = normalized1.precision
        if normalized2.precision < low_prec:
            low_prec = normalized2.precision
        if (
            low_prec <= 9
            or (normalized1.precision != low_prec)
            or (normalized2.precision != low_prec)
        ):
            normalized1.calendarmodel = normalized2.calendarmodel
        normalized1.precision = low_prec
        normalized2.precision = low_prec
        final1 = normalized1.normalize()
        final2 = normalized2.normalize()
        is_equal = final1 == final2
        return is_equal

    def process_property(self, claims):
        """Group statements by normalized date using a precision-to-claims map."""
        if any(claim.rank == "preferred" for claim in claims):
            return  # Skip if any statement is already preferred

        # Build a dictionary: { precision_level: [claims] }
        precision_map = {}
        for claim in claims:
            if claim.rank == "deprecated":
                continue
            prec = self.precision_level(claim)
            if prec > 11:
                raise RuntimeError("Unsupported precision > 11")
            precision_map.setdefault(prec, []).append(claim)

        by_normalized = []
        # Highest precision first
        for prec in sorted(precision_map.keys(), reverse=True):
            for claim in precision_map[prec]:
                found = False
                for group in by_normalized:
                    if self.has_same_normalized_date(claim, group[0]):
                        group.append(claim)
                        found = True
                        break
                if not found:
                    by_normalized.append([claim])

        if len(by_normalized) == 0:
            # only deprecated statements; nothing to do
            return
        if len(by_normalized) != 1:
            raise RuntimeError("len(by_normalized) != 1")

        group = by_normalized[0]
        if len(group) == 1:
            # only 1 claim, no need to change
            return

        for claim in group:
            if claim.qualifiers:
                if len(claim.qualifiers) != 0:
                    raise RuntimeError("1 group with claims with qualifiers")

        claim = group[0]
        if not self.is_sourced(claim):
            raise RuntimeError("Unsourced best claim")

        if claim.rank == "deprecated":
            raise RuntimeError("Best claim is deprecated")
        if claim.rank == "preferred":
            raise RuntimeError("Best claim is preferred")

        claim.rank = "preferred"
        qualifier = pwb.Claim(REPO, PID_REASON_FOR_PREFERRED_RANK, is_qualifier=True)
        target = pwb.ItemPage(REPO, QID_MOST_PRECISE_VALUE)
        qualifier.setTarget(target)
        claim.qualifiers.setdefault(PID_REASON_FOR_PREFERRED_RANK, []).append(qualifier)
        self.wd_page.claim_changed(claim)

    def prepare(self):
        pass

    def apply(self):
        if self.prop in self.wd_page.claims:
            try:
                self.process_property(self.wd_page.claims[self.prop])
            except RuntimeError as e:
                print(f"Runtime error: {e}")
                pass

    def post_apply(self):
        pass


class ItemStatement(Statement):
    def __init__(
        self,
        qid: Optional[str] = None,
        start_date: Optional[Date] = None,
        end_date: Optional[Date] = None,
        qid_alternative: Optional[str] = None,
    ):
        self.qid = qid
        self.qid_alternative = qid_alternative
        # PID_START_TIME
        self.start_date = start_date
        # PID_END_TIME
        self.end_date = end_date
        # PID_SUBJECT_NAMED_AS
        self.subject_named_as = None
        # PID_VOLUME
        self.volume = None
        # PID_PAGES
        self.pages = None
        # PID_URL
        self.url = None

    def __repr__(self):
        attributes = [
            f"start_date={self.start_date}" if self.start_date else "",
            f"end_date={self.end_date}" if self.end_date else "",
            (
                f"subject_named_as={self.subject_named_as}"
                if self.subject_named_as
                else ""
            ),
            f"volume={self.volume}" if self.volume else "",
            f"pages={self.pages}" if self.pages else "",
            f"url={self.url}" if self.url else "",
        ]
        attributes = ", ".join(attr for attr in attributes if attr)
        return f"{self.__class__.__name__}(item='{self.qid}'{', ' if attributes else ''}{attributes})"

    def can_attach_to_claim(self, claim, strict: bool) -> bool:
        target = claim.getTarget()
        if not target:
            # unknown value
            return False
        id = target.getID()
        if (id != self.qid) and (id != self.qid_alternative):
            return False

        qualifiers = [
            (wd.PID_START_TIME, self.start_date),
            (wd.PID_END_TIME, self.end_date),
            (wd.PID_SUBJECT_NAMED_AS, self.subject_named_as),
            (wd.PID_VOLUME, self.volume),
            (wd.PID_PAGES, self.pages),
            (wd.PID_URL, self.url),
        ]

        for qualifier, value in qualifiers:
            if qualifier in claim.qualifiers and value:
                if not self.has_equal_qualifier(value, claim, qualifier):
                    return False
            elif strict and (qualifier in claim.qualifiers or value):
                return False
            elif qualifier in claim.qualifiers:
                raise RuntimeError("Need to check this variant")

        return True

    def update_statement(self, claim: pwb.Claim):
        qualifiers = [
            (wd.PID_START_TIME, self.start_date),
            (wd.PID_END_TIME, self.end_date),
            (wd.PID_SUBJECT_NAMED_AS, self.subject_named_as),
            (wd.PID_VOLUME, self.volume),
            (wd.PID_PAGES, self.pages),
            (wd.PID_URL, self.url),
        ]

        for qualifier, value in qualifiers:
            if value:
                if not self.has_equal_qualifier(value, claim, qualifier):
                    qual_claim = pwb.Claim(REPO, qualifier, is_qualifier=True)
                    if isinstance(value, Date):
                        target = value.create_wikidata_item()
                    else:
                        target = value
                    qual_claim.setTarget(target)
                    claim.qualifiers.setdefault(qualifier, []).append(qual_claim)
        self.wd_page.claim_changed(claim)

    def add_statement(self) -> pwb.Claim:
        pid = self.get_prop()
        claim = pwb.Claim(REPO, pid)
        claim.setTarget(pwb.ItemPage(REPO, self.qid))

        self.update_statement(claim)
        self.wd_page.add_claim(pid, claim)
        return claim


class DateQualifiers:
    ALLOWED_PROPS = {
        PID_NATURE_OF_STATEMENT,
        PID_SOURCING_CIRCUMSTANCES,
        wd.PID_EARLIEST_DATE,
        wd.PID_LATEST_DATE,
    }

    def __init__(
        self,
        is_circa: bool,
        earliest: Optional[Date] = None,
        latest: Optional[Date] = None,
    ):
        self.is_circa = is_circa
        self.earliest = earliest
        self.latest = latest

    @classmethod
    def from_claim(cls, claim) -> "DateQualifiers":
        quals = claim.qualifiers  # dict: prop → [Qualifier, …]

        # 1. reject any unknown property
        extra = set(quals) - cls.ALLOWED_PROPS
        if extra:
            raise RuntimeError(f"Unsupported qualifier props: {extra}")

        # 2. parse is_circa: must only ever point to Q5727902
        seen_circa = False
        for prop in (PID_NATURE_OF_STATEMENT, PID_SOURCING_CIRCUMSTANCES):
            for q in quals.get(prop, []):
                target_qid = q.getTarget().getID()
                if target_qid != QID_CIRCA:
                    raise RuntimeError(f"Unknown value {target_qid!r} for {prop}")
                seen_circa = True

        # 3. parse earliest/latest dates
        def parse_date(prop):
            qlist = quals.get(prop, [])
            if len(qlist) > 1:
                raise RuntimeError(f"Multiple {prop} qualifiers")
            if not qlist:
                return None
            return Date.create_from_WbTime(qlist[0].getTarget())

        earliest = parse_date(wd.PID_EARLIEST_DATE)
        latest = parse_date(wd.PID_LATEST_DATE)

        return cls(is_circa=seen_circa, earliest=earliest, latest=latest)

    @classmethod
    def from_statement(cls, stmt: "DateStatement") -> "DateQualifiers":
        return cls(
            is_circa=stmt.is_circa,
            earliest=stmt.earliest,
            latest=stmt.latest,
        )

    def __eq__(self, other):
        if not isinstance(other, DateQualifiers):
            return NotImplemented
        return (
            self.is_circa == other.is_circa
            and self.earliest == other.earliest
            and self.latest == other.latest
        )

    def __repr__(self):
        return (
            f"<DateQualifiers circa={self.is_circa!r}, "
            f"earliest={self.earliest!r}, latest={self.latest!r}>"
        )

    @classmethod
    def is_equal(cls, item1: "DateQualifiers", item2: "DateQualifiers", strict: bool):
        if strict:
            return item1 == item2
        else:
            return (
                (item1.is_circa == item2.is_circa)
                and (
                    (not item1.earliest and not item2.earliest)
                    or (item1.earliest == item2.earliest)
                )
                and (
                    (not item1.latest and not item2.latest)
                    or (item1.latest == item2.latest)
                )
            )


class DateStatement(Statement):
    def __init__(
        self,
        date: Optional[Date] = None,
        earliest: Optional[Date] = None,
        latest: Optional[Date] = None,
        is_circa: bool = False,
        ignore_calendar_model: bool = False,
        require_unreferenced: bool = False,
        only_change: bool = False,
    ):
        self.date = date
        self.earliest = earliest
        self.latest = latest
        self.is_circa = is_circa
        self.ignore_calendar_model = ignore_calendar_model
        self.require_unreferenced = require_unreferenced
        self.only_change = only_change

    def __repr__(self):
        if self.earliest or self.latest:
            return f"{self.__class__.__name__}(date={self.date}, earliest={self.earliest}, latest={self.latest}, is_circa={self.is_circa}')"
        else:
            return f"{self.__class__.__name__}(date={self.date}, is_circa={self.is_circa}')"

    def can_add_claim(self) -> bool:
        return not self.only_change

    def can_attach_to_claim(self, claim, strict: bool) -> bool:
        dt = claim.getTarget()
        ignore_calendar_model = not strict and self.ignore_calendar_model
        if not Date.is_equal(
            self.date, dt, ignore_calendar_model=ignore_calendar_model
        ):
            return False

        has_circa = self.wd_page.is_circa(claim)
        if self.is_circa != has_circa:
            return False

        if self.require_unreferenced:
            refs = claim.getSources()
            if refs:
                return False

        # build & validate both qualifier‐sets
        claim_qs = DateQualifiers.from_claim(claim)  # may raise
        target_qs = DateQualifiers.from_statement(self)

        # a single EQ check
        return DateQualifiers.is_equal(claim_qs, target_qs, strict)

        # qualifiers = [
        #     (wd.PID_EARLIEST_DATE, self.earliest),
        #     (wd.PID_LATEST_DATE, self.latest),
        # ]

        # for qualifier, value in qualifiers:
        #     if qualifier in claim.qualifiers and value:
        #         if not self.has_equal_qualifier(value, claim, qualifier):
        #             return False
        #     elif strict and (qualifier in claim.qualifiers or value):
        #         return False
        #     elif qualifier in claim.qualifiers:
        #         raise RuntimeError("Need to check this variant")

        # if self.has_unknown_qualifiers(claim):
        #     raise RuntimeError("Unexpeced qualifier")

        # return True

    def update_statement(self, claim: pwb.Claim):
        if self.is_circa and not self.wd_page.is_circa(claim):
            qual_claim = pwb.Claim(
                REPO, wd.PID_SOURCING_CIRCUMSTANCES, is_qualifier=True
            )
            qual_claim.setTarget(pwb.ItemPage(REPO, QID_CIRCA))
            claim.qualifiers.setdefault(wd.PID_SOURCING_CIRCUMSTANCES, []).append(
                qual_claim
            )

        qualifiers = [
            (wd.PID_EARLIEST_DATE, self.earliest),
            (wd.PID_LATEST_DATE, self.latest),
        ]

        for qualifier, value in qualifiers:
            if value:
                if not self.has_equal_qualifier(value, claim, qualifier):
                    qual_claim = pwb.Claim(REPO, qualifier, is_qualifier=True)
                    if isinstance(value, Date):
                        target = value.create_wikidata_item()
                    else:
                        target = value
                    qual_claim.setTarget(target)
                    claim.qualifiers.setdefault(qualifier, []).append(qual_claim)
        self.wd_page.claim_changed(claim)

    def add_statement(self) -> Optional[pwb.Claim]:
        if not self.date:
            return None

        pid = self.get_prop()
        claim = pwb.Claim(REPO, pid)
        claim.setTarget(self.date.create_wikidata_item())

        self.update_statement(claim)
        self.wd_page.add_claim(pid, claim)
        return claim


class ExternalIDStatement(Statement):
    def __init__(
        self,
        url: Optional[str] = None,
        prop: Optional[str] = None,
        external_id: Optional[str] = None,
    ):
        self.url = url
        self.prop = prop
        self.external_id = external_id

    def __repr__(self):
        if self.url:
            return f"ExternalIDStatement(url={self.url})"
        else:
            return (
                f"ExternalIDStatement(prop={self.prop}, external_id={self.external_id})"
            )

    def can_attach_to_claim(self, claim, strict: bool) -> bool:
        return claim.getTarget() == self.external_id

    def can_add(self):
        if self.url and (not self.prop or not self.external_id):
            raise RuntimeError("Not implemented")
            found_list = self.wd_page.stated_in.extract_ids_from_url(self.url)
            if not found_list:
                raise RuntimeError(f"Unrecognized url {self.url}")

            if len(found_list) != 1:
                raise RuntimeError(
                    f"get_stated_in_from_url: multiple results for {self.url}"
                )

            self.prop, stated_in, self.external_id, keep_url = found_list[0]

        is_valid, actual_prop, actual_external_id = self.wd_page.check_url_redirect(
            self.prop, self.external_id
        )
        if not is_valid:
            print(f"The id {self.prop} {self.external_id} is not valid anymore")
            return False

        if actual_prop != self.prop:
            raise RuntimeError("pid changed")

        if actual_external_id != self.external_id:
            print(
                f"{self.url} - {self.prop} - {self.external_id} redirects to {actual_external_id}"
            )
            self.external_id = actual_external_id

        return True

    def get_prop(self) -> Optional[str]:
        return self.prop

    def update_statement(self, claim: pwb.Claim):
        # nothing to do
        pass

    def add_statement(self) -> pwb.Claim:
        claim = pwb.Claim(REPO, self.prop)
        claim.setTarget(self.external_id)

        self.wd_page.add_claim(self.prop, claim)
        return claim


class Label(WikidataEntity):
    def __init__(self, text, language):
        self.text = text
        self.language = language

    def __repr__(self):
        return f"Label(text='{self.text}', language='{self.language}')"

    def has_language_label(self, language: str) -> bool:
        if language in self.wd_page.item.labels:
            return True

        if "labels" in self.wd_page.data:
            if language in self.wd_page.data["labels"]:
                return True

        return False

    def has_label(self, language: str, text: str) -> bool:
        # already saved?
        if "labels" in self.wd_page.data:
            if language in self.wd_page.data["labels"]:
                if self.wd_page.data["labels"][language] == text:
                    return True

        # already on the page?
        if language not in self.wd_page.item.labels:
            return False
        return self.wd_page.item.labels[language] == text

    def has_alias(self, language: str, text: str) -> bool:
        # already saved?
        if "aliases" in self.wd_page.data:
            if language in self.wd_page.data["aliases"]:
                if text in self.wd_page.data["aliases"][language]:
                    return True

        # already on the page?
        if language not in self.wd_page.item.aliases:
            return False
        return text in self.wd_page.item.aliases[language]

    def add(self):
        if not self.has_language_label(self.language):
            print(TextColor.OKGREEN + " label added" + TextColor.ENDC)
            self.wd_page.save_label(self.language, self.text)
            return

        if self.has_label(self.language, self.text):
            print(" already added")
            return

        if self.has_alias(self.language, self.text):
            print(" already added (as alias)")
        else:
            print(TextColor.OKGREEN + " alias added" + TextColor.ENDC)
            self.wd_page.save_alias(self.language, self.text)


class DateOfBirth(DateStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_DATE_OF_BIRTH

    def post_add(self):
        if self.date:
            if self.date.precision:
                if self.date.precision >= PRECISION_YEAR:
                    self.wd_page.add_birth_year(self.date.year)


class DateOfBaptism(DateStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_DATE_OF_BAPTISM

    def post_add(self):
        if self.date:
            if self.date.precision:
                if self.date.precision >= PRECISION_YEAR:
                    self.wd_page.add_birth_year(self.date.year)


class DateOfDeath(DateStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_DATE_OF_DEATH

    def post_add(self):
        if self.date:
            if self.date.precision:
                if self.date.precision >= PRECISION_YEAR:
                    self.wd_page.add_death_year(self.date.year)


class DateOfBurialOrCremation(DateStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_DATE_OF_BURIAL_OR_CREMATION

    def post_add(self):
        if self.date:
            if self.date.precision:
                if self.date.precision >= PRECISION_YEAR:
                    self.wd_page.add_death_year(self.date.year)


class PlaceOfBirth(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_PLACE_OF_BIRTH

    def post_add(self):
        pass


class PlaceOfDeath(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_PLACE_OF_DEATH


class SexOrGender(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_SEX_OR_GENDER


class Father(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_FATHER


class Mother(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_MOTHER


class Child(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_CHILD


class Patronym(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_PATRONYM_OR_MATRONYM


class Occupation(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_OCCUPATION


class MilitaryOrPoliceRank(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_MILITARY_OR_POLICE_RANK


class NobleTitle(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_NOBLE_TITLE


class PositionHeld(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_POSITION_HELD


class WorkLocation(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_WORK_LOCATION


class MasterOf(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_STUDENT


class DescribedBySource(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_DESCRIBED_BY_SOURCE


class DepictedBy(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_DEPICTED_BY


class StudentOf(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_STUDENT_OF


class ReligionOrWorldview(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_RELIGION_OR_WORLDVIEW


class MedicalCondition(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_MEDICAL_CONDITION


class Genre(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_GENRE


class LanguagesSpokenWrittenOrSigned(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_LANGUAGES_SPOKEN_WRITTEN_OR_SIGNED


class MemberOf(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_MEMBER_OF


def ensure_loaded(item: pwb.ItemPage):
    try:
        qid = item.title()

        if not qid.startswith("Q"):  # ignore property pages and lexeme pages
            raise RuntimeError(f"Skipping {qid} because it does not start with a Q")

        if not item.exists():
            raise RuntimeError(f"Skipping {qid} because it does not exists")

    except pwb.exceptions.MaxlagTimeoutError as ex:
        time.sleep(MAX_LAG_BACKOFF_SECS)
        raise RuntimeError("max lag timeout. sleeping")

    if item.isRedirectPage():
        raise RuntimeError(f"Skipping {qid} because it is a redirect")

    if not item.botMayEdit():
        raise RuntimeError(f"Skipping {qid} because it cannot be edited by bots")

    return item


@dataclass
class WikiDataPage:
    item: pwb.ItemPage
    test: bool

    # defaults for everything else
    actions: List = field(default_factory=list)
    claims: Dict = field(init=False)
    changed_claims: List = field(default_factory=list)
    deleted_claims: List = field(default_factory=list)
    claims_with_changed_references: List = field(default_factory=list)
    references_added: int = 0
    references_changed: int = 0
    references_deleted: int = 0
    data: Dict = field(default_factory=dict)
    summary: str = ""
    birth_year_low: Optional[int] = None
    birth_year_high: Optional[int] = None
    death_year_low: Optional[int] = None
    death_year_high: Optional[int] = None

    def __post_init__(self):
        # ensure_loaded before anything else
        self.item = ensure_loaded(self.item)
        # safely extract claims once
        self.claims = self.item.get().get("claims", {})

    @classmethod
    def from_qid(cls, site, qid: str, test: bool):
        item = pwb.ItemPage(site, qid)
        return cls(item=item, test=test)

    def _add_action(self, action):
        """
        Helper method to append an action to the actions list.
        """
        self.actions.append(action)

    def add_statement(
        self, statement: Statement, reference: Optional[Reference] = None
    ):
        """
        Creates an action to add a statement to the page.

        :param statement: The WikidataEntity to add as a statement.
        :param reference: Optional reference for the statement.
        """
        self._prepare_statement(statement, reference)
        self._add_action(AddStatement(statement))

    def delete_statement(self, statement: Statement):
        """
        Creates an action to delete a statement from the page.

        :param statement: The WikidataEntity to delete.
        """
        self._prepare_statement(statement)
        self._add_action(DeleteStatement(statement))

    def move_references(self, from_statement: Statement, to_statement: Statement):
        """
        Creates an action to move references from one statement to another.

        :param from_statement: The source statement for references.
        :param to_statement: The target statement for references.
        """
        self._prepare_statement(from_statement)
        self._prepare_statement(to_statement)
        self._add_action(MoveReferences(from_statement, to_statement))

    def check_date_statements(self):
        for prop in [
            wd.PID_DATE_OF_BIRTH,
            wd.PID_DATE_OF_BURIAL_OR_CREMATION,
            wd.PID_DATE_OF_DEATH,
            wd.PID_DATE_OF_BAPTISM,
        ]:
            self._add_action(CheckDateStatements(self, prop))

    def _prepare_statement(
        self, statement: WikidataEntity, reference: Optional[Reference] = None
    ):
        """
        Helper method to prepare a statement by setting its page and reference attributes.

        :param statement: The WikidataEntity to prepare.
        :param reference: Optional reference to associate with the statement.
        """
        statement.wd_page = self
        statement.reference = reference

    def apply(self) -> bool:
        """
        Applies all actions on the Wikidata page in sequence.

        :return: True if actions were successfully applied, False otherwise.
        """
        for phase in ["prepare", "apply", "post_apply"]:
            for action in self.actions:
                # Dynamically call the method on the specific subclass instance
                getattr(
                    action, phase
                )()  # Dynamically invokes the method (e.g., prepare, apply)

        added_objects = []
        changed_objects = []
        deleted_objects = []
        pids_added = set()
        pids_changed = set()
        pids_deleted = set()

        if self.claims:
            for prop in self.claims:
                for claim in self.claims[prop]:
                    if claim.snak is None:
                        added_objects.append(claim)
                        pids_added.add(claim.id)
                        self.save_changed_claim(claim)
                    elif claim.snak in self.deleted_claims:
                        deleted_objects.append(claim)
                        pids_deleted.add(claim.id)
                        self.save_deleted_claim(claim)
                    elif claim.snak in self.changed_claims:
                        changed_objects.append(claim)
                        pids_changed.add(claim.id)
                        self.save_changed_claim(claim)
                    elif claim.snak in self.claims_with_changed_references:
                        self.save_changed_claim(claim)

        print(f"added statements: {len(added_objects)}")
        print(f"changed statements: {len(changed_objects)}")
        print(f"deleted statements: {len(deleted_objects)}")
        print(f"references added: {self.references_added}")
        print(f"references changed: {self.references_changed}")
        print(f"references deleted: {self.references_deleted}")

        summary = self.summary

        def generate_description(action, pids, sort_func):
            desc = ", ".join(f"[[Property:{pid}]]" for pid in sort_func(pids))
            return f", {action} {desc}" if desc else ""

        def generate_reference_description(action, count):
            return f"{action} ({count}x)" if count else ""

        summary += generate_description("added", pids_added, sort_pids)
        summary += generate_description("changed", pids_changed, sort_pids)
        summary += generate_description("deleted", pids_deleted, sort_pids)

        ref_actions = [
            generate_reference_description("added", self.references_added),
            generate_reference_description("updated", self.references_changed),
            generate_reference_description("removed", self.references_deleted),
        ]

        ref_desc = ", ".join(filter(None, ref_actions))
        if ref_desc:
            summary += f", references {ref_desc}"

        if not self.data:
            print("No changes")
            return False
        elif self.test:
            print(summary)
            return True

        # see: https://www.wikidata.org/w/api.php?action=help&modules=wbeditentity
        # Removes the claims from the item with the provided GUIDs
        # api.php?action=wbeditentity&id=Q4115189&data={"claims":[
        #    {"id":"Q4115189$D8404CDA-25E4-4334-AF13-A3290BCD9C0F","remove":""},
        #    {"id":"Q4115189$GH678DSA-01PQ-28XC-HJ90-DDFD9990126X","remove":""}]}
        self.item.editEntity(data=self.data, summary=summary)
        return True

    def save_label(self, language: str, name: str):
        if "labels" not in self.data:
            self.data["labels"] = {}
        self.data["labels"][language] = name

    def save_alias(self, language: str, name: str):
        if "aliases" not in self.data:
            self.data["aliases"] = {}
        self.data["aliases"].setdefault(language, []).append(name)

    def save_changed_claim(self, claim: pwb.Claim):
        # add changed claim to self.data
        if not claim.on_item:
            claim.on_item = self.item
        if "claims" not in self.data:
            self.data["claims"] = []
        # REPO.save_claim(claim, summary=summary)
        self.data["claims"].append(claim.toJSON())

    def save_deleted_claim(self, claim: pwb.Claim):
        raise RuntimeError("Not implemented")
        # if not 'id' in claim:
        #     raise RuntimeError("save_deleted_claim: claim does not contain 'id'")

        # if "claims" not in self.data:
        #     self.data["claims"] = []
        # self.data["claims"].append({'id': claim['id'], 'remove': ''})

    def print(self):
        for statement in self.actions:
            print(statement)

    def has_property(self, pid: str) -> bool:
        if self.claims:
            return pid in self.claims
        else:
            return False

    def has_qid(self, pid: str) -> bool:
        qids = self.get_qids(pid)
        return len(qids) > 0

    def get_qids(self, pid: str):
        res = set()
        if self.claims:
            if pid in self.claims:
                for claim in self.claims[pid]:
                    if claim.getRank() == "deprecated":
                        continue
                    target = claim.getTarget()
                    if target:
                        qid = target.getID()
                        res.add(qid)
        return res

    def claim_changed(self, claim: pwb.Claim):
        if claim.snak:
            self.changed_claims.append(claim.snak)

    def add_claim(self, pid, claim: pwb.Claim):
        if self.claims:
            self.claims.setdefault(pid, []).append(claim)

    def reference_added(self, claim: pwb.Claim):
        if claim.snak:
            self.claims_with_changed_references.append(claim.snak)
            self.references_added += 1

    def reference_changed(self, claim: pwb.Claim):
        if claim.snak:
            self.claims_with_changed_references.append(claim.snak)
            self.references_changed += 1

    def reference_deleted(self, claim: pwb.Claim):
        if claim.snak:
            self.claims_with_changed_references.append(claim.snak)
            self.references_deleted += 1

    def determine_birth_death(self):
        date_mappings = {
            wd.PID_DATE_OF_BIRTH: self.add_birth_year,
            wd.PID_DATE_OF_BAPTISM: self.add_birth_year,
            wd.PID_DATE_OF_DEATH: self.add_death_year,
            wd.PID_DATE_OF_BURIAL_OR_CREMATION: self.add_death_year,
        }
        if self.claims:
            for pid, add_year_func in date_mappings.items():
                if pid in self.claims:
                    for claim in self.claims[pid]:
                        if claim.getRank() == "deprecated":
                            continue
                        date = claim.getTarget()
                        if date and date.precision >= PRECISION_YEAR:
                            add_year_func(date.year)

    def add_birth_year(self, year: int):
        if not self.birth_year_low or self.birth_year_low > year:
            self.birth_year_low = year
        if not self.birth_year_high or self.birth_year_high < year:
            self.birth_year_high = year

    def add_death_year(self, year: int):
        if not self.death_year_low or self.death_year_low > year:
            self.death_year_low = year
        if not self.death_year_high or self.death_year_high < year:
            self.death_year_high = year

    def has_qualifier(self, claim, qualifier_pid, target_qid) -> bool:
        if qualifier_pid in claim.qualifiers:
            for qualifier in claim.qualifiers[qualifier_pid]:
                if qualifier.getTarget().getID() == target_qid:
                    return True
        return False

    def is_circa(self, claim) -> bool:
        return self.has_qualifier(
            claim, PID_SOURCING_CIRCUMSTANCES, QID_CIRCA
        ) or self.has_qualifier(claim, PID_NATURE_OF_STATEMENT, QID_CIRCA)

    def is_possibly(self, claim) -> bool:
        return self.has_qualifier(
            claim, PID_SOURCING_CIRCUMSTANCES, QID_POSSIBLY
        ) or self.has_qualifier(claim, PID_NATURE_OF_STATEMENT, QID_POSSIBLY)

    # def base_check_url_redirect(self, url, headers):
    #     try:
    #         # Send a HEAD request to check for redirects or 404
    #         response = requests.get(url, allow_redirects=True, headers=headers)

    #         # Check if the URL results in a 404
    #         if response.status_code == 404:
    #             return (False, None)

    #         # Extract the final URL after redirects (if any)
    #         final_url = response.url

    #         return (True, final_url)

    #     except requests.RequestException as e:
    #         # Handle exceptions (e.g., network issues)
    #         print(f"Error occurred: {e}")
    #         return (False, None)

    def check_url_redirect(self, pid: Optional[str], external_id: Optional[str]):
        # ignore for now
        if pid == wd.PID_VIAF_ID and False:
            url = f"https://viaf.org/viaf/{external_id}"
            headers = {"Accept": "application/json"}
            is_valid, actual_url = self.base_check_url_redirect(url, headers)
            if not is_valid:
                return (False, None, None)

            if actual_url == url:
                return (True, pid, external_id)

            found_list = self.stated_in.extract_ids_from_url(actual_url)
            if not found_list:
                raise RuntimeError(f"Unrecognized url {actual_url}")

            if len(found_list) != 1:
                raise RuntimeError(
                    f"get_stated_in_from_url: multiple results for {actual_url}"
                )

            actual_pid, stated_in, actual_external_id, keep_url = found_list[0]
            return (True, actual_pid, actual_external_id)

        return (True, pid, external_id)


# SITE = pwb.Site("wikidata", "wikidata")
# SITE.login()
# SITE.get_tokens("csrf")
# REPO = SITE.data_repository()

# def main() -> None:
#     item = pwb.ItemPage(REPO, "Q112795079")
#     page = WikiDataPage(item, None, test=False)
#     page.load()
#     page.add_statement(DateOfDeath(Date(2010, 5, 5)))
#     page.apply()
#     print(f"birth year: {page.birth_year_low} - {page.birth_year_high}")
#     print(f"death year: {page.death_year_low} - {page.death_year_high}")


# if __name__ == "__main__":
#     main()
