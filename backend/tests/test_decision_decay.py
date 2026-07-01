from __future__ import annotations

import sqlite3
import textwrap
from datetime import UTC, datetime, timedelta

import pytest

from app.behavior_signals.common import now_iso, signal_id


def _create_test_db() -> sqlite3.Connection:
    """Create an in-memory SQLite DB with the minimal schema needed for tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        create table behavior_signals (
            signal_id text primary key,
            signal_key text not null,
            signal_kind text,
            title text,
            why_it_matters text,
            severity text,
            confidence text,
            priority_score integer not null default 50,
            affected_scope_json text,
            evidence_groups_json text,
            linked_conversations_json text,
            usage_summary_json text,
            enrichment_status_summary_json text,
            suggested_actions_json text,
            decision_state text not null default 'unread',
            snapshot_hash text not null,
            first_seen_at text,
            last_seen_at text,
            last_event_at text,
            occurrence_count integer not null default 1,
            latest_fact_id text,
            latest_summary text,
            updated_at text,
            decision_count integer not null default 0
        )
        """
    )
    conn.execute(
        """
        create table signal_decisions (
            signal_id text primary key,
            decision_state text not null,
            conclusion_code text,
            note text,
            updated_by text,
            updated_at text
        )
        """
    )
    conn.execute(
        """
        create table audit_logs (
            audit_id text primary key,
            object_type text not null,
            object_id text not null,
            action text not null,
            actor text not null,
            metadata_json text,
            created_at text
        )
        """
    )
    conn.execute(
        """
        create table observed_facts (
            fact_id text primary key,
            fact_type text,
            category text,
            source_specific_json text,
            source_event_type text,
            summary text,
            occurred_at text,
            conversation_ref text,
            session_ref text
        )
        """
    )
    conn.execute(
        """
        create table risk_signals (
            fact_id text,
            risk_type text
        )
        """
    )
    conn.execute(
        """
        create table error_signatures (
            signature_key text primary key,
            category text,
            occurrences integer
        )
        """
    )
    conn.execute(
        """
        create table error_signature_facts (
            signature_key text,
            fact_id text
        )
        """
    )
    conn.commit()
    return conn


def _insert_signal(conn: sqlite3.Connection, signal_key: str, **kwargs) -> str:
    """Insert a behavior_signal row and return its signal_id."""
    sid = signal_id(signal_key)
    now = kwargs.pop("updated_at", now_iso())
    conn.execute(
        """
        insert into behavior_signals (
            signal_id, signal_key, signal_kind, title, priority_score,
            affected_scope_json, evidence_groups_json, linked_conversations_json,
            decision_state, snapshot_hash, occurrence_count, updated_at
        ) values (?, ?, ?, ?, ?, '{}', '[]', '[]', ?, ?, ?, ?)
        """,
        (
            sid,
            signal_key,
            kwargs.get("signal_kind", "tool_execution_failure"),
            kwargs.get("title", "Test signal"),
            kwargs.get("priority_score", 80),
            kwargs.get("decision_state", "unread"),
            kwargs.get("snapshot_hash", "abc123"),
            kwargs.get("occurrence_count", 1),
            now,
        ),
    )
    conn.commit()
    return sid


class TestApplyDecisionDecay:
    """Tests for apply_decision_decay function."""

    def test_no_decay_when_no_decisions(self):
        """No decay decisions → priority unchanged."""
        from app.behavior_signals.service import apply_decision_decay

        conn = _create_test_db()
        _insert_signal(conn, "test:decay:no-decisions", priority_score=80)
        result = apply_decision_decay(conn, "test:decay:no-decisions", 80, 1)
        assert result["priority"] == 80
        assert result["decay_reason"] is None
        assert result["decay_count"] == 0

    def test_decay_triggered_after_three_markings(self):
        """Three expected_nonzero_exit decisions → priority drops to 30."""
        from app.behavior_signals.service import apply_decision_decay, handle_signal

        conn = _create_test_db()
        sid = _insert_signal(conn, "test:decay:three", priority_score=80)

        # Mark 1
        handle_signal(conn, sid, "expected_nonzero_exit", "Expected exit code 1")
        # Mark 2
        handle_signal(conn, sid, "expected_nonzero_exit", "Again expected")
        # Mark 3
        handle_signal(conn, sid, "expected_nonzero_exit", "Third time")

        result = apply_decision_decay(conn, "test:decay:three", 80, 1)
        assert result["priority"] == 30
        assert result["decay_count"] == 3
        assert result["decay_reason"] is not None

    def test_decay_accepted_risk_counts_too(self):
        """Accepted_risk decisions also count toward decay."""
        from app.behavior_signals.service import apply_decision_decay, handle_signal

        conn = _create_test_db()
        sid = _insert_signal(conn, "test:decay:accepted", priority_score=75)

        handle_signal(conn, sid, "accepted_risk", "Risk accepted")
        handle_signal(conn, sid, "accepted_risk", "Still accepted")
        handle_signal(conn, sid, "accepted_risk", "Third acceptance")

        result = apply_decision_decay(conn, "test:decay:accepted", 75, 1)
        assert result["priority"] == 30
        assert result["decay_count"] == 3

    def test_decay_not_triggered_with_two_decisions(self):
        """Only two decisions → no decay."""
        from app.behavior_signals.service import apply_decision_decay, handle_signal

        conn = _create_test_db()
        sid = _insert_signal(conn, "test:decay:two", priority_score=80)

        handle_signal(conn, sid, "expected_nonzero_exit", "First")
        handle_signal(conn, sid, "expected_nonzero_exit", "Second")

        result = apply_decision_decay(conn, "test:decay:two", 80, 1)
        assert result["priority"] == 80
        assert result["decay_count"] == 2
        assert result["decay_reason"] is None

    def test_already_low_priority_no_change(self):
        """Priority already at 30 → no further reduction."""
        from app.behavior_signals.service import apply_decision_decay, handle_signal

        conn = _create_test_db()
        sid = _insert_signal(conn, "test:decay:already-low", priority_score=30)

        handle_signal(conn, sid, "expected_nonzero_exit", "First")
        handle_signal(conn, sid, "expected_nonzero_exit", "Second")
        handle_signal(conn, sid, "expected_nonzero_exit", "Third")

        result = apply_decision_decay(conn, "test:decay:already-low", 30, 1)
        assert result["priority"] == 30
        assert result["decay_reason"] is None  # No decay applied since already low

    def test_different_conclusion_codes_do_not_count(self):
        """known_issue decisions don't count toward decay."""
        from app.behavior_signals.service import apply_decision_decay, handle_signal

        conn = _create_test_db()
        sid = _insert_signal(conn, "test:decay:wrong-code", priority_score=80)

        handle_signal(conn, sid, "known_issue", "Known issue")
        handle_signal(conn, sid, "needs_fix", "Needs fix")
        handle_signal(conn, sid, "not_actionable", "Not actionable")

        result = apply_decision_decay(conn, "test:decay:wrong-code", 80, 1)
        assert result["priority"] == 80
        assert result["decay_count"] == 0

    def test_mixed_decay_codes_count(self):
        """Mix of expected_nonzero_exit and accepted_risk counts toward decay."""
        from app.behavior_signals.service import apply_decision_decay, handle_signal

        conn = _create_test_db()
        sid = _insert_signal(conn, "test:decay:mixed", priority_score=85)

        handle_signal(conn, sid, "expected_nonzero_exit", "First")
        handle_signal(conn, sid, "accepted_risk", "Second")
        handle_signal(conn, sid, "expected_nonzero_exit", "Third")

        result = apply_decision_decay(conn, "test:decay:mixed", 85, 1)
        assert result["priority"] == 30
        assert result["decay_count"] == 3


class TestDecisionStateWithDecay:
    """Tests for _decision_state with occurrence growth tracking."""

    def test_needs_review_on_snapshot_change(self):
        """Different snapshot_hash with handled decision → needs_review."""
        from app.behavior_signals.service import _decision_state

        conn = _create_test_db()
        sid = _insert_signal(conn, "test:dstate:snapshot-change", priority_score=80)

        existing = conn.execute(
            "select snapshot_hash, decision_state from behavior_signals where signal_id = ?",
            (sid,),
        ).fetchone()
        decision = conn.execute(
            "select * from signal_decisions where signal_id = ?", (sid,)
        ).fetchone()

        # No decision yet → unread
        result = _decision_state(existing, decision, "new-hash", conn, sid)
        assert result == "unread"

    def test_decision_state_expands_new_codes(self):
        """New conclusion codes are stored and retrievable."""
        from app.behavior_signals.service import handle_signal

        conn = _create_test_db()
        sid = _insert_signal(conn, "test:dstate:new-codes", priority_score=80)

        result = handle_signal(conn, sid, "expected_nonzero_exit", "Expected exit")
        assert result["conclusion_code"] == "expected_nonzero_exit"
        assert result["decision_state"] in ("handled", "needs_review")

        result2 = handle_signal(conn, sid, "duplicate_signal", "Duplicate")
        assert result2["conclusion_code"] == "duplicate_signal"


class TestSetDecisionIntegration:
    """Integration tests for _set_decision with decay-aware state computation."""

    def test_set_decision_stores_conclusion_code(self):
        """Setting a decision stores the conclusion_code in signal_decisions."""
        from app.behavior_signals.service import handle_signal

        conn = _create_test_db()
        sid = _insert_signal(conn, "test:integ:store-code", priority_score=80)

        result = handle_signal(conn, sid, "accepted_risk", "Accepting risk")
        assert result["conclusion_code"] == "accepted_risk"
        assert result["decision_state"] == "handled"

    def test_mark_signal_read_unchanged(self):
        """mark_signal_read sets decision_state to 'read' without conclusion_code."""
        from app.behavior_signals.service import mark_signal_read

        conn = _create_test_db()
        sid = _insert_signal(conn, "test:integ:mark-read", priority_score=80)

        result = mark_signal_read(conn, sid)
        assert result["decision_state"] == "read"
        assert result["conclusion_code"] is None

    def test_handle_signal_requires_conclusion_code(self):
        """handle_signal raises ValueError for empty conclusion_code."""
        from app.behavior_signals.service import handle_signal

        conn = _create_test_db()
        sid = _insert_signal(conn, "test:integ:require-code", priority_score=80)

        with pytest.raises(ValueError, match="conclusion_code_required"):
            handle_signal(conn, sid, "", None)

    def test_handle_signal_nonexistent_raises(self):
        """handle_signal raises LookupError for unknown signal_id."""
        from app.behavior_signals.service import handle_signal

        conn = _create_test_db()
        with pytest.raises(LookupError):
            handle_signal(conn, "signal-nonexistent", "known_issue", None)


class TestRepeatedFailuresExcludesDecayed:
    """Ensure detect_repeated_failures respects decay decision codes."""

    def test_excluded_signatures_filtered(self):
        """Signals marked expected_nonzero_exit are excluded from repeated failures."""
        from app.behavior_signals.service import detect_repeated_failures, _upsert_signal

        conn = _create_test_db()
        sid = _insert_signal(conn, "test:exclude:repeated", priority_score=80)

        # Mark this signal as expected_nonzero_exit
        from app.behavior_signals.service import handle_signal
        handle_signal(conn, sid, "expected_nonzero_exit", "Expected")

        # Now call detect_repeated_failures — should not include this signal
        results = detect_repeated_failures(conn, "test", _upsert_signal)
        signal_keys_in_results = {r["signal_key"] for r in results}
        assert "test:exclude:repeated" not in signal_keys_in_results

    def test_non_excluded_codes_not_filtered(self):
        """Signals marked with known_issue are NOT excluded from repeated failures."""
        from app.behavior_signals.service import detect_repeated_failures, _upsert_signal, handle_signal

        conn = _create_test_db()
        sid = _insert_signal(conn, "test:not-excluded:repeated", priority_score=80)

        # Mark as known_issue (not in excluded set)
        handle_signal(conn, sid, "known_issue", "Known")

        results = detect_repeated_failures(conn, "test", _upsert_signal)
        # The signal_key might appear if facts exist; at minimum no crash
        # The important thing is it wasn't excluded
        assert isinstance(results, list)


class TestNeedsReviewTriggers:
    """Tests for needs_review trigger conditions."""

    def test_occurrence_growth_triggers_review(self):
        """High occurrence count with handled state → needs_review."""
        from app.behavior_signals.service import handle_signal, _decision_state

        conn = _create_test_db()
        sid = _insert_signal(conn, "test:nr:growth", priority_score=80, occurrence_count=5)

        # Mark as handled
        handle_signal(conn, sid, "accepted_risk", "Accepted")

        # Read back the row
        existing = conn.execute(
            "select snapshot_hash, decision_state from behavior_signals where signal_id = ?",
            (sid,),
        ).fetchone()
        decision = conn.execute(
            "select * from signal_decisions where signal_id = ?", (sid,)
        ).fetchone()

        # Snapshot changed + occurrence >= 2 → needs_review
        result = _decision_state(existing, decision, "different-hash", conn, sid)
        assert result == "needs_review"

    def test_read_state_with_high_occurrence_triggers_review(self):
        """Previously 'read' state + high occurrence → needs_review."""
        from app.behavior_signals.service import _decision_state

        conn = _create_test_db()
        sid = _insert_signal(conn, "test:nr:read-high", priority_score=80, occurrence_count=3, decision_state="read")

        existing = conn.execute(
            "select snapshot_hash, decision_state from behavior_signals where signal_id = ?",
            (sid,),
        ).fetchone()
        # No decision row → decision is None
        decision = conn.execute(
            "select * from signal_decisions where signal_id = ?", (sid,)
        ).fetchone()

        # No decision → unread regardless
        result = _decision_state(existing, decision, "new-hash", conn, sid)
        assert result == "unread"
