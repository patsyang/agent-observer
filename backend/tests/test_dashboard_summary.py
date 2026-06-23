from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.dashboard.service import get_dashboard_summary
from app.db.connection import connect
from app.ingest.service import ingest_telemetry


def test_dashboard_summary_is_lightweight_and_windowed(tmp_path):
    observed_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "dashboard-summary-001",
                "protocol_version": "agent-observer-telemetry/v3",
                "agent_version": "0.3.0",
                "collector_id": "collector-dashboard",
                "source": "codex",
        "source_id": "codex-local",
        "agent_type": "codex",
        "source_kind": "codex_local",
                "cursor": "1",
                "items": [
                    {
                        "source_event_id": "dashboard-error-001",
                        "fact_type": "error",
                        "category": "tool_execution_failure",
                        "quality": "high",
                        "severity": "high",
                        "summary": "function_call_output failed with exit_code=1",
                        "occurred_at": observed_at,
                        "span": "session:dashboard",
                        "raw_hash": "hash-dashboard-error",
                        "projection": {"tool_name": "exec_command", "exit_code": 1},
                        "error_signature": {"signature_key": "dashboard-tool-failure", "category": "tool_execution_failure"},
                        "source_refs": {"conversation_ref": "conv-dashboard"},
                        "source_specific": {"event_type": "tool_result"},
                        "raw_content": "raw command content must not be in summary",
                        "upload_raw": True,
                    }
                ],
            },
        )

        summary = get_dashboard_summary(conn, window="1h")

    assert summary["facts"]["total"] == 1
    assert summary["facts"]["items"][0]["content_preview"]
    assert "raw_content" not in summary["facts"]["items"][0]
    assert summary["signals"]["total"] >= 1
    assert summary["signals"]["items"][0]["signal_kind"] == "tool_execution_failure"


def test_dashboard_summary_uses_event_time_not_backfill_ingest_time(tmp_path):
    old_observed_at = (datetime.now(UTC) - timedelta(days=1)).replace(microsecond=0).isoformat()
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "dashboard-backfill-001",
                "protocol_version": "agent-observer-telemetry/v3",
                "agent_version": "0.3.0",
                "collector_id": "collector-dashboard",
                "source": "codex",
        "source_id": "codex-local",
        "agent_type": "codex",
        "source_kind": "codex_local",
                "cursor": "backfill",
                "items": [
                    {
                        "source_event_id": "dashboard-backfill-prompt",
                        "fact_type": "content",
                        "category": "agent_prompt",
                        "quality": "high",
                        "severity": "low",
                        "summary": "历史 Prompt 刚刚完成回填。",
                        "occurred_at": old_observed_at,
                        "span": "session:backfill",
                        "raw_hash": "hash-dashboard-backfill",
                        "projection": {"role": "user", "content_length": 12, "prompt_text": "历史 Prompt 刚刚完成回填。"},
                        "upload_raw": True,
                        "raw_content": "历史 Prompt 刚刚完成回填。",
                        "source_refs": {"conversation_ref": "conv-dashboard-backfill"},
                        "source_specific": {"event_type": "message"},
                    }
                ],
            },
        )

        summary = get_dashboard_summary(conn, window="1h")

    assert summary["facts"]["time_basis"] == "occurred"
    assert summary["facts"]["total"] == 0
    assert summary["facts"]["items"] == []


def test_dashboard_summary_filters_by_agent_type(tmp_path):
    observed_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    with connect(tmp_path / "observer.sqlite") as conn:
        for agent_type, source_id, source_kind in (
            ("codex", "codex-local", "codex_local"),
            ("workbuddy", "workbuddy-local", "workbuddy_local"),
        ):
            ingest_telemetry(
                conn,
                {
                    "batch_id": f"dashboard-agent-{agent_type}",
                    "protocol_version": "agent-observer-telemetry/v3",
                    "agent_version": "0.3.0",
                    "collector_id": "collector-dashboard",
                    "source": agent_type,
                    "source_id": source_id,
                    "agent_type": agent_type,
                    "source_kind": source_kind,
                    "cursor": agent_type,
                    "items": [
                        {
                            "source_event_id": f"dashboard-prompt-{agent_type}",
                            "fact_type": "content",
                            "category": "agent_prompt",
                            "quality": "high",
                            "severity": "low",
                            "summary": f"{agent_type} Prompt",
                            "occurred_at": observed_at,
                            "span": f"session:{agent_type}",
                            "raw_hash": f"hash-dashboard-{agent_type}",
                            "projection": {"role": "user", "prompt_text": f"{agent_type} Prompt"},
                            "upload_raw": True,
                            "raw_content": f"{agent_type} Prompt",
                            "source_refs": {"conversation_ref": f"conv-dashboard-{agent_type}"},
                            "source_specific": {"event_type": "message"},
                        }
                    ],
                },
            )

        summary = get_dashboard_summary(conn, window="1h", agent_type="workbuddy")

    assert summary["facts"]["total"] == 1
    assert summary["facts"]["items"][0]["agent_type"] == "workbuddy"


def test_dashboard_summary_today_window_starts_at_current_day(tmp_path):
    today = datetime.now(UTC).replace(microsecond=0)
    yesterday = today - timedelta(days=1)
    with connect(tmp_path / "observer.sqlite") as conn:
        for event_id, occurred_at in (
            ("dashboard-yesterday", yesterday.isoformat()),
            ("dashboard-today", today.isoformat()),
        ):
            ingest_telemetry(
                conn,
                {
                    "batch_id": f"batch-{event_id}",
                    "protocol_version": "agent-observer-telemetry/v3",
                    "agent_version": "0.3.0",
                    "collector_id": "collector-dashboard",
                    "source": "codex",
                    "source_id": "codex-local",
                    "agent_type": "codex",
                    "source_kind": "codex_local",
                    "cursor": event_id,
                    "items": [
                        {
                            "source_event_id": event_id,
                            "fact_type": "content",
                            "category": "agent_prompt",
                            "quality": "high",
                            "severity": "low",
                            "summary": event_id,
                            "occurred_at": occurred_at,
                            "span": f"session:{event_id}",
                            "raw_hash": f"hash-{event_id}",
                            "projection": {"role": "user", "prompt_text": event_id},
                            "upload_raw": True,
                            "raw_content": event_id,
                            "source_refs": {"conversation_ref": f"conv-{event_id}"},
                            "source_specific": {"event_type": "message"},
                        }
                    ],
                },
            )

        summary = get_dashboard_summary(conn, window="today")

    assert summary["facts"]["total"] == 1
    assert summary["facts"]["items"][0]["source_event_id"] == "dashboard-today"
