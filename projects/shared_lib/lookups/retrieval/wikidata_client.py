from typing import Optional

from pywikibot.data import sparql

from shared_lib.lookups.interfaces.ecartico_lookup_interface import (
    EcarticoLookupInterface,
)
from shared_lib.lookups.interfaces.place_lookup_interface import (
    CountryLookupInterface,
    PlaceLookupInterface,
)

WD = "http://www.wikidata.org/entity/"

SKIP = "SKIP"
LEEG = "LEEG"
MULTIPLE = "MULTIPLE"


class WikidataClient(
    PlaceLookupInterface, CountryLookupInterface, EcarticoLookupInterface
):
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
                if row["country"]["type"] == "uri":
                    country_qid = row["country"]["value"].split("/")[-1]
                else:
                    # unknown; for example for 'at sea'
                    country_qid = None
                place_label = row["placeLabel"]["value"]
                # country_label = row["countryLabel"]["value"]
                return place_qid, country_qid, place_label

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
                country_code = row.get("alpha3", {}).get("value")
                country_label = row.get("label", {}).get("value")
                if not country_label:
                    country_label = country_qid
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

    def get_occupation(self, occupation_id: str) -> tuple[Optional[str], str]:
        raise NotImplementedError

    def get_place(self, place_id: str) -> tuple[Optional[str], str]:
        raise NotImplementedError

    def get_source(self, source_id: str) -> tuple[Optional[str], str]:
        raise NotImplementedError

    def get_patronym_qid(self, text: Optional[str]) -> Optional[str]:
        raise NotImplementedError

    def get_religion_qid(self, text: Optional[str]) -> Optional[str]:
        raise NotImplementedError

    def get_rkdimage_qid(self, rkdimage_id: str) -> Optional[str]:
        if not rkdimage_id:
            return None

        qry = f'SELECT DISTINCT ?item WHERE {{ ?item wdt:P350 "{rkdimage_id}". }}'
        qids = []
        query_object = sparql.SparqlQuery()
        payload = query_object.query(query=qry)
        if payload:
            for row in payload["results"]["bindings"]:
                qid = row.get("item", {}).get("value", "").replace(WD, "")
                qids.append(qid)

        if len(qids) > 1:
            qid = MULTIPLE
        elif len(qids) == 1:
            qid = qids[0]
        else:
            qid = None
        return qid

    def get_genre_qid(
        self, attribute: Optional[str], value: Optional[str]
    ) -> Optional[str]:
        raise NotImplementedError

    def get_person(self, ecartico_id: Optional[str]) -> Optional[tuple[str, str]]:
        qry = f'SELECT DISTINCT ?item WHERE {{ ?item wdt:P2915 "{ecartico_id}". }}'
        qids = []
        query_object = sparql.SparqlQuery()
        payload = query_object.query(query=qry)
        if payload:
            for row in payload["results"]["bindings"]:
                qid = row.get("item", {}).get("value", "").replace(WD, "")
                qids.append(qid)

        if len(qids) > 1:
            return MULTIPLE, ""
        elif len(qids) == 1:
            return qids[0], "?"
        else:
            return None

    def get_gutenberg_qid(self, ebook_id: Optional[str]) -> Optional[str]:
        if not ebook_id:
            return None

        qry = f"""SELECT DISTINCT ?item WHERE {{
            ?item p:P2034 ?statement0.
            ?statement0 ps:P2034 "{ebook_id}".
            }}
            LIMIT 2"""

        qids = []
        query_object = sparql.SparqlQuery()
        payload = query_object.query(query=qry)
        if payload:
            for row in payload["results"]["bindings"]:
                qid = row.get("item", {}).get("value", "").replace(WD, "")
                qids.append(qid)

        if len(qids) > 1:
            qid = MULTIPLE
        elif len(qids) == 1:
            qid = qids[0]
        else:
            qid = None
        return qid

    def get_rijksmuseum_qid(
        self, url: str, inventory_number: Optional[str]
    ) -> Optional[str]:
        if not inventory_number:
            return None

        qry = f"""SELECT DISTINCT ?item WHERE {{
            ?item p:P217 ?statement0.
            ?statement0 ps:P217 "{inventory_number}".
            ?item p:P195 ?statement1.
            ?statement1 ps:P195 wd:Q190804.
            }}
            LIMIT 2"""
        qids = []
        query_object = sparql.SparqlQuery()
        payload = query_object.query(query=qry)
        if payload:
            for row in payload["results"]["bindings"]:
                qid = row.get("item", {}).get("value", "").replace(WD, "")
                qids.append(qid)

        if len(qids) > 1:
            qid = MULTIPLE
        elif len(qids) == 1:
            qid = qids[0]
        else:
            qid = None
        return qid

    def get_occupation_type(self, qid: str) -> Optional[str]:
        raise NotImplementedError

    def is_possible(self, ecartico_id: Optional[str], qid: str) -> bool:
        raise NotImplementedError

    def get_description(self, qid: str) -> Optional[str]:
        query = f"""
            SELECT ?item ?itemLabel WHERE {{
            VALUES ?item {{wd:{qid}}}
            SERVICE wikibase:label {{ bd:serviceParam wikibase:language "nl,en,mul". }}
            }}
            """
        description = None
        query_object = sparql.SparqlQuery()
        payload = query_object.query(query=query)
        if payload:
            for row in payload["results"]["bindings"]:
                description = row.get("itemLabel", {}).get("value", "").replace(WD, "")
                break

        return description

    def get_is(self, qid: str, query: str) -> bool:
        qry = f"""
            SELECT DISTINCT ?item WHERE {{
            values ?item {{wd:{qid}}}
            ?item p:P31 ?statement0.
            ?statement0 (ps:P31/(wdt:P279*)) wd:{query}.
            }}
            """
        res = False
        query_object = sparql.SparqlQuery()
        payload = query_object.query(query=qry)
        if payload:
            for row in payload["results"]["bindings"]:
                found = row.get("item", {}).get("value", "").replace(WD, "")
                res = found == qid
                break

        return res
