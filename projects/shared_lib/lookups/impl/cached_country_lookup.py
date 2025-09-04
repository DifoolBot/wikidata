from shared_lib.lookups.interfaces.place_lookup_interface import (
    CountryLookupInterface,
)


class CachedCountryLookup(CountryLookupInterface):
    def __init__(self, cache: CountryLookupInterface, source: CountryLookupInterface):
        self.cache = cache
        self.source = source

    def get_country_by_qid(self, qid: str):
        result = self.cache.get_country_by_qid(qid)
        if result:
            return result
        result = self.source.get_country_by_qid(qid)
        if result:
            qid, country_code, description = result
            self.cache.set_country(qid, country_code, description)
        return result

    def get_country_by_code(self, qid: str):
        result = self.cache.get_country_by_code(qid)
        if result:
            return result
        result = self.source.get_country_by_code(qid)
        if result:
            qid, country_code, description = result
            self.cache.set_country(qid, country_code, description)
        return result

    def set_country(self, country_qid: str, country_code: str, country_label: str):
        self.cache.set_country(country_qid, country_code, country_label)
