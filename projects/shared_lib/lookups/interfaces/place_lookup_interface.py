from typing import Protocol, Optional, Tuple


class PlaceLookupInterface(Protocol):
    def get_place_by_qid(self, qid: str) -> Optional[Tuple[str, str, str]]:
        """
        Retrieve place data by qid.
        Returns (place_qid, country_qid, place label) or None if not found.
        """
        ...

    def get_place_qid_by_desc(self, text: str) -> str:
        """
        Retrieve place data by qid.
        Returns (place_qid, country_qid, place label) or None if not found.
        """
        ...

    def set_place(self, place_qid: str, country_qid: str, place_description: str): ...


class CountryLookupInterface(Protocol):
    def get_country_by_qid(self, qid: str) -> Optional[Tuple[str, str, str]]:
        """
        Retrieve country data by qid.
        Returns (country_qid, code, country label) or None if not found.
        """
        ...

    def get_country_by_code(self, code: str) -> Optional[Tuple[str, str, str]]:
        """
        Retrieve country data by code.
        Returns (country_qid, code, country label) or None if not found.
        """
        ...

    def set_country(self, country_qid: str, country_code: str, country_label: str): ...
