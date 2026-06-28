"""
test_apply.py

Tests for apply.build_payload using lightweight fakes that duck-type the small
slice of the pywikibot API that build_payload actually touches:

  - item.claims   : dict[pid -> list[Claim]]
  - item.aliases  : dict[lang -> list[str | dict]]
  - claim.snak    : the claim id string
  - claim.toJSON(): the wbgetentities-style claim dict

build_payload makes no network calls and (at runtime) does not import
pywikibot, so these fakes are enough to exercise the merge logic.

Run with:
    python -m pytest test_apply.py -v
"""

import copy

import pytest

from cleanup.apply import build_payload
from cleanup.detectors import (
    ACTION_ADD_MUL_ALIAS,
    ACTION_REMOVE_ALIAS,
    ACTION_REMOVE_CLAIM,
    ACTION_REMOVE_REFS,
)


# ==== Fakes ==================================================================


class FakeClaim:
    """Duck-types pywikibot.Claim for build_payload's needs."""

    def __init__(self, claim_id: str, json_data: dict | None = None) -> None:
        self.snak = claim_id
        self._json = json_data or {"id": claim_id}

    def toJSON(self) -> dict:
        # Return a deep copy: build_payload mutates the returned dict in place.
        return copy.deepcopy(self._json)


class FakeItem:
    """Duck-types pywikibot.ItemPage for build_payload's needs."""

    def __init__(
        self,
        claims: dict[str, list[FakeClaim]] | None = None,
        aliases: dict[str, list] | None = None,
        item_id: str = "Q1",
    ) -> None:
        self.id = item_id
        self.claims = claims or {}
        self.aliases = aliases or {}


# ==== ACTION_REMOVE_CLAIM summaries (#2) =====================================
#
# A single action constant is reused by three detectors; the per-change log
# line must reflect which one produced the removal.


class TestRemoveClaimSummaries:
    def _item(self) -> FakeItem:
        return FakeItem(claims={"P569": [FakeClaim("Q1$dob")]})

    def _diff(self, detector: str) -> dict:
        return {
            "detector": detector,
            "action": ACTION_REMOVE_CLAIM,
            "pid": "P569",
            "claim_id": "Q1$dob",
        }

    def test_remove_claim_payload_structure(self):
        item = self._item()
        payload, _ = build_payload(item, [self._diff("self_cite")])
        assert payload["claims"] == [{"id": "Q1$dob", "remove": ""}]

    def test_self_cite_summary(self):
        item = FakeItem(claims={"P2860": [FakeClaim("Q1$cite")]})
        diff = {
            "detector": "self_cite",
            "action": ACTION_REMOVE_CLAIM,
            "pid": "P2860",
            "claim_id": "Q1$cite",
        }
        _, descriptions = build_payload(item, [diff])
        assert descriptions == ["remove P2860 self-citation"]

    def test_julian_gregorian_summary(self):
        item = self._item()
        _, descriptions = build_payload(item, [self._diff("julian_gregorian_dates")])
        assert descriptions == ["remove duplicate Julian/Gregorian P569 date"]

    def test_low_precision_summary(self):
        item = self._item()
        _, descriptions = build_payload(item, [self._diff("low_precision_dates")])
        assert descriptions == ["remove redundant low-precision P569 date"]

    def test_unknown_detector_falls_back_to_self_citation(self):
        item = self._item()
        _, descriptions = build_payload(item, [self._diff("something_else")])
        assert descriptions == ["remove P569 self-citation"]


# ==== ACTION_REMOVE_ALIAS (reason optional / hidden diffs) ===================


class TestRemoveAlias:
    def test_alias_equals_label_keeps_reason_and_removes_value(self):
        item = FakeItem(aliases={"en": ["Foo", "Bar"]})
        diff = {
            "detector": "alias_equals_label",
            "action": ACTION_REMOVE_ALIAS,
            "lang": "en",
            "value": "Bar",
            "reason": "duplicate",
        }
        payload, descriptions = build_payload(item, [diff])
        assert payload["aliases"]["en"] == ["Foo"]
        assert descriptions == ["remove alias [en] 'Bar' (duplicate)"]

    def test_hidden_remove_alias_without_reason_does_not_raise(self):
        # Regression: detect_add_mul_alias emits hidden ACTION_REMOVE_ALIAS diffs
        # that carry no "reason" key.  This previously raised KeyError.
        item = FakeItem(aliases={"de": ["Name"]})
        diff = {
            "detector": "add_mul_alias",
            "action": ACTION_REMOVE_ALIAS,
            "_hidden": True,
            "row_id": "addMulAlias_name",
            "lang": "de",
            "value": "Name",
        }
        payload, descriptions = build_payload(item, [diff])
        # The alias is still removed...
        assert payload["aliases"]["de"] == []
        # ...but the hidden diff produces no log line.
        assert descriptions == []

    def test_full_add_mul_alias_scenario(self):
        item = FakeItem(
            aliases={"de": ["Name"], "fr": ["Name"], "mul": []},
        )
        row_id = "addMulAlias_name"
        diffs = [
            {
                "detector": "add_mul_alias",
                "action": ACTION_ADD_MUL_ALIAS,
                "row_id": row_id,
                "value": "Name",
                "source_langs": ["de", "fr"],
                "lang_count": 2,
            },
            {
                "detector": "add_mul_alias",
                "action": ACTION_REMOVE_ALIAS,
                "_hidden": True,
                "row_id": row_id,
                "lang": "de",
                "value": "Name",
            },
            {
                "detector": "add_mul_alias",
                "action": ACTION_REMOVE_ALIAS,
                "_hidden": True,
                "row_id": row_id,
                "lang": "fr",
                "value": "Name",
            },
        ]
        payload, descriptions = build_payload(item, diffs)

        assert payload["aliases"]["mul"] == [{"language": "mul", "value": "Name"}]
        assert payload["aliases"]["de"] == []
        assert payload["aliases"]["fr"] == []
        # Only the add-mul-alias line is surfaced; the hidden removals are silent.
        assert descriptions == ["add mul alias: 'Name'"]

    def test_missing_reason_on_non_hidden_diff_degrades_gracefully(self):
        # Defensive: a non-hidden remove-alias without a reason should still
        # produce a (reason-less) line rather than raising.
        item = FakeItem(aliases={"en": ["Solo"]})
        diff = {
            "detector": "alias_equals_label",
            "action": ACTION_REMOVE_ALIAS,
            "lang": "en",
            "value": "Solo",
        }
        payload, descriptions = build_payload(item, [diff])
        assert payload["aliases"]["en"] == []
        assert descriptions == ["remove alias [en] 'Solo'"]


# ==== ACTION_REMOVE_REFS summaries ===========================================
#
# The reference-removal action is shared by detect_duplicate_refs and every
# ref-category detector, so the log line must reflect which one removed it.


class TestRemoveRefsSummaries:
    def _item(self, pid: str = "P373") -> FakeItem:
        claim = FakeClaim(
            "Q1$ref",
            {"id": "Q1$ref", "references": [{"hash": "h1"}, {"hash": "h2"}]},
        )
        return FakeItem(claims={pid: [claim]})

    def _diff(self, detector: str, pid: str = "P373") -> dict:
        return {
            "detector": detector,
            "action": ACTION_REMOVE_REFS,
            "pid": pid,
            "claim_id": "Q1$ref",
            "ref_hash": "h1",
        }

    def test_removes_the_targeted_reference(self):
        item = self._item()
        payload, _ = build_payload(item, [self._diff("wikimedia")])
        assert payload["claims"][0]["references"] == [{"hash": "h2"}]

    @pytest.mark.parametrize(
        "detector,expected",
        [
            ("dup_retrieved", "remove duplicate reference on P373"),
            ("wikimedia", "remove imported-from-Wikimedia reference on P373"),
            ("aggregator", "remove aggregator reference on P373"),
            ("community", "remove community reference on P373"),
            ("redundant", "remove redundant reference on P373"),
            ("inferred", "remove inferred reference on P373"),
            ("obsolete", "remove obsolete-ID reference on P373"),
            ("self_stated_in", "remove tautological stated-in reference on P373"),
        ],
    )
    def test_summary_reflects_detector(self, detector, expected):
        item = self._item()
        _, descriptions = build_payload(item, [self._diff(detector)])
        assert descriptions == [expected]

    def test_unknown_detector_falls_back_to_weak(self):
        item = self._item()
        _, descriptions = build_payload(item, [self._diff("mystery")])
        assert descriptions == ["remove weak reference on P373"]
