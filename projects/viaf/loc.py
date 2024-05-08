import requests
import name as nm
import authdata
import scriptutils
import languagecodes as lc

PID_LIBRARY_OF_CONGRESS_AUTHORITY_ID = "P244"
# see applicable 'stated in' value
QID_LIBRARY_OF_CONGRESS_AUTHORITIES = "Q13219454"

MADS_ASSOCIATEDLANGUAGE = "http://www.loc.gov/mads/rdf/v1#associatedLanguage"
MADS_ASSOCIATEDLOCALE = "http://www.loc.gov/mads/rdf/v1#associatedLocale"
MADS_BIRTHDATE = "http://www.loc.gov/mads/rdf/v1#birthDate"
MADS_CITATIONNOTE = "http://www.loc.gov/mads/rdf/v1#citationNote"
MADS_CITATIONSOURCE = "http://www.loc.gov/mads/rdf/v1#citationSource"
MADS_DEATHDATE = "http://www.loc.gov/mads/rdf/v1#deathDate"
MADS_ELEMENTLIST = "http://www.loc.gov/mads/rdf/v1#elementList"
MADS_ELEMENTVALUE = "http://www.loc.gov/mads/rdf/v1#elementValue"
MADS_FULLNAMEELEMENT = "http://www.loc.gov/mads/rdf/v1#FullNameElement"
MADS_HASVARIANT = "http://www.loc.gov/mads/rdf/v1#hasVariant"
MADS_SOURCE = "http://www.loc.gov/mads/rdf/v1#Source"
MADS_USEINSTEAD = "http://www.loc.gov/mads/rdf/v1#useInstead"
MADS_VARIANTLABEL = "http://www.loc.gov/mads/rdf/v1#variantLabel"
RDF_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
SKOS_ALTLABEL = "http://www.w3.org/2008/05/skos-xl#altLabel"
SKOS_LABEL = "http://www.w3.org/2008/05/skos-xl#Label"
SKOS_LITERALFORM = "http://www.w3.org/2008/05/skos-xl#literalForm"
SKOS_PREFLABEL = "http://www.w3.org/2004/02/skos/core#prefLabel"
URL_LOC_NAMES = "http://id.loc.gov/authorities/names/"
URL_LOC_LANGUAGES = "http://id.loc.gov/vocabulary/languages/"


class LocPage(authdata.AuthPage):
    def __init__(self, loc_id: str):
        super().__init__(
            pid=PID_LIBRARY_OF_CONGRESS_AUTHORITY_ID,
            stated_in=QID_LIBRARY_OF_CONGRESS_AUTHORITIES,
            id=loc_id,
            page_language="en",
        )

    def __str__(self):
        output = f"""
                init_id: {self.init_id}
                loc_id: {self.id}
                not found: {self.not_found}
                redirect: {self.is_redirect}"""
        if self.latin_name:
            output += f"""
                name: {self.latin_name.names()}
                given_name: {self.latin_name.given_name} 
                family_name: {self.latin_name.family_name}
                birth_date: {self.birth_date}
                death_date: {self.death_date}
                variants: {self.variants}
                countries: {self.countries}
                languages: {self.languages}
                hebrew: {self.has_hebrew_script()}
                cyrillic: {self.has_cyrillic_script()}
                non latin: {self.has_non_latin_script()}"""
        return output

    def query(self):
        url = f"https://id.loc.gov/authorities/names/{self.id}.json"
        response = requests.get(url, timeout=20)
        if response.status_code == 404:
            self.not_found = True
            return None

        payload = response.json()
        return payload

    def run(self):
        self.process(self.load())

    def get_short_desc(self):
        return "LoC"

    def load(self):
        data = self.query()
        return data

    def get_name_parts(self, data_dict, element_list):
        if len(element_list) != 1:
            raise ValueError("len(elementlist) != 1")
        list = element_list[0]["@list"]
        for id_obj in list:
            id = id_obj["@id"]
            if id in data_dict:
                p = data_dict[id]
                name_part = {
                    "type": p["@type"][0],
                    "value": p[MADS_ELEMENTVALUE][0]["@value"],
                }
                yield name_part

    def get_variant_name(self, data_dict, variant_id):
        if variant_id not in data_dict:
            return None
        p = data_dict[variant_id]
        variant = p[MADS_VARIANTLABEL][0]["@value"]
        if MADS_ELEMENTLIST in p:
            variant = self.extract_fullname(data_dict, p[MADS_ELEMENTLIST], variant)
        return variant

    def extract_fullname(self, data_dict, element_list, name):
        """
        construct the name_parts array using MADS_ELEMENTLIST
        the name_parts are all the parts in the pref_label
        for example: pref_label = "Xu, Feng, 1980-"
        part 1, type: FullNameElement, value: "Xu, Feng,"
        part 2, type: DateNameElement, value: "1980-"
        """
        for name_part in self.get_name_parts(data_dict, element_list):
            if name_part["type"] != MADS_FULLNAMEELEMENT:
                part = name_part["value"]
                if part not in name:
                    raise ValueError(f"{part} not in {name}")
                name = name.replace(part, "", 1)
        name = name.strip(" ,")
        return name

    def process(self, data):
        if not data:
            return

        # transform the list into a dictionary with @id as key
        data_dict = {p["@id"]: p for p in data}

        url = URL_LOC_NAMES + self.init_id
        if url in data_dict:
            p = data_dict[url]
            if SKOS_PREFLABEL in p:
                pref_label = p[SKOS_PREFLABEL][0]["@value"]
                if MADS_ELEMENTLIST in p:
                    pref_label = self.extract_fullname(
                        data_dict, p[MADS_ELEMENTLIST], pref_label
                    )
                self.latin_name = nm.Name(name=pref_label)
            if MADS_HASVARIANT in p:
                for id_obj in p[MADS_HASVARIANT]:
                    id = id_obj["@id"]
                    variant = self.get_variant_name(data_dict, id)
                    self.variants.append(variant)
            if MADS_USEINSTEAD in p:
                use_instead = p[MADS_USEINSTEAD][0]["@id"]
                self.id = use_instead.replace(URL_LOC_NAMES, "")
                self.is_redirect = self.id != self.init_id

        url = "http://id.loc.gov/rwo/agents/" + self.init_id
        if url in data_dict:
            p = data_dict[url]
            if MADS_BIRTHDATE in p:
                self.birth_date = p[MADS_BIRTHDATE][0]["@value"]
            if MADS_DEATHDATE in p:
                self.death_date = p[MADS_DEATHDATE][0]["@value"]
            if MADS_ASSOCIATEDLOCALE in p:
                for id_obj in p[MADS_ASSOCIATEDLOCALE]:
                    id = id_obj["@id"]
                    pp = data_dict[id]
                    loc_locale = pp[RDF_LABEL][0]["@value"]
                    country = lc.get_loc_locale_country(loc_locale)
                    self.add_country(country)
            if MADS_ASSOCIATEDLANGUAGE in p:
                for id_obj in p[MADS_ASSOCIATEDLANGUAGE]:
                    id = id_obj["@id"]
                    loc_lang = id.replace(URL_LOC_LANGUAGES, "")
                    lang = lc.get_iso639_3(loc_lang)
                    self.add_language(lang)

        for p in data:
            if MADS_SOURCE in p["@type"]:
                if MADS_CITATIONSOURCE in p:
                    for source in p[MADS_CITATIONSOURCE]:
                        if "@value" in source:
                            self.sources.append(source["@value"])
                if MADS_CITATIONNOTE in p:
                    for source in p[MADS_CITATIONNOTE]:
                        if "@value" in source:
                            self.sources.append(source["@value"])

        self.set_name_order(self.get_name_order())


def main() -> None:
    # birth_date: n98025505
    # death_date: n79063710
    # japanese: nr92043638; nr93034015; no2012059592
    # russian: no91014701
    # russian language: n86009319
    # ukranian: no2013109553; n50010242
    # multiple cyrillic names: no2008028899
    # chinese: n2011182115
    # hebrew: n79085630
    # name with title: no93031097'
    # lang/short name: n2002066224; no2014117435; n81116002
    # 404: no00079374
    # deprecated: no2006103855
    # double space: no2002014027

    # check script: nr2004033376
    # todo: test no2011112751; hungarian

    p = LocPage("no2002014027")
    p.run()
    print(p)


if __name__ == "__main__":
    main()
