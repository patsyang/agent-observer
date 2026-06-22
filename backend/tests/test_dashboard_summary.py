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
                "protocol_version": "agent-observer-telemetry/v2",
                "agent_version": "0.2.0",
                "collector_id": "collector-dashboard",
                "source": "codex",
                "cursor": "1",
                "items": [
                    {
                        "source_event_id": "dashboard-error-001",
                        "fact_type": "error",
                        "category": "codex_error",
                        "quality": "high",
                        "severity": "high",
                        "summary": "function_call_output failed with exit_code=1",
                        "occurred_at": observed_at,
                        "span": "session:dashboard",
                        "raw_hash": "hash-dashboard-error",
                        "projection": {"tool_name": "exec_command", "exit_code": 1},
                        "error_signature": {"signature_key": "dashboard-tool-failure", "category": "codex_error"},
                        "source_refs": {"conversation_ref": "conv-dashboard"},
                        "source_specific": {"codex_event_type": "tool_result"},
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
    assert summary["signals"]["items"][0]["signal_kind"] == "tool_failure_cluster"


def test_dashboard_summary_uses_event_time_not_backfill_ingest_time(tmp_path):
    old_observed_at = (datetime.now(UTC) - timedelta(days=1)).replace(microsecond=0).isoformat()
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "dashboard-backfill-001",
                "protocol_version": "agent-observer-telemetry/v2",
                "agent_version": "0.2.0",
                "collector_id": "collector-dashboard",
                "source": "codex",
                "cursor": "backfill",
                "items": [
                    {
                        "source_event_id": "dashboard-backfill-prompt",
                        "fact_type": "content",
                        "category": "codex_prompt",
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
                        "source_specific": {"codex_event_type": "message"},
                    }
                ],
            },
        )

        summary = get_dashboard_summary(conn, window="1h")

    assert summary["facts"]["time_basis"] == "occurred"
    assert summary["facts"]["total"] == 0
    assert summary["facts"]["items"] == []
