import requests
from bs4 import BeautifulSoup


class Page:
    """Abstract base class for external ID pages."""

    def __init__(self, external_id):
        self.external_id = external_id
        self.url = None
        self._response = None
        self._soup = None

    def load(self):
        if not self.url:
            raise RuntimeError("No url")
        """Fetch the page and prepare soup."""
        self._response = requests.get(self.url, allow_redirects=True)
        self._soup = BeautifulSoup(self._response.text, "html.parser")

    def get_name(self):
        """Extract the name from the page. Override in subclass if needed."""
        if not self._soup:
            raise RuntimeError("Page not loaded. Call load() first.")
        title = self._soup.find("title")
        return title.get_text(strip=True) if title else None

    def is_redirect(self):
        """Check if the request was redirected."""
        if not self._response:
            raise RuntimeError("Page not loaded. Call load() first.")
        return len(self._response.history) > 0


class BiografischPortaalPage(Page):
    """Page class for Biografisch Portaal van Nederland (P651)."""

    BASE_URL = "http://www.biografischportaal.nl/persoon/{}"

    def __init__(self, external_id):
        super().__init__(external_id)
        self.url = self.BASE_URL.format(external_id)


class PageFactory:
    """Factory that returns the correct Page subclass for a Wikidata property."""

    _registry = {
        "P651": BiografischPortaalPage,  # Biografisch Portaal van Nederland ID
    }

    @classmethod
    def create_page(cls, wikidata_property, external_id):
        page_class = cls._registry.get(wikidata_property)
        if not page_class:
            raise ValueError(
                f"No page class registered for property {wikidata_property}"
            )
        return page_class(external_id)


if __name__ == "__main__":
    # Biografisch Portaal van Nederland ID (P651) = 20320203
    page = PageFactory.create_page("P651", "20320203")
    page.load()
    print("URL:", page.url)
    print("Name:", page.get_name())
    print("Redirected:", page.is_redirect())
