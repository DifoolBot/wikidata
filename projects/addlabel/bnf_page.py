"""Bibliothèque nationale de France authority record (data.bnf.fr SPARQL)."""

import re

import shared_lib.constants as wd
from shared_lib.rate_limiter import rate_limit

import addlabel.countries as countries
import addlabel.person_name as pn
from addlabel.authority_page import AuthorityPage
from addlabel.countries import Countries
from addlabel.http_client import http_get
from addlabel.languages import Languages

BNF_ENDPOINT = "https://data.bnf.fr/sparql"
BNF_SLEEP_AFTER_ERROR = 5 * 60  # sec

BIO_BIRTH = "http://vocab.org/bio/0.1/birth"
BIO_DEATH = "http://vocab.org/bio/0.1/death"
BNF_FIRSTYEAR = "http://data.bnf.fr/ontology/bnf-onto/firstYear"
BNF_LASTYEAR = "http://data.bnf.fr/ontology/bnf-onto/lastYear"
ELEMENTSGR2_LANGUAGE = "http://rdvocab.info/ElementsGr2/languageOfThePerson"
ELEMENTSGR2_COUNTRY = "http://rdvocab.info/ElementsGr2/countryAssociatedWithThePerson"
FOAF_FAMILYNAME = "http://xmlns.com/foaf/0.1/familyName"
FOAF_FOCUS = "http://xmlns.com/foaf/0.1/focus"
FOAF_GENDER = "http://xmlns.com/foaf/0.1/gender"
FOAF_GIVENNAME = "http://xmlns.com/foaf/0.1/givenName"
FOAF_PERSON = "http://xmlns.com/foaf/0.1/Person"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
SKOS_ALTLABEL = "http://www.w3.org/2004/02/skos/core#altLabel"
SKOS_EDITORIALNOTE = "http://www.w3.org/2004/02/skos/core#editorialNote"
SKOS_PREFLABEL = "http://www.w3.org/2004/02/skos/core#prefLabel"
URL_LOC_ISO639_2 = "http://id.loc.gov/vocabulary/iso639-2/"
URL_LOC_COUNTRIES = "http://id.loc.gov/vocabulary/countries/"
URL_BNF_COUNTRIES = "http://data.bnf.fr/vocabulary/countrycodes/"


class BnfPage(AuthorityPage):
    def __init__(
        self,
        bnf_id: str,
        language_lookup: Languages,
        country_lookup: Countries,
    ):
        super().__init__(
            pid=wd.PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID,
            stated_in_qid=wd.QID_BNF_AUTHORITIES,
            external_id=bnf_id,
            page_language="fr",
            language_lookup=language_lookup,
            country_lookup=country_lookup,
        )

    def get_short_desc(self):
        return "BnF"

    def __str__(self):
        output = f"""
                init_id: {self.initial_external_id}
                bnf_id: {self.external_id}
                not found: {self.not_found}
                redirect: {self.is_redirect}"""
        if self.latin_name:
            output += f"""
                gender: {self.sex}
                name: {self.latin_name.names()}
                given_name: {self.latin_name.given_name}
                family_name: {self.latin_name.family_name}
                birth_date: {self.birth_date}
                death_date: {self.death_date}
                countries: {self.country_codes()}
                languages: {self.language_codes()}
                hebrew: {self.has_hebrew_script()}
                cyrillic: {self.has_cyrillic_script()}
                non latin: {self.has_non_latin_script()}"""
        return output

    @rate_limit(10)
    def query_sparql(self, query: str):
        response = http_get(
            "BnF",
            BNF_ENDPOINT,
            params={"query": query, "format": "json"},
            sleep_after_error=BNF_SLEEP_AFTER_ERROR,
        )

        try:
            payload = response.json()
        except Exception as ex:
            message = f"An exception of type {type(ex).__name__} occurred. Arguments:\n{ex.args!r}"
            print("*** Uncaught Error ***")
            print(message)
            raise RuntimeError("BnF JSON error: " + message)

        return payload["results"]["bindings"]

    def query_catalogue_page(self):
        url = f"https://catalogue.bnf.fr/ark:/12148/cb{self.external_id}"
        response = http_get("BnF", url, sleep_after_error=BNF_SLEEP_AFTER_ERROR)
        if response.status_code == 404:
            self.not_found = True
            return None

        return response.text

    def run(self):
        query_template = """
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            PREFIX bio: <http://vocab.org/bio/0.1/>
            PREFIX rdagroup2elements: <http://rdvocab.info/ElementsGr2/>
            PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            PREFIX bnfonto: <http://data.bnf.fr/ontology/bnf-onto/>

            SELECT ?y ?z ?xx ?yy WHERE {{
                <http://data.bnf.fr/ark:/12148/cb{bnf_id}> ?y ?z .
                OPTIONAL {{ ?z ?xx ?yy }} .
            }}"""
        qry = query_template.format(bnf_id=self.external_id)
        rows = self.query_sparql(qry)
        if rows is None:
            raise RuntimeError("BnF: no result")
        if rows == []:
            self.check_redirect()
            if not self.is_redirect:
                self.not_found = True
            return

        about_url = f"http://data.bnf.fr/ark:/12148/cb{self.external_id}#about"

        birth_year = ""
        death_year = ""
        pref_label = ""
        family_name = ""
        given_name = ""
        for row in rows:
            col1, col2, col3, col4 = (
                row.get("y", {}).get("value", ""),
                row.get("z", {}).get("value", ""),
                row.get("xx", {}).get("value", ""),
                row.get("yy", {}).get("value", ""),
            )

            if col1 == SKOS_PREFLABEL:
                pref_label = col2
            elif col1 == SKOS_ALTLABEL:
                self.variants.append(col2)
            elif col1 == SKOS_EDITORIALNOTE:
                self.add_source(col2)
            elif col1 == FOAF_FOCUS and col2 == about_url:
                if col3 == RDF_TYPE:
                    if col4 != FOAF_PERSON:
                        raise RuntimeError("BnF: not a person")
                elif col3 == FOAF_GENDER:
                    self.sex = col4
                elif col3 == BIO_BIRTH:
                    self.birth_date = col4
                elif col3 == BIO_DEATH:
                    self.death_date = col4
                elif col3 == BNF_FIRSTYEAR:
                    birth_year = col4
                elif col3 == BNF_LASTYEAR:
                    death_year = col4
                elif col3 == ELEMENTSGR2_LANGUAGE:
                    iso639_2 = col4.replace(URL_LOC_ISO639_2, "")
                    lang = self.language_lookup.get_language_from_iso639_2(iso639_2)
                    self.add_language(lang)
                elif col3 == FOAF_FAMILYNAME:
                    family_name = col4
                elif col3 == FOAF_GIVENNAME:
                    given_name = col4
                elif col3 == ELEMENTSGR2_COUNTRY:
                    self.add_country_url(col4)

        if not self.birth_date and birth_year:
            self.birth_date = birth_year
        if not self.death_date and death_year:
            self.death_date = death_year
        self.latin_name = pn.PersonName(
            name=pref_label, given_name=given_name, family_name=family_name
        )
        self.set_name_order(self.determine_name_order())

    def add_country_url(self, country_url: str):
        if not country_url:
            return
        if country_url.startswith(URL_LOC_COUNTRIES):
            code = country_url.replace(URL_LOC_COUNTRIES, "")
            self.add_country(self.country_lookup.get_country_from_loc(code))
        elif country_url.startswith(URL_BNF_COUNTRIES):
            code = country_url.replace(URL_BNF_COUNTRIES, "")
            if code not in countries.bnf_country_dict:
                raise RuntimeError(f"BnF: Unknown bnf country {code}")
            self.add_country(countries.bnf_country_dict[code])
        else:
            raise RuntimeError(f"BnF: Unrecognized country url {country_url}")

    def check_redirect(self):
        """An empty SPARQL result can mean the record was merged; the catalogue
        page still resolves and mentions the current record id."""
        text = self.query_catalogue_page()
        if text:
            regex = r"Identifiant de la notice.*?<\/span>ark:\/12148\/cb(\d{8,9}[0-9bcdfghjkmnpqrstvwxz])<\/div>"
            matches = re.search(regex, text, re.IGNORECASE)
            if matches:
                self.external_id = matches.group(1)
                self.is_redirect = self.external_id != self.initial_external_id


def main() -> None:
    p = BnfPage(
        "18077251",
        language_lookup=Languages(),
        country_lookup=Countries(),
    )
    p.run()
    print(p)


if __name__ == "__main__":
    main()
