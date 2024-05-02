import requests
import name as nm
import authdata
import languagecodes as lc

PID_GND_ID = "P227"
# see applicable 'stated in' value
QID_INTEGRATED_AUTHORITY_FILE = "Q36578"


class GndPage(authdata.AuthPage):
    def __init__(self, gnd_id: str):
        super().__init__(
            pid=PID_GND_ID,
            stated_in=QID_INTEGRATED_AUTHORITY_FILE,
            id=gnd_id,
            page_language="de",
        )

    def __str__(self):
        output = f"""
                init_id: {self.init_id}
                gnd: {self.id}
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
                cyrillic: {self.has_cyrillic_script()}"""
        return output

    def has_hebrew_script(self):
        if self.has_script(lc.is_hebrew):
            return True

        return False

    def has_cyrillic_script(self):
        if self.has_script(lc.is_cyrillic):
            return True

        return False

    def query(self):
        url = f"https://hub.culturegraph.org/entityfacts/{self.id}"
        response = requests.get(url, timeout=20)
        if response.status_code == 404:
            self.not_found = True
            return None

        payload = response.json()
        return payload

    def run(self):
        self.process(self.query())

    def get_short_desc(self) -> str:
        return "GND"

    def convert_date(self, date_str: str) -> str:
        month_mapping = {
            "Januar": 1,
            "Februar": 2,
            "März": 3,
            "April": 4,
            "Mai": 5,
            "Juni": 6,
            "Juli": 7,
            "August": 8,
            "September": 9,
            "Oktober": 10,
            "November": 11,
            "Dezember": 12,
        }

        if '?' in date_str:
            print(f'Skipped date {date_str}')
            return ''
        # 1320/1330
        if '/' in date_str:
            print(f'Skipped date {date_str}')
            return ''
        
        parts = date_str.split(" ")
        if len(parts) == 1:
            year_str = parts[0]
            if year_str.startswith("XX.XX."):
                year_str = year_str[len("XX.XX.") :]
            # 14XX
            if 'X' in year_str:
                print(f'Skipped date {year_str}')
                return ''

            # only year
            if not year_str.isdigit():
                raise RuntimeError('GND: Unrecognized year string {year_str}')
            year = int(year_str)
            return str(year)
        elif len(parts) == 3:
            day = int(parts[0][:-1])  # Remove the trailing period
            month = month_mapping.get(parts[1])
            if not month:
                raise RuntimeError(f"GND: Unrecognized month in date string: {date_str}")

            year = parts[2]
            return f"{year}-{month:02d}-{day:02d}"
        else:
            raise RuntimeError(f"GND: Unrecognized date string: {date_str}")

    def process(self, data):
        if data is None:
            return

        pref_name = ""
        family_name = ""
        prefix = ""
        given_name = ""

        for attr, value in data.items():
            # "@id": "https://d-nb.info/gnd/1016579004",
            if attr == "@id":
                self.id = value.replace("https://d-nb.info/gnd/", "")
                self.is_redirect = self.id != self.init_id
            elif attr == "preferredName":
                pref_name = value
            elif attr == "surname":
                family_name = value
            elif attr == "prefix":
                prefix = value
            elif attr == "forename":
                given_name = value
            elif attr == "@type":
                if value != "person":
                    raise RuntimeError("GND: Not a person")
            elif attr == "dateOfBirth":
                self.birth_date = self.convert_date(value)
            elif attr == "dateOfDeath":
                self.death_date = self.convert_date(value)
            elif attr == "gender":
                self.sex = value["@id"].replace(
                    "https://d-nb.info/standards/vocab/gnd/gender#", ""
                )
                print(f"GND: sex: {self.sex}")
            elif attr == "associatedCountry":
                for part in value:
                    url = part["@id"]
                    code = url.replace(
                            "https://d-nb.info/standards/vocab/gnd/geographic-area-code#",
                            "")
                    if code not in lc.gnd_country_dict:
                        raise RuntimeError(f"GND: Unknown country code {code}")
                    country = lc.gnd_country_dict[code]
                    if country:
                        self.countries.append(country)

        # todo ; als prefix dan nooit family name first?
        if prefix:
            family_name = (prefix + " " + family_name).strip()
        self.latin_name = nm.Name(
            name=pref_name, given_name=given_name, family_name=family_name
        )
        self.set_name_order(self.get_name_order())


def main() -> None:
    # japanese: 1033550817
    # chinese, gender: 1146362013
    # redirect: 1017872724
    # name with title: 1075339227
    # multiple countries: 17222246X
    # undif
    # error: 137661495 - Arnold, ter Hoernen
    # russian: 124071279; 118992309
    # family name with comma:  12140286X, 1023416093, 100975704

    p = GndPage("1023416093")
    p.run()
    print(p)


if __name__ == "__main__":
    main()
