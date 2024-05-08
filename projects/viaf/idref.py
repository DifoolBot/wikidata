import xml.etree.ElementTree as ET
import requests
import re
import name as nm
import authdata
import scriptutils
import languagecodes as lc

PID_IDREF_ID = "P269"
# see applicable 'stated in' value
QID_IDREF = "Q47757534"

# namespace dictionary to store the tag prefixes
ns = {
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


class IdrefPage(authdata.AuthPage):
    def __init__(self, idref_id: str):
        super().__init__(
            pid=PID_IDREF_ID, stated_in=QID_IDREF, id=idref_id, page_language="fr"
        )
        self.bnf = ""

    def __str__(self):
        output = f"""
                init_id: {self.init_id}
                IdRef: {self.id}
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
                countries: {self.countries}
                languages: {self.languages}
                hebrew: {self.has_hebrew_script()}
                cyrillic: {self.has_cyrillic_script()}
                non latin: {self.has_non_latin_script()}"""
        return output

    def query(self):
        url = f"https://www.idref.fr/{self.id}.rdf"
        response = requests.get(url, timeout=20)
        if response.status_code == 404:
            self.not_found = True
            return None

        return ET.fromstring(response.text)

    def get_short_desc(self):
        return "IdRef"

    def run(self):
        root = self.query()
        if not root:
            return

        person = root.find("foaf:Person", ns)
        if person is None:
            raise RuntimeError("not a person")

        url = person.attrib[RDF_ABOUT]
        # regex = "http?:\/\/(?:www\.)idref\.fr\/([0-9]\d*)"
        regex = "https?:\/\/(?:www\.)?idref\.fr\/(\d{8}[\dX]|)"
        matches = re.search(regex, url, re.IGNORECASE)
        if matches:
            self.id = matches.group(1)
            self.is_redirect = self.id != self.init_id

        element = person.find("foaf:gender", ns)
        if element is not None:
            self.sex = element.text or ''

        element = person.find("foaf:familyName", ns)
        if element is not None:
            family_name = element.text or ''
        else:
            family_name = ""

        element = person.find("foaf:givenName", ns)
        if element is not None:
            given_name = element.text or ''
        else:
            given_name = ""

        element = person.find("skos:prefLabel", ns)
        if element is not None:
            pref_label = element.text or ''
        else:
            pref_label = ""

        print(f"idref: pref {pref_label} given {given_name} family {family_name}")
        self.latin_name = nm.Name(name=pref_label)
        # self.variant = nm.Name(given_name=given_name, family_name=family_name)
        if given_name or family_name:
            self.variants.append((given_name + " " + family_name).strip())

        element = person.find("dbpedia:citizenship", ns)
        if element is not None:
            url = element.attrib[RDF_RESOURCE]
            # <dbpedia-owl:citizenship rdf:resource=""/>
            if url:
                if not url.startswith(URL_GEONAMES):
                    raise RuntimeError(f"IdRef: Unexpected country url {url}")
                geoname_id = url.replace(URL_GEONAMES, "").replace("/", "")
                if geoname_id not in lc.geonames_country_dict:
                    raise RuntimeError(f"IdRef: Unexpected geoname {geoname_id}")
                self.add_country(lc.geonames_country_dict[geoname_id])

        element = person.find("bnf:FRBNF", ns)
        if element is not None:
            self.bnf = element.text

        for language in person.iterfind("dcterms:language", ns):
            url = language.attrib[RDF_RESOURCE]
            if url.startswith(URL_LEXVO_3):
                iso_code = url.replace(URL_LEXVO_3, "")
            elif url.startswith(URL_LEXVO_5):
                iso_code = url.replace(URL_LEXVO_5, "")
            else:
                raise RuntimeError(f"IdRef: Unexpected language url {url}")
            if iso_code not in lc.iso639_3_dict:
                raise RuntimeError(f"IdRef: Unexpected language {url}")
            self.add_language(iso_code)

        for event in person.iterfind("bio:event", ns):
            for el in event:
                if el.tag == BIO_BIRTH:
                    e = el.find("bio:date", ns)
                    if e is None:
                        e = el.find("dcterms:date", ns)
                    if e is not None:
                        self.birth_date = e.text
                elif el.tag == BIO_DEATH:
                    e = el.find("bio:date", ns)
                    if e is None:
                        e = el.find("dcterms:date", ns)
                    if e is not None:
                        self.death_date = e.text

        for document in root.iterfind("bibo:Document", ns):
            element = document.find("dcterms:bibliographicCitation", ns)
            if element is not None:
                source = element.text
                self.sources.append(source)

        self.set_name_order(self.get_name_order())


def main() -> None:
    # no comma: 031955207
    # china: 255065140, 24928071X
    # russian: 034466835; 114722722
    # wrong name: 179363697
    # redirect: 086119427, 07739481X, 19938309X
    # not found: 07878249X
    # gender: 086119427
    # d': 118126881
    # enseignment: 128470119
    # polish: 113796358
    # USSR: 153704225
    # taiwan: 074186329
    # Ukranian: 187171416

    p = IdrefPage("11244416x")
    p.run()
    print(p)


if __name__ == "__main__":
    main()
