"""signal_summary —— 按 risk_family × severity 聚合的测试。"""
from __future__ import annotations

from app.behavior_signals.service import signal_summary
from app.db.connection import connect


def _insert_signal(
    conn,
    *,
    signal_id: str,
    signal_kind: str,
    severity: str,
    decision_state: str = "unread",
    last_event_at: str = "2026-07-01T00:00:00+00:00",
) -> None:
    conn.execute(
        """
        insert into behavior_signals (
          signal_id, signal_key, signal_kind, title, why_it_matters, severity, confidence,
          priority_score, affected_scope_json, evidence_groups_json, linked_conversations_json,
          usage_summary_json, enrichment_status_summary_json, suggested_actions_json,
          decision_state, snapshot_hash, first_seen_at, last_seen_at, last_event_at,
          occurrence_count, latest_fact_id, latest_summary, updated_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            signal_id, signal_id, signal_kind, "t", "w", severity, "high", 50, "{}", "[]", "[]",
            "{}", "{}", "[]", decision_state, "h", last_event_at, last_event_at, last_event_at,
            1, None, "s", last_event_at,
        ),
    )


def _by_family(summary: dict) -> dict:
    return {family["id"]: family for family in summary["families"]}


def test_signal_summary_groups_by_family_and_severity(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        _insert_signal(conn, signal_id="s1", signal_kind="sensitive_content_exposure", severity="high")
        _insert_signal(conn, signal_id="s2", signal_kind="sensitive_content_exposure", severity="high")
        _insert_signal(conn, signal_id="s3", signal_kind="destructive_operation_attempt", severity="high")
        _insert_signal(conn, signal_id="s4", signal_kind="tool_execution_failure", severity="medium")
        _insert_signal(conn, signal_id="s5", signal_kind="usage_spike", severity="medium")
        _insert_signal(conn, signal_id="s6", signal_kind="tool_execution_failure", severity="high", decision_state="handled")
        summary = signal_summary(conn, window="all")

    families = _by_family(summary)
    assert families["data_exposure"]["total"] == 2
    assert families["data_exposure"]["by_severity"]["high"] == 2
    assert families["behavior_anomaly"]["total"] == 1
    assert families["execution_error"]["total"] == 1  # handled signal excluded
    assert families["usage_cost"]["total"] == 1
    assert summary["total"] == 5
    assert summary["high_severity_total"] == 3
    assert "uncategorized" not in families  # no drift


def test_signal_summary_surfaces_uncategorized_for_drift(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        _insert_signal(conn, signal_id="s1", signal_kind="brand_new_unmapped_kind", severity="high")
        summary = signal_summary(conn, window="all")

    families = _by_family(summary)
    assert "uncategorized" in families
    assert families["uncategorized"]["total"] == 1
    assert summary["total"] == 1


def test_signal_summary_respects_window(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        _insert_signal(
            conn, signal_id="old", signal_kind="sensitive_content_exposure", severity="high",
            last_event_at="2000-01-01T00:00:00+00:00",
        )
        _insert_signal(
            conn, signal_id="recent", signal_kind="sensitive_content_exposure", severity="high",
            last_event_at="2099-01-01T00:00:00+00:00",
        )
        summary = signal_summary(conn, window="1h")

    families = _by_family(summary)
    assert families["data_exposure"]["total"] == 1  # only the future-dated one passes >= now-1h
    assert summary["total"] == 1
