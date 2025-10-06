from typing import Optional, Tuple

import requests
from bs4 import BeautifulSoup, Tag

from shared_lib.lookups.interfaces.ecartico_lookup_interface import (
    EcarticoLookupInterface,
)


def get_html_content_from_url(url: str) -> str:
    response = requests.get(url)
    if response.status_code == 200:
        return response.text
    else:
        raise RuntimeError(
            f"Failed to retrieve the webpage. Status code: {response.status_code}"
        )


class EcarticoClient(EcarticoLookupInterface):
    def extract_qid_from_ecartico_page(self, url: str) -> tuple[Optional[str], str]:
        html_content = get_html_content_from_url(url)
        soup = BeautifulSoup(html_content, "html.parser")

        h1 = soup.find("h1")
        if not h1:
            raise RuntimeError(f"No <h1> found in {url}")
        description = h1.text
        if "/sources/" in url:
            title_elem = soup.find("td", property="schema:name")
            if title_elem:
                title = title_elem.get_text()
                # Replace tabs with a single space
                title = title.replace("\t", " ")
                # Replace double spaces with a single space
                title = " ".join(title.split())
                description = title

        # Find the <h2> tag with "External resources"
        external_header = soup.find("h2", string="External identifiers")
        if not external_header:
            external_header = soup.find("h2", string="External resources")
        if not external_header:
            external_header = soup.find("h2", string="References")
        if external_header:

            # Initialize a list to store URLs
            urls = []

            # Find the next <ul> after the <h2> "External resources"
            next_ul = external_header.find_next("ul")
            if not next_ul:
                raise RuntimeError(f"No <ul> found after 'External resources' in {url}")

            # cast next_ul to Tag
            if not isinstance(next_ul, Tag):
                raise RuntimeError("next_ul is not a Tag")

            # Extract all URLs from <a> tags within the <ul>
            for a_tag in next_ul.find_all("a", href=True):
                if not isinstance(a_tag, Tag):
                    raise RuntimeError("a_tag is not a Tag")
                href = a_tag["href"]
                if not isinstance(href, str):
                    raise RuntimeError("href is not a string")
                url = href
                urls.append(url)

            # Print the extracted URLs
            for url in urls:
                prefix = "http://www.wikidata.org/entity/"
                if url.startswith(prefix):
                    qid = url[len(prefix) :]
                    return qid, description
                prefix = "https://www.wikidata.org/wiki/"
                if url.startswith(prefix):
                    qid = url[len(prefix) :]
                    return qid, description
                if "wikidata" in url:
                    raise RuntimeError(f"Unrecognized wikidata url {url}")

        return None, description

    def get_occupation(self, occupation_id: str) -> tuple[Optional[str], str]:
        complete_url = f"https://ecartico.org/occupations/{occupation_id}"
        return self.extract_qid_from_ecartico_page(complete_url)

    def get_patronym_qid(self, text: str) -> Optional[str]:
        return None

    def get_place(self, place_id: str) -> tuple[Optional[str], str]:
        complete_url = f"https://ecartico.org/places/{place_id}"
        return self.extract_qid_from_ecartico_page(complete_url)

    def get_religion_qid(self, text: str) -> Optional[str]:
        return None

    def get_rkdimage_qid(self, rkdimage_id: str) -> Optional[str]:
        return None

    def get_source(self, source_id: str) -> tuple[Optional[str], str]:
        complete_url = f"https://ecartico.org/sources/{source_id}"
        return self.extract_qid_from_ecartico_page(complete_url)

    def get_genre_qid(self, attribute: str, value: str) -> Optional[str]:
        return None

    def get_person_qid(self, ecartico_id: Optional[str]) -> Optional[str]:
        pass

    def get_gutenberg_qid(self, ebook_id: Optional[str]) -> Optional[str]:
        pass

    def get_rijksmuseum_qid(
        self, url: str, inventory_number: Optional[str]
    ) -> Optional[str]:
        pass

    def get_occupation_type(self, qid: str) -> Optional[str]:
        pass

    def is_possible(self, ecartico_id: Optional[str], qid: str) -> bool:
        pass
