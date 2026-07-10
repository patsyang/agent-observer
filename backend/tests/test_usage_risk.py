from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.db.connection import connect
from app.ingest.service import ingest_telemetry
from app.risks.service import get_risk_summary
from app.usage.service import get_usage_summary
from source_payloads import default_versions


def _usage_risk_batch() -> dict:
    observed_at = datetime.now(UTC).replace(microsecond=0).isoformat()
    return {
        "batch_id": "batch-usage-001",
        **default_versions(),
        "collector_id": "collector-codex",
        "source": "codex",
        "source_id": "codex-local",
        "agent_type": "codex",
        "source_kind": "codex_local",
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
                    "project_ref": "project-test-app",
                    "account_ref": "account-local",
                    "input_tokens": 200,
                    "output_tokens": 0,
                    "total_tokens": 200,
                    "cached_input_tokens": 80,
                    "cache_observed": True,
                    "unit_basis": "non_cached_input_plus_output",
                    "observability_level": "full",
                },
                "source_refs": {"conversation_ref": "conversation-001"},
                "source_specific": {"event_type": "usage_summary"},
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
                    "project_ref": "project-test-app",
                    "account_ref": "account-local",
                    "input_tokens": 50,
                    "output_tokens": 0,
                    "total_tokens": 50,
                    "cached_input_tokens": 10,
                    "cache_observed": True,
                    "unit_basis": "non_cached_input_plus_output",
                    "observability_level": "full",
                },
                "source_refs": {"conversation_ref": "conversation-001"},
                "source_specific": {"event_type": "usage_summary"},
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
                "source_specific": {"event_type": "usage_summary"},
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
                "source_specific": {"event_type": "tool_result"},
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
        "bucket_size_minutes": 60,
        "rollups": [],
        "trend": [],
        "totals": {
            "effective_units": 0,
            "unknown_units": 0,
            "cached_input_units": 0,
            "input_token_units": 0,
            "output_token_units": 0,
            "total_token_units": 0,
            "cache_write_input_units": 0,
            "reasoning_output_units": 0,
            "credit_total": 0,
            "cache_observed_input_units": 0,
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
    usage_bucket = next(row for row in summary["trend"] if row["effective_units"] == 175)
    assert usage_bucket["unknown_units"] == 15
    assert usage_bucket["cached_input_units"] == 90
    assert usage_bucket["input_token_units"] == 250
    assert usage_bucket["cache_hit_rate"] == 0.36
    assert summary["totals"]["cached_input_units"] == 90
    assert summary["totals"]["input_token_units"] == 250
    assert summary["totals"]["cache_hit_rate"] == 0.36


def test_total_only_usage_does_not_affect_cache_hit_denominator(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        batch = _usage_risk_batch()
        batch["items"] = [dict(batch["items"][0]), dict(batch["items"][2])]
        batch["items"][1].update(
            {
                "source_event_id": "usage-total-only",
                "raw_hash": "hash-usage-total-only",
                "projection": {"activity_tag": "workbuddy_turn", "units": 999, "total_tokens": 999, "observability_level": "total_only"},
                "usage": {
                    "scope": "session",
                    "units": 999,
                    "activity_tag": "workbuddy_turn",
                    "total_tokens": 999,
                    "observability_level": "total_only",
                    "cache_observed": False,
                },
            }
        )
        ingest_telemetry(conn, batch)
        summary = get_usage_summary(conn, window="1h")

    assert summary["totals"]["effective_units"] == 1119
    assert summary["totals"]["cache_observed_input_units"] == 200
    assert summary["totals"]["cache_hit_rate"] == 0.4


def test_usage_summary_one_hour_uses_five_minute_zero_filled_trend_buckets(tmp_path):
    first_at = (datetime.now(UTC) - timedelta(minutes=10)).replace(second=0, microsecond=0)
    second_at = first_at + timedelta(minutes=1)
    with connect(tmp_path / "observer.sqlite") as conn:
        batch = _usage_risk_batch()
        batch["items"] = [dict(batch["items"][0]), dict(batch["items"][1])]
        batch["items"][0].update({"source_event_id": "minute-usage-1", "raw_hash": "hash-minute-usage-1", "occurred_at": first_at.isoformat()})
        batch["items"][1].update({"source_event_id": "minute-usage-2", "raw_hash": "hash-minute-usage-2", "occurred_at": second_at.isoformat()})
        ingest_telemetry(conn, batch)
        summary = get_usage_summary(conn, window="1h")

    assert summary["bucket_size_minutes"] == 5
    assert len(summary["trend"]) >= 12
    assert sum(row["effective_units"] for row in summary["trend"]) == 160
    assert any(row["effective_units"] == 0 for row in summary["trend"])


def test_usage_summary_today_uses_hourly_trend_buckets(tmp_path):
    local_start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    local_now = datetime.now().astimezone()
    first_at = (local_start + timedelta(minutes=10)).astimezone(UTC).replace(microsecond=0).isoformat()
    second_at = local_now.astimezone(UTC).replace(microsecond=0).isoformat()
    with connect(tmp_path / "observer.sqlite") as conn:
        batch = _usage_risk_batch()
        batch["items"] = [dict(batch["items"][0]), dict(batch["items"][1])]
        batch["items"][0].update({"source_event_id": "today-usage-1", "raw_hash": "hash-today-usage-1", "occurred_at": first_at})
        batch["items"][1].update({"source_event_id": "today-usage-2", "raw_hash": "hash-today-usage-2", "occurred_at": second_at})
        ingest_telemetry(conn, batch)
        summary = get_usage_summary(conn, window="today")

    assert summary["bucket_size_minutes"] == 60
    assert len(summary["trend"]) >= local_now.hour + 1
    assert sum(row["effective_units"] for row in summary["trend"]) == 160
    assert summary["trend"][0]["bucket"] == local_start.astimezone(UTC).isoformat()
    assert all(row["bucket"].endswith(":00:00+00:00") for row in summary["trend"])


def test_usage_summary_custom_range_uses_adaptive_trend_buckets(tmp_path):
    end = datetime.now(UTC).replace(microsecond=0)
    start = end - timedelta(hours=6)
    inside_one = (start + timedelta(minutes=20)).isoformat()
    inside_two = (start + timedelta(hours=1, minutes=10)).isoformat()
    outside = (start - timedelta(minutes=20)).isoformat()
    with connect(tmp_path / "observer.sqlite") as conn:
        batch = _usage_risk_batch()
        batch["items"] = [dict(batch["items"][0]), dict(batch["items"][1]), dict(batch["items"][2])]
        batch["items"][0].update({"source_event_id": "custom-usage-1", "raw_hash": "hash-custom-usage-1", "occurred_at": inside_one})
        batch["items"][1].update({"source_event_id": "custom-usage-2", "raw_hash": "hash-custom-usage-2", "occurred_at": inside_two})
        batch["items"][2].update({"source_event_id": "custom-usage-outside", "raw_hash": "hash-custom-usage-outside", "occurred_at": outside})
        ingest_telemetry(conn, batch)
        summary = get_usage_summary(conn, window="custom", start_at=start.isoformat(), end_at=end.isoformat())

    assert summary["bucket_size_minutes"] == 15
    assert summary["totals"]["effective_units"] == 160
    assert len(summary["trend"]) >= 24
    assert sum(row["effective_units"] for row in summary["trend"]) == 160
    assert any(row["effective_units"] == 0 for row in summary["trend"])


@pytest.mark.parametrize(
    ("window", "expected_bucket_minutes", "outside_delta"),
    [
        ("3h", 15, timedelta(hours=4)),
        ("6h", 30, timedelta(hours=7)),
        ("12h", 60, timedelta(hours=13)),
    ],
)
def test_usage_summary_short_windows_exclude_history_and_use_subday_buckets(
    tmp_path,
    window,
    expected_bucket_minutes,
    outside_delta,
):
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    inside_at = (now - timedelta(minutes=30)).isoformat()
    outside_at = (now - outside_delta).isoformat()
    with connect(tmp_path / "observer.sqlite") as conn:
        batch = _usage_risk_batch()
        batch["items"] = [dict(batch["items"][0]), dict(batch["items"][1])]
        batch["items"][0].update({"source_event_id": f"{window}-inside", "raw_hash": f"hash-{window}-inside", "occurred_at": inside_at})
        batch["items"][1].update({"source_event_id": f"{window}-outside", "raw_hash": f"hash-{window}-outside", "occurred_at": outside_at})
        ingest_telemetry(conn, batch)
        summary = get_usage_summary(conn, window=window)

    assert summary["bucket_size_minutes"] == expected_bucket_minutes
    assert summary["totals"]["effective_units"] == 120
    assert sum(row["effective_units"] for row in summary["trend"]) == 120
    assert any(row["effective_units"] == 0 for row in summary["trend"])
    bucket_at = datetime.fromisoformat(next(row["bucket"] for row in summary["trend"] if row["effective_units"] == 120))
    inside = datetime.fromisoformat(inside_at)
    assert timedelta(0) <= inside - bucket_at < timedelta(minutes=expected_bucket_minutes)


def test_usage_summary_week_uses_local_day_trend_bucket(tmp_path):
    local_start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    event_at = (local_start + timedelta(minutes=30)).astimezone(UTC).isoformat()
    with connect(tmp_path / "observer.sqlite") as conn:
        batch = _usage_risk_batch()
        batch["items"] = [dict(batch["items"][0])]
        batch["items"][0].update({"source_event_id": "week-local-day-usage", "raw_hash": "hash-week-local-day-usage", "occurred_at": event_at})
        ingest_telemetry(conn, batch)
        summary = get_usage_summary(conn, window="week")

    assert summary["bucket_size_minutes"] == 24 * 60
    usage_bucket = next(row for row in summary["trend"] if row["effective_units"] == 120)
    assert usage_bucket == {
        "bucket": local_start.astimezone(UTC).isoformat(),
        "effective_units": 120,
        "unknown_units": 0,
        "cached_input_units": 80,
        "input_token_units": 200,
        "output_token_units": 0,
        "total_token_units": 200,
        "cache_write_input_units": 0,
        "reasoning_output_units": 0,
        "credit_total": 0.0,
        "cache_observed_input_units": 200,
        "cache_hit_rate": 0.4,
    }
    assert len(summary["trend"]) >= datetime.now().astimezone().weekday() + 1


def test_usage_summary_filters_by_agent_type(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        codex = _usage_risk_batch()
        workbuddy = _usage_risk_batch()
        workbuddy.update(
            {
                "batch_id": "batch-workbuddy-usage",
                "collector_id": "collector-workbuddy",
                "source": "workbuddy",
                "source_id": "workbuddy-local",
                "agent_type": "workbuddy",
                "source_kind": "workbuddy_local",
            }
        )
        workbuddy["items"] = [dict(codex["items"][0])]
        workbuddy["items"][0].update(
            {
                "source_event_id": "workbuddy-usage-001",
                "raw_hash": "hash-workbuddy-usage",
                "projection": {
                    "activity_tag": "workbuddy_turn",
                    "units": 300,
                    "input_tokens": 500,
                    "cached_input_tokens": 50,
                },
                "usage": {
                    "scope": "session",
                    "units": 300,
                    "activity_tag": "workbuddy_turn",
                    "session_id": "session-workbuddy",
                    "conversation_id": "conversation-workbuddy",
                    "project_ref": "project-workbuddy",
                    "account_ref": "account-local",
                    "input_tokens": 500,
                    "output_tokens": 0,
                    "total_tokens": 500,
                    "cached_input_tokens": 50,
                    "cache_observed": True,
                    "unit_basis": "non_cached_input_plus_output",
                    "observability_level": "full",
                },
            }
        )
        ingest_telemetry(conn, codex)
        ingest_telemetry(conn, workbuddy)
        codex_summary = get_usage_summary(conn, window="1h", agent_type="codex")
        workbuddy_summary = get_usage_summary(conn, window="1h", agent_type="workbuddy")

    assert codex_summary["totals"]["effective_units"] == 175
    assert sum(row["effective_units"] for row in codex_summary["trend"]) == 175
    assert workbuddy_summary["totals"]["effective_units"] == 300
    assert sum(row["effective_units"] for row in workbuddy_summary["trend"]) == 300


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
                **default_versions(),
                "collector_id": "collector-codex",
                "source": "codex",
        "source_id": "codex-local",
        "agent_type": "codex",
        "source_kind": "codex_local",
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
                        "source_specific": {"event_type": "function_call"},
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
                        "source_specific": {"event_type": "function_call"},
                    },
                ],
            },
        )
        summary = get_risk_summary(conn)

    signals = {(signal["risk_type"], signal["object_type"]): signal for signal in summary["signals"]}
    assert ("sensitive_content_exposure", "credential") not in signals
    assert ("sensitive_content_exposure", "auth") not in signals
