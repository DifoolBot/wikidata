"""IdRef (SUDOC) authority record (RDF/XML)."""

import re
import time
import xml.etree.ElementTree as ET

import shared_lib.constants as wd
from shared_lib.rate_limiter import rate_limit

import addlabel.person_name as pn
from addlabel.authority_page import AuthorityPage
from addlabel.countries import Countries
from addlabel.http_client import http_get
from addlabel.languages import Languages

IDREF_SLEEP_AFTER_ERROR = 5 * 60  # sec

# namespace dictionary to store the tag prefixes
NS = {
    "foaf": "http://xmlns.com/foaf/0.1/",
    "bnf": "http://data.bnf.fr/ontology/bnf-onto/",
    "bio": "http://purl.org/vocab/bio/0.1/",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "dbpedia": "http://dbpedia.org/ontology/",
    "dcterms": "http://purl.org/dc/terms/",
    "bibo": "http://purl.org/ontology/bibo/",
}

BIO_BIRTH = "{http://purl.org/vocab/bio/0.1/}Birth"
BIO_DEATH = "{http://purl.org/vocab/bio/0.1/}Death"
RDF_ABOUT = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about"
RDF_RESOURCE = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"
URL_GEONAMES = "http://sws.geonames.org"
URL_LEXVO_3 = "http://lexvo.org/id/iso639-3/"
URL_LEXVO_5 = "http://lexvo.org/id/iso639-5/"


class IdrefPage(AuthorityPage):
    def __init__(
        self,
        idref_id: str,
        language_lookup: Languages,
        country_lookup: Countries,
    ):
        super().__init__(
            pid=wd.PID_IDREF_ID,
            stated_in_qid=wd.QID_IDREF,
            external_id=idref_id,
            page_language="fr",
            language_lookup=language_lookup,
            country_lookup=country_lookup,
        )
        self.bnf = ""

    def __str__(self):
        output = f"""
                init_id: {self.initial_external_id}
                IdRef: {self.external_id}
                not found: {self.not_found}
                redirect: {self.is_redirect}"""
        if self.latin_name:
            output += f"""
                gender: {self.sex}
                name: {self.latin_name.names()}
                variant: {self.variants}
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

    def get_short_desc(self):
        return "IdRef"

    @rate_limit(50)
    def query(self):
        url = f"https://www.idref.fr/{self.external_id}.rdf"
        response = http_get("IdRef", url, sleep_after_error=IDREF_SLEEP_AFTER_ERROR)
        if response.status_code == 404:
            self.not_found = True
            return None
        if response.status_code == 500:
            print("*** IdRef: Internal Server Error ***")
            time.sleep(IDREF_SLEEP_AFTER_ERROR)
            raise RuntimeError("IdRef Internal Server Error")

        try:
            return ET.fromstring(response.text)
        except Exception as ex:
            message = f"An exception of type {type(ex).__name__} occurred. Arguments:\n{ex.args!r}"
            print("*** Uncaught Error ***")
            print(message)
            time.sleep(IDREF_SLEEP_AFTER_ERROR)
            raise RuntimeError("IdRef Parse error: " + message)

    def find_text(self, element, path: str) -> str:
        found = element.find(path, NS)
        if found is not None:
            return found.text or ""
        return ""

    def run(self):
        root = self.query()
        if root is None:
            return

        person = root.find("foaf:Person", NS)
        if person is None:
            raise RuntimeError("IdRef: not a person")

        url = person.attrib[RDF_ABOUT]
        pattern = "https?:\\/\\/(?:www\\.)?idref\\.fr\\/(\\d{8}[\\dX]|)"
        matches = re.search(pattern, url, re.IGNORECASE)
        if matches:
            self.external_id = matches.group(1)
            self.is_redirect = self.external_id != self.initial_external_id

        self.sex = self.find_text(person, "foaf:gender")
        family_name = self.find_text(person, "foaf:familyName")
        given_name = self.find_text(person, "foaf:givenName")
        pref_label = self.find_text(person, "skos:prefLabel")

        print(f"idref: pref {pref_label} given {given_name} family {family_name}")
        self.latin_name = pn.PersonName(name=pref_label)
        if given_name or family_name:
            self.variants.append((given_name + " " + family_name).strip())

        element = person.find("dbpedia:citizenship", NS)
        if element is not None:
            url = element.attrib[RDF_RESOURCE]
            # <dbpedia-owl:citizenship rdf:resource=""/>
            if url:
                if not url.startswith(URL_GEONAMES):
                    raise RuntimeError(f"IdRef: Unexpected country url {url}")
                geoname_id = url.replace(URL_GEONAMES, "").replace("/", "")
                country_qid = self.country_lookup.get_country_from_geo(geoname_id)
                self.add_country(country_qid)

        element = person.find("bnf:FRBNF", NS)
        if element is not None:
            self.bnf = element.text

        for language in person.iterfind("dcterms:language", NS):
            url = language.attrib[RDF_RESOURCE]
            if not url:
                continue
            if url.startswith(URL_LEXVO_3):
                iso_code = url.replace(URL_LEXVO_3, "")
            elif url.startswith(URL_LEXVO_5):
                iso_code = url.replace(URL_LEXVO_5, "")
            else:
                raise RuntimeError(f"IdRef: Unexpected language url {url}")
            lang = self.language_lookup.get_language_from_iso(iso_code)
            self.add_language(lang)

        for event in person.iterfind("bio:event", NS):
            for el in event:
                if el.tag == BIO_BIRTH:
                    e = el.find("bio:date", NS)
                    if e is None:
                        e = el.find("dcterms:date", NS)
                    if e is not None:
                        self.birth_date = e.text
                elif el.tag == BIO_DEATH:
                    e = el.find("bio:date", NS)
                    if e is None:
                        e = el.find("dcterms:date", NS)
                    if e is not None:
                        self.death_date = e.text

        for document in root.iterfind("bibo:Document", NS):
            element = document.find("dcterms:bibliographicCitation", NS)
            if element is not None and element.text:
                self.add_source(element.text)

        self.set_name_order(self.determine_name_order())


def main() -> None:
    p = IdrefPage(
        "191756547",
        language_lookup=Languages(),
        country_lookup=Countries(),
    )
    p.run()
    print(p)


if __name__ == "__main__":
    main()
