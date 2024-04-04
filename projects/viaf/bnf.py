import requests
import name as nm
import authdata
import re

BNF_ENDPOINT = "https://data.bnf.fr/sparql"

PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID = "P268"
# see applicable 'stated in' value
QID_BNF_AUTHORITIES = "Q19938912"


class BnfPage(authdata.AuthPage):
    def __init__(self, bnf_id: str):
        super().__init__(
            pid=PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID,
            stated_in=QID_BNF_AUTHORITIES,
            id=bnf_id,
            page_language="fr",
        )
        self.country = ""

    def get_short_desc(self):
        return "BnF"

    def __str__(self):
        output = f"""
                init_id: {self.init_id}
                bnf_id: {self.id}
                not found: {self.not_found}
                redirect: {self.is_redirect}"""
        if self.name:
            output += f"""
                gender: {self.sex}
                name: {self.name.names_en()}
                country: {self.country}
                given_name_en: {self.name.given_name_en} 
                family_name_en: {self.name.family_name_en}
                birth_date: {self.birth_date}
                death_date: {self.death_date}"""
        return output

    def query_sparql(self, query: str, retry_counter: int = 3):
        response = requests.get(BNF_ENDPOINT, params={"query": query, "format": "json"})
        payload = response.json()

        return payload["results"]["bindings"]

    def query_url(self):
        url = f"https://catalogue.bnf.fr/ark:/12148/cb{self.id}"
        response = requests.get(url, timeout=20)
        if response.status_code == 404:
            self.not_found = True
            return None

        return response.text

    def get_name_order(self):
        if not self.country:
            return nm.NAME_ORDER_UNDETERMINED

        print(f"BnF: country: {self.country}")
        # see: http://id.loc.gov/vocabulary/countries/collection_PastPresentCountriesEntries
        lst = [
            "ko",  # Korea (South)
            "ja",  # Japan
            "cc",  # China
            "vm",  # Vietnam
            "kn",  # Korea (North)
        ]
        if (
            self.country.lower().replace("http://id.loc.gov/vocabulary/countries/", "")
            in lst
        ):
            print("Bnf: family name FIRST based on country")
            return nm.NAME_ORDER_EASTERN

        return nm.NAME_ORDER_UNDETERMINED

    def run(self):
        # SELECT ?value WHERE {
        #   { SELECT ?value WHERE { <http://data.bnf.fr/ark:/12148/cb15142263s#about> <http://www.w3.org/2002/07/owl#sameAs> ?value } }
        #   UNION
        #   { SELECT ?value WHERE { <http://data.bnf.fr/ark:/12148/cb15142263s> <http://isni.org/ontology#identifierValid> ?isni .
        #                          BIND (CONCAT("http://isni.org/isni/", ?isni) AS ?value) } }
        # }
        query_template = """
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            PREFIX bio: <http://vocab.org/bio/0.1/>
            PREFIX rdagroup2elements: <http://rdvocab.info/ElementsGr2/>
            PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            PREFIX bnfonto: <http://data.bnf.fr/ontology/bnf-onto/>

            SELECT ?page ?label ?type ?gender ?birth ?birthYear ?death ?country ?familyName ?givenName
                        WHERE {{
                            <http://data.bnf.fr/ark:/12148/cb{bnf_id}> skos:prefLabel ?label ; foaf:focus ?focus .
                            OPTIONAL {{ ?focus foaf:page ?page }} .
                            OPTIONAL {{ ?focus rdf:type ?type }} .
                            OPTIONAL {{ ?focus foaf:gender ?gender }} .
                            OPTIONAL {{ ?focus bio:birth ?birth }} .
                            OPTIONAL {{ ?focus bnfonto:firstYear ?birthYear }} .                           
                            OPTIONAL {{ ?focus bio:death ?death }} .
                            OPTIONAL {{ ?focus rdagroup2elements:countryAssociatedWithThePerson ?country }} .
                            OPTIONAL {{ ?focus foaf:familyName ?familyName }} .
                            OPTIONAL {{ ?focus foaf:givenName ?givenName }} .
                        }}"""
        qry = query_template.format(bnf_id=self.id)
        r = self.query_sparql(qry)
        if r is None:
            raise RuntimeError('BnF: no result')
        if r == []:
            self.check_redirect()
            if not self.is_redirect:
                self.not_found = True
            return
        for row in r:
            # {'type': 'uri', 'value': 'http://data.bnf.fr/16765535/ferenc_sajdik/'}
            # page = row.get("page", {}).get("value", "")
            # id = page.replace("http://data.bnf.fr/", "").split("/", 1)[0]
            pref_label = row.get("label", {}).get("value", "")
            family_name = row.get("familyName", {}).get("value", "")
            given_name = row.get("givenName", {}).get("value", "")
            type = row.get("type", {}).get("value", "")
            if type != "http://xmlns.com/foaf/0.1/Person":
                raise RuntimeError("not a person")
            self.sex = row.get("gender", {}).get("value", "")
            self.birth_date = row.get("birth", {}).get("value", "")
            # skip dates like 19..
            if "." in self.birth_date:
                self.birth_date = ""
            if not self.birth_date:
                self.birth_date = row.get("birthYear", {}).get("value", "")

            self.death_date = row.get("death", {}).get("value", "")
            if "." in self.death_date:
                self.death_date = ""
            self.country = row.get("country", {}).get("value", "")

            self.name = nm.Name(
                name_en=pref_label, given_name_en=given_name, family_name_en=family_name
            )
            self.set_name_order(self.get_name_order())

    def check_redirect(self):
        text = self.query_url()
        if text:
            regex = r"Identifiant de la notice.*?<\/span>ark:\/12148\/cb(\d{8,9}[0-9bcdfghjkmnpqrstvwxz])<\/div>"
            matches = re.search(regex, text, re.IGNORECASE)
            if matches:
                self.id = matches.group(1)
                self.is_redirect = self.id != self.init_id


def main() -> None:
    # not found: 167675653
    # birth date: 10211222t
    # redirect: 12377888j

    p = BnfPage("15142263s")
    p.run()
    print(p)


if __name__ == "__main__":
    main()
