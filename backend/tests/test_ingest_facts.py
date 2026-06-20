from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db.connection import connect
from app.facts.service import get_fact_detail, query_facts
from app.ingest.service import ingest_telemetry


def _batch(batch_id: str = "batch-001") -> dict:
    return {
        "batch_id": batch_id,
        "collector_id": "collector-codex",
        "source": "codex",
        "cursor": "cursor-001",
        "items": [
            {
                "source_event_id": "event-error-001",
                "fact_type": "error",
                "category": "tool_failure",
                "quality": "high",
                "severity": "high",
                "summary": "Tool execution failed with raw signature",
                "occurred_at": "2026-06-18T10:00:00+00:00",
                "span": "session:demo",
                "raw_hash": "hash-error-001",
                "projection": {"tool": "apply_patch", "exit_code": 1},
                "evidence_projections": [
                    {
                        "projection_id": "proj-event-error-001-result",
                        "category": "tool_result",
                        "span": "session:demo:result",
                        "raw_hash": "hash-error-001-result",
                        "projection": {"tool": "apply_patch", "exit_code": 1},
                    },
                    {
                        "projection_id": "proj-event-error-001-stderr",
                        "category": "stderr",
                        "span": "session:demo:stderr",
                        "raw_hash": "hash-error-001-stderr",
                        "projection": {"normalized_error": "command_failed"},
                    },
                ],
                "error_signature": {
                    "signature_key": "tool_failure:apply_patch:1",
                    "category": "tool_failure",
                },
                "usage": {"scope": "session", "units": 42, "activity_tag": "implementation"},
                "risk": {"risk_type": "high_risk_operation", "severity": "medium"},
                "source_refs": {"conversation_ref": "conv-hash-001"},
                "source_specific": {"codex_event_type": "tool_result"},
            },
            {
                "source_event_id": "event-low-001",
                "fact_type": "unknown",
                "category": "uncategorized",
                "quality": "low",
                "severity": "low",
                "summary": "Low evidence fact remains queryable",
                "occurred_at": "2026-06-18T10:01:00+00:00",
                "span": "session:demo",
                "raw_hash": "hash-low-001",
                "projection": {"classification": "unknown"},
                "source_refs": {"conversation_ref": "conv-hash-001"},
                "source_specific": {"codex_event_type": "message_summary"},
            },
        ],
    }


def test_ingest_codex_batch_writes_observed_facts_and_projections(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        result = ingest_telemetry(conn, _batch())
        facts = query_facts(conn)
        detail = get_fact_detail(conn, "event-error-001")
        error_count = conn.execute("select count(*) from error_signatures").fetchone()[0]
        usage_count = conn.execute("select count(*) from usage_signals").fetchone()[0]
        risk_count = conn.execute("select count(*) from risk_signals").fetchone()[0]

    assert result == {"batch_id": "batch-001", "accepted": 2, "duplicates": 0}
    assert facts["total"] == 2
    assert facts["limit"] == 50
    assert facts["offset"] == 0
    assert [fact["fact_id"] for fact in facts["facts"]] == ["event-low-001", "event-error-001"]
    assert facts["facts"][1]["content_preview"] == "工具 apply_patch，退出码 1"
    assert facts["facts"][1]["raw_status"] == "仅结构化字段"
    assert facts["facts"][1]["source_event_type"] == "tool_result"
    assert facts["facts"][1]["source_label"] == "Codex 会话 conv-hash-001"
    assert detail["fact"]["quality"] == "high"
    assert detail["evidence_projection"]["raw_hash"] == "hash-error-001-result"
    assert detail["evidence_projection"]["upload_raw"] is False
    assert [item["category"] for item in detail["evidence_projections"]] == ["tool_result", "stderr"]
    assert detail["source_specific_json"]["codex_event_type"] == "tool_result"
    assert error_count == 1
    assert usage_count == 1
    assert risk_count == 1


def test_duplicate_batch_is_idempotent(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        first = ingest_telemetry(conn, _batch())
        second = ingest_telemetry(conn, _batch())
        fact_count = conn.execute("select count(*) from observed_facts").fetchone()[0]
        projection_count = conn.execute("select count(*) from evidence_projections").fetchone()[0]

    assert first["accepted"] == 2
    assert second == {"batch_id": "batch-001", "accepted": 0, "duplicates": 2}
    assert fact_count == 2
    assert projection_count == 3


def test_duplicate_raw_enabled_upload_enriches_existing_projection(tmp_path):
    raw_off = {
        "batch_id": "raw-off-batch",
        "collector_id": "collector-codex",
        "source": "codex",
        "cursor": "raw-off",
        "items": [
            {
                "source_event_id": "prompt-event-001",
                "fact_type": "content",
                "category": "codex_prompt",
                "quality": "high",
                "severity": "low",
                "summary": "记录到 Codex 用户 Prompt，原文上报未开启。",
                "occurred_at": "2026-06-18T10:00:00+00:00",
                "span": "session:prompt",
                "raw_hash": "hash-prompt-001",
                "projection": {"role": "user", "content_length": 12, "raw_content_uploaded": False},
                "source_refs": {"conversation_ref": "conv-prompt"},
                "source_specific": {"codex_event_type": "message"},
            }
        ],
    }
    raw_on = {
        **raw_off,
        "batch_id": "raw-on-batch",
        "cursor": "raw-on",
        "items": [
            {
                **raw_off["items"][0],
                "summary": "记录到 Codex 用户 Prompt，已上传原始内容。",
                "raw_hash": "hash-prompt-001-raw",
                "projection": {
                    "role": "user",
                    "content_length": 12,
                    "raw_content_uploaded": True,
                    "prompt_text": "查看原始 Prompt",
                },
                "upload_raw": True,
                "raw_content": '{"payload":{"content":[{"text":"查看原始 Prompt"}]}}',
            }
        ],
    }

    with connect(tmp_path / "observer.sqlite") as conn:
        first = ingest_telemetry(conn, raw_off)
        second = ingest_telemetry(conn, raw_on)
        detail = get_fact_detail(conn, "prompt-event-001")
        fact_count = conn.execute("select count(*) from observed_facts").fetchone()[0]
        projection_count = conn.execute("select count(*) from evidence_projections").fetchone()[0]

    assert first["accepted"] == 1
    assert second == {"batch_id": "raw-on-batch", "accepted": 0, "duplicates": 1}
    assert fact_count == 1
    assert projection_count == 1
    assert detail["fact"]["summary"] == "记录到 Codex 用户 Prompt，已上传原始内容。"
    assert detail["evidence_projection"]["upload_raw"] is True
    assert detail["evidence_projection"]["raw_content"] == '{"payload":{"content":[{"text":"查看原始 Prompt"}]}}'
    assert detail["evidence_projection"]["projection_json"]["prompt_text"] == "查看原始 Prompt"
    assert detail["fact"]["content_preview"] == "Prompt: 查看原始 Prompt"
    assert detail["fact"]["raw_status"] == "已上传原文"


def test_source_event_id_is_idempotent_per_collector(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        first = ingest_telemetry(conn, _batch())
        other = _batch("batch-002")
        other["collector_id"] = "collector-other"
        other["cursor"] = "cursor-002"
        second = ingest_telemetry(conn, other)
        repeat = ingest_telemetry(conn, other)
        rows = conn.execute(
            "select collector_id, source_event_id, fact_id from observed_facts order by collector_id, source_event_id"
        ).fetchall()
        projection_count = conn.execute("select count(*) from evidence_projections").fetchone()[0]

    assert first["accepted"] == 2
    assert second["accepted"] == 2
    assert repeat["duplicates"] == 2
    assert len(rows) == 4
    assert {row["collector_id"] for row in rows} == {"collector-codex", "collector-other"}
    assert all(row["source_event_id"] in {"event-error-001", "event-low-001"} for row in rows)
    assert projection_count == 6


def test_low_evidence_fact_stays_queryable_when_error_story_is_built(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, _batch())
        result = query_facts(conn, quality="low")
        story_count = conn.execute("select count(*) from observation_stories").fetchone()[0]

    assert len(result["facts"]) == 1
    assert result["facts"][0]["fact_id"] == "event-low-001"
    assert result["facts"][0]["quality"] == "low"
    assert result["facts"][0]["promoted_to_story"] is False
    assert story_count >= 1
