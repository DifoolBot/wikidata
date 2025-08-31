from shared_lib.lookups.interfaces.place_lookup_interface import PlaceLookupInterface


class CachedPlaceLookup:
    def __init__(self, cache: PlaceLookupInterface, source: PlaceLookupInterface):
        self.cache = cache
        self.source = source

    def get_place_by_qid(self, qid: str):
        result = self.cache.get_place_by_qid(qid)
        if result:
            return result
        result = self.source.get_place_by_qid(qid)
        if result:
            qid, country_qid, description = result
            self.cache.set_place(qid, country_qid, description)
        return result

    def get_place_qid_by_desc(self, desc: str) -> str:
        return self.cache.get_place_qid_by_desc(desc)
