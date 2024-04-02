import xml.etree.ElementTree as ET
import requests
import re
import name
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
}


class IdrefPage(authdata.AuthPage):
    def __init__(self, idref_id: str):
        super().__init__(idref_id, "fr")
        self.citizenship = ""
        self.bnf = ""

    def __str__(self):
        return f"""
          idref: {self.id}
          not found: {self.not_found}
          redirect: {self.is_redirect}
          gender: {self.sex}
          name: {self.name.name_en()}
          citizenship: {self.citizenship}
          given_name: {self.name.given_name} 
          family_name: {self.name.family_name}
          given_name_en: {self.name.given_name_en} 
          family_name_en: {self.name.family_name_en}
          """

    def query(self):
        url = "https://www.idref.fr/{id}.rdf".format(id=self.id)
        response = requests.get(url, timeout=20)
        if response.status_code == 404:
            self.not_found = True
            return None

        return ET.fromstring(response.text)

    def name_order(self):
        if not self.citizenship:
            return ""

        print(f"Idref: citizenship: {self.citizenship}")
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
            print("Idref: family name FIRST based on citizenship")
            return name.NAME_ORDER_EASTERN
        else:
            return ""

    def get_short_desc(self):
        return "IdRef"

    def run(self):
        root = self.query()
        if root is None:
            return

        person = root.find("foaf:Person", ns)
        if person is not None:
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

            self.name = name.Name(
                name_en=pref_label, given_name=given_name, family_name=family_name
            )

            element = person.find("dbpedia:citizenship", ns)
            if element is not None:
                self.citizenship = element.attrib[
                    "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"
                ]

            self.name.name_order = self.name_order()

            element = person.find("bnf:FRBNF", ns)
            if element is not None:
                self.bnf = element.text

            for event in person.iterfind("bio:event", ns):
                for el in event:
                    if el.tag == "{http://purl.org/vocab/bio/0.1/}Birth":
                        e = el.find("bio:date", ns)
                        if e is not None:
                            self.birth_date = e.text
                    elif el.tag == "{http://purl.org/vocab/bio/0.1/}Death":
                        e = el.find("bio:date", ns)
                        if e is not None:
                            self.death_date = e.text

    def get_ref(self):
        # IdRef (Q47757534)
        # IdRef ID (P269)
        res = {"id_pid": PID_IDREF_ID, "stated in": QID_IDREF, "id": self.id}

        return res


def main() -> None:
    # geen comma: 031955207
    # p = IdrefPage('034466835')
    # china
    # p = IdrefPage('255065140')
    # p = IdrefPage('24928071X')
    # redirect
    # p = IdrefPage('086119427')
    # p = IdrefPage('07739481X')
    # not found
    # p = IdrefPage('07878249X')

    # wrong name: 179363697

    p = IdrefPage("179363697")
    p.run()
    print(p)


if __name__ == "__main__":
    main()
