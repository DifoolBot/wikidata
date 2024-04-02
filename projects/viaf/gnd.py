import requests
import name
import authdata

PID_GND_ID = 'P227'
# see applicable 'stated in' value
QID_INTEGRATED_AUTHORITY_FILE = 'Q36578'

class GndPage(authdata.AuthPage):
    def __init__(self, gnd_id: str):
        super().__init__(gnd_id, 'de')
        self.country = ''
        self.error = False

    def __str__(self):
        return f"""
          gnd: {self.id}
          not found: {self.not_found}
          redirect: {self.is_redirect}
          gender: {self.sex}
          name: {self.name.name_en()}
          country: {self.country}
          """

    def query(self):
        url = "https://hub.culturegraph.org/entityfacts/{id}".format(
            id=self.id
        )
        response = requests.get(url, timeout=20)
        if response.status_code == 404:
            self.not_found = True
            return None

        payload = response.json()
        return payload

    def name_order(self):
        lst = [
            'XB-KR',  # Zuid-Korea', True, 'ko', 'Q9176');
            'XB-JP',  # Japan', True, 'ja', 'Q5287');
            'XB-CN',  # China', True, 'zh', 'Q7850');
            'XB-VN',  # Vietnam', True, 'vi', 'Q9199');
            'XB-MO',  # Macau', True, 'zh'); // check
            'XB-KP'   # Korea', True, 'ko');
        ]
        if self.country:
            in_list = self.country in lst
            if in_list:
                print('GND: family name FIRST based on country')
                return name.NAME_ORDER_EASTERN

        return ''

    def run(self):
        self.process(self.query())

    def get_short_desc(self):
        return 'gnd'

    def convert_date(self, s: str) -> str:
        month_mapping = {
            'Januar': 1,
            'Februar': 2,
            'März': 3,
            'April': 4,
            'Mai': 5,
            'Juni': 6,
            'Juli': 7,
            'August': 8,
            'September': 9,
            'Oktober': 10,
            'November': 11,
            'Dezember': 12
        }

        parts = s.split(' ')
        if len(parts) == 1:
            # only year
            year = int(parts[0])
            return str(year)

        if len(parts) != 3:
            raise RuntimeError('Unrecognized date string: ' + s)

        day = int(parts[0][:-1])  # Remove the trailing period
        month = month_mapping.get(parts[1])
        if not month:
            raise RuntimeError('Unrecognized month in date string: ' + s)

        year = parts[2]
        return f'{year}-{month:02d}-{day:02d}'

    def process(self, data):
        if data is None:
            return

        pref_name = ''
        family_name = ''
        prefix = ''
        given_name = ''

        for attr, value in data.items():
            # "@id": "https://d-nb.info/gnd/1016579004",
            if attr == "@id":
                self.id = value.replace('https://d-nb.info/gnd/', '')
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
                    self.error = True
            elif attr == "dateOfBirth":
                self.birth_date = self.convert_date(value)
            elif attr == "dateOfDeath":
                self.death_date = self.convert_date(value)
            elif attr == "gender":
                self.sex = value["@id"].replace(
                    'https://d-nb.info/standards/vocab/gnd/gender#', '')
                print(f'GND: sex: {self.sex}')
            elif attr == "associatedCountry":
                self.country = value[0]["@id"].replace(
                    'https://d-nb.info/standards/vocab/gnd/geographic-area-code#', '')

        if prefix:
            family_name = (prefix + ' ' + family_name).strip()
        self.name = name.Name(
            name_en=pref_name, given_name_en=given_name, family_name_en=family_name)
        self.name.name_order = self.name_order()

    def get_ref(self):
        res = {
            'id_pid': PID_GND_ID,
            'stated in': QID_INTEGRATED_AUTHORITY_FILE,
            'id': self.id
        }
        return res


def main() -> None:
    # 1016579004
    # 1033550817 japanese
    # 1146362013  chinese; gender

    # p = GndPage('1146362013')
    # p.run()
    # print(p)

    # 1075339227 title ha-Kohen
    p = GndPage('1075339227')
    p.run()
    print(p)


if __name__ == "__main__":
    main()
