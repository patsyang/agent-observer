from __future__ import annotations

from app.db.connection import connect
from app.collectors.service import heartbeat, register_collector
from app.evidence_enrichment.service import record_enrichment_result, request_enrichment
from app.ingest.service import ingest_telemetry
from app.policy import update_effective_policy
from app.behavior_signals.service import handle_signal
from app.behavior_signals.service import rebuild_signals
from app.validation.service import (
    ACCEPTANCE_IDS,
    FLOW_IDS,
    run_minimum_validation_experiment,
)

CLIENT_PROTOCOL = {
    "protocol_version": "agent-observer-telemetry/v2",
    "agent_version": "0.2.0",
}


def _validation_batch(
    *,
    validation_sample: str = "synthetic_minimized_codex_session_fixture",
    occurred_at: list[str] | None = None,
) -> dict:
    categories = [
        ("validation-error-recurring", "error", "codex_error", "high", "high", "Recurring checkout command failure"),
        ("validation-low-evidence", "unknown", "uncategorized", "low", "low", "Low evidence retry candidate"),
        ("validation-enrichment", "enrichment", "enrichment_result", "high", "medium", "Enrichment result feedback needed"),
        ("validation-usage", "usage", "usage", "high", "low", "High usage session with deterministic label"),
        ("validation-risk", "risk", "high_risk_operation", "high", "medium", "High-risk workspace command"),
        ("validation-sensitive", "risk", "sensitive_touch", "high", "high", "Sensitive configuration touched"),
    ]
    items = []
    dates = occurred_at or ["2026-06-18T10:00:00+00:00"] * len(categories)
    for index, (event_id, fact_type, category, quality, severity, summary) in enumerate(categories):
        item = {
            "source_event_id": event_id,
            "fact_type": fact_type,
            "category": category,
            "quality": quality,
            "severity": severity,
            "summary": summary,
            "occurred_at": dates[index],
            "span": f"span:{event_id}",
            "raw_hash": f"hash-{event_id}",
            "projection": {"category": category},
            "source_refs": {"conversation_ref": f"conversation-{event_id}"},
            "source_specific": {"validation_sample": validation_sample},
        }
        if category == "codex_error":
            item["error_signature"] = {"signature_key": event_id, "category": "codex_error"}
        if fact_type == "usage":
            item["usage"] = {
                "units": 90,
                "activity_tag": "implementation",
                "session_id": "session-validation",
                "conversation_id": "conversation-validation",
            }
        if fact_type == "risk":
            item["risk"] = {
                "risk_type": "sensitive_object_touch" if category == "sensitive_touch" else "high_risk_operation",
                "severity": severity,
                "object_type": "configuration",
            }
        items.append(item)
    return {
        "batch_id": "batch-validation-001",
        "protocol_version": "agent-observer-telemetry/v2",
        "agent_version": "0.2.0",
        "collector_id": "collector-codex",
        "source": "codex",
        "cursor": "cursor-validation-001",
        "items": items,
    }


def test_minimum_validation_stops_synthetic_sample_before_release_pass(tmp_path):
    output_path = tmp_path / "validation-summary.json"
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, _validation_batch())
        rebuild_signals(conn, reason="minimum-validation")
        report = run_minimum_validation_experiment(conn, output_path)

    assert report["result"] == "STOP"
    assert report["stop_marker"] is True
    assert report["sample_source"] == "unqualified_synthetic_or_short_local_sample"
    assert report["sample_profile"]["qualified_for_release_evaluation"] is False
    assert {item["rule_id"] for item in report["rule_fix_list"]} == {
        "validation-sample-representativeness",
        "flow-acceptance-coverage",
    }
    assert {row["category"] for row in report["sample_coverage"]} == {
        "error_recurrence",
        "low_evidence_fact",
        "enrichment_feedback",
        "usage_signal",
        "high_risk_operation",
        "sensitive_object_touch",
    }
    assert all(row["covered"] for row in report["sample_coverage"])
    assert report["flow_coverage"].keys() == set(FLOW_IDS)
    assert report["acceptance_coverage"].keys() == set(ACCEPTANCE_IDS)
    assert report["data_handling_review"]["raw_upload_mode"] == "always_on"
    assert output_path.exists()


def test_minimum_validation_emits_pass_report_for_documented_7_day_local_sample(tmp_path):
    output_path = tmp_path / "validation-summary.json"
    dates = [
        "2026-06-12T10:00:00+00:00",
        "2026-06-13T10:00:00+00:00",
        "2026-06-14T10:00:00+00:00",
        "2026-06-15T10:00:00+00:00",
        "2026-06-16T10:00:00+00:00",
        "2026-06-18T10:00:00+00:00",
    ]
    with connect(tmp_path / "observer.sqlite") as conn:
        register_collector(
            conn,
            {
                "collector_id": "collector-codex",
                "display_name": "Codex collector",
                "hostname": "validation-host",
                "windows_username": "validation-user",
                **CLIENT_PROTOCOL,
            },
        )
        heartbeat(conn, "collector-codex", {**CLIENT_PROTOCOL, "source_status": "online", "reason_code": "start_running"})
        ingest_telemetry(
            conn,
            _validation_batch(validation_sample="documented_7_day_local_sample", occurred_at=dates),
        )
        rebuild_signals(conn, reason="minimum-validation")
        signal_id = conn.execute("select signal_id from behavior_signals order by rowid limit 1").fetchone()["signal_id"]
        handle_signal(conn, signal_id, "known_issue", "已确认需要跟进")
        job = request_enrichment(conn, signal_id, "codex_tool_failure_context")
        record_enrichment_result(conn, job["job_id"], "succeeded", "补证结果已回流")
        update_effective_policy(
            conn,
            {
                "expected_version": 1,
                "enrichment_mode": "enabled",
            },
        )
        report = run_minimum_validation_experiment(conn, output_path)

    assert report["result"] == "PASS"
    assert report["stop_marker"] is False
    assert report["sample_source"] == "documented_7_day_local_data_sample"
    assert report["sample_profile"]["qualified_for_release_evaluation"] is True
    assert report["error_signal_evidence_group_pass_rate"] >= 0.8
    assert report["usage_explanation_pass_rate"] >= 0.8
    assert {row["category"] for row in report["sample_coverage"]} == {
        "error_recurrence",
        "low_evidence_fact",
        "enrichment_feedback",
        "usage_signal",
        "high_risk_operation",
        "sensitive_object_touch",
    }
    assert all(row["covered"] for row in report["sample_coverage"])
    assert report["flow_coverage"].keys() == set(FLOW_IDS)
    assert report["acceptance_coverage"].keys() == set(ACCEPTANCE_IDS)
    assert all(item["covered"] for item in report["flow_coverage"].values())
    assert all(item["covered"] for item in report["acceptance_coverage"].values())
    assert report["data_handling_review"]["raw_upload_mode"] == "always_on"
    assert output_path.exists()


def test_minimum_validation_qualifies_real_local_codex_template_without_fixture_marker(tmp_path):
    output_path = tmp_path / "validation-summary.json"
    dates = [
        "2026-06-12T10:00:00+00:00",
        "2026-06-13T10:00:00+00:00",
        "2026-06-14T10:00:00+00:00",
        "2026-06-15T10:00:00+00:00",
        "2026-06-16T10:00:00+00:00",
        "2026-06-18T10:00:00+00:00",
    ]
    batch = _validation_batch(validation_sample="", occurred_at=dates)
    for item in batch["items"]:
        item["source_specific"] = {"source_template": "codex.local.sessions.v1"}
    for index in range(100):
        batch["items"].append(
            {
                "source_event_id": f"validation-real-local-extra-{index}",
                "fact_type": "unknown",
                "category": "uncategorized",
                "quality": "low",
                "severity": "low",
                "summary": "Additional local Codex event",
                "occurred_at": dates[index % len(dates)],
                "span": f"span:validation-real-local-extra-{index}",
                "raw_hash": f"hash-validation-real-local-extra-{index}",
                "projection": {"category": "uncategorized"},
                "source_refs": {"conversation_ref": f"conversation-extra-{index}"},
                "source_specific": {"source_template": "codex.local.sessions.v1"},
            }
        )

    with connect(tmp_path / "observer.sqlite") as conn:
        register_collector(
            conn,
            {
                "collector_id": "collector-codex",
                "display_name": "Codex collector",
                "hostname": "validation-host",
                "windows_username": "validation-user",
                **CLIENT_PROTOCOL,
            },
        )
        heartbeat(conn, "collector-codex", {**CLIENT_PROTOCOL, "source_status": "online", "reason_code": "start_running"})
        ingest_telemetry(conn, batch)
        rebuild_signals(conn, reason="minimum-validation")
        signal_id = conn.execute("select signal_id from behavior_signals order by rowid limit 1").fetchone()["signal_id"]
        handle_signal(conn, signal_id, "known_issue", "已确认需要跟进")
        job = request_enrichment(conn, signal_id, "codex_tool_failure_context")
        record_enrichment_result(conn, job["job_id"], "succeeded", "补证结果已回流")
        update_effective_policy(
            conn,
            {
                "expected_version": 1,
                "enrichment_mode": "enabled",
            },
        )
        report = run_minimum_validation_experiment(conn, output_path)

    assert report["result"] == "PASS"
    assert report["sample_source"] == "documented_7_day_local_data_sample"
    assert report["sample_profile"]["qualified_for_release_evaluation"] is True


def test_minimum_validation_stop_marker_lists_rule_fixes_when_thresholds_fail(tmp_path):
    output_path = tmp_path / "validation-summary.json"
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, _validation_batch())
        report = run_minimum_validation_experiment(conn, output_path, thresholds={"error": 1.01, "usage": 1.01})

    assert report["result"] == "STOP"
    assert report["stop_marker"] is True
    assert {item["rule_id"] for item in report["rule_fix_list"]} == {
        "validation-sample-representativeness",
        "flow-acceptance-coverage",
        "signal-evidence-groups",
        "usage-activity-label",
    }
