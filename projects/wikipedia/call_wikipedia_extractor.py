from pathlib import Path

import pywikibot as pwb
from convertdate import julian
from pywikibot.data import sparql
from pywikibot.pagegenerators import WikidataSPARQLPageGenerator
from wikipedia.wikipedia_extractor import (
    PersonLocale,
    WikidataStatusTracker,
    reconcile_dates,
)
import wikipedia.template_date_extractor as tde
from shared_lib.database_handler import DatabaseHandler

PAGE_TITLE = "User:Difool/date_mismatches"
WIKI_FILE = "wiki.txt"


def date_str(date: pwb.WbTime) -> str:
    calendar_map = {
        tde.URL_PROLEPTIC_GREGORIAN_CALENDAR: "G",
        tde.URL_PROLEPTIC_JULIAN_CALENDAR: "J",
    }
    cm = calendar_map.get(str(date.calendarmodel), "")

    if date.precision == 9:
        dt = f"{date.year:04d}"
    elif date.precision == 10:
        dt = f"{date.year:04d}-{date.month:02d}"
    elif date.precision == 11:
        dt = f"{date.year:04d}-{date.month:02d}-{date.day:02d}"
    else:
        raise RuntimeError(f"Unsupported precision: {date.precision}")

    return f"{dt}{cm}"


def assume_gregorian(wbt: pwb.WbTime) -> pwb.WbTime:
    return pwb.WbTime(
        year=wbt.year,
        month=wbt.month,
        day=wbt.day,
        precision=wbt.precision,
        calendarmodel=tde.URL_PROLEPTIC_GREGORIAN_CALENDAR,
    ).normalize()


def julian_to_gregorian(wbt: pwb.WbTime) -> pwb.WbTime:
    """Convert WbTime to a Gregorian date object, accounting for Julian calendar if needed."""
    g_year, g_month, g_day = julian.to_gregorian(wbt.year, wbt.month, wbt.day)
    return pwb.WbTime(
        year=g_year,
        month=g_month,
        day=g_day,
        precision=wbt.precision,
        calendarmodel=tde.URL_PROLEPTIC_GREGORIAN_CALENDAR,
    ).normalize()


def change_precision(wbt: pwb.WbTime, precision: int) -> pwb.WbTime:
    """Returns a copy of WbTime with adjusted precision."""
    return pwb.WbTime(
        year=wbt.year,
        month=wbt.month,
        day=wbt.day,
        precision=precision,
        calendarmodel=wbt.calendarmodel,
    ).normalize()


def date_difference_characteristic(wd_date: pwb.WbTime, wp_date: pwb.WbTime) -> str:
    # Gregorian-Julian diff
    if wp_date.calendarmodel == tde.URL_UNSPECIFIED_CALENDAR:
        wp_date.calendarmodel = wd_date.calendarmodel
    if wd_date.precision == 11 and wp_date.precision == 11:
        if julian_to_gregorian(wd_date) == assume_gregorian(wp_date):
            return "Gregorian-Julian"
        if julian_to_gregorian(wp_date) == assume_gregorian(wd_date):
            return "Gregorian-Julian"

    # More/Less precision (only if normalized values match at lowest precision)
    if wd_date.precision != wp_date.precision:
        lowest_precision = min(wd_date.precision, wp_date.precision)
        wd_norm = change_precision(wd_date, lowest_precision)
        wp_norm = change_precision(wp_date, lowest_precision)
        # don't care about calendar model
        wp_norm.calendarmodel = wd_norm.calendarmodel
        if wd_norm == wp_norm:
            if wd_date.precision > wp_date.precision:
                return "More prec."
            elif wd_date.precision < wp_date.precision:
                return "Less prec."

    # Component-wise differences
    y_diff = wd_date.year != wp_date.year
    m_diff = wd_date.month != wp_date.month
    d_diff = wd_date.day != wp_date.day

    if y_diff and not m_diff and not d_diff:
        return "Year"
    elif m_diff and not y_diff and not d_diff:
        return "Month"
    elif d_diff and not y_diff and not m_diff:
        return "Day"
    elif d_diff and m_diff and not y_diff:
        return "Day/Month"
    elif y_diff or m_diff or d_diff:
        return "Other"
    else:
        return ""


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

    def set_country_info(self, country_qid: str, country_code: str, country_desc: str):
        country_code = country_code.upper()
        if not country_code:
            country_code = ""
        shortened_desc = country_desc[:255]
        sql = "EXECUTE PROCEDURE add_country(?, ?, ?)"
        self.execute_procedure(sql, (country_qid, country_code, shortened_desc))

    def get_country_info(self, country_qid: str):
        rows = self.execute_query(
            "SELECT countrycode,description FROM country where qcountry=?",
            (country_qid,),
        )
        for row in rows:
            return country_qid, row[0], row[1]

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

    def add_mismatch(
        self, qid: str, lang: str, kind: str, wikidata_dates, wikipedia_dates, url
    ):
        sql = "INSERT INTO mismatch (qid, lang, kind, wd, wp, diff, url) VALUES (?, ?, ?, ?, ?, ?, ?)"
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            for wd in wikidata_dates:
                for wp in wikipedia_dates:
                    cur.execute(
                        sql,
                        (
                            qid,
                            lang,
                            kind[0],
                            date_str(wd),
                            date_str(wp),
                            date_difference_characteristic(wd, wp),
                            url,
                        ),
                    )
                    conn.commit()
        finally:
            conn.close()

    def get_mismatches(self):
        sql = "SELECT QID, LANG, KIND, WD, WP, URL, DIFF FROM MISMATCH order by cast(substring(qid from 2) as integer)"
        rows = self.execute_query(sql)
        for row in rows:
            qid = row[0]
            lang = row[1]
            kind = row[2]
            wd = row[3]
            wp = row[4]
            url = row[5]
            diff = row[6]
            yield qid, lang, kind, wd, wp, url, diff


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


def todo(test: bool = True):
    tracker = FirebirdStatusTracker()
    for qid in tracker.get_todo():
        item = pwb.ItemPage(pwb.Site("wikidata", "wikidata"), qid)
        reconcile_dates(item, tracker, test=test)


def do_item(qid: str):
    tracker = FirebirdStatusTracker()
    item = pwb.ItemPage(pwb.Site("wikidata", "wikidata"), qid)
    reconcile_dates(item, tracker, check_already_done=False)


def do_sandbox2(qid: str):
    tracker = FirebirdStatusTracker()
    sandbox_item = pwb.ItemPage(pwb.Site("wikidata", "wikidata"), "Q13406268")
    real_item = pwb.ItemPage(pwb.Site("wikidata", "wikidata"), qid)
    locale = PersonLocale(real_item, tracker)
    locale.load()
    reconcile_dates(
        sandbox_item, tracker, check_already_done=False, locale=locale, test=True
    )


def do_sandbox3(qid: str):
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


def make_wikitext():
    tracker = FirebirdStatusTracker()

    heading = ""
    header = '\n{| class="wikitable sortable" style="vertical-align:bottom;"\n|-\n! QID\n! Lang\n! WikiLink\n! Event\n! WD Date\n! WP Date\n! Diff'
    body = ""
    line = "\n|-\n| {{{{Q|{qid}}}}}\n| {lang}\n| {wikilink}\n| {event}\n| {wd_date}\n| {wp_date}\n| {diff}"
    for row in tracker.get_mismatches():
        qid, lang, event, wd_date, wp_date, url, diff = row
        if event == "b":
            event = "Birth"
        if event == "d":
            event = "Death"
        wikilink = f"[[{url}]]"

        body = body + line.format(
            qid=qid,
            lang=lang,
            wikilink=wikilink,
            event=event,
            wd_date=wd_date,
            wp_date=wp_date,
            diff=diff,
        )
    footer = "\n|}"
    wikitext = f"{heading}{header}{body}{footer}"

    return wikitext


def write_to_wiki(wikitext):
    # with open(WIKI_FILE, "w", encoding="utf-8") as outfile:
    #     outfile.write(wikitext)
    # return
    if not wikitext:
        return
    site = pwb.Site("wikidata", "wikidata")
    page = pwb.Page(site, PAGE_TITLE)
    page.text = page.text + "\n" + wikitext
    page.save(summary="upd", minor=False)


def generate_report():
    write_to_wiki(make_wikitext())


def main():
    todo(test=False)
    # query_loop()
    # fill()
    # calc()
    do_sandbox2("Q18747311")
    # do_item("Q3071923")
    # generate_report()


if __name__ == "__main__":
    main()
