from pathlib import Path

import pywikibot as pwb
from pywikibot.data import sparql
from pywikibot.pagegenerators import WikidataSPARQLPageGenerator
from wikipedia.wikipedia_extractor import (
    WikidataStatusTracker,
    reconcile_dates,
    PersonLocale,
)

from shared_lib.database_handler import DatabaseHandler


class FirebirdStatusTracker(DatabaseHandler, WikidataStatusTracker):

    def __init__(self):
        file_path = Path(__file__).parent / "wp_dates.json"
        super().__init__(file_path)

    def is_error(self, qid: str) -> bool:
        return self.has_record("QERROR", "QCODE=? AND NOT RETRY", (qid,))

    def is_done(self, qid: str) -> bool:
        return self.has_record("QDONE", "QCODE=?", (qid,))

    def mark_error(self, qid: str, error: str):
        shortened_msg = error[:255]
        sql = "EXECUTE PROCEDURE add_error(?, ?)"
        self.execute_procedure(sql, (qid, shortened_msg))

    def mark_done(self, qid: str, language: str, message: str):
        shortened_msg = message[:255]
        sql = "EXECUTE PROCEDURE add_done(?, ?, ?)"
        self.execute_procedure(sql, (qid, language, shortened_msg))

    def add_country(self, qid: str, description: str):
        shortened_desc = description[:255]
        sql = "EXECUTE PROCEDURE add_country(?, NULL, ?)"
        self.execute_procedure(sql, (qid, shortened_desc))

    def add_language(self, qid: str, language: str):
        sql = "EXECUTE PROCEDURE add_language(?, ?)"
        self.execute_procedure(sql, (qid, language))

    def get_country_qid(self, place_qid: str):
        rows = self.execute_query(
            "SELECT QCOUNTRY FROM PLACE where QPLACE=?", (place_qid,)
        )
        for row in rows:
            return row[0]

        return None

    def set_country_qid(
        self, place_qid: str, place_label: str, country_qid: str, country_label: str
    ):
        shortened_place_label = place_label[:255]
        shortened_country_label = country_label[:255]
        sql = "EXECUTE PROCEDURE add_place(?, ?, ?, ?)"
        self.execute_procedure(
            sql,
            (place_qid, shortened_place_label, country_qid, shortened_country_label),
        )

    def get_languages_for_country(self, country_qid: str):
        rows = self.execute_query(
            "SELECT LANGUAGE FROM GET_LANGUAGES(?)", (country_qid,)
        )
        results = []
        for row in rows:
            results.append(row[0])
        return results

    def get_todo(self):
        rows = self.execute_query("SELECT QCODE FROM qtodo order by 1")
        for row in rows:
            yield row[0]

    def get_empty_countries(self):
        qry = """SELECT r.QCOUNTRY
FROM COUNTRY r
left join language l on l.COUNTRY=r.QCOUNTRY
left join wiki w on w.LANGUAGE=l.language
where w.language is null"""

        rows = self.execute_query(qry)
        for row in rows:
            yield row[0]

    def set_country_info(self, country_qid: str, info):
        code, description = info
        code = code.upper()
        if not code:
            code = ""
        shortened_desc = description[:255]
        sql = "EXECUTE PROCEDURE add_country(?, ?, ?)"
        self.execute_procedure(sql, (country_qid, code, shortened_desc))

    def get_country_info(self, country_qid: str):
        rows = self.execute_query(
            "SELECT countrycode,description FROM country where qcountry=?",
            (country_qid,),
        )
        for row in rows:
            return row[0], row[1]

        return None

    def get_sorted_languages(self):
        rows = self.execute_query(
            "SELECT language FROM WIKI where sort_order is not null order by sort_order"
        )
        result = []
        for row in rows:
            result.append(row[0])
        return result

    def add_lead_sentence(self, qid: str, lang: str, lead_sentence: str):
        sql = """
            INSERT INTO lead_sentences (qid, lang, lead_sentence) 
            VALUES (?, ?, ?)
            """
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(sql, (qid, lang, lead_sentence))
            conn.commit()
        finally:
            conn.close()

    def get_wikipedia_qid(self, lang: str):
        rows = self.execute_query(
            "SELECT wikipedia FROM wiki where language=?", (lang,)
        )
        for row in rows:
            return row[0]

        return None

    # def add_source_to_claim(self, item, claim):
    #     wdpage = cwd.WikiDataPage(item, None, test=False)
    #     wdpage.load()
    #     wdpage.add_statement(
    #             cwd.DateOfBirth(self.create_date(date)),
    #             reference=self.createwdref(date_info),
    #         )
    #     wdpage.apply()


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


def calc_query(site, offset, limit) -> int:
    # 615810 items
    query = f"""SELECT (count( distinct ?item) as ?count) WHERE {{
  SERVICE bd:slice {{?item wdt:P569 ?date_of_birth .
                    bd:serviceParam bd:slice.offset {offset} .
                    bd:serviceParam bd:slice.limit {limit} .
                   }}
                  ?item p:P569/psv:P569 ?dateNode.
      ?dateNode wikibase:timeValue ?date;
                wikibase:timePrecision ?precision.
      FILTER(?precision = 11)
      FILTER(YEAR(?date) > 1500)
      FILTER NOT EXISTS {{ ?item p:P569/ prov:wasDerivedFrom [] }}

      ?item wikibase:sitelinks ?sitelinkCount .
      FILTER(?sitelinkCount > 0)
        
}}"""
    query_object = sparql.SparqlQuery()
    payload = query_object.query(query=query)
    if payload:
        for row in payload["results"]["bindings"]:
            count = int(row["count"]["value"])
            return count
    raise RuntimeError("finished")


def calc():
    site = pwb.Site("wikidata", "wikidata")
    offset = 0
    limit = 125_000
    total_count = 0
    while True:
        count = calc_query(site, offset, limit)
        total_count = total_count + count
        print(f"offset = {offset} count = {count} total_count = {total_count}")
        offset = offset + limit


def get_country_languages(country_qid: str):
    """
    Lookup the country QID for a given place QID.
    This is a placeholder function; actual implementation may vary.
    """
    query = f"""
            SELECT ?country ?countryLabel  ?langCode WHERE {{
            VALUES ?country {{ wd:{country_qid} }}  # Replace with your country QID

            # Get official languages
            ?country wdt:P37 ?language.
            ?language wdt:P218 ?langCode.  # ISO 639-1 code

            # Get English label and description
            SERVICE wikibase:label {{
                bd:serviceParam wikibase:language "en".
                ?country rdfs:label ?countryLabel.
                ?country schema:description ?description.
            }}
            }}
    """
    query_object = sparql.SparqlQuery()
    payload = query_object.query(query=query)
    results = []
    if payload:
        for row in payload["results"]["bindings"]:
            country_desc = row["countryLabel"]["value"]
            lang = row["langCode"]["value"]

            results.append((country_qid, country_desc, lang))

    return results


def query_loop():
    tracker = FirebirdStatusTracker()
    for item in iterate_query():
        reconcile_dates(item, tracker)


def todo():
    tracker = FirebirdStatusTracker()
    for qid in tracker.get_todo():
        item = pwb.ItemPage(pwb.Site("wikidata", "wikidata"), qid)
        reconcile_dates(item, tracker)


def do_item(qid: str):
    tracker = FirebirdStatusTracker()
    item = pwb.ItemPage(pwb.Site("wikidata", "wikidata"), qid)
    reconcile_dates(item, tracker, check_already_done=False)


def do_sandbox(qid: str):
    tracker = FirebirdStatusTracker()
    sandbox_item = pwb.ItemPage(pwb.Site("wikidata", "wikidata"), "Q15397819")
    real_item = pwb.ItemPage(pwb.Site("wikidata", "wikidata"), qid)
    locale = PersonLocale(real_item, tracker)
    locale.load()
    reconcile_dates(
        sandbox_item, tracker, check_already_done=False, locale=locale, test=False
    )


def fill():
    tracker = FirebirdStatusTracker()
    for qid in tracker.get_empty_countries():
        rows = get_country_languages(qid)
        for row in rows:
            country_qid, country_desc, lang = row
            tracker.add_country(qid, country_desc)
            tracker.add_language(qid, lang)
            print(f"Added {country_desc} ({lang}) to {qid}")


def main():
    # todo()
    # query_loop()
    # fill()
    # calc()
    do_sandbox("Q5863042")


if __name__ == "__main__":
    main()
