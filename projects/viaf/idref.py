import xml.etree.ElementTree as ET
import requests
import re
import name as nm
import authdata

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
        self.citizenship = ""
        self.bnf = ""
        self.sources = []

    def __str__(self):
        output = f"""
                init_id: {self.init_id}
                IdRef: {self.id}
                not found: {self.not_found}
                redirect: {self.is_redirect}"""
        if self.name:
            output += f"""
                gender: {self.sex}
                name: {self.name.names_en()}
                citizenship: {self.citizenship}
                given_name_en: {self.name.given_name_en} 
                family_name_en: {self.name.family_name_en}
                given_name: {self.name.given_name} 
                family_name: {self.name.family_name}
                birth_date: {self.birth_date}
                death_date: {self.death_date}"""
        return output

    def query(self):
        url = f"https://www.idref.fr/{self.id}.rdf"
        response = requests.get(url, timeout=20)
        if response.status_code == 404:
            self.not_found = True
            return None

        return ET.fromstring(response.text)

    def get_name_order(self):
        print(f"IdRef: citizenship: {self.citizenship}")
        family_name_first = 0
        family_name_last = 0
        for src in self.sources:
            for name in self.name.family_name_first_en():
                if name in src:
                    family_name_first += 1
            for name in self.name.family_name_last_en():
                if name in src:
                    family_name_last += 1
        if family_name_first > family_name_last:
            print("IdRef: family name FIRST based on sources")
            return nm.NAME_ORDER_EASTERN
        elif family_name_first < family_name_last:
            print("IdRef: family name LAST based on sources")
            return nm.NAME_ORDER_WESTERN

        if not self.citizenship:
            return nm.NAME_ORDER_UNDETERMINED

        lst = [
            "1835841",  # Korea (South)
            "1861060",  # Japan
            "1814991",  # China
            "1562822",  # Vietnam
            "1821275",  # Macau
            "1873107",  # Korea (North)
        ]
        id = self.citizenship.replace("http://sws.geonames.org", "").replace("/", "")
        if id in lst:
            print("IdRef: family name FIRST based on citizenship")
            return nm.NAME_ORDER_EASTERN
        else:
            return nm.NAME_ORDER_UNDETERMINED

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
        self.name = nm.Name(
            name_en=pref_label, given_name=given_name, family_name=family_name
        )

        element = person.find("dbpedia:citizenship", ns)
        if element is not None:
            self.citizenship = element.attrib[
                "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"
            ]

        element = person.find("bnf:FRBNF", ns)
        if element is not None:
            self.bnf = element.text

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
    # russian: 034466835
    # wrong name: 179363697
    # redirect: 086119427, 07739481X
    # not found: 07878249X
    # gender: 086119427

    p = IdrefPage("078837863")
    p.run()
    print(p)


if __name__ == "__main__":
    main()
