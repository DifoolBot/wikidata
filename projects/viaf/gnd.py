import requests
import name as nm
import authdata

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
        self.countries = []

    def __str__(self):
        output = f"""
                init_id: {self.init_id}
                gnd: {self.id}
                not found: {self.not_found}
                redirect: {self.is_redirect}"""
        if self.name:
            output += f"""
                gender: {self.sex}
                name: {self.name.names_en()}
                country: {self.countries}
                given_name_en: {self.name.given_name_en} 
                family_name_en: {self.name.family_name_en}
                birth_date: {self.birth_date}
                death_date: {self.death_date}"""
        return output

    def query(self):
        url = f"https://hub.culturegraph.org/entityfacts/{self.id}"
        response = requests.get(url, timeout=20)
        if response.status_code == 404:
            self.not_found = True
            return None

        payload = response.json()
        return payload

    def get_name_order(self):
        lst = [
            "XB-KR",  # Korea (South)
            "XB-JP",  # Japan
            "XB-CN",  # China
            "XB-VN",  # Vietnam
            "XB-MO",  # Macau
            "XB-KP",  # Korea (North)
        ]
        if self.countries:
            print(f"GND: country: {self.countries}")
            for country in self.countries:
                if country in lst:
                    print("GND: family name FIRST based on country")
                    return nm.NAME_ORDER_EASTERN

        return nm.NAME_ORDER_UNDETERMINED

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

        parts = date_str.split(" ")
        if len(parts) == 1:
            year_str = parts[0]
            if year_str.startswith("XX.XX."):
                year_str = year_str[len("XX.XX.") :]

            # only year
            year = int(year_str)
            return str(year)
        elif len(parts) == 3:
            day = int(parts[0][:-1])  # Remove the trailing period
            month = month_mapping.get(parts[1])
            if not month:
                raise RuntimeError(f"Unrecognized month in date string: {date_str}")

            year = parts[2]
            return f"{year}-{month:02d}-{day:02d}"
        else:
            raise RuntimeError(f"Unrecognized date string: {date_str}")

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
                    raise RuntimeError("Not a person")
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
                    self.countries.append(
                        part["@id"].replace(
                            "https://d-nb.info/standards/vocab/gnd/geographic-area-code#",
                            "",
                        )
                    )

        if prefix:
            family_name = (prefix + " " + family_name).strip()
        self.name = nm.Name(
            name_en=pref_name, given_name_en=given_name, family_name_en=family_name
        )
        self.set_name_order(self.get_name_order())


def main() -> None:
    # japanese: 1033550817
    # chinese, gender: 1146362013
    # redirect: 1017872724
    # name with title: 1075339227
    # multiple countries: 17222246X

    p = GndPage("1017872723")
    p.run()
    print(p)


if __name__ == "__main__":
    main()
