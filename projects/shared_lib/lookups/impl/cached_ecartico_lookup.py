from typing import Optional

from shared_lib.lookups.interfaces.ecartico_lookup_interface import (
    EcarticoLookupInterface,
    EcarticoLookupAddInterface,
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

    def get_occupation(self, occupation_id: str) -> tuple[Optional[str], str]:
        qid, description = self.cache.get_occupation(occupation_id)

        if not qid:
            qid, description = self.ecartico_source.get_occupation(occupation_id)
            if not qid:
                qid = LEEG
            self.cache.add_occupation(occupation_id, description, qid)

        if qid == SKIP:
            return None, description
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

    def get_place(self, place_id: str) -> tuple[Optional[str], str]:
        qid, description = self.cache.get_place(place_id)
        if not qid:
            qid, description = self.ecartico_source.get_place(place_id)
            if not qid:
                qid = LEEG
            self.cache.add_place(place_id, description, qid)

        if qid == SKIP:
            return None, description
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

    def get_source(self, source_id: str) -> tuple[Optional[str], str]:
        qid, description = self.cache.get_source(source_id)
        if not qid:
            # load
            qid, description = self.ecartico_source.get_source(source_id)
            if not qid:
                qid = LEEG
            self.cache.add_source(source_id, description, qid)

        if qid == SKIP:
            return None, description
        if qid and qid.startswith("Q"):
            return qid, description

        # todo; tijdelijk
        # return None
        raise RuntimeError(f"unrecognized source: {source_id} {description} -> {qid}")

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

    def add_person_qid(
        self, ecartico_id: Optional[str], description: Optional[str], qid: Optional[str]
    ):
        self.cache.add_person_qid(ecartico_id, description, qid)

    def add_place(self, place_id: str, description: str, qid: str):
        self.cache.add_place(place_id, description, qid)

    def add_religion(self, religion: str, qid: str) -> None:
        self.cache.add_religion(religion, qid)

    def add_rijksmuseum_inventory_number_qid(
        self, inventory_number: str, qid: str
    ) -> None:
        self.cache.add_rijksmuseum_inventory_number_qid(inventory_number, qid)

    def add_rkdimage_qid(self, rkdimage_id: str, qid: str) -> None:
        self.cache.add_rkdimage_qid(rkdimage_id, qid)

    def add_source(self, source_id: str, description: str, qid: str):
        self.cache.add_source(source_id, description, qid)

    def get_person_qid(self, ecartico_id: Optional[str]) -> Optional[str]:
        pass

    def get_gutenberg_qid(self, ebook_id: Optional[str]) -> Optional[str]:
        pass

    def get_rijksmuseum_qid(
        self, url: str, inventory_number: Optional[str]
    ) -> Optional[str]:
        if not inventory_number:
            inventory_number = self.get_rijksmuseum_inventory_number(url)

        return self.get_rijksmuseum_inventory_number_qid(inventory_number)

    def is_possible(self, ecartico_id: Optional[str], qid: str) -> bool:
        pass

    def get_occupation_type(self, qid: str) -> Optional[str]:
        pass
