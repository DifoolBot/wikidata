from typing import Optional, Protocol, Tuple, final


class EcarticoLookupInterface(Protocol):
    @final
    def get_occupation_qid(self, occupation_id: Optional[str]) -> Optional[str]:
        if not occupation_id:
            return None
        t = self.get_occupation(occupation_id)
        if t:
            qid, desc = t
            return qid
        else:
            return None

    @final
    def get_place_qid(self, place_id: Optional[str]) -> Optional[str]:
        if not place_id:
            return None
        t = self.get_place(place_id)
        if t:
            qid, desc = t
            return qid
        else:
            return None

    @final
    def get_source_qid(self, source_id: Optional[str]) -> Optional[str]:
        if not source_id:
            return None
        t = self.get_source(source_id)
        if t:
            qid, desc = t
            return qid
        else:
            return None

    @final
    def get_person_qid(self, ecartico_id: Optional[str]) -> Optional[str]:
        if not ecartico_id:
            return None
        t = self.get_person(ecartico_id)
        if t:
            qid, desc = t
            return qid
        else:
            return None

    def get_occupation(self, occupation_id: str) -> Optional[tuple[str, str]]: ...
    def get_place(self, place_id: str) -> Optional[tuple[str, str]]: ...
    def get_source(self, source_id: str) -> Optional[tuple[str, str]]: ...
    def get_person(self, ecartico_id: Optional[str]) -> Optional[tuple[str, str]]: ...
    def get_patronym_qid(self, text: Optional[str]) -> Optional[str]: ...
    def get_religion_qid(self, text: Optional[str]) -> Optional[str]: ...
    def get_rkdimage_qid(self, rkdimage_id: str) -> Optional[str]: ...
    def get_genre_qid(
        self, attribute: Optional[str], value: Optional[str]
    ) -> Optional[str]: ...
    def get_gutenberg_qid(self, ebook_id: Optional[str]) -> Optional[str]: ...
    def get_rijksmuseum_qid(
        self, url: str, inventory_number: Optional[str]
    ) -> Optional[str]: ...
    def get_occupation_type(self, qid: str) -> Optional[str]: ...
    def is_possible(self, ecartico_id: Optional[str], qid: str) -> bool: ...
    def get_description(self, qid: str) -> Optional[str]: ...
    def get_is(self, qid: str, query: str) -> bool: ...


class EcarticoAddInterface(Protocol):
    def add_genre(self, attribute: str, value: str, qid: str) -> None: ...
    def add_gutenberg_ebook_id_qid(self, ebook_id: Optional[str], qid: str) -> None: ...
    def add_is_possible(self, ecartico_id: Optional[str], qid: str): ...
    def add_occupation(self, occupation_id, description: str, qid: str): ...
    def add_occupation_type(self, qid: str, description: str, text: str) -> None: ...
    def add_patronym(self, text: str, qid: str) -> None: ...
    def add_person(
        self, ecartico_id: Optional[str], description: Optional[str], qid: Optional[str]
    ): ...
    def add_place(self, place_id: str, description: str, qid: str): ...
    def add_religion(self, religion: str, qid: str) -> None: ...
    def add_rijksmuseum_qid(self, inventory_number: str, qid: str) -> None: ...
    def add_rkdimage_qid(self, rkdimage_id: str, qid: str) -> None: ...
    def add_source(self, source_id: str, description: str, qid: str): ...


class EcarticoLookupAddInterface(
    EcarticoLookupInterface, EcarticoAddInterface, Protocol
):
    pass
