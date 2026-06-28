"""
test_database.py

Tests for database.py using SQLite so no MariaDB connection is needed.

Run with:
    python -m pytest test_database.py -v
"""

import pathlib
from typing import Iterator

import pytest

from cleanup.database import WikidataCleanupTracker


@pytest.fixture
def tracker(tmp_path) -> Iterator[WikidataCleanupTracker]:
    """Fresh in-memory SQLite tracker for each test."""
    db = tmp_path / "test.db"
    t = WikidataCleanupTracker(db_path=db)
    yield t
    t.close()


# ==== is_processed ===========================================================


class TestIsProcessed:
    def test_new_item_not_processed(self, tracker):
        assert not tracker.is_processed("Q1")

    def test_changed_item_is_processed(self, tracker):
        tracker.mark_changed("Q1", run_id="r1", diffs_count=2, edit_summary="test")
        assert tracker.is_processed("Q1")

    def test_skipped_item_not_considered_processed(self, tracker):
        tracker.mark_skipped("Q1", run_id="r1")
        assert not tracker.is_processed("Q1")

    def test_error_item_not_considered_processed(self, tracker):
        tracker.mark_error("Q1", Exception("oops"), run_id="r1")
        assert not tracker.is_processed("Q1")

    def test_different_qid_not_affected(self, tracker):
        tracker.mark_changed("Q1", run_id="r1")
        assert not tracker.is_processed("Q2")


# ==== mark_changed ===========================================================


class TestMarkChanged:
    def test_records_status_changed(self, tracker):
        tracker.mark_changed(
            "Q1", run_id="r1", diffs_count=3, edit_summary="remove alias"
        )
        rows = tracker.execute_query(
            "SELECT status, diffs_count, edit_summary FROM qids WHERE qid = %s",
            ("Q1",),
        )
        assert len(rows) == 1
        assert rows[0][0] == "changed"
        assert rows[0][1] == 3
        assert "alias" in rows[0][2]

    def test_long_summary_truncated(self, tracker):
        tracker.mark_changed("Q1", edit_summary="x" * 3000)
        rows = tracker.execute_query(
            "SELECT edit_summary FROM qids WHERE qid = %s", ("Q1",)
        )
        assert len(rows[0][0]) <= 2000


# ==== mark_skipped ===========================================================


class TestMarkSkipped:
    def test_records_status_skipped(self, tracker):
        tracker.mark_skipped("Q1", run_id="r1")
        rows = tracker.execute_query("SELECT status FROM qids WHERE qid = %s", ("Q1",))
        assert rows[0][0] == "skipped"

    def test_skipped_not_overwritten_by_duplicate(self, tracker):
        tracker.mark_skipped("Q1", run_id="r1")
        tracker.mark_skipped("Q1", run_id="r1")  # second call — INSERT IGNORE
        rows = tracker.execute_query(
            "SELECT COUNT(*) FROM qids WHERE qid = %s", ("Q1",)
        )
        assert rows[0][0] == 1


# ==== mark_error =============================================================


class TestMarkError:
    def test_records_status_error(self, tracker):
        tracker.mark_error("Q1", Exception("network timeout"), run_id="r1")
        rows = tracker.execute_query(
            "SELECT status, error_msg FROM qids WHERE qid = %s", ("Q1",)
        )
        assert rows[0][0] == "error"
        assert "timeout" in rows[0][1]

    def test_long_error_truncated(self, tracker):
        tracker.mark_error("Q1", Exception("e" * 3000))
        rows = tracker.execute_query(
            "SELECT error_msg FROM qids WHERE qid = %s", ("Q1",)
        )
        assert len(rows[0][0]) <= 2000


# ==== get_processed_qids =====================================================


class TestGetProcessedQids:
    def test_empty_initially(self, tracker):
        assert tracker.get_processed_qids() == set()

    def test_changed_qids_returned(self, tracker):
        tracker.mark_changed("Q1", run_id="r1")
        tracker.mark_changed("Q2", run_id="r1")
        assert tracker.get_processed_qids() == {"Q1", "Q2"}

    def test_skipped_and_error_excluded(self, tracker):
        tracker.mark_changed("Q1", run_id="r1")
        tracker.mark_skipped("Q2", run_id="r1")
        tracker.mark_error("Q3", Exception("oops"), run_id="r1")
        assert tracker.get_processed_qids() == {"Q1"}


# ==== summary ================================================================


class TestSummary:
    def test_empty_summary(self, tracker):
        counts = tracker.summary()
        assert counts == {}

    def test_summary_counts(self, tracker):
        tracker.mark_changed("Q1", run_id="r1")
        tracker.mark_changed("Q2", run_id="r1")
        tracker.mark_skipped("Q3", run_id="r1")
        tracker.mark_error("Q4", Exception("oops"), run_id="r1")
        counts = tracker.summary()
        assert counts["changed"] == 2
        assert counts["skipped"] == 1
        assert counts["error"] == 1


# ==== run_id isolation =======================================================


class TestRunIdIsolation:
    def test_multiple_runs_same_qid(self, tracker):
        tracker.mark_changed("Q1", run_id="run-001", diffs_count=1)
        tracker.mark_changed("Q1", run_id="run-002", diffs_count=2)
        rows = tracker.execute_query(
            "SELECT run_id, diffs_count FROM qids WHERE qid = %s", ("Q1",)
        )
        run_ids = {r[0] for r in rows}
        # Both runs should be recorded (different primary keys)
        assert "run-001" in run_ids
        assert "run-002" in run_ids

    def test_is_processed_true_after_any_run(self, tracker):
        tracker.mark_changed("Q1", run_id="run-001")
        # Item was changed in run-001, so is_processed should be True
        assert tracker.is_processed("Q1")
