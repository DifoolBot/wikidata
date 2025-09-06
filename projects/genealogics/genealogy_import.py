import re
from abc import ABC, abstractmethod
from pprint import pprint
from typing import List, Optional, Tuple, Type

import genealogics.genealogics_date as gd
import genealogics.genealogics_org_parser as gap
import genealogics.nameparser as np
import genealogics.wikitree_parser as wtp
import pywikibot as pwb

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
from shared_lib.lookups.interfaces.place_lookup_interface import (
    PlaceLookupInterface,
    CountryLookupInterface,
)
from shared_lib.locale_resolver import LocaleResolver
from shared_lib.calendar_system_resolver import DateCalendarService

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


def StateInGenealogicsOrg(identifier: str) -> cwd.Reference:
    return cwd.StateInReference(
        wd.QID_GENEALOGICS, wd.PID_GENEALOGICS_ORG_PERSON_ID, identifier
    )


def StateInWikiTree(identifier: str) -> cwd.Reference:
    return cwd.StateInReference(wd.QID_WIKITREE, wd.PID_WIKITREE_PERSON_ID, identifier)


def is_year_span(text: str) -> bool:
    pattern = r"^(?:\()?\d{3,4}\s?[–—-]\s?\d{3,4}(?:\))?$"
    return re.fullmatch(pattern, text) is not None


def is_only_spaces_and_dashes(s):
    return bool(s) and set(s).issubset({" ", "-"})


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
        self.data_from_genealogics = False
        self.data_from_wikitree = False
        self.deprecated_desc_date = None
        self.locale = LocaleResolver(place_lookup)
        self.date_service = None

    def create_date(self, cls: Type[cwd.DateStatement], g_date: gd.GenealogicsDate):
        earliest = latest = None
        is_circa = False
        if not self.date_service:
            self.date_service = DateCalendarService(
                country_qid=self.locale.resolve(), country_lookup=self.country_lookup
            )
        wb_time = self.date_service.get_wbtime(
            year=g_date.year, month=g_date.month, day=g_date.day
        )
        date = cwd.Date.create_from_WbTime(wb_time)
        if date.calendar == cwd.CALENDAR_ASSUMED_GREGORIAN:
            date.calendar = cwd.CALENDAR_GREGORIAN
        if g_date.modifier == "before":
            latest = date
            if date.precision == cwd.PRECISION_DAY:
                date = cwd.Date(year=g_date.year, calendar=date.calendar)
            else:
                date = None
        elif g_date.modifier == "after":
            earliest = date
            if date.precision == cwd.PRECISION_DAY:
                date = cwd.Date(year=g_date.year, calendar=date.calendar)
            else:
                date = None
        elif g_date.modifier in ["about", "estimated"]:
            is_circa = True
        elif not g_date.modifier:
            pass
        else:
            raise ValueError(f"Unexpected date modifier {g_date.modifier}")
        return cls(
            date=date,
            earliest=earliest,
            latest=latest,
            is_circa=is_circa,
            remove_old_claims=True,
        )

    def get_wiki_tree_span(self, description: str) -> Optional[str]:
        pattern = r"\(?(?:certain|uncertain)? ?\d{1,2} [A-Za-z]{3} \d{4} - (?:(?:certain|uncertain)? ?\d{1,2} [A-Za-z]{3} \d{4})?\)?"
        match = re.search(pattern, description)

        if match:
            date_range = match.group(0)
            return date_range
        else:
            return None

    def work_wikitree(self, wt_id: str, mode: str):
        data = wtp.fetch_wikitree_profiles(wt_id)
        pprint(data, sort_dicts=False)

        if mode == "full" or wd.PID_PLACE_OF_BIRTH not in self.page.claims:
            if birth_location := data.get("birth_location"):
                location_qid = self.place_lookup.get_place_qid_by_desc(birth_location)
                if not location_qid:
                    raise RuntimeError(f"Location not found: {birth_location}")
                self.page.add_statement(
                    cwd.PlaceOfBirth(qid=location_qid),
                    reference=StateInWikiTree(wt_id),
                )
                self.locale.add_place_of_birth(location_qid)
                self.data_from_wikitree = True

        if mode == "full" or wd.PID_PLACE_OF_DEATH not in self.page.claims:
            if death_location := data.get("death_location"):
                location_qid = self.place_lookup.get_place_qid_by_desc(death_location)
                if not location_qid:
                    raise RuntimeError(f"Location not found: {death_location}")
                self.page.add_statement(
                    cwd.PlaceOfDeath(qid=location_qid),
                    reference=StateInWikiTree(wt_id),
                )
                self.locale.add_place_of_death(location_qid)
                self.data_from_wikitree = True

        if mode == "full" or wd.PID_DATE_OF_BIRTH not in self.page.claims:
            if birth_date := data.get("birth_date"):
                self.page.add_statement(
                    self.create_date(cwd.DateOfBirth, birth_date),
                    reference=StateInWikiTree(wt_id),
                )
                self.data_from_wikitree = True

        if mode == "full" or wd.PID_DATE_OF_DEATH not in self.page.claims:
            if death_date := data.get("death_date"):
                self.page.add_statement(
                    self.create_date(cwd.DateOfDeath, death_date),
                    reference=StateInWikiTree(wt_id),
                )
                self.data_from_wikitree = True

        if findagrave_id := data.get("findagrave_id"):
            self.page.add_statement(
                cwd.ExternalIDStatement(
                    prop=wd.PID_FIND_A_GRAVE_MEMORIAL_ID, external_id=findagrave_id
                ),
                reference=StateInWikiTree(wt_id),
            )
            self.data_from_wikitree = True

        if mode in ["full", "wikitree"]:
            if "en" in self.page.item.labels:
                display_name = data.get("display_name")
                current_label = self.page.item.labels["en"]
                if display_name:
                    for name in data.get("deprecated_names", []):
                        if current_label == name:
                            print(
                                f"Deprecating label: {current_label} -> {display_name}"
                            )
                            self.page.deprecate_label(current_label, display_name)
                            self.data_from_wikitree = True
                            break
            if "en" in self.page.item.descriptions:
                current_desc = self.page.item.descriptions["en"]
                wiki_tree_span = self.get_wiki_tree_span(current_desc)
                if wiki_tree_span:
                    self.deprecated_desc_date = wiki_tree_span
                elif is_year_span(current_desc):
                    self.deprecated_desc_date = current_desc

        if not self.deprecated_desc_date:
            if "en" in self.page.item.descriptions:
                current_desc = self.page.item.descriptions["en"]
                if current_desc and is_only_spaces_and_dashes(current_desc):
                    self.deprecated_desc_date = current_desc

        if prefix := data.get("prefix"):
            # honorific prefix (P511) Lieutenant (Q123564138)
            if prefix == "Lieutenant" or prefix == "Lieut." or prefix == "Lieut":
                pass
            elif prefix == "Sir":
                self.page.add_statement(
                    cwd.HonorificPrefix(qid=wd.QID_SIR),
                    reference=None,
                )
                self.data_from_wikitree = True
            elif prefix == "Ensign":
                # military or police rank x ensign
                pass
            elif prefix == "Capt.":
                # military or police rank x ensign
                pass
            elif prefix == "Rev." or prefix == "Rev":
                self.page.add_statement(
                    cwd.HonorificPrefix(qid=wd.QID_REVEREND),
                    reference=None,
                )
                self.data_from_wikitree = True
            elif prefix == "Dr":
                # military or police rank x ensign
                pass
            else:
                raise NotImplementedError(f"Prefix not implemented yet: {prefix}")

    def work_genealogics(self, id: str, mode: str):
        data = gap.fetch_genealogics(id)
        pprint(data, sort_dicts=False)
        label_parts = data.get("label_parts")
        if not label_parts:
            raise RuntimeError("No label parts found")
        if len(label_parts) not in [1, 2]:
            raise RuntimeError("Unexpected label parts")
        names = np.NameParser(label_parts[0])
        print(names)
        if not names.cleaned_name:
            raise RuntimeError("No cleaned name found")
        if gender := data.get("gender"):
            if gender == "Male":
                gender_qid = wd.QID_MALE
            elif gender == "Female":
                gender_qid = wd.QID_FEMALE
            else:
                raise ValueError(f"Unexpected gender {gender}")
            if wd.PID_SEX_OR_GENDER not in self.page.claims:
                self.page.add_statement(cwd.SexOrGender(qid=gender_qid), reference=None)
                self.data_from_genealogics = True

        if birth := data.get("birth"):
            if mode in ["full", "wikitree"]:

                if birth_date := birth.get("date"):
                    self.page.add_statement(
                        self.create_date(cwd.DateOfBirth, birth_date),
                        reference=StateInGenealogicsOrg(id),
                    )
                    self.data_from_genealogics = True

                if birth_place := birth.get("place"):
                    lived_in = data.get("lived_in")
                    if lived_in:
                        birth_place = f"{birth_place}, {lived_in}"
                    location_qid = self.place_lookup.get_place_qid_by_desc(birth_place)
                    if not location_qid:
                        raise RuntimeError(f"Location not found: {birth_place}")
                    self.page.add_statement(
                        cwd.PlaceOfBirth(qid=location_qid),
                        reference=StateInGenealogicsOrg(id),
                    )
                    self.locale.add_place_of_birth(location_qid)
                    self.data_from_genealogics = True
        if wd.PID_DATE_OF_BAPTISM not in self.page.claims:
            if christening := data.get("christening"):
                if christening_date := christening.get("date"):
                    self.page.add_statement(
                        self.create_date(cwd.DateOfBaptism, christening_date),
                        reference=StateInGenealogicsOrg(id),
                    )

                    self.data_from_genealogics = True

        if death := data.get("death"):
            if mode in ["full", "wikitree"]:

                if death_date := death.get("date"):
                    self.page.add_statement(
                        self.create_date(cwd.DateOfDeath, death_date),
                        reference=StateInGenealogicsOrg(id),
                    )
                    self.data_from_genealogics = True

                if death_place := death.get("place"):
                    lived_in = data.get("lived_in")
                    if lived_in:
                        birth_place = f"{death_place}, {lived_in}"
                    location_qid = self.place_lookup.get_place_qid_by_desc(death_place)
                    if not location_qid:
                        raise RuntimeError(f"Location not found: {death_place}")
                    self.page.add_statement(
                        cwd.PlaceOfDeath(qid=location_qid),
                        reference=StateInGenealogicsOrg(id),
                    )
                    self.data_from_genealogics = True

        if wd.PID_DATE_OF_BURIAL_OR_CREMATION not in self.page.claims:
            if burial := data.get("burial"):
                if burial_date := burial.get("date"):
                    self.page.add_statement(
                        self.create_date(cwd.DateOfBurialOrCremation, burial_date),
                        reference=StateInGenealogicsOrg(id),
                    )

                    self.data_from_genealogics = True

        if mode in ["full", "wikitree"]:
            if names.location:
                location = names.location
                lived_in = data.get("lived_in")
                if lived_in:
                    location = f"{location}; {lived_in}"
                location_qid = self.place_lookup.get_place_qid_by_desc(location)
                if not location_qid:
                    raise RuntimeError(f"Location not found: {location}")
                self.page.add_statement(cwd.Residence(qid=location_qid), reference=None)
                self.locale.add_place(location_qid)
                self.data_from_genealogics = True

        if mode in ["full", "wikitree"]:
            if "en" in self.page.item.labels:
                current_label = self.page.item.labels["en"]
                if len(label_parts) == 2:
                    title = label_parts[1]
                    raw_text = f"{label_parts[0]}, {title}"
                    cleaned_name = f"{names.cleaned_name}, {title}"
                else:
                    raw_text = label_parts[0]
                    cleaned_name = names.cleaned_name
                if names.cleaned_name and (current_label == raw_text):
                    if raw_text != cleaned_name:
                        self.page.deprecate_label(current_label, cleaned_name)
                        self.data_from_genealogics = True

                for name in names.variants:
                    self.page.add_statement(
                        cwd.Label(name, language="en"), reference=None
                    )
                    self.data_from_genealogics = True

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

        id_set = set(identifiers.keys())
        # remove ignore
        id_set = id_set - {
            wd.PID_FIND_A_GRAVE_MEMORIAL_ID,
            wd.PID_GENI_COM_PROFILE_ID,
            wd.PID_SAR_ANCESTOR_ID,
        }
        if id_set <= set([wd.PID_GENEALOGICS_ORG_PERSON_ID]):
            mode = "full"
        elif id_set <= set(
            [
                wd.PID_GENEALOGICS_ORG_PERSON_ID,
                wd.PID_WIKITREE_PERSON_ID,
            ]
        ):
            mode = "wikitree"
        else:
            mode = "simple"

        if wd.PID_GENEALOGICS_ORG_PERSON_ID in identifiers:
            for id in identifiers[wd.PID_GENEALOGICS_ORG_PERSON_ID]:
                self.work_genealogics(id, mode=mode)

        if mode == "wikitree":
            mode = "full"
        if wd.PID_WIKITREE_PERSON_ID in identifiers:
            for id in identifiers[wd.PID_WIKITREE_PERSON_ID]:
                self.work_wikitree(id, mode)

        if self.deprecated_desc_date:
            print(f"Deprecating description: {self.deprecated_desc_date}")
            self.page.recalc_date_span("en", self.deprecated_desc_date)

        from_arr = []
        if self.data_from_genealogics:
            from_arr.append("Genealogics.org")
        if self.data_from_wikitree:
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
        print(f"--{item.id}--")
        page = cwd.WikiDataPage(item, test=test)

        updater = WikidataUpdater(page, country_lookup, place_lookup, tracker)
        updater.work()

        if len(page.actions) > 0:
            page.check_date_statements()
            page.apply()

            if not test:
                tracker.mark_done(page.item.id, "changed")
        else:
            if not test:
                tracker.mark_done(page.item.id, "nothing changed")

    except RuntimeError as e:
        print(f"Error processing item {item.id}: {e}")
        tracker.mark_error(item.id, f" {str(e)}".strip())
    except ValueError as e:
        print(f"Value error for item {item.id}: {e}")
        tracker.mark_error(item.id, f" {str(e)}".strip())
