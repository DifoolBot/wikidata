import abc
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set

import ecartico.external_pages as external_pages
import pywikibot as pwb
from bs4 import BeautifulSoup, Tag

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
from shared_lib.lookups.interfaces.ecartico_lookup_interface import (
    EcarticoLookupAddInterface,
)
from shared_lib.date_value import Date

SOURCE_RKD_IMAGES = "1987"
SOURCE_RKD_PORTRAITS = "3416"
SOURCE_RIJKSMUSEUM_AMSTERDAM = "3174"
SOURCE_LE_DICTIONNAIRE_DES_PEINTRES_BELGES = "326"

MAX_EXPECTED_LIFE_SPAN = 100

SITE = pwb.Site("wikidata", "wikidata")
SITE.login()
SITE.get_tokens("csrf")
REPO = SITE.data_repository()


def _get_href(url_elem) -> str:
    if not isinstance(url_elem, Tag):
        raise RuntimeError("Unexpected url_elem type")
    href = url_elem.get("href")
    if not isinstance(href, str):
        raise RuntimeError("Unexpected href type")
    return href


def decode_date(date_str: str):
    if len(date_str) == 10:  # Format: YYYY-MM-DD
        date = datetime.strptime(date_str, "%Y-%m-%d")
        return date.year, date.month, date.day
    elif len(date_str) == 7:  # Format: YYYY-MM
        date = datetime.strptime(date_str, "%Y-%m")
        return date.year, date.month, None
    elif len(date_str) == 4:  # Format: YYYY
        date = datetime.strptime(date_str, "%Y")
        return date.year, None, None
    else:
        raise ValueError(f"Invalid date format: {date_str}")


def construct_date(date_str: Optional[str]) -> Optional[cwd.Date]:
    if not date_str or (date_str == "0"):
        return None
    year, month, day = decode_date(date_str)
    return cwd.Date(year, month, day)


def is_rkd_source(src):
    if wd.PID_STATED_IN in src:
        for claim in src[wd.PID_STATED_IN]:
            id = claim.getTarget().getID()
            if id == wd.QID_RKDARTISTS:
                return True
    if wd.PID_RKDARTISTS_ID in src:
        return True

    return False


def has_rkd_work_location(claims):
    if wd.PID_WORK_LOCATION not in claims:
        return False

    claims = claims[wd.PID_WORK_LOCATION]
    claims = cwd.filter_claims_by_rank(claims)
    for claim in claims:
        if claim.getRank() == "deprecated":
            continue
        srcs = claim.getSources()
        for src in srcs:
            if is_rkd_source(src):
                return True
    return False


class EcarticoReference(cwd.Reference):
    def __init__(self, ecartico_id):
        self.pid = wd.PID_ECARTICO_PERSON_ID
        self.id = ecartico_id

    def is_equal_reference(self, src) -> bool:
        if self.pid not in src:
            return False
        if len(src[self.pid]) != 1:
            raise RuntimeError("Multiple ecartico ids")
        actual = src[self.pid][0].getTarget()
        return actual == self.id

    def is_strong_reference(self) -> bool:
        return True

    def create_source(self):
        source = OrderedDict()

        stated_in_claim = pwb.Claim(REPO, wd.PID_STATED_IN, is_reference=True)
        stated_in_claim.setTarget(pwb.ItemPage(REPO, wd.QID_ECARTICO))

        ecartico_claim = pwb.Claim(REPO, wd.PID_ECARTICO_PERSON_ID, is_reference=True)
        ecartico_claim.setTarget(self.id)

        today = datetime.now(timezone.utc)
        dateCre = pwb.WbTime(
            year=int(today.strftime("%Y")),
            month=int(today.strftime("%m")),
            day=int(today.strftime("%d")),
        )
        retr_claim = pwb.Claim(REPO, wd.PID_RETRIEVED, is_reference=True)
        retr_claim.setTarget(dateCre)

        source[wd.PID_STATED_IN] = [stated_in_claim]
        source[wd.PID_ECARTICO_PERSON_ID] = [ecartico_claim]
        source[wd.PID_RETRIEVED] = [retr_claim]

        return source


class FindYear:
    def __init__(self):
        self.earliest = None
        self.is_earliest_circa = False
        self.latest = None
        self.is_latest_circa = None

    def has_found(self) -> bool:
        return bool(self.earliest or self.latest)

    def add(self, date: Optional[cwd.Date], is_circa: bool = False):
        if not date or not date.year:
            return
        year = date.year

        if self.earliest is None or year < self.earliest:
            self.earliest = year
            self.is_earliest_circa = is_circa
        if self.latest is None or year > self.latest:
            self.latest = year
            self.is_latest_circa = is_circa

    def get_earliest(self):
        return self.earliest, self.is_earliest_circa

    def get_latest(self):
        return self.latest, self.is_latest_circa


class EcarticoElement:
    structure: "EcarticoStructure"
    is_ignore: bool = False

    def resolve(self, lookup: EcarticoLookupAddInterface):
        pass

    def apply(self, lookup: EcarticoLookupAddInterface, wikidata: cwd.WikiDataPage):
        pass

    def find_year(self, query: FindYear):
        pass


class Marriage(EcarticoElement):
    def __init__(
        self,
        ecartico_id: Optional[str],
        place_id: Optional[str],
        date: Optional[str],
        is_circa: bool,
    ):
        self.ecartico_id = ecartico_id
        self.place_id = place_id
        self.date = date
        self.is_circa = is_circa
        self.spouse_qid = None

    def __repr__(self):
        return f"Marriage(ecartico_id={self.ecartico_id}, place_id={self.place_id}, date={self.date}, circa={self.is_circa})"

    def find_year(self, query: FindYear):
        query.add(construct_date(self.date), self.is_circa)

    def resolve(self, lookup: EcarticoLookupAddInterface):
        self.spouse_qid = lookup.get_person_qid(self.ecartico_id)

    def apply(self, lookup_add: EcarticoLookupAddInterface, wikidata: cwd.WikiDataPage):
        if self.spouse_qid:
            # TODO
            # wikidata.add_statement(cwd.Child(self.qid))
            return

        qids = wikidata.get_qids(wd.PID_SPOUSE)
        if not qids:
            return

        for statement in self.structure.statements:
            if isinstance(statement, Marriage):
                other_qid = statement.spouse_qid
                qids.discard(other_qid)
        if not qids:
            return

        for qid in qids:
            lookup_add.add_is_possible(self.ecartico_id, qid)
        for qid in qids:
            if lookup_add.is_possible(self.ecartico_id, qid):
                raise RuntimeError(f"Spouse {self.ecartico_id} can be {qid}")


class Person(EcarticoElement):
    def __init__(self, ecartico_id: Optional[str] = None, text: Optional[str] = None):
        self.ecartico_id = ecartico_id
        self.text = text
        self.person_qid = None

    def resolve(self, lookup: EcarticoLookupAddInterface):
        self.person_qid = lookup.get_person_qid(self.ecartico_id)

    def __repr__(self):
        return f"{self.__class__.__name__}(ecartico_id={self.ecartico_id}, text='{self.text}')"


class Child(Person):
    def apply(self, lookup: EcarticoLookupAddInterface, wikidata: cwd.WikiDataPage):
        if not self.ecartico_id:
            return
        if self.person_qid:
            wikidata.add_statement(
                cwd.Child(self.person_qid),
                EcarticoReference(self.structure.ecartico_id),
            )
            return

        qids = wikidata.get_qids(wd.PID_CHILD)
        if not qids:
            return

        for statement in self.structure.statements:
            if isinstance(statement, Child):
                other_qid = statement.person_qid
                qids.discard(other_qid)
        if not qids:
            return

        for qid in qids:
            lookup.add_is_possible(self.ecartico_id, qid)
        for qid in qids:
            if lookup.is_possible(self.ecartico_id, qid):
                raise RuntimeError(f"Child {self.ecartico_id} can be {qid}")


class Father(Person):
    def apply(self, lookup: EcarticoLookupAddInterface, wikidata: cwd.WikiDataPage):
        if self.person_qid:
            wikidata.add_statement(
                cwd.Father(self.person_qid),
                EcarticoReference(self.structure.ecartico_id),
            )
        elif wikidata.has_qid(wd.PID_FATHER):
            raise RuntimeError(
                f"Father: {self.ecartico_id} unknown, but wikidata page has father"
            )


class Mother(Person):
    def apply(self, lookup: EcarticoLookupAddInterface, wikidata: cwd.WikiDataPage):
        if self.person_qid:
            wikidata.add_statement(
                cwd.Mother(self.person_qid),
                EcarticoReference(self.structure.ecartico_id),
            )
        elif wikidata.has_qid(wd.PID_MOTHER):
            raise RuntimeError(
                f"Mother: {self.ecartico_id} unknown, but wikidata page has mother"
            )


class Gender(EcarticoElement):
    def __init__(self, text: Optional[str] = None):
        self.text = text
        self.qid = None

    def __repr__(self):
        return f"Gender(text='{self.text}')"

    def resolve(self, lookup: EcarticoLookupAddInterface):
        if self.text == "male":
            self.qid = wd.QID_MALE
        elif self.text == "female":
            self.qid = wd.QID_FEMALE
        elif self.text == "unknown":
            # Q996886
            self.qid = None
        else:
            raise RuntimeError(f"Unexpected gender {self.text}")

    def apply(self, lookup: EcarticoLookupAddInterface, wikidata: cwd.WikiDataPage):
        config = cwd.StatementConfig()
        config.skip_if_strong_refs = True
        wikidata.add_statement(
            cwd.SexOrGender(self.qid, config=config),
            EcarticoReference(self.structure.ecartico_id),
        )


class Patronym(EcarticoElement):
    def __init__(self, text: Optional[str] = None):
        self.text = text

    def __repr__(self):
        return f"Patronym(text='{self.text}')"

    def resolve(self, lookup: EcarticoLookupAddInterface):
        self.qid = lookup.get_patronym_qid(self.text)

    def apply(self, lookup: EcarticoLookupAddInterface, wikidata: cwd.WikiDataPage):
        if self.qid:
            wikidata.add_statement(
                cwd.Patronym(self.qid), EcarticoReference(self.structure.ecartico_id)
            )


class Occupation(EcarticoElement):

    occupation_types = {
        "Occupation": cwd.Occupation,
        "PositionHeld": cwd.PositionHeld,
        "NobleTitle": cwd.NobleTitle,
        "MilitaryRank": cwd.MilitaryOrPoliceRank,
    }

    def __init__(
        self,
        occupation_id: Optional[str],
        start_date: Optional[str],
        end_date: Optional[str],
    ):
        self.occupation_id = occupation_id
        self.start_date = start_date
        self.end_date = end_date
        self.occupation_qid = None

    def __repr__(self):
        return f"{self.__class__.__name__}(occupation_id={self.occupation_id}, start_date='{self.start_date}', end_date='{self.end_date}')"

    def find_year(self, query: FindYear):
        query.add(construct_date(self.start_date))
        query.add(construct_date(self.end_date))

    def resolve(self, lookup: EcarticoLookupAddInterface):
        self.occupation_qid = lookup.get_occupation_qid(self.occupation_id)
        if self.occupation_qid:
            self.occupation_type = lookup.get_occupation_type(self.occupation_qid)

    def has_double(self) -> bool:
        occupations = set()
        for statement in self.structure.statements:
            if isinstance(statement, Occupation):
                qid = statement.occupation_qid
                if qid and qid in occupations:
                    return True
                occupations.add(qid)

        return False

    def apply(self, lookup: EcarticoLookupAddInterface, wikidata: cwd.WikiDataPage):
        if not self.occupation_qid:
            return

        if not self.occupation_type in self.occupation_types:
            return

        if self.has_double():
            raise RuntimeError("Double occupation")

        occupation_class = self.occupation_types[self.occupation_type]
        statement = occupation_class(
            self.occupation_qid,
            start_date=construct_date(self.start_date),
            end_date=construct_date(self.end_date),
        )
        wikidata.add_statement(statement, EcarticoReference(self.structure.ecartico_id))


class OccupationalAddresses(EcarticoElement):
    def __init__(
        self,
        place_id: Optional[str],
        start_date: Optional[str],
        end_date: Optional[str],
    ):
        self.place_id = place_id
        self.start_date = start_date
        self.end_date = end_date
        self.place_qid = None

    def __repr__(self):
        return f"{self.__class__.__name__}(place_id={self.place_id}, start_date='{self.start_date}', end_date='{self.end_date}')"

    def find_year(self, query: FindYear):
        query.add(construct_date(self.start_date))
        query.add(construct_date(self.end_date))

    def ignore_worklocations(self):
        for statement in self.structure.statements:
            if isinstance(statement, OccupationalAddresses):
                statement.is_ignore = True

    def has_double(self) -> bool:
        places = set()
        for statement in self.structure.statements:
            if isinstance(statement, OccupationalAddresses):
                qid = statement.place_qid
                if qid and qid in places:
                    return True
                places.add(qid)

        return False

    def resolve(self, lookup: EcarticoLookupAddInterface):
        self.place_qid = lookup.get_place_qid(self.place_id)

    def apply(self, lookup: EcarticoLookupAddInterface, wikidata: cwd.WikiDataPage):
        if not self.place_qid:
            return

        if self.has_double():
            print("Double worklocation")
            self.ignore_worklocations()
            return

        statement = cwd.WorkLocation(
            self.place_qid, qid_alternative=get_place_alternative(self.place_qid)
        )
        if self.start_date:
            statement.start_date = construct_date(self.start_date)
        if self.end_date:
            statement.end_date = construct_date(self.end_date)
        wikidata.add_statement(statement, EcarticoReference(self.structure.ecartico_id))


class SingleDate(EcarticoElement):
    def __init__(
        self,
        date: Optional[str] = None,
        earliest: Optional[str] = None,
        latest: Optional[str] = None,
        is_circa: bool = False,
        is_baptism_burial: bool = False,
        is_or: bool = False,
    ):
        self.date: Optional[cwd.Date] = construct_date(date)
        self.earliest: Optional[cwd.Date] = construct_date(earliest)
        self.latest: Optional[cwd.Date] = construct_date(latest)
        self.is_circa = is_circa
        self.is_baptism_burial = is_baptism_burial
        self.is_or = is_or

    def __repr__(self):
        return f"{self.__class__.__name__}(date={self.date}, min_date={self.earliest}, max_date={self.latest}, is_circa={self.is_circa}, is_baptism_burial={self.is_baptism_burial}, is_or={self.is_or})"

    def find_year(self, query: FindYear):
        query.add(self.earliest, self.is_circa)
        query.add(self.latest, self.is_circa)
        query.add(self.date, self.is_circa)

    def is_unknown_date(self) -> bool:
        if self.date:
            return False
        if self.earliest and self.latest:
            return False
        if self.earliest:
            return True
        if self.latest:
            return True
        return False

    @abc.abstractmethod
    def get_date_class(self) -> type[cwd.DateStatement]:
        pass

    def apply(self, lookup: EcarticoLookupAddInterface, wikidata: cwd.WikiDataPage):

        if not self.date and self.earliest and self.latest:
            if self.is_or:
                if self.latest.follows(self.earliest):
                    self.is_or = False
                else:
                    raise RuntimeError("Unexpected or date")
            if self.earliest and self.latest:
                if self.earliest.is_1_jan() and self.latest.is_31_dec():
                    self.earliest.change_to_year()
                    self.latest.change_to_year()
                if self.earliest == self.latest:
                    self.date = self.earliest
                    self.earliest = None
                    self.latest = None

        date_class = self.get_date_class()
        if self.date:
            if self.earliest:
                raise RuntimeError("Unexpected date and earliest date")
            if self.latest:
                raise RuntimeError("Unexpected date and latest date")
            statement = date_class(date=self.date, is_circa=self.is_circa)
            if self.get_date_class() == cwd.DateOfBaptism:
                wikidata.remove_references(
                    wd.PID_DATE_OF_BIRTH, EcarticoReference(self.structure.ecartico_id)
                )
                wikidata.deprecate_date(pid=wd.PID_DATE_OF_BIRTH, date=self.date)
            if self.get_date_class() == cwd.DateOfBurialOrCremation:
                wikidata.remove_references(
                    wd.PID_DATE_OF_DEATH, EcarticoReference(self.structure.ecartico_id)
                )
                wikidata.deprecate_date(pid=wd.PID_DATE_OF_DEATH, date=self.date)
        else:
            calc_earliest = self.earliest
            calc_latest = self.latest
            calc_is_circa = self.is_circa
            if not self.earliest or not self.latest:
                query = FindYear()
                for statement in self.structure.statements:
                    if statement != self:
                        statement.find_year(query)
                if query.has_found:
                    if isinstance(self, DateOfDeath):
                        if not self.latest:
                            year, use_circa = query.get_earliest()
                            if not year or use_circa is None:
                                raise RuntimeError("No earliest year found")
                            calc_latest = cwd.Date(year=year + MAX_EXPECTED_LIFE_SPAN)
                        else:
                            year, use_circa = query.get_latest()
                            if not year or use_circa is None:
                                raise RuntimeError("No latest year found")
                            calc_earliest = cwd.Date(year=year)
                        calc_is_circa = calc_is_circa or use_circa
                    elif isinstance(self, DateOfBirth):
                        if not self.latest:
                            year, use_circa = query.get_earliest()
                            if not year or use_circa is None:
                                raise RuntimeError("No earliest year found")
                            calc_latest = cwd.Date(year=year)
                        else:
                            year, use_circa = query.get_latest()
                            if not year or use_circa is None:
                                raise RuntimeError("No latest year found")
                            calc_earliest = cwd.Date(year=year - MAX_EXPECTED_LIFE_SPAN)
                        calc_is_circa = calc_is_circa or use_circa

            middle = cwd.Date.create_middle(
                calc_earliest,
                calc_latest,
                do_strict=not self.earliest or not self.latest,
            )
            print(f"Calculated middle date {middle} for {self}")

            statement = date_class(middle, self.earliest, self.latest, calc_is_circa)
        wikidata.add_statement(statement, EcarticoReference(self.structure.ecartico_id))


class DateOfBirth(SingleDate):

    def resolve(self, lookup: EcarticoLookupAddInterface):
        if not self.structure.config.include_date_of_birth:
            self.is_ignore = True

    def get_date_class(self) -> type[cwd.DateStatement]:
        if self.is_baptism_burial:
            return cwd.DateOfBaptism
        else:
            return cwd.DateOfBirth


class DateOfDeath(SingleDate):
    def resolve(self, lookup: EcarticoLookupAddInterface):
        if not self.structure.config.include_date_of_death:
            self.is_ignore = True

    def get_date_class(self) -> type[cwd.DateStatement]:
        if self.is_baptism_burial:
            return cwd.DateOfBurialOrCremation
        else:
            return cwd.DateOfDeath


def get_place_alternative(qid: str) -> Optional[str]:
    alternatives = {}
    pairs = [
        ("Q803", "Q39297398"),
        ("Q10001", "Q26296883"),  # deventer
        # Add more pairs here
    ]

    for a, b in pairs:
        alternatives[a] = b
        alternatives[b] = a

    return alternatives.get(qid)


class Place(EcarticoElement):
    def __init__(self, place_id: Optional[str] = None):
        self.place_id = place_id

    def __repr__(self):
        return f"{self.__class__.__name__}(place_id={self.place_id})"

    def resolve(self, lookup: EcarticoLookupAddInterface):
        self.place_qid = lookup.get_place_qid(self.place_id)


class PlaceOfBirth(Place):
    def apply(self, lookup: EcarticoLookupAddInterface, wikidata: cwd.WikiDataPage):
        if self.place_qid:
            wikidata.add_statement(
                cwd.PlaceOfBirth(
                    self.place_qid,
                    qid_alternative=get_place_alternative(self.place_qid),
                ),
                EcarticoReference(self.structure.ecartico_id),
            )


class PlaceOfDeath(Place):
    def apply(self, lookup: EcarticoLookupAddInterface, wikidata: cwd.WikiDataPage):
        if self.place_qid:
            wikidata.add_statement(
                cwd.PlaceOfDeath(
                    self.place_qid,
                    qid_alternative=get_place_alternative(self.place_qid),
                ),
                EcarticoReference(self.structure.ecartico_id),
            )


class SubjectOfPainting(EcarticoElement):
    def __init__(self, attribute: Optional[str], value: Optional[str]):
        self.attribute = attribute
        self.value = value
        self.qid = None

    def __repr__(self):
        return (
            f"{self.__class__.__name__}(attribute={self.attribute}, value={self.value})"
        )

    def resolve(self, lookup: EcarticoLookupAddInterface):
        self.qid = lookup.get_genre_qid(self.attribute, self.value)

    def apply(self, lookup: EcarticoLookupAddInterface, wikidata: cwd.WikiDataPage):
        if self.qid:
            wikidata.add_statement(
                cwd.Genre(self.qid), EcarticoReference(self.structure.ecartico_id)
            )


class Attribute(EcarticoElement):
    def __init__(
        self,
        text: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ):
        self.text = text
        self.start_date = construct_date(start_date)
        self.end_date = construct_date(end_date)
        self.qid = None

    def find_year(self, query: FindYear):
        query.add(self.start_date)
        query.add(self.end_date)

    def __repr__(self):
        return f"{self.__class__.__name__}(text={self.text}, start_date={self.start_date}, end_date={self.end_date})"

    def apply(self, lookup: EcarticoLookupAddInterface, wikidata: cwd.WikiDataPage):
        pass


class ReligionDenomination(Attribute):
    def resolve(self, lookup: EcarticoLookupAddInterface):
        self.qid = lookup.get_religion_qid(self.text)

    def apply(self, lookup: EcarticoLookupAddInterface, wikidata: cwd.WikiDataPage):
        if self.qid:
            wikidata.add_statement(
                cwd.ReligionOrWorldview(
                    self.qid,
                    start_date=self.start_date,
                    end_date=self.end_date,
                ),
                EcarticoReference(self.structure.ecartico_id),
            )


class Bentvueghels(Attribute):

    def apply(self, lookup: EcarticoLookupAddInterface, wikidata: cwd.WikiDataPage):
        if self.qid:
            statement = cwd.MemberOf(
                self.qid,
                start_date=self.start_date,
                end_date=self.end_date,
            )
            statement.subject_named_as = self.text
            wikidata.add_statement(
                statement, EcarticoReference(self.structure.ecartico_id)
            )


class Nickname(Attribute):
    def resolve(self, lookup: EcarticoLookupAddInterface):
        raise RuntimeError(f"unexpected Nickname {self.text}")


class PenName(Attribute):
    def resolve(self, lookup: EcarticoLookupAddInterface):
        raise RuntimeError(f"unexpected PenName {self.text}")


class ReligiousName(Attribute):
    def resolve(self, lookup: EcarticoLookupAddInterface):
        raise RuntimeError(f"unexpected ReligiousName {self.text}")


class Pseudonym(Attribute):
    def resolve(self, lookup: EcarticoLookupAddInterface):
        raise RuntimeError(f"unexpected Pseudonym {self.text}")


class Language(Attribute):
    def resolve(self, lookup: EcarticoLookupAddInterface):
        qid_mapping = {
            "Dutch": wd.QID_DUTCH,
            "Frisian": wd.QID_FRISIAN,
            "Latin": wd.QID_LATIN,
            "English": wd.QID_ENGLISH,
            "French": wd.QID_FRENCH,
            "Greek": wd.QID_GREEK,
            "Italian": wd.QID_ITALIAN,
            "German": wd.QID_GERMAN,
        }

        if self.text in qid_mapping:
            self.qid = qid_mapping[self.text]
        else:
            raise RuntimeError(f"unexpected Language {self.text}")

    def apply(self, lookup: EcarticoLookupAddInterface, wikidata: cwd.WikiDataPage):
        if self.qid:
            wikidata.add_statement(
                cwd.LanguagesSpokenWrittenOrSigned(self.qid),
                EcarticoReference(self.structure.ecartico_id),
            )


class PhysicalHandicap(Attribute):
    def resolve(self, lookup: EcarticoLookupAddInterface):
        qid_mapping = {
            "Blindness": wd.QID_BLINDNESS,
            "Deafness": wd.QID_DEAFNESS,
            "Ectrodactyly": wd.QID_ECTRODACTYLY,
            "Dwarfism": wd.QID_DWARFISM,
        }

        if self.text in qid_mapping:
            self.qid = qid_mapping[self.text]
        else:
            raise RuntimeError(f"unexpected PhysicalHandicap {self.text}")

    def apply(self, lookup: EcarticoLookupAddInterface, wikidata: cwd.WikiDataPage):
        if self.qid:
            wikidata.add_statement(
                cwd.MedicalCondition(self.qid),
                EcarticoReference(self.structure.ecartico_id),
            )


class NaturalizedAs(Attribute):
    def resolve(self, lookup: EcarticoLookupAddInterface):
        raise RuntimeError(f"unexpected NaturalizedAs {self.text}")


class PaternityExtramarital(Attribute):
    def resolve(self, lookup: EcarticoLookupAddInterface):
        raise RuntimeError(f"unexpected PaternityExtramarital {self.text}")


class RKDImageID(EcarticoElement):
    def __init__(self, url: Optional[str]):
        self.url = url or ""
        self.qid = None

    def __repr__(self):
        return f"{self.__class__.__name__}(url={self.url})"

    def resolve(self, lookup: EcarticoLookupAddInterface):
        # https://rkd.nl/explore/images/237243
        prefix1 = "http://explore.rkd.nl/explore/images/"
        prefix2 = "https://rkd.nl/explore/images/"
        if self.url.startswith(prefix1):
            id = self.url[len(prefix1) :]
        elif self.url.startswith(prefix2):
            id = self.url[len(prefix2) :]
        else:
            raise RuntimeError(f"Unexpected rkdimage url {self.url}")
        self.qid = lookup.get_rkdimage_qid(id)

    def apply(self, lookup: EcarticoLookupAddInterface, wikidata: cwd.WikiDataPage):
        if self.qid:
            wikidata.add_statement(
                cwd.DepictedBy(self.qid), EcarticoReference(self.structure.ecartico_id)
            )


class Rijksmuseum(EcarticoElement):
    def __init__(self, url: Optional[str]):
        self.url = url or ""
        self.inventory_number = None
        self.qid = None

    def __repr__(self):
        return f"{self.__class__.__name__}(url={self.url})"

    def resolve(self, lookup: EcarticoLookupAddInterface):
        self.qid = lookup.get_rijksmuseum_qid(self.url, self.inventory_number)

    def apply(self, lookup: EcarticoLookupAddInterface, wikidata: cwd.WikiDataPage):
        if self.qid:
            statement = cwd.DepictedBy(self.qid)
            wikidata.add_statement(
                statement, EcarticoReference(self.structure.ecartico_id)
            )


class Gutenberg(EcarticoElement):
    def __init__(
        self, ebook_id: Optional[str], volume: Optional[str], page: Optional[str]
    ):
        self.ebook_id = ebook_id
        self.volume = volume
        self.page = page
        self.qid = None

    def __repr__(self):
        return f"{self.__class__.__name__}(ebook_id={self.ebook_id})"

    def resolve(self, lookup: EcarticoLookupAddInterface):
        self.qid = lookup.get_gutenberg_qid(self.ebook_id)

    def apply(self, lookup: EcarticoLookupAddInterface, wikidata: cwd.WikiDataPage):
        if self.qid:
            statement = cwd.DescribedBySource(self.qid)
            statement.volume = self.volume
            statement.pages = self.page
            wikidata.add_statement(
                statement, EcarticoReference(self.structure.ecartico_id)
            )


class DescribedBySource(EcarticoElement):
    def __init__(
        self,
        source_id: Optional[str],
        book_url: Optional[str],
        volume: Optional[str],
        page: Optional[str],
    ):
        self.source_id = source_id
        self.book_url = book_url
        self.volume = volume
        self.page = page

    def __repr__(self):
        return f"{self.__class__.__name__}(source_id={self.source_id}, book_url={self.book_url}, volume={self.volume}, pagination={self.page})"

    def resolve(self, lookup: EcarticoLookupAddInterface):
        self.source_qid = lookup.get_source_qid(self.source_id)

    def apply(self, lookup: EcarticoLookupAddInterface, wikidata: cwd.WikiDataPage):
        if self.source_qid:
            statement = cwd.DescribedBySource(self.source_qid)
            statement.volume = self.volume
            statement.pages = self.page
            statement.url = self.book_url
            wikidata.add_statement(
                statement, EcarticoReference(self.structure.ecartico_id)
            )


class Relation(EcarticoElement):
    def __init__(
        self,
        ecartico_id: Optional[str],
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ):
        self.ecartico_id = ecartico_id
        self.start_date = construct_date(start_date)
        self.end_date = construct_date(end_date)
        self.person_qid = None

    def __repr__(self):
        return f"{self.__class__.__name__}(ecartico_id={self.ecartico_id}, start_date={self.start_date}, end_date={self.end_date})"

    def find_year(self, query: FindYear):
        query.add(self.start_date)
        query.add(self.end_date)

    def resolve(self, lookup: EcarticoLookupAddInterface):
        self.person_qid = lookup.get_person_qid(self.ecartico_id)

    @abc.abstractmethod
    def get_relation_class(self):
        pass

    def apply(self, lookup: EcarticoLookupAddInterface, wikidata: cwd.WikiDataPage):
        if not self.person_qid:
            return
        relation_class = self.get_relation_class()
        if relation_class is None:
            raise RuntimeError("No relation class")
        statement = relation_class(
            self.person_qid, start_date=self.start_date, end_date=self.end_date
        )
        wikidata.add_statement(statement, EcarticoReference(self.structure.ecartico_id))


class MasterOf(Relation):
    def get_relation_class(self):
        return cwd.MasterOf


class PupilOf(Relation):
    def get_relation_class(self):
        return cwd.StudentOf


def elem_to_circa(elem) -> bool:
    if elem:
        circa = elem.text.strip()
        if not circa:
            return False
        if circa == "circa":
            return True
        raise RuntimeError(f"Unknown circa value {circa}")
    else:
        return False


@dataclass
class EcarticoConfig:
    # include_viaf even if there is already a viaf id in wikidata
    always_include_viaf: bool = False
    include_date_of_birth: bool = True
    include_date_of_death: bool = True


class EcarticoStructure:
    def __init__(
        self,
        qid: Optional[str] = None,
        ecartico_id: Optional[str] = None,
        config: EcarticoConfig = EcarticoConfig(),
    ):
        self.qid = qid
        self.ecartico_id = ecartico_id
        self.names = []
        self.statements: list[EcarticoElement] = []
        self.same_as_urls: list[str] = []
        self.config = config

    def add_statement(self, statement: EcarticoElement):
        statement.structure = self
        self.statements.append(statement)

    def parse(self, soup: BeautifulSoup):

        # Extract the title
        if soup.title is None or soup.title.string is None:
            raise RuntimeError("No title found")
        title = soup.title.string
        print(f"Title: {title}")

        # <h1 property="foaf:name rdfs:label schema:name" lang="">Jacob Savery I</h1>

        # Extract the person's name
        h1 = soup.find("h1", {"property": "foaf:name rdfs:label schema:name"})
        if not h1:
            raise RuntimeError("No h1 name found")
        name = h1.text.strip()
        print(f"Name: {name}")

        # Extract details from the table
        for row in soup.find_all("tr"):
            if not isinstance(row, Tag):
                raise RuntimeError("Unexpected row type")
            cells = row.find_all("td")
            if len(cells) == 2:
                key = cells[0].text.strip().rstrip(":")
                cells1 = cells[1]
                if not isinstance(cells1, Tag):
                    raise RuntimeError("Unexpected cell type")
                value = cells1.text.strip()
                if key == "Name":
                    given_name_elem = cells1.find("span", {"property": "pnv:givenName"})
                    given_name = given_name_elem.text.strip() if given_name_elem else ""

                    patronym_elem = cells1.find("span", {"property": "pnv:patronym"})
                    patronym = patronym_elem.text.strip() if patronym_elem else ""

                    prefix_elem = cells1.find("span", {"property": "pnv:surnamePrefix"})
                    surname_prefix = prefix_elem.text.strip() if prefix_elem else ""

                    surname_elem = cells1.find("span", {"property": "pnv:baseSurname"})
                    surname = surname_elem.text.strip() if surname_elem else ""

                    self.names.append(
                        self.get_name(given_name, patronym, surname_prefix, surname)
                    )
                    if patronym:
                        statement = Patronym(text=patronym)
                        self.add_statement(statement)

                elif key == "Born":
                    url_elem = cells1.find("a", {"rel": "schema:birthPlace"})
                    if url_elem:
                        statement = PlaceOfBirth(
                            place_id=self.extract_place_id_from_url(_get_href(url_elem))
                        )
                        self.add_statement(statement)
                    birthdate_elem = (
                        cells1.find("span", {"id": "birthdate"})
                        or cells1.find("time", {"property": "schema:birthDate"})
                        or cells1.find("time", {"property": "rdf:value"})
                    )
                    if birthdate_elem:
                        if not isinstance(birthdate_elem, Tag):
                            raise RuntimeError("Unexpected birthdate_elem type")
                        if birthdate_elem.name == "span":  # Structured value
                            birth_note = birthdate_elem.find(
                                "span", {"property": "skos:scopeNote"}
                            )

                            # Extract the minimum and maximum values of the dates
                            min_date = birthdate_elem.find(
                                "time",
                                {
                                    "property": "schema:minValue sem:hasEarliestBeginTimeStamp"
                                },
                            )
                            max_date = birthdate_elem.find(
                                "time",
                                {
                                    "property": "schema:maxValue sem:hasLatestEndTimeStamp"
                                },
                            )
                            date = birthdate_elem.find(
                                "time", {"property": "rdf:value"}
                            )
                            is_baptism_burial = (
                                birthdate_elem.find(
                                    "link", {"href": "[ecartico:ProxiedByBaptism]"}
                                )
                                is not None
                            )
                            is_or = False

                            if not min_date and not max_date and not date:
                                # or
                                # Extract the birthdate from <time> tags
                                dates = [
                                    time_tag
                                    for time_tag in birthdate_elem.find_all("time")
                                ]
                                if len(dates) != 2:
                                    raise RuntimeError(
                                        f"Unexpected nr. of dates {len(dates)}"
                                    )

                                min_date = dates[0]
                                max_date = dates[1]
                                is_or = True

                            statement = DateOfBirth(
                                date=date.text.strip() if date else "",
                                earliest=min_date.text.strip() if min_date else "",
                                latest=max_date.text.strip() if max_date else "",
                                is_circa=elem_to_circa(birth_note),
                                is_baptism_burial=is_baptism_burial,
                                is_or=is_or,
                            )
                            self.add_statement(statement)
                        else:  # Direct rdf:value
                            statement = DateOfBirth(date=birthdate_elem.text.strip())
                            self.add_statement(statement)
                elif key == "Died":
                    url_elem = cells1.find("a", {"rel": "schema:deathPlace"})
                    if url_elem:
                        statement = PlaceOfDeath(
                            place_id=self.extract_place_id_from_url(_get_href(url_elem))
                        )
                        self.add_statement(statement)
                    deathdate_elem = (
                        cells1.find("span", {"id": "deathdate"})
                        or cells1.find("time", {"property": "schema:deathDate"})
                        or cells1.find("time", {"property": "rdf:value"})
                    )
                    if deathdate_elem:
                        if not isinstance(deathdate_elem, Tag):
                            raise RuntimeError("Unexpected deathdate_elem type")
                        if deathdate_elem.name == "span":  # Structured value
                            death_note = deathdate_elem.find(
                                "span", {"property": "skos:scopeNote"}
                            )

                            # Extract the minimum and maximum values of the dates
                            min_date = deathdate_elem.find(
                                "time",
                                {
                                    "property": "schema:minValue sem:hasEarliestBeginTimeStamp"
                                },
                            )
                            max_date = deathdate_elem.find(
                                "time",
                                {
                                    "property": "schema:maxValue sem:hasLatestEndTimeStamp"
                                },
                            )
                            date = deathdate_elem.find(
                                "time", {"property": "rdf:value"}
                            )
                            is_baptism_burial = (
                                deathdate_elem.find(
                                    "link", {"href": "[ecartico:ProxiedByBurial]"}
                                )
                                is not None
                            )
                            is_or = False

                            if not min_date and not max_date and not date:
                                # or
                                # Extract the birthdate from <time> tags
                                dates = [
                                    time_tag
                                    for time_tag in deathdate_elem.find_all("time")
                                ]
                                if len(dates) != 2:
                                    raise RuntimeError(
                                        f"Unexpected nr. of dates {len(dates)}"
                                    )

                                min_date = dates[0]
                                max_date = dates[1]
                                is_or = True

                            statement = DateOfDeath(
                                date=date.text.strip() if date else "",
                                earliest=min_date.text.strip() if min_date else "",
                                latest=max_date.text.strip() if max_date else "",
                                is_circa=elem_to_circa(death_note),
                                is_baptism_burial=is_baptism_burial,
                            )
                            self.add_statement(statement)
                        else:  # Direct rdf:value
                            statement = DateOfDeath(date=deathdate_elem.text.strip())
                            self.add_statement(statement)

                elif key == "Father":
                    father_link = cells1.find("a", {"rel": "schema:parent"})
                    if father_link:
                        ecartico_id = self.extract_ecartico_id_from_url(
                            _get_href(father_link)
                        )
                        statement = Father(
                            ecartico_id=ecartico_id, text=father_link.text.strip()
                        )
                        self.add_statement(statement)
                elif key == "Mother":
                    mother_link = cells1.find("a", {"rel": "schema:parent"})
                    if mother_link:
                        ecartico_id = self.extract_ecartico_id_from_url(
                            _get_href(mother_link)
                        )
                        statement = Mother(
                            ecartico_id=ecartico_id, text=mother_link.text.strip()
                        )
                        self.add_statement(statement)
                elif key == "Gender":
                    statement = Gender(text=value)
                    self.add_statement(statement)
                elif key == "Name variants":
                    pass
                    # details['name variants'] = value
                else:
                    raise RuntimeError(f"Unknown key: {key}")

        h2s = soup.find_all("h2")
        for i in range(len(h2s)):
            current_h2 = h2s[i]
            next_h2 = h2s[i + 1] if i + 1 < len(h2s) else None
            current_h2_text = current_h2.text.strip(":")
            if current_h2_text == "Marriages" or current_h2_text == "Marriage":
                self.process_marriage(current_h2)
            elif current_h2_text == "Children" or current_h2_text == "Child":
                self.process_children(current_h2)
            elif current_h2_text == "Occupations" or current_h2_text == "Occupation":
                self.process_occupations(current_h2)
            elif (
                current_h2_text == "Occupational addresses"
                or current_h2_text == "Occupational address"
            ):
                self.process_occupational_addresses(current_h2)
            elif current_h2_text == "Attributes":
                tbodies = self.find_tbodies(current_h2, next_h2)
                self.process_attributes(tbodies)
            elif current_h2_text == "Relations":
                tbodies = self.find_tbodies(current_h2, next_h2)
                self.process_relations(tbodies)
            elif current_h2_text == "References":
                self.process_references(current_h2)
            elif current_h2_text == "Network tools":
                pass
            elif current_h2_text == "Metadata":
                pass
            else:
                raise RuntimeError(f"Unrecognized h2: {current_h2_text}")

    def process_marriage(self, h2):
        marriage_list = h2.find_next("ul")
        for li in marriage_list.find_all("li"):
            spouse_elem = li.find("a", {"rel": "schema:spouse"})
            if spouse_elem:
                spouse_url = _get_href(spouse_elem)
            else:
                spouse_url = None
            place_elem = li.find("a", {"rel": "bio:place"})
            if place_elem:
                place_url = _get_href(place_elem)
            else:
                place_url = None

            date_time = li.find("time", {"property": "rdf:value"}) or li.find(
                "time", {"property": "time:hasTime"}
            )
            if date_time:
                marriage_date = date_time.text.strip()
            else:
                marriage_date = None

            circa_span = li.find("span", {"property": "skos:scopeNote"})

            statement = Marriage(
                ecartico_id=self.extract_ecartico_id_from_url(spouse_url),
                place_id=self.extract_place_id_from_url(place_url),
                date=marriage_date,
                is_circa=elem_to_circa(circa_span),
            )
            self.add_statement(statement)

    def process_children(self, h2):
        children_list = h2.find_next("ul")
        for li in children_list.find_all("li"):
            child_url = _get_href(li.find("a", {"rel": "schema:children"}))
            child_text = li.text.strip()
            statement = Child(
                ecartico_id=self.extract_ecartico_id_from_url(child_url),
                text=child_text,
            )
            self.add_statement(statement)

    def process_occupations(self, h2):
        occupations_list = h2.find_next("ul")
        for li in occupations_list.find_all("span", {"typeof": "schema:Role"}):
            occupation_url = _get_href(li.find("a", {"rel": "schema:hasOccupation"}))
            start_date = (
                li.find("time", {"property": "schema:startDate"}).text.strip()
                if li.find("time", {"property": "schema:startDate"})
                else None
            )
            end_date = (
                li.find("time", {"property": "schema:endDate"}).text.strip()
                if li.find("time", {"property": "schema:endDate"})
                else None
            )
            statement = Occupation(
                occupation_id=self.extract_occupation_id_from_url(occupation_url),
                start_date=start_date,
                end_date=end_date,
            )
            self.add_statement(statement)

    def process_occupational_addresses(self, h2):
        occupational_addresses_list = h2.find_next("ul")
        for li in occupational_addresses_list.find_all(
            "span", {"typeof": "schema:Role"}
        ):
            address_url = _get_href(li.find("a", {"rel": "schema:workLocation"}))
            start_date = (
                li.find("time", {"property": "schema:startDate"}).text.strip()
                if li.find("time", {"property": "schema:startDate"})
                else None
            )
            end_date = (
                li.find("time", {"property": "schema:endDate"}).text.strip()
                if li.find("time", {"property": "schema:endDate"})
                else None
            )
            statement = OccupationalAddresses(
                place_id=self.extract_place_id_from_url(address_url),
                start_date=start_date,
                end_date=end_date,
            )
            self.add_statement(statement)

    def find_tbodies(self, first_header, second_header):

        # Initialize a list to store all <tbody> elements between the two headers
        tbodies_between = []

        # Iterate through all elements between the two headers
        current_element = first_header.find_next_sibling()
        while current_element and current_element != second_header:
            if current_element.name == "tbody":
                tbodies_between.append(current_element)
            else:
                for tbody in current_element.find_all("tbody"):
                    tbodies_between.append(tbody)
            current_element = current_element.find_next_sibling()

        return tbodies_between

    def process_attributes(self, tbodies):

        # Extract data from the table
        attributes = []

        for tbody in tbodies:
            for row in tbody.find_all("tr"):
                tds = row.find_all("td")
                if not tds:
                    continue
                category = (
                    tds[0].text.strip()
                    if len(tds) > 0 and tds[0].text.strip()
                    else None
                )
                attribute_str = (
                    tds[1].text.strip()
                    if len(tds) > 1 and tds[1].text.strip()
                    else None
                )
                value = (
                    tds[2].text.strip()
                    if len(tds) > 2 and tds[2].text.strip()
                    else None
                )
                start_date = (
                    tds[3].text.strip()
                    if len(tds) > 3 and tds[3].text.strip()
                    else None
                )
                end_date = (
                    tds[4].text.strip()
                    if len(tds) > 4 and tds[4].text.strip()
                    else None
                )
                attribute = {
                    "category": category,
                    "attribute": attribute_str,
                    "value": value,
                    "start_date": start_date,
                    "end_date": end_date,
                }
                attributes.append(attribute)

                if category == "Subject of painting":
                    if start_date:
                        raise RuntimeError("Unexpected start_date {start_date}")
                    if end_date:
                        raise RuntimeError("Unexpected end_date {end_date}")
                    statement = SubjectOfPainting(attribute=attribute_str, value=value)
                    self.add_statement(statement)
                elif category == "Religion" and attribute_str == "Denomination":
                    statement = ReligionDenomination(
                        text=value, start_date=start_date, end_date=end_date
                    )
                    self.add_statement(statement)
                elif (
                    category == "Religion"
                    and attribute_str == "executed for religious convictions"
                ):
                    # 17269
                    # todo
                    pass
                elif category == "Identity" and attribute_str == "Motto":
                    pass
                elif category == "Identity" and attribute_str == "Incorrect name":
                    pass
                elif (
                    category == "Identity"
                    and attribute_str == "Nickname (Bentvueghels)"
                ):
                    statement = Bentvueghels(
                        text=value, start_date=start_date, end_date=end_date
                    )
                    self.add_statement(statement)
                elif category == "Identity" and attribute_str == "Nickname (general)":
                    statement = Nickname(
                        text=value, start_date=start_date, end_date=end_date
                    )
                    self.add_statement(statement)
                elif category == "Identity" and attribute_str == "Pen name":
                    statement = PenName(
                        text=value, start_date=start_date, end_date=end_date
                    )
                    self.add_statement(statement)
                elif (
                    category == "Identity"
                    and attribute_str == "Pseudonym (printing/publishing)"
                ):
                    statement = Pseudonym(
                        text=value, start_date=start_date, end_date=end_date
                    )
                    self.add_statement(statement)
                elif category == "Identity" and attribute_str == "Religious name":
                    statement = ReligiousName(
                        text=value, start_date=start_date, end_date=end_date
                    )
                    self.add_statement(statement)
                elif (category == "Language" and attribute_str == "Poetry") or (
                    category == "Language" and attribute_str == "Drama"
                ):
                    # if not value in ('Dutch', 'Latin', 'Greek', 'French', 'Italian', 'German', 'Spanish', 'English', 'Frisian'):
                    statement = Language(
                        text=value, start_date=start_date, end_date=end_date
                    )
                    self.add_statement(statement)
                elif category == "Membership chamber of rethorics":
                    pass
                elif category == "Medical" and attribute_str == "Physical handicap":
                    statement = PhysicalHandicap(
                        text=value, start_date=start_date, end_date=end_date
                    )
                    self.add_statement(statement)
                    # if not value in ('Blindness', 'Deafness', 'Ectrodactyly', 'Dwarfism'):
                elif category == "Wealth" and attribute_str == "Gross wealth":
                    pass
                elif category == "Wealth" and attribute_str == "Net wealth":
                    pass
                elif (
                    category == "Wealth" and attribute_str == "Insolvency / bankruptcy"
                ):
                    pass
                elif category == "Wealth" and attribute_str == "housing tenure":
                    pass
                elif category == "Wealth" and attribute_str == "Yearly income":
                    pass
                elif category == "Citizenship" and attribute_str == "naturalized as":
                    # 2712 - French citizen
                    # if not value in ('French citizen', 'English citizen'):
                    #    raise RuntimeError(f"Citizenship - naturalized as: {value}")
                    statement = NaturalizedAs(
                        text=value, start_date=start_date, end_date=end_date
                    )
                    self.add_statement(statement)
                elif category == "Kinship" and attribute_str == "Paternity":
                    # 488 - Extramarital
                    # if not value in ('Extramarital'):
                    #    raise RuntimeError(f"Kinship - Paternity: {value}")
                    statement = PaternityExtramarital(
                        text=value, start_date=start_date, end_date=end_date
                    )
                    self.add_statement(statement)
                elif category == "Kinship" and attribute_str == "Filiation":
                    pass
                elif (
                    category == "Tax Assessment"
                    and attribute_str == "100e en 5e penning, Antwerp 1584/1585"
                ):
                    pass
                else:
                    raise RuntimeError(
                        f"Unknown category: {category} - {attribute_str}"
                    )

        # Print extracted attributes
        for attribute in attributes:
            print(attribute)

    def process_relations(self, tbodies):
        # Initialize a list to store the extracted data
        relationship_data = []

        # Define mapping of relation types to their corresponding actions
        relation_actions = {
            "masterOf": MasterOf,
            "pupilOf": PupilOf,
            # Add other relationship classes if needed
        }

        for tbody in tbodies:
            if "rel" in tbody.attrs:
                # Extract data for all relationships found
                relationship = tbody["rel"]
                type_str = relationship.split(":")[
                    -1
                ]  # Extract the specific relationship type
                if not type_str:
                    # professor of
                    continue

                for row in tbody.find_all("tr"):
                    person_url = _get_href(row.find("a", {"rel": relationship}))
                    certainty = (
                        row.find("span", {"rel": "skos:note"}).text.strip()
                        if row.find("span", {"rel": "skos:note"})
                        else None
                    )
                    start_date = (
                        row.find("time", {"property": "schema:startDate"}).text.strip()
                        if row.find("time", {"property": "schema:startDate"})
                        else None
                    )
                    end_date = (
                        row.find("time", {"property": "schema:endDate"}).text.strip()
                        if row.find("time", {"property": "schema:endDate"})
                        else None
                    )

                    relationship_info = {
                        "type": type_str,
                        "person_url": person_url,
                        "certainty": certainty,
                        "start_date": start_date,
                        "end_date": end_date,
                    }
                    relationship_data.append(relationship_info)

                    # Process relationships based on their type
                    if type_str in relation_actions:
                        if certainty == "certain":
                            statement = relation_actions[type_str](
                                ecartico_id=self.extract_ecartico_id_from_url(
                                    person_url
                                ),
                                start_date=start_date,
                                end_date=end_date,
                            )
                            self.add_statement(statement)
                    elif type_str == "divorcedFrom":
                        pass
                    elif type_str in {
                        "collaboratedWith",
                        "tennantOf",
                        "portrayed",
                        "portrayedBy",
                        "workedUnderCommissionFor",
                        "businessConflictWith",
                        "businessRelationWith",
                        "contributedToAlbumAmicorumOf",
                        "principalOf",
                        "domesticEmployerOf",
                        "sellsOrLeavesStockTo",
                        "assistedAtMarriage",
                        "assistedAtMarriageBy",
                        "attendedFuneralOf",
                        "baptismWitnessedBy",
                        "bequestsTo",
                        "commissionedWorksOfArtBy",
                        "courtlyClientOf",
                        "differentFrom",
                        "employeeOf",
                        "employerOf",
                        "legalGuardianOf",
                        "lodgerOf",
                        "sharedHouseWith",
                        "soldHouseTo",
                        "standSuretyFor",
                        "travellingCompanionOf",
                        "wardOf",
                        "willWitnessedBy",
                        "witnessedBaptismOf",
                        "agentFor",
                        "boughtHouseFrom",
                        "boughtPaintingsFrom",
                        "businessPartnerOf",
                        "buysOrInheritsStockFrom",
                        "buysTypographicalMaterialFrom",
                        "courtlyClientOf",
                        "courtlyPatronOf",
                        "domesticServantOf",
                        "executorFor",
                        "funeralAttendedBy",
                        "heirOf",
                        "isAssuredBy",
                        "landlordOf",
                        "nominatesAsExecutor",
                        "posedAsModelFor",
                        "predecessorOf",
                        "receivedContributionInAlbumAmicorumFrom",
                        "residentialLandlordOf",
                        "soldPaintingsTo",
                        "successorOf",
                        "usedAsModel",
                        "witnessedWillOf",
                        "buysPrintingPressFrom",
                        "sellsPrintingPressTo",
                        "sellsTypographicalMaterialTo",
                    }:

                        pass
                    else:
                        raise RuntimeError(f"Unrecognized relation {type_str}")

        # Print extracted data
        for entry in relationship_data:
            print(entry)

    def process_external_records(self, h3):
        reference_list = h3.find_next("ul")
        for link in reference_list.find_all(["a"], {"rel": "owl:sameAs schema:sameAs"}):
            href = _get_href(link)
            if href:
                self.same_as_urls.append(href)
        for link in reference_list.find_all(
            ["li"], {"property": "owl:sameAs schema:sameAs"}
        ):
            resource = link.get("resource")
            if resource:
                self.same_as_urls.append(resource)

    def process_primary_sources(self, h3):
        pass

    def process_secondary_sources(self, h3):
        reference_list = h3.find_next("ol")
        for li in reference_list.find_all("li"):
            source_url = None
            book_url = None
            volume = None
            pagination = None
            # Find the 'link' tag with the ecartico.org URL
            link_tag = li.find("link", href=lambda x: x and "ecartico.org/sources" in x)
            if link_tag:
                source_url = link_tag["href"]

            # Find the 'a' tag with the book URL
            a_tag = li.find("a", rel="schema:url") or li.find("a")
            if a_tag:
                book_url = a_tag["href"]

            volume_span = li.find("span", attrs={"property": "schema:volumeNumber"})
            if volume_span:
                volume = volume_span.text.strip()

            pagination_span = li.find("span", property="schema:pagination")
            if pagination_span:
                pagination = pagination_span.text.strip()

            if source_url or book_url:
                if book_url:
                    match = re.search(
                        r"^https?:\/\/www\.gutenberg\.org\/ebooks\/(\d+)$",
                        book_url,
                        re.IGNORECASE,
                    )
                    if match:
                        ebook_id = match.group(1)
                        statement = Gutenberg(ebook_id, volume, pagination)
                        self.add_statement(statement)
                        continue

                source_id = self.extract_source_id_from_url(source_url)
                if (source_id == SOURCE_RKD_IMAGES) or (
                    source_id == SOURCE_RKD_PORTRAITS
                ):
                    statement = RKDImageID(book_url)
                    self.add_statement(statement)
                elif source_id == SOURCE_RIJKSMUSEUM_AMSTERDAM:
                    # todo; include inventory nr
                    statement = Rijksmuseum(book_url)
                    self.add_statement(statement)
                elif source_id == SOURCE_LE_DICTIONNAIRE_DES_PEINTRES_BELGES:
                    # balat.kikirpa.be
                    if not book_url:
                        raise RuntimeError("No book url")
                    self.same_as_urls.append(book_url)
                else:
                    statement = DescribedBySource(
                        source_id, book_url, volume, pagination
                    )
                    self.add_statement(statement)

    def process_references(self, h2):
        # Extract URLs with rel="owl:sameAs schema:sameAs" or property="owl:sameAs schema:sameAs"

        for (
            sibling
        ) in (
            h2.find_all_next()
        ):  # Check if the sibling is an h3 tag with the specified text
            if sibling.name == "h3":
                if sibling.text == "External biographical records":
                    self.process_external_records(sibling)
                elif sibling.text == "Primary sources":
                    self.process_secondary_sources(sibling)
                elif sibling.text == "Secondary sources":
                    self.process_secondary_sources(sibling)
                else:
                    raise RuntimeError(f"Unexpected h3: {sibling.text}")

            elif sibling.name == "h2":
                break

    def get_name(
        self, given_name: str, patronym: str, surname_prefix: str, surname: str
    ) -> str:
        parts = [
            given_name.strip(),
            patronym.strip(),
            surname_prefix.strip(),
            surname.strip(),
        ]
        # If surname prefix ends with an apostrophe, combine it directly with the surname
        if surname_prefix.strip().endswith("'"):
            parts[-2:] = [surname_prefix.strip() + surname.strip()]
        name = " ".join(part for part in parts if part)
        if "#" in name or "&" in name or "%" in name:
            raise RuntimeError(f"Invalid character in name: {name}")
        return name

    def print(self):
        for name in self.names:
            print(f"name: {name}")
        for url in self.same_as_urls:
            print(f"same as: {url}")
        for statement in self.statements:
            print(statement)

    def geturl_prop_id(self, url: str):
        if url.startswith("http://www.wikidata.org/entity/"):
            return None

        prefix = "https://id.rijksmuseum.nl/310"
        if url.startswith(prefix):
            prop = wd.PID_RIJKSMUSEUM_RESEARCH_LIBRARY_AUTHORITY_ID
            external_id = url[len(prefix) :]
            return prop, external_id

        prefix = "http://viaf.org/viaf/"
        if url.startswith(prefix):
            prop = wd.PID_VIAF_CLUSTER_ID
            external_id = url[len(prefix) :]
            return prop, external_id

        prefix = "http://vocab.getty.edu/page/ulan/"
        if url.startswith(prefix):
            prop = wd.PID_UNION_LIST_OF_ARTIST_NAMES_ID
            external_id = url[len(prefix) :]
            return prop, external_id

        prefix = "http://www.biografischportaal.nl/persoon/"
        if url.startswith(prefix):
            prop = wd.PID_BIOGRAFISCH_PORTAAL_VAN_NEDERLAND_ID
            external_id = url[len(prefix) :]
            return prop, external_id

        prefix = "https://rkd.nl/artists/"
        if url.startswith(prefix):
            prop = wd.PID_RKDARTISTS_ID
            external_id = url[len(prefix) :]
            return prop, external_id

        prefix = "http://data.bibliotheken.nl/id/dbnla/"
        if url.startswith(prefix):
            prop = wd.PID_DIGITALE_BIBLIOTHEEK_VOOR_DE_NEDERLANDSE_LETTEREN_AUTHOR_ID
            external_id = url[len(prefix) :]
            return prop, external_id

        prefix = "http://balat.kikirpa.be/peintres/Detail_notice.php?id="
        if url.startswith(prefix):
            prop = wd.PID_DICTIONNAIRE_DES_PEINTRES_BELGES_ID
            external_id = url[len(prefix) :]
            return prop, external_id

        prefix = "http://ta.sandrart.net/-person-"
        if url.startswith(prefix):
            prop = wd.PID_SANDRARTNET_PERSON_ID
            external_id = url[len(prefix) :]
            return prop, external_id

        prefix = "http://data.bibliotheken.nl/id/thes/p"
        if url.startswith(prefix):
            prop = wd.PID_NATIONALE_THESAURUS_VOOR_AUTEURSNAMEN_ID
            external_id = url[len(prefix) :]
            return prop, external_id

        if "data.deutsche-biographie.de/Person/" in url:
            raise RuntimeError("url = data.deutsche-biographie.de/Person/")
        if "urn:rijksmuseum:people" in url:
            return None

        raise RuntimeError(f"unrecognized url: {url}")

    def apply(self, lookup: EcarticoLookupAddInterface, wikidata: cwd.WikiDataPage):
        if has_rkd_work_location(wikidata.claims):
            for statement in self.statements:
                if isinstance(statement, OccupationalAddresses):
                    statement.is_ignore = True

        for name in self.names:
            wikidata.add_statement(cwd.Label(name, language="nl"), reference=None)
        for statement in self.statements:
            statement.resolve(lookup)
        for statement in self.statements:
            if not statement.is_ignore:
                statement.apply(lookup, wikidata)
        ids = {}
        for url in self.same_as_urls:
            t = self.geturl_prop_id(url)
            if t:
                prop, external_id = t
                if not prop in ids:
                    ids[prop] = []
                if external_id not in ids[prop]:
                    ids[prop].append(external_id)
        for prop in ids:
            if prop == wd.PID_VIAF_CLUSTER_ID:
                # ignore VIAF if already added; contains redirects
                if (
                    not self.config.always_include_viaf
                    and wd.PID_VIAF_CLUSTER_ID in wikidata.claims
                ):
                    continue
            if prop == wd.PID_BIOGRAFISCH_PORTAAL_VAN_NEDERLAND_ID:
                if len(ids[prop]) > 1:
                    pages = []
                    for external_id in ids[prop]:
                        page = external_pages.PageFactory.create_page(prop, external_id)
                        page.load()
                        if not page.is_redirect():
                            pages.append(page)

                    for page in pages:
                        wikidata.add_statement(
                            cwd.ExternalIDStatement(
                                prop=prop,
                                external_id=external_id,
                                subject_named_as=(
                                    page.get_name() if len(pages) > 1 else None
                                ),
                            ),
                            EcarticoReference(self.ecartico_id),
                        )
                    continue

            for external_id in ids[prop]:
                wikidata.add_statement(
                    cwd.ExternalIDStatement(prop=prop, external_id=external_id),
                    EcarticoReference(self.ecartico_id),
                )

        # wikidata.print()
        wikidata.summary = "from ecartico.org"
        wikidata.apply()

    def extract_ecartico_id_from_url(self, url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        prefix = "../persons/"
        if not url.startswith(prefix):
            raise RuntimeError(f"unrecognized person url: {url}")

        ecartico_id = url[len(prefix) :]
        return ecartico_id

    def extract_place_id_from_url(self, url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        prefix = "../places/"
        if not url.startswith(prefix):
            raise RuntimeError(f"unrecognized place url: {url}")

        place_id = url[len(prefix) :]
        return place_id

    def extract_occupation_id_from_url(self, url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        prefix = "../occupations/"
        if not url.startswith(prefix):
            raise RuntimeError(f"unrecognized occupation url: {url}")

        occupation_id = url[len(prefix) :]
        return occupation_id

    def extract_source_id_from_url(self, url: Optional[str]) -> Optional[str]:
        if not url:
            return None
        prefix = "https://ecartico.org/sources/"
        if not url.startswith(prefix):
            raise RuntimeError(f"unrecognized source url: {url}")

        source_id = url[len(prefix) :]
        return source_id
