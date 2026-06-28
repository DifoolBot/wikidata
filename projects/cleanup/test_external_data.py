"""
test_external_data.py

Tests for external_data.py — specifically the pure parsing functions that
require no network access.  Network-dependent functions (SPARQL queries,
MediaWiki API calls) are tested via mocking.

Run with:
    python -m pytest test_external_data.py -v
"""

import pathlib

import pytest
from unittest.mock import patch, MagicMock

from cleanup.detectors import UrlStripRules, SourceCategoryRules, WikipediaEditions

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")
from cleanup.external_data import (
    _parse_source_category_page,
    load_url_strip_rules,
    load_wikipedia_editions,
    load_source_category_rules,
)

# ==== _parse_source_category_page ============================================


class TestParseSourceCategoryPage:
    # Minimal representative wikitext matching the actual page format
    WIKITEXT = """\
=== Aggregator sources ===
{| class="wikitable sortable"
! Property  !!  Notes
|-
| {{P|P214}}  ||  VIAF aggregates national library data
|-
| {{P|P213}}  ||  ISNI aggregates multiple registries
|}

=== Community sources ===
{| class="wikitable sortable"
! Property  !!  Notes
|-
| {{P|P434}}  ||  MusicBrainz artist ID
|-
| {{P|P1953}} ||  Discogs artist ID
|}

=== Redundant sources ===
{| class="wikitable sortable"
! Weak property  !! Strong property  !! Notes
|-
| {{P|P2163}}  || {{P|P244}}   || FAST derived from LC
|-
| {{P|P2347}}  || {{P|P227}}   || YSO derived from GND
|}
"""

    def test_aggregator_pids(self):
        agg, com, red = _parse_source_category_page(self.WIKITEXT)
        assert "P214" in agg
        assert "P213" in agg

    def test_community_pids(self):
        agg, com, red = _parse_source_category_page(self.WIKITEXT)
        assert "P434" in com
        assert "P1953" in com

    def test_redundancy_pairs(self):
        agg, com, red = _parse_source_category_page(self.WIKITEXT)
        assert ("P2163", "P244") in red
        assert ("P2347", "P227") in red

    def test_no_cross_contamination(self):
        agg, com, red = _parse_source_category_page(self.WIKITEXT)
        assert "P434" not in agg
        assert "P214" not in com

    def test_empty_wikitext(self):
        agg, com, red = _parse_source_category_page("")
        assert agg == set()
        assert com == set()
        assert red == []

    def test_unknown_section_ignored(self):
        wikitext = """\
=== Unknown section ===
{| class="wikitable"
|-
| {{P|P999}} || some note
|}
"""
        agg, com, red = _parse_source_category_page(wikitext)
        assert agg == set()
        assert com == set()
        assert red == []

    def test_header_row_not_parsed_as_pid(self):
        # The ! header line should never produce a PID
        agg, com, red = _parse_source_category_page(self.WIKITEXT)
        # "Property" is not a PID so shouldn't appear
        assert "Property" not in str(agg)

    def test_redundant_row_needs_two_cells(self):
        wikitext = """\
=== Redundant sources ===
{| class="wikitable"
|-
| {{P|P2163}}
|}
"""
        agg, com, red = _parse_source_category_page(wikitext)
        assert red == []

    def test_actual_page_content(self):
        """Smoke test against the real wiki page content."""
        wikitext = _read_fixture("reference-source-categories.txt")
        agg, com, red = _parse_source_category_page(wikitext)
        # The real page has at least one entry in each section
        assert len(agg) >= 1
        assert len(com) >= 1
        assert len(red) >= 1


# ==== load_url_strip_rules (mocked network) ==================================


class TestLoadUrlStripRules:
    def test_actual_page_parsed(self):
        """Parse the real url_tracking_params page content."""
        wikitext = _read_fixture("url_tracking_params.txt")
        with patch("cleanup.external_data._mediawiki_page", return_value=wikitext):
            rules = load_url_strip_rules()
        # Global wildcard always entry from the real page
        wildcard_params = rules.params_for(rules.always, "example.com")
        assert "utm_source" in wildcard_params
        assert "utm_medium" in wildcard_params

    def test_fallback_on_error(self):
        """Returns hardcoded defaults when fetch fails."""
        with patch("cleanup.external_data._mediawiki_page", side_effect=Exception("network")):
            rules = load_url_strip_rules()
        # Should still have hardcoded defaults
        assert isinstance(rules, UrlStripRules)
        assert "ref_" in rules.params_for(rules.always, "imdb.com")

    def test_youtube_recognition_params(self):
        wikitext = _read_fixture("url_tracking_params.txt")
        with patch("cleanup.external_data._mediawiki_page", return_value=wikitext):
            rules = load_url_strip_rules()
        # youtube.com recognition params exist in the real page
        recog = rules.params_for(rules.recognition, "youtube.com")
        assert "t" in recog or "ab_channel" in recog


# ==== load_wikipedia_editions (mocked SPARQL) ================================


class TestLoadWikipediaEditions:
    SPARQL_RESPONSE = [
        {
            "item": {"value": "http://www.wikidata.org/entity/Q328"},
            "lang": {"value": "en"},
        },
        {
            "item": {"value": "http://www.wikidata.org/entity/Q8447"},
            "lang": {"value": "fr"},
        },
        {
            "item": {"value": "http://www.wikidata.org/entity/Q48183"},
            "lang": {"value": "de"},
        },
    ]

    def test_lang_to_qid_populated(self):
        with patch("cleanup.external_data._sparql", return_value=self.SPARQL_RESPONSE):
            editions = load_wikipedia_editions()
        assert editions.get_qid("en") == "Q328"
        assert editions.get_qid("fr") == "Q8447"
        assert editions.get_qid("de") == "Q48183"

    def test_qid_to_lang_reverse_lookup(self):
        with patch("cleanup.external_data._sparql", return_value=self.SPARQL_RESPONSE):
            editions = load_wikipedia_editions()
        assert editions.get_lang("Q328") == "en"
        assert editions.get_lang("Q8447") == "fr"

    def test_is_wikipedia_edition(self):
        with patch("cleanup.external_data._sparql", return_value=self.SPARQL_RESPONSE):
            editions = load_wikipedia_editions()
        assert editions.is_wikipedia_edition("Q328")
        assert not editions.is_wikipedia_edition("Q1")

    def test_first_seen_wins_on_duplicate_lang(self):
        dupes = [
            {
                "item": {"value": "http://www.wikidata.org/entity/Q328"},
                "lang": {"value": "en"},
            },
            {
                "item": {"value": "http://www.wikidata.org/entity/Q99999"},
                "lang": {"value": "en"},
            },  # duplicate lang
        ]
        with patch("cleanup.external_data._sparql", return_value=dupes):
            editions = load_wikipedia_editions()
        assert editions.get_qid("en") == "Q328"

    def test_fallback_on_error(self):
        with patch("cleanup.external_data._sparql", side_effect=Exception("timeout")):
            editions = load_wikipedia_editions()
        assert isinstance(editions, WikipediaEditions)
        assert editions.get_qid("en") is None


# ==== load_source_category_rules (mocked) ====================================


class TestLoadSourceCategoryRules:
    WIKI_PAGE = """\
=== Aggregator sources ===
{| class="wikitable"
|-
| {{P|P214}} || VIAF
|}

=== Community sources ===
{| class="wikitable"
|-
| {{P|P434}} || MusicBrainz
|}

=== Redundant sources ===
{| class="wikitable"
|-
| {{P|P2163}} || {{P|P244}} || FAST/LC
|}
"""
    OBSOLETE_SEARCH = [{"title": "Property:P1580"}]
    PARTIAL_SPARQL: list = []  # no partially-obsolete props
    STATED_IN_ROWS = [
        {
            "prop": {"value": "http://www.wikidata.org/entity/P214"},
            "stated_in": {"value": "http://www.wikidata.org/entity/Q54919"},
            "rank": {"value": "http://wikiba.se/ontology#PreferredRank"},
        },
    ]
    RELATED_ROWS: list = []

    def _mock_sparql(self, query: str) -> list:
        if "P518" in query:  # partially-obsolete filter
            return self.PARTIAL_SPARQL
        if "P9073" in query and "P2378" not in query:  # stated-in query
            return self.STATED_IN_ROWS
        return self.RELATED_ROWS  # related query or anything else

    def _mock_mw_search(self, **kwargs):
        return {"query": {"search": self.OBSOLETE_SEARCH}}

    def test_full_load(self):
        site_mock = MagicMock()
        site_mock._simple_request.return_value.submit.return_value = (
            self._mock_mw_search()
        )
        with (
            patch("cleanup.external_data._mediawiki_page", return_value=self.WIKI_PAGE),
            patch("cleanup.external_data._sparql", side_effect=self._mock_sparql),
            patch("pywikibot.Site", return_value=site_mock),
        ):
            rules = load_source_category_rules()

        assert rules.is_aggregator("P214")
        assert rules.is_community("P434")
        assert ("P2163", "P244") in rules.redundancy_pairs

    def test_partial_failure_still_returns_object(self):
        """A failure in one source leaves the others intact."""
        with (
            patch("cleanup.external_data._mediawiki_page", side_effect=Exception("network")),
            patch("cleanup.external_data._sparql", return_value=[]),
            patch("cleanup.external_data._fetch_obsolete_id_props", return_value=set()),
            patch("cleanup.external_data._fetch_stated_in_preferences", return_value={}),
        ):
            rules = load_source_category_rules()
        assert isinstance(rules, SourceCategoryRules)
        assert rules.aggregator_pids == set()

    def test_obsolete_pids_populated(self):
        site_mock = MagicMock()
        site_mock._simple_request.return_value.submit.return_value = (
            self._mock_mw_search()
        )
        with (
            patch("cleanup.external_data._mediawiki_page", return_value=self.WIKI_PAGE),
            patch("cleanup.external_data._sparql", side_effect=self._mock_sparql),
            patch("pywikibot.Site", return_value=site_mock),
        ):
            rules = load_source_category_rules()
        assert rules.is_obsolete("P1580")

    def test_stated_in_populated(self):
        site_mock = MagicMock()
        site_mock._simple_request.return_value.submit.return_value = (
            self._mock_mw_search()
        )
        with (
            patch("cleanup.external_data._mediawiki_page", return_value=self.WIKI_PAGE),
            patch("cleanup.external_data._sparql", side_effect=self._mock_sparql),
            patch("pywikibot.Site", return_value=site_mock),
        ):
            rules = load_source_category_rules()
        prefs = rules.get_property_stated_in("P214")
        assert prefs is not None
        assert prefs["preferred"] == "Q54919"
        assert "Q54919" in prefs["allowed"]
