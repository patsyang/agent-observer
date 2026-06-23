from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.conversations.service import get_conversation_for_fact, get_conversation_query, query_conversations
from app.db.connection import connect
from app.ingest.service import ingest_telemetry


def _item(
    event_id: str,
    category: str,
    text: str,
    occurred_at: str,
    conversation: str = "conv-alpha",
    *,
    line: int | None = None,
    source_path_hash: str | None = None,
) -> dict:
    role = "user" if category == "agent_prompt" else "assistant"
    projection = {"role": role, "content_text": text}
    if category == "agent_prompt":
        projection = {"role": role, "prompt_text": text}
    return {
        "source_event_id": event_id,
        "fact_type": "content",
        "category": category,
        "quality": "high",
        "severity": "low",
        "summary": text,
        "occurred_at": occurred_at,
        "span": f"session:{conversation}",
        "raw_hash": f"hash-{event_id}",
        "projection": projection,
        "upload_raw": True,
        "raw_content": text,
        "source_refs": _source_refs(conversation, line=line, source_path_hash=source_path_hash),
        "source_specific": {"event_type": "message"},
    }


def _usage(
    event_id: str,
    units: int,
    occurred_at: str,
    conversation: str = "conv-alpha",
    *,
    line: int | None = None,
    source_path_hash: str | None = None,
    input_tokens: int = 0,
    cached_input_tokens: int = 0,
) -> dict:
    return {
        "source_event_id": event_id,
        "fact_type": "usage",
        "category": "usage",
        "quality": "high",
        "severity": "low",
        "summary": f"Usage {units}",
        "occurred_at": occurred_at,
        "span": f"usage:{conversation}",
        "raw_hash": f"hash-{event_id}",
        "projection": {
            "activity_tag": "codex_turn",
            "units": units,
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
        },
        "usage": {
            "scope": "conversation",
            "units": units,
            "activity_tag": "codex_turn",
            "session_id": f"session-{conversation}",
            "conversation_id": conversation,
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "total_tokens": input_tokens,
            "unit_basis": "non_cached_input_plus_output",
            "observability_level": "full" if input_tokens else "total_only",
            "cache_observed": bool(input_tokens),
        },
        "source_refs": _source_refs(conversation, line=line, source_path_hash=source_path_hash),
        "source_specific": {"event_type": "usage_summary"},
    }


def _event(event_id: str, category: str, occurred_at: str, conversation: str = "conv-event-only") -> dict:
    return {
        "source_event_id": event_id,
        "fact_type": "tool",
        "category": category,
        "quality": "high",
        "severity": "low",
        "summary": "Tool event without prompt or response",
        "occurred_at": occurred_at,
        "span": f"event:{conversation}",
        "raw_hash": f"hash-{event_id}",
        "projection": {"tool": "exec_command"},
        "source_refs": {"conversation_ref": conversation, "session_ref": f"session-{conversation}"},
        "source_specific": {"event_type": "function_call"},
    }


def _tool_failure(event_id: str, occurred_at: str, conversation: str = "conv-detail") -> dict:
    return {
        "source_event_id": event_id,
        "fact_type": "error",
        "category": "tool_execution_failure",
        "quality": "high",
        "severity": "medium",
        "summary": "工具执行失败：cmd /c apps\\agent-observer\\scripts\\start-backend.cmd，exit_code=1。",
        "occurred_at": occurred_at,
        "span": f"event:{conversation}",
        "raw_hash": f"hash-{event_id}",
        "projection": {
            "tool_name": "exec_command",
            "command": "cmd /c apps\\agent-observer\\scripts\\start-backend.cmd",
            "command_excerpt": "cmd /c apps\\agent-observer\\scripts\\start-backend.cmd",
            "command_category": "shell",
            "exit_code": 1,
            "error_excerpt": "Port 8765 is already in use.",
        },
        "source_refs": _source_refs(conversation),
        "source_specific": {"event_type": "function_call_output"},
        "error_signature": {"signature_key": f"tool_execution_failure:exec_command:{event_id}:1", "category": "tool_execution_failure"},
    }


def _source_refs(conversation: str, *, line: int | None = None, source_path_hash: str | None = None) -> dict:
    refs = {"conversation_ref": conversation, "session_ref": f"session-{conversation}"}
    if line is not None:
        refs["line"] = line
    if source_path_hash is not None:
        refs["source_path_hash"] = source_path_hash
    return refs


def _source_refs_with_title(conversation: str, title: str) -> dict:
    refs = _source_refs(conversation)
    refs["session_title"] = title
    return refs


def _source_refs_with_workspace(conversation: str, label: str, path: str = "D:/workspace/agentic_factory/apps/agent-observer") -> dict:
    refs = _source_refs(conversation)
    refs.update(
        {
            "workspace_id": "codex:workspace-agent-observer",
            "workspace_path": path,
            "workspace_label": label,
            "workspace_alias_source": "codex_global_state",
            "workspace_confidence": "high",
            "agent_type": "codex",
        }
    )
    return refs


def test_query_conversations_groups_prompt_response_and_usage(tmp_path):
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "batch-conversation-alpha",
                "protocol_version": "agent-observer-telemetry/v3",
                "agent_version": "0.3.0",
                "collector_id": "collector-codex",
                "source": "codex",
        "source_id": "codex-local",
        "agent_type": "codex",
        "source_kind": "codex_local",
                "cursor": "cursor-alpha",
                "items": [
                    _item("alpha-prompt", "agent_prompt", "请检查观测总览的信号列表", (now - timedelta(minutes=5)).isoformat()),
                    _item("alpha-response", "agent_response", "已经定位到信号聚合过宽的问题", (now - timedelta(minutes=4)).isoformat()),
                    _usage("alpha-usage", 320, (now - timedelta(minutes=3)).isoformat(), input_tokens=800, cached_input_tokens=480),
                ],
            },
        )
        result = query_conversations(conn, window="1h")

    assert result["total"] == 1
    row = result["conversations"][0]
    assert row["conversation_ref"] == "conv-alpha"
    assert row["prompt_preview"] == "请检查观测总览的信号列表"
    assert row["response_preview"] == "已经定位到信号聚合过宽的问题"
    assert row["token_usage"]["effective_units"] == 320
    assert row["token_usage"]["cached_input_units"] == 480
    assert row["token_usage"]["input_token_units"] == 800
    assert row["token_usage"]["cache_hit_rate"] == 0.6


def test_query_conversations_exposes_codex_session_title(tmp_path):
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        prompt = _item("title-prompt", "agent_prompt", "查看会话标题", (now - timedelta(minutes=5)).isoformat(), "conv-title")
        prompt["source_refs"] = _source_refs_with_title("conv-title", "分析信号定义与类型-Grill")
        response = _item("title-response", "agent_response", "已展示 Codex 会话名", (now - timedelta(minutes=4)).isoformat(), "conv-title")
        response["source_refs"] = _source_refs_with_title("conv-title", "分析信号定义与类型-Grill")
        ingest_telemetry(
            conn,
            {
                "batch_id": "batch-conversation-title",
                "protocol_version": "agent-observer-telemetry/v3",
                "agent_version": "0.3.0",
                "collector_id": "collector-codex",
                "source": "codex",
        "source_id": "codex-local",
        "agent_type": "codex",
        "source_kind": "codex_local",
                "cursor": "cursor-title",
                "items": [prompt, response],
            },
        )
        result = query_conversations(conn, window="1h")
        detail = get_conversation_query(conn, "conv-title")

    assert result["conversations"][0]["session_title"] == "分析信号定义与类型-Grill"
    assert detail["session_title"] == "分析信号定义与类型-Grill"


def test_query_conversations_exposes_and_filters_workspace(tmp_path):
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        prompt = _item("workspace-prompt", "agent_prompt", "查看工作区", (now - timedelta(minutes=5)).isoformat(), "conv-workspace")
        prompt["source_refs"] = _source_refs_with_workspace("conv-workspace", "Agent Observer")
        response = _item("workspace-response", "agent_response", "已展示工作区", (now - timedelta(minutes=4)).isoformat(), "conv-workspace")
        response["source_refs"] = _source_refs_with_workspace("conv-workspace", "Agent Observer")
        other_prompt = _item("other-prompt", "agent_prompt", "其他输入", (now - timedelta(minutes=5)).isoformat(), "conv-other")
        other_prompt["source_refs"] = _source_refs_with_workspace("conv-other", "Knowledge Kit", "D:/workspace/work_knowledge/knowledge_kit")
        other_response = _item("other-response", "agent_response", "其他输出", (now - timedelta(minutes=4)).isoformat(), "conv-other")
        other_response["source_refs"] = _source_refs_with_workspace("conv-other", "Knowledge Kit", "D:/workspace/work_knowledge/knowledge_kit")
        ingest_telemetry(
            conn,
            {
                "batch_id": "batch-conversation-workspace",
                "protocol_version": "agent-observer-telemetry/v3",
                "agent_version": "0.3.0",
                "collector_id": "collector-codex",
                "source": "codex",
        "source_id": "codex-local",
        "agent_type": "codex",
        "source_kind": "codex_local",
                "cursor": "cursor-workspace",
                "items": [prompt, response, other_prompt, other_response],
            },
        )
        result = query_conversations(conn, window="1h", workspace_query="agent observer")
        detail = get_conversation_query(conn, "conv-workspace")

    assert [row["conversation_ref"] for row in result["conversations"]] == ["conv-workspace"]
    assert result["conversations"][0]["workspace"]["workspace_label"] == "Agent Observer"
    assert detail["workspace"]["workspace_path"].endswith("agent-observer")


def test_query_conversations_requires_uploaded_prompt_response_text(tmp_path):
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "batch-conversation-redacted",
                "protocol_version": "agent-observer-telemetry/v3",
                "agent_version": "0.3.0",
                "collector_id": "collector-codex",
                "source": "codex",
        "source_id": "codex-local",
        "agent_type": "codex",
        "source_kind": "codex_local",
                "cursor": "cursor-redacted",
                "items": [
                    {
                        "source_event_id": "redacted-prompt",
                        "fact_type": "content",
                        "category": "agent_prompt",
                        "quality": "high",
                        "severity": "low",
                        "summary": "记录到 Codex Prompt，已上传原始内容。",
                        "occurred_at": (now - timedelta(minutes=2)).isoformat(),
                        "span": "session:conv-redacted",
                        "raw_hash": "hash-redacted-prompt",
                        "projection": {"role": "user", "prompt_text": "真实 Prompt", "content_length": 9, "raw_content_uploaded": True},
                        "upload_raw": True,
                        "raw_content": "真实 Prompt",
                        "source_refs": _source_refs("conv-redacted"),
                        "source_specific": {"event_type": "message"},
                    },
                    {
                        "source_event_id": "redacted-response",
                        "fact_type": "content",
                        "category": "agent_response",
                        "quality": "high",
                        "severity": "low",
                        "summary": "记录到 Codex 响应，已上传原始内容。",
                        "occurred_at": (now - timedelta(minutes=1)).isoformat(),
                        "span": "session:conv-redacted",
                        "raw_hash": "hash-redacted-response",
                        "projection": {"role": "assistant", "content_text": "真实响应", "content_length": 4, "raw_content_uploaded": True},
                        "upload_raw": True,
                        "raw_content": "真实响应",
                        "source_refs": _source_refs("conv-redacted"),
                        "source_specific": {"event_type": "message"},
                    },
                ],
            },
        )
        result = query_conversations(conn, window="1h")

    assert result["total"] == 1
    row = result["conversations"][0]
    assert row["prompt_preview"] == "真实 Prompt"
    assert row["response_preview"] == "真实响应"


def test_query_conversations_excludes_groups_without_complete_input_and_output(tmp_path):
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "batch-conversation-event-only",
                "protocol_version": "agent-observer-telemetry/v3",
                "agent_version": "0.3.0",
                "collector_id": "collector-codex",
                "source": "codex",
        "source_id": "codex-local",
        "agent_type": "codex",
        "source_kind": "codex_local",
                "cursor": "cursor-event-only",
                "items": [
                    _event("event-only-tool", "tool_call", (now - timedelta(minutes=3)).isoformat()),
                    _item("prompt-only", "agent_prompt", "只有输入", (now - timedelta(minutes=3)).isoformat(), "conv-prompt-only"),
                    _item("response-only", "agent_response", "只有输出", (now - timedelta(minutes=3)).isoformat(), "conv-response-only"),
                    _item("prompt", "agent_prompt", "真实输入", (now - timedelta(minutes=2)).isoformat(), "conv-real"),
                    _item("response", "agent_response", "真实输出", (now - timedelta(minutes=1)).isoformat(), "conv-real"),
                ],
            },
        )
        result = query_conversations(conn, window="1h")

    assert [row["conversation_ref"] for row in result["conversations"]] == ["conv-real"]


def test_query_conversations_filters_prompt_response_and_custom_range(tmp_path):
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "batch-conversation-filter",
                "protocol_version": "agent-observer-telemetry/v3",
                "agent_version": "0.3.0",
                "collector_id": "collector-codex",
                "source": "codex",
        "source_id": "codex-local",
        "agent_type": "codex",
        "source_kind": "codex_local",
                "cursor": "cursor-filter",
                "items": [
                    _item("alpha-prompt", "agent_prompt", "重构会话查询", (now - timedelta(minutes=10)).isoformat(), "conv-alpha"),
                    _item("alpha-response", "agent_response", "响应内容包含右侧抽屉", (now - timedelta(minutes=9)).isoformat(), "conv-alpha"),
                    _item("beta-prompt", "agent_prompt", "旧窗口外 prompt", (now - timedelta(hours=3)).isoformat(), "conv-beta"),
                    _item("beta-response", "agent_response", "旧窗口外 response", (now - timedelta(hours=3)).isoformat(), "conv-beta"),
                ],
            },
        )
        prompt_result = query_conversations(conn, window="all", prompt_query="会话")
        response_result = query_conversations(conn, window="all", response_query="抽屉")
        ranged = query_conversations(
            conn,
            window="all",
            start_at=(now - timedelta(minutes=30)).isoformat(),
            end_at=(now - timedelta(minutes=1)).isoformat(),
        )

    assert [row["conversation_ref"] for row in prompt_result["conversations"]] == ["conv-alpha"]
    assert [row["conversation_ref"] for row in response_result["conversations"]] == ["conv-alpha"]
    assert [row["conversation_ref"] for row in ranged["conversations"]] == ["conv-alpha"]


def test_query_conversations_searches_full_multiturn_content_and_browser_time_format(tmp_path):
    now = datetime.now(UTC).replace(microsecond=0)
    long_prompt = f"{'前置内容' * 80} 尾部关键字"
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "batch-conversation-full-search",
                "protocol_version": "agent-observer-telemetry/v3",
                "agent_version": "0.3.0",
                "collector_id": "collector-codex",
                "source": "codex",
        "source_id": "codex-local",
        "agent_type": "codex",
        "source_kind": "codex_local",
                "cursor": "cursor-full-search",
                "items": [
                    _item("long-prompt", "agent_prompt", long_prompt, (now - timedelta(minutes=10)).isoformat(), "conv-long"),
                    _item("first-response", "agent_response", "第一轮响应", (now - timedelta(minutes=9)).isoformat(), "conv-long"),
                    _item("second-response", "agent_response", "第二轮响应包含复核关键字", (now - timedelta(minutes=8)).isoformat(), "conv-long"),
                ],
            },
        )
        result = query_conversations(
            conn,
            window="all",
            start_at=(now - timedelta(minutes=30)).isoformat().replace("+00:00", ".000Z"),
            end_at=(now + timedelta(minutes=1)).isoformat().replace("+00:00", ".000Z"),
            prompt_query="尾部关键字",
            response_query="复核关键字",
        )

    assert [row["conversation_ref"] for row in result["conversations"]] == ["conv-long"]


def test_query_conversations_splits_codex_thread_by_prompt_lines(tmp_path):
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "batch-conversation-turn-split",
                "protocol_version": "agent-observer-telemetry/v3",
                "agent_version": "0.3.0",
                "collector_id": "collector-codex",
                "source": "codex",
        "source_id": "codex-local",
        "agent_type": "codex",
        "source_kind": "codex_local",
                "cursor": "cursor-turn-split",
                "items": [
                    _item("turn-1-prompt", "agent_prompt", "第一轮输入", (now - timedelta(minutes=10)).isoformat(), "conv-thread", line=10, source_path_hash="path-a"),
                    _item("turn-1-response", "agent_response", "第一轮输出", (now - timedelta(minutes=9)).isoformat(), "conv-thread", line=11, source_path_hash="path-a"),
                    _usage("turn-1-usage", 10, (now - timedelta(minutes=9)).isoformat(), "conv-thread", line=12, source_path_hash="path-a"),
                    _item("turn-2-prompt", "agent_prompt", "第二轮输入", (now - timedelta(minutes=5)).isoformat(), "conv-thread", line=20, source_path_hash="path-a"),
                    _item("turn-2-response", "agent_response", "第二轮输出", (now - timedelta(minutes=4)).isoformat(), "conv-thread", line=21, source_path_hash="path-a"),
                    _usage("turn-2-usage", 20, (now - timedelta(minutes=4)).isoformat(), "conv-thread", line=22, source_path_hash="path-a"),
                ],
            },
        )
        result = query_conversations(conn, window="1h")
        latest_ref = result["conversations"][0]["conversation_ref"]
        detail = get_conversation_query(conn, latest_ref)

    assert result["total"] == 2
    assert [row["prompt_preview"] for row in result["conversations"]] == ["第二轮输入", "第一轮输入"]
    assert [row["response_preview"] for row in result["conversations"]] == ["第二轮输出", "第一轮输出"]
    assert [row["token_usage"]["effective_units"] for row in result["conversations"]] == [20, 10]
    assert detail["messages"][0]["content"] == "第二轮输入"
    assert detail["messages"][1]["content"] == "第二轮输出"


def test_conversation_detail_can_be_loaded_from_story_fact(tmp_path):
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "batch-conversation-detail",
                "protocol_version": "agent-observer-telemetry/v3",
                "agent_version": "0.3.0",
                "collector_id": "collector-codex",
                "source": "codex",
        "source_id": "codex-local",
        "agent_type": "codex",
        "source_kind": "codex_local",
                "cursor": "cursor-detail",
                "items": [
                    _item("detail-prompt", "agent_prompt", "打开完整输入", (now - timedelta(minutes=5)).isoformat(), "conv-detail"),
                    _item("detail-response", "agent_response", "显示完整输出和 token", (now - timedelta(minutes=4)).isoformat(), "conv-detail"),
                    _event("detail-tool", "tool_call", (now - timedelta(minutes=3)).isoformat(), "conv-detail"),
                    _usage("detail-usage", 64, (now - timedelta(minutes=3)).isoformat(), "conv-detail"),
                ],
            },
        )
        detail = get_conversation_query(conn, "conv-detail")
        by_fact = get_conversation_for_fact(conn, "detail-response")

    assert detail["conversation_ref"] == "conv-detail"
    assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][0]["content"] == "打开完整输入"
    assert [hit["fact_id"] for hit in detail["hits"]] == ["detail-tool"]
    assert detail["token_usage"]["effective_units"] == 64
    assert by_fact["conversation_ref"] == "conv-detail"


def test_conversation_detail_hits_expose_tool_context(tmp_path):
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "batch-conversation-tool-context",
                "protocol_version": "agent-observer-telemetry/v3",
                "agent_version": "0.3.0",
                "collector_id": "collector-codex",
                "source": "codex",
        "source_id": "codex-local",
        "agent_type": "codex",
        "source_kind": "codex_local",
                "cursor": "cursor-tool-context",
                "items": [
                    _item("tool-context-prompt", "agent_prompt", "启动后端", (now - timedelta(minutes=5)).isoformat(), "conv-tool-context"),
                    _item("tool-context-response", "agent_response", "后端端口被占用", (now - timedelta(minutes=4)).isoformat(), "conv-tool-context"),
                    _tool_failure("tool-context-failure", (now - timedelta(minutes=3)).isoformat(), "conv-tool-context"),
                ],
            },
        )
        detail = get_conversation_query(conn, "conv-tool-context")

    assert detail["hits"][0]["content_preview"].startswith("命令 cmd /c apps\\agent-observer")
    assert detail["hits"][0]["tool_context"] == {
        "tool_name": "exec_command",
        "command": "cmd /c apps\\agent-observer\\scripts\\start-backend.cmd",
        "command_excerpt": "cmd /c apps\\agent-observer\\scripts\\start-backend.cmd",
        "command_category": "shell",
        "exit_code": 1,
        "is_timeout": False,
        "timeout_ms": None,
        "timeout_after_ms": None,
        "wall_time_seconds": None,
        "error_excerpt": "Port 8765 is already in use.",
        "call_id": "",
    }


def test_query_conversations_supports_dashboard_time_windows(tmp_path):
    now = datetime.now(UTC).replace(microsecond=0)
    local_start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    local_week_start = local_start - timedelta(days=datetime.now().astimezone().weekday())
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "batch-conversation-windows",
                "protocol_version": "agent-observer-telemetry/v3",
                "agent_version": "0.3.0",
                "collector_id": "collector-codex",
                "source": "codex",
        "source_id": "codex-local",
        "agent_type": "codex",
        "source_kind": "codex_local",
                "cursor": "cursor-windows",
                "items": [
                    _item("recent-prompt", "agent_prompt", "最近输入", (now - timedelta(minutes=30)).isoformat(), "conv-recent"),
                    _item("recent-response", "agent_response", "最近输出", (now - timedelta(minutes=29)).isoformat(), "conv-recent"),
                    _item("two-hour-prompt", "agent_prompt", "两小时内输入", (now - timedelta(minutes=90)).isoformat(), "conv-two-hour"),
                    _item("two-hour-response", "agent_response", "两小时内输出", (now - timedelta(minutes=89)).isoformat(), "conv-two-hour"),
                    _item("old-prompt", "agent_prompt", "两小时前输入", (now - timedelta(hours=4)).isoformat(), "conv-old"),
                    _item("old-response", "agent_response", "两小时前输出", (now - timedelta(hours=4, minutes=-1)).isoformat(), "conv-old"),
                    _item("yesterday-prompt", "agent_prompt", "昨天输入", (local_start - timedelta(hours=3)).isoformat(), "conv-yesterday"),
                    _item("yesterday-response", "agent_response", "昨天输出", (local_start - timedelta(hours=3, minutes=-1)).isoformat(), "conv-yesterday"),
                    _item("previous-week-prompt", "agent_prompt", "上周输入", (local_week_start - timedelta(days=1)).isoformat(), "conv-previous-week"),
                    _item("previous-week-response", "agent_response", "上周输出", (local_week_start - timedelta(days=1, minutes=-1)).isoformat(), "conv-previous-week"),
                ],
            },
        )
        two_hour = query_conversations(conn, window="2h")
        today = query_conversations(conn, window="today")
        week = query_conversations(conn, window="week")

    assert {item["conversation_ref"] for item in two_hour["conversations"]} == {"conv-recent", "conv-two-hour"}
    assert "conv-yesterday" not in {item["conversation_ref"] for item in today["conversations"]}
    assert "conv-yesterday" in {item["conversation_ref"] for item in week["conversations"]}
    assert "conv-previous-week" not in {item["conversation_ref"] for item in week["conversations"]}
