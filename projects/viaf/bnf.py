import requests
import name as nm
import authdata

BNF_ENDPOINT = "https://data.bnf.fr/sparql"

PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID = "P268"
# see applicable 'stated in' value
QID_BNF_AUTHORITIES = "Q19938912"


class BnfPage(authdata.AuthPage):
    def __init__(self, bnf_id: str):
        super().__init__(bnf_id, "fr")
        self.country = ""

    def get_short_desc(self):
        return "BnF"

    def __str__(self):
        return f"""
          bnf: {self.id}
          not found: {self.not_found}
          redirect: {self.is_redirect}
          gender: {self.gender}
          name: {self.name.names_en()}
          birth_date: {self.birth_date}
          death_date: {self.death_date}
          country: {self.country}
          """

    def query_wdqs(self, query: str, retry_counter: int = 3):
        response = requests.get(BNF_ENDPOINT, params={"query": query, "format": "json"})
        payload = response.json()

        return payload["results"]["bindings"]

    def name_order(self):
        if not self.country:
            return ""

        print(f"BnF: country: {self.country}")
        # see: http://id.loc.gov/vocabulary/countries/collection_PastPresentCountriesEntries
        lst = [
            "ko",  # Korea (South)
            "ja",  # Japan
            "cc",  # China
            "vm",  # Vietnam
            "kn",  # Korea (North)
        ]
        if self.country.lower().replace("http://id.loc.gov/vocabulary/countries/", "") in lst:
            print("Bnf: family name FIRST based on country")
            return nm.NAME_ORDER_EASTERN
        
        return ""

    def run(self):
        query_template = """
            PREFIX foaf: <http://xmlns.com/foaf/0.1/>
            PREFIX bio: <http://vocab.org/bio/0.1/>
            PREFIX rdagroup2elements: <http://rdvocab.info/ElementsGr2/>
            PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

            SELECT ?page ?label ?type ?gender ?birth ?death ?country ?familyName ?givenName
                        WHERE {{
                            <http://data.bnf.fr/ark:/12148/cb{bnf_id}> skos:prefLabel ?label ; foaf:focus ?focus .
                            OPTIONAL {{ ?focus foaf:page ?page }} .
                            OPTIONAL {{ ?focus rdf:type ?type }} .
                            OPTIONAL {{ ?focus foaf:gender ?gender }} .
                            OPTIONAL {{ ?focus bio:birth ?birth }} .
                            OPTIONAL {{ ?focus bio:death ?death }} .
                            OPTIONAL {{ ?focus rdagroup2elements:countryAssociatedWithThePerson ?country }} .
                            OPTIONAL {{ ?focus foaf:familyName ?familyName }} .
                            OPTIONAL {{ ?focus foaf:givenName ?givenName }} .
                        }}"""
        qry = query_template.format(bnf_id=self.id)
        r = self.query_wdqs(qry)
        if r is None:
            return
        if r == []:
            self.not_found = True
            return
        for row in r:
            # {'type': 'uri', 'value': 'http://data.bnf.fr/16765535/ferenc_sajdik/'}
            page = row.get("page", {}).get("value", "")
            id = page.replace("http://data.bnf.fr/", "").split("/", 1)[0]
            pref_label = row.get("label", {}).get("value", "")
            family_name = row.get("familyName", {}).get("value", "")
            given_name = row.get("givenName", {}).get("value", "")
            type = row.get("type", {}).get("value", "")
            if type != "http://xmlns.com/foaf/0.1/Person":
                raise RuntimeError("not a person")
            self.gender = row.get("gender", {}).get("value", "")
            self.birth_date = row.get("birth", {}).get("value", "")
            # skip dates like 19..
            if "." in self.birth_date:
                self.birth_date = ""
            self.death_date = row.get("death", {}).get("value", "")
            if "." in self.death_date:
                self.death_date = ""
            self.country = row.get("country", {}).get("value", "")

            self.name = nm.Name(
                name_en=pref_label, given_name_en=given_name, family_name_en=family_name
            )
            self.name.name_order = self.name_order()

    def get_ref(self):
        res = {
            "id_pid": PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID,
            "stated in": QID_BNF_AUTHORITIES,
            "id": self.id,
        }

        return res


def main() -> None:
    # 16765535p
    # 10211222t
    # empty result: 167675653
    # cb15142263s

    p = BnfPage("15142263s")
    p.run()
    print(p)


if __name__ == "__main__":
    main()
