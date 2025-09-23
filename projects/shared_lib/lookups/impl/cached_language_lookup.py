from shared_lib.lookups.interfaces.place_lookup_interface import (
    LanguageLookupInterface,
    CountryLookupInterface,
)


class CachedLanguageLookup(LanguageLookupInterface):
    def __init__(
        self,
        cache: LanguageLookupInterface,
        # source: LanguageLookupInterface,
        country: CountryLookupInterface,
    ):
        self.cache = cache
        # self.source = source
        self.country = country

    def get_languages_for_country(self, country_qid: str):
        result = self.cache.get_languages_for_country(country_qid)
        if not result:
            self.country.get_country_by_qid(country_qid)  # Ensure country exists
        return result

    def get_sorted_languages(self):
        return self.cache.get_sorted_languages()
