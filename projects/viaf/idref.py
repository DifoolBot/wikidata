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


class IdrefPage(authdata.AuthPage):
    def __init__(self, idref_id: str):
        super().__init__(
            pid=PID_IDREF_ID, stated_in=QID_IDREF, id=idref_id, page_language="fr"
        )
        self.bnf = ""
        self.variant = None

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
                variant: {"None" if self.variant == None else self.variant.names()}
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

    def has_hebrew_script(self):
        if self.variant:
            for name in self.variant.names():
                if scriptutils.is_hebrew(name):
                    return True

        if self.has_script(lc.is_hebrew):
            return True

        return False

    def has_cyrillic_script(self):
        if self.variant:
            for name in self.variant.names():
                if scriptutils.is_cyrillic(name):
                    return True

        if self.has_script(lc.is_cyrillic):
            return True

        return False

    def has_non_latin_script(self):
        if self.variant:
            for name in self.variant.names():
                if not scriptutils.is_latin(name):
                    return True

        if self.has_script(lc.is_not_latin):
            return True

        return False


    def get_short_desc(self):
        return "IdRef"

    def run(self):
        root = self.query()
        if not root:
            return

        person = root.find("foaf:Person", ns)
        if person is None:
            raise RuntimeError("not a person")

        url = person.attrib["{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about"]
        # regex = "http?:\/\/(?:www\.)idref\.fr\/([0-9]\d*)"
        regex = "https?:\/\/(?:www\.)?idref\.fr\/(\d{8}[\dX]|)"
        matches = re.search(regex, url, re.IGNORECASE)
        if matches:
            self.id = matches.group(1)
            self.is_redirect = self.id != self.init_id

        element = person.find("foaf:gender", ns)
        if element is not None:
            self.sex = element.text

        element = person.find("foaf:familyName", ns)
        if element is not None:
            family_name = element.text
        else:
            family_name = ""

        element = person.find("foaf:givenName", ns)
        if element is not None:
            given_name = element.text
        else:
            given_name = ""

        element = person.find("skos:prefLabel", ns)
        if element is not None:
            pref_label = element.text
        else:
            pref_label = ""

        print(f"idref: pref {pref_label} given {given_name} family {family_name}")
        self.latin_name = nm.Name(name=pref_label)
        self.variant = nm.Name(given_name=given_name, family_name=family_name)

        element = person.find("dbpedia:citizenship", ns)
        if element is not None:
            url = element.attrib[
                "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"
            ]
            # <dbpedia-owl:citizenship rdf:resource=""/>
            if url:
                if not url.startswith("http://sws.geonames.org"):
                    raise RuntimeError(f"IdRef: Unexpected language {url}")
                geoname_id = url.replace("http://sws.geonames.org", "").replace("/", "")
                if geoname_id not in lc.geonames_country_dict:
                    raise RuntimeError(f"IdRef: Unexpected geoname {geoname_id}")
                self.countries.append(lc.geonames_country_dict[geoname_id])

        element = person.find("bnf:FRBNF", ns)
        if element is not None:
            self.bnf = element.text

        for language in person.iterfind("dcterms:language", ns):
            url = language.attrib[
                "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"
            ]
            if url.startswith("http://lexvo.org/id/iso639-3/"):
                iso_code = url.replace("http://lexvo.org/id/iso639-3/", "")
            elif url.startswith("http://lexvo.org/id/iso639-5/"):
                iso_code = url.replace("http://lexvo.org/id/iso639-5/", "")
            else:
                raise RuntimeError(f"IdRef: Unexpected language {url}")
            if iso_code not in lc.iso639_3_dict:
                raise RuntimeError(f"IdRef: Unexpected language {url}")
            self.languages.append(iso_code)

        for event in person.iterfind("bio:event", ns):
            for el in event:
                if el.tag == "{http://purl.org/vocab/bio/0.1/}Birth":
                    e = el.find("bio:date", ns)
                    if e is None:
                        e = el.find("dcterms:date", ns)
                    if e is not None:
                        self.birth_date = e.text
                elif el.tag == "{http://purl.org/vocab/bio/0.1/}Death":
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
