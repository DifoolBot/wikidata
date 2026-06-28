"""
test_wikidata_cleanup_bot.py

Unit tests for the three detectors implemented in wikidata_cleanup_bot.py.

The fixtures use plain dicts that mirror pywikibot's item structure so tests
run without a live Wikidata connection.  Each fixture is also valid JSON so
the same data can drive tests on the JS side.

Run with:
    python -m pytest test_wikidata_cleanup_bot.py -v
"""

import pytest
from unittest.mock import MagicMock, patch

from cleanup.wikidata_cleanup_bot import (
    normalize_text,
    detect_self_cite,
    detect_empty_end_time,
    detect_alias_equals_label,
)

# ==== Helpers to build mock pywikibot objects ================================


def make_item(
    qid: str,
    claims: dict | None = None,
    labels: dict | None = None,
    aliases: dict | None = None,
) -> MagicMock:
    """Return a mock ItemPage with the given attributes."""
    item = MagicMock()
    item.id = qid
    item.claims = claims or {}
    item.labels = labels or {}
    item.aliases = aliases or {}
    return item


def make_claim(pid: str, target_qid: str | None = None) -> MagicMock:
    """Return a mock Claim with an ItemPage target."""
    claim = MagicMock()
    claim.getID.return_value = pid
    claim.snak = f"{pid}-snak"
    claim.qualifiers = {}
    if target_qid is not None:
        target = MagicMock()
        target.id = target_qid
        # Make isinstance(target, pywikibot.ItemPage) return True via spec
        target.__class__.__name__ = "ItemPage"
        claim.getTarget.return_value = target
    return claim


def make_qualifier(snaktype: str = "value") -> MagicMock:
    """Return a mock qualifier Claim."""
    q = MagicMock()
    q.snaktype = snaktype
    return q


# ==== normalize_text =========================================================


class TestNormalizeText:
    def test_unicode_hyphen_replaced(self):
        assert normalize_text("foo\u2010bar") == "foo-bar"

    def test_nbsp_replaced(self):
        assert normalize_text("foo\u00a0bar") == "foo bar"

    def test_leading_trailing_stripped(self):
        assert normalize_text("  , foo , ") == "foo"

    def test_multiple_spaces_collapsed(self):
        assert normalize_text("foo  bar") == "foo bar"

    def test_empty_string(self):
        assert normalize_text("") == ""

    def test_none_passthrough(self):
        # JS normalizeText returns the input unchanged when falsy
        assert normalize_text(None) is None

    def test_plain_string_unchanged(self):
        assert normalize_text("foo bar") == "foo bar"

    def test_combined(self):
        assert normalize_text("  foo\u2010bar\u00a0baz  ") == "foo-bar baz"


# ==== detect_self_cite =======================================================


class TestDetectSelfCite:
    def test_no_p2860_claims(self):
        item = make_item("Q1")
        assert detect_self_cite(item) == []

    def test_cites_different_item(self):
        claim = make_claim("P2860", "Q2")
        item = make_item("Q1", claims={"P2860": [claim]})
        assert detect_self_cite(item) == []

    def test_cites_self(self):
        claim = make_claim("P2860", "Q1")
        item = make_item("Q1", claims={"P2860": [claim]})
        result = detect_self_cite(item)
        assert len(result) == 1
        assert result[0]["detector"] == "self_cite"
        assert result[0]["claim"] is claim

    def test_multiple_claims_one_self(self):
        claim_self = make_claim("P2860", "Q1")
        claim_other = make_claim("P2860", "Q99")
        item = make_item("Q1", claims={"P2860": [claim_other, claim_self]})
        result = detect_self_cite(item)
        assert len(result) == 1
        assert result[0]["claim"] is claim_self

    def test_multiple_self_citations(self):
        # Unusual but guard against it
        claim_a = make_claim("P2860", "Q1")
        claim_b = make_claim("P2860", "Q1")
        item = make_item("Q1", claims={"P2860": [claim_a, claim_b]})
        result = detect_self_cite(item)
        assert len(result) == 2

    def test_non_item_target_skipped(self):
        # Target is a string (malformed data) — should not crash
        claim = MagicMock()
        claim.getID.return_value = "P2860"
        claim.snak = "P2860-snak"
        claim.qualifiers = {}
        claim.getTarget.return_value = "not an ItemPage"
        item = make_item("Q1", claims={"P2860": [claim]})
        assert detect_self_cite(item) == []


# ==== detect_empty_end_time ==================================================


class TestDetectEmptyEndTime:
    def test_no_claims(self):
        item = make_item("Q1")
        assert detect_empty_end_time(item) == []

    def test_claim_without_p582(self):
        claim = make_claim("P27")
        item = make_item("Q1", claims={"P27": [claim]})
        assert detect_empty_end_time(item) == []

    def test_p582_with_value(self):
        qual = make_qualifier("value")
        claim = make_claim("P27")
        claim.qualifiers = {"P582": [qual]}
        item = make_item("Q1", claims={"P27": [claim]})
        assert detect_empty_end_time(item) == []

    def test_p582_with_somevalue(self):
        qual = make_qualifier("somevalue")
        claim = make_claim("P27")
        claim.qualifiers = {"P582": [qual]}
        item = make_item("Q1", claims={"P27": [claim]})
        assert detect_empty_end_time(item) == []

    def test_p582_novalue(self):
        qual = make_qualifier("novalue")
        claim = make_claim("P27")
        claim.qualifiers = {"P582": [qual]}
        item = make_item("Q1", claims={"P27": [claim]})
        result = detect_empty_end_time(item)
        assert len(result) == 1
        assert result[0]["detector"] == "empty_end_time"
        assert result[0]["claim"] is claim
        assert result[0]["qualifier"] is qual

    def test_multiple_claims_multiple_qualifiers(self):
        qual_a = make_qualifier("novalue")
        qual_b = make_qualifier("novalue")
        qual_value = make_qualifier("value")
        claim_a = make_claim("P27")
        claim_a.qualifiers = {"P582": [qual_a]}
        claim_b = make_claim("P102")
        claim_b.qualifiers = {"P582": [qual_value, qual_b]}
        item = make_item("Q1", claims={"P27": [claim_a], "P102": [claim_b]})
        result = detect_empty_end_time(item)
        assert len(result) == 2
        qualifiers = {r["qualifier"] for r in result}
        assert qual_a in qualifiers
        assert qual_b in qualifiers

    def test_deprecated_claim_still_checked(self):
        # The JS checks all claims regardless of rank
        qual = make_qualifier("novalue")
        claim = make_claim("P27")
        claim.qualifiers = {"P582": [qual]}
        item = make_item("Q1", claims={"P27": [claim]})
        result = detect_empty_end_time(item)
        assert len(result) == 1


# ==== detect_alias_equals_label ==============================================


class TestDetectAliasEqualsLabel:
    def test_no_aliases(self):
        item = make_item("Q1", labels={"en": "Foo"})
        assert detect_alias_equals_label(item) == []

    def test_alias_differs_from_label(self):
        item = make_item(
            "Q1",
            labels={"en": "Foo"},
            aliases={"en": ["Bar"]},
        )
        assert detect_alias_equals_label(item) == []

    # (a) alias equals same-language label
    def test_alias_equals_label_same_lang(self):
        item = make_item(
            "Q1",
            labels={"en": "Foo"},
            aliases={"en": ["Foo"]},
        )
        result = detect_alias_equals_label(item)
        assert len(result) == 1
        assert result[0]["reason"] == "alias_equals_label"
        assert result[0]["lang"] == "en"
        assert result[0]["value"] == "Foo"

    def test_alias_equals_label_after_normalisation(self):
        # Alias has a Unicode hyphen; label has ASCII hyphen
        item = make_item(
            "Q1",
            labels={"en": "foo-bar"},
            aliases={"en": ["foo\u2010bar"]},
        )
        result = detect_alias_equals_label(item)
        assert len(result) == 1
        assert result[0]["reason"] == "alias_equals_label"

    # (b) alias equals mul label
    def test_alias_equals_mul_label(self):
        item = make_item(
            "Q1",
            labels={"mul": "Foo", "de": "Baz"},
            aliases={"de": ["Foo"]},
        )
        result = detect_alias_equals_label(item)
        assert len(result) == 1
        assert result[0]["reason"] == "alias_equals_mul_label"
        assert result[0]["lang"] == "de"

    def test_mul_aliases_not_processed_as_source(self):
        # mul aliases themselves should never appear as diffs
        item = make_item(
            "Q1",
            labels={"mul": "Foo"},
            aliases={"mul": ["Bar"]},
        )
        result = detect_alias_equals_label(item)
        assert result == []

    # (c) alias equals a mul alias
    def test_alias_equals_mul_alias(self):
        item = make_item(
            "Q1",
            labels={},
            aliases={"mul": ["Shared"], "fr": ["Shared"]},
        )
        result = detect_alias_equals_label(item)
        assert len(result) == 1
        assert result[0]["reason"] == "alias_equals_mul_alias"
        assert result[0]["lang"] == "fr"
        assert result[0]["value"] == "Shared"

    # (d) duplicate within same language
    def test_duplicate_alias_within_lang(self):
        item = make_item(
            "Q1",
            labels={"en": "Something else"},
            aliases={"en": ["Foo", "Bar", "Foo"]},
        )
        result = detect_alias_equals_label(item)
        assert len(result) == 1
        assert result[0]["reason"] == "duplicate"
        assert result[0]["value"] == "Foo"

    def test_duplicate_alias_after_normalisation(self):
        item = make_item(
            "Q1",
            labels={"en": "X"},
            aliases={"en": ["foo\u2010bar", "foo-bar"]},
        )
        result = detect_alias_equals_label(item)
        assert len(result) == 1
        assert result[0]["reason"] == "duplicate"

    def test_priority_order_label_beats_duplicate(self):
        # First occurrence equals the label — caught by (a).
        # Second occurrence is then a duplicate — but since (a) fires first
        # and skips adding to `seen`, the second occurrence should not be
        # reported as a duplicate.
        item = make_item(
            "Q1",
            labels={"en": "Foo"},
            aliases={"en": ["Foo", "Foo"]},
        )
        result = detect_alias_equals_label(item)
        # Both match rule (a) since label_norm == "foo" for both
        assert all(r["reason"] == "alias_equals_label" for r in result)
        assert len(result) == 2

    def test_multiple_languages(self):
        item = make_item(
            "Q1",
            labels={"en": "English", "de": "Deutsch"},
            aliases={
                "en": ["English", "Alias"],  # first is dup of label
                "de": ["Deutsch", "Other"],  # first is dup of label
            },
        )
        result = detect_alias_equals_label(item)
        assert len(result) == 2
        langs = {r["lang"] for r in result}
        assert langs == {"en", "de"}
        assert all(r["reason"] == "alias_equals_label" for r in result)

    def test_empty_label_no_false_positive(self):
        # If label is absent, normalizeText("") == "" — aliases should not
        # match the empty string unless the alias is itself empty.
        item = make_item(
            "Q1",
            labels={},
            aliases={"en": ["Foo"]},
        )
        result = detect_alias_equals_label(item)
        assert result == []

    def test_combined_reasons_single_item(self):
        item = make_item(
            "Q1",
            labels={"en": "Match", "mul": "MulLabel"},
            aliases={
                "en": ["Match", "MulLabel", "Dup", "Dup"],
                "mul": ["MulAlias"],
                "fr": ["MulAlias"],
            },
        )
        result = detect_alias_equals_label(item)
        reasons = {r["reason"] for r in result}
        assert "alias_equals_label" in reasons  # "Match" in en
        assert "alias_equals_mul_label" in reasons  # "MulLabel" in en
        assert "duplicate" in reasons  # second "Dup" in en
        assert "alias_equals_mul_alias" in reasons  # "MulAlias" in fr


# ==== JSON fixture export (for cross-implementation testing) =================
# These dicts are valid JSON and represent the expected input/output pairs
# for each detector. They can be loaded by a JS test runner to verify that
# the JS and Python implementations agree.

FIXTURES = {
    "self_cite": [
        {
            "description": "self-citation removed",
            "item_id": "Q1",
            "claims": {"P2860": [{"target": "Q1"}]},
            "expected_diffs": 1,
        },
        {
            "description": "citation of other item — no change",
            "item_id": "Q1",
            "claims": {"P2860": [{"target": "Q2"}]},
            "expected_diffs": 0,
        },
    ],
    "empty_end_time": [
        {
            "description": "novalue P582 removed",
            "item_id": "Q1",
            "claims": {"P27": [{"qualifiers": {"P582": [{"snaktype": "novalue"}]}}]},
            "expected_diffs": 1,
        },
        {
            "description": "value P582 kept",
            "item_id": "Q1",
            "claims": {"P27": [{"qualifiers": {"P582": [{"snaktype": "value"}]}}]},
            "expected_diffs": 0,
        },
    ],
    "alias_equals_label": [
        {
            "description": "alias equals same-language label",
            "item_id": "Q1",
            "labels": {"en": "Foo"},
            "aliases": {"en": ["Foo", "Bar"]},
            "expected_diffs": 1,
            "expected_reasons": ["alias_equals_label"],
        },
        {
            "description": "alias equals mul label",
            "item_id": "Q1",
            "labels": {"mul": "Foo", "de": "Baz"},
            "aliases": {"de": ["Foo"]},
            "expected_diffs": 1,
            "expected_reasons": ["alias_equals_mul_label"],
        },
        {
            "description": "alias equals mul alias",
            "item_id": "Q1",
            "labels": {},
            "aliases": {"mul": ["Shared"], "fr": ["Shared"]},
            "expected_diffs": 1,
            "expected_reasons": ["alias_equals_mul_alias"],
        },
        {
            "description": "duplicate alias within language",
            "item_id": "Q1",
            "labels": {"en": "Other"},
            "aliases": {"en": ["Dup", "Dup"]},
            "expected_diffs": 1,
            "expected_reasons": ["duplicate"],
        },
        {
            "description": "no redundant aliases",
            "item_id": "Q1",
            "labels": {"en": "Foo"},
            "aliases": {"en": ["Bar", "Baz"]},
            "expected_diffs": 0,
            "expected_reasons": [],
        },
    ],
}


if __name__ == "__main__":
    import json

    print(json.dumps(FIXTURES, indent=2, ensure_ascii=False))
