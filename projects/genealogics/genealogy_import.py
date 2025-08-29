from abc import ABC, abstractmethod
from pprint import pprint
from typing import List, Optional, Tuple
from typing import Type

import genealogics.genealogics_org_parser as gap
import genealogics.wikitree_parser as wtp
import genealogics.nameparser as np
import pywikibot as pwb
import genealogics.genealogics_date as gd

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd

# TODO:
#   * Update description
#   * Only genealogics.org -> always update name
#   * Add title to Nameparser
#   * Check if current name is problematic -> deprecate, else -> deprecate only English label
#   * Gaat iets fout met None dates met before/after
#   * gebruik code voor Julian/Gregorian
#   * Q100450663: description aanpassen


class GenealogicsStatusTracker(ABC):
    @abstractmethod
    def is_done(self, qid: str) -> bool:
        """Return True if the item is already marked as done."""
        pass

    @abstractmethod
    def mark_done(self, qid: str, language: Optional[str], message: str):
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

    @abstractmethod
    def get_location_qid(self, location: str) -> Optional[str]:
        """Get the QID for a location string, or None if not found."""
        pass


def StateInGenealogicsOrg() -> cwd.Reference:
    return cwd.StateInReference(wd.QID_GENEALOGICS)


def StateInWikiTree() -> cwd.Reference:
    return cwd.StateInReference(wd.QID_WIKITREE)


class WikidataUpdater:
    def __init__(
        self,
        page: cwd.WikiDataPage,
        tracker: GenealogicsStatusTracker,
    ):
        self.page = page
        self.tracker = tracker
        self.qid = self.page.item.id
        self.data_from_genealogics = False
        self.data_from_wikitree = False

    def create_date(self, cls: Type[cwd.DateStatement], g_date: gd.GenealogicsDate):
        earliest = latest = None
        date = cwd.Date(year=g_date.year, month=g_date.month, day=g_date.day)
        if g_date.modifier == "before":
            latest = date
            if date.precision == cwd.PRECISION_DAY:
                date = cwd.Date(year=g_date.year)
            else:
                date = None
        elif g_date.modifier == "after":
            earliest = date
            if date.precision == cwd.PRECISION_DAY:
                date = cwd.Date(year=g_date.year)
            else:
                date = None
        elif not g_date.modifier:
            pass
        else:
            raise ValueError(f"Unexpected date modifier {g_date.modifier}")
        return cls(date=date, earliest=earliest, latest=latest)

    def work_wikitree(self, wt_id: str):
        data = wtp.fetch_wikitree_profiles(wt_id)
        pprint(data, sort_dicts=False)

        if birth_date := data.get("birth_date"):
            self.page.add_statement(
                self.create_date(cwd.DateOfBirth, birth_date),
                reference=StateInWikiTree(),
            )
            self.data_from_wikitree = True

        if birth_location := data.get("birth_location"):
            location_qid = self.tracker.get_location_qid(birth_location)
            if not location_qid:
                raise RuntimeError(f"Location not found: {birth_location}")
            self.page.add_statement(
                cwd.PlaceOfBirth(qid=location_qid),
                reference=StateInGenealogicsOrg(),
            )
            self.data_from_wikitree = True

        if death_date := data.get("death_date"):
            self.page.add_statement(
                self.create_date(cwd.DateOfDeath, death_date),
                reference=StateInWikiTree(),
            )
            self.data_from_wikitree = True

        if death_location := data.get("death_location"):
            location_qid = self.tracker.get_location_qid(death_location)
            if not location_qid:
                raise RuntimeError(f"Location not found: {death_location}")
            self.page.add_statement(
                cwd.PlaceOfDeath(qid=location_qid),
                reference=StateInGenealogicsOrg(),
            )
            self.data_from_wikitree = True

        if findagrave_id := data.get("findagrave_id"):
            self.page.add_statement(
                cwd.ExternalIDStatement(
                    prop=wd.PID_FIND_A_GRAVE_MEMORIAL_ID, external_id=findagrave_id
                ),
                reference=StateInWikiTree(),
            )
            self.data_from_wikitree = True

        if prefix := data.get("prefix"):
            if prefix == "Lieutenant":
                pass
            else:
                raise NotImplementedError(f"Prefix not implemented yet: {prefix}")

    def work_genealogics(self, id: str):
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
            self.page.add_statement(cwd.SexOrGender(qid=gender_qid), reference=None)
            self.data_from_genealogics = True
        if birth := data.get("birth"):

            if birth_date := birth.get("date"):
                self.page.add_statement(
                    self.create_date(cwd.DateOfBirth, birth_date),
                    reference=StateInGenealogicsOrg(),
                )
                self.data_from_genealogics = True

            if birth_place := birth.get("place"):
                location_qid = self.tracker.get_location_qid(birth_place)
                if not location_qid:
                    raise RuntimeError(f"Location not found: {birth_place}")
                self.page.add_statement(
                    cwd.PlaceOfBirth(qid=location_qid),
                    reference=StateInGenealogicsOrg(),
                )
                self.data_from_genealogics = True
        if "christening" in data and data["christening"]:
            raise NotImplementedError("Christening not implemented yet")

        if death := data.get("death"):

            if death_date := death.get("date"):
                self.page.add_statement(
                    self.create_date(cwd.DateOfDeath, death_date),
                    reference=StateInGenealogicsOrg(),
                )
                self.data_from_genealogics = True

            if death_place := death.get("place"):
                location_qid = self.tracker.get_location_qid(death_place)
                if not location_qid:
                    raise RuntimeError(f"Location not found: {death_place}")
                self.page.add_statement(
                    cwd.PlaceOfDeath(qid=location_qid),
                    reference=StateInGenealogicsOrg(),
                )
                self.data_from_genealogics = True

        if "burial" in data and data["burial"]:
            raise NotImplementedError("Burial not implemented yet")

        if names.location:
            location = names.location
            lived_in = data.get("lived_in")
            if lived_in:
                location = f"{location}; {lived_in}"
            location_qid = self.tracker.get_location_qid(location)
            if not location_qid:
                raise RuntimeError(f"Location not found: {location}")
            self.page.add_statement(cwd.Residence(qid=location_qid), reference=None)
            self.data_from_genealogics = True

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
                self.page.add_statement(cwd.Label(name, language="en"), reference=None)
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

        if wd.PID_GENEALOGICS_ORG_PERSON_ID in identifiers:
            for id in identifiers[wd.PID_GENEALOGICS_ORG_PERSON_ID]:
                self.work_genealogics(id)
        if wd.PID_WIKITREE_PERSON_ID in identifiers:
            for id in identifiers[wd.PID_WIKITREE_PERSON_ID]:
                self.work_wikitree(id)

        from_arr = []
        if self.data_from_genealogics:
            from_arr.append("Genealogics.org")
        if self.data_from_wikitree:
            from_arr.append("WikiTree")
        if from_arr:
            from_str = ", ".join(from_arr)
            self.page.summary = f"Data from {from_str}"


def update_wikidata_from_sources(
    item: pwb.ItemPage,
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

        updater = WikidataUpdater(page, tracker)
        updater.work()

        if len(page.actions) > 0:
            page.check_date_statements()
            page.apply()

    except RuntimeError as e:
        print(f"Error processing item {item.id}: {e}")
        tracker.mark_error(item.id, f" {str(e)}".strip())
    except ValueError as e:
        print(f"Value error for item {item.id}: {e}")
        tracker.mark_error(item.id, f" {str(e)}".strip())
