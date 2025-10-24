import abc
import time
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Literal, Optional, Set

import pywikibot as pwb

import shared_lib.constants as wd
from shared_lib.date_value import (
    CALENDAR_ASSUMED_GREGORIAN,
    CALENDAR_JULIAN,
    PRECISION_DAY,
    PRECISION_YEAR,
    Date,
)
from shared_lib.qualifier_handler import QualifierHandler

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


class ClaimChangeType(Enum):
    CLAIM_CHANGED = "claim_changed"
    CLAIM_DELETED = "claim_deleted"
    REFERENCE_ADDED = "reference_added"
    REFERENCE_CHANGED = "reference_changed"
    REFERENCE_DELETED = "reference_deleted"


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


def is_weak_source(source):
    if wd.PID_BASED_ON_HEURISTIC in source:
        return True
    if wd.PID_IMPORTED_FROM_WIKIMEDIA_PROJECT in source:
        return True
    if wd.PID_STATED_IN in source:
        has_viaf = False
        for claim in source[wd.PID_STATED_IN]:
            id = claim.getTarget().getID()
            has_viaf = (
                id == wd.QID_VIRTUAL_INTERNATIONAL_AUTHORITY_FILE
                or id == wd.QID_VIAF_ID
            )
            if not has_viaf:
                return False
        if has_viaf:
            return True

    return False


def has_strong_source(claim):
    srcs = claim.getSources()
    for src in srcs:
        if not is_weak_source(src):
            return True
    return False


class Reference(abc.ABC):
    @abc.abstractmethod
    def is_equal_reference(self, src) -> bool:
        raise NotImplementedError

    @abc.abstractmethod
    def create_source(self):
        raise NotImplementedError

    @abc.abstractmethod
    def is_strong_reference(self) -> bool:
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


@dataclass
class StatementConfig:
    # do not add a statement only change statements
    only_change: bool = False
    # remove statements with the same ref + prop
    remove_old_claims: bool = False
    # do not add a reference to existing statements if the statement already has a 'strong' reference
    skip_if_strong_refs: bool = False
    # match dates even if they have different calendar models (Julian/Gregorian)
    ignore_calendar_model: bool = False
    # only add if statement is unreferenced; ie add reference
    require_unreferenced: bool = False


class Statement(WikidataEntity):

    def __init__(self, config: Optional[StatementConfig] = None):
        self.config = config or StatementConfig()

    def check_remove_weak_references(self, claim):
        if (
            self.reference and self.reference.is_strong_reference()
        ) or has_strong_source(claim):
            self.remove_weak_references(claim)

    def check_add_reference(self, claim):
        if not self.reference:
            return

        if self.reference.has_equal_reference(claim):
            self.print_action("already added")
        elif self.config.skip_if_strong_refs and has_strong_source(claim):
            self.print_action("already has strong reference")
        else:
            self.print_action("reference added", TextColor.OKCYAN)
            self.add_reference(claim)

    # TODO : rename?
    def add(self):
        prop = self.get_prop()
        if prop in self.wd_page.claims:
            for claim in self.wd_page.claims[prop]:
                if self.can_attach_to_claim(claim, strict=True):
                    if claim.rank == "deprecated":
                        self.print_action("deprecated claim", TextColor.WARNING)
                        return
                    self.check_remove_weak_references(claim)
                    self.check_add_reference(claim)
                    return

        if prop in self.wd_page.claims:
            for claim in self.wd_page.claims[prop]:
                if self.can_attach_to_claim(claim, strict=False):
                    if claim.rank == "deprecated":
                        self.print_action(
                            "skipping deprecated claim", TextColor.WARNING
                        )
                        return

                    self.check_remove_weak_references(claim)

                    if self.update_statement(claim):
                        self.print_action("statement changed", TextColor.OKBLUE)

                        did_delete_ref = False
                        if self.reference:
                            if self.reference.has_equal_reference(claim):
                                self.print_action("reference deleted")
                                self.wd_page.delete_reference(
                                    claim, self.reference, is_update=True
                                )
                                did_delete_ref = True

                        if self.reference:
                            self.print_action("reference added")
                            self.add_reference(claim, is_update=did_delete_ref)
                    return

        if self.can_add_claim:
            if self.reference:
                if self.config.remove_old_claims:
                    if prop in self.wd_page.claims:
                        for claim in self.wd_page.claims[prop]:
                            self.wd_page.delete_reference(
                                claim,
                                self.reference,
                                is_update=False,
                                can_delete_claim=True,
                            )

            self.print_action("statement added", TextColor.OKGREEN)
            claim = self.add_statement()

            if self.reference:
                self.print_action("reference added")
                self.add_reference(claim)

    def can_add_claim(self) -> bool:
        return not self.config.only_change

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

    def remove_weak_references(self, claim: pwb.Claim, is_update: bool = False):
        if not self.reference:
            return

        new_sources = []
        changed = False
        for source in claim.sources:
            if is_weak_source(source):
                changed = True
            else:
                new_sources.append(source)

        if changed:
            claim.sources = new_sources
            if not is_update:
                print("weak references removed")
                self.wd_page.reference_deleted(claim)

    @abc.abstractmethod
    def update_statement(self, claim: pwb.Claim) -> bool:
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


class RemoveReferences(Action):
    def __init__(self, wd_page: "WikiDataPage", pid: str, reference: Reference):
        self.wd_page = wd_page
        self.pid = pid
        self.reference = reference

    def prepare(self):
        pass

    def apply(self):
        if self.pid in self.wd_page.claims:
            for claim in self.wd_page.claims[self.pid]:
                self.wd_page.delete_reference(
                    claim, self.reference, is_update=False, can_delete_claim=False
                )

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


class DeprecateDate(Action):
    def __init__(self, wd_page: "WikiDataPage", pid: str, date: Date):
        self.wd_page = wd_page
        self.pid = pid
        self.date = date
        if self.pid == wd.PID_DATE_OF_BIRTH:
            self.real_desc = "date of birth"
            self.approx_desc = "date of baptism"
            self.qid_deprecated_reason = (
                wd.QID_BAPTISM_DATE_IMPORTED_OR_INTERPRETED_AS_BIRTH_DATE
            )
            self.qid_inferred_from = wd.QID_INFERRED_FROM_DATE_OF_BAPTISM
        elif self.pid == wd.PID_DATE_OF_DEATH:
            self.real_desc = "date of death"
            self.approx_desc = "date of funeral"
            self.qid_deprecated_reason = (
                wd.QID_BURIAL_DATE_IMPORTED_OR_INTERPRETED_AS_DEATH_DATE
            )
            self.qid_inferred_from = wd.QID_INFERRED_FROM_DATE_OF_BURIAL_OR_CREMATION
        else:
            raise RuntimeError("Unknown property")

    def prepare(self):
        pass

    def remove_most_precise(self, claim) -> bool:
        if wd.PID_REASON_FOR_PREFERRED_RANK in claim.qualifiers:
            for qualifier in claim.qualifiers[wd.PID_REASON_FOR_PREFERRED_RANK]:
                if qualifier.getTarget().getID() != wd.QID_MOST_PRECISE_VALUE:
                    return False
            claim.qualifiers.pop(wd.PID_REASON_FOR_PREFERRED_RANK)

        return True

    def apply(self):
        if self.date.precision != PRECISION_DAY:
            raise RuntimeError("Date precision must be day")

        self.deprecate_same_dates()
        self.add_based_on_heuristic()

    def add_based_on_heuristic(self):
        if self.pid not in self.wd_page.claims:
            return
        claims = self.wd_page.exclude_deleted_claims(self.wd_page.claims[self.pid])
        for claim in claims:
            if claim.rank != "deprecated":
                return

        year = self.date.year
        month = self.date.month
        day = self.date.day

        if (month == 1) and (day <= 9):
            raise RuntimeError(
                f"Has no {self.real_desc}; {self.approx_desc} month is {month} day is {day}"
            )

        print(f" {self.real_desc} added: {get_year_str(claim)}")
        year_date = Date(year=year, precision=PRECISION_YEAR)

        claim = pwb.Claim(REPO, self.pid)
        claim.setTarget(year_date.create_wikidata_item())

        source = OrderedDict()

        based_on = pwb.Claim(REPO, wd.PID_BASED_ON_HEURISTIC, is_reference=True)
        based_on.setTarget(pwb.ItemPage(REPO, self.qid_inferred_from))
        source[wd.PID_BASED_ON_HEURISTIC] = [based_on]

        claim.sources.append(source)
        self.wd_page.add_claim(self.pid, claim)

    def deprecate_same_dates(self):
        if self.pid not in self.wd_page.claims:
            return
        claims = self.wd_page.exclude_deleted_claims(self.wd_page.claims[self.pid])
        for claim in claims:
            if is_circa(claim):
                continue
            date_real = claim.getTarget()
            if date_real == None:
                # date is unknown
                continue
            if not Date.is_equal(date_real, self.date, ignore_calendar_model=True):
                continue

            if claim.rank == "preferred":
                if not self.remove_most_precise(claim):
                    raise RuntimeError(
                        f"{self.real_desc} equal to {self.approx_desc}, but cannot change to deprecated"
                    )

            print(f" {self.real_desc} deprecated: {get_year_str(claim)}")
            claim.rank = "deprecated"

            add_qualifier = True
            if wd.PID_REASON_FOR_DEPRECATED_RANK in claim.qualifiers:
                for q in claim.qualifiers[wd.PID_REASON_FOR_DEPRECATED_RANK]:
                    if q.getTarget().getID() == self.qid_deprecated_reason:
                        add_qualifier = False

            if add_qualifier:
                qualifier = pwb.Claim(
                    REPO, wd.PID_REASON_FOR_DEPRECATED_RANK, is_qualifier=True
                )
                target = pwb.ItemPage(REPO, self.qid_deprecated_reason)
                qualifier.setTarget(target)

                claim.qualifiers.setdefault(
                    wd.PID_REASON_FOR_DEPRECATED_RANK, []
                ).append(qualifier)

            self.wd_page.claim_changed(claim)

    def post_apply(self):
        pass

    def get_action_kind(self) -> Set[Action.ActionKind]:
        return {"read_claims", "change_claim"}


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


class MonolingualTextStatement(Statement):
    def __init__(
        self,
        text: str,
        language: str,
        config: Optional[StatementConfig] = None,
    ):
        super().__init__(config)
        self.text = text
        self.language = language

    def __repr__(self):
        return (
            f"{self.__class__.__name__}(text='{self.text}', language='{self.language}')"
        )

    def can_attach_to_claim(self, claim, strict: bool) -> bool:
        raise NotImplementedError

    def update_statement(self, claim: pwb.Claim) -> bool:
        return False

    def add_statement(self) -> pwb.Claim:
        pid = self.get_prop()
        claim = pwb.Claim(REPO, pid)
        text = pwb.WbMonolingualText(self.text, self.language)
        claim.setTarget(text)

        # external_q = self.create_qualifiers()
        # claim.qualifiers = external_q.recreate_qualifiers(claim)
        self.wd_page.add_claim(pid, claim)

        return claim


class ItemStatement(Statement):
    def __init__(
        self,
        qid: Optional[str] = None,
        start_date: Optional[Date] = None,
        end_date: Optional[Date] = None,
        qid_alternative: Optional[str] = None,
        based_on: Optional[str] = None,
        config: Optional[StatementConfig] = None,
    ):
        super().__init__(config)
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
        # PID_BASED_ON
        self.based_on = based_on

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

        # build & validate both qualifier‐sets
        claim_qs = QualifierHandler()
        claim_qs.from_claim(claim)
        target_qs = self.create_qualifiers()

        return claim_qs.is_equal(target_qs, strict)

        # qualifiers = [
        #     (wd.PID_START_TIME, self.start_date),
        #     (wd.PID_END_TIME, self.end_date),
        #     (wd.PID_SUBJECT_NAMED_AS, self.subject_named_as),
        #     (wd.PID_VOLUME, self.volume),
        #     (wd.PID_PAGES, self.pages),
        #     (wd.PID_URL, self.url),
        # ]

        # for qualifier, value in qualifiers:
        #     if qualifier in claim.qualifiers and value:
        #         if not self.has_equal_qualifier(value, claim, qualifier):
        #             return False
        #     elif strict and (qualifier in claim.qualifiers or value):
        #         return False
        #     elif qualifier in claim.qualifiers:
        #         # for example URL in Wikitext is not in import data
        #         raise RuntimeError(
        #             "Qualifier error: Qualifier in claim but not in data"
        #         )

        # return True

    def create_qualifiers(self) -> QualifierHandler:
        qh = QualifierHandler()
        if self.start_date:
            qh.add_date(wd.PID_START_TIME, self.start_date)
        if self.end_date:
            qh.add_date(wd.PID_END_TIME, self.end_date)
        if self.subject_named_as:
            qh.add_str(wd.PID_SUBJECT_NAMED_AS, self.subject_named_as)
        if self.volume:
            qh.add_str(wd.PID_VOLUME, self.volume)
        if self.pages:
            qh.add_str(wd.PID_PAGES, self.pages)
        if self.url:
            qh.add_str(wd.PID_URL, self.url)
        return qh

    def update_statement(self, claim: pwb.Claim) -> bool:

        claim_changed = False

        orig_q = QualifierHandler()
        orig_q.from_claim(claim)

        new_q = QualifierHandler()
        new_q.from_claim(claim)
        external_q = self.create_qualifiers()
        res = new_q.merge(external_q)
        print(res)

        if not new_q.is_equal(orig_q, strict=True):
            claim.qualifiers = new_q.recreate_qualifiers(claim)
            claim_changed = True

        if claim_changed:
            self.wd_page.claim_changed(claim)

        return claim_changed

        # qualifiers = [
        #     (wd.PID_START_TIME, self.start_date),
        #     (wd.PID_END_TIME, self.end_date),
        #     (wd.PID_SUBJECT_NAMED_AS, self.subject_named_as),
        #     (wd.PID_VOLUME, self.volume),
        #     (wd.PID_PAGES, self.pages),
        #     (wd.PID_URL, self.url),
        # ]

        # for qualifier, value in qualifiers:
        #     if value:
        #         if not self.has_equal_qualifier(value, claim, qualifier):
        #             qual_claim = pwb.Claim(REPO, qualifier, is_qualifier=True)
        #             if isinstance(value, Date):
        #                 target = value.create_wikidata_item()
        #             else:
        #                 target = value
        #             qual_claim.setTarget(target)
        #             claim.qualifiers.setdefault(qualifier, []).append(qual_claim)
        # self.wd_page.claim_changed(claim)

    def add_statement(self) -> pwb.Claim:
        pid = self.get_prop()
        claim = pwb.Claim(REPO, pid)
        claim.setTarget(pwb.ItemPage(REPO, self.qid))

        external_q = self.create_qualifiers()
        claim.qualifiers = external_q.recreate_qualifiers(claim)

        self.wd_page.add_claim(pid, claim)
        return claim


# ParseHandler = Callable[[Iterable[pwb.Claim]], Any]
# CreateHandler = Callable[[Any], List[pwb.Claim]]
# T = TypeVar("T", bound="Qualifiers")


# class Qualifiers:
#     ALLOWED_PROPS: Set[str] = set()
#     PARSE_HANDLERS: Dict[str, ParseHandler] = {}
#     CREATE_HANDLERS: Dict[str, CreateHandler] = {}
#     PRIORITY_ORDER: List[str] = []

#     def __init__(self):
#         pass

#     @classmethod
#     def from_claim(cls: Type[T], claim: pwb.Claim) -> T:
#         quals = claim.qualifiers
#         extra = set(quals) - cls.ALLOWED_PROPS
#         if extra:
#             raise RuntimeError(f"Unsupported qualifier props: {extra}")

#         inst = cls.__new__(cls)
#         cls.__init__(inst)

#         for prop in cls.ALLOWED_PROPS:
#             handler = cls.PARSE_HANDLERS.get(prop)
#             if handler:
#                 value = handler(quals.get(prop, []))
#                 setattr(inst, prop, value)
#             else:
#                 qlist = quals.get(prop, [])
#                 if not qlist:
#                     setattr(inst, prop, None)
#                 elif len(qlist) == 1:
#                     setattr(inst, prop, qlist[0].getTarget())
#                 else:
#                     raise RuntimeError(f"Multiple {prop} qualifiers")

#         return inst

#     def merge(self, other: "Qualifiers"):
#         if type(self) is not type(other):
#             raise TypeError("Can only merge same qualifier types")
#         for prop in self.ALLOWED_PROPS:
#             a = getattr(self, prop, None)
#             b = getattr(other, prop, None)
#             if b is None:
#                 continue
#             if a is None:
#                 setattr(self, prop, b)
#             else:
#                 if a != b:
#                     raise RuntimeError(
#                         f"Can not merge because of difference for {prop}"
#                     )

#     def recreate_qualifiers(
#         self, claim: pwb.Claim
#     ) -> "OrderedDict[str, List[pwb.Claim]]":
#         created: Dict[str, List[pwb.Claim]] = {}
#         for prop, creator in self.CREATE_HANDLERS.items():
#             value = getattr(self, prop, None)
#             if value is None:
#                 continue
#             qual_claims = creator(value)
#             if qual_claims:
#                 created[prop] = qual_claims

#         filtered: Dict[str, List[pwb.Claim]] = {}
#         for pid, qualifiers in claim.qualifiers.items():
#             if pid in self.ALLOWED_PROPS:
#                 # do not copy managed props; they will be rebuilt from `created`
#                 continue
#             filtered[pid] = list(qualifiers)

#         custom_pid_order: List[str] = []
#         seen = set()
#         for pid in claim.qualifiers:
#             if pid not in seen:
#                 custom_pid_order.append(pid)
#                 seen.add(pid)
#         for pid in self.PRIORITY_ORDER:
#             if pid in created and pid not in seen:
#                 custom_pid_order.append(pid)
#                 seen.add(pid)
#         for pid in created:
#             if pid not in seen:
#                 custom_pid_order.append(pid)
#                 seen.add(pid)

#         ordered = OrderedDict()
#         for pid in custom_pid_order:
#             if pid in filtered:
#                 ordered[pid] = filtered[pid]
#             elif pid in created:
#                 ordered[pid] = created[pid]

#         for pid in list(filtered.keys()):
#             if pid not in ordered:
#                 ordered[pid] = filtered[pid]
#         for pid in list(created.keys()):
#             if pid not in ordered:
#                 ordered[pid] = created[pid]

#         return ordered

#     @classmethod
#     def is_equal(cls: Type[T], a: T, b: T, strict: bool) -> bool:
#         if strict:
#             return a.__dict__ == b.__dict__
#         for prop in cls.ALLOWED_PROPS:
#             va = getattr(a, prop, None)
#             vb = getattr(b, prop, None)
#             if va is None and vb is None:
#                 continue
#             if va != vb:
#                 return False
#         return True

#     def __repr__(self):
#         props = ", ".join(f"{k}={v!r}" for k, v in self.__dict__.items())
#         return f"<{self.__class__.__name__} {props}>"


# assumes Qualifiers base class, wd, REPO, Date, CALENDAR_ASSUMED_GREGORIAN are available


# class DateQualifiers(Qualifiers):
#     ALLOWED_PROPS = {
#         wd.PID_NATURE_OF_STATEMENT,
#         wd.PID_SOURCING_CIRCUMSTANCES,
#         wd.PID_EARLIEST_DATE,
#         wd.PID_LATEST_DATE,
#         wd.PID_INSTANCE_OF,
#         wd.PID_STATEMENT_DISPUTED_BY,
#         wd.PID_REASON_FOR_PREFERRED_RANK,
#         wd.PID_REASON_FOR_DEPRECATED_RANK,
#     }

#     PRIORITY_ORDER = [
#         wd.PID_SOURCING_CIRCUMSTANCES,
#         wd.PID_EARLIEST_DATE,
#         wd.PID_LATEST_DATE,
#     ]

#     def __init__(
#         self,
#         is_circa: bool = False,
#         gregorian_pre_1584: bool = False,
#         assumed_gregorian: bool = False,
#         earliest: Optional[Date] = None,
#         latest: Optional[Date] = None,
#     ):
#         self.is_circa = is_circa
#         self.gregorian_pre_1584 = gregorian_pre_1584
#         self.assumed_gregorian = assumed_gregorian
#         self.earliest = earliest
#         self.latest = latest

#     # ----- parsing helpers -----
#     @staticmethod
#     def _parse_date_single(qlist: Iterable[pwb.Claim]) -> Optional[Date]:
#         q = list(qlist)
#         if not q:
#             return None
#         if len(q) > 1:
#             raise RuntimeError("Multiple date qualifiers")
#         t = q[0].getTarget()
#         if not isinstance(t, pwb.WbTime):
#             raise RuntimeError("Date qualifier not a WbTime")
#         return Date.create_from_WbTime(t)

#     # PARSE_HANDLERS not used for flags because flags can appear on multiple props;
#     # we override from_claim to collect them from nature, sourcing, instance_of

#     PARSE_HANDLERS = {
#         wd.PID_EARLIEST_DATE: _parse_date_single.__func__,
#         wd.PID_LATEST_DATE: _parse_date_single.__func__,
#     }

#     # ----- creation helper (instance-aware) -----
#     def _create_map(self) -> Dict[str, List[pwb.Claim]]:
#         created: Dict[str, List[pwb.Claim]] = {}

#         def add_qid(pid, qid, condition):
#             if condition:
#                 qual = pwb.Claim(REPO, pid, is_qualifier=True)
#                 qual.setTarget(pwb.ItemPage(REPO, qid))
#                 created.setdefault(pid, []).append(qual)

#         def add_date(pid, value: Optional[Date]):
#             if value:
#                 qual = pwb.Claim(REPO, pid, is_qualifier=True)
#                 qual.setTarget(value.create_wikidata_item())
#                 created.setdefault(pid, []).append(qual)

#         add_qid(wd.PID_SOURCING_CIRCUMSTANCES, wd.QID_CIRCA, self.is_circa)
#         add_qid(
#             wd.PID_SOURCING_CIRCUMSTANCES,
#             wd.QID_STATEMENT_WITH_GREGORIAN_DATE_EARLIER_THAN_1584,
#             self.gregorian_pre_1584,
#         )
#         add_qid(
#             wd.PID_SOURCING_CIRCUMSTANCES,
#             wd.QID_UNSPECIFIED_CALENDAR_ASSUMED_GREGORIAN,
#             self.assumed_gregorian,
#         )
#         add_date(wd.PID_EARLIEST_DATE, self.earliest)
#         add_date(wd.PID_LATEST_DATE, self.latest)

#         return created

#     # CREATE_HANDLERS left empty because creation spans multiple props and depends on instance
#     CREATE_HANDLERS = {}

#     # ----- override from_claim to aggregate flags from multiple props -----
#     @classmethod
#     def from_claim(cls, claim: pwb.Claim) -> "DateQualifiers":
#         quals = claim.qualifiers
#         extra = set(quals) - cls.ALLOWED_PROPS
#         if extra:
#             raise RuntimeError(f"Unsupported qualifier props: {extra}")

#         seen_circa = False
#         seen_gregorian_pre_1584 = False
#         seen_assumed_gregorian = False

#         for qualifier_pid in (
#             wd.PID_NATURE_OF_STATEMENT,
#             wd.PID_SOURCING_CIRCUMSTANCES,
#             wd.PID_INSTANCE_OF,
#         ):
#             for qualifier in quals.get(qualifier_pid, []):
#                 qid = qualifier.getTarget().getID()
#                 if qid == wd.QID_CIRCA:
#                     seen_circa = True
#                 elif qid == wd.QID_STATEMENT_WITH_GREGORIAN_DATE_EARLIER_THAN_1584:
#                     seen_gregorian_pre_1584 = True
#                 elif qid == wd.QID_UNSPECIFIED_CALENDAR_ASSUMED_GREGORIAN:
#                     seen_assumed_gregorian = True
#                 else:
#                     raise RuntimeError(f"Unknown value {qid} for {qualifier_pid}")

#         earliest = cls._parse_date_single(quals.get(wd.PID_EARLIEST_DATE, []))
#         latest = cls._parse_date_single(quals.get(wd.PID_LATEST_DATE, []))

#         return cls(
#             is_circa=seen_circa,
#             gregorian_pre_1584=seen_gregorian_pre_1584,
#             assumed_gregorian=seen_assumed_gregorian,
#             earliest=earliest,
#             latest=latest,
#         )

#     # ----- recreate_qualifiers reuses base ordering approach but needs instance-aware creators -----
#     def recreate_qualifiers(
#         self, claim: pwb.Claim
#     ) -> "OrderedDict[str, List[pwb.Claim]]":
#         created = self._create_map()

#         # Start with a shallow copy of existing qualifiers: keep all props but for the managed ones
#         # only keep individual qualifiers that should remain (e.g., other qids we don't recognize)
#         filtered: Dict[str, List[pwb.Claim]] = {}
#         for pid, qualifiers in claim.qualifiers.items():
#             if pid in {
#                 wd.PID_NATURE_OF_STATEMENT,
#                 wd.PID_SOURCING_CIRCUMSTANCES,
#                 wd.PID_INSTANCE_OF,
#             }:
#                 filtered[pid] = []
#                 for q in qualifiers:
#                     qid = q.getTarget().getID()
#                     # keep recognized qids only if the instance says so
#                     if qid == wd.QID_STATEMENT_WITH_GREGORIAN_DATE_EARLIER_THAN_1584:
#                         if self.gregorian_pre_1584:
#                             filtered[pid].append(q)
#                     elif qid == wd.QID_CIRCA:
#                         if self.is_circa:
#                             filtered[pid].append(q)
#                     elif qid == wd.QID_UNSPECIFIED_CALENDAR_ASSUMED_GREGORIAN:
#                         if self.assumed_gregorian:
#                             filtered[pid].append(q)
#                     else:
#                         filtered[pid].append(q)
#             else:
#                 filtered[pid] = list(qualifiers)

#         # Build custom order: preserve original claim order, then PRIORITY_ORDER, then remaining created props
#         custom_pid_order: List[str] = []
#         seen = set()
#         for pid in claim.qualifiers:
#             if pid not in seen:
#                 custom_pid_order.append(pid)
#                 seen.add(pid)
#         for pid in self.PRIORITY_ORDER:
#             if pid in created and pid not in seen:
#                 custom_pid_order.append(pid)
#                 seen.add(pid)
#         for pid in created:
#             if pid not in seen:
#                 custom_pid_order.append(pid)
#                 seen.add(pid)

#         ordered = OrderedDict()
#         for pid in custom_pid_order:
#             if pid in filtered:
#                 ordered[pid] = filtered[pid]
#             elif pid in created:
#                 ordered[pid] = created[pid]

#         # append any remaining
#         for pid in list(filtered.keys()):
#             if pid not in ordered:
#                 ordered[pid] = filtered[pid]
#         for pid in list(created.keys()):
#             if pid not in ordered:
#                 ordered[pid] = created[pid]

#         return ordered

#     # ----- merging and equality -----
#     def merge(self, other: "DateQualifiers"):
#         if not isinstance(other, DateQualifiers):
#             raise TypeError("Can only merge DateQualifiers with DateQualifiers")
#         self.is_circa = self.is_circa or other.is_circa
#         self.gregorian_pre_1584 = self.gregorian_pre_1584 or other.gregorian_pre_1584
#         self.assumed_gregorian = self.assumed_gregorian or other.assumed_gregorian

#         if other.earliest:
#             if self.earliest:
#                 if other.earliest != self.earliest:
#                     raise RuntimeError("Can not merge because of diff earliest")
#             else:
#                 self.earliest = other.earliest
#         if other.latest:
#             if self.latest:
#                 if other.latest != self.latest:
#                     raise RuntimeError("Can not merge because of diff latest")
#             else:
#                 self.latest = other.latest

#     def __eq__(self, other):
#         if not isinstance(other, DateQualifiers):
#             return NotImplemented
#         return (
#             self.is_circa == other.is_circa
#             and self.earliest == other.earliest
#             and self.latest == other.latest
#             and self.assumed_gregorian == other.assumed_gregorian
#             and self.gregorian_pre_1584 == other.gregorian_pre_1584
#         )

#     @classmethod
#     def from_statement(cls, stmt: "DateStatement") -> "DateQualifiers":
#         assumed_gregorian = (
#             getattr(stmt.date, "calendar", None) == CALENDAR_ASSUMED_GREGORIAN
#         )
#         return cls(
#             is_circa=stmt.is_circa,
#             gregorian_pre_1584=False,
#             assumed_gregorian=assumed_gregorian,
#             earliest=stmt.earliest,
#             latest=stmt.latest,
#         )

#     @classmethod
#     def is_equal(cls, item1: "DateQualifiers", item2: "DateQualifiers", strict: bool):
#         if strict:
#             return item1 == item2
#         else:
#             return (
#                 (item1.is_circa == item2.is_circa)
#                 and (
#                     (not item1.earliest and not item2.earliest)
#                     or (item1.earliest == item2.earliest)
#                 )
#                 and (
#                     (not item1.latest and not item2.latest)
#                     or (item1.latest == item2.latest)
#                 )
#             )


# class DateQualifiers:
#     ALLOWED_PROPS = {
#         wd.PID_NATURE_OF_STATEMENT,
#         wd.PID_SOURCING_CIRCUMSTANCES,
#         wd.PID_EARLIEST_DATE,
#         wd.PID_LATEST_DATE,
#         wd.PID_INSTANCE_OF,
#     }

#     def __init__(
#         self,
#         is_circa: bool,
#         gregorian_pre_1584: bool,
#         assumed_gregorian: bool = False,
#         earliest: Optional[Date] = None,
#         latest: Optional[Date] = None,
#     ):
#         self.is_circa = is_circa
#         self.gregorian_pre_1584 = gregorian_pre_1584
#         self.assumed_gregorian = assumed_gregorian
#         self.earliest = earliest
#         self.latest = latest

#     def merge(self, other: "DateQualifiers"):
#         self.is_circa = self.is_circa or other.is_circa
#         self.gregorian_pre_1584 = self.gregorian_pre_1584 or other.gregorian_pre_1584
#         self.assumed_gregorian = self.assumed_gregorian or other.assumed_gregorian
#         if other.earliest:
#             if self.earliest:
#                 if other.earliest != self.earliest:
#                     raise RuntimeError("Can not merge because of diff earliest")
#             else:
#                 self.earliest = other.earliest
#         if other.latest:
#             if self.latest:
#                 if other.latest != self.latest:
#                     raise RuntimeError("Can not merge because of diff latest")
#             else:
#                 self.latest = other.latest

#     def recreate_qualifiers(self, claim: pwb.Claim):
#         QUALIFIER_PRIORITY = {
#             wd.PID_SOURCING_CIRCUMSTANCES: 0,
#             wd.PID_EARLIEST_DATE: 1,
#             wd.PID_LATEST_DATE: 2,
#         }

#         # Start with a shallow copy of existing qualifiers, but only keep allowed ones
#         filtered = {}
#         for pid, qualifiers in claim.qualifiers.items():
#             if pid in {
#                 wd.PID_NATURE_OF_STATEMENT,
#                 wd.PID_SOURCING_CIRCUMSTANCES,
#                 wd.PID_INSTANCE_OF,
#             }:
#                 filtered[pid] = []
#                 for q in qualifiers:
#                     qid = q.getTarget().getID()
#                     if qid == wd.QID_STATEMENT_WITH_GREGORIAN_DATE_EARLIER_THAN_1584:
#                         if self.gregorian_pre_1584:
#                             filtered[pid].append(q)
#                     elif qid == wd.QID_CIRCA:
#                         if self.is_circa:
#                             filtered[pid].append(q)
#                     elif qid == wd.QID_UNSPECIFIED_CALENDAR_ASSUMED_GREGORIAN:
#                         if self.assumed_gregorian:
#                             filtered[pid].append(q)
#                     else:
#                         filtered[pid].append(q)
#             else:
#                 filtered[pid] = qualifiers

#         # Add missing qualifiers if needed
#         def add_qid_qual(pid, qid, condition):
#             if condition:
#                 already = any(
#                     q.getTarget().getID() == qid for q in filtered.get(pid, [])
#                 )
#                 if not already:
#                     qual = pwb.Claim(REPO, pid, is_qualifier=True)
#                     qual.setTarget(pwb.ItemPage(REPO, qid))
#                     filtered.setdefault(pid, []).append(qual)

#         def add_date_qual(pid, value: Optional[Date]):
#             if value:
#                 already = pid in filtered
#                 if not already:
#                     qual = pwb.Claim(REPO, pid, is_qualifier=True)
#                     qual.setTarget(value.create_wikidata_item())
#                     filtered.setdefault(pid, []).append(qual)

#         add_qid_qual(wd.PID_SOURCING_CIRCUMSTANCES, wd.QID_CIRCA, self.is_circa)
#         add_qid_qual(
#             wd.PID_SOURCING_CIRCUMSTANCES,
#             wd.QID_STATEMENT_WITH_GREGORIAN_DATE_EARLIER_THAN_1584,
#             self.gregorian_pre_1584,
#         )
#         add_qid_qual(
#             wd.PID_SOURCING_CIRCUMSTANCES,
#             wd.QID_UNSPECIFIED_CALENDAR_ASSUMED_GREGORIAN,
#             self.assumed_gregorian,
#         )
#         add_date_qual(wd.PID_EARLIEST_DATE, self.earliest)
#         add_date_qual(wd.PID_LATEST_DATE, self.latest)

#         # Sort qualifiers by custom order
#         custom_pid_order = []
#         seen = set()
#         for pid in claim.qualifiers:
#             if pid not in seen:
#                 custom_pid_order.append(pid)
#                 seen.add(pid)
#         for pid in sorted(QUALIFIER_PRIORITY, key=lambda p: QUALIFIER_PRIORITY[p]):
#             if pid in filtered and pid not in seen:
#                 custom_pid_order.append(pid)
#                 seen.add(pid)
#         if (
#             wd.PID_EARLIEST_DATE in custom_pid_order
#             and wd.PID_LATEST_DATE in custom_pid_order
#         ):
#             i1, i2 = custom_pid_order.index(
#                 wd.PID_EARLIEST_DATE
#             ), custom_pid_order.index(wd.PID_LATEST_DATE)
#             if i1 > i2:
#                 item = custom_pid_order.pop(i1)
#                 custom_pid_order.insert(i2, item)

#         ordered_dict = OrderedDict(
#             (key, filtered[key]) for key in custom_pid_order if key in filtered
#         )
#         return ordered_dict

#     @classmethod
#     def from_claim(cls, claim) -> "DateQualifiers":
#         quals = claim.qualifiers

#         # 1. reject any unknown property
#         extra = set(quals) - cls.ALLOWED_PROPS
#         if extra:
#             raise RuntimeError(f"Unsupported qualifier props: {extra}")

#         # 2. parse is_circa, gregorian_date_earlier_than_1584
#         seen_circa = False
#         seen_gregorian_pre_1584 = False
#         seen_assumed_gregorian = False
#         for qualifier_pid in (
#             wd.PID_NATURE_OF_STATEMENT,
#             wd.PID_SOURCING_CIRCUMSTANCES,
#             wd.PID_INSTANCE_OF,
#         ):
#             for qualifier in quals.get(qualifier_pid, []):
#                 qid = qualifier.getTarget().getID()
#                 if qid == wd.QID_CIRCA:
#                     seen_circa = True
#                 elif qid == wd.QID_STATEMENT_WITH_GREGORIAN_DATE_EARLIER_THAN_1584:
#                     seen_gregorian_pre_1584 = True
#                 elif qid == wd.QID_UNSPECIFIED_CALENDAR_ASSUMED_GREGORIAN:
#                     seen_assumed_gregorian = True
#                 else:
#                     raise RuntimeError(f"Unknown value {qid} for {qualifier_pid}")

#         # 3. parse earliest/latest dates
#         def parse_date(prop):
#             qlist = quals.get(prop, [])
#             if len(qlist) > 1:
#                 raise RuntimeError(f"Multiple {prop} qualifiers")
#             if not qlist:
#                 return None
#             return Date.create_from_WbTime(qlist[0].getTarget())

#         earliest = parse_date(wd.PID_EARLIEST_DATE)
#         latest = parse_date(wd.PID_LATEST_DATE)

#         return cls(
#             is_circa=seen_circa,
#             gregorian_pre_1584=seen_gregorian_pre_1584,
#             assumed_gregorian=seen_assumed_gregorian,
#             earliest=earliest,
#             latest=latest,
#         )

#     @classmethod
#     def from_statement(cls, stmt: "DateStatement") -> "DateQualifiers":
#         assumed_gregorian = (
#             getattr(stmt.date, "calendar", None) == CALENDAR_ASSUMED_GREGORIAN
#         )
#         return cls(
#             is_circa=stmt.is_circa,
#             gregorian_pre_1584=False,
#             assumed_gregorian=assumed_gregorian,
#             earliest=stmt.earliest,
#             latest=stmt.latest,
#         )

#     def __eq__(self, other):
#         if not isinstance(other, DateQualifiers):
#             return NotImplemented
#         return (
#             self.is_circa == other.is_circa
#             and self.earliest == other.earliest
#             and self.latest == other.latest
#             and self.assumed_gregorian == other.assumed_gregorian
#             and self.gregorian_pre_1584 == other.gregorian_pre_1584
#         )

#     def __repr__(self):
#         return (
#             f"<DateQualifiers circa={self.is_circa!r}, "
#             f"earliest={self.earliest!r}, latest={self.latest!r}>"
#         )

#     @classmethod
#     def is_equal(cls, item1: "DateQualifiers", item2: "DateQualifiers", strict: bool):
#         if strict:
#             return item1 == item2
#         else:
#             # ignore gregorian_date_earlier_than_1584
#             return (
#                 (item1.is_circa == item2.is_circa)
#                 and (
#                     (not item1.earliest and not item2.earliest)
#                     or (item1.earliest == item2.earliest)
#                 )
#                 and (
#                     (not item1.latest and not item2.latest)
#                     or (item1.latest == item2.latest)
#                 )
#             )


class DateStatement(Statement):
    def __init__(
        self,
        date: Optional[Date] = None,
        earliest: Optional[Date] = None,
        latest: Optional[Date] = None,
        is_circa: bool = False,
        config: Optional[StatementConfig] = None,
    ):
        super().__init__(config)
        self.date = date
        self.earliest = earliest
        self.latest = latest
        self.is_circa = is_circa

    def __repr__(self):
        if self.earliest or self.latest:
            return f"{self.__class__.__name__}(date={self.date}, earliest={self.earliest}, latest={self.latest}, is_circa={self.is_circa}')"
        else:
            return f"{self.__class__.__name__}(date={self.date}, is_circa={self.is_circa}')"

    def can_attach_to_claim(self, claim, strict: bool) -> bool:
        dt = claim.getTarget()
        ignore_calendar_model = not strict and self.config.ignore_calendar_model
        if not Date.is_equal(
            self.date, dt, ignore_calendar_model=ignore_calendar_model
        ):
            return False

        has_circa = is_circa(claim)
        if self.is_circa != has_circa:
            return False

        if self.config.require_unreferenced:
            refs = claim.getSources()
            if refs:
                return False

        # build & validate both qualifier‐sets
        claim_qs = QualifierHandler()
        claim_qs.from_claim(claim)
        target_qs = self.create_qualifiers()

        return claim_qs.is_equal(target_qs, strict)

    def create_qualifiers(self) -> QualifierHandler:
        qh = QualifierHandler()
        if self.is_circa:
            qh.add_qid(wd.QID_CIRCA, wd.PID_SOURCING_CIRCUMSTANCES)
        assumed_gregorian = (
            getattr(self.date, "calendar", None) == CALENDAR_ASSUMED_GREGORIAN
        )
        if assumed_gregorian:
            qh.add_qid(
                wd.QID_UNSPECIFIED_CALENDAR_ASSUMED_GREGORIAN,
                wd.PID_SOURCING_CIRCUMSTANCES,
            )
        if self.earliest:
            qh.add_date(wd.PID_EARLIEST_DATE, self.earliest)
        if self.latest:
            qh.add_date(wd.PID_LATEST_DATE, self.latest)
        return qh

    def update_statement(self, claim: pwb.Claim) -> bool:
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

        orig_q = QualifierHandler()
        orig_q.from_claim(claim)

        new_q = QualifierHandler()
        new_q.from_claim(claim)
        external_q = self.create_qualifiers()
        res = new_q.merge(external_q)
        print(res)

        if self.date:
            if self.date.calendar == CALENDAR_JULIAN:
                new_q.remove_qid(wd.QID_STATEMENT_WITH_GREGORIAN_DATE_EARLIER_THAN_1584)
                new_q.remove_qid(wd.QID_UNSPECIFIED_CALENDAR_ASSUMED_GREGORIAN)

        if not new_q.is_equal(orig_q, strict=True):
            claim.qualifiers = new_q.recreate_qualifiers(claim)
            claim_changed = True

        if claim_changed:
            self.wd_page.claim_changed(claim)

        return claim_changed

    def add_statement(self) -> Optional[pwb.Claim]:
        pid = self.get_prop()
        claim = pwb.Claim(REPO, pid)
        if self.date:
            claim.setTarget(self.date.create_wikidata_item())
        else:
            claim.setSnakType("somevalue")

        external_q = self.create_qualifiers()
        claim.qualifiers = external_q.recreate_qualifiers(claim)
        self.wd_page.add_claim(pid, claim)
        return claim


# class ExternalIDQualifiers(Qualifiers):
#     ALLOWED_PROPS = {wd.PID_SUBJECT_NAMED_AS}
#     PRIORITY_ORDER = [wd.PID_SUBJECT_NAMED_AS]

#     def __init__(self, subject_named_as: Optional[str] = None):
#         self.subject_named_as = subject_named_as

#     # parse handler: return plain string or None
#     @staticmethod
#     def _parse_subject_named_as(qlist: Iterable[pwb.Claim]) -> Optional[str]:
#         q = list(qlist)
#         if not q:
#             return None
#         if len(q) > 1:
#             raise RuntimeError(f"Multiple {wd.PID_SUBJECT_NAMED_AS} qualifiers")
#         return q[0].getTarget()

#     # create handler: given a plain string produce a pwb.Claim list with plain string target
#     @staticmethod
#     def _create_subject_named_as(value: str) -> List[pwb.Claim]:
#         qual = pwb.Claim(REPO, wd.PID_SUBJECT_NAMED_AS, is_qualifier=True)
#         qual.setTarget(value)
#         return [qual]

#     PARSE_HANDLERS = {wd.PID_SUBJECT_NAMED_AS: _parse_subject_named_as.__func__}
#     CREATE_HANDLERS = {wd.PID_SUBJECT_NAMED_AS: _create_subject_named_as.__func__}

#     @classmethod
#     def from_statement(cls, stmt: "ExternalIDStatement") -> "ExternalIDQualifiers":
#         return cls(subject_named_as=stmt.subject_named_as)

#     def merge(self, other: "ExternalIDQualifiers"):
#         if not isinstance(other, ExternalIDQualifiers):
#             raise TypeError(
#                 "Can only merge ExternalIDQualifiers with ExternalIDQualifiers"
#             )
#         if other.subject_named_as:
#             if self.subject_named_as:
#                 if other.subject_named_as != self.subject_named_as:
#                     raise RuntimeError("Can not merge because of diff subject_named_as")
#             else:
#                 self.subject_named_as = other.subject_named_as

#     def __eq__(self, other):
#         if not isinstance(other, ExternalIDQualifiers):
#             return NotImplemented
#         return self.subject_named_as == other.subject_named_as

#     @classmethod
#     def is_equal(
#         cls, a: "ExternalIDQualifiers", b: "ExternalIDQualifiers", strict: bool
#     ) -> bool:
#         if strict:
#             return a == b
#         return a.subject_named_as == b.subject_named_as


class ExternalIDStatement(Statement):
    def __init__(
        self,
        url: Optional[str] = None,
        prop: Optional[str] = None,
        external_id: Optional[str] = None,
        subject_named_as: Optional[str] = None,
    ):
        super().__init__()
        self.url = url
        self.prop = prop
        self.external_id = external_id
        self.subject_named_as = subject_named_as

    def __repr__(self):
        if self.url:
            return f"ExternalIDStatement(url={self.url})"
        else:
            return (
                f"ExternalIDStatement(prop={self.prop}, external_id={self.external_id})"
            )

    def can_attach_to_claim(self, claim, strict: bool) -> bool:
        if claim.getTarget() != self.external_id:
            return False

        # build & validate both qualifier‐sets
        claim_qs = QualifierHandler()
        claim_qs.from_claim(claim)
        target_qs = self.create_qualifiers()

        return claim_qs.is_equal(target_qs, strict)

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

    def create_qualifiers(self) -> QualifierHandler:
        qh = QualifierHandler()
        if self.subject_named_as:
            qh.add_str(wd.PID_SUBJECT_NAMED_AS, self.subject_named_as)
        return qh

    def update_statement(self, claim: pwb.Claim) -> bool:

        orig_q = QualifierHandler()
        orig_q.from_claim(claim)

        new_q = QualifierHandler()
        new_q.from_claim(claim)

        external_q = self.create_qualifiers()
        res = new_q.merge(external_q)
        print(res)

        if not new_q.is_equal(orig_q, strict=True):
            claim.qualifiers = new_q.recreate_qualifiers(claim)
            claim_changed = True

        if claim_changed:
            self.wd_page.claim_changed(claim)

        return claim_changed

    def add_statement(self) -> pwb.Claim:
        claim = pwb.Claim(REPO, self.prop)
        claim.setTarget(self.external_id)

        external_q = self.create_qualifiers()
        claim.qualifiers = external_q.recreate_qualifiers(claim)
        self.wd_page.add_claim(self.prop, claim)
        return claim

    def get_description(self) -> str:
        res = f"External ID {self.prop}"
        if self.subject_named_as:
            res = res + f" subject_named_as {self.subject_named_as}"
        return res


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


class Description(WikidataEntity):
    def __init__(self, text: str, language: str):
        self.text = text
        self.language = language

    def __repr__(self):
        return f"Description(text='{self.text}', language='{self.language}')"

    def add(self):
        if not self.wd_page.has_language_description(self.language):
            self.print_action("description added", TextColor.OKGREEN)
            self.wd_page.save_description(self.language, self.text)
            return

        if self.wd_page.has_description(self.language, self.text):
            self.print_action("already added")
            return

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


class ShortName(MonolingualTextStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_SHORT_NAME

    def get_description(self) -> str:
        return "Short name"


class InstanceOf(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_INSTANCE_OF

    def get_description(self) -> str:
        return "Instance of"


class WritingSystem(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_WRITING_SYSTEM

    def get_description(self) -> str:
        return "Writing system"


class HasCharacteristic(ItemStatement):
    def get_prop(self) -> Optional[str]:
        return wd.PID_HAS_CHARACTERISTIC

    def get_description(self) -> str:
        return "Has characteristic"


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
    changed_claims: Dict[str, Set[ClaimChangeType]] = field(default_factory=dict)
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

    def remove_references(self, pid: str, reference: Reference):
        """
        Creates an action to delete a statement from the page.

        :param statement: The WikidataEntity to delete.
        """
        self._add_action(RemoveReferences(self, pid, reference))

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

    def deprecate_date(self, pid: str, date: Date):
        self._add_action(DeprecateDate(self, pid, date))

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

        references_added = 0
        references_changed = 0
        references_deleted = 0

        for prop in self.claims:
            for claim in self.claims[prop]:
                if claim.snak is None:
                    added_objects.append(claim)
                    pids_added.add(claim.id)
                    self.save_changed_claim(claim)
                elif claim.snak in self.changed_claims:
                    value = self.changed_claims[claim.snak]
                    if ClaimChangeType.CLAIM_DELETED in value:
                        deleted_objects.append(claim)
                        pids_deleted.add(claim.id)
                        self.save_deleted_claim(claim)
                    elif ClaimChangeType.CLAIM_CHANGED in value:
                        changed_objects.append(claim)
                        pids_changed.add(claim.id)
                        self.save_changed_claim(claim)
                    else:
                        if ClaimChangeType.REFERENCE_ADDED in value:
                            references_added += 1
                        if ClaimChangeType.REFERENCE_CHANGED in value:
                            references_changed += 1
                        if ClaimChangeType.REFERENCE_DELETED in value:
                            references_deleted += 1
                        self.save_changed_claim(claim)

        print(f"added statements: {len(added_objects)}")
        print(f"changed statements: {len(changed_objects)}")
        print(f"deleted statements: {len(deleted_objects)}")
        print(f"references added: {references_added}")
        print(f"references changed: {references_changed}")
        print(f"references deleted: {references_deleted}")

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
            generate_reference_description("added", references_added),
            generate_reference_description("updated", references_changed),
            generate_reference_description("removed", references_deleted),
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
            if (
                claim.snak
                and claim.snak in self.changed_claims
                and ClaimChangeType.CLAIM_DELETED in self.changed_claims[claim.snak]
            ):
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

    def has_language_description(self, language: str) -> bool:
        if language in self.item.descriptions:
            return True

        if "descriptions" in self.data:
            if language in self.data["descriptions"]:
                return True

        return False

    def has_description(self, language: str, text: str) -> bool:
        # already saved?
        if "descriptions" in self.data:
            if language in self.data["descriptions"]:
                return self.data["descriptions"][language] == text

        # already on the page?
        if language not in self.item.descriptions:
            return False
        return self.item.descriptions[language] == text

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
        return pid in self.claims

    def has_qid(self, pid: str) -> bool:
        qids = self.get_qids(pid)
        return len(qids) > 0

    def get_qids(self, pid: str):
        res = set()
        if pid in self.claims:
            for claim in self.claims[pid]:
                if claim.rank == "deprecated":
                    continue
                target = claim.getTarget()
                if target:
                    qid = target.getID()
                    res.add(qid)
        return res

    def claim_changed(self, claim: pwb.Claim):
        if claim.snak:
            self.changed_claims.setdefault(claim.snak, set()).add(
                ClaimChangeType.CLAIM_CHANGED
            )

    def claim_deleted(self, claim: pwb.Claim):
        if claim.snak:
            self.changed_claims.setdefault(claim.snak, set()).add(
                ClaimChangeType.CLAIM_DELETED
            )

    def add_claim(self, pid, claim: pwb.Claim):
        # self.claims can be {}
        # if self.claims:
        self.claims.setdefault(pid, []).append(claim)

    def reference_added(self, claim: pwb.Claim):
        if claim.snak:
            self.changed_claims.setdefault(claim.snak, set()).add(
                ClaimChangeType.REFERENCE_ADDED
            )

    def reference_changed(self, claim: pwb.Claim):
        if claim.snak:
            self.changed_claims.setdefault(claim.snak, set()).add(
                ClaimChangeType.REFERENCE_CHANGED
            )

    def reference_deleted(self, claim: pwb.Claim):
        if claim.snak:
            self.changed_claims.setdefault(claim.snak, set()).add(
                ClaimChangeType.REFERENCE_DELETED
            )

    def delete_reference(
        self,
        claim: pwb.Claim,
        reference: Reference,
        is_update: bool = False,
        can_delete_claim: bool = False,
    ):
        new_sources = []
        found = False
        for source in claim.sources:
            if reference.is_equal_reference(source):
                found = True
            else:
                new_sources.append(source)

        if found:
            if new_sources == [] and can_delete_claim:
                print("reference removed, claim deleted")
                self.claim_deleted(claim)
            else:
                claim.sources = new_sources
                if not is_update:
                    self.reference_deleted(claim)

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
        for pid, add_year_func in date_mappings.items():
            if pid in self.claims:
                for claim in self.claims[pid]:
                    if claim.rank == "deprecated":
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
        if pid == wd.PID_VIAF_CLUSTER_ID and False:
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
