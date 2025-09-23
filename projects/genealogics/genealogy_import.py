import re
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple, Type

import genealogics.genealogics_date as gd
import genealogics.genealogics_org_parser as gap
import genealogics.nameparser as np
import genealogics.prefix_suffix_utils as psu
import genealogics.rules as rules
import genealogics.titles as titles
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
    pattern1 = r"^(?:\()?(?:\d{3,4})?\s?[–—-]\s?(?:\d{3,4})?(?:\))?$"
    pattern2 = r"^\d{4}$"
    return (
        re.fullmatch(pattern1, text) is not None
        or re.fullmatch(pattern2, text) is not None
    )


def is_only_spaces_and_dashes(s):
    return bool(s) and set(s).issubset({" ", "-"})


def same_name(name1: str, name2: str) -> bool:
    return name1 == name2


def has_word(text: str, word: str) -> bool:
    """
    Check if `word` appears as a whole word in `text`, case-insensitive.
    Word boundaries are respected to avoid partial matches.
    """
    pattern = rf"\b{re.escape(word)}\b"
    return re.search(pattern, text, re.IGNORECASE) is not None


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

    def parse_title(
        self, field: rules.Field, source: rules.Source, value: str
    ) -> list[cwd.Statement]:
        lived_in = self.get_raw_value(source, rules.Field.LIVED_IN)
        if not lived_in:
            lived_in = ""
        return titles.analyze_title(self.place_lookup, value, lived_in)

    def parse_gender(
        self, field: rules.Field, source: rules.Source, value: str
    ) -> list[cwd.Statement]:
        if value == "Male":
            gender_qid = wd.QID_MALE
        elif value == "Female":
            gender_qid = wd.QID_FEMALE
            raise RuntimeError("Need to check - Female")
        else:
            raise RuntimeError(f"Unexpected gender {value}")
        statement = cwd.SexOrGender(qid=gender_qid)
        return [statement]

    def parse_prefix(
        self, field: rules.Field, source: rules.Source, value: str
    ) -> list[cwd.Statement]:
        result = []
        arr = psu.analyze_prefix(value, include_full=True)
        for item in arr:
            cls, qid = item
            result.append(cls(qid=qid))
        return result

    def parse_suffix(
        self, field: rules.Field, source: rules.Source, value: str
    ) -> list[cwd.Statement]:
        result = []
        arr = psu.analyze_suffix(value)
        for item in arr:
            cls, qid = item
            result.append(cls(qid=qid))
        return result

    def parse_external_id(
        self, field: rules.Field, source: rules.Source, value: str
    ) -> list[cwd.Statement]:
        if field == rules.Field.FIND_A_GRAVE_ID:
            statement = cwd.ExternalIDStatement(
                prop=wd.PID_FIND_A_GRAVE_MEMORIAL_ID, external_id=value
            )
            return [statement]

        raise RuntimeError(f"parse_external_id: Unexpected field {field}")

    def parse_place(
        self, field: rules.Field, source: rules.Source, value
    ) -> list[cwd.Statement]:
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
        return [statement]

    def parse_date(
        self, field: rules.Field, source: rules.Source, value: gd.GenealogicsDate
    ) -> list[cwd.Statement]:
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
        if value.is_decade:
            raise RuntimeError("Need to check this variant: decade")
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
        statement = cls(
            date=date,
            earliest=earliest,
            latest=latest,
            is_circa=is_circa,
            remove_old_claims=True,
        )
        return [statement]

    def get_wiki_tree_span(self, description: str) -> Optional[str]:
        date_pattern = (
            r"(?:certain|uncertain|est\.)? ?(?:\d{1,2})? ?(?:[A-Za-z]{3})? ?\d{4}"
        )
        pattern1 = rf"\(?{date_pattern} - {date_pattern}\)?"
        pattern2 = rf"\(?{date_pattern} - \)?"
        pattern3 = rf"\(? - {date_pattern}\)?"
        match = (
            re.search(pattern1, description)
            or re.search(pattern2, description)
            or re.search(pattern3, description)
        )

        if match:
            date_range = match.group(0)
            if date_range == description:
                return date_range
            if date_range.startswith("(") and date_range.endswith(")"):
                return date_range
            if description.endswith(f", {date_range}"):
                return f", {date_range}"
        return None

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
        elif field == rules.Field.TITLE:
            return self.parse_title
        return None

    def get_pid(self, field: rules.Field) -> str:
        DICT = {
            rules.Field.PREFIX: None,
            rules.Field.SUFFIX: None,
            rules.Field.TITLE: None,
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
            raise RuntimeError(f"Unexpected field {field}")

    def has_wikidata_field(self, field: rules.Field) -> bool:
        pid = self.get_pid(field)
        if not pid:
            return False
        has = pid in self.page.item.claims
        return has

    def create_reference_for_pid(self, pid: Optional[str], source: rules.Source):
        if pid in [
            wd.PID_ACADEMIC_DEGREE,
            wd.PID_DATE_OF_BAPTISM,
            wd.PID_DATE_OF_BIRTH,
            wd.PID_DATE_OF_BURIAL_OR_CREMATION,
            wd.PID_DATE_OF_DEATH,
            wd.PID_PLACE_OF_BIRTH,
            wd.PID_PLACE_OF_DEATH,
            wd.PID_FIND_A_GRAVE_MEMORIAL_ID,
        ]:
            return self.create_reference(source)
        elif pid in [
            wd.PID_SEX_OR_GENDER,
            wd.PID_HONORIFIC_PREFIX,
            wd.PID_HONORIFIC_SUFFIX,
            wd.PID_OCCUPATION,
            wd.PID_WORK_LOCATION,
            wd.PID_RESIDENCE,
            wd.PID_MEMBER_OF,
            wd.PID_AWARD_RECEIVED,
            wd.PID_NOBLE_TITLE,
        ]:
            return None
        else:
            raise RuntimeError(f"Unknown PID {pid}")

    def create_reference(self, source: rules.Source) -> cwd.Reference:
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

    def has_wikidata_pid_qid(self, pid: str, qid: str) -> bool:
        if pid not in self.page.item.claims:
            return False

        for claim in self.page.item.claims[pid]:
            t = claim.getTarget()
            if t:
                if t.id == qid:
                    return True
        return False

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

    def should_skip_statement(self, statement):
        pid = statement.get_prop()
        if pid in [wd.PID_MEMBER_OF, wd.PID_AWARD_RECEIVED]:
            qid = statement.qid
            if not qid:
                return False

            return self.has_wikidata_pid_qid(pid, qid)

        return False

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
                statements = parser(field, source, raw_value)
                if statements:
                    for statement in statements:
                        # skip some statements if they are already in wikidata
                        if self.should_skip_statement(statement):
                            continue
                        reference = self.create_reference_for_pid(
                            statement.get_prop(), source=source
                        )
                        self.page.add_statement(statement, reference=reference)
                    self.data_from[source] = True

    def check_placeholders(self, text: str, strict: bool = True):
        placeholders = [
            "unknown",
            "Unknown",
            "Unkown",
            "Unknowm",
            "Unkownn",
            "Unkownnn",
            "NN",
            "?",
            "_",
        ]
        for placeholder in placeholders:
            if placeholder in text:
                raise RuntimeError(
                    f"Need to check this variant; placeholder {placeholder}"
                )

        if '"' in text or "’" in text:
            raise RuntimeError("Need to check this variant; quote in name")
        if "|" in text:
            raise RuntimeError("Need to check this variant; pipe in name")
        if ", of " in text:
            raise RuntimeError("Need to check this variant; , of in name")
        if " gen." in text:
            raise RuntimeError("Need to check this variant; gen. in name")
        if "(" in text or ")" in text:
            raise RuntimeError("Need to check this variant; parentheses () in name")
        if "[" in text or "]" in text:
            raise RuntimeError("Need to check this variant; parentheses [] in name")
        if strict:
            if "," in text:
                raise RuntimeError("Need to check this variant; , in name")
            if has_word(text, "baron"):
                raise RuntimeError("Need to check this variant; baron in name")
            if "," in text:
                raise RuntimeError("Need to check this variant; , in name")
        if " ap " in text:
            raise RuntimeError("Need to check this variant; ap in name")

    def work_names(self, sources):
        if "en" in self.page.item.labels:
            current_label = self.page.item.labels["en"]
        elif "mul" in self.page.item.labels:
            current_label = self.page.item.labels["mul"]
            raise RuntimeError("Need to check this variant; work_names only mul")
        else:
            return

        print(f"Current name: {current_label}")

        if wd.PID_PSEUDONYM in self.page.claims:
            for claim in self.page.claims[wd.PID_PSEUDONYM]:
                pseudonym = claim.getTarget()
                if pseudonym == current_label:
                    print("Current name is a pseudonym")
                    return
            raise RuntimeError(
                "Need to check this variant; pseudonym diff current-name"
            )

        def do_deprecate() -> bool:
            for source in sources:
                deprecated_names = self.get_raw_value(
                    source, rules.Field.DEPRECATED_NAMES
                )
                if deprecated_names:
                    for depr_name in deprecated_names:
                        if same_name(depr_name, current_label):
                            return True

            names = np.NameParser(current_label, psu.get_prefixes(), psu.get_suffixes())
            if names.extracted_prefixes or names.extracted_suffixes:
                return True

            return False

        wikitree_name = self.get_raw_value(
            rules.Source.WIKITREE, rules.Field.DISPLAY_NAME
        )
        genealogics_name = self.get_raw_value(
            rules.Source.GENEALOGICS, rules.Field.DISPLAY_NAME
        )
        replaced = False
        if wikitree_name or genealogics_name:
            pref_name = wikitree_name or genealogics_name
            self.check_placeholders(pref_name)
            if do_deprecate():
                if current_label != pref_name:
                    self.page.deprecate_label(current_label, pref_name)
                    replaced = True

        self.check_placeholders(current_label, strict=not replaced)

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
            if not self.more_ids_case:
                self.page.recalc_date_span("en", "")
            return

        current_desc = self.page.item.descriptions["en"]
        print(f"Current desc: {current_desc}")

        deprecated_descs = []
        for source in sources:
            src_deprecated_descs = self.get_raw_value(
                source, rules.Field.DEPRECATED_DESCS
            )
            if src_deprecated_descs:
                deprecated_descs = deprecated_descs + src_deprecated_descs

        if deprecated_descs:
            for deprecated_desc in deprecated_descs:
                if current_desc == deprecated_desc:
                    self.deprecated_desc_date = deprecated_desc
                    break

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
            wd.PID_CAMBRIDGE_ALUMNI_DATABASE_ID,
            wd.PID_FIND_A_GRAVE_MEMORIAL_ID,
            wd.PID_GENI_COM_PROFILE_ID,
            wd.PID_GOOGLE_KNOWLEDGE_GRAPH_ID,
            wd.PID_PRABOOK_ID,
            wd.PID_SAR_ANCESTOR_ID,
            wd.PID_FREEBASE_ID,
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

        if rules.Source.WIKITREE in sources and rules.Source.GENEALOGICS in sources:
            wktr_ref = self.create_reference(source=rules.Source.WIKITREE)
            gen_ref = self.create_reference(source=rules.Source.GENEALOGICS)

            self.page.pref_date_statements([wktr_ref, gen_ref])
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
            return "processed"
        if tracker.is_error(item.id):
            print(f"Item {item.id} already processed.")
            return "processed"

    try:
        print(f"-- {item.id} --")
        page = cwd.WikiDataPage(item, test=test)

        updater = WikidataUpdater(page, country_lookup, place_lookup, tracker)
        updater.work()

        changed = False
        if len(page.actions) > 0:
            page.check_date_statements()
            page.check_aliases()
            changed = page.apply()

        if test:
            if changed:
                print(f"Item {item.id} would be changed.")
                return "would change"
            else:
                print(f"Item {item.id} would not change.")
                return "would not change"
        else:
            if changed:
                tracker.mark_done(page.item.id, "changed")
                return "changed"
            else:
                tracker.mark_done(page.item.id, "nothing changed")
                return "nothing changed"

    except RuntimeError as e:
        print(f"Error processing item {item.id}: {e}")
        tracker.mark_error(item.id, f" {str(e)}".strip())
        return "error"
    except ValueError as e:
        print(f"Value error for item {item.id}: {e}")
        tracker.mark_error(item.id, f" {str(e)}".strip())
        return "error"
