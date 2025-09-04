from pathlib import Path
from typing import List, Optional, Tuple

import pywikibot as pwb
from genealogics.genealogy_import import (
    GenealogicsStatusTracker,
    update_wikidata_from_sources,
)
from pywikibot.data import sparql
from pywikibot.pagegenerators import WikidataSPARQLPageGenerator

from shared_lib.database_handler import DatabaseHandler
from shared_lib.lookups.impl.cached_place_lookup import CachedPlaceLookup
from shared_lib.lookups.impl.cached_country_lookup import CachedCountryLookup
from shared_lib.lookups.retrieval.db_cache import DBCache
from shared_lib.lookups.retrieval.wikidata_client import WikidataClient


class FirebirdStatusTracker(DatabaseHandler, GenealogicsStatusTracker):

    def __init__(self):
        file_path = Path(__file__).parent / "genealogics.json"
        create_script = Path("schemas/genealogics.sql")
        super().__init__(file_path, create_script)

    def is_error(self, qid: str) -> bool:
        return self.has_record("ERRORS", "qid=? AND NOT RETRY", (qid,))

    def is_done(self, qid: str) -> bool:
        return self.has_record("DONE", "qid=?", (qid,))

    def mark_error(self, qid: str, error: str):
        shortened_msg = error[:255]
        sql = "EXECUTE PROCEDURE add_error(?, ?)"
        self.execute_procedure(sql, (qid, shortened_msg))

    def mark_done(self, qid: str, message: str):
        shortened_msg = message[:255]
        sql = "EXECUTE PROCEDURE add_done(?, ?, ?)"
        self.execute_procedure(sql, (qid, shortened_msg))

    def get_todo(self):
        rows = self.execute_query("SELECT qid FROM todo order by 1")
        for row in rows:
            yield row[0]

    # def get_location_qid(self, location: str) -> Optional[str]:
    #     """Get the QID for a location string, or None if not found."""
    #     location = location.strip()
    #     if not location:
    #         return None
    #     shortened_loc = location[:255]
    #     sql = "EXECUTE PROCEDURE add_location(?)"
    #     self.execute_procedure(sql, (shortened_loc,))
    #     rows = self.execute_query(
    #         "SELECT QID FROM LOCATION WHERE UPPER(LOCATION)=UPPER(?)", (shortened_loc,)
    #     )
    #     for row in rows:
    #         return row[0]

    #     return None


def iterate_query():
    qry = """SELECT ?item ?date ?precision WHERE {
        ?item p:P569/psv:P569 ?dateNode.
        ?dateNode wikibase:timeValue ?date;
                    wikibase:timePrecision ?precision.
        FILTER(?precision = 11)
        FILTER(YEAR(?date) > 1800)
        FILTER NOT EXISTS { ?item p:P569/ prov:wasDerivedFrom [] }

        # must have at least one sitelink
        ?item wikibase:sitelinks ?sitelinkCount .
        FILTER(?sitelinkCount > 0)

    } limit 50"""
    site = pwb.Site("wikidata", "wikidata")
    for item in WikidataSPARQLPageGenerator(qry, site=site):
        yield item


def query_loop():
    tracker = FirebirdStatusTracker()
    country_lookup = CachedCountryLookup(
        cache=DBCache(),
        source=WikidataClient(),
    )
    place_lookup = CachedPlaceLookup(
        cache=DBCache(), source=WikidataClient(), country=country_lookup
    )
    for item in iterate_query():
        update_wikidata_from_sources(item, country_lookup, place_lookup, tracker)


def todo(test: bool = True):
    tracker = FirebirdStatusTracker()
    country_lookup = CachedCountryLookup(
        cache=DBCache(),
        source=WikidataClient(),
    )
    place_lookup = CachedPlaceLookup(
        cache=DBCache(), source=WikidataClient(), country=country_lookup
    )
    for qid in tracker.get_todo():
        item = pwb.ItemPage(pwb.Site("wikidata", "wikidata"), qid)
        update_wikidata_from_sources(
            item, country_lookup, place_lookup, tracker, test=test
        )


def do_item(qid: str, test: bool = True):
    tracker = FirebirdStatusTracker()
    country_lookup = CachedCountryLookup(
        cache=DBCache(),
        source=WikidataClient(),
    )
    place_lookup = CachedPlaceLookup(
        cache=DBCache(), source=WikidataClient(), country=country_lookup
    )
    item = pwb.ItemPage(pwb.Site("wikidata", "wikidata"), qid)
    update_wikidata_from_sources(
        item, country_lookup, place_lookup, tracker, check_already_done=False, test=test
    )


def main():
    # todo(test=True)
    # query_loop()
    # fill()
    # calc()
    # do_sandbox2("Q18747311")
    # do_item("Q101247401")
    # do_item("Q100450663")
    # do_item("Q100450658")  # Pelatiah Adams, Sr.
    # do_item("Q104034261")  # Harriet Byne Mead
    # do_item("Q15327330")  # Paon de Roet ()
    # do_item("Q100447276")  # Joan
    do_item("Q100154116")  # Rev.
    # do_item("Q100148333", test=False)
    # generate_report()


if __name__ == "__main__":
    main()
