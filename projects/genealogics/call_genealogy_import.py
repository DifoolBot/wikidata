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
        sql = "EXECUTE PROCEDURE add_done(?, ?)"
        self.execute_procedure(sql, (qid, shortened_msg))

    def get_todo(self):
        rows = self.execute_query("SELECT first 1 qid FROM todo order by id")
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
            item,
            country_lookup,
            place_lookup,
            tracker,
            test=test,
            check_already_done=False,
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
    # todo(test=False)
    todo(test=True)
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
    # do_item("Q100154116", test=False)  # Rev.
    # do_item("Q100148333", test=False)
    # generate_report()

    # --- real name ----
    # do_item("Q100725746")  # 	Maj. William Todd	-	Todd-507 -> real name = guess

    # --- nick name ----
    # do_item("Q100726196")  # 	Col. Gawin Corbin	-	Corbin-188
    # do_item("Q100751106")  # 	A. M. Burton	-	Burton-4875

    # --- done ----
    # do_item("Q100433231", test=False)
    # # do_item("Q112795079", test = False)
    # do_item("Q100433233", test=False)
    # do_item("Q100153942", test=False)  # 	Ens. John Rowley	-	Rowley-98
    # do_item("Q100154350", test=False)  # 	Col. Septa Fillmore	-	Fillmore-605
    # do_item("Q100145569", test=False)  # Hon. Capt. Christopher Christophers
    # do_item("Q100402439", test=False)  # 	Capt. Nathan Chesebrough	-	Chesebrough-95
    # do_item("Q100154116")  # 	Rev. Richard Treat	-	Treat-254
    # do_item("Q100155340", test=False)  # 	Lt. Samuel Fairchild	-	Fairchild-75
    # do_item("Q100402424", test=False)  # 	Lt. Robert Chesebrough	-	Chesebrough-213
    # do_item("Q100433231")  # 	Rev. Thomas Smith	-	Smith-889
    # do_item("Q100753235", test=False)  # 	Dr. Harris Fuller Hamilton	-	Hamilton-8375
    # do_item("Q100753240", test=False)  # 	Dr. Merrill Thomas Hamilton	-	Hamilton-8376
    # do_item("Q100753243", test=False)  # 	Dr. Hannibal Charles Hamilton	-	Hamilton-8377
    # do_item("Q100753251", test=False)  # 	Rev. Elisha Hamilton	-	Hamilton-8379
    # do_item("Q100773424")  # 	J. Michael Lane	-	Lane-15238
    # do_item("Q100898120", test=False)  # 	Capt. Jonathan Starr	-	Starr-50
    # do_item("Q100911124", test=False)  # 	Capt. Prince Alden	-	Alden-50
    # do_item("Q100912551", test=False)  # 	Capt. John Dyer	-	Dyer-9459

    # do_item("Q100912707")  # 	Rev. Solomon Paine	-	Paine-134
    # do_item("Q101341465")

    # do_item("Q100912707", test = False)  # 	Rev. Solomon Paine	-	Paine-134
    # do_item("Q102157587", test = False) #	Dr. Ezra Granger Williams	-	Williams-93388
    # do_item("Q102157728", test = False) #	Capt. John Williams	-	Williams-28337
    # do_item("Q102157858", test = False) #	Lt. Abner Cooley	-	Cooley-653
    # do_item("Q102157894", test = False) #	Capt. Stephen Hollister, Sr.	-	Hollister-159
    # do_item("Q102161818", test = False) #	Capt. John Sherwood	-	Sherwood-1611

    # do_item("Q102162290", test = False) #	Capt. Joseph Hull, Jr.	-	Hull-2951
    # do_item("Q102165976", test=False)  # 	J. F. Paxton
    # do_item("Q110426659")


if __name__ == "__main__":
    main()
