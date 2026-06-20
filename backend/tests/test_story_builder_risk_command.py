from __future__ import annotations

from app.db.connection import connect
from app.ingest.service import ingest_telemetry
from app.stories.service import get_story_detail, list_stories, rebuild_stories
from backend.tests.test_story_builder import _story_batch


SENSITIVE_MATCH = {
    "category": "token",
    "match_type": "authorization_bearer",
    "confidence": "high",
    "evidence_key": "command",
    "matched_preview": "Authorization: Bearer abcdefghijklmnop",
    "reason_code": "bearer_value",
}


def _sensitive_item(event_id: str, projection: dict, occurred_at: str = "2026-06-18T10:00:00+00:00") -> dict:
    return {
        "source_event_id": event_id,
        "fact_type": "risk",
        "category": "sensitive_touch",
        "quality": "high",
        "severity": "high",
        "summary": "Codex 会话触达敏感对象类别。",
        "occurred_at": occurred_at,
        "span": f"session:{event_id}",
        "raw_hash": f"hash-{event_id}",
        "projection": projection,
        "risk": {"risk_type": "sensitive_object_touch", "severity": "high", "object_type": "credential"},
        "source_refs": {"conversation_ref": f"ref:{event_id}"},
        "source_specific": {"codex_event_type": "function_call"},
    }


def test_sensitive_risk_story_surfaces_object_in_impact_and_evidence(tmp_path):
    items = [
        _sensitive_item(
            f"sensitive-risk-{index}",
            {
                "object_type": "credential",
                "category_count": 1,
                "sensitive_categories": ["token"],
                "sensitive_matches": [SENSITIVE_MATCH],
                "sensitivity_confidence": "high",
            },
            f"2026-06-18T10:0{index}:00+00:00",
        )
        for index in range(3)
    ]
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

    assert story["conclusion"] == "检测到 3 次敏感对象触达，归类为认证凭据对象；主要命中 token 3 次。"
    assert story["impact_objects"][0] == "认证凭据对象"
    assert story["impact_objects"][1] == "Codex 对话 3 个"
    evidence = detail["current_snapshot"]["evidence_chain"][0]
    assert evidence["risk_object"] == "认证凭据对象"
    assert evidence["risk_object_type"] == "credential"
    assert evidence["risk_category_count"] == 1
    assert evidence["sensitive_categories"] == ["token"]
    assert evidence["content_preview"] == "敏感对象触达: 认证凭据对象，命中 token"


def test_sensitive_risk_ignores_auth_status_without_secret_value(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "batch-sensitive-legacy",
                "collector_id": "collector-codex",
                "source": "codex",
                "cursor": "cursor-sensitive-legacy",
                "items": [
                    _sensitive_item(
                        "sensitive-legacy-auth",
                        {
                            "object_type": "credential",
                            "category_count": 1,
                            "sensitive_categories": ["sensitive_reference"],
                            "upload_raw": True,
                            "raw_content": '{"payload":{"arguments":"{\\"command\\":\\"uv run oh auth status\\"}"}}',
                        },
                    )
                ],
            },
        )
        rebuild_stories(conn)
        stories = list_stories(conn, queue="all")["stories"]

    assert not any(story["story_key"].startswith("risk:sensitive_object_touch") for story in stories)


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
                    _sensitive_item(
                        "sensitive-unexplained",
                        {"object_type": "credential", "category_count": 1, "sensitive_categories": ["sensitive_reference"]},
                    )
                ],
            },
        )
        stories = list_stories(conn, queue="all")["stories"]

    assert not any(story["story_key"].startswith("risk:sensitive_object_touch") for story in stories)


def test_command_timeout_story_uses_workflow_run_id_not_conversation_group(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "batch-command-timeout",
                "collector_id": "collector-codex",
                "source": "codex",
                "cursor": "cursor-command-timeout",
                "items": [
                    {
                        "source_event_id": "timeout-run-7631",
                        "fact_type": "error",
                        "category": "command_timeout",
                        "quality": "high",
                        "severity": "high",
                        "summary": "spec-driven resume 在 run_76317963ed8f 上运行约 3,604 秒后超时退出。",
                        "occurred_at": "2026-06-19T00:51:14.903Z",
                        "span": "codex-session:timeout",
                        "raw_hash": "hash-command-timeout",
                        "projection": {
                            "tool_name": "shell_command",
                            "command": "python scripts/ao.py spec-driven resume --run-id run_76317963ed8f",
                            "workdir": "D:/workspace/agentic_factory",
                            "timeout_ms": 3600000,
                            "exit_code": 124,
                            "wall_time_seconds": 3604.0,
                            "timeout_after_ms": 3604035,
                            "workflow": "spec-driven",
                            "run_id": "run_76317963ed8f",
                        },
                        "error_signature": {"signature_key": "command_timeout:spec-driven:run_76317963ed8f:124", "category": "command_timeout"},
                        "source_refs": {"conversation_ref": "ref:timeout-conversation"},
                        "source_specific": {"codex_event_type": "response_item:function_call_output"},
                    }
                ],
            },
        )
        story = get_story_detail(conn, "story-command-timeout-spec-driven-run-76317963ed8f")

    assert story["story_key"] == "command_timeout:spec-driven:run_76317963ed8f"
    assert story["conclusion"] == "spec-driven resume 在 run_76317963ed8f 上运行约 3,604 秒后超时退出。"
    assert story["impact_objects"] == ["run_76317963ed8f"]
    assert story["suggested_action"] == "打开该 run 的 run.json 和 workflow-event.jsonl，定位超时卡点。"


def test_ingest_updates_command_timeout_story_without_full_rebuild(tmp_path, monkeypatch):
    import app.stories.service as story_service

    monkeypatch.setattr(story_service, "rebuild_stories", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("full rebuild called")))
    traced_sql: list[str] = []
    with connect(tmp_path / "observer.sqlite") as conn:
        conn.set_trace_callback(traced_sql.append)
        ingest_telemetry(
            conn,
            {
                "batch_id": "batch-command-timeout-incremental",
                "collector_id": "collector-codex",
                "source": "codex",
                "cursor": "cursor-command-timeout-incremental",
                "items": [
                    {
                        "source_event_id": "timeout-incremental",
                        "fact_type": "error",
                        "category": "command_timeout",
                        "quality": "high",
                        "severity": "high",
                        "summary": "plan-execute resume 在 run_incremental 上运行约 60 秒后超时退出。",
                        "occurred_at": "2026-06-19T00:51:14.903Z",
                        "span": "codex-session:timeout",
                        "raw_hash": "hash-command-timeout-incremental",
                        "projection": {
                            "exit_code": 124,
                            "wall_time_seconds": 60.0,
                            "workflow": "plan-execute",
                            "run_id": "run_incremental",
                        },
                        "error_signature": {"signature_key": "command_timeout:plan-execute:run_incremental:124", "category": "command_timeout"},
                        "source_refs": {"conversation_ref": "ref:timeout-incremental"},
                        "source_specific": {"codex_event_type": "response_item:function_call_output"},
                    }
                ],
            },
        )
        story = get_story_detail(conn, "story-command-timeout-plan-execute-run-incremental")

    assert story["story_key"] == "command_timeout:plan-execute:run_incremental"
    normalized_sql = " ".join(statement.lower() for statement in traced_sql)
    assert "from observed_facts where category in ('command_timeout', 'codex_error')" not in normalized_sql
    assert "from error_signatures where category != 'command_timeout' order by signature_key" not in normalized_sql


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
