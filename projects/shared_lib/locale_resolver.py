from collections import defaultdict
from typing import Optional

import shared_lib.constants as wd
from shared_lib.lookups.interfaces.place_lookup_interface import PlaceLookupInterface


class LocaleResolver:
    def __init__(self, place_lookup: PlaceLookupInterface):
        self.place_lookup = place_lookup
        self.birth_country_qids = set()
        self.death_country_qids = set()
        self.country_qids = set()
        self.country_config = None

    def load_from_claims(self, claims: dict):
        """
        Load country information from Wikidata claims.
        """
        if wd.PID_PLACE_OF_BIRTH in claims:
            for claim in claims[wd.PID_PLACE_OF_BIRTH]:
                if claim.rank == "deprecated":
                    continue
                target = claim.getTarget()
                if target:
                    place_qid = target.id
                    self.add_place_of_birth(place_qid)

        if wd.PID_PLACE_OF_DEATH in claims:
            for claim in claims[wd.PID_PLACE_OF_DEATH]:
                if claim.rank == "deprecated":
                    continue
                target = claim.getTarget()
                if target:
                    place_qid = target.id
                    self.add_place_of_death(place_qid)

        # Countries of citizenship (P27)
        if wd.PID_COUNTRY_OF_CITIZENSHIP in claims:
            for claim in claims[wd.PID_COUNTRY_OF_CITIZENSHIP]:
                if claim.rank == "deprecated":
                    continue
                target = claim.getTarget()
                if target:
                    country_qid = target.id
                    self.add_country(country_qid)

        if wd.PID_RESIDENCE in claims:
            for claim in claims[wd.PID_RESIDENCE]:
                if claim.rank == "deprecated":
                    continue
                target = claim.getTarget()
                if target:
                    country_qid = target.id
                    self.add_country(country_qid)

    def add_place_of_birth(self, place_qid: str):
        data = self.place_lookup.get_place_by_qid(place_qid)
        if not data:
            raise RuntimeError(f"Country QID not found for place of birth {place_qid}")
        place_qid, country_qid, place_label = data
        self.birth_country_qids.add(country_qid)
        self.country_qids.add(country_qid)

    def add_place_of_death(self, place_qid: str):
        data = self.place_lookup.get_place_by_qid(place_qid)
        if not data:
            raise RuntimeError(f"Country QID not found for place of death {place_qid}")
        place_qid, country_qid, place_label = data
        self.death_country_qids.add(country_qid)
        self.country_qids.add(country_qid)

    def add_place(self, place_qid: str):
        data = self.place_lookup.get_place_by_qid(place_qid)
        if not data:
            raise RuntimeError(f"Country QID not found for place {place_qid}")
        place_qid, country_qid, place_label = data
        self.country_qids.add(country_qid)

    def add_country(self, country_qid: str):
        self.country_qids.add(country_qid)

    def get_country(self) -> Optional[str]:
        sorted_countries = self.get_weighted_countries()
        if sorted_countries:
            return sorted_countries[0]
        else:
            return None

    def get_weighted_countries(self):
        weights = {
            3: self.birth_country_qids,
            2: self.death_country_qids,
            1: self.country_qids,
        }

        country_scores = defaultdict(int)

        for weight, qid_set in weights.items():
            for country_qid in qid_set:
                country_scores[country_qid] += weight

        # Sort by score descending and return only the QIDs
        sorted_country_qids = [
            qid for qid, _ in sorted(country_scores.items(), key=lambda x: -x[1])
        ]
        return sorted_country_qids

    def resolve(self) -> Optional[str]:
        country_qid = self.get_country()
        return country_qid

    # def get_weighted_languages(self):
    #     weights = {
    #         3: self.birth_country_qids,
    #         2: self.death_country_qids,
    #         1: self.country_qids,
    #     }

    #     language_scores = defaultdict(int)

    #     for weight, qid_set in weights.items():
    #         for country_qid in qid_set:
    #             langs = self.place_lookup.get_languages_for_country(country_qid)
    #             if not langs:
    #                 self.place_lookup.ensure_country_info(qid=country_qid)

    #                 raise RuntimeError(
    #                     f"No languages found for country QID {country_qid} in item {self.item.id}"
    #                 )
    #             for lang_qid in langs:
    #                 language_scores[lang_qid] += weight

    #     # Sort by score descending
    #     sorted_language_qids = [
    #         lang for lang, _ in sorted(language_scores.items(), key=lambda x: -x[1])
    #     ]
    #     return sorted_language_qids
