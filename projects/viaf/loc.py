import requests
import name
import authdata

PID_LIBRARY_OF_CONGRESS_AUTHORITY_ID = "P244"
# see applicable 'stated in' value
QID_LIBRARY_OF_CONGRESS_AUTHORITIES = "Q13219454"


class LocPage(authdata.AuthPage):
    def __init__(self, loc_id: str):
        super().__init__(loc_id, "en")
        self.languages = []
        self.sources = []

    def __str__(self):
        return f"""
          loc_id: {self.id}
          not found: {self.not_found}
          redirect: {self.is_redirect}
          name: {self.name.name_en()}
          languages: {self.languages}
          given_name_en: {self.name.given_name_en} 
          family_name_en: {self.name.family_name_en}
          birth_date: {self.birth_date}
          death_date: {self.death_date}
          """

    def query(self):
        url = "https://id.loc.gov/authorities/names/{id}.json".format(id=self.id)
        response = requests.get(url, timeout=20)
        if response.status_code == 404:
            self.not_found = True
            return None

        payload = response.json()
        return payload

    def is_family_name_first_language(self, user_languages):
        family_name_first_languages = {"jpn", "kor", "chi", "zho", "vie", "khm"}
        return any(lang in family_name_first_languages for lang in user_languages)

    def name_order(self):
        print(f"LoC: language: {self.languages}")
        family_name_first = 0
        family_name_last = 0
        for src in self.sources:
            for n in self.name.family_name_first_en():
                if n in src:
                    family_name_first += 1
            for n in self.name.family_name_last_en():
                if n in src:
                    family_name_last += 1
        if family_name_first > family_name_last:
            print("LoC: family name FIRST based on sources")
            return name.NAME_ORDER_EASTERN
        elif family_name_first < family_name_last:
            print("LoC: family name LAST based on sources")
            return name.NAME_ORDER_WESTERN

        if self.is_family_name_first_language(self.languages):
            print("LoC: family name FIRST based on language")
            return name.NAME_ORDER_EASTERN

        # undetermined
        return ""

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

        element_list = []
        for p in data:
            if p["@id"] == "http://id.loc.gov/authorities/names/" + self.init_id:
                if "http://www.loc.gov/mads/rdf/v1#elementList" in p:
                    arr = p["http://www.loc.gov/mads/rdf/v1#elementList"]
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
                        "value": p["http://www.loc.gov/mads/rdf/v1#elementValue"][0][
                            "@value"
                        ],
                    }
                    name_parts.append(name_part)

        for p in data:
            if p["@id"] == "http://id.loc.gov/authorities/names/" + self.init_id:
                if "http://www.w3.org/2004/02/skos/core#prefLabel" in p:
                    pref_label = p["http://www.w3.org/2004/02/skos/core#prefLabel"][0][
                        "@value"
                    ]
                    if name_parts != []:
                        print(f"LoC: pref_label: {pref_label}")
                        print(f"LoC: name parts: {name_parts}")
                        for name_part in name_parts:
                            if (
                                name_part["type"]
                                != "http://www.loc.gov/mads/rdf/v1#FullNameElement"
                            ):
                                part = name_part["value"]
                                if part not in pref_label:
                                    raise ValueError(f"{part} not in {pref_label}")
                                pref_label = pref_label.replace(part, "", 1)
                        pref_label = pref_label.strip(" ,")
                    if self.name is None:
                        self.name = name.Name(name_en=pref_label)
            elif p["@id"] == "http://id.loc.gov/rwo/agents/" + self.init_id:
                if "http://www.loc.gov/mads/rdf/v1#birthDate" in p:
                    self.birth_date = p["http://www.loc.gov/mads/rdf/v1#birthDate"][0][
                        "@value"
                    ]
                if "http://www.loc.gov/mads/rdf/v1#deathDate" in p:
                    self.death_date = p["http://www.loc.gov/mads/rdf/v1#deathDate"][0][
                        "@value"
                    ]
            elif p["@id"].startswith("http://id.loc.gov/vocabulary/languages/"):
                lang = p["@id"].replace("http://id.loc.gov/vocabulary/languages/", "")
                self.languages.append(lang)
            elif "http://www.loc.gov/mads/rdf/v1#Source" in p["@type"]:
                if "http://www.loc.gov/mads/rdf/v1#citationSource" in p:
                    for s in p["http://www.loc.gov/mads/rdf/v1#citationSource"]:
                        if "@value" in s:
                            self.sources.append(s["@value"])
                if "http://www.loc.gov/mads/rdf/v1#citationNote" in p:
                    for s in p["http://www.loc.gov/mads/rdf/v1#citationNote"]:
                        if "@value" in s:
                            self.sources.append(s["@value"])

        if self.name is not None:
            self.name.name_order = self.name_order()

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
    # japanese: nr92043638
    # p = LocPage('n2011182115')
    # p = LocPage('no2012059592')
    # p = LocPage('nr93034015')
    # p = LocPage('no2014117435')

    # title: no93031097'
    # meerdere fullname: n2002066224; no2014117435; n81116002

    # error: no2016151337
    p = LocPage("n2002066224")

    p.run()
    print(p)


if __name__ == "__main__":
    main()
