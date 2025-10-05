import abc
import time
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Literal, Optional, Set

import pywikibot as pwb

import shared_lib.constants as wd

CALENDAR_JULIAN = "julian"
CALENDAR_GREGORIAN = "gregorian"
CALENDAR_ASSUMED_GREGORIAN = "assumed_gregorian"

PRECISION_DAY = 11
PRECISION_MONTH = 10
PRECISION_YEAR = 9
PRECISION_DECADE = 8
PRECISION_CENTURY = 7
PRECISION_MILLENNIUM = 6

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


def annotate_unicode(s):
    annotated = ""
    for char in s:
        if ord(char) > 127:
            name = unicodedata.name(char, "UNKNOWN CHARACTER")
            annotated += f"[{name}]"
        else:
            annotated += char
    return annotated


def print_color(text: str, color=None):
    if color:
        print(f"{color}{annotate_unicode(text)}{TextColor.ENDC}")
    else:
        print(text)


def sort_pids(pids):
    return sorted(pids, key=lambda x: int(x[1:]))


def is_sourced(claim: pwb.Claim):
    """Check if the claim has at least one reference."""
    return bool(claim.sources)


def precision_level(claim: pwb.Claim):
    """Return numeric precision level: year=9, month=10, day=11"""
    t = claim.getTarget()
    if t:
        return t.precision
    else:
        return 0


def has_qualifier(claim, qualifier_pid, target_qid) -> bool:
    if qualifier_pid in claim.qualifiers:
        for qualifier in claim.qualifiers[qualifier_pid]:
            if qualifier.getTarget().getID() == target_qid:
                return True
    return False


def is_circa(claim) -> bool:
    return has_qualifier(
        claim, wd.PID_SOURCING_CIRCUMSTANCES, wd.QID_CIRCA
    ) or has_qualifier(claim, wd.PID_NATURE_OF_STATEMENT, wd.QID_CIRCA)


def is_possibly(claim) -> bool:
    return has_qualifier(
        claim, wd.PID_SOURCING_CIRCUMSTANCES, wd.QID_POSSIBLY
    ) or has_qualifier(claim, wd.PID_NATURE_OF_STATEMENT, wd.QID_POSSIBLY)


def has_same_normalized_date(claim1: pwb.Claim, claim2: pwb.Claim):
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
        low_prec <= PRECISION_YEAR
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


def filter_claims_by_rank(claims):
    preferred_claims = [c for c in claims if c.rank == "preferred"]
    if preferred_claims:
        return preferred_claims
    # If no preferred, use normal (or any non-deprecated)
    return [c for c in claims if c.rank != "deprecated"]


def get_before_after(claim: pwb.Claim):
    def retrieve_date(prop):
        qlist = claim.qualifiers.get(prop, [])
        if len(qlist) > 1:
            raise RuntimeError(f"Multiple {prop} qualifiers")
        if not qlist:
            return None
        return qlist[0].getTarget()

    before = retrieve_date(wd.PID_LATEST_DATE)
    after = retrieve_date(wd.PID_EARLIEST_DATE)
    return before, after


def get_year_str(claim: pwb.Claim) -> Optional[str]:
    if not claim:
        return None
    prefix_list = []
    target = claim.getTarget()
    before, after = get_before_after(claim)
    if target and (before or after):
        raise RuntimeError("Both target and before/after")
    if before and after:
        raise RuntimeError("Both before and after")
    if not target:
        if before:
            prefix_list.append("bef. ")
            target = before
        elif after:
            prefix_list.append("aft. ")
            target = after
        else:
            return None
    normalized = target.normalize()
    if is_circa(claim):
        prefix_list.append("ca. ")
    if prefix_list:
        prefix = "".join(prefix_list)
    else:
        prefix = ""
    if normalized.precision >= PRECISION_YEAR:
        return f"{prefix}{normalized.year}"
    else:
        return None


def get_date_groups(claims) -> List[List[pwb.Claim]]:
    claims = filter_claims_by_rank(claims)

    # Build a dictionary: { precision_level: [claims] }
    precision_map = {}
    for claim in claims:
        if claim.rank == "deprecated":
            continue
        prec = precision_level(claim)
        if prec > PRECISION_DAY:
            raise RuntimeError("Unsupported precision > 11 (day)")
        precision_map.setdefault(prec, []).append(claim)

    groups = []
    # Highest precision first
    for prec in sorted(precision_map.keys(), reverse=True):
        for claim in precision_map[prec]:
            found = False
            for group in groups:
                if has_same_normalized_date(claim, group[0]):
                    group.append(claim)
                    found = True
                    break
            if not found:
                groups.append([claim])

    return groups


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


class StateInReference(Reference):
    def __init__(self, state_in_qid: str, identifier_pid: str, identifier: str):
        self.state_in_qid = state_in_qid
        self.identifier_pid = identifier_pid
        self.identifier = identifier

    def is_equal_reference(self, src) -> bool:
        if wd.PID_STATED_IN in src:
            for claim in src[wd.PID_STATED_IN]:
                actual = claim.getTarget()
                if actual.id == self.state_in_qid:
                    return True
        if self.identifier_pid in src:
            for claim in src[self.identifier_pid]:
                actual = claim.getTarget()
                if actual == self.identifier:
                    return True

        return False

    def create_source(self):
        source = OrderedDict()

        stated_in_claim = pwb.Claim(REPO, wd.PID_STATED_IN, is_reference=True)
        stated_in_claim.setTarget(pwb.ItemPage(REPO, self.state_in_qid))
        source[wd.PID_STATED_IN] = [stated_in_claim]

        return source


class WikipediaReference(Reference):
    def __init__(self, wikipedia_qid: str, url: str):
        self.wikipedia_qid = wikipedia_qid
        self.url = url

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

        url_claim = pwb.Claim(REPO, wd.PID_WIKIMEDIA_IMPORT_URL, is_reference=True)
        url_claim.setTarget(self.url)

        source[wd.PID_IMPORTED_FROM_WIKIMEDIA_PROJECT] = [imported_from_claim]
        source[wd.PID_WIKIMEDIA_IMPORT_URL] = [url_claim]

        return source


class WikidataEntity(abc.ABC):
    wd_page: "WikiDataPage"
    reference: Optional[Reference]

    def can_add(self) -> bool:
        return True

    @abc.abstractmethod
    def add(self):
        raise NotImplementedError

    def post_add(self):
        pass

    @abc.abstractmethod
    def get_description(self) -> str:
        raise NotImplementedError

    def print_action(self, action_str: str, color=None):
        print_color(f" {action_str} - {self.get_description()}", color)


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

    ActionKind = Literal[
        "add_claim",
        "add_label",
        "delete_claim",
        "delete_label",
        "change_claim",
        "change_labels",
        "read_claims",
        "read_labels",
    ]

    @abc.abstractmethod
    def get_action_kind(self) -> Set[ActionKind]:
        """
        Return a list of allowed action kind strings. Must only contain values from ActionKind.
        """
        raise NotImplementedError


class Statement(WikidataEntity):

    def __init__(self, only_change: bool = False, remove_old_claims: bool = False):
        self.only_change = only_change
        self.remove_old_claims = remove_old_claims

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
                            self.print_action("already added")
                        else:
                            self.print_action("reference added", TextColor.OKCYAN)
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
                            self.print_action("reference deleted")
                            self.delete_reference(claim, is_update=True)
                            did_delete_ref = True

                    self.print_action("statement changed", TextColor.OKBLUE)
                    self.update_statement(claim)

                    if self.reference:
                        self.print_action("reference added")
                        self.add_reference(claim, is_update=did_delete_ref)
                    return

        if self.can_add_claim:
            if self.remove_old_claims:
                if prop in self.wd_page.claims:
                    for claim in self.wd_page.claims[prop]:
                        self.delete_reference(
                            claim, is_update=False, can_delete_claim=True
                        )

            self.print_action("statement added", TextColor.OKGREEN)
            claim = self.add_statement()

            if self.reference:
                self.print_action("reference added")
                self.add_reference(claim)

    def can_add_claim(self) -> bool:
        return not self.only_change

    @abc.abstractmethod
    # optional because of ExternalIDStatement
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

    def delete_reference(
        self, claim: pwb.Claim, is_update: bool = False, can_delete_claim: bool = False
    ):
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
            if new_sources == [] and can_delete_claim:
                print("reference removed, claim deleted")
                self.wd_page.claim_deleted(claim)
            else:
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


class AddStatement(Action):
    def __init__(self, statement: WikidataEntity):
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

    def get_action_kind(self) -> Set[Action.ActionKind]:
        return {"add_claim"}


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

    def get_action_kind(self) -> Set[Action.ActionKind]:
        return {"delete_claim"}


class DeprecateLabel(Action):
    def __init__(self, wd_page: "WikiDataPage", old_label: str, new_label: str):
        self.wd_page = wd_page
        self.old_label = old_label
        self.new_label = new_label

    def prepare(self):
        pass

    def apply(self):
        for language in self.wd_page.item.labels:
            if self.wd_page.item.labels[language] == self.old_label:
                if language in ["en", "mul"]:
                    print_color(
                        f" {language} label: {self.old_label} -> {self.new_label}",
                        TextColor.OKBLUE,
                    )
                    self.wd_page.save_label(language, self.new_label)
                    self.wd_page.remove_saved_alias(language, self.new_label)
                else:
                    # remove label in other languages
                    print_color(
                        f" {language} label: {self.old_label} removed", TextColor.OKCYAN
                    )
                    self.wd_page.save_label(language, "")
                if language == "en":
                    if not self.wd_page.has_alias(language, self.old_label):
                        print_color(
                            f" {language} alias: {self.old_label} added",
                            TextColor.OKGREEN,
                        )
                        self.wd_page.save_alias(language, self.old_label)

    def post_apply(self):
        pass

    def get_action_kind(self) -> Set[Action.ActionKind]:
        return {"change_labels", "read_claims"}


class RecalcDateSpan(Action):
    def __init__(self, wd_page: "WikiDataPage", language: str, current_span_str: str):
        self.wd_page = wd_page
        self.language = language
        self.current_span_str = current_span_str

    def prepare(self):
        pass

    def apply(self):
        current_description = ""
        if self.language in self.wd_page.item.descriptions:
            current_description = self.wd_page.item.descriptions[self.language]
            if current_description and self.current_span_str not in current_description:
                return

        new_span_str = self.wd_page.calculate_date_span_description()
        if new_span_str and new_span_str != self.current_span_str:
            if current_description:
                new_description = current_description.replace(
                    self.current_span_str, new_span_str
                )
            else:
                new_description = new_span_str
            self.wd_page.save_description(self.language, new_description)
            print_color(
                f" {self.language} description changed to '{new_description}'",
                TextColor.OKBLUE,
            )

    def post_apply(self):
        pass

    def get_action_kind(self) -> Set[Action.ActionKind]:
        return {"read_claims", "change_labels"}


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

    def get_action_kind(self) -> Set[Action.ActionKind]:
        return {"change_claim"}


class PrefDateStatements(Action):
    def __init__(self, wd_page: "WikiDataPage", prop: str, references):
        self.wd_page = wd_page
        self.prop = prop
        self.references = references

    def get_action_kind(self) -> Set[Action.ActionKind]:
        return {"read_claims", "change_claim"}

    def process_property(self, claims):
        claims = self.wd_page.exclude_deleted_claims(claims)
        """Group statements by normalized date using a precision-to-claims map."""
        if any(claim.rank == "preferred" for claim in claims):
            return  # Skip if any statement is already preferred

        groups = get_date_groups(claims)

        if len(groups) <= 1:
            return

        best_groups = []
        ref_index = None

        def get_ref_index(group):
            best_index = None
            for claim in group:
                for index, ref in enumerate(self.references):
                    if ref.has_equal_reference(claim):
                        if not best_index or index < best_index:
                            best_index = index
                        break
            return best_index

        for group in groups:
            ref_index = get_ref_index(group)
            if ref_index is None:
                return
            if not best_groups or (best_group_index > ref_index):
                best_groups = [group]
                best_group_index = ref_index
            elif best_group_index == ref_index:
                best_groups.append(group)

        if best_groups and len(best_groups) == 1:
            best_group = best_groups[0]
            claim = best_group[0]
            claim.rank = "preferred"
            qualifier = pwb.Claim(
                REPO, wd.PID_REASON_FOR_PREFERRED_RANK, is_qualifier=True
            )
            target = pwb.ItemPage(REPO, wd.QID_BEST_REFERENCED_VALUE)
            qualifier.setTarget(target)
            claim.qualifiers.setdefault(wd.PID_REASON_FOR_PREFERRED_RANK, []).append(
                qualifier
            )
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


class CheckAliases(Action):
    def __init__(self, wd_page: "WikiDataPage"):
        self.wd_page = wd_page

    def get_action_kind(self) -> Set[Action.ActionKind]:
        return {"read_labels", "change_labels"}

    def prepare(self):
        pass

    def get_all_alias_languages(self):
        languages = set(self.wd_page.item.aliases.keys())
        if "aliases" in self.wd_page.data:
            for lang in self.wd_page.data["aliases"].keys():
                languages.add(lang)
        return languages

    def normalize_alias(self, alias: str) -> str:
        norm_alias = alias.replace("\u2010", "-")  # hyphen
        norm_alias = norm_alias.replace("\u00a0", " ")  # no-break space
        # strip start and end spaces and commas
        norm_alias = norm_alias.strip(", ")
        # replace multiple spaces with single space
        norm_alias = " ".join(norm_alias.split())
        return norm_alias

    def apply(self):
        languages = self.get_all_alias_languages()
        if not languages:
            return
        for language in languages:
            if (
                "aliases" in self.wd_page.data
                and language in self.wd_page.data["aliases"]
            ):
                aliases = self.wd_page.data["aliases"][language]
            elif language in self.wd_page.item.aliases:
                aliases = self.wd_page.item.aliases[language]
            else:
                continue
            new_aliases = []
            changed = False
            for alias in aliases:
                norm_alias = self.normalize_alias(alias)
                if norm_alias != alias:
                    print_color(
                        f" {language} alias: {alias} normalized to {norm_alias}",
                        TextColor.WARNING,
                    )
                    changed = True
                    # not continue; keep normalized alias
                if not norm_alias:
                    changed = True
                    # do not add empty
                    continue
                if norm_alias in new_aliases:
                    print_color(
                        f" {language} alias: {alias} duplicate removed (duplicate alias)",
                        TextColor.WARNING,
                    )
                    changed = True
                    # do not add duplicate
                    continue
                if self.wd_page.has_label(language, norm_alias):
                    print_color(
                        f" {language} alias: {alias} duplicate removed (same label)",
                        TextColor.WARNING,
                    )
                    changed = True
                    # do not add duplicate
                    continue
                if language != "mul":
                    if self.wd_page.has_label("mul", norm_alias):
                        print_color(
                            f" {language} alias: {alias} duplicate removed (same mul label)",
                            TextColor.WARNING,
                        )
                        changed = True
                        # do not add duplicate
                        continue
                    if language != "en" and self.wd_page.has_alias("mul", norm_alias):
                        print_color(
                            f" {language} alias: {alias} duplicate removed (same mul alias)",
                            TextColor.WARNING,
                        )
                        changed = True
                        # do not add duplicate
                        continue
                new_aliases.append(norm_alias)
            if changed:
                self.wd_page.save_aliases(language, new_aliases)

    def post_apply(self):
        pass


class CheckDateStatements(Action):
    def __init__(self, wd_page: "WikiDataPage", prop: str):
        self.wd_page = wd_page
        self.prop = prop

    def get_action_kind(self) -> Set[Action.ActionKind]:
        return {"read_claims", "change_claim"}

    def process_property(self, claims):
        claims = self.wd_page.exclude_deleted_claims(claims)
        """Group statements by normalized date using a precision-to-claims map."""
        if any(claim.rank == "preferred" for claim in claims):
            return  # Skip if any statement is already preferred

        groups = get_date_groups(claims)

        if len(groups) == 0:
            # only deprecated statements; nothing to do
            return
        if len(groups) != 1:
            raise RuntimeError("len(by_normalized) != 1")

        group = groups[0]
        if len(group) == 1:
            # only 1 claim, no need to change
            return

        for claim in group:
            if claim.qualifiers:
                if len(claim.qualifiers) != 0:
                    raise RuntimeError("1 group with claims with qualifiers")

        claim = group[0]
        if not is_sourced(claim):
            raise RuntimeError("Unsourced best claim")

        if claim.rank == "deprecated":
            raise RuntimeError("Best claim is deprecated")
        if claim.rank == "preferred":
            raise RuntimeError("Best claim is preferred")

        claim.rank = "preferred"
        qualifier = pwb.Claim(REPO, wd.PID_REASON_FOR_PREFERRED_RANK, is_qualifier=True)
        target = pwb.ItemPage(REPO, wd.QID_MOST_PRECISE_VALUE)
        qualifier.setTarget(target)
        claim.qualifiers.setdefault(wd.PID_REASON_FOR_PREFERRED_RANK, []).append(
            qualifier
        )
        self.wd_page.claim_changed(claim)

    def prepare(self):
        pass

    def apply(self):
        if self.prop in self.wd_page.claims:
            try:
                self.process_property(self.wd_page.claims[self.prop])
            except RuntimeError as e:
                print(f"CheckDateStatements {self.prop} failed: {e}")
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
        remove_old_claims: bool = False,
    ):
        super().__init__(only_change=False, remove_old_claims=remove_old_claims)
        self.qid = qid
        self.qid_alternative = qid_alternative
        # PID_START_TIME
        self.start_date = start_date
        # PID_END_TIME
        self.end_date = end_date
        # PID_SUBJECT_NAMED_AS
        self.subject_named_as: Optional[str] = None
        # PID_VOLUME
        self.volume: Optional[str] = None
        # PID_PAGES
        self.pages: Optional[str] = None
        # PID_URL
        self.url: Optional[str] = None

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
        wd.PID_NATURE_OF_STATEMENT,
        wd.PID_SOURCING_CIRCUMSTANCES,
        wd.PID_EARLIEST_DATE,
        wd.PID_LATEST_DATE,
        wd.PID_INSTANCE_OF,
    }

    def __init__(
        self,
        is_circa: bool,
        gregorian_pre_1584: bool,
        assumed_gregorian: bool = False,
        earliest: Optional[Date] = None,
        latest: Optional[Date] = None,
    ):
        self.is_circa = is_circa
        self.gregorian_pre_1584 = gregorian_pre_1584
        self.assumed_gregorian = assumed_gregorian
        self.earliest = earliest
        self.latest = latest

    def merge(self, other: "DateQualifiers"):
        self.is_circa = self.is_circa or other.is_circa
        self.gregorian_pre_1584 = self.gregorian_pre_1584 or other.gregorian_pre_1584
        self.assumed_gregorian = self.assumed_gregorian or other.assumed_gregorian
        if other.earliest:
            if self.earliest:
                if other.earliest != self.earliest:
                    raise RuntimeError("Can not merge because of diff earliest")
            else:
                self.earliest = other.earliest
        if other.latest:
            if self.latest:
                if other.latest != self.latest:
                    raise RuntimeError("Can not merge because of diff latest")
            else:
                self.latest = other.latest

    def recreate_qualifiers(self, claim: pwb.Claim):
        QUALIFIER_PRIORITY = {
            wd.PID_SOURCING_CIRCUMSTANCES: 0,
            wd.PID_EARLIEST_DATE: 1,
            wd.PID_LATEST_DATE: 2,
        }

        # Start with a shallow copy of existing qualifiers, but only keep allowed ones
        filtered = {}
        for pid, qualifiers in claim.qualifiers.items():
            if pid in {
                wd.PID_NATURE_OF_STATEMENT,
                wd.PID_SOURCING_CIRCUMSTANCES,
                wd.PID_INSTANCE_OF,
            }:
                filtered[pid] = []
                for q in qualifiers:
                    qid = q.getTarget().getID()
                    if qid == wd.QID_STATEMENT_WITH_GREGORIAN_DATE_EARLIER_THAN_1584:
                        if self.gregorian_pre_1584:
                            filtered[pid].append(q)
                    elif qid == wd.QID_CIRCA:
                        if self.is_circa:
                            filtered[pid].append(q)
                    elif qid == wd.QID_UNSPECIFIED_CALENDAR_ASSUMED_GREGORIAN:
                        if self.assumed_gregorian:
                            filtered[pid].append(q)
                    else:
                        filtered[pid].append(q)
            else:
                filtered[pid] = qualifiers

        # Add missing qualifiers if needed
        def add_qid_qual(pid, qid, condition):
            if condition:
                already = any(
                    q.getTarget().getID() == qid for q in filtered.get(pid, [])
                )
                if not already:
                    qual = pwb.Claim(REPO, pid, is_qualifier=True)
                    qual.setTarget(pwb.ItemPage(REPO, qid))
                    filtered.setdefault(pid, []).append(qual)

        def add_date_qual(pid, value: Optional[Date]):
            if value:
                already = pid in filtered
                if not already:
                    qual = pwb.Claim(REPO, pid, is_qualifier=True)
                    qual.setTarget(value.create_wikidata_item())
                    filtered.setdefault(pid, []).append(qual)

        add_qid_qual(wd.PID_SOURCING_CIRCUMSTANCES, wd.QID_CIRCA, self.is_circa)
        add_qid_qual(
            wd.PID_SOURCING_CIRCUMSTANCES,
            wd.QID_STATEMENT_WITH_GREGORIAN_DATE_EARLIER_THAN_1584,
            self.gregorian_pre_1584,
        )
        add_qid_qual(
            wd.PID_SOURCING_CIRCUMSTANCES,
            wd.QID_UNSPECIFIED_CALENDAR_ASSUMED_GREGORIAN,
            self.assumed_gregorian,
        )
        add_date_qual(wd.PID_EARLIEST_DATE, self.earliest)
        add_date_qual(wd.PID_LATEST_DATE, self.latest)

        # Sort qualifiers by custom order
        custom_pid_order = []
        seen = set()
        for pid in claim.qualifiers:
            if pid not in seen:
                custom_pid_order.append(pid)
                seen.add(pid)
        for pid in sorted(QUALIFIER_PRIORITY, key=lambda p: QUALIFIER_PRIORITY[p]):
            if pid in filtered and pid not in seen:
                custom_pid_order.append(pid)
                seen.add(pid)
        if (
            wd.PID_EARLIEST_DATE in custom_pid_order
            and wd.PID_LATEST_DATE in custom_pid_order
        ):
            i1, i2 = custom_pid_order.index(
                wd.PID_EARLIEST_DATE
            ), custom_pid_order.index(wd.PID_LATEST_DATE)
            if i1 > i2:
                item = custom_pid_order.pop(i1)
                custom_pid_order.insert(i2, item)

        ordered_dict = OrderedDict(
            (key, filtered[key]) for key in custom_pid_order if key in filtered
        )
        return ordered_dict

    @classmethod
    def from_claim(cls, claim) -> "DateQualifiers":
        quals = claim.qualifiers

        # 1. reject any unknown property
        extra = set(quals) - cls.ALLOWED_PROPS
        if extra:
            raise RuntimeError(f"Unsupported qualifier props: {extra}")

        # 2. parse is_circa, gregorian_date_earlier_than_1584
        seen_circa = False
        seen_gregorian_pre_1584 = False
        seen_assumed_gregorian = False
        for qualifier_pid in (
            wd.PID_NATURE_OF_STATEMENT,
            wd.PID_SOURCING_CIRCUMSTANCES,
            wd.PID_INSTANCE_OF,
        ):
            for qualifier in quals.get(qualifier_pid, []):
                qid = qualifier.getTarget().getID()
                if qid == wd.QID_CIRCA:
                    seen_circa = True
                elif qid == wd.QID_STATEMENT_WITH_GREGORIAN_DATE_EARLIER_THAN_1584:
                    seen_gregorian_pre_1584 = True
                elif qid == wd.QID_UNSPECIFIED_CALENDAR_ASSUMED_GREGORIAN:
                    seen_assumed_gregorian = True
                else:
                    raise RuntimeError(f"Unknown value {qid} for {qualifier_pid}")

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

        return cls(
            is_circa=seen_circa,
            gregorian_pre_1584=seen_gregorian_pre_1584,
            assumed_gregorian=seen_assumed_gregorian,
            earliest=earliest,
            latest=latest,
        )

    @classmethod
    def from_statement(cls, stmt: "DateStatement") -> "DateQualifiers":
        assumed_gregorian = (
            getattr(stmt.date, "calendar", None) == CALENDAR_ASSUMED_GREGORIAN
        )
        return cls(
            is_circa=stmt.is_circa,
            gregorian_pre_1584=False,
            assumed_gregorian=assumed_gregorian,
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
            and self.assumed_gregorian == other.assumed_gregorian
            and self.gregorian_pre_1584 == other.gregorian_pre_1584
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
            # ignore gregorian_date_earlier_than_1584
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
        remove_old_claims: bool = False,
    ):
        super().__init__(only_change=only_change, remove_old_claims=remove_old_claims)
        self.date = date
        self.earliest = earliest
        self.latest = latest
        self.is_circa = is_circa
        self.ignore_calendar_model = ignore_calendar_model
        self.require_unreferenced = require_unreferenced

    def __repr__(self):
        if self.earliest or self.latest:
            return f"{self.__class__.__name__}(date={self.date}, earliest={self.earliest}, latest={self.latest}, is_circa={self.is_circa}')"
        else:
            return f"{self.__class__.__name__}(date={self.date}, is_circa={self.is_circa}')"

    def can_attach_to_claim(self, claim, strict: bool) -> bool:
        dt = claim.getTarget()
        ignore_calendar_model = not strict and self.ignore_calendar_model
        if not Date.is_equal(
            self.date, dt, ignore_calendar_model=ignore_calendar_model
        ):
            return False

        has_circa = is_circa(claim)
        if self.is_circa != has_circa:
            return False

        if self.require_unreferenced:
            refs = claim.getSources()
            if refs:
                return False

        # build & validate both qualifier‐sets
        claim_qs = DateQualifiers.from_claim(claim)  # may raise
        target_qs = DateQualifiers.from_statement(self)

        return DateQualifiers.is_equal(claim_qs, target_qs, strict)

    def update_statement(self, claim: pwb.Claim):
        claim_changed = False
        if self.date:
            new_dt = self.date.create_wikidata_item()
            old_dt = claim.getTarget()
            if not old_dt:
                raise RuntimeError("No old date")
            if not self.date.calendar:
                new_dt.calendarmodel = old_dt.calendarmodel
            if new_dt.normalize() != old_dt.normalize():
                claim.setTarget(new_dt)
                claim_changed = True

        claim_qs = DateQualifiers.from_claim(claim)  # may raise
        target_qs = DateQualifiers.from_statement(self)
        target_qs.merge(claim_qs)

        if self.date:
            if self.date.calendar == CALENDAR_JULIAN:
                target_qs.gregorian_pre_1584 = False
                target_qs.assumed_gregorian = False

        if claim_qs != target_qs:
            claim.qualifiers = target_qs.recreate_qualifiers(claim)
            claim_changed = True

        if claim_changed:
            self.wd_page.claim_changed(claim)

    def add_statement(self) -> Optional[pwb.Claim]:
        pid = self.get_prop()
        claim = pwb.Claim(REPO, pid)
        if self.date:
            claim.setTarget(self.date.create_wikidata_item())
        else:
            claim.setSnakType("somevalue")

        target_qs = DateQualifiers.from_statement(self)
        claim.qualifiers = target_qs.recreate_qualifiers(claim)
        self.wd_page.add_claim(pid, claim)
        return claim


class ExternalIDStatement(Statement):
    def __init__(
        self,
        url: Optional[str] = None,
        prop: Optional[str] = None,
        external_id: Optional[str] = None,
    ):
        super().__init__()
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

    def get_description(self) -> str:
        return f"External ID {self.prop}"


class Label(WikidataEntity):
    def __init__(self, text, language):
        self.text = text
        self.language = language

    def __repr__(self):
        return f"Label(text='{self.text}', language='{self.language}')"

    def add(self):
        if not self.wd_page.has_language_label(self.language):
            self.print_action("label added", TextColor.OKGREEN)
            self.wd_page.save_label(self.language, self.text)
            return

        if self.wd_page.has_label(self.language, self.text):
            self.print_action("already added")
            return

        if self.wd_page.has_alias(self.language, self.text):
            self.print_action("already added (as alias)")
        else:
            self.print_action(" alias added", TextColor.OKGREEN)
            self.wd_page.save_alias(self.language, self.text)

    def get_description(self) -> str:
        return f"{self.language}:{self.text}"


class DateOfBirth(DateStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_DATE_OF_BIRTH

    def post_add(self):
        if self.date:
            if self.date.precision:
                if self.date.precision >= PRECISION_YEAR:
                    self.wd_page.add_birth_year(self.date.year)

    def get_description(self) -> str:
        return "Date of birth"


class DateOfBaptism(DateStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_DATE_OF_BAPTISM

    def post_add(self):
        if self.date:
            if self.date.precision:
                if self.date.precision >= PRECISION_YEAR:
                    self.wd_page.add_birth_year(self.date.year)

    def get_description(self) -> str:
        return "Date of baptism"


class DateOfDeath(DateStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_DATE_OF_DEATH

    def post_add(self):
        if self.date:
            if self.date.precision:
                if self.date.precision >= PRECISION_YEAR:
                    self.wd_page.add_death_year(self.date.year)

    def get_description(self) -> str:
        return "Date of death"


class DateOfProbate(DateStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_DATE_OF_PROBATE

    def get_description(self) -> str:
        return "Date of probate"


class DateOfBurialOrCremation(DateStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_DATE_OF_BURIAL_OR_CREMATION

    def post_add(self):
        if self.date:
            if self.date.precision:
                if self.date.precision >= PRECISION_YEAR:
                    self.wd_page.add_death_year(self.date.year)

    def get_description(self) -> str:
        return "Date of burial or cremation"


class PlaceOfBirth(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_PLACE_OF_BIRTH

    def post_add(self):
        pass

    def get_description(self) -> str:
        return "Place of birth"


class PlaceOfDeath(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_PLACE_OF_DEATH

    def get_description(self) -> str:
        return "Place of death"


class SexOrGender(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_SEX_OR_GENDER

    def get_description(self) -> str:
        return "Sex or gender"


class Father(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_FATHER

    def get_description(self) -> str:
        return "Father"


class Mother(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_MOTHER

    def get_description(self) -> str:
        return "Mother"


class Child(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_CHILD

    def get_description(self) -> str:
        return "Child"


class Patronym(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_PATRONYM_OR_MATRONYM

    def get_description(self) -> str:
        return "Patronym"


class Occupation(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_OCCUPATION

    def get_description(self) -> str:
        return "Occupation"


class MilitaryOrPoliceRank(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_MILITARY_OR_POLICE_RANK

    def get_description(self) -> str:
        return "Military or police rank"


class NobleTitle(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_NOBLE_TITLE

    def get_description(self) -> str:
        return "Noble title"


class PositionHeld(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_POSITION_HELD

    def get_description(self) -> str:
        return "Position held"


class WorkLocation(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_WORK_LOCATION

    def get_description(self) -> str:
        return "Work location"


class Residence(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_RESIDENCE

    def get_description(self) -> str:
        return "Residence"


class MasterOf(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_STUDENT

    def get_description(self) -> str:
        return "Master of"


class DescribedBySource(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_DESCRIBED_BY_SOURCE

    def get_description(self) -> str:
        return "Described by source"


class DepictedBy(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_DEPICTED_BY

    def get_description(self) -> str:
        return "Depicted by"


class StudentOf(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_STUDENT_OF

    def get_description(self) -> str:
        return "Student of"


class ReligionOrWorldview(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_RELIGION_OR_WORLDVIEW

    def get_description(self) -> str:
        return "Religion or worldview"


class AcademicDegree(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_ACADEMIC_DEGREE

    def get_description(self) -> str:
        return "academic degree"


class MilitaryBranch(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_MILITARY_BRANCH

    def get_description(self) -> str:
        return "military branch"


class HonorificPrefix(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_HONORIFIC_PREFIX

    def get_description(self) -> str:
        return "honorific prefix"


class HonorificSuffix(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_HONORIFIC_SUFFIX

    def get_description(self) -> str:
        return "honorific suffix"


class MedicalCondition(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_MEDICAL_CONDITION

    def get_description(self) -> str:
        return "Medical condition"


class Genre(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_GENRE

    def get_description(self) -> str:
        return "Genre"


class LanguagesSpokenWrittenOrSigned(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_LANGUAGES_SPOKEN_WRITTEN_OR_SIGNED

    def get_description(self) -> str:
        return "Languages spoken written or signed"


class MemberOf(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_MEMBER_OF

    def get_description(self) -> str:
        return "Member of"


class AwardReceived(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_AWARD_RECEIVED

    def get_description(self) -> str:
        return "Award received"


def ensure_loaded(item: pwb.ItemPage):
    try:
        qid = item.title()

        if not qid.startswith("Q"):  # ignore property pages and lexeme pages
            raise RuntimeError(f"Skipping {qid} because it does not start with a Q")

        if not item.exists():
            raise RuntimeError(f"Skipping {qid} because it does not exists")

        if item.isRedirectPage():
            raise RuntimeError(f"Skipping {qid} because it is a redirect")

        if not item.botMayEdit():
            raise RuntimeError(f"Skipping {qid} because it cannot be edited by bots")

    except pwb.exceptions.MaxlagTimeoutError as ex:
        print("Max lag timeout. Sleeping")
        time.sleep(MAX_LAG_BACKOFF_SECS)
        raise RuntimeError("Max lag timeout")

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
        self, statement: WikidataEntity, reference: Optional[Reference] = None
    ):
        """
        Creates an action to add a statement to the page.

        :param statement: The WikidataEntity to add as a statement.
        :param reference: Optional reference for the statement.
        """
        self._prepare_entity(statement, reference)
        self._add_action(AddStatement(statement))

    def delete_statement(self, statement: Statement):
        """
        Creates an action to delete a statement from the page.

        :param statement: The WikidataEntity to delete.
        """
        self._prepare_entity(statement)
        self._add_action(DeleteStatement(statement))

    def move_references(self, from_statement: Statement, to_statement: Statement):
        """
        Creates an action to move references from one statement to another.

        :param from_statement: The source statement for references.
        :param to_statement: The target statement for references.
        """
        self._prepare_entity(from_statement)
        self._prepare_entity(to_statement)
        self._add_action(MoveReferences(from_statement, to_statement))

    def deprecate_label(self, old_label, new_label: str):
        self._add_action(DeprecateLabel(self, old_label, new_label))

    def recalc_date_span(self, language: str, current_str: str):
        self._add_action(RecalcDateSpan(self, language, current_str))

    def pref_date_statements(self, references):
        for prop in [
            wd.PID_DATE_OF_BIRTH,
            wd.PID_DATE_OF_BURIAL_OR_CREMATION,
            wd.PID_DATE_OF_DEATH,
            wd.PID_DATE_OF_BAPTISM,
            wd.PID_DATE_OF_PROBATE,
        ]:
            self._add_action(PrefDateStatements(self, prop, references))

    def check_date_statements(self):
        for prop in [
            wd.PID_DATE_OF_BIRTH,
            wd.PID_DATE_OF_BURIAL_OR_CREMATION,
            wd.PID_DATE_OF_DEATH,
            wd.PID_DATE_OF_BAPTISM,
            wd.PID_DATE_OF_PROBATE,
        ]:
            self._add_action(CheckDateStatements(self, prop))

    def check_aliases(self):
        self._add_action(CheckAliases(self))

    def _prepare_entity(
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

        # Define ActionKind order
        ACTION_KIND_ORDER = [
            "add_claim",
            "add_label",
            "delete_claim",
            "delete_label",
            "change_claim",
            "change_labels",
            "read_claims",
            "read_labels",
            "update_claims",
        ]

        def kind_index(kind):
            return ACTION_KIND_ORDER.index(kind)

        def sort_key(action):
            kinds = action.get_action_kind()
            if not kinds:
                return (len(ACTION_KIND_ORDER), len(ACTION_KIND_ORDER))
            earliest = min(kind_index(k) for k in kinds)
            latest = max(kind_index(k) for k in kinds)
            return (latest, earliest)

        self.actions.sort(key=sort_key)

        for phase in ["prepare", "apply", "post_apply"]:
            for action in self.actions:
                getattr(action, phase)()

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

        # summary = (
        #     summary
        #     + ", test edit for [[Wikidata:Requests_for_permissions/Bot/DifoolBot_7]]"
        # )

        # see: https://www.wikidata.org/w/api.php?action=help&modules=wbeditentity
        # Removes the claims from the item with the provided GUIDs
        # api.php?action=wbeditentity&id=Q4115189&data={"claims":[
        #    {"id":"Q4115189$D8404CDA-25E4-4334-AF13-A3290BCD9C0F","remove":""},
        #    {"id":"Q4115189$GH678DSA-01PQ-28XC-HJ90-DDFD9990126X","remove":""}]}
        self.item.editEntity(data=self.data, summary=summary)
        return True

    def exclude_deleted_claims(self, claims):
        result = []
        for claim in claims:
            if claim.snak and claim.snak in self.deleted_claims:
                pass
            else:
                result.append(claim)
        return result

    def has_language_label(self, language: str) -> bool:
        if language in self.item.labels:
            return True

        if "labels" in self.data:
            if language in self.data["labels"]:
                return True

        return False

    def has_label(self, language: str, text: str) -> bool:
        # already saved?
        if "labels" in self.data:
            if language in self.data["labels"]:
                return self.data["labels"][language] == text

        # already on the page?
        if language not in self.item.labels:
            return False
        return self.item.labels[language] == text

    def has_alias(self, language: str, text: str) -> bool:
        # already saved?
        if "aliases" in self.data:
            if language in self.data["aliases"]:
                return text in self.data["aliases"][language]

        # already on the page?
        if language not in self.item.aliases:
            return False
        return text in self.item.aliases[language]

    def save_label(self, language: str, value: str):
        if "labels" not in self.data:
            self.data["labels"] = {}
        self.data["labels"][language] = value

    def save_description(self, language: str, value: str):
        if "descriptions" not in self.data:
            self.data["descriptions"] = {}
        self.data["descriptions"][language] = value

    def remove_saved_alias(self, language: str, value: str):
        if "aliases" in self.data and language in self.data["aliases"]:
            if value in self.data["aliases"][language]:
                self.data["aliases"][language].remove(value)
                if not self.data["aliases"][language]:
                    self.data["aliases"].pop(language)
                    if not self.data["aliases"]:
                        self.data.pop("aliases")

    def save_aliases(self, language: str, values: List[str]):
        if "aliases" not in self.data:
            self.data["aliases"] = {}
        # overwrite existing aliases
        self.data["aliases"][language] = values

    def save_alias(self, language: str, value: str):
        if "aliases" not in self.data:
            self.data["aliases"] = {}
        if language not in self.data["aliases"]:
            if language in self.item.aliases:
                self.data["aliases"][language] = self.item.aliases[language]
        self.data["aliases"].setdefault(language, []).append(value)

    def save_changed_claim(self, claim: pwb.Claim):
        # add changed claim to self.data
        if not claim.on_item:
            claim.on_item = self.item
        if "claims" not in self.data:
            self.data["claims"] = []
        # REPO.save_claim(claim, summary=summary)
        self.data["claims"].append(claim.toJSON())

    def save_deleted_claim(self, claim: pwb.Claim):
        id = claim.snak
        if not id:
            raise RuntimeError("No snak to delete")

        if "claims" not in self.data:
            self.data["claims"] = []
        self.data["claims"].append({"id": id, "remove": ""})

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

    def claim_deleted(self, claim: pwb.Claim):
        if claim.snak:
            self.deleted_claims.append(claim.snak)

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

    def calculate_date_span_description(self) -> str | None:
        if wd.PID_DATE_OF_BIRTH in self.claims:
            claims = self.claims[wd.PID_DATE_OF_BIRTH]
            claims = self.exclude_deleted_claims(claims)
            claims = filter_claims_by_rank(claims)

            groups = get_date_groups(claims)

            birth_years = set()
            for group in groups:
                claim = next(iter(group))
                birth_year = get_year_str(claim)
                birth_years.add(birth_year)
            if len(birth_years) > 1:
                return None
            if len(birth_years) == 1:
                birth_year = next(iter(birth_years))
            else:
                birth_year = None
        else:
            birth_year = None

        if wd.PID_DATE_OF_DEATH in self.claims:
            claims = self.claims[wd.PID_DATE_OF_DEATH]
            claims = self.exclude_deleted_claims(claims)
            claims = filter_claims_by_rank(claims)

            groups = get_date_groups(claims)

            death_years = set()
            for group in groups:
                claim = next(iter(group))
                death_year = get_year_str(claim)
                death_years.add(death_year)
            if len(death_years) > 1:
                return None
            if len(death_years) == 1:
                death_year = next(iter(death_years))
            else:
                death_year = None
        else:
            death_year = None

        if birth_year or death_year:
            if not birth_year:
                span = f"d. {death_year}"
            elif not death_year:
                span = f"b. {birth_year}"
            else:
                span = f"{birth_year}–{death_year}"
            return f"({span})"
        return None

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
