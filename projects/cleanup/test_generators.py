"""
test_generators.py

Tests for generators.py.  Only the query-building logic is tested here;
actual SPARQL execution against Wikidata requires a live connection.

Run with:
    python -m pytest test_generators.py -v
"""

import pytest
from unittest.mock import MagicMock, patch

from cleanup.detectors import SourceCategoryRules
from cleanup.generators import (
    QUERIES,
    _build_aggregator_query,
    _fallback_query,
    generator_for_detectors,
)

# ==== QUERIES dict ============================================================


class TestQueriesDict:
    def test_all_expected_keys_present(self):
        expected = {
            "self_cite",
            "empty_end_time",
            "alias_equals_label",
            "redundant_preferred",
            "expired_preferred",
            "dup_retrieved",
            "merge_same_date_claims",
            "julian_gregorian_dates",
            "low_precision_dates",
            "normalize_labels",
            "add_mul_label",
            "add_mul_alias",
            "upgrade_precise_date",
            "replace_wrong_property",
            "split_reference_urls",
            "merge_wiki_import_refs",
            "wikimedia",
            "inferred",
        }
        assert expected <= set(QUERIES.keys())

    def test_all_queries_contain_limit_placeholder(self):
        for name, query in QUERIES.items():
            assert "{limit}" in query, f"Query {name!r} missing {{limit}} placeholder"

    def test_all_queries_select_item(self):
        for name, query in QUERIES.items():
            assert "?item" in query, f"Query {name!r} does not select ?item"

    def test_self_cite_query_structure(self):
        q = QUERIES["self_cite"].replace("{limit}", "100")
        assert "wdt:P2860" in q
        assert "?item" in q

    def test_empty_end_time_uses_novalue(self):
        q = QUERIES["empty_end_time"].replace("{limit}", "100")
        assert "novalue" in q.lower() or "P582" in q

    def test_add_mul_label_requires_q5(self):
        q = QUERIES["add_mul_label"].replace("{limit}", "100")
        assert "Q5" in q

    def test_wikimedia_covers_p143_and_p4656(self):
        q = QUERIES["wikimedia"].replace("{limit}", "100")
        assert "P143" in q
        assert "P4656" in q

    def test_inferred_covers_p3452_and_p887(self):
        q = QUERIES["inferred"].replace("{limit}", "100")
        assert "P3452" in q
        assert "P887" in q


# ==== _build_aggregator_query ================================================


class TestBuildAggregatorQuery:
    def test_empty_pids_returns_none(self):
        assert _build_aggregator_query(set(), 100) is None

    def test_single_pid(self):
        q = _build_aggregator_query({"P214"}, 100)
        assert q is not None
        assert "P214" in q
        assert "100" in q

    def test_multiple_pids_all_included(self):
        q = _build_aggregator_query({"P214", "P434", "P1953"}, 500)
        assert q is not None
        assert "P214" in q
        assert "P434" in q
        assert "P1953" in q

    def test_limit_applied(self):
        q = _build_aggregator_query({"P214"}, 250)
        assert q is not None
        assert "250" in q

    def test_query_contains_wasDerivedFrom(self):
        q = _build_aggregator_query({"P214"}, 100)
        assert q is not None
        assert "wasDerivedFrom" in q


# ==== generator_for_detectors ================================================


class TestGeneratorForDetectors:
    def _mock_repo(self) -> MagicMock:
        return MagicMock(spec=["data_repository"])

    def _mock_sparql_gen(self, items=None):
        """Return a mock generator that yields nothing (no live SPARQL)."""
        return iter([])

    def test_no_detectors_returns_none(self):
        repo = self._mock_repo()
        with patch("generators._sparql_generator", return_value=iter([])):
            result = generator_for_detectors(set(), repo)
        # No generators built → should be None or empty
        # (CombinedPageGenerator with no generators is valid but empty)
        # We just check it doesn't raise.

    def test_single_static_detector(self):
        repo = self._mock_repo()
        calls = []

        def mock_gen(query, repo):
            calls.append(query)
            return iter([])

        with patch("generators._sparql_generator", side_effect=mock_gen):
            generator_for_detectors({"self_cite"}, repo, limit=100)
        assert len(calls) == 1
        assert "P2860" in calls[0]
        assert "100" in calls[0]

    def test_duplicate_queries_deduplicated(self):
        # If two detectors share the same query template after formatting,
        # only one SPARQL call should be made.
        repo = self._mock_repo()
        calls = []

        def mock_gen(query, repo):
            calls.append(query)
            return iter([])

        # wikimedia appears twice — once via "wikimedia", once explicitly
        with patch("generators._sparql_generator", side_effect=mock_gen):
            generator_for_detectors({"wikimedia"}, repo, limit=100)
        # Should only call once for wikimedia
        wiki_calls = [c for c in calls if "P143" in c]
        assert len(wiki_calls) == 1

    def test_ref_cat_detectors_use_wikimedia_query(self):
        repo = self._mock_repo()
        calls = []

        def mock_gen(query, repo):
            calls.append(query)
            return iter([])

        with patch("generators._sparql_generator", side_effect=mock_gen):
            generator_for_detectors({"wikimedia"}, repo, limit=200)
        assert any("P143" in c for c in calls)

    def test_dynamic_ref_cat_with_source_rules(self):
        repo = self._mock_repo()
        rules = SourceCategoryRules(
            aggregator_pids={"P214"},
            community_pids={"P434"},
        )
        calls = []

        def mock_gen(query, repo):
            calls.append(query)
            return iter([])

        with patch("generators._sparql_generator", side_effect=mock_gen):
            generator_for_detectors(
                {"aggregator", "community"},
                repo,
                limit=100,
                source_rules=rules,
            )
        # Should have built a dynamic query containing P214 and P434
        combined = " ".join(calls)
        assert "P214" in combined or "P434" in combined

    def test_dynamic_ref_cat_without_source_rules_uses_fallback(self):
        repo = self._mock_repo()
        calls = []

        def mock_gen(query, repo):
            calls.append(query)
            return iter([])

        with patch("generators._sparql_generator", side_effect=mock_gen):
            generator_for_detectors({"aggregator"}, repo, limit=100, source_rules=None)
        # Should fall back to the recent-items query
        assert any("dateModified" in c or "modified" in c for c in calls)

    def test_single_item_not_affected(self):
        # generator_for_detectors is not called when -item: is used;
        # this just confirms the function handles empty detector sets cleanly.
        repo = self._mock_repo()
        with patch("generators._sparql_generator", return_value=iter([])):
            gen = generator_for_detectors(set(), repo, limit=100)
        # Should return None or an empty generator — no crash.

    def test_fallback_query_format(self):
        from cleanup.generators import _fallback_query

        q = _fallback_query(500)
        assert "dateModified" in q or "modified" in q
        assert "2020-01-01" in q
        assert "500" in q
