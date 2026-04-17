import json
import re
from abc import ABC, abstractmethod
from urllib.parse import parse_qs, urlparse

import pywikibot
import requests
from bs4 import BeautifulSoup

import shared_lib.change_wikidata as cwd
import shared_lib.constants as wd

site = pywikibot.Site("wikidata", "wikidata")
repo = site.data_repository()

MUBI_REG_EX = r"https:\/\/mubi\.com\/([a-z]{2,}\/)?cast\/([a-z-]+)"


class IdentifierStrategy(ABC):
    """Generic interface for extracting and validating external IDs."""

    @abstractmethod
    def match_url(self, url: str) -> bool:
        """Return True if this strategy can handle the given URL."""
        pass

    @abstractmethod
    def extract_id_from_url(self, url: str) -> str | None:
        """Extract identifier from a URL if possible."""
        pass

    @abstractmethod
    def fetch_id(self, url: str) -> str | None:
        """Fetch identifier from a remote page if needed."""
        pass

    @abstractmethod
    def property_id(self) -> str:
        """Return the Wikidata property ID for this identifier."""
        pass

    @abstractmethod
    def source_qid(self) -> str:
        """Return the Wikidata QID for the source (e.g. MUBI)."""
        pass

    @abstractmethod
    def name(self) -> str:
        """Return the name of the identifier strategy."""
        pass

    @abstractmethod
    def summary_name(self) -> str:
        """Return the name used in edit summaries."""
        pass

    def get_ids_from_urls(self, urls):
        """Extract IDs from a list of URLs."""
        ids = set()
        for url in urls:
            id = self.extract_id_from_url(url)
            if id:
                ids.add(id)
        return ids

    def get_ref_urls(self, item):
        """Extract reference URLs from a Wikidata item for a given strategy."""
        urls = set()

        for prop_id, claims in item.claims.items():
            for claim in claims:
                for src in claim.sources:
                    for ref_prop, ref_values in src.items():
                        if ref_prop != wd.PID_REFERENCE_URL:
                            continue
                        for ref_val in ref_values:
                            url = ref_val.getTarget()
                            if not self.match_url(url):
                                continue
                            urls.add(url)

        return list(urls)

    def get_main_id(self, item):
        """Extract IDs and their reference URLs from a Wikidata item."""
        result = {}

        for claim in item.claims.get(self.property_id(), []):
            if claim.rank == "deprecated":
                continue

            person_id = claim.getTarget()
            urls = set()

            for src in claim.sources:
                for ref_prop, ref_values in src.items():
                    if ref_prop != wd.PID_REFERENCE_URL:
                        continue
                    for ref_val in ref_values:
                        url = ref_val.getTarget()
                        if not self.match_url(url):
                            continue
                        urls.add(url)

            result[person_id] = urls

        return result


class MubiStrategy(IdentifierStrategy):
    def fetch_id(self, url: str) -> int:
        # Fetch the page
        response = requests.get(url)
        response.raise_for_status()

        # Parse HTML
        soup = BeautifulSoup(response.text, "html.parser")

        # Find the __NEXT_DATA__ script tag
        script_tag = soup.find("script", id="__NEXT_DATA__")
        if not script_tag:
            raise ValueError("Could not find __NEXT_DATA__ script tag")

        script_tag = soup.find("script", id="__NEXT_DATA__")
        if not script_tag:
            raise ValueError("Could not find __NEXT_DATA__ script tag")

        # Load JSON
        # Navigate to castMember.id
        try:
            data = json.loads(script_tag.get_text())
            person_id = data["props"]["pageProps"]["castMember"]["id"]
            return person_id
        except KeyError:
            raise ValueError("Could not extract person ID from JSON")

    def property_id(self) -> str:
        return wd.PID_MUBI_PERSON_ID

    def source_qid(self) -> str:
        return wd.QID_MUBI

    def match_url(self, url: str) -> bool:
        return "mubi.com" in url and "/cast/" in url

    def extract_id_from_url(self, url):
        """Extract MUBI person ID from a MUBI URL."""
        match = re.search(MUBI_REG_EX, url)
        if match:
            return match.group(2)
        return None

    def name(self) -> str:
        return "MUBI"

    def summary_name(self) -> str:
        return "mubi.com cast member"


def get_is_human(page):
    """Check if the Wikidata page represents a human."""
    if wd.PID_INSTANCE_OF in page.claims:
        instance_ofs = [
            claim.getTarget().id for claim in page.claims[wd.PID_INSTANCE_OF]
        ]
        if wd.QID_HUMAN in instance_ofs:
            return True
    return False


def process_item(qid, test: bool, strategy: IdentifierStrategy):
    item = pywikibot.ItemPage(repo, qid)
    page = cwd.WikiDataPage(item, test=test)
    is_human = get_is_human(page)
    if not is_human:
        print(f"{qid} is not a human")
        return

    main_ids = strategy.get_main_id(item)
    main_id = None
    main_url = None
    if len(main_ids) == 0:
        print(f"No {strategy.name} IDs found for {qid}")
    elif len(main_ids) > 1:
        print(f"Multiple {strategy.name} IDs found for {qid}: {list(main_ids.keys())}")
        return
    else:
        main_id = list(main_ids.keys())[0]
        if len(main_ids[main_id]) > 1:
            print(f"Multiple reference URLs for {strategy.name} ID {main_id} in {qid}")
            return
        if len(main_ids[main_id]) > 0:
            main_url = list(main_ids[main_id])[0]
    ref_urls = strategy.get_ref_urls(item)
    if len(ref_urls) == 0:
        print(f"No {strategy.name} reference URLs found for {qid}")
        return
    if len(strategy.get_ids_from_urls(ref_urls)) > 1:
        print(f"Multiple {strategy.name} reference URLs found for {qid}")
        return
    ref_url = ref_urls[0]
    if main_url:
        if len(strategy.get_ids_from_urls([main_url, ref_url])) > 1:
            print(
                f"{strategy.name} ID {main_id} has a different reference URL in {qid}"
            )
            return

    if not main_id:
        # not yet a mubi_id, fetch it
        main_id = strategy.fetch_id(ref_url)

    did_add_ref_url = False
    if strategy.property_id() in page.claims:
        for claim in page.claims[strategy.property_id()]:
            if claim.sources:
                page.add_ref_value(
                    strategy.property_id(),
                    claim,
                    0,
                    wd.PID_REFERENCE_URL,
                    str(ref_url),
                )
                did_add_ref_url = True
                break

    if not did_add_ref_url:
        page.add_statement(
            cwd.ExternalIDStatement(None, strategy.property_id(), str(main_id)),
            reference=cwd.URLReference(ref_url),
        )

    # remove exact match
    props = [
        wd.PID_EXACT_MATCH,
        wd.PID_REFERENCE_URL,
        wd.PID_ARCHIVE_URL,
        wd.PID_OFFICIAL_WEBSITE,
        wd.PID_DESCRIBED_AT_URL,
    ]
    for prop in props:
        if prop in page.claims:
            for claim in page.claims[prop]:
                target = claim.getTarget()
                if isinstance(target, str) and target == ref_url:
                    page.remove_property(prop, claim)

    for prop_id, claims in page.claims.items():
        if prop_id == strategy.property_id():
            continue
        for claim in claims:
            for src in claim.sources:
                for ref_prop, ref_values in src.items():
                    if ref_prop != wd.PID_REFERENCE_URL:
                        continue
                    for ref_val in ref_values:
                        url = ref_val.getTarget()
                        if not strategy.match_url(url):
                            continue
                        if strategy.extract_id_from_url(
                            url
                        ) != strategy.extract_id_from_url(ref_url):
                            print(f"Unknown {strategy.name} URL found in references")
                            return
                        ref_index = claim.sources.index(src)
                        page.remove_ref_value(
                            prop_id, claim, ref_index, ref_prop, ref_url
                        )
                        page.add_ref_value(
                            prop_id,
                            claim,
                            ref_index,
                            wd.PID_STATED_IN,
                            strategy.source_qid(),
                        )
                        page.add_ref_value(
                            prop_id,
                            claim,
                            ref_index,
                            strategy.property_id(),
                            str(main_id),
                        )

    page.summary = f"resolve {strategy.summary_name()} URLs to IDs"
    page.apply()


def load_items_from_file(filename):
    with open(filename, "r", encoding="utf-8") as f:
        # Strip whitespace and skip empty lines
        return [line.strip() for line in f if line.strip()]


def main():
    # Example input list from qlever
    items = ["Q113847934"]
    # items = load_items_from_file("D:\\python\\wikidata\\projects\\clean_url\\mubi.txt")
    for qid in items:
        print(f"Processing {qid}...")
        process_item(qid, strategy=MubiStrategy(), test=False)


if __name__ == "__main__":
    main()
