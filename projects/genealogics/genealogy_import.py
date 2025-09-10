import re
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple, Type

import genealogics.genealogics_date as gd
import genealogics.genealogics_org_parser as gap
import genealogics.nameparser as np
import genealogics.prefix_suffix_utils as psu
import genealogics.rules as rules
import genealogics.wikitree_parser as wtp
import pywikibot as pwb

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
from shared_lib.calendar_system_resolver import DateCalendarService
from shared_lib.locale_resolver import LocaleResolver
from shared_lib.lookups.interfaces.place_lookup_interface import (
    CountryLookupInterface,
    PlaceLookupInterface,
)

# TODO:
#   * Update description
#   * Only genealogics.org -> always update name
#   * Add title to Nameparser
#   * Check if current name is problematic -> deprecate, else -> deprecate only English label
#   O Gaat iets fout met None dates met before/after
#   * gebruik code voor Julian/Gregorian
#   * Q100450663: description aanpassen
#   * wait before read gen, wikitree


class GenealogicsStatusTracker(ABC):
    @abstractmethod
    def is_done(self, qid: str) -> bool:
        """Return True if the item is already marked as done."""
        pass

    @abstractmethod
    def mark_done(self, qid: str, message: str):
        """Mark the item as done."""
        pass

    @abstractmethod
    def mark_error(self, qid: str, error: str):
        """Mark the item as errored, with an error message."""
        pass

    @abstractmethod
    def is_error(self, qid: str) -> bool:
        """Return True if the item is marked as errored."""
        pass


def is_year_span(text: str) -> bool:
    pattern = r"^(?:\()?\d{3,4}\s?[–—-]\s?\d{3,4}(?:\))?$"
    return re.fullmatch(pattern, text) is not None


def is_only_spaces_and_dashes(s):
    return bool(s) and set(s).issubset({" ", "-"})


def same_name(name1: str, name2: str) -> bool:
    return name1 == name2


STATEMENT_CLASS_FOR_FIELD = {
    rules.Field.DATE_OF_BIRTH: cwd.DateOfBirth,
    rules.Field.DATE_OF_DEATH: cwd.DateOfDeath,
    rules.Field.DATE_OF_BAPTISM: cwd.DateOfBaptism,
    rules.Field.DATE_OF_BURIAL: cwd.DateOfBurialOrCremation,
    rules.Field.DATE_OF_PROBATE: cwd.DateOfProbate,
    rules.Field.PLACE_OF_BIRTH: cwd.PlaceOfBirth,
    rules.Field.PLACE_OF_DEATH: cwd.PlaceOfDeath,
    rules.Field.PLACE_OF_RESIDENCE: cwd.Residence,
}


class WikidataUpdater:

    def __init__(
        self,
        page: cwd.WikiDataPage,
        country_lookup: CountryLookupInterface,
        place_lookup: PlaceLookupInterface,
        tracker: GenealogicsStatusTracker,
    ):
        self.page = page
        self.country_lookup = country_lookup
        self.place_lookup = place_lookup
        self.tracker = tracker
        self.qid = self.page.item.id
        self.data_from = {}
        self.data_from[rules.Source.GENEALOGICS] = False
        self.data_from[rules.Source.WIKITREE] = False
        self.raw_data_sources = {}
        self.identifiers = {}
        self.deprecated_desc_date = None
        self.locale = LocaleResolver(place_lookup)
        self.date_service = None

    def parse_gender(self, field: rules.Field, value: str) -> cwd.Statement:
        if value == "Male":
            gender_qid = wd.QID_MALE
        if value == "Female":
            gender_qid = wd.QID_FEMALE
            raise RuntimeError("Need to check - Female")

        return cwd.SexOrGender(qid=gender_qid)

    def parse_prefix(self, field: rules.Field, value: str) -> Optional[cwd.Statement]:
        cls, qid = psu.analyze_prefix(value)
        if cls and qid:
            return cls(qid=qid)
        else:
            return None

    def parse_suffix(self, field: rules.Field, value: str) -> Optional[cwd.Statement]:
        cls, qid = psu.analyze_suffix(value)
        if cls and qid:
            return cls(qid=qid)
        else:
            return None

    def parse_external_id(
        self, field: rules.Field, value: str
    ) -> Optional[cwd.Statement]:
        if field == rules.Field.FIND_A_GRAVE_ID:
            return cwd.ExternalIDStatement(
                prop=wd.PID_FIND_A_GRAVE_MEMORIAL_ID, external_id=value
            )

        raise RuntimeError(f"parse_external_id: Unexpected field {field}")

    def parse_place(self, field: rules.Field, value) -> cwd.Statement:
        location_qid = self.place_lookup.get_place_qid_by_desc(value)
        if not location_qid:
            raise RuntimeError(f"Location not found: {value}")
        cls = STATEMENT_CLASS_FOR_FIELD[field]
        statement = cls(qid=location_qid)
        if field == rules.Field.PLACE_OF_BIRTH:
            self.locale.add_place_of_birth(location_qid)
        elif field == rules.Field.PLACE_OF_DEATH:
            self.locale.add_place_of_death(location_qid)
        else:
            self.locale.add_place(location_qid)
        return statement

    def parse_date(
        self, field: rules.Field, value: gd.GenealogicsDate
    ) -> cwd.Statement:
        cls = STATEMENT_CLASS_FOR_FIELD[field]
        earliest = latest = None
        is_circa = False
        if not self.date_service:
            self.date_service = DateCalendarService(
                country_qid=self.locale.resolve(), country_lookup=self.country_lookup
            )

        is_julian = False
        year = value.year
        if value.alt_year and value.year:
            if value.alt_year == value.year + 1:
                is_julian = True
                year = value.alt_year
        wb_time = self.date_service.get_wbtime(
            year=year, month=value.month, day=value.day, is_julian=is_julian
        )
        date = cwd.Date.create_from_WbTime(wb_time)
        if date.calendar == cwd.CALENDAR_ASSUMED_GREGORIAN:
            date.calendar = cwd.CALENDAR_GREGORIAN
        if value.modifier == "before":
            raise NotImplementedError("Before modifier not implemented yet")
            latest = date
            if date.precision == cwd.PRECISION_DAY:
                date = cwd.Date(year=value.year, calendar=date.calendar)
            else:
                date = None
        elif value.modifier == "after":
            raise NotImplementedError("After modifier not implemented yet")
            earliest = date
            if date.precision == cwd.PRECISION_DAY:
                date = cwd.Date(year=value.year, calendar=date.calendar)
            else:
                date = None
        elif value.modifier in ["about", "estimated"]:
            is_circa = True
        elif not value.modifier:
            pass
        else:
            raise ValueError(f"Unexpected date modifier {value.modifier}")
        return cls(
            date=date,
            earliest=earliest,
            latest=latest,
            is_circa=is_circa,
            remove_old_claims=True,
        )

    def get_wiki_tree_span(self, description: str) -> Optional[str]:
        date_pattern = (
            r"(?:certain|uncertain|est\.)? ?(?:\d{1,2})? ?(?:[A-Za-z]{3})? ?\d{4}"
        )
        pattern = rf"\(?{date_pattern} - {date_pattern}\)?"
        match = re.search(pattern, description)

        if match:
            date_range = match.group(0)
            if date_range == description:
                return date_range
            if date_range.startswith("(") and date_range.endswith(")"):
                return date_range
            if description.endswith(f", {date_range}"):
                return f", {date_range}"
        return None

    # def work_wikitree(self, wt_id: str, mode: str):
    #     data = wtp.fetch_wikitree_profiles(wt_id)
    #     pprint(data, sort_dicts=False)

    #     if mode == "full" or wd.PID_SEX_OR_GENDER not in self.page.claims:
    #         if gender := data.get(rules.Field.GENDER):
    #             if gender == "Male":
    #                 gender_qid = wd.QID_MALE
    #             elif gender == "Female":
    #                 gender_qid = wd.QID_FEMALE
    #                 raise RuntimeError("Need to check")
    #             else:
    #                 raise ValueError(f"Unexpected gender {gender}")
    #             if wd.PID_SEX_OR_GENDER not in self.page.claims:
    #                 self.page.add_statement(cwd.SexOrGender(qid=gender_qid), reference=None)
    #                 self.data_from[rules.Source.WIKITREE] = True

    #     if mode == "full" or wd.PID_PLACE_OF_BIRTH not in self.page.claims:
    #         if birth_location := data.get(rules.Field.PLACE_OF_BIRTH):
    #             location_qid = self.place_lookup.get_place_qid_by_desc(birth_location)
    #             if not location_qid:
    #                 raise RuntimeError(f"Location not found: {birth_location}")
    #             self.page.add_statement(
    #                 cwd.PlaceOfBirth(qid=location_qid),
    #                 reference=StateInWikiTree(wt_id),
    #             )
    #             self.locale.add_place_of_birth(location_qid)
    #             self.data_from[rules.Source.WIKITREE] = True

    #     if mode == "full" or wd.PID_PLACE_OF_DEATH not in self.page.claims:
    #         if death_location := data.get(rules.Field.PLACE_OF_DEATH):
    #             location_qid = self.place_lookup.get_place_qid_by_desc(death_location)
    #             if not location_qid:
    #                 raise RuntimeError(f"Location not found: {death_location}")
    #             self.page.add_statement(
    #                 cwd.PlaceOfDeath(qid=location_qid),
    #                 reference=StateInWikiTree(wt_id),
    #             )
    #             self.locale.add_place_of_death(location_qid)
    #             self.data_from[rules.Source.WIKITREE] = True

    #     if mode == "full" or wd.PID_DATE_OF_BIRTH not in self.page.claims:
    #         if birth_date := data.get(rules.Field.DATE_OF_BIRTH):
    #             self.page.add_statement(
    #                 self.create_date(cwd.DateOfBirth, birth_date),
    #                 reference=StateInWikiTree(wt_id),
    #             )
    #             self.data_from[rules.Source.WIKITREE] = True

    #     if mode == "full" or wd.PID_DATE_OF_DEATH not in self.page.claims:
    #         if death_date := data.get(rules.Field.DATE_OF_DEATH):
    #             self.page.add_statement(
    #                 self.create_date(cwd.DateOfDeath, death_date),
    #                 reference=StateInWikiTree(wt_id),
    #             )
    #             self.data_from[rules.Source.WIKITREE] = True

    #     if findagrave_id := data.get(rules.Field.findagrave_id):
    #         self.page.add_statement(
    #             cwd.ExternalIDStatement(
    #                 prop=wd.PID_FIND_A_GRAVE_MEMORIAL_ID, external_id=findagrave_id
    #             ),
    #             reference=StateInWikiTree(wt_id),
    #         )
    #         self.data_from[rules.Source.WIKITREE] = True

    #     # Update label and description
    #     if display_name := data.get(rules.Field.display_name):
    #         if "en" in self.page.item.labels:
    #             current_label = self.page.item.labels["en"]
    #         elif "mul" in self.page.item.labels:
    #             raise RuntimeError("Need to check")
    #             current_label = self.page.item.labels["mul"]
    #         else:
    #             raise RuntimeError("Need to check")
    #             current_label = None
    #         print(f"Current label: {current_label}")
    #         did_deprecate = False
    #         if mode in ["full", "wikitree"]:
    #             for name in data.get(rules.Field.deprecated_names, []):
    #                 if current_label == name:
    #                     print(
    #                         f"Deprecating label: {current_label} -> {display_name}"
    #                     )
    #                     self.page.deprecate_label(current_label, display_name)
    #                     self.data_from[rules.Source.WIKITREE] = True
    #                     did_deprecate = True
    #                     break
    #         if not did_deprecate:
    #             self.page.add_statement(cwd.Label(display_name, language="en"), reference=None)
    #     if "en" in self.page.item.descriptions:
    #         current_desc = self.page.item.descriptions["en"]
    #         print(f"Current desc: {current_desc}")
    #         wiki_tree_span = self.get_wiki_tree_span(current_desc)
    #         if wiki_tree_span:
    #             self.deprecated_desc_date = wiki_tree_span
    #         elif is_year_span(current_desc):
    #             self.deprecated_desc_date = current_desc

    #     if not self.deprecated_desc_date:
    #         if "en" in self.page.item.descriptions:
    #             current_desc = self.page.item.descriptions["en"]
    #             if current_desc and is_only_spaces_and_dashes(current_desc):
    #                 self.deprecated_desc_date = current_desc

    #     if prefix := data.get(rules.Field.PREFIX):
    #         norm_prefix = normalize_prefix(prefix)
    #         mapping = PREFIX_TO_CLASS_QID.get(norm_prefix)
    #         if mapping:
    #             cls, qid = mapping
    #             self.page.add_statement(
    #                 cls(qid=qid),
    #                 reference=None,
    #             )
    #             self.data_from[rules.Source.WIKITREE] = True
    #         elif norm_prefix in PREFIX_TO_CLASS_QID:
    #             # Known but intentionally not mapped
    #             pass
    #         else:
    #             raise NotImplementedError(f"Prefix not implemented yet: {prefix} (normalized: {norm_prefix})")

    # def work_genealogics(self, id: str, mode: str):
    #     data = gap.fetch_genealogics(id)
    #     pprint(data, sort_dicts=False)
    #     label_parts = data.get(rules.Field.label_parts)
    #     if not label_parts:
    #         raise RuntimeError("No label parts found")
    #     if len(label_parts) not in [1, 2]:
    #         raise RuntimeError("Unexpected label parts")
    #     names = np.NameParser(label_parts[0])
    #     print(names)
    #     if not names.cleaned_name:
    #         raise RuntimeError("No cleaned name found")
    #     if gender := data.get(rules.Field.GENDER):
    #         if gender == "Male":
    #             gender_qid = wd.QID_MALE
    #         elif gender == "Female":
    #             gender_qid = wd.QID_FEMALE
    #         else:
    #             raise ValueError(f"Unexpected gender {gender}")
    #         if wd.PID_SEX_OR_GENDER not in self.page.claims:
    #             self.page.add_statement(cwd.SexOrGender(qid=gender_qid), reference=None)
    #             self.data_from[rules.Source.GENEALOGICS] = True

    #     if birth := data.get(rules.Field.DATE_OF_BIRTH):
    #         if mode in ["full", "wikitree"]:

    #             if birth_date := birth.get("date"):
    #                 self.page.add_statement(
    #                     self.create_date(cwd.DateOfBirth, birth_date),
    #                     reference=StateInGenealogicsOrg(id),
    #                 )
    #                 self.data_from[rules.Source.GENEALOGICS] = True

    #             if birth_place := birth.get("place"):
    #                 location_qid = self.place_lookup.get_place_qid_by_desc(birth_place)
    #                 if not location_qid:
    #                     raise RuntimeError(f"Location not found: {birth_place}")
    #                 self.page.add_statement(
    #                     cwd.PlaceOfBirth(qid=location_qid),
    #                     reference=StateInGenealogicsOrg(id),
    #                 )
    #                 self.locale.add_place_of_birth(location_qid)
    #                 self.data_from[rules.Source.GENEALOGICS] = True
    #     if wd.PID_DATE_OF_BAPTISM not in self.page.claims:
    #         if christening := data.get(rules.Field.DATE_OF_BAPTISM):
    #             if christening_date := christening.get("date"):
    #                 self.page.add_statement(
    #                     self.create_date(cwd.DateOfBaptism, christening_date),
    #                     reference=StateInGenealogicsOrg(id),
    #                 )

    #                 self.data_from[rules.Source.GENEALOGICS] = True

    #     if death := data.get(rules.Field.DATE_OF_DEATH):
    #         if mode in ["full", "wikitree"]:

    #             if death_date := death.get("date"):
    #                 self.page.add_statement(
    #                     self.create_date(cwd.DateOfDeath, death_date),
    #                     reference=StateInGenealogicsOrg(id),
    #                 )
    #                 self.data_from[rules.Source.GENEALOGICS] = True

    #             if death_place := death.get("place"):
    #                 location_qid = self.place_lookup.get_place_qid_by_desc(death_place)
    #                 if not location_qid:
    #                     raise RuntimeError(f"Location not found: {death_place}")
    #                 self.page.add_statement(
    #                     cwd.PlaceOfDeath(qid=location_qid),
    #                     reference=StateInGenealogicsOrg(id),
    #                 )
    #                 self.data_from[rules.Source.GENEALOGICS] = True

    #     if wd.PID_DATE_OF_BURIAL_OR_CREMATION not in self.page.claims:
    #         if burial := data.get(rules.Field.DATE_OF_BURIAL):
    #             if burial_date := burial.get("date"):
    #                 self.page.add_statement(
    #                     self.create_date(cwd.DateOfBurialOrCremation, burial_date),
    #                     reference=StateInGenealogicsOrg(id),
    #                 )

    #                 self.data_from[rules.Source.GENEALOGICS] = True

    #     if mode in ["full", "wikitree"]:
    #         if names.location:
    #             location = names.location
    #             lived_in = data.get(rules.Field.LIVED_IN)
    #             if lived_in:
    #                 location = f"{location}; {lived_in}"
    #             location_qid = self.place_lookup.get_place_qid_by_desc(location)
    #             if not location_qid:
    #                 raise RuntimeError(f"Location not found: {location}")
    #             self.page.add_statement(cwd.Residence(qid=location_qid), reference=None)
    #             self.locale.add_place(location_qid)
    #             self.data_from[rules.Source.GENEALOGICS] = True

    #     if mode in ["full", "wikitree"]:
    #         if "en" in self.page.item.labels:
    #             current_label = self.page.item.labels["en"]
    #             if len(label_parts) == 2:
    #                 title = label_parts[1]
    #                 raw_text = f"{label_parts[0]}, {title}"
    #                 cleaned_name = f"{names.cleaned_name}, {title}"
    #             else:
    #                 raw_text = label_parts[0]
    #                 cleaned_name = names.cleaned_name
    #             if names.cleaned_name and (current_label == raw_text):
    #                 if raw_text != cleaned_name:
    #                     self.page.deprecate_label(current_label, cleaned_name)
    #                     self.data_from[rules.Source.GENEALOGICS] = True

    #             for name in names.variants:
    #                 self.page.add_statement(
    #                     cwd.Label(name, language="en"), reference=None
    #                 )
    #                 self.data_from[rules.Source.GENEALOGICS] = True

    def get_parser(self, field: rules.Field, source: rules.Source):
        if field in rules.DATE_FIELDS:
            return self.parse_date
        elif field == rules.Field.GENDER:
            return self.parse_gender
        elif field == rules.Field.PREFIX:
            return self.parse_prefix
        elif field == rules.Field.SUFFIX:
            return self.parse_suffix
        elif field == rules.Field.FIND_A_GRAVE_ID:
            return self.parse_external_id
        elif field in rules.PLACE_FIELDS:
            return self.parse_place
        return None

    def get_pid(self, field: rules.Field) -> str:
        DICT = {
            rules.Field.PREFIX: None,
            rules.Field.SUFFIX: None,
            rules.Field.DATE_OF_BIRTH: wd.PID_DATE_OF_BIRTH,
            rules.Field.DATE_OF_DEATH: wd.PID_DATE_OF_DEATH,
            rules.Field.DATE_OF_BAPTISM: wd.PID_DATE_OF_BAPTISM,
            rules.Field.DATE_OF_BURIAL: wd.PID_DATE_OF_BURIAL_OR_CREMATION,
            rules.Field.DATE_OF_PROBATE: wd.PID_DATE_OF_PROBATE,
            rules.Field.PLACE_OF_BIRTH: wd.PID_PLACE_OF_BIRTH,
            rules.Field.PLACE_OF_DEATH: wd.PID_PLACE_OF_DEATH,
            rules.Field.PLACE_OF_RESIDENCE: wd.PID_RESIDENCE,
            rules.Field.GENDER: wd.PID_SEX_OR_GENDER,
            rules.Field.FIND_A_GRAVE_ID: wd.PID_FIND_A_GRAVE_MEMORIAL_ID,
        }
        if field in DICT:
            return DICT[field]
        else:
            raise RuntimeError("Unexpeced field")

    def has_wikidata_field(self, field: rules.Field) -> bool:
        pid = self.get_pid(field)
        if not pid:
            return False
        has = pid in self.page.item.claims
        return has

    def create_reference(self, field, source):
        if field == rules.Field.GENDER:
            return None
        if field == rules.Field.PREFIX:
            return None
        if field == rules.Field.SUFFIX:
            return None
        if source == rules.Source.GENEALOGICS:
            return cwd.StateInReference(
                wd.QID_GENEALOGICS,
                wd.PID_GENEALOGICS_ORG_PERSON_ID,
                self.identifiers[source],
            )
        elif source == rules.Source.WIKITREE:
            return cwd.StateInReference(
                wd.QID_WIKITREE, wd.PID_WIKITREE_PERSON_ID, self.identifiers[source]
            )
        else:
            raise RuntimeError("Unexpected source {source}")

    def get_wikidata_date_precision(self, field):
        pid = self.get_pid(field)
        if not pid:
            return None
        min_prec = None
        for claim in self.page.item.claims[pid]:
            if claim.rank == "deprecated":
                continue
            t = claim.getTarget()
            if t:
                prec = t.precision
                if not min_prec or (prec < min_prec):
                    min_prec = prec
        return min_prec

    def parse_date_precision(self, raw_value):
        prec = raw_value.precision()
        if prec == "day":
            return 11
        elif prec == "month":
            return 10
        elif prec == "year":
            return 9
        elif prec == "decade":
            return 8
        else:
            return None

    def should_skip(self, field, source, raw_value):
        """
        Decide whether to skip adding a field when more_ids_case is active
        and Wikidata already has a value.

        Returns True if we should skip, False if we should proceed.
        """
        # If not in more_ids_case or Wikidata doesn't have the field, never skip here
        if not (self.more_ids_case and self.has_wikidata_field(field)):
            return False

        # Exception: DOB/DOD from Wikitree with higher precision than Wikidata
        if field in rules.DATE_FIELDS and source == rules.Source.WIKITREE:
            wd_precision = self.get_wikidata_date_precision(field)
            wt_precision = self.parse_date_precision(raw_value)
            if not wd_precision or not wt_precision:
                if wt_precision:
                    # do not skip
                    return False
                else:
                    # skip
                    return True
            # Wikidata precision: 9=year, 10=month, 11=day
            if wt_precision > wd_precision:
                return False  # allow adding
            # else fall through to skip

        # Default: skip
        return True

    def get_raw_value(self, source: rules.Source, field: rules.Field):
        return self.raw_data_sources.get(source, {}).get(field)

    def work_fields(self, fields: List[rules.Field], sources):
        for field in fields:
            for source in sources:
                raw_value = self.get_raw_value(source, field)
                if not raw_value:
                    continue

                # Gap-only rule for more identifiers case
                if self.should_skip(field, source, raw_value):
                    continue

                # Special rule for places
                if field in rules.PLACE_FIELDS:
                    # Skip if Wikidata already has a place
                    if self.has_wikidata_field(field):
                        continue
                    # Skip Genealogics if Wikitree has a place
                    if source == rules.Source.GENEALOGICS and self.get_raw_value(
                        rules.Source.WIKITREE, field
                    ):
                        continue
                # Use source-specific parser if available
                parser = self.get_parser(field, source)
                if not parser:
                    raise RuntimeError(f"No parser for {field}")
                statement = parser(field, raw_value)
                reference = self.create_reference(field, source)
                if statement:
                    self.page.add_statement(statement, reference=reference)
                    self.data_from[source] = True

    def work_names(self, sources):
        if "en" in self.page.item.labels:
            current_label = self.page.item.labels["en"]
        elif "mul" in self.page.item.labels:
            current_label = self.page.item.labels["mul"]
            raise RuntimeError("Need to check this variant")
        else:
            return

        print(f"Current name: {current_label}")

        def do_deprecate() -> bool:
            for source in sources:
                deprecated_names = self.get_raw_value(
                    source, rules.Field.DEPRECATED_NAMES
                )
                if deprecated_names:
                    for depr_name in deprecated_names:
                        if same_name(depr_name, current_label):
                            return True

                names = np.NameParser(
                    current_label, psu.get_prefixes(), psu.get_suffixes()
                )
                if names.extracted_prefixes or names.extracted_suffixes:
                    return True

            return False

        wikitree_name = self.get_raw_value(
            rules.Source.WIKITREE, rules.Field.DISPLAY_NAME
        )
        genealogics_name = self.get_raw_value(
            rules.Source.GENEALOGICS, rules.Field.DISPLAY_NAME
        )
        if wikitree_name or genealogics_name:
            pref_name = wikitree_name or genealogics_name
            if do_deprecate():
                if current_label != pref_name:
                    self.page.deprecate_label(current_label, pref_name)
        if wikitree_name:
            self.page.add_statement(
                cwd.Label(wikitree_name, language="en"), reference=None
            )
        if genealogics_name:
            self.page.add_statement(
                cwd.Label(genealogics_name, language="en"), reference=None
            )

        for source in sources:
            aliases = self.get_raw_value(source, rules.Field.ALIASES)
            if aliases:
                for alias in aliases:
                    self.page.add_statement(
                        cwd.Label(alias, language="en"), reference=None
                    )

    def work_description(self, sources):
        if "en" not in self.page.item.descriptions:
            return

        current_desc = self.page.item.descriptions["en"]
        print(f"Current desc: {current_desc}")
        # deprecated_descs = []
        for source in sources:
            deprecated_desc = self.get_raw_value(source, rules.Field.DEPRECATED_DESC)
            if deprecated_desc:
                if current_desc == deprecated_desc:
                    self.deprecated_desc_date = deprecated_desc
                    break
                # deprecated_descs.append(deprecated_desc)

        if not self.deprecated_desc_date:
            wiki_tree_span = self.get_wiki_tree_span(current_desc)
            if wiki_tree_span:
                self.deprecated_desc_date = wiki_tree_span
            elif is_year_span(current_desc):
                self.deprecated_desc_date = current_desc

        if not self.deprecated_desc_date:
            if current_desc and is_only_spaces_and_dashes(current_desc):
                self.deprecated_desc_date = current_desc

    def work(self):
        identifiers = {}

        for pid, claims in self.page.item.claims.items():
            for claim in claims:
                if claim.rank == "deprecated":
                    continue
                if claim.type == "external-id":
                    prop_id = claim.getID()
                    if prop_id.startswith("P"):
                        # Initialize the list if the property ID is not yet in the dictionary
                        if prop_id not in identifiers:
                            identifiers[prop_id] = []
                        identifiers[prop_id].append(claim.getTarget())

        if wd.PID_GENEALOGICS_ORG_PERSON_ID in identifiers:
            if len(identifiers[wd.PID_GENEALOGICS_ORG_PERSON_ID]) != 1:
                raise RuntimeError("Multiple Genealogics.org IDs found")
        if wd.PID_WIKITREE_PERSON_ID in identifiers:
            if len(identifiers[wd.PID_WIKITREE_PERSON_ID]) != 1:
                raise RuntimeError("Multiple Genealogics.org IDs found")

        self.locale.load_from_claims(self.page.item.claims)

        self.ids = set(identifiers.keys())
        # remove ignore
        self.ids = self.ids - {
            wd.PID_FIND_A_GRAVE_MEMORIAL_ID,
            wd.PID_GENI_COM_PROFILE_ID,
            wd.PID_SAR_ANCESTOR_ID,
        }
        self.more_ids_case = len(self.ids) > 2 or (
            self.ids - {wd.PID_WIKITREE_PERSON_ID, wd.PID_GENEALOGICS_ORG_PERSON_ID}
        )

        sources = []
        if wd.PID_GENEALOGICS_ORG_PERSON_ID in identifiers:
            for id in identifiers[wd.PID_GENEALOGICS_ORG_PERSON_ID]:
                self.raw_data_sources[rules.Source.GENEALOGICS] = gap.fetch_genealogics(
                    id
                )
                self.identifiers[rules.Source.GENEALOGICS] = id
                sources = sources + [rules.Source.GENEALOGICS]
                # self.work_genealogics(id, mode=mode)

        if wd.PID_WIKITREE_PERSON_ID in identifiers:
            for id in identifiers[wd.PID_WIKITREE_PERSON_ID]:
                self.raw_data_sources[rules.Source.WIKITREE] = (
                    wtp.fetch_wikitree_profiles(id)
                )
                self.identifiers[rules.Source.WIKITREE] = id
                sources = sources + [rules.Source.WIKITREE]
                # self.work_wikitree(id, mode)

        self.work_fields(list(rules.PLACE_FIELDS), sources)
        self.work_fields(
            list(rules.ALL_EXCEPT_NAME_FIELDS - rules.PLACE_FIELDS), sources
        )
        self.work_names(sources)
        self.work_description(sources)

        if self.deprecated_desc_date:
            print(f"Deprecating description: {self.deprecated_desc_date}")
            self.page.recalc_date_span("en", self.deprecated_desc_date)

        from_arr = []
        if self.data_from[rules.Source.GENEALOGICS]:
            from_arr.append("Genealogics.org")
        if self.data_from[rules.Source.WIKITREE]:
            from_arr.append("WikiTree")
        if from_arr:
            from_str = ", ".join(from_arr)
            self.page.summary = f"from {from_str}"


def update_wikidata_from_sources(
    item: pwb.ItemPage,
    country_lookup: CountryLookupInterface,
    place_lookup: PlaceLookupInterface,
    tracker: GenealogicsStatusTracker,
    check_already_done: bool = True,
    test: bool = True,
):
    """
    Reconcile dates for a Wikidata item, using a status tracker to avoid reprocessing.
    """
    if check_already_done:
        if tracker.is_done(item.id):
            print(f"Item {item.id} already processed.")
            return
        if tracker.is_error(item.id):
            print(f"Item {item.id} already processed.")
            return

    try:
        print(f"-- {item.id} --")
        page = cwd.WikiDataPage(item, test=test)

        updater = WikidataUpdater(page, country_lookup, place_lookup, tracker)
        updater.work()

        changed = False
        if len(page.actions) > 0:
            page.check_date_statements()
            changed = page.apply()

        if not test:
            if changed:
                tracker.mark_done(page.item.id, "changed")
            else:
                tracker.mark_done(page.item.id, "nothing changed")

    except RuntimeError as e:
        print(f"Error processing item {item.id}: {e}")
        tracker.mark_error(item.id, f" {str(e)}".strip())
    except ValueError as e:
        print(f"Value error for item {item.id}: {e}")
        tracker.mark_error(item.id, f" {str(e)}".strip())
