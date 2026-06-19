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
    assert story["evidence_refs"] == [
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


def test_sensitive_risk_story_surfaces_object_in_impact_and_evidence(tmp_path):
    items = []
    for index in range(3):
        items.append(
            {
                "source_event_id": f"sensitive-risk-{index}",
                "fact_type": "risk",
                "category": "sensitive_touch",
                "quality": "high",
                "severity": "high",
                "summary": "Codex 会话触达敏感对象类别。",
                "occurred_at": f"2026-06-18T10:0{index}:00+00:00",
                "span": f"session:sensitive:{index}",
                "raw_hash": f"hash-sensitive-{index}",
                "projection": {
                    "object_type": "credential",
                    "category_count": 2,
                    "sensitive_categories": ["token", "auth"],
                },
                "risk": {"risk_type": "sensitive_object_touch", "severity": "high", "object_type": "credential"},
                "source_refs": {"conversation_ref": f"ref:conversation-sensitive-{index}"},
                "source_specific": {"codex_event_type": "function_call"},
            }
        )
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "batch-sensitive-risk",
                "collector_id": "collector-codex",
                "source": "codex",
                "cursor": "cursor-sensitive-risk",
                "items": items,
            },
        )
        queue = list_stories(conn)
        story = next(item for item in queue["stories"] if item["story_key"] == "risk:sensitive_object_touch:credential")
        detail = get_story_detail(conn, story["story_id"])

    assert story["conclusion"] == "检测到 3 次敏感对象触达，归类为认证凭据对象；主要命中 token 3 次、auth 3 次。"
    assert story["impact_objects"][0] == "认证凭据对象"
    assert story["impact_objects"][1] == "Codex 对话 3 个"
    evidence = detail["current_snapshot"]["evidence_chain"][0]
    assert evidence["risk_object"] == "认证凭据对象"
    assert evidence["risk_object_type"] == "credential"
    assert evidence["risk_category_count"] == 2
    assert evidence["sensitive_categories"] == ["token", "auth"]
    assert evidence["content_preview"] == "敏感对象触达: 认证凭据对象，命中 token、auth"


def test_sensitive_risk_evidence_infers_legacy_reference_from_raw_content(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "batch-sensitive-legacy",
                "collector_id": "collector-codex",
                "source": "codex",
                "cursor": "cursor-sensitive-legacy",
                "items": [
                    {
                        "source_event_id": "sensitive-legacy-auth",
                        "fact_type": "risk",
                        "category": "sensitive_touch",
                        "quality": "high",
                        "severity": "high",
                        "summary": "Legacy sensitive reference",
                        "occurred_at": "2026-06-18T10:00:00+00:00",
                        "span": "session:legacy",
                        "raw_hash": "hash-sensitive-legacy",
                        "projection": {
                            "object_type": "credential",
                            "category_count": 1,
                            "sensitive_categories": ["sensitive_reference"],
                            "upload_raw": True,
                            "raw_content": '{"payload":{"arguments":"{\\"command\\":\\"uv run oh auth status\\"}"}}',
                        },
                        "risk": {"risk_type": "sensitive_object_touch", "severity": "high", "object_type": "credential"},
                        "source_refs": {"conversation_ref": "ref:sensitive-legacy"},
                        "source_specific": {"codex_event_type": "function_call"},
                    }
                ],
            },
        )
        rebuild_stories(conn)
        detail = get_story_detail(conn, "story-risk-sensitive-object-touch-auth")

    assert detail["conclusion"] == "检测到 1 次敏感对象触达，归类为认证对象；主要命中 auth 1 次。"
    assert detail["impact_objects"][0] == "认证对象"
    evidence = detail["current_snapshot"]["evidence_chain"][0]
    assert evidence["risk_object"] == "认证对象"
    assert evidence["risk_object_type"] == "auth"
    assert evidence["sensitive_categories"] == ["auth"]
    assert evidence["content_preview"] == "敏感对象触达: 认证对象，命中 auth"


def test_sensitive_risk_without_explainable_hit_is_not_promoted_to_story(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "batch-sensitive-unexplained",
                "collector_id": "collector-codex",
                "source": "codex",
                "cursor": "cursor-sensitive-unexplained",
                "items": [
                    {
                        "source_event_id": "sensitive-unexplained",
                        "fact_type": "risk",
                        "category": "sensitive_touch",
                        "quality": "high",
                        "severity": "high",
                        "summary": "Legacy sensitive reference without readable hit",
                        "occurred_at": "2026-06-18T10:00:00+00:00",
                        "span": "session:legacy",
                        "raw_hash": "hash-sensitive-unexplained",
                        "projection": {
                            "object_type": "credential",
                            "category_count": 1,
                            "sensitive_categories": ["sensitive_reference"],
                        },
                        "risk": {"risk_type": "sensitive_object_touch", "severity": "high", "object_type": "credential"},
                        "source_refs": {"conversation_ref": "ref:sensitive-unexplained"},
                        "source_specific": {"codex_event_type": "function_call"},
                    }
                ],
            },
        )
        stories = list_stories(conn, queue="all")["stories"]

    assert not any(story["story_key"].startswith("risk:sensitive_object_touch") for story in stories)


def test_legacy_hashed_error_signatures_are_grouped_into_one_story(tmp_path):
    batch = {
        "batch_id": "batch-legacy-signatures",
        "collector_id": "collector-codex",
        "source": "codex",
        "cursor": "cursor-legacy",
        "items": [],
    }
    for index, suffix in enumerate(("06a0f807", "49a470b1"), start=1):
        batch["items"].append(
            {
                "source_event_id": f"legacy-error-{index}",
                "fact_type": "error",
                "category": "codex_error",
                "quality": "high",
                "severity": "high",
                "summary": "Codex function_call_output failed",
                "occurred_at": f"2026-06-18T10:0{index}:00+00:00",
                "span": f"event:{index}",
                "raw_hash": f"hash-legacy-{index}",
                "projection": {"tool": "function_call_output", "exit_code": 1},
                "error_signature": {
                    "signature_key": f"codex_error:function_call_output:response_item:1:{suffix}",
                    "category": "codex_error",
                },
                "source_refs": {"conversation_ref": "conversation-legacy"},
                "source_specific": {"codex_event_type": "function_call_output"},
            }
        )

    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, batch)
        queue = list_stories(conn)

    error_stories = [story for story in queue["stories"] if story["story_key"].startswith("error:")]
    assert [story["story_key"] for story in error_stories] == [
        "error:codex_error:function_call_output:response_item:1:function_call_output"
    ]
    assert "2 次 Codex 工具执行失败" in error_stories[0]["conclusion"]


def test_handled_story_recurrence_moves_attention_to_needs_review(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, _story_batch())
        story = rebuild_stories(conn, reason="initial")["stories"][0]
        conn.execute(
            """
            insert into story_handling_states (
              story_id, handling_state, conclusion_code, note, updated_by, updated_at
            ) values (?, 'handled', 'known_issue', 'Tracked in backlog', 'fixed-management-account', '2026-06-18T11:00:00+00:00')
            """,
            (story["story_id"],),
        )
        conn.commit()

        ingest_telemetry(conn, _story_batch(batch_id="batch-story-002"))
        recurrent = rebuild_stories(conn, reason="recurrence")["stories"][0]
        detail = get_story_detail(conn, recurrent["story_id"])

    assert recurrent["attention_state"] == "needs_review"
    assert detail["handling_state"] == "handled"
    assert detail["conclusion_code"] == "known_issue"
    assert detail["recent_audit_summary"]["latest"] == "暂无审计记录"
