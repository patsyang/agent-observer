from __future__ import annotations

from app.db.connection import connect
from app.ingest.service import ingest_telemetry
from app.stories.service import get_story_detail, list_stories, rebuild_stories


def _story_batch(batch_id: str = "batch-story-001") -> dict:
    return {
        "batch_id": batch_id,
        "collector_id": "collector-codex",
        "source": "codex",
        "cursor": f"cursor-{batch_id}",
        "items": [
            {
                "source_event_id": f"{batch_id}-error",
                "fact_type": "error",
                "category": "codex_error",
                "quality": "high",
                "severity": "high",
                "summary": "Codex command failed repeatedly in checkout workflow",
                "occurred_at": "2026-06-18T10:00:00+00:00",
                "span": "command:checkout",
                "raw_hash": f"hash-{batch_id}-error",
                "projection": {"impact": "checkout workflow", "count": 2},
                "error_signature": {"signature_key": "sig-checkout-failure", "category": "codex_error"},
                "source_refs": {"conversation_ref": "conversation-story"},
                "source_specific": {"codex_event_type": "tool_result"},
            },
            {
                "source_event_id": f"{batch_id}-usage",
                "fact_type": "usage",
                "category": "usage",
                "quality": "high",
                "severity": "low",
                "summary": "Attributed bug-fix usage for checkout recovery",
                "occurred_at": "2026-06-18T10:05:00+00:00",
                "span": "conversation:story",
                "raw_hash": f"hash-{batch_id}-usage",
                "projection": {"activity_tag": "bug_fix", "units": 55},
                "upload_raw": True,
                "raw_content": '{"type":"token_count","payload":{"total_tokens":55}}',
                "usage": {
                    "units": 55,
                    "usage_kind": "attributed",
                    "activity_tag": "bug_fix",
                    "session_id": "session-story",
                    "conversation_id": "conversation-story",
                },
                "source_refs": {"conversation_ref": "conversation-story"},
                "source_specific": {"codex_event_type": "usage_summary"},
            },
            {
                "source_event_id": f"{batch_id}-risk",
                "fact_type": "risk",
                "category": "high_risk_operation",
                "quality": "high",
                "severity": "medium",
                "summary": "High-risk operation touched workspace configuration",
                "occurred_at": "2026-06-18T10:10:00+00:00",
                "span": "session:story",
                "raw_hash": f"hash-{batch_id}-risk",
                "projection": {"object_type": "configuration", "count": 1},
                "risk": {"risk_type": "high_risk_operation", "severity": "medium", "object_type": "configuration"},
                "source_refs": {"conversation_ref": "conversation-story"},
                "source_specific": {"codex_event_type": "tool_result"},
            },
        ],
    }


def test_rebuild_stories_generates_required_snapshot_fields(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, _story_batch())
        result = rebuild_stories(conn, reason="test-fixture")
        queue = list_stories(conn)
        actionable_queue = list_stories(conn, queue="actionable")
        detail = get_story_detail(conn, "story-error-sig-checkout-failure")

    story = next(item for item in queue["stories"] if item["story_key"] == "error:sig-checkout-failure")
    assert result["updated"] >= 3
    assert story["story_key"] == "error:sig-checkout-failure"
    assert story["priority_score"] > 0
    assert story["attention_state"] == "active"
    assert story["handling_state"] == "unread"
    assert story["snapshot_hash"]
    assert story["conclusion"]
    assert story["impact_objects"] == ["checkout workflow"]
    assert story["evidence_refs"] == []
    assert detail["evidence_refs"] == [
        "proj-batch-story-001-error",
        "proj-batch-story-001-risk",
        "proj-batch-story-001-usage",
    ]
    assert story["usage_summary"]["attributed_units"] == 55
    assert story["diagnostic_status_summary"]["status"] == "none"
    assert story["suggested_action"] == "查看证据链并选择处理结论"
    assert any(item["story_key"].startswith("usage:") for item in queue["stories"])
    assert any(item["story_key"].startswith("risk:") for item in queue["stories"])
    assert not any(item["story_key"].startswith("usage:") for item in actionable_queue["stories"])
    assert any(item["story_key"].startswith("error:") for item in actionable_queue["stories"])
    evidence = detail["current_snapshot"]["evidence_chain"]
    error_evidence = next(item for item in evidence if item["fact_id"] == "batch-story-001-error")
    usage_evidence = next(item for item in evidence if item["fact_id"] == "batch-story-001-usage")
    risk_evidence = next(item for item in evidence if item["fact_id"] == "batch-story-001-risk")
    assert error_evidence["content_preview"] == "Codex command failed repeatedly in checkout workflow"
    assert usage_evidence["content_preview"] == "用量 55 token，活动 缺陷修复"
    assert risk_evidence["content_preview"] == "高风险操作: 配置对象"
    assert "risk_object" not in usage_evidence
    assert "sensitive_categories" not in usage_evidence
    assert error_evidence["raw_status"] == "仅结构化字段"
    assert error_evidence["source_label"] == "Codex 会话 conversation-story"


def test_usage_story_uses_operator_readable_conclusion_and_compacts_refs(tmp_path):
    items = []
    for index in range(6):
        items.append(
            {
                "source_event_id": f"usage-ref-{index}",
                "fact_type": "usage",
                "category": "usage",
                "quality": "high",
                "severity": "low",
                "summary": "Codex usage event",
                "occurred_at": "2026-06-18T10:05:00+00:00",
                "span": f"conversation:{index}",
                "raw_hash": f"hash-usage-{index}",
                "projection": {"activity_tag": "codex_turn", "units": 100},
                "usage": {
                    "units": 100,
                    "usage_kind": "associated",
                    "activity_tag": "codex_turn",
                    "session_id": "ref:session-opaque",
                    "conversation_id": f"conversation-{index}",
                },
                "source_refs": {"conversation_ref": f"ref:conversation-{index}"},
                "source_specific": {"codex_event_type": "usage_summary"},
            }
        )
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "batch-usage-readable",
                "collector_id": "collector-codex",
                "source": "codex",
                "cursor": "cursor-readable",
                "items": items,
            },
        )
        queue = list_stories(conn)

    story = next(item for item in queue["stories"] if item["story_key"].startswith("usage:"))
    assert "ref:session-opaque" not in story["conclusion"]
    assert "历史窗口内发现 6 个 Codex 用量事件" in story["conclusion"]
    assert "活动类型为 Codex 对话" in story["conclusion"]
    assert story["impact_objects"][0] == "Codex 对话 6 个"
    assert len(story["impact_objects"]) == 1
