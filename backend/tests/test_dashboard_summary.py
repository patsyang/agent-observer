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
                "collector_id": "collector-dashboard",
                "source": "codex",
                "cursor": "1",
                "items": [
                    {
                        "source_event_id": "dashboard-risk-001",
                        "fact_type": "risk",
                        "category": "high_risk_operation",
                        "quality": "high",
                        "severity": "high",
                        "summary": "检测到删除类命令。",
                        "occurred_at": observed_at,
                        "span": "session:dashboard",
                        "raw_hash": "hash-dashboard-risk",
                        "projection": {"risk_type": "high_risk_operation", "object_type": "command"},
                        "risk": {"risk_type": "high_risk_operation", "severity": "high", "object_type": "command"},
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
    assert summary["risks"]["top"][0]["risk_type"] == "high_risk_operation"
    assert summary["stories"]["total"] >= 1


def test_dashboard_summary_uses_event_time_not_backfill_ingest_time(tmp_path):
    old_observed_at = (datetime.now(UTC) - timedelta(days=1)).replace(microsecond=0).isoformat()
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "dashboard-backfill-001",
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
                        "projection": {"role": "user", "content_length": 12},
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
