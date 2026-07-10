"""Base class for a person record fetched from one authority source.

Each subclass (LocPage, BnfPage, IdrefPage, GndPage, WikidataPage) retrieves
one external record and normalizes it into the attributes defined here: the
latinized name, birth/death date strings, sex, associated countries/languages
(as Wikidata QIDs), name variants and citation sources. The Collector then
combines several pages into a single verdict per item.
"""

from typing import Optional

import addlabel.person_name as pn
import addlabel.script_utils as script_utils
from addlabel.countries import Countries
from addlabel.languages import Languages


def tri_state_or(a: Optional[bool], b: Optional[bool]) -> Optional[bool]:
    """Three-valued OR where None means "unknown".

    None x None -> None; a x None -> a; None x b -> b; a x b -> a or b
    """
    return a if b is None else b if a is None else a or b


class AuthorityPage:
    def __init__(
        self,
        language_lookup: Languages,
        country_lookup: Countries,
        external_id: str,
        pid: str = "",
        stated_in_qid: str = "",
        page_language: str = "",
    ):
        # Wikidata property for this source's identifier ("" for WikidataPage)
        self.pid = pid
        # QID to use as the 'stated in' (P248) reference value
        self.stated_in_qid = stated_in_qid
        # the id as found on the Wikidata item; external_id is updated when the
        # source reports a redirect
        self.initial_external_id = external_id
        self.external_id = external_id
        self.not_found = False
        self.is_redirect = False
        self.latin_name: Optional[pn.PersonName] = None
        self.page_language = page_language
        self.birth_date = ""
        self.death_date = ""
        self.sex = ""
        self.name_order = pn.NAME_ORDER_UNDETERMINED
        self.countries = []  # country QIDs
        self.languages = []  # language QIDs
        self.sources = []  # citation strings, used to detect name order
        self.variants = []  # alternative name strings
        self.has_prefix = False
        self.did_run = False
        self.language_lookup = language_lookup
        self.country_lookup = country_lookup

    def run(self):
        """Fetch and process the record; implemented by subclasses."""
        raise NotImplementedError

    def get_short_desc(self) -> str:
        """Short source tag ("LoC", "BnF", ...) used in edit summaries."""
        raise NotImplementedError

    def run_once(self):
        if self.did_run:
            return

        self.did_run = True
        self.run()

    def determine_name_order(self) -> str:
        short = self.get_short_desc()
        for country in self.countries:
            if self.country_lookup.is_hungarian_name_order_country(country):
                print(f"{short}: family name FIRST (hungarian) based on country")
                return pn.NAME_ORDER_HUNGARIAN
        for language in self.languages:
            if self.country_lookup.is_hungarian_name_order_language(language):
                print(f"{short}: family name FIRST (hungarian) based on language")
                return pn.NAME_ORDER_HUNGARIAN

        if self.has_prefix:
            print(f"{short}: family name LAST based on existing prefix")
            return pn.NAME_ORDER_WESTERN

        if self.latin_name:
            # same if given_name or family_name is empty; for example Q3160707
            # (Jala; pseudonym)
            if (
                self.latin_name.family_name_first()
                == self.latin_name.family_name_last()
            ):
                return pn.NAME_ORDER_UNDETERMINED

            # count in how many citation strings each order appears
            family_name_first = 0
            family_name_last = 0
            for src in self.sources:
                for name in self.latin_name.family_name_first():
                    if name in src:
                        family_name_first += 1
                for name in self.latin_name.family_name_last():
                    if name in src:
                        family_name_last += 1
            if family_name_first > family_name_last:
                print(f"{short}: family name FIRST based on sources")
                return pn.NAME_ORDER_EASTERN
            elif family_name_first < family_name_last:
                print(f"{short}: family name LAST based on sources")
                return pn.NAME_ORDER_WESTERN

        for country in self.countries:
            if self.country_lookup.is_eastern_name_order_country(country):
                print(f"{short}: family name FIRST based on country")
                return pn.NAME_ORDER_EASTERN
        for language in self.languages:
            if self.country_lookup.is_eastern_name_order_language(language):
                print(f"{short}: family name FIRST based on language")
                return pn.NAME_ORDER_EASTERN

        return pn.NAME_ORDER_UNDETERMINED

    def country_codes(self):
        return [
            self.country_lookup.get_country(qid).get_code() for qid in self.countries
        ]

    def language_codes(self):
        return [
            self.language_lookup.get_language(qid).get_code() for qid in self.languages
        ]

    def add_country(self, country_qid: str):
        if country_qid and country_qid not in self.countries:
            self.countries.append(country_qid)

    def add_source(self, source: str):
        if source:
            self.sources.append(source)

    def add_language(self, language_qid: str):
        if language_qid and language_qid not in self.languages:
            self.languages.append(language_qid)

    def set_name_order(self, value: str):
        self.name_order = value
        if self.latin_name:
            self.latin_name.name_order = value

    def create_reference(self):
        """Reference (cwd.StateInReference) for statements sourced from this
        page. Imported lazily: importing change_wikidata logs in to Wikidata,
        which the offline collector logic doesn't need."""
        import shared_lib.change_wikidata as cwd

        return cwd.StateInReference(self.stated_in_qid, self.pid, self.external_id)

    def has_hebrew_script(self):
        for name in self.variants:
            if name and script_utils.is_hebrew_text(name):
                return True

        if self.check_locale(self.is_hebrew_language):
            return True

        return False

    def has_cyrillic_script(self):
        for name in self.variants:
            if name and script_utils.is_cyrillic_text(name):
                return True

        if self.check_locale(self.is_cyrillic_language):
            return True

        return False

    def has_non_latin_script(self):
        # can return None = unknown
        for name in self.variants:
            if name and not script_utils.is_latin_text(name):
                return True

        return self.check_locale(self.is_not_latin_language)

    def check_locale(self, predicate) -> Optional[bool]:
        """Apply a language predicate to the page's languages and the languages
        of its countries; three-valued (None = unknown)."""
        return tri_state_or(
            self.check_languages(predicate), self.check_countries(predicate)
        )

    def check_languages(self, predicate) -> Optional[bool]:
        res = None
        for language in self.languages:
            res = tri_state_or(res, predicate(language))
        return res

    def check_countries(self, predicate) -> Optional[bool]:
        res = None
        for country in self.countries:
            languages = self.country_lookup.get_country(country).get_languages()
            for language in languages:
                res = tri_state_or(res, predicate(language))

        return res

    def is_hebrew_language(self, language_qid: str) -> bool:
        return self.language_lookup.get_language(language_qid).get_is_hebrew()

    def is_cyrillic_language(self, language_qid: str) -> bool:
        return self.language_lookup.get_language(language_qid).get_is_cyrillic()

    def is_not_latin_language(self, language_qid: str) -> Optional[bool]:
        is_latin = self.language_lookup.get_language(language_qid).get_is_latin()
        if is_latin is None:
            return None
        return not is_latin

    def has_language_info(self) -> bool:
        if self.countries:
            return True
        if self.languages:
            return True
        for name in self.variants:
            if name and not script_utils.is_latin_text(name):
                return True
        return False
