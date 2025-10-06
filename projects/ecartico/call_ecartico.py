import os.path
import re
from pathlib import Path
from typing import Dict, List, Optional, Set
from abc import ABC, abstractmethod

import pywikibot as pwb
import requests
from bs4 import BeautifulSoup, Tag
from ecartico.ecartico_structure import EcarticoStructure
from pywikibot import pagegenerators
from pywikibot.data import sparql

from shared_lib.lookups.interfaces.ecartico_lookup_interface import (
    EcarticoLookupAddInterface,
)
import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd
from shared_lib.rate_limiter import rate_limit
from shared_lib.lookups.impl.cached_ecartico_lookup import CachedEcarticoLookup
from shared_lib.lookups.retrieval.ecartico_cache import EcarticoCache
from shared_lib.lookups.retrieval.ecartico_client import EcarticoClient
from shared_lib.lookups.retrieval.wikidata_client import WikidataClient


WD = "http://www.wikidata.org/entity/"

SKIP = "SKIP"
LEEG = "LEEG"
MULTIPLE = "MULTIPLE"

CACHE_DIR = Path("ecartico_cache")
CACHE_DIR.mkdir(exist_ok=True)


SITE = pwb.Site("wikidata", "wikidata")
SITE.login()
SITE.get_tokens("csrf")
REPO = SITE.data_repository()


# @rate_limit
def get_html_content_from_url(url: str) -> str:
    response = requests.get(url)
    if response.status_code == 200:
        return response.text
        # Continue with extraction as shown above...
    else:
        raise RuntimeError(
            f"Failed to retrieve the webpage. Status code: {response.status_code}"
        )


def get_html_content(ecartico_id: str) -> str:
    # Define the subdirectory and file name based on the ecartico_id
    subdirectory = "ecartico"
    file_name = f"{ecartico_id}.html"
    file_path = os.path.join(subdirectory, file_name)
    url = f"https://ecartico.org/persons/{ecartico_id}"

    # Check if the file already exists in the subdirectory
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as infile:
            html_content = infile.read()
            return html_content

    # Create the subdirectory if it doesn't exist
    if not os.path.exists(subdirectory):
        os.makedirs(subdirectory)

    # Get the HTML content from the URL
    html_content = get_html_content_from_url(url)

    # Write the HTML content to the file
    with open(file_path, "w", encoding="utf-8") as infile:
        infile.write(html_content)

    return html_content


class EcarticoStatusTracker(ABC):
    @abstractmethod
    def is_done(self, qid: str) -> bool:
        """Return True if the item is already marked as done."""
        pass

    @abstractmethod
    def mark_done(self, qid: str, message: str):
        """Mark the item as done."""
        pass

    @abstractmethod
    def mark_error(self, qid: str, error: str):
        """Mark the item as errored, with an error message."""
        pass

    @abstractmethod
    def is_error(self, qid: str) -> bool:
        """Return True if the item is marked as errored."""
        pass


class EcarticoBot:
    def __init__(
        self,
        generator,
        lookup_add: EcarticoLookupAddInterface,
        tracker: EcarticoStatusTracker,
        ignore_done_list: bool = False,
        ignore_error_list: bool = False,
    ):
        self.generator = pagegenerators.PreloadingEntityGenerator(generator)
        self.lookup_add = lookup_add
        self.tracker = tracker
        self.ignore_done_list = ignore_done_list
        self.ignore_error_list = ignore_error_list
        self.structure: Optional[EcarticoStructure] = None
        self.test = True

    def run(self):
        """
        Runs the bot on all items from the generator.
        """
        for item in self.generator:
            self.item = item
            self.examine_item()

    def examine(self, qid: str, ecartico_id: Optional[str] = None):
        self.item = pwb.ItemPage(REPO, qid)
        self.ecartico_id = ecartico_id
        self.examine_item()

    def is_ignore(self, ecartico_id: str) -> bool:

        ignore = [
            972,  # dubbele; stond verkeerd in wikidata
            1336,
            52985,  # achternaam als voornaam
            5927,  # man/vrouw
            4871,  # man/vrouw
            29909,  # moeder onduidelijk
            29025,  # einddatum > begindatum
            51899,  # verkeerde image; uitzoeken
            # 51273, # or datum
            45573,
        ]
        return ecartico_id in ignore

    def examine_item(self):
        self.structure = EcarticoStructure(qid=self.item.title())

        if not self.ignore_error_list and self.tracker.is_error(
            self.structure.qid or ""
        ):
            print(f"{self.structure.qid}: skipped, in error list")
            return

        if not self.ignore_done_list and self.tracker.is_done(self.structure.qid or ""):
            print(f"{self.structure.qid}: skipped, in done list")
            return

        if not self.item.exists():
            # mark this page as done and remove old errors from the log
            self.tracker.mark_done(self.structure.qid or "", "Does not exists")
            return

        if self.item.isRedirectPage():
            # mark this page as done and remove old errors from the log
            self.tracker.mark_done(self.structure.qid or "", "redirect")
            return

        claims = self.item.get().get("claims")
        if not claims:
            raise RuntimeError(
                f"Skipping {self.structure.qid} because it has no claims"
            )

        if not self.item.botMayEdit():
            raise RuntimeError(
                f"Skipping {self.structure.qid} because it cannot be edited by bots"
            )

        try:
            if self.ecartico_id is None:
                if wd.PID_ECARTICO_PERSON_ID not in claims:
                    self.tracker.mark_done(
                        self.structure.qid or "", "No ecartico person id"
                    )
                    return

                self.ecartico_id = None
                for claim in claims[wd.PID_ECARTICO_PERSON_ID]:
                    if claim.getRank() == "deprecated":
                        continue
                    current_target_id = claim.getTarget()
                    if (
                        self.ecartico_id
                        and current_target_id
                        and self.ecartico_id != current_target_id
                    ):
                        raise RuntimeError("Multiple ecartico ids")
                    if current_target_id:
                        self.ecartico_id = current_target_id

            if not self.ecartico_id:
                raise RuntimeError("No ecartico id")

            if self.is_ignore(self.ecartico_id):
                raise RuntimeError(
                    f"Ecartco id {self.ecartico_id} is on the ignore list"
                )

            self.structure.ecartico_id = self.ecartico_id
            if self.structure.qid != "Q13406268":
                self.lookup_add.add_person_qid(
                    self.structure.ecartico_id, None, self.structure.qid
                )
            print("")
            print(f"== {self.structure.qid} - {self.structure.ecartico_id} ==")
            print("")
            self.load()
            if self.structure.qid != "Q13406268":
                self.lookup_add.add_person_qid(
                    self.structure.ecartico_id,
                    self.structure.names[0],
                    self.structure.qid,
                )
            self.structure.print()

            wikidata = cwd.WikiDataPage(self.item, test=self.test)

            print("--")
            self.structure.apply(self.lookup_add, wikidata)

            self.tracker.mark_done(self.structure.qid or "", "done")
        except RuntimeError as e:
            print(f"{self.structure.qid}: Runtime error: {e}")
            self.tracker.mark_error(self.structure.qid or "", e.__repr__())
        except Exception as e:
            print(f"{self.structure.qid}: Error: {e}")
            self.tracker.mark_error(self.structure.qid or "", e.__repr__())

    def get_url(self) -> str:
        if not self.structure or not self.structure.ecartico_id:
            raise RuntimeError("No ecartico_id")
        return f"https://ecartico.org/persons/{self.structure.ecartico_id}"

    def get_file_path(self):
        if not self.structure or not self.structure.ecartico_id:
            raise RuntimeError("No ecartico_id")

        cache_file = CACHE_DIR / f"{self.structure.ecartico_id}.html"
        return cache_file

    def get_html_content(self) -> str:
        # Define the subdirectory and file name based on the ecartico_id
        file_path = self.get_file_path()

        # Check if the file already exists in the subdirectory
        if file_path.exists():
            with open(file_path, "r", encoding="utf-8") as infile:
                html_content = infile.read()
                return html_content

        # Get the HTML content from the URL
        html_content = get_html_content_from_url(self.get_url())

        # Write the HTML content to the file
        with open(file_path, "w", encoding="utf-8") as infile:
            infile.write(html_content)

        return html_content

    def load(self):
        html_content = self.get_html_content()
        if not html_content:
            return

        # if "balat.kikirpa.be" in html_content:
        #     raise RuntimeError("balat.kikirpa.be")

        # Q433522
        # if "sources/3174" in html_content:
        #     raise RuntimeError("sources/3174")

        soup = BeautifulSoup(html_content, "html.parser")
        if not self.structure:
            raise RuntimeError("No structure")
        self.structure.parse(soup)

    # def get_description(self, qid: str) -> Optional[str]:
    #     query = f"""
    #         SELECT ?item ?itemLabel WHERE {{
    #         VALUES ?item {{wd:{qid}}}
    #         SERVICE wikibase:label {{ bd:serviceParam wikibase:language "nl,en,mul". }}
    #         }}
    #         """
    #     description = None
    #     query_object = sparql.SparqlQuery()
    #     payload = query_object.query(query=query)
    #     if payload:
    #         for row in payload["results"]["bindings"]:
    #             description = row.get("itemLabel", {}).get("value", "").replace(WD, "")
    #             break

    #     return description

    # def get_is(self, qid: str, query: str) -> bool:
    #     qry = f"""
    #         SELECT DISTINCT ?item WHERE {{
    #         values ?item {{wd:{qid}}}
    #         ?item p:P31 ?statement0.
    #         ?statement0 (ps:P31/(wdt:P279*)) wd:{query}.
    #         }}
    #         """
    #     res = False
    #     query_object = sparql.SparqlQuery()
    #     payload = query_object.query(query=query)
    #     if payload:
    #         for row in payload["results"]["bindings"]:
    #             found = row.get("item", {}).get("value", "").replace(WD, "")
    #             res = found == qid
    #             break

    #     return res

    # def get_qids_from_ecartico_id(self, ecartico_id: str) -> List[str]:
    #     qry = f'SELECT DISTINCT ?item WHERE {{ ?item wdt:P2915 "{ecartico_id}". }}'
    #     qids = []
    #     query_object = sparql.SparqlQuery()
    #     payload = query_object.query(query=qry)
    #     if payload:
    #         for row in payload["results"]["bindings"]:
    #             qid = row.get("item", {}).get("value", "").replace(WD, "")
    #             qids.append(qid)

    #     return qids

    # def get_qids_from_rijksmuseum_inventory_number(
    #     self, inventory_number: str
    # ) -> List[str]:
    #     qry = f"""SELECT DISTINCT ?item WHERE {{
    #         ?item p:P217 ?statement0.
    #         ?statement0 ps:P217 "{inventory_number}".
    #         ?item p:P195 ?statement1.
    #         ?statement1 ps:P195 wd:Q190804.
    #         }}
    #         LIMIT 2"""
    #     qids = []
    #     query_object = sparql.SparqlQuery()
    #     payload = query_object.query(query=qry)
    #     if payload:
    #         for row in payload["results"]["bindings"]:
    #             qid = row.get("item", {}).get("value", "").replace(WD, "")
    #             qids.append(qid)

    #     return qids

    # def get_qids_from_gutenberg_ebook_id(self, ebook_id: str) -> List[str]:
    #     qry = f"""SELECT DISTINCT ?item WHERE {{
    #         ?item p:P2034 ?statement0.
    #         ?statement0 ps:P2034 "{ebook_id}".
    #         }}
    #         LIMIT 2"""

    #     qids = []
    #     query_object = sparql.SparqlQuery()
    #     payload = query_object.query(query=qry)
    #     if payload:
    #         for row in payload["results"]["bindings"]:
    #             qid = row.get("item", {}).get("value", "").replace(WD, "")
    #             qids.append(qid)

    #     return qids

    # def get_qids_from_rkdimage_id(self, rkdimage_id: str) -> List[str]:
    #     qry = f'SELECT DISTINCT ?item WHERE {{ ?item wdt:P350 "{rkdimage_id}". }}'
    #     qids = []
    #     query_object = sparql.SparqlQuery()
    #     payload = query_object.query(query=qry)
    #     if payload:
    #         for row in payload["results"]["bindings"]:
    #             qid = row.get("item", {}).get("value", "").replace(WD, "")
    #             qids.append(qid)

    #     return qids

    # def get_person_qid(self, ecartico_id: str) -> Optional[str]:

    #     qid = self.cached_data.get_person_qid(ecartico_id)
    #     if not qid:
    #         # load from ecartico
    #         complete_url = f"https://ecartico.org/persons/{ecartico_id}"
    #         qid, description = self.extract_qid_from_ecartico_page(complete_url)
    #         if qid and qid.startswith("Q"):
    #             self.cached_data.add_person_qid(ecartico_id, description, qid)
    #             return qid

    #         # load from wikidata
    #         qids = self.get_qids_from_ecartico_id(ecartico_id)
    #         if len(qids) > 1:
    #             qid = MULTIPLE
    #         elif not qids:
    #             qid = SKIP
    #         else:
    #             qid = qids[0]
    #         self.cached_data.add_person_qid(ecartico_id, description, qid)

    #     if qid == SKIP:
    #         return None
    #     if qid and qid.startswith("Q"):
    #         return qid

    #     raise RuntimeError(f"unrecognized person qid: {ecartico_id} -> {qid}")

    # def extract_qid_from_ecartico_page(self, url: str):
    #     html_content = get_html_content_from_url(url)
    #     soup = BeautifulSoup(html_content, "html.parser")

    #     h1 = soup.find("h1")
    #     if not h1:
    #         raise RuntimeError(f"No <h1> found in {url}")
    #     description = h1.text
    #     if "/sources/" in url:
    #         title_elem = soup.find("td", property="schema:name")
    #         if title_elem:
    #             title = title_elem.get_text()
    #             # Replace tabs with a single space
    #             title = title.replace("\t", " ")
    #             # Replace double spaces with a single space
    #             title = " ".join(title.split())
    #             description = title

    #     # Find the <h2> tag with "External resources"
    #     external_header = soup.find("h2", string="External identifiers")
    #     if not external_header:
    #         external_header = soup.find("h2", string="External resources")
    #     if not external_header:
    #         external_header = soup.find("h2", string="References")
    #     if external_header:

    #         # Initialize a list to store URLs
    #         urls = []

    #         # Find the next <ul> after the <h2> "External resources"
    #         next_ul = external_header.find_next("ul")
    #         if not next_ul:
    #             raise RuntimeError(f"No <ul> found after 'External resources' in {url}")

    #         # cast next_ul to Tag
    #         if not isinstance(next_ul, Tag):
    #             raise RuntimeError("next_ul is not a Tag")

    #         # Extract all URLs from <a> tags within the <ul>
    #         for a_tag in next_ul.find_all("a", href=True):
    #             if not isinstance(a_tag, Tag):
    #                 raise RuntimeError("a_tag is not a Tag")
    #             href = a_tag["href"]
    #             if not isinstance(href, str):
    #                 raise RuntimeError("href is not a string")
    #             url = href
    #             urls.append(url)

    #         # Print the extracted URLs
    #         for url in urls:
    #             prefix = "http://www.wikidata.org/entity/"
    #             if url.startswith(prefix):
    #                 qid = url[len(prefix) :]
    #                 return qid, description
    #             prefix = "https://www.wikidata.org/wiki/"
    #             if url.startswith(prefix):
    #                 qid = url[len(prefix) :]
    #                 return qid, description
    #             if "wikidata" in url:
    #                 raise RuntimeError(f"Unrecognized wikidata url {url}")

    #     return None, description

    # def get_place_qid(self, place_id: str) -> Optional[str]:
    #     qid = self.cached_data.get_place_qid(place_id)
    #     if not qid:
    #         # load
    #         complete_url = f"https://ecartico.org/places/{place_id}"
    #         qid, description = self.extract_qid_from_ecartico_page(complete_url)
    #         if not qid:
    #             qid = LEEG
    #         self.cached_data.add_place_qid(place_id, description, qid)

    #     if qid == SKIP:
    #         return None
    #     if qid and qid.startswith("Q"):
    #         return qid

    #     raise RuntimeError(f"unrecognized place qid: {place_id} -> {qid}")

    # def get_rkdimage_qid(self, rkdimage_id: str) -> Optional[str]:
    #     qid = self.cached_data.get_rkdimage_qid(rkdimage_id)
    #     if not qid:
    #         # load
    #         qids = self.get_qids_from_rkdimage_id(rkdimage_id)
    #         if len(qids) > 1:
    #             qid = MULTIPLE
    #         elif not qids:
    #             qid = SKIP
    #         else:
    #             qid = qids[0]
    #         self.cached_data.add_rkdimage_qid(rkdimage_id, qid)

    #     if qid == SKIP:
    #         return None
    #     if qid and qid.startswith("Q"):
    #         return qid

    #     raise RuntimeError(f"unrecognized rkdimage qid: {rkdimage_id} -> {qid}")

    # def get_religion_qid(self, text: str) -> Optional[str]:
    #     qid = self.cached_data.get_religion_qid(text)
    #     if not qid:
    #         qid = LEEG
    #         self.cached_data.add_religion_qid(text, qid)

    #     if qid == SKIP:
    #         return None
    #     if qid and qid.startswith("Q"):
    #         return qid

    #     raise RuntimeError(f"unrecognized religion qid: {text} -> {qid}")

    # def get_patronym_qid(self, text: str) -> Optional[str]:
    #     qid = self.cached_data.get_patronym_qid(text)
    #     if not qid:
    #         qid = LEEG
    #         self.cached_data.add_patronym_qid(text, qid)

    #     if qid == SKIP:
    #         return None
    #     if qid and qid.startswith("Q"):
    #         return qid

    #     raise RuntimeError(f"unrecognized patronym qid: {text} -> {qid}")

    # def get_occupation_qid(self, occupation_id: str) -> Optional[str]:
    #     qid = self.cached_data.get_occupation_qid(occupation_id)

    #     if not qid:
    #         # load
    #         complete_url = f"https://ecartico.org/occupations/{occupation_id}"
    #         qid, description = self.extract_qid_from_ecartico_page(complete_url)
    #         if not qid:
    #             qid = LEEG
    #         self.cached_data.add_occupation_qid(occupation_id, description, qid)

    #     if qid == SKIP:
    #         return None
    #     if qid and qid.startswith("Q"):
    #         return qid

    #     raise RuntimeError(f"unrecognized occupation qid: {occupation_id} -> {qid}")

    # def get_source_qid(self, source_id: str) -> Optional[str]:

    #     qid = self.cached_data.get_source_qid(source_id)
    #     if not qid:
    #         # load
    #         complete_url = f"https://ecartico.org/sources/{source_id}"
    #         qid, description = self.extract_qid_from_ecartico_page(complete_url)
    #         if not qid:
    #             qid = LEEG
    #         self.cached_data.add_source_qid(source_id, description, qid)

    #     if qid == SKIP:
    #         return None
    #     if qid and qid.startswith("Q"):
    #         return qid

    #     # todo; tijdelijk
    #     return None
    #     # raise RuntimeError(f"unrecognized source qid: {source_id} -> {qid}")

    # def get_genre_qid(self, attribute: str, value: str) -> Optional[str]:
    #     qid = self.cached_data.get_genre_qid(attribute, value)

    #     if not qid:
    #         qid = LEEG
    #         self.cached_data.add_genre_qid(attribute, value, qid)

    #     if qid == SKIP:
    #         return None
    #     if qid and qid.startswith("Q"):
    #         return qid

    #     raise RuntimeError(f"unrecognized genre qid: {attribute} {value} -> {qid}")

    def get_redirect_url(self, url):
        try:
            response = requests.head(url, allow_redirects=True)
            return response.url
        except requests.RequestException as e:
            print(f"Error: {e}")
            return None

    # def get_rijksmuseum_inventory_number(self, url: str) -> str:
    #     match = re.search(
    #         r"^https?:\/\/www.rijksmuseum\.nl\/nl\/zoeken\/objecten\?q=([A-Z0-9.-]+)",
    #         url,
    #         re.IGNORECASE,
    #     )
    #     if not match:
    #         raise RuntimeError(f"Unexpected url {url}")
    #     inventory_number = match.group(1)

    #     return inventory_number

    # def get_rijksmuseum_inventory_number_qid(
    #     self, inventory_number: str
    # ) -> Optional[str]:
    #     qid = self.cached_data.get_qid_from_rijksmuseum_inventory_number(
    #         inventory_number
    #     )
    #     if not qid:
    #         # load from wikidata
    #         qids = self.get_qids_from_rijksmuseum_inventory_number(inventory_number)
    #         if len(qids) > 1:
    #             qid = MULTIPLE
    #         elif not qids:
    #             qid = SKIP
    #         else:
    #             qid = qids[0]
    #         self.cached_data.add_rijksmuseum_inventory_number_qid(inventory_number, qid)

    #     if qid == SKIP:
    #         return None
    #     if qid and qid.startswith("Q"):
    #         return qid

    #     raise RuntimeError(
    #         f"unrecognized rijksmuseum_inventory_number qid: {inventory_number} -> {qid}"
    #     )

    # def get_rijksmuseum_qid(self, url: str, inventory_number: str) -> Optional[str]:
    #     if not inventory_number:
    #         inventory_number = self.get_rijksmuseum_inventory_number(url)

    #     return self.get_rijksmuseum_inventory_number_qid(inventory_number)

    # def get_gutenberg_qid(self, ebook_id: str):
    #     qid = self.cached_data.get_qid_from_gutenberg_ebook_id(ebook_id)
    #     if not qid:
    #         # load from wikidata
    #         qids = self.get_qids_from_gutenberg_ebook_id(ebook_id)
    #         if len(qids) > 1:
    #             qid = MULTIPLE
    #         elif not qids:
    #             qid = SKIP
    #         else:
    #             qid = qids[0]
    #         self.cached_data.add_gutenberg_ebook_id_qid(ebook_id, qid)

    #     if qid == SKIP:
    #         return None
    #     if qid and qid.startswith("Q"):
    #         return qid

    # def get_occupation_type(self, qid: str) -> Optional[str]:
    #     text = self.cached_data.get_occupation_type(qid)
    #     if text == LEEG:
    #         return None
    #     if text:
    #         return text

    #     # load
    #     description = self.get_description(qid)

    #     types = []

    #     if self.get_is(qid, wd.QID_POSITION):
    #         types.append("Position")
    #     if self.get_is(qid, wd.QID_NOBLE_TITLE):
    #         types.append("NobleTitle")
    #     if self.get_is(qid, wd.QID_OCCUPATION):
    #         types.append("Occupation")

    #     text = "+".join(types) if types else LEEG

    #     self.cached_data.add_occupation_type(qid, description, text)
    #     return text

    # def add_is_possible(self, ecartico_id: str, qid: str):
    #     self.cached_data.add_is_possible(ecartico_id, qid)

    # def is_possible(self, ecartico_id: str, qid: str) -> bool:
    #     return self.cached_data.is_possible(ecartico_id, qid)


def try_one(
    lookup_add: EcarticoLookupAddInterface,
    tracker: EcarticoStatusTracker,
    qid: str,
    ecartico_id: Optional[str] = None,
):
    bot = EcarticoBot(
        None, lookup_add, tracker, ignore_done_list=True, ignore_error_list=True
    )
    bot.examine(qid, ecartico_id=ecartico_id)


def iterate_all(lookup_add: EcarticoLookupAddInterface, tracker: EcarticoStatusTracker):
    qry = """SELECT distinct ?item  WHERE {
      ?item wdt:P2915 ?ecartico_id.
        } limit 1000
        """
    p = pagegenerators.WikidataSPARQLPageGenerator(qry, site=REPO)
    generator = pagegenerators.PreloadingEntityGenerator(p)

    bot = EcarticoBot(generator, lookup_add, tracker)
    bot.ignore_error_list = True
    bot.ignore_done_list = False
    bot.run()
    # for row in query_wdqs(qry):
    #     qid = row.get("item", {}).get("value", "").replace(WD, "")
    #     ecartico_id = row.get("ecartico_id", {}).get("value", "")
    #     if data.has_done(ecartico_id):
    #         continue
    #     try_one(data, ecartico_id, qid)


def sync_occupation(lookup_add: EcarticoLookupAddInterface):
    print("sync occupations")
    # Open the file in read mode
    with open(
        r"D:\projects\wikidata\Win32\Debug\cache\occupations.txt", "r", encoding="utf-8"
    ) as file:
        # Read each line in the file
        for line in file:
            # Process the line (e.g., print it)
            s = line.strip()
            match = re.search(r"^(\d+)=([A-Z0-9]+)", s, re.IGNORECASE)
            if not match:
                continue
            id = match.group(1)
            code = match.group(2)
            current = lookup_add.get_occupation_qid(id)
            if current == LEEG:
                if code == SKIP:
                    lookup_add.add_occupation(id, "", "SKIP")
                    print(f"{id} -> SKIP")
                elif code.startswith("Q"):
                    lookup_add.add_occupation(id, "", code)
                    print(f"{id} -> {code}")


def sync_source(lookup_add: EcarticoLookupAddInterface):
    print("sync sources")
    # Open the file in read mode
    with open(
        r"D:\projects\wikidata\Win32\Debug\cache\books.txt", "r", encoding="utf-8"
    ) as file:
        # Read each line in the file
        for line in file:
            # Process the line (e.g., print it)
            s = line.strip()
            match = re.search(r"^(\d+)=([A-Z0-9]+)", s, re.IGNORECASE)
            if not match:
                continue
            id = match.group(1)
            code = match.group(2)
            current = lookup_add.get_source_qid(id)
            if current == LEEG:
                if code == SKIP:
                    lookup_add.add_source(id, "", "SKIP")
                    print(f"{id} -> SKIP")
                elif code.startswith("Q"):
                    lookup_add.add_source(id, "", code)
                    print(f"{id} -> {code}")


def sync_place(lookup_add: EcarticoLookupAddInterface):
    print("sync places")
    # Open the file in read mode
    with open(
        r"D:\projects\wikidata\Win32\Debug\cache\places.txt", "r", encoding="utf-8"
    ) as file:
        # Read each line in the file
        for line in file:
            # Process the line (e.g., print it)
            s = line.strip()
            match = re.search(r"^(\d+)=([A-Z0-9]+)", s, re.IGNORECASE)
            if not match:
                continue
            id = match.group(1)
            code = match.group(2)
            current = lookup_add.get_place_qid(id)
            if current == LEEG:
                if code == SKIP:
                    lookup_add.add_place(id, "", "SKIP")
                    print(f"{id} -> SKIP")
                elif code.startswith("Q"):
                    lookup_add.add_place(id, "", code)
                    print(f"{id} -> {code}")


def main():
    # circa: 4608
    # no surname; Barentz: 41860
    # Rembrandt; 6292
    # d'Amour: 52809 - baptized
    # Jan Six: 16511

    # circa: 4608
    # no surname: 41860
    # tussenvoegesel: 52809
    # baptized: 52809
    # between: 421
    # buried: 421
    # marriage circa: 4847; 55143
    # born, geen date: 1318
    # check occupation: 446
    # occupation circa: 3790
    # died after: 9665
    # or date: 3843; Q711737
    # occupation circa: 2306
    # address circa: 2306
    # rare end-date: Q118138045
    # date between: Q4860445
    # circa; Q2664887; Q2644001
    # died after: Q117794036
    # languages: Q560746

    # Q4893781: Bentvueghels
    # Q6163946: gutenberg book

    lookup_add = CachedEcarticoLookup(
        cache=EcarticoCache(),
        ecartico_source=EcarticoClient(),
        wikidata_source=WikidataClient(),
    )
    tracker = FirebirdStatusTracker()
    # data = impl_ecartico_data.EcarticoData()
    # ecartico = Ecartico(data, "4766")
    # ecartico.load()
    # ecartico.print()

    # wikidata = wd.WikiDataPage("Q87466")
    # wikidata.load()
    # ecartico.check(wikidata)

    # ecartico = Ecartico(data, "17348")
    # ecartico.load()

    # data = impl_ecartico_data.EcarticoData()
    # ecartico = EcarticoBot(data, "")
    # ecartico.get_occupation_qid("../occupations/478")
    # iterate_all(data)
    try_one(lookup_add, tracker, "Q1876107")
    # try_one(data, "Q6163946")

    # qid testen
    # Q80665302 - d'Amour
    # Q6163946 - 1 add
    # Q97036698 - utrecht; viaf redirect
    # Q6150343 - before; date of burial
    # Q1435298 - date of birth/baptized
    # Q721656 - 3572 - Egbert Jaspersz van Heemskerck
    # Q512817 - RKDartists WorkLocation
    # Q3340725 - wrong ecartico birth statement -> remove  TODO
    # Q6150343 - wrong ecartico death statement -> remove  TODO
    # Q3806892 - naam met ()                               TODO
    # Q3806892 - date of death = date of burial            TODO
    # description by qid items                             TODO
    # Q1876107 dubbele biografischportaal                  TODO
    # TODO: rkdartist inlezen en link toevoegen of eventueel self link toevoegen

    # sync_occupation(data)
    # sync_place(data)
    # sync_source(data)
    # try_one(data, "39061", None)

    # Q97036698,Pieter Bodart
    # Q3340725,Nicolas Regnesson
    # Q3806892,Jan Hoogsaat
    # Q6150343,Jan van Aken
    # Q4795325,Arnold de Jode
    # Q5171251,Cornelis van Caukercken
    # Q2579703,Jan van Beuningen
    # Q1435298,Folbert van Alten-Allen
    # Q1934374,Jan Gillisz van Vliet
    # Q1876107,Coenraed Lauwers


if __name__ == "__main__":
    main()
