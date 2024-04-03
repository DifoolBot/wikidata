import requests
import name as nm
import authdata

PID_LIBRARY_OF_CONGRESS_AUTHORITY_ID = "P244"
# see applicable 'stated in' value
QID_LIBRARY_OF_CONGRESS_AUTHORITIES = "Q13219454"

MADS_ELEMENTLIST = "http://www.loc.gov/mads/rdf/v1#elementList"
MADS_ELEMENTVALUE = "http://www.loc.gov/mads/rdf/v1#elementValue"
MADS_FULLNAMEELEMENT = "http://www.loc.gov/mads/rdf/v1#FullNameElement"
MADS_BIRTHDATE = "http://www.loc.gov/mads/rdf/v1#birthDate"
MADS_DEATHDATE = "http://www.loc.gov/mads/rdf/v1#deathDate"
MADS_SOURCE = "http://www.loc.gov/mads/rdf/v1#Source"
MADS_CITATIONSOURCE = "http://www.loc.gov/mads/rdf/v1#citationSource"
MADS_CITATIONNOTE = "http://www.loc.gov/mads/rdf/v1#citationNote"
SKOS_PREFLABEL = "http://www.w3.org/2004/02/skos/core#prefLabel"
MADS_USEINSTEAD = "http://www.loc.gov/mads/rdf/v1#useInstead"


class LocPage(authdata.AuthPage):
    def __init__(self, loc_id: str):
        super().__init__(loc_id, "en")
        self.languages = []
        self.sources = []

    def __str__(self):
        output = f"""
                init_id: {self.init_id}
                loc_id: {self.id}
                not found: {self.not_found}
                redirect: {self.is_redirect}"""
        if self.name is not None:
            output += f"""
                name: {self.name.names_en()}
                languages: {self.languages}
                given_name_en: {self.name.given_name_en} 
                family_name_en: {self.name.family_name_en}
                birth_date: {self.birth_date}
                death_date: {self.death_date}"""
        return output

    def query(self):
        url = f"https://id.loc.gov/authorities/names/{self.id}.json"
        response = requests.get(url, timeout=20)
        if response.status_code == 404:
            self.not_found = True
            return None

        payload = response.json()
        return payload

    def is_family_name_first_language(self, user_languages):
        family_name_first_languages = {"jpn", "kor", "chi", "zho", "vie", "khm"}
        return any(lang in family_name_first_languages for lang in user_languages)

    def get_name_order(self):
        print(f"LoC: language: {self.languages}")
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
            print("LoC: family name FIRST based on sources")
            return nm.NAME_ORDER_EASTERN
        elif family_name_first < family_name_last:
            print("LoC: family name LAST based on sources")
            return nm.NAME_ORDER_WESTERN

        if self.is_family_name_first_language(self.languages):
            print("LoC: family name FIRST based on language")
            return nm.NAME_ORDER_EASTERN

        return nm.NAME_ORDER_UNDETERMINED

    def run(self):
        self.process(self.load())

    def get_short_desc(self):
        return "LoC"

    def load(self):
        data = self.query()
        return data

    def process(self, data):
        if data is None:
            return

        # construct the name_parts array using MADS_ELEMENTLIST
        # the name_parts are all the parts in the pref_label
        # for example: pref_label = "Xu, Feng, 1980-"
        # part 1, type: FullNameElement, value: "Xu, Feng,"
        # part 2, type: DateNameElement, value: "1980-"
        element_list = []
        for p in data:
            if p["@id"] == "http://id.loc.gov/authorities/names/" + self.init_id:
                if MADS_ELEMENTLIST in p:
                    arr = p[MADS_ELEMENTLIST]
                    if len(arr) != 1:
                        raise ValueError("len(elementlist) != 1")
                    list = arr[0]["@list"]
                    for id_obj in list:
                        id = id_obj["@id"]
                        element_list.append(id)
                break

        name_parts = []
        if element_list:
            for p in data:
                if p["@id"] in element_list:
                    name_part = {
                        "type": p["@type"][0],
                        "value": p[MADS_ELEMENTVALUE][0]["@value"],
                    }
                    name_parts.append(name_part)

        for p in data:
            if p["@id"] == "http://id.loc.gov/authorities/names/" + self.init_id:
                if SKOS_PREFLABEL in p:
                    pref_label = p[SKOS_PREFLABEL][0]["@value"]
                    if name_parts != []:
                        print(f"LoC: pref_label: {pref_label}")
                        print(f"LoC: name parts: {name_parts}")
                        # remove from pref_label all name parts that are not MADS_FULLNAMEELEMENT
                        #  i.e. dates, titles
                        for name_part in name_parts:
                            if name_part["type"] != MADS_FULLNAMEELEMENT:
                                part = name_part["value"]
                                if part not in pref_label:
                                    raise ValueError(f"{part} not in {pref_label}")
                                pref_label = pref_label.replace(part, "", 1)
                        pref_label = pref_label.strip(" ,")
                    if self.name is None:
                        self.name = nm.Name(name_en=pref_label)
                if MADS_USEINSTEAD in p:
                    use_instead = p[MADS_USEINSTEAD][0]["@id"]
                    self.id = use_instead.replace(
                        "http://id.loc.gov/authorities/names/", ""
                    )
                    self.is_redirect = self.id != self.init_id

            elif p["@id"] == "http://id.loc.gov/rwo/agents/" + self.init_id:
                if MADS_BIRTHDATE in p:
                    self.birth_date = p[MADS_BIRTHDATE][0]["@value"]
                if MADS_DEATHDATE in p:
                    self.death_date = p[MADS_DEATHDATE][0]["@value"]
            elif p["@id"].startswith("http://id.loc.gov/vocabulary/languages/"):
                lang = p["@id"].replace("http://id.loc.gov/vocabulary/languages/", "")
                self.languages.append(lang)
            elif MADS_SOURCE in p["@type"]:
                if MADS_CITATIONSOURCE in p:
                    for source in p[MADS_CITATIONSOURCE]:
                        if "@value" in source:
                            self.sources.append(source["@value"])
                if MADS_CITATIONNOTE in p:
                    for source in p[MADS_CITATIONNOTE]:
                        if "@value" in source:
                            self.sources.append(source["@value"])

        self.set_name_order(self.get_name_order())

    def get_ref(self):
        res = {
            "id_pid": PID_LIBRARY_OF_CONGRESS_AUTHORITY_ID,
            "stated in": QID_LIBRARY_OF_CONGRESS_AUTHORITIES,
            "id": self.id,
        }

        return res


def main() -> None:
    # birth_date: n98025505
    # death_date: n79063710
    # japanese: nr92043638; nr93034015; no2012059592
    # chinese: n2011182115
    # name with title: no93031097'
    # lang/short name: n2002066224; no2014117435; n81116002
    # 404: no00079374
    # deprecated: no2006103855

    p = LocPage("no2016151337")
    p.run()
    print(p)


if __name__ == "__main__":
    main()
