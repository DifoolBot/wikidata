"""GND (Deutsche Nationalbibliothek) authority record (DNB SPARQL)."""

import shared_lib.constants as wd
from shared_lib.rate_limiter import rate_limit

import addlabel.countries as countries
import addlabel.person_name as pn
from addlabel.authority_page import AuthorityPage
from addlabel.countries import Countries
from addlabel.http_client import http_get
from addlabel.languages import Languages

GND_SLEEP_AFTER_ERROR = 2 * 60  # sec

URL_GND = "https://d-nb.info/gnd/"
URL_GND_GENDER = "https://d-nb.info/standards/vocab/gnd/gender#"
URL_GND_AREACODE = "https://d-nb.info/standards/vocab/gnd/geographic-area-code#"
URL_SPARQL = "https://sparql.dnb.de/api/gnd"

GNDO_PREFIX = "https://d-nb.info/standards/elementset/gnd#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

GERMAN_MONTHS = {
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


class GndPage(AuthorityPage):
    def __init__(
        self,
        gnd_id: str,
        language_lookup: Languages,
        country_lookup: Countries,
    ):
        super().__init__(
            pid=wd.PID_GND_ID,
            stated_in_qid=wd.QID_INTEGRATED_AUTHORITY_FILE,
            external_id=gnd_id,
            page_language="de",
            language_lookup=language_lookup,
            country_lookup=country_lookup,
        )

    def __str__(self):
        output = f"""
                init_id: {self.initial_external_id}
                gnd: {self.external_id}
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
                countries: {self.country_codes()}
                languages: {self.language_codes()}
                hebrew: {self.has_hebrew_script()}
                cyrillic: {self.has_cyrillic_script()}
                non latin: {self.has_non_latin_script()}"""
        return output

    def get_short_desc(self) -> str:
        return "GND"

    @rate_limit(30)
    def query(self):
        """
        Run two SPARQL queries against the DNB SPARQL endpoint:
          1. Fetch all direct triples for the person.
          2. Fetch name-part triples (forename, surname, prefix) from the
             preferredNameEntityForThePerson blank node.

        Returns a dict with keys 'direct' and 'name_parts', each holding
        the parsed SPARQL JSON result, or None on 404.
        """
        person_uri = f"{URL_GND}{self.initial_external_id}"

        query_direct = f"""
PREFIX gndo: <{GNDO_PREFIX}>
SELECT ?p ?o WHERE {{
  <{person_uri}> ?p ?o .
}}
"""
        query_name_parts = f"""
PREFIX gndo: <{GNDO_PREFIX}>
SELECT ?p ?o WHERE {{
  <{person_uri}> gndo:preferredNameEntityForThePerson ?nameNode .
  ?nameNode ?p ?o .
}}
"""
        results = {}
        for key, sparql in (
            ("direct", query_direct),
            ("name_parts", query_name_parts),
        ):
            response = http_get(
                "GND",
                URL_SPARQL,
                params={
                    "query": sparql,
                    "format": "application/sparql-results+json",
                },
                sleep_after_error=GND_SLEEP_AFTER_ERROR,
            )

            if response.status_code == 429:
                print("*** 429: Too Many Requests ***")
                raise RuntimeError("GND Connection error 429: Too Many Requests")

            if response.status_code == 404:
                self.not_found = True
                return None

            if response.status_code != 200:
                raise RuntimeError(
                    f"GND SPARQL error {response.status_code}: {response.text[:200]}"
                )

            results[key] = response.json()

        # 404-equivalent: person has no triples at all
        if not results["direct"].get("results", {}).get("bindings"):
            self.not_found = True
            return None

        return results

    def run(self):
        self.process(self.query())

    @staticmethod
    def sparql_rows(payload, key):
        """Yield (predicate_localname, value, predicate_uri) triples from the
        SPARQL JSON."""
        bindings = payload[key]["results"]["bindings"]
        for row in bindings:
            pred_uri = row["p"]["value"]  # full URI
            obj_val = row["o"]["value"]
            # strip namespace to get a comparable local name
            local = pred_uri.split("#")[-1].split("/")[-1]
            yield local, obj_val, pred_uri

    def convert_date(self, date_str: str) -> str:
        """Convert GND date strings ("1956", "XX.XX.1956", "3. März 1956") to
        "YYYY[-MM-DD]"; returns "" for imprecise dates."""
        if "?" in date_str or "/" in date_str:
            print(f"Skipped date {date_str}")
            return ""

        parts = date_str.split(" ")
        if len(parts) == 1:
            year_str = parts[0]
            if year_str.startswith("XX.XX."):
                year_str = year_str[len("XX.XX.") :]
            if "X" in year_str:
                print(f"Skipped date {year_str}")
                return ""
            if not year_str.isdigit():
                raise RuntimeError(f"GND: Unrecognized year string {year_str}")
            return str(int(year_str))
        elif len(parts) == 3:
            day = int(parts[0][:-1])
            month = GERMAN_MONTHS.get(parts[1])
            if not month:
                raise RuntimeError(
                    f"GND: Unrecognized month in date string: {date_str}"
                )
            return f"{parts[2]}-{month:02d}-{day:02d}"
        else:
            raise RuntimeError(f"GND: Unrecognized date string: {date_str}")

    def process(self, data):
        if data is None:
            return

        pref_name = ""
        family_name = ""
        prefix = ""
        given_name = ""

        for local, value, full_uri in self.sparql_rows(data, "direct"):

            if local == "gndIdentifier":
                # detect redirects: the canonical GND id may differ from the
                # one we requested
                self.external_id = value
                self.is_redirect = value != self.initial_external_id

            elif local == "type":
                # RDF type URI, e.g. gndo:DifferentiatedPerson
                type_local = value.split("#")[-1].split("/")[-1]
                # accept any Person subtype; reject non-persons
                if "Person" not in type_local and full_uri == RDF_TYPE:
                    raise RuntimeError(f"GND: Not a person: {value}")

            elif local == "preferredNameForThePerson":
                pref_name = value

            elif local == "dateOfBirth":
                self.birth_date = self.convert_date(value)

            elif local == "dateOfDeath":
                self.death_date = self.convert_date(value)

            elif local == "gender":
                # value is a full URI, e.g. .../gnd/gender#male
                self.sex = value.replace(URL_GND_GENDER, "")
                print(f"GND: sex: {self.sex}")

            elif local == "geographicAreaCode":
                code = value.replace(URL_GND_AREACODE, "")
                if code not in countries.gnd_country_dict:
                    raise RuntimeError(f"GND: Unknown country code {code}")
                self.add_country(countries.gnd_country_dict[code])

        for local, value, _ in self.sparql_rows(data, "name_parts"):
            if local == "forename":
                given_name = value
            elif local == "surname":
                family_name = value
            elif local == "prefix":
                prefix = value

        if prefix:
            if prefix.endswith("'"):
                family_name = (prefix + family_name).strip()
            else:
                family_name = (prefix + " " + family_name).strip()
            self.has_prefix = True

        self.latin_name = pn.PersonName(
            name=pref_name, given_name=given_name, family_name=family_name
        )
        self.set_name_order(self.determine_name_order())


def main() -> None:
    p = GndPage(
        "1146362013",
        language_lookup=Languages(),
        country_lookup=Countries(),
    )
    p.run()
    print(p)


if __name__ == "__main__":
    main()
