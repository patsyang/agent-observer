from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db.connection import connect
from app.ingest.service import ingest_telemetry
from app.risks.service import get_risk_summary
from app.usage.service import get_usage_summary


def _usage_risk_batch() -> dict:
    observed_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    return {
        "batch_id": "batch-usage-001",
        "protocol_version": "agent-observer-telemetry/v2",
        "agent_version": "0.2.0",
        "collector_id": "collector-codex",
        "source": "codex",
        "cursor": "cursor-usage-001",
        "items": [
            {
                "source_event_id": "usage-implementation-001",
                "fact_type": "usage",
                "category": "usage",
                "quality": "high",
                "severity": "low",
                "summary": "Implementation usage",
                "occurred_at": observed_at,
                "span": "session:s-001",
                "raw_hash": "hash-usage-implementation",
                "projection": {
                    "activity_tag": "implementation",
                    "units": 120,
                    "input_tokens": 200,
                    "cached_input_tokens": 80,
                },
                "usage": {
                    "scope": "session",
                    "units": 120,
                    "activity_tag": "implementation",
                    "session_id": "session-001",
                    "conversation_id": "conversation-001",
                    "project_ref": "project-agent-observer",
                    "account_ref": "account-local",
                },
                "source_refs": {"conversation_ref": "conversation-001"},
                "source_specific": {"codex_event_type": "usage_summary"},
            },
            {
                "source_event_id": "usage-fix-001",
                "fact_type": "usage",
                "category": "usage",
                "quality": "high",
                "severity": "low",
                "summary": "Fix usage",
                "occurred_at": observed_at,
                "span": "conversation:c-001",
                "raw_hash": "hash-usage-fix",
                "projection": {
                    "activity_tag": "bug_fix",
                    "units": 40,
                    "input_tokens": 50,
                    "cached_input_tokens": 10,
                },
                "usage": {
                    "scope": "conversation",
                    "units": 40,
                    "activity_tag": "bug_fix",
                    "session_id": "session-001",
                    "conversation_id": "conversation-001",
                    "project_ref": "project-agent-observer",
                    "account_ref": "account-local",
                },
                "source_refs": {"conversation_ref": "conversation-001"},
                "source_specific": {"codex_event_type": "usage_summary"},
            },
            {
                "source_event_id": "usage-unknown-001",
                "fact_type": "usage",
                "category": "usage",
                "quality": "low",
                "severity": "low",
                "summary": "Usage with unknown activity label",
                "occurred_at": observed_at,
                "span": "session:s-002",
                "raw_hash": "hash-usage-unknown",
                "projection": {"activity_tag": "unknown", "units": 15},
                "usage": {"scope": "session", "units": 15, "activity_tag": "unknown"},
                "source_refs": {"conversation_ref": "conversation-002"},
                "source_specific": {"codex_event_type": "usage_summary"},
            },
            {
                "source_event_id": "risk-sensitive-001",
                "fact_type": "risk",
                "category": "sensitive_content_exposure",
                "quality": "high",
                "severity": "high",
                "summary": "Sensitive configuration touched through raw category",
                "occurred_at": observed_at,
                "span": "session:s-001",
                "raw_hash": "hash-risk-sensitive",
                "projection": {"object_type": "configuration", "count": 1},
                "risk": {
                    "risk_type": "sensitive_content_exposure",
                    "severity": "high",
                    "object_type": "configuration",
                },
                "source_refs": {"conversation_ref": "conversation-001"},
                "source_specific": {"codex_event_type": "tool_result"},
            },
        ],
    }


def test_usage_rollups_summarize_effective_and_unknown_usage(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, _usage_risk_batch())
        summary = get_usage_summary(conn)

    total_effective = next(row for row in summary["rollups"] if row["scope"] == "total")
    unknown = next(row for row in summary["rollups"] if row["activity_tag"] == "unknown")

    assert total_effective["units"] == 175
    assert set(total_effective) == {"rollup_id", "window", "scope", "scope_value", "units", "activity_tag", "evidence_refs"}
    assert unknown["scope_value"] == "unknown"
    assert summary["totals"]["unknown_units"] > 0


def test_usage_summary_returns_empty_rollup_when_no_usage_signals(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        summary = get_usage_summary(conn)

    assert summary == {
        "window": "24h",
        "rollups": [],
        "trend": [],
        "totals": {
            "effective_units": 0,
            "unknown_units": 0,
            "cached_input_units": 0,
            "input_token_units": 0,
            "cache_hit_rate": 0,
        },
    }


def test_usage_summary_filters_by_window_and_rebuilds_rollups(tmp_path):
    old_at = (datetime.now(UTC) - timedelta(days=2)).replace(microsecond=0).isoformat()
    with connect(tmp_path / "observer.sqlite") as conn:
        batch = _usage_risk_batch()
        batch["items"][0]["source_event_id"] = "old-effective"
        batch["items"][0]["occurred_at"] = old_at
        ingest_telemetry(conn, batch)
        recent = get_usage_summary(conn, window="1h")
        all_time = get_usage_summary(conn, window="all")

    assert recent["totals"]["effective_units"] == 55
    assert all_time["totals"]["effective_units"] == 175


def test_usage_summary_read_does_not_write_rollup_rows(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, _usage_risk_batch())
        before = conn.execute("select count(*) from usage_rollups").fetchone()[0]
        summary = get_usage_summary(conn, window="1h")
        after = conn.execute("select count(*) from usage_rollups").fetchone()[0]

    assert summary["totals"]["effective_units"] == 175
    assert before == 0
    assert after == 0


def test_usage_summary_includes_time_trend(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, _usage_risk_batch())
        summary = get_usage_summary(conn, window="1h")

    assert summary["trend"]
    assert summary["trend"][0]["effective_units"] == 175
    assert summary["trend"][0]["unknown_units"] == 15
    assert summary["trend"][0]["cached_input_units"] == 90
    assert summary["trend"][0]["input_token_units"] == 250
    assert summary["trend"][0]["cache_hit_rate"] == 0.36
    assert summary["totals"]["cached_input_units"] == 90
    assert summary["totals"]["input_token_units"] == 250
    assert summary["totals"]["cache_hit_rate"] == 0.36


def test_risk_summary_uses_projection_refs_and_object_counts(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, _usage_risk_batch())
        summary = get_risk_summary(conn)
        detailed = get_risk_summary(conn, mode="detailed")

    signal = summary["signals"][0]
    assert signal["risk_type"] == "sensitive_content_exposure"
    assert signal["object_type"] == "configuration"
    assert signal["count"] == 1
    assert signal["highest_severity"] == "high"
    assert "evidence_refs" not in signal
    assert "trend" not in signal
    assert signal["top_examples"] == ["Sensitive configuration touched through raw category"]
    detailed_signal = detailed["signals"][0]
    assert detailed_signal["evidence_refs"] == ["proj-risk-sensitive-001"]
    assert detailed_signal["trend"] == [{"occurred_at": signal["last_seen_at"], "severity": "high"}]


def test_risk_summary_filters_by_window(tmp_path):
    old_at = (datetime.now(UTC) - timedelta(days=2)).replace(microsecond=0).isoformat()
    with connect(tmp_path / "observer.sqlite") as conn:
        batch = _usage_risk_batch()
        batch["items"][3]["source_event_id"] = "old-risk-sensitive"
        batch["items"][3]["occurred_at"] = old_at
        ingest_telemetry(conn, batch)
        recent = get_risk_summary(conn, window="1h")
        all_time = get_risk_summary(conn, window="all")

    assert recent["window"] == "1h"
    assert recent["signals"] == []
    assert all_time["signals"][0]["count"] == 1


def test_risk_summary_filters_unexplained_credential_false_positive(tmp_path):
    observed_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "batch-risk-sensitive-context",
                "protocol_version": "agent-observer-telemetry/v2",
                "agent_version": "0.2.0",
                "collector_id": "collector-codex",
                "source": "codex",
                "cursor": "cursor-risk-sensitive-context",
                "items": [
                    {
                        "source_event_id": "risk-token-telemetry",
                        "fact_type": "risk",
                        "category": "sensitive_content_exposure",
                        "quality": "high",
                        "severity": "high",
                        "summary": "Legacy token false positive",
                        "occurred_at": observed_at,
                        "span": "session:false-positive",
                        "raw_hash": "hash-risk-token-telemetry",
                        "projection": {
                            "object_type": "credential",
                            "category_count": 1,
                            "sensitive_categories": ["sensitive_reference"],
                        },
                        "upload_raw": True,
                        "raw_content": '{"payload":{"arguments":"git commit -m \\"token telemetry contract\\""}}',
                        "risk": {"risk_type": "sensitive_content_exposure", "severity": "high", "object_type": "credential"},
                        "source_refs": {"conversation_ref": "conversation-token-telemetry"},
                        "source_specific": {"codex_event_type": "function_call"},
                    },
                    {
                        "source_event_id": "risk-auth-status",
                        "fact_type": "risk",
                        "category": "sensitive_content_exposure",
                        "quality": "high",
                        "severity": "high",
                        "summary": "Legacy auth reference",
                        "occurred_at": observed_at,
                        "span": "session:auth",
                        "raw_hash": "hash-risk-auth",
                        "projection": {
                            "object_type": "credential",
                            "category_count": 1,
                            "sensitive_categories": ["sensitive_reference"],
                        },
                        "upload_raw": True,
                        "raw_content": '{"payload":{"arguments":"uv run oh auth status"}}',
                        "risk": {"risk_type": "sensitive_content_exposure", "severity": "high", "object_type": "credential"},
                        "source_refs": {"conversation_ref": "conversation-auth"},
                        "source_specific": {"codex_event_type": "function_call"},
                    },
                ],
            },
        )
        summary = get_risk_summary(conn)

    signals = {(signal["risk_type"], signal["object_type"]): signal for signal in summary["signals"]}
    assert ("sensitive_content_exposure", "credential") not in signals
    assert ("sensitive_content_exposure", "auth") not in signals
