import requests
import name as nm
import authdata
import re
import languagecodes as lc
import time

BNF_ENDPOINT = "https://data.bnf.fr/sparql"
BNF_SLEEP_AFTER_ERROR = 1 * 60 # 10 * 60

PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID = "P268"
# see applicable 'stated in' value
QID_BNF_AUTHORITIES = "Q19938912"

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


class BnfPage(authdata.AuthPage):
    def __init__(self, bnf_id: str):
        super().__init__(
            pid=PID_BIBLIOTHEQUE_NATIONALE_DE_FRANCE_ID,
            stated_in=QID_BNF_AUTHORITIES,
            id=bnf_id,
            page_language="fr",
        )
        self.variants = []

    def get_short_desc(self):
        return "BnF"

    def __str__(self):
        output = f"""
                init_id: {self.init_id}
                bnf_id: {self.id}
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
                countries: {self.countries}
                languages: {self.languages}
                hebrew: {self.has_hebrew_script()}
                cyrillic: {self.has_cyrillic_script()}
                non latin: {self.has_non_latin_script()}"""
        return output

    def query_sparql(self, query: str, retry_counter: int = 3):
        try:
            response = requests.get(BNF_ENDPOINT, params={"query": query, "format": "json"})
        except requests.exceptions.ConnectionError as e:
            print('*** ConnectionError ***')
            print('Error: {error}'.format(error=e))
            time.sleep(BNF_SLEEP_AFTER_ERROR)
            raise RuntimeError("BNF Connection error")
        
        payload = response.json()
        return payload["results"]["bindings"]

    def query_url(self):
        url = f"https://catalogue.bnf.fr/ark:/12148/cb{self.id}"
        response = requests.get(url, timeout=20)
        if response.status_code == 404:
            self.not_found = True
            return None

        return response.text

    # https://data.bnf.fr/sparql/

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
        qry = query_template.format(bnf_id=self.id)
        r = self.query_sparql(qry)
        if r is None:
            raise RuntimeError("BnF: no result")
        if r == []:
            self.check_redirect()
            if not self.is_redirect:
                self.not_found = True
            return

        about_url = f"http://data.bnf.fr/ark:/12148/cb{self.id}#about"

        birth_year = ""
        death_year = ""
        given_name = ""
        given_name = ""
        pref_label = ""
        family_name = ""
        given_name = ""
        for row in r:
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
                self.sources.append(col2)
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
                    lang = lc.get_iso639_3(iso639_2)
                    self.add_language(lang)
                elif col3 == FOAF_FAMILYNAME:
                    family_name = col4
                elif col3 == FOAF_GIVENNAME:
                    given_name = col4
                elif col3 == ELEMENTSGR2_COUNTRY:
                    country = col4
                    if not country:
                        continue
                    if country.startswith(URL_LOC_COUNTRIES):
                        code = country.replace(URL_LOC_COUNTRIES, "")
                        if code not in lc.loc_country_dict:
                            raise RuntimeError(f"BnF: Unknown loc country {code}")
                        self.add_country(lc.loc_country_dict[code])
                    elif country.startswith(URL_BNF_COUNTRIES):
                        code = country.replace(URL_BNF_COUNTRIES, "")
                        if code not in lc.bnf_country_dict:
                            raise RuntimeError(f"BnF: Unknown bnf country {code}")
                        self.add_country(lc.bnf_country_dict[code])
                    else:
                        raise RuntimeError(f"BnF: Unrecognized country url {country}")

        if not self.birth_date and birth_year:
            self.birth_date = birth_year
        if not self.death_date and death_year:
            self.death_date = death_year
        self.latin_name = nm.Name(
            name=pref_label, given_name=given_name, family_name=family_name
        )
        self.set_name_order(self.get_name_order())

    def run_old(self):
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
            raise RuntimeError("BnF: no result")
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
                raise RuntimeError("BnF: not a person")
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
            country = row.get("country", {}).get("value", "")
            if country:
                if country.startswith(URL_LOC_COUNTRIES):
                    code = country.replace(URL_LOC_COUNTRIES, "")
                    if code not in lc.loc_country_dict:
                        raise RuntimeError(f"BnF: Unknown loc country {code}")
                    country3 = lc.loc_country_dict[code]
                    self.add_country(country3)
                elif country.startswith(URL_BNF_COUNTRIES):
                    code = country.replace(URL_BNF_COUNTRIES, "")
                    if code not in lc.bnf_country_dict:
                        raise RuntimeError(f"BnF: Unknown bnf country {code}")
                    country3 = lc.bnf_country_dict[code]
                    self.add_country(country3)
                else:
                    raise RuntimeError(f"BnF: Unrecognized country url {country}")


            self.latin_name = nm.Name(
                name=pref_label, given_name=given_name, family_name=family_name
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
    # not found: 167675653; 16143177k
    # birth date: 10211222t
    # redirect: 12377888j
    # leonardo: 11912491s: Léonard de Vinci
    # van gogh: 11927591g: Vincent Van Gogh
    # Hebrew: 11909578b
    # ota: 11244416x

    p = BnfPage("11909578b")
    p.run()
    print(p)


if __name__ == "__main__":
    main()
