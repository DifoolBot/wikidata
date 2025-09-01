from typing import Optional, Tuple

from pywikibot.data import sparql
from shared_lib.lookups.interfaces.place_lookup_interface import (
    CountryLookupInterface,
    PlaceLookupInterface,
)


class WikidataClient(PlaceLookupInterface, CountryLookupInterface):
    """Low-level client for querying Wikidata."""

    def get_place_by_qid(self, place_qid: str):
        """
        Given a Wikidata QID for a place, return the QID, label, and country label for its country (P17).
        Returns (country_qid, place_label, country_label) or None if not found.
        """
        query = f"""
                SELECT ?country ?placeLabel ?countryLabel WHERE {{
                    values ?place {{wd:{place_qid}}}
                    ?place wdt:P17 ?country.
                SERVICE wikibase:label {{ bd:serviceParam wikibase:language "[AUTO_LANGUAGE],en". }}
                }}
                """
        query_object = sparql.SparqlQuery()
        payload = query_object.query(query=query)
        if payload:
            for row in payload["results"]["bindings"]:
                country_qid = row["country"]["value"].split("/")[-1]
                place_label = row["placeLabel"]["value"]
                country_label = row["countryLabel"]["value"]
                return country_qid, place_label, country_label

        return None

    def get_country_by_qid(self, country_qid: Optional[str]):
        """
        Given a country QID, return its QID, ISO 3166-1 alpha-3 code, and English/multilingual label.
        Returns (country_qid, country_code, country_desc) or None if not found.
        """
        if not country_qid:
            return None

        query = f"""
                SELECT ?alpha3 ?label WHERE {{
                VALUES ?country {{ wd:{country_qid} }}  

                OPTIONAL {{ ?country wdt:P298 ?alpha3 }}  # ISO 3166-1 alpha-3 code
                OPTIONAL {{
                    ?country rdfs:label ?label
                    FILTER(LANG(?label) IN ("en", "mul"))
                }}
                }}
                """
        query_object = sparql.SparqlQuery()
        payload = query_object.query(query=query)
        if payload:
            for row in payload["results"]["bindings"]:
                if "alpha3" in row:
                    country_code = row["alpha3"]["value"]
                else:
                    country_code = ""
                country_label = row["label"]["value"]
                return country_qid, country_code, country_label

        return None

    def get_country_by_code(self, country_code: Optional[str]):
        """
        Given an ISO 3166-1 alpha-3 country code, return the country QID, code, and label.
        Returns (country_qid, country_code, country_desc) or None if not found.
        """
        if not country_code:
            return None

        query = f"""
                    SELECT DISTINCT ?country ?countryLabel WHERE {{
                    VALUES ?code {{"{country_code}"}}
                    ?country p:P298 ?statement0.
                    ?statement0 ps:P298 ?code.
                    ?country p:P31 ?statement1.
                    ?statement1 (ps:P31/(wdt:P279*)) wd:Q6256.
                    SERVICE wikibase:label {{ bd:serviceParam wikibase:language "mul,en". }}
                    }}
                """
        query_object = sparql.SparqlQuery()
        payload = query_object.query(query=query)
        if payload:
            for row in payload["results"]["bindings"]:
                country_qid = row["country"]["value"].split("/")[-1]
                country_label = row["countryLabel"]["value"]
                return country_qid, country_code, country_label

        return None

    def set_country(self, country_qid: str, country_code: str, country_label: str):
        raise NotImplementedError(
            "WikidataClient does not support setting country data."
        )

    def get_place_qid_by_desc(self, text: str) -> str:
        raise NotImplementedError(
            "WikidataClient does not support reverse place lookup by description."
        )

    def set_place(self, place_qid: str, country_qid: str, place_description: str):
        raise NotImplementedError("WikidataClient does not support setting place data.")
