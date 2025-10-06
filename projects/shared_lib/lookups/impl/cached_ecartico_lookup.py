import re
from typing import Optional

import shared_lib.constants as wd
from shared_lib.lookups.interfaces.ecartico_lookup_interface import (
    EcarticoLookupAddInterface,
    EcarticoLookupInterface,
)

SKIP = "SKIP"
LEEG = "LEEG"
MULTIPLE = "MULTIPLE"


class CachedEcarticoLookup(EcarticoLookupAddInterface):
    def __init__(
        self,
        cache: EcarticoLookupAddInterface,
        ecartico_source: EcarticoLookupInterface,
        wikidata_source: EcarticoLookupInterface,
    ) -> None:
        self.cache = cache
        self.ecartico_source = ecartico_source
        self.wikidata_source = wikidata_source

    def get_occupation(self, occupation_id: str) -> Optional[tuple[str, str]]:
        t = self.cache.get_occupation(occupation_id)
        if not t:
            t = self.ecartico_source.get_occupation(occupation_id)
            if t:
                qid, description = t
            else:
                qid = LEEG
                description = ""
            self.cache.add_occupation(occupation_id, description, qid)
        else:
            qid, description = t

        if qid == SKIP:
            return None
        if qid and qid.startswith("Q"):
            return qid, description

        raise RuntimeError(
            f"unrecognized occupation: {occupation_id} {description} -> {qid}"
        )

    def get_patronym_qid(self, text: str) -> Optional[str]:
        qid = self.cache.get_patronym_qid(text)
        if not qid:
            qid = LEEG
            self.cache.add_patronym(text, qid)

        if qid == SKIP:
            return None
        if qid and qid.startswith("Q"):
            return qid

        raise RuntimeError(f"unrecognized patronym: {text} -> {qid}")

    def get_place(self, place_id: str) -> Optional[tuple[str, str]]:
        t = self.cache.get_place(place_id)
        if t:
            qid, description = t
        else:
            t = self.ecartico_source.get_place(place_id)
            if t:
                qid, description = t
            else:
                qid = LEEG
                description = ""
            self.cache.add_place(place_id, description, qid)

        if qid == SKIP:
            return None
        if qid and qid.startswith("Q"):
            return qid, description

        raise RuntimeError(f"unrecognized place: {place_id} {description}-> {qid}")

    def get_religion_qid(self, text: str) -> Optional[str]:
        qid = self.cache.get_religion_qid(text)
        if not qid:
            qid = LEEG
            self.cache.add_religion(text, qid)

        if qid == SKIP:
            return None
        if qid and qid.startswith("Q"):
            return qid

        raise RuntimeError(f"unrecognized religion: {text} -> {qid}")

    def get_rkdimage_qid(self, rkdimage_id: str) -> Optional[str]:
        qid = self.cache.get_rkdimage_qid(rkdimage_id)
        if not qid:
            # load
            qid = self.wikidata_source.get_rkdimage_qid(rkdimage_id)
            # qid = self.get_qids_from_rkdimage_id(rkdimage_id)
            # if len(qids) > 1:
            #     qid = MULTIPLE
            # elif not qids:
            #     qid = SKIP
            # else:
            #     qid = qids[0]
            if not qid:
                qid = SKIP
            self.cache.add_rkdimage_qid(rkdimage_id, qid)

        if qid == SKIP:
            return None
        if qid and qid.startswith("Q"):
            return qid

        raise RuntimeError(f"unrecognized rkdimage: {rkdimage_id} -> {qid}")

    def get_source(self, source_id: str) -> Optional[tuple[str, str]]:
        t = self.cache.get_source(source_id)
        if t:
            qid, description = t
        else:
            # load
            t = self.ecartico_source.get_source(source_id)
            if t:
                qid, description = t
            else:
                qid = LEEG
                description = ""
            self.cache.add_source(source_id, description, qid)

        if qid == SKIP:
            return None
        if qid and qid.startswith("Q"):
            return qid, description

        # todo; tijdelijk
        return None
        raise RuntimeError(f"unrecognized source: {source_id}-{description} -> {qid}")

    def get_genre_qid(self, attribute: str, value: str) -> Optional[str]:
        qid = self.cache.get_genre_qid(attribute, value)

        if not qid:
            qid = LEEG
            self.cache.add_genre(attribute, value, qid)

        if qid == SKIP:
            return None
        if qid and qid.startswith("Q"):
            return qid

        raise RuntimeError(f"unrecognized genre: {attribute} {value} -> {qid}")

    def add_genre(self, attribute: str, value: str, qid: str) -> None:
        self.cache.add_genre(attribute, value, qid)

    def add_gutenberg_ebook_id_qid(self, ebook_id: str, qid: str) -> None:
        self.cache.add_gutenberg_ebook_id_qid(ebook_id, qid)

    def add_is_possible(self, ecartico_id: Optional[str], qid: str):
        self.cache.add_is_possible(ecartico_id, qid)

    def add_occupation(self, occupation_id, description: str, qid: str):
        self.cache.add_occupation(occupation_id, description, qid)

    def add_occupation_type(self, qid: str, description: str, text: str) -> None:
        self.cache.add_occupation_type(qid, description, text)

    def add_patronym(self, text: str, qid: str) -> None:
        self.cache.add_patronym(text, qid)

    def add_person(
        self, ecartico_id: Optional[str], description: Optional[str], qid: Optional[str]
    ):
        self.cache.add_person(ecartico_id, description, qid)

    def add_place(self, place_id: str, description: str, qid: str):
        self.cache.add_place(place_id, description, qid)

    def add_religion(self, religion: str, qid: str) -> None:
        self.cache.add_religion(religion, qid)

    def add_rijksmuseum_qid(self, inventory_number: str, qid: str) -> None:
        self.cache.add_rijksmuseum_qid(inventory_number, qid)

    def add_rkdimage_qid(self, rkdimage_id: str, qid: str) -> None:
        self.cache.add_rkdimage_qid(rkdimage_id, qid)

    def add_source(self, source_id: str, description: str, qid: str):
        self.cache.add_source(source_id, description, qid)

    def get_person(self, ecartico_id: str) -> Optional[tuple[str, str]]:
        t = self.cache.get_person(ecartico_id)
        if t:
            qid, description = t
        else:
            t = self.ecartico_source.get_person(ecartico_id)
            if t:
                qid, description = t
                if qid and qid.startswith("Q"):
                    self.cache.add_person(ecartico_id, description, qid)
                    return qid, description

            t = self.wikidata_source.get_person(ecartico_id)
            if t:
                qid, description = t
                if qid and qid.startswith("Q"):
                    self.cache.add_person(ecartico_id, description, qid)
                    return qid, description

        if qid == SKIP:
            return None
        if qid and qid.startswith("Q"):
            return qid, description

        raise RuntimeError(f"unrecognized person: {ecartico_id} {description} -> {qid}")

    # def get_person_qid(self, ecartico_id: Optional[str]) -> Optional[str]:
    #     qid = self.cache.get_person_qid(ecartico_id)
    #     if not qid:

    #         # load from ecartico
    #         complete_url = f"https://ecartico.org/persons/{ecartico_id}"
    #         qid, description = self.extract_qid_from_ecartico_page(complete_url)
    #         if qid and qid.startswith("Q"):
    #             self.cache.add_person(ecartico_id, description, qid)
    #             return qid

    #         # load from wikidata
    #         qids = self.get_qids_from_ecartico_id(ecartico_id)
    #         if len(qids) > 1:
    #             qid = MULTIPLE
    #         elif not qids:
    #             qid = SKIP
    #         else:
    #             qid = qids[0]
    #         self.cache.add_person(ecartico_id, description, qid)

    #     if qid == SKIP:
    #         return None
    #     if qid and qid.startswith("Q"):
    #         return qid

    #     raise RuntimeError(f"unrecognized person qid: {ecartico_id} -> {qid}")

    def get_gutenberg_qid(self, ebook_id: Optional[str]) -> Optional[str]:
        qid = self.cache.get_gutenberg_qid(ebook_id)
        if not qid:
            # load from wikidata
            qid = self.wikidata_source.get_gutenberg_qid(ebook_id)
            # if len(qids) > 1:
            #     qid = MULTIPLE
            if not qid:
                qid = SKIP
            # else:
            #     qid = qids[0]
            self.cache.add_gutenberg_ebook_id_qid(ebook_id, qid)

        if qid == SKIP:
            return None
        if qid and qid.startswith("Q"):
            return qid

    def get_rijksmuseum_inventory_number(self, url: str) -> str:
        match = re.search(
            r"^https?:\/\/www.rijksmuseum\.nl\/nl\/zoeken\/objecten\?q=([A-Z0-9.-]+)",
            url,
            re.IGNORECASE,
        )
        if not match:
            raise RuntimeError(f"Unexpected url {url}")
        inventory_number = match.group(1)

        return inventory_number

    def get_rijksmuseum_qid(
        self, url: str, inventory_number: Optional[str]
    ) -> Optional[str]:
        if not inventory_number:
            inventory_number = self.get_rijksmuseum_inventory_number(url)

        qid = self.cache.get_rijksmuseum_qid(url, inventory_number)
        if not qid:
            # load from wikidata
            qid = self.wikidata_source.get_rijksmuseum_qid(url, inventory_number)
            # if len(qids) > 1:
            #     qid = MULTIPLE
            if not qid:
                qid = SKIP
            # else:
            #     qid = qids[0]
            self.cache.add_rijksmuseum_qid(inventory_number, qid)

        if qid == SKIP:
            return None
        if qid and qid.startswith("Q"):
            return qid

        raise RuntimeError(
            f"unrecognized rijksmuseum_inventory_number qid: {inventory_number} -> {qid}"
        )

    def is_possible(self, ecartico_id: Optional[str], qid: str) -> bool:
        return self.cache.is_possible(ecartico_id, qid)

    def get_occupation_type(self, qid: str) -> Optional[str]:
        text = self.cache.get_occupation_type(qid)
        if text == LEEG:
            return None
        if text:
            return text

        # load
        description = self.wikidata_source.get_description(qid)
        if not description:
            raise RuntimeError(f"No description for occupation {qid}")

        types = []

        if self.wikidata_source.get_is(qid, wd.QID_POSITION):
            types.append("Position")
        if self.wikidata_source.get_is(qid, wd.QID_NOBLE_TITLE):
            types.append("NobleTitle")
        if self.wikidata_source.get_is(qid, wd.QID_OCCUPATION):
            types.append("Occupation")

        text = "+".join(types) if types else LEEG

        self.cache.add_occupation_type(qid, description, text)
        return text

    def get_description(self, qid: str) -> Optional[str]:
        return self.wikidata_source.get_description(qid)

    def get_is(self, qid: str, query: str) -> bool:
        return self.wikidata_source.get_is(qid, query)
