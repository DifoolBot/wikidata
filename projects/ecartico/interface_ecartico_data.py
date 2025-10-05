from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Optional, Set


class IEcartico(ABC):
    @abstractmethod
    def get_place_qid(self, place_id: Optional[str]) -> str:
        pass

    @abstractmethod
    def get_person_qid(self, ecartico_id: Optional[str]) -> str:
        pass

    @abstractmethod
    def get_occupation_qid(self, occupation_id: Optional[str]) -> str:
        pass

    @abstractmethod
    def get_rkdimage_qid(self, rkdimage_id: Optional[str]) -> str:
        pass

    @abstractmethod
    def get_occupation_type(self, qid: Optional[str]) -> str:
        pass

    @abstractmethod
    def get_religion_qid(self, text: Optional[str]) -> str:
        pass

    @abstractmethod
    def get_source_qid(self, source_id: Optional[str]) -> str:
        pass

    @abstractmethod
    def get_patronym_qid(self, text: Optional[str]) -> str:
        pass

    @abstractmethod
    def add_is_possible(self, ecartico_id: Optional[str], qid: Optional[str]):
        pass

    @abstractmethod
    def is_possible(self, ecartico_id: Optional[str], qid: Optional[str]) -> bool:
        pass

    @abstractmethod
    def get_genre_qid(self, attribute: Optional[str], value: Optional[str]) -> str:
        pass

    @abstractmethod
    def get_rijksmuseum_qid(self, url: str, inventory_number: Optional[str]):
        pass

    @abstractmethod
    def get_gutenberg_qid(self, ebook_id: Optional[str]):
        pass


class IEcarticoData(ABC):

    @abstractmethod
    def get_person_qid(self, ecartico_id: Optional[str]) -> str:
        pass

    @abstractmethod
    def get_place_qid(self, place_id: Optional[str]) -> str:
        pass

    @abstractmethod
    def get_occupation_qid(self, occupation_id: Optional[str]) -> str:
        pass

    @abstractmethod
    def get_source_qid(self, source_id: Optional[str]) -> str:
        pass

    @abstractmethod
    def get_genre_qid(self, attribute: str, value: Optional[str]) -> str:
        pass

    @abstractmethod
    def add_genre_qid(self, attribute: str, value: str, qid: Optional[str]) -> None:
        pass

    @abstractmethod
    def add_person_qid(
        self, ecartico_id: Optional[str], description: Optional[str], qid: Optional[str]
    ):
        pass

    @abstractmethod
    def add_place_qid(self, place_id: str, description: str, qid: Optional[str]):
        pass

    @abstractmethod
    def add_occupation_qid(
        self, occupation_id: str, description: str, qid: Optional[str]
    ):
        pass

    @abstractmethod
    def add_source_qid(self, source_id: str, description: str, qid: Optional[str]):
        pass

    @abstractmethod
    def get_patronym_qid(self, text: Optional[str]) -> str:
        pass

    @abstractmethod
    def add_patronym_qid(self, text: str, qid: Optional[str]) -> None:
        pass

    @abstractmethod
    def get_qid_from_rijksmuseum_inventory_number(
        self, inventory_number: Optional[str]
    ) -> str:
        pass

    @abstractmethod
    def add_rijksmuseum_inventory_number_qid(
        self, inventory_number: str, qid: str
    ) -> None:
        pass

    @abstractmethod
    def get_qid_from_gutenberg_ebook_id(self, ebook_id: Optional[str]) -> str:
        pass

    @abstractmethod
    def add_gutenberg_ebook_id_qid(self, ebook_id: str, qid: Optional[str]) -> None:
        pass

    @abstractmethod
    def get_occupation_type(self, qid: Optional[str]) -> str:
        pass

    @abstractmethod
    def add_occupation_type(
        self, qid: str, description: Optional[str], text: Optional[str]
    ) -> None:
        pass

    @abstractmethod
    def get_religion_qid(self, text: Optional[str]) -> str:
        pass

    @abstractmethod
    def add_religion_qid(self, text: str, qid: Optional[str]) -> None:
        pass

    @abstractmethod
    def add_error(self, qid: Optional[str], msg: Optional[str]):
        pass

    @abstractmethod
    def add_done(self, qid: Optional[str]):
        pass

    @abstractmethod
    def has_done(self, qid: Optional[str]) -> bool:
        pass

    @abstractmethod
    def has_error(self, qid: Optional[str]) -> bool:
        pass

    @abstractmethod
    def add_is_possible(self, ecartico_id: Optional[str], qid: Optional[str]):
        pass

    @abstractmethod
    def is_possible(self, ecartico_id: Optional[str], qid: Optional[str]) -> bool:
        pass

    @abstractmethod
    def get_rkdimage_qid(self, rkdimage_id: Optional[str]) -> str:
        pass

    @abstractmethod
    def add_rkdimage_qid(self, rkdimage_id: str, qid: Optional[str]) -> None:
        pass
