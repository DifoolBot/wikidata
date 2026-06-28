"""
test_labels.py

Tests for the shared label vocabulary and the length-capped edit-summary
builder.

Run with:
    python -m pytest test_labels.py -v
"""

from cleanup.labels import (
    EDIT_SUMMARY_MAX_LEN,
    build_edit_summary,
    remove_claim_description,
    remove_refs_description,
    summary_parts,
)

TOOL = "User:Difool/WikidataCleanup"


# ==== per-change descriptions ================================================


class TestDescriptions:
    def test_remove_refs_known_detector(self):
        assert (
            remove_refs_description("wikimedia", "P373")
            == "remove imported-from-Wikimedia reference on P373"
        )

    def test_remove_refs_unknown_detector_falls_back(self):
        assert remove_refs_description("???", "P21") == "remove weak reference on P21"

    def test_remove_claim_known_detector(self):
        assert (
            remove_claim_description("low_precision_dates", "P569")
            == "remove redundant low-precision P569 date"
        )

    def test_remove_claim_unknown_detector_falls_back(self):
        assert remove_claim_description("???", "P2860") == "remove P2860 self-citation"


# ==== build_edit_summary =====================================================


# ==== summary_parts (ref-category collapsing) ================================


class TestSummaryParts:
    def test_two_ref_categories_collapse(self):
        # Mirrors the JS: 'remove A refs' + 'remove B refs' -> 'remove A+B refs'.
        assert summary_parts({"wikimedia", "aggregator"}) == [
            "remove aggregator+wikimedia refs"
        ]

    def test_dup_retrieved_joins_the_ref_part_as_duplicate(self):
        assert summary_parts({"dup_retrieved", "aggregator"}) == [
            "remove aggregator+duplicate refs"
        ]

    def test_all_ref_categories_single_part(self):
        parts = summary_parts(
            {
                "wikimedia",
                "aggregator",
                "community",
                "redundant",
                "inferred",
                "obsolete",
                "self_stated_in",
            }
        )
        assert parts == [
            "remove aggregator+community+inferred+obsolete+redundant+"
            "self_stated_in+wikimedia refs"
        ]

    def test_ref_part_first_then_sorted_others(self):
        parts = summary_parts({"clean_urls", "wikimedia", "aggregator"})
        assert parts == ["remove aggregator+wikimedia refs", "clean URLs"]

    def test_non_ref_only_uses_detector_labels(self):
        assert summary_parts({"clean_urls", "add_mul_label"}) == [
            "add mul label",
            "clean URLs",
        ]

    def test_unknown_detector_falls_back_to_id(self):
        assert summary_parts({"mystery_detector"}) == ["mystery_detector"]


# ==== build_edit_summary =====================================================


class TestBuildEditSummary:
    def test_short_summary_format(self):
        out = build_edit_summary({"clean_urls", "add_mul_label"}, TOOL)
        assert out == f"Cleanup: add mul label; clean URLs ([[{TOOL}|bot]])"

    def test_collapsed_ref_summary(self):
        out = build_edit_summary({"wikimedia", "aggregator"}, TOOL)
        assert out == f"Cleanup: remove aggregator+wikimedia refs ([[{TOOL}|bot]])"

    def test_single_detector(self):
        out = build_edit_summary({"clean_urls"}, TOOL)
        assert out == f"Cleanup: clean URLs ([[{TOOL}|bot]])"

    def _many(self, n=40):
        return {f"detector_with_a_fairly_long_name_{i:02d}" for i in range(n)}

    def test_long_summary_is_capped(self):
        out = build_edit_summary(self._many(), TOOL)
        assert len(out) <= EDIT_SUMMARY_MAX_LEN

    def test_long_summary_preserves_prefix_and_bot_link(self):
        out = build_edit_summary(self._many(), TOOL)
        assert out.startswith("Cleanup: ")
        assert out.endswith(f"([[{TOOL}|bot]])")

    def test_long_summary_reports_dropped_count(self):
        import re

        ids = self._many()
        out = build_edit_summary(ids, TOOL)
        m = re.search(r"\(\+(\d+) more\)", out)
        assert m is not None
        assert 0 < int(m.group(1)) < len(ids)

    def test_custom_max_len(self):
        out = build_edit_summary(self._many(), TOOL, max_len=150)
        assert len(out) <= 150
        assert out.startswith("Cleanup: ")
        assert out.endswith(f"([[{TOOL}|bot]])")

    def test_no_overflow_marker_when_everything_fits(self):
        out = build_edit_summary({"clean_urls", "add_mul_label"}, TOOL)
        assert "more)" not in out
