from shared_lib.lookups.interfaces.place_lookup_interface import PlaceLookupInterface, CountryLookupInterface

class CachedPlaceLookup(PlaceLookupInterface):
    def __init__(self, cache: PlaceLookupInterface, source: PlaceLookupInterface,
                country: CountryLookupInterface):
        self.cache = cache
        self.source = source
        self.country = country

    def get_place_by_qid(self, place_qid: str):
        result = self.cache.get_place_by_qid(place_qid)
        if result:
            return result
        result = self.source.get_place_by_qid(place_qid)
        if result:
            place_qid, country_qid, place_label = result
            # ensure the country exists
            self.country.get_country_by_qid(country_qid)
            # cache the place
            self.cache.set_place(place_qid, country_qid, place_label)
        return result

    def get_place_qid_by_desc(self, desc: str) -> str:
        return self.cache.get_place_qid_by_desc(desc)

    def set_place(self, place_qid: str, country_qid: str, place_label: str):
        # ensure the country exists
        self.country.get_country_by_qid(country_qid)
        self.cache.set_place(place_qid, country_qid, place_label)
