"""Library of Congress name-authority record (MADS/RDF JSON)."""

import shared_lib.constants as wd
from shared_lib.rate_limiter import rate_limit

import addlabel.countries as countries
import addlabel.person_name as pn
from addlabel.authority_page import AuthorityPage
from addlabel.countries import Countries
from addlabel.http_client import http_get
from addlabel.languages import Languages

LOC_SLEEP_AFTER_ERROR = 2 * 60  # sec

MADS_ASSOCIATEDLANGUAGE = "http://www.loc.gov/mads/rdf/v1#associatedLanguage"
MADS_ASSOCIATEDLOCALE = "http://www.loc.gov/mads/rdf/v1#associatedLocale"
MADS_BIRTHDATE = "http://www.loc.gov/mads/rdf/v1#birthDate"
MADS_CITATIONNOTE = "http://www.loc.gov/mads/rdf/v1#citationNote"
MADS_CITATIONSOURCE = "http://www.loc.gov/mads/rdf/v1#citationSource"
MADS_CODE = "http://www.loc.gov/mads/rdf/v1#code"
MADS_DEATHDATE = "http://www.loc.gov/mads/rdf/v1#deathDate"
MADS_ELEMENTLIST = "http://www.loc.gov/mads/rdf/v1#elementList"
MADS_ELEMENTVALUE = "http://www.loc.gov/mads/rdf/v1#elementValue"
MADS_FULLNAMEELEMENT = "http://www.loc.gov/mads/rdf/v1#FullNameElement"
MADS_HASVARIANT = "http://www.loc.gov/mads/rdf/v1#hasVariant"
MADS_SOURCE = "http://www.loc.gov/mads/rdf/v1#Source"
MADS_USEINSTEAD = "http://www.loc.gov/mads/rdf/v1#useInstead"
MADS_VARIANTLABEL = "http://www.loc.gov/mads/rdf/v1#variantLabel"
RDF_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
SKOS_PREFLABEL = "http://www.w3.org/2004/02/skos/core#prefLabel"
URL_LOC_NAMES = "http://id.loc.gov/authorities/names/"
URL_LOC_RWO_AGENTS = "http://id.loc.gov/rwo/agents/"
URL_LOC_LANGUAGES = "http://id.loc.gov/vocabulary/languages/"
URL_LOC_ISO639_1 = "http://id.loc.gov/vocabulary/iso639-1/"
URL_LOC_ISO639_3 = "http://id.loc.gov/vocabulary/iso639-3/"


class LocPage(AuthorityPage):
    def __init__(
        self,
        loc_id: str,
        language_lookup: Languages,
        country_lookup: Countries,
    ):
        super().__init__(
            pid=wd.PID_LIBRARY_OF_CONGRESS_AUTHORITY_ID,
            stated_in_qid=wd.QID_LIBRARY_OF_CONGRESS_AUTHORITIES,
            external_id=loc_id,
            page_language="en",
            language_lookup=language_lookup,
            country_lookup=country_lookup,
        )

    def __str__(self):
        output = f"""
                init_id: {self.initial_external_id}
                loc_id: {self.external_id}
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
                countries: {self.country_codes()}
                languages: {self.language_codes()}
                hebrew: {self.has_hebrew_script()}
                cyrillic: {self.has_cyrillic_script()}
                non latin: {self.has_non_latin_script()}"""
        return output

    def get_short_desc(self):
        return "LoC"

    @rate_limit(30)
    def query(self):
        url = f"https://id.loc.gov/authorities/names/{self.external_id}.json"
        response = http_get("LoC", url, sleep_after_error=LOC_SLEEP_AFTER_ERROR)

        if response.status_code == 404:
            self.not_found = True
            return None

        try:
            return response.json()
        except Exception as ex:
            message = f"An exception of type {type(ex).__name__} occurred. Arguments:\n{ex.args!r}"
            print("*** Uncaught Error ***")
            print(message)
            raise RuntimeError("LoC JSON error: " + message)

    def run(self):
        self.process(self.query())

    def get_name_parts(self, data_dict, element_list):
        if len(element_list) != 1:
            raise RuntimeError("len(elementlist) != 1")
        for id_obj in element_list[0]["@list"]:
            id = id_obj["@id"]
            if id in data_dict:
                p = data_dict[id]
                yield {
                    "type": p["@type"][0],
                    "value": p[MADS_ELEMENTVALUE][0]["@value"],
                }

    def get_variant_name(self, data_dict, variant_id):
        if variant_id not in data_dict:
            return None
        p = data_dict[variant_id]
        variant = p[MADS_VARIANTLABEL][0]["@value"]
        if MADS_ELEMENTLIST in p:
            variant = self.extract_fullname(data_dict, p[MADS_ELEMENTLIST], variant)
        return variant

    def extract_fullname(self, data_dict, element_list, name):
        """Strip the non-name elements (dates, titles) from a label.

        The element list contains all parts of the pref_label, for example
        pref_label "Xu, Feng, 1980-" consists of
        part 1, type: FullNameElement, value: "Xu, Feng,"
        part 2, type: DateNameElement, value: "1980-"
        """
        for name_part in self.get_name_parts(data_dict, element_list):
            if name_part["type"] != MADS_FULLNAMEELEMENT:
                part = name_part["value"]
                if part in name:
                    name = name.replace(part, "", 1)
                elif part.strip() in name:
                    name = name.replace(part.strip(), "", 1).strip()
                else:
                    raise RuntimeError(f"{part} not in {name}")
        return name.strip(" ,")

    def process(self, data):
        if not data:
            return

        # transform the list into a dictionary with @id as key
        data_dict = {p["@id"]: p for p in data}

        url = URL_LOC_NAMES + self.initial_external_id
        if url in data_dict:
            p = data_dict[url]
            if SKOS_PREFLABEL in p:
                pref_label = p[SKOS_PREFLABEL][0]["@value"]
                if MADS_ELEMENTLIST in p:
                    pref_label = self.extract_fullname(
                        data_dict, p[MADS_ELEMENTLIST], pref_label
                    )
                self.latin_name = pn.PersonName(name=pref_label)
            if MADS_HASVARIANT in p:
                for id_obj in p[MADS_HASVARIANT]:
                    variant = self.get_variant_name(data_dict, id_obj["@id"])
                    self.variants.append(variant)
            if MADS_USEINSTEAD in p:
                use_instead = p[MADS_USEINSTEAD][0]["@id"]
                self.external_id = use_instead.replace(URL_LOC_NAMES, "")
                self.is_redirect = self.external_id != self.initial_external_id

        url = URL_LOC_RWO_AGENTS + self.initial_external_id
        if url in data_dict:
            p = data_dict[url]
            if MADS_BIRTHDATE in p:
                self.birth_date = p[MADS_BIRTHDATE][0]["@value"]
            if MADS_DEATHDATE in p:
                self.death_date = p[MADS_DEATHDATE][0]["@value"]
            if MADS_ASSOCIATEDLOCALE in p:
                for id_obj in p[MADS_ASSOCIATEDLOCALE]:
                    id = id_obj["@id"]
                    if id not in data_dict:
                        country = countries.get_loc_url_country(id)
                        self.add_country(country)
                    else:
                        pp = data_dict[id]
                        if RDF_LABEL in pp:
                            loc_locale = pp[RDF_LABEL][0]["@value"]
                            country = countries.get_loc_locale_country(loc_locale)
                            self.add_country(country)
                        elif MADS_CODE in pp:
                            loc_locale = pp[MADS_CODE][0]["@value"]
                            country = countries.get_loc_geographic_areas_country(
                                loc_locale
                            )
                            self.add_country(country)
                        else:
                            raise RuntimeError(f"Unknown associated locale {pp}")

            if MADS_ASSOCIATEDLANGUAGE in p:
                for id_obj in p[MADS_ASSOCIATEDLANGUAGE]:
                    id = id_obj["@id"]
                    if id.startswith(URL_LOC_LANGUAGES):
                        loc_lang = id.replace(URL_LOC_LANGUAGES, "")
                    elif id.startswith(URL_LOC_ISO639_1):
                        loc_lang = id.replace(URL_LOC_ISO639_1, "")
                    elif id.startswith(URL_LOC_ISO639_3):
                        loc_lang = id.replace(URL_LOC_ISO639_3, "")
                    else:
                        raise RuntimeError(f"Unknown loc language id {id}")
                    lang = self.language_lookup.get_language_from_iso639_2(loc_lang)
                    self.add_language(lang)

        for p in data:
            if "@type" in p and MADS_SOURCE in p["@type"]:
                if MADS_CITATIONSOURCE in p:
                    for source in p[MADS_CITATIONSOURCE]:
                        if "@value" in source:
                            self.add_source(source["@value"])
                if MADS_CITATIONNOTE in p:
                    for source in p[MADS_CITATIONNOTE]:
                        if "@value" in source:
                            self.add_source(source["@value"])

        self.set_name_order(self.determine_name_order())


def main() -> None:
    p = LocPage(
        "n50010242",
        language_lookup=Languages(),
        country_lookup=Countries(),
    )
    p.run()
    print(p)


if __name__ == "__main__":
    main()
