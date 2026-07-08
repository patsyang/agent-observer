from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.conversations.service import (
    get_conversation_for_fact,
    get_conversation_query,
    locate_conversation_message,
    query_conversation_hits,
    query_conversation_hits_by_fact_ids,
    query_conversation_messages,
    query_conversations,
)
from app.db.connection import connect
from app.ingest.service import ingest_telemetry
from source_payloads import default_versions


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
                **default_versions(),
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


def test_query_conversations_uses_recent_activity_to_show_full_context(tmp_path):
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "batch-conversation-recent-activity",
                **default_versions(),
                "collector_id": "collector-codex",
                "source": "codex",
                "source_id": "codex-local",
                "agent_type": "codex",
                "source_kind": "codex_local",
                "cursor": "cursor-recent-activity",
                "items": [
                    _item("activity-prompt", "agent_prompt", "两小时前的输入", (now - timedelta(hours=2)).isoformat(), "conv-activity"),
                    _item("activity-response", "agent_response", "两小时前的输出", (now - timedelta(hours=2, minutes=-1)).isoformat(), "conv-activity"),
                    _usage("activity-usage", 64, (now - timedelta(minutes=10)).isoformat(), "conv-activity", input_tokens=100, cached_input_tokens=40),
                ],
            },
        )
        result = query_conversations(conn, window="1h")

    assert result["total"] == 1
    row = result["conversations"][0]
    assert row["conversation_ref"] == "conv-activity"
    assert row["prompt_preview"] == "两小时前的输入"
    assert row["response_preview"] == "两小时前的输出"
    assert row["token_usage"]["effective_units"] == 64


def test_query_conversations_includes_usage_only_activity(tmp_path):
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "batch-conversation-usage-only",
                **default_versions(),
                "collector_id": "collector-workbuddy",
                "source": "workbuddy",
                "source_id": "workbuddy-local",
                "agent_type": "workbuddy",
                "source_kind": "workbuddy_local",
                "cursor": "cursor-usage-only",
                "items": [
                    _usage("usage-only", 128, (now - timedelta(minutes=5)).isoformat(), "conv-usage-only", input_tokens=256, cached_input_tokens=128),
                ],
            },
        )
        result = query_conversations(conn, window="1h")

    assert result["total"] == 1
    row = result["conversations"][0]
    assert row["conversation_ref"] == "conv-usage-only"
    assert row["prompt_preview"] == ""
    assert row["response_preview"] == ""
    assert row["token_usage"]["effective_units"] == 128


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
                **default_versions(),
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
                **default_versions(),
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
                **default_versions(),
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
                **default_versions(),
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
                **default_versions(),
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
                **default_versions(),
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


def test_query_conversations_aggregates_multi_turn_thread_as_single_session(tmp_path):
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "batch-conversation-turn-split",
                **default_versions(),
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
        ref = result["conversations"][0]["conversation_ref"]
        detail = get_conversation_query(conn, ref)

    # 多轮 turn 归并为单个会话（conversation_ref = base_ref）
    assert result["total"] == 1
    assert ref == "conv-thread"
    row = result["conversations"][0]
    # 首条 prompt/response 按 occurred_at 取最早
    assert row["prompt_preview"] == "第一轮输入"
    assert row["response_preview"] == "第一轮输出"
    # token 聚合：两轮 usage 总和
    assert row["token_usage"]["effective_units"] == 30
    # 详情概要返回总数（内容按需加载）
    assert detail["messages_total"] == 4
    # 倒序分页：最新两条在第一页
    page1 = query_conversation_messages(conn, ref, page=1, page_size=2)
    assert [m["content"] for m in page1["messages"]] == ["第二轮输出", "第二轮输入"]
    assert page1["has_more"] is True
    page2 = query_conversation_messages(conn, ref, page=2, page_size=2)
    assert [m["content"] for m in page2["messages"]] == ["第一轮输出", "第一轮输入"]
    assert page2["has_more"] is False


def test_conversation_detail_can_be_loaded_from_story_fact(tmp_path):
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "batch-conversation-detail",
                **default_versions(),
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
        msgs = query_conversation_messages(conn, "conv-detail")
        hits = query_conversation_hits(conn, "conv-detail")

    assert detail["conversation_ref"] == "conv-detail"
    assert detail["messages_total"] == 2
    assert detail["hits_total"] == 1
    # 倒序：assistant（最新）在前
    assert [message["role"] for message in msgs["messages"]] == ["assistant", "user"]
    assert msgs["messages"][1]["content"] == "打开完整输入"
    assert [hit["fact_id"] for hit in hits["hits"]] == ["detail-tool"]
    assert detail["token_usage"]["effective_units"] == 64
    assert by_fact["conversation_ref"] == "conv-detail"
    assert by_fact["focus_fact_id"] == "detail-response"


def test_conversation_detail_hits_expose_tool_context(tmp_path):
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "batch-conversation-tool-context",
                **default_versions(),
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
        hits = query_conversation_hits(conn, "conv-tool-context")

    assert detail["hits_total"] == 1
    assert hits["hits"][0]["content_preview"].startswith("命令 cmd /c apps\\agent-observer")
    assert hits["hits"][0]["tool_context"] == {
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
                **default_versions(),
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


def test_conversation_detail_exposes_sensitive_matches_for_pii(tmp_path):
    """detector 在 ingest 时自动给含 PII 的 content fact 写 risk_signal，使其出现在 hits 中并暴露完整敏感值作为证据。"""
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(
            conn,
            {
                "batch_id": "batch-sensitive-conv",
                **default_versions(),
                "collector_id": "collector-codex",
                "source": "codex",
                "source_id": "codex-local",
                "agent_type": "codex",
                "source_kind": "codex_local",
                "cursor": "cursor-sensitive",
                "items": [
                    _item("sensitive-prompt", "agent_prompt", "知道13521661669这个手机号吗？", (now - timedelta(minutes=2)).isoformat(), "conv-sensitive"),
                    _item("sensitive-response", "agent_response", "13521661669是一个手机号。", (now - timedelta(minutes=1)).isoformat(), "conv-sensitive"),
                ],
            },
        )
        prompt_row = conn.execute(
            "select fact_id from observed_facts where source_event_id='sensitive-prompt' limit 1"
        ).fetchone()
        response_row = conn.execute(
            "select fact_id from observed_facts where source_event_id='sensitive-response' limit 1"
        ).fetchone()
        # detector 在 ingest 时自动给两条含手机号的 content fact 都写 risk_signal，
        # 二者都应出现在 hits 中并暴露完整手机号（无需手动插 signal）。
        detail = get_conversation_query(conn, "conv-sensitive")
        msgs = query_conversation_messages(conn, "conv-sensitive")
        hits = query_conversation_hits(conn, "conv-sensitive")

    msg_with_matches = [m for m in msgs["messages"] if m.get("sensitive_matches")]
    assert len(msg_with_matches) >= 1
    phone_values = [
        m["matched_value"]
        for msg in msg_with_matches
        for m in msg["sensitive_matches"]
        if m["category"] == "phone"
    ]
    assert "13521661669" in phone_values

    hit_fact_ids = {h["fact_id"] for h in hits["hits"]}
    assert prompt_row["fact_id"] in hit_fact_ids
    assert response_row["fact_id"] in hit_fact_ids

    sensitive_hits = [h for h in hits["hits"] if h.get("sensitive_matches")]
    assert len(sensitive_hits) >= 1
    hit_phones = [
        m["matched_value"]
        for h in sensitive_hits
        for m in h["sensitive_matches"]
        if m["category"] == "phone"
    ]
    assert "13521661669" in hit_phones
    # [F8] hit_count 必须计入有 risk_signal 的 content fact，不能只按 fact_type 统计
    assert detail["hit_count"] >= len(sensitive_hits)


# ---------------------------------------------------------------------------
# 分页 / 筛选 / 定位 / 批量查询
# ---------------------------------------------------------------------------


def test_query_conversation_messages_paginated_desc(tmp_path):
    """消息倒序分页：最新在前，page_size 控制每页条数，has_more 正确。"""
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        items = [
            _item(f"msg-{i}", "agent_prompt", f"消息{i}", (now - timedelta(minutes=10 - i)).isoformat(), "conv-page")
            for i in range(1, 6)
        ]
        ingest_telemetry(conn, {
            "batch_id": "b-page", **default_versions(),
            "collector_id": "c1", "source": "codex", "source_id": "codex-local",
            "agent_type": "codex", "source_kind": "codex_local", "cursor": "cur",
            "items": items,
        })
        page1 = query_conversation_messages(conn, "conv-page", page=1, page_size=2)
        page2 = query_conversation_messages(conn, "conv-page", page=2, page_size=2)
        page3 = query_conversation_messages(conn, "conv-page", page=3, page_size=2)

    assert page1["total"] == 5
    assert [m["content"] for m in page1["messages"]] == ["消息5", "消息4"]
    assert page1["has_more"] is True
    assert [m["content"] for m in page2["messages"]] == ["消息3", "消息2"]
    assert page2["has_more"] is True
    assert [m["content"] for m in page3["messages"]] == ["消息1"]
    assert page3["has_more"] is False


def test_query_conversation_messages_role_filter(tmp_path):
    """role 筛选：只返回 user 或 assistant。"""
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, {
            "batch_id": "b-role", **default_versions(),
            "collector_id": "c1", "source": "codex", "source_id": "codex-local",
            "agent_type": "codex", "source_kind": "codex_local", "cursor": "cur",
            "items": [
                _item("p1", "agent_prompt", "输入1", (now - timedelta(minutes=2)).isoformat(), "conv-role"),
                _item("r1", "agent_response", "输出1", (now - timedelta(minutes=1)).isoformat(), "conv-role"),
            ],
        })
        user_only = query_conversation_messages(conn, "conv-role", role="user")
        assistant_only = query_conversation_messages(conn, "conv-role", role="assistant")

    assert user_only["total"] == 1
    assert [m["content"] for m in user_only["messages"]] == ["输入1"]
    assert assistant_only["total"] == 1
    assert [m["content"] for m in assistant_only["messages"]] == ["输出1"]


def test_query_conversation_messages_invalid_role_ignored(tmp_path):
    """非法 role 值忽略筛选，返回全部。"""
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, {
            "batch_id": "b-bad-role", **default_versions(),
            "collector_id": "c1", "source": "codex", "source_id": "codex-local",
            "agent_type": "codex", "source_kind": "codex_local", "cursor": "cur",
            "items": [
                _item("p1", "agent_prompt", "输入", (now - timedelta(minutes=2)).isoformat(), "conv-bad-role"),
                _item("r1", "agent_response", "输出", (now - timedelta(minutes=1)).isoformat(), "conv-bad-role"),
            ],
        })
        result = query_conversation_messages(conn, "conv-bad-role", role="system")

    assert result["total"] == 2


def test_query_conversation_messages_page_zero_defaults_to_one(tmp_path):
    """page=0 兜底为第 1 页；page_size=0 兜底为默认值 50。"""
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, {
            "batch_id": "b-zero", **default_versions(),
            "collector_id": "c1", "source": "codex", "source_id": "codex-local",
            "agent_type": "codex", "source_kind": "codex_local", "cursor": "cur",
            "items": [_item("p1", "agent_prompt", "输入", now.isoformat(), "conv-zero")],
        })
        result = query_conversation_messages(conn, "conv-zero", page=0, page_size=0)

    assert result["page"] == 1
    assert result["page_size"] == 50  # page_size=0 触发 `or 50` 兜底为默认值
    assert len(result["messages"]) == 1


def test_query_conversation_messages_page_size_capped_at_200(tmp_path):
    """page_size 上限 200。"""
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, {
            "batch_id": "b-cap", **default_versions(),
            "collector_id": "c1", "source": "codex", "source_id": "codex-local",
            "agent_type": "codex", "source_kind": "codex_local", "cursor": "cur",
            "items": [_item("p1", "agent_prompt", "输入", now.isoformat(), "conv-cap")],
        })
        result = query_conversation_messages(conn, "conv-cap", page_size=100000)

    assert result["page_size"] == 200


def test_query_conversation_messages_empty_conversation(tmp_path):
    """空会话返回空列表 + total=0。"""
    with connect(tmp_path / "observer.sqlite") as conn:
        # 仅写一条 usage（不进 conversation_messages）
        ingest_telemetry(conn, {
            "batch_id": "b-empty", **default_versions(),
            "collector_id": "c1", "source": "codex", "source_id": "codex-local",
            "agent_type": "codex", "source_kind": "codex_local", "cursor": "cur",
            "items": [_usage("u1", 10, datetime.now(UTC).isoformat(), "conv-empty")],
        })
        result = query_conversation_messages(conn, "conv-empty")

    assert result["total"] == 0
    assert result["messages"] == []
    assert result["has_more"] is False


def test_query_conversation_messages_page_out_of_range(tmp_path):
    """超出范围的页返回空列表 + has_more=false。"""
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, {
            "batch_id": "b-oor", **default_versions(),
            "collector_id": "c1", "source": "codex", "source_id": "codex-local",
            "agent_type": "codex", "source_kind": "codex_local", "cursor": "cur",
            "items": [_item("p1", "agent_prompt", "输入", now.isoformat(), "conv-oor")],
        })
        result = query_conversation_messages(conn, "conv-oor", page=999, page_size=50)

    assert result["total"] == 1
    assert result["messages"] == []
    assert result["has_more"] is False


def test_query_conversation_hits_paginated_desc(tmp_path):
    """hits 倒序分页。"""
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        items = []
        for i in range(1, 4):
            item = _tool_failure(f"fail-{i}", (now - timedelta(minutes=4 - i)).isoformat(), "conv-hits-page")
            items.append(item)
        ingest_telemetry(conn, {
            "batch_id": "b-hits-page", **default_versions(),
            "collector_id": "c1", "source": "codex", "source_id": "codex-local",
            "agent_type": "codex", "source_kind": "codex_local", "cursor": "cur",
            "items": items,
        })
        page1 = query_conversation_hits(conn, "conv-hits-page", page=1, page_size=2)
        page2 = query_conversation_hits(conn, "conv-hits-page", page=2, page_size=2)

    assert page1["total"] == 3
    assert len(page1["hits"]) == 2
    assert page1["has_more"] is True
    assert len(page2["hits"]) == 1
    assert page2["has_more"] is False


def test_query_conversation_hits_category_filter(tmp_path):
    """category 筛选。"""
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, {
            "batch_id": "b-cat", **default_versions(),
            "collector_id": "c1", "source": "codex", "source_id": "codex-local",
            "agent_type": "codex", "source_kind": "codex_local", "cursor": "cur",
            "items": [
                _tool_failure("fail-1", (now - timedelta(minutes=2)).isoformat(), "conv-cat"),
                _event("evt-1", "tool_call", (now - timedelta(minutes=1)).isoformat(), "conv-cat"),
            ],
        })
        # category='tool_execution_failure' 只匹配 _tool_failure
        filtered = query_conversation_hits(conn, "conv-cat", category="tool_execution_failure")
        all_hits = query_conversation_hits(conn, "conv-cat")

    assert filtered["total"] == 1
    assert filtered["hits"][0]["fact_id"] == "fail-1"
    assert all_hits["total"] == 2


def test_locate_conversation_message_returns_correct_page(tmp_path):
    """定位 fact_id 所在页号（倒序）。"""
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        items = [
            _item(f"loc-{i}", "agent_prompt", f"消息{i}", (now - timedelta(minutes=10 - i)).isoformat(), "conv-loc")
            for i in range(1, 6)
        ]
        ingest_telemetry(conn, {
            "batch_id": "b-loc", **default_versions(),
            "collector_id": "c1", "source": "codex", "source_id": "codex-local",
            "agent_type": "codex", "source_kind": "codex_local", "cursor": "cur",
            "items": items,
        })
        # loc-5 是最新 → 倒序 rank=0 → page=1
        # loc-1 是最旧 → 倒序 rank=4 → page=3（page_size=2）
        latest = locate_conversation_message(conn, "conv-loc", "loc-5", page_size=2)
        oldest = locate_conversation_message(conn, "conv-loc", "loc-1", page_size=2)

    assert latest["page"] == 1
    assert oldest["page"] == 3


def test_locate_conversation_message_fact_not_found(tmp_path):
    """fact_id 不存在抛 LookupError。"""
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, {
            "batch_id": "b-loc-404", **default_versions(),
            "collector_id": "c1", "source": "codex", "source_id": "codex-local",
            "agent_type": "codex", "source_kind": "codex_local", "cursor": "cur",
            "items": [_item("p1", "agent_prompt", "输入", now.isoformat(), "conv-loc-404")],
        })
        try:
            locate_conversation_message(conn, "conv-loc-404", "nonexistent-fact")
            raised = False
        except LookupError:
            raised = True

    assert raised is True


def test_query_conversation_hits_by_fact_ids(tmp_path):
    """按 fact_id 列表批量查询 hits。"""
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, {
            "batch_id": "b-batch", **default_versions(),
            "collector_id": "c1", "source": "codex", "source_id": "codex-local",
            "agent_type": "codex", "source_kind": "codex_local", "cursor": "cur",
            "items": [
                _tool_failure("fail-1", (now - timedelta(minutes=2)).isoformat(), "conv-batch"),
                _tool_failure("fail-2", (now - timedelta(minutes=1)).isoformat(), "conv-batch"),
                _event("evt-1", "tool_call", now.isoformat(), "conv-batch"),
            ],
        })
        result = query_conversation_hits_by_fact_ids(conn, "conv-batch", ["fail-1", "evt-1"])

    assert len(result["hits"]) == 2
    assert {h["fact_id"] for h in result["hits"]} == {"fail-1", "evt-1"}


def test_query_conversation_hits_by_fact_ids_empty_list(tmp_path):
    """空 fact_ids 列表返回空。"""
    with connect(tmp_path / "observer.sqlite") as conn:
        result = query_conversation_hits_by_fact_ids(conn, "conv-any", [])

    assert result["hits"] == []


def test_get_conversation_query_returns_totals_not_messages(tmp_path):
    """get_conversation_query 返回概要（无 messages/hits，有 totals）。"""
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, {
            "batch_id": "b-summary", **default_versions(),
            "collector_id": "c1", "source": "codex", "source_id": "codex-local",
            "agent_type": "codex", "source_kind": "codex_local", "cursor": "cur",
            "items": [
                _item("p1", "agent_prompt", "输入", (now - timedelta(minutes=2)).isoformat(), "conv-summary"),
                _item("r1", "agent_response", "输出", (now - timedelta(minutes=1)).isoformat(), "conv-summary"),
                _tool_failure("fail-1", now.isoformat(), "conv-summary"),
            ],
        })
        detail = get_conversation_query(conn, "conv-summary")

    assert "messages" not in detail
    assert "hits" not in detail
    assert detail["messages_total"] == 2
    assert detail["hits_total"] == 1


def test_get_conversation_for_fact_includes_focus_fact_id(tmp_path):
    """get_conversation_for_fact 返回 focus_fact_id。"""
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, {
            "batch_id": "b-focus", **default_versions(),
            "collector_id": "c1", "source": "codex", "source_id": "codex-local",
            "agent_type": "codex", "source_kind": "codex_local", "cursor": "cur",
            "items": [
                _item("p1", "agent_prompt", "输入", (now - timedelta(minutes=1)).isoformat(), "conv-focus"),
                _item("r1", "agent_response", "输出", now.isoformat(), "conv-focus"),
            ],
        })
        detail = get_conversation_for_fact(conn, "r1")

    assert detail["focus_fact_id"] == "r1"
    assert detail["conversation_ref"] == "conv-focus"


def test_query_conversation_messages_excludes_empty_content(tmp_path):
    """空 content 的消息行不在分页结果中，total 也排除空 content 行。"""
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, {
            "batch_id": "b-empty-content", **default_versions(),
            "collector_id": "c1", "source": "codex", "source_id": "codex-local",
            "agent_type": "codex", "source_kind": "codex_local", "cursor": "cur",
            "items": [
                _item("p1", "agent_prompt", "有内容的消息", (now - timedelta(minutes=1)).isoformat(), "conv-empty-content"),
            ],
        })
        # 直接插入一条空 content 行（模拟 materialize 边缘场景）
        conn.execute(
            "insert into conversation_messages "
            "(fact_id, conversation_ref, base_ref, role, category, occurred_at, content) "
            "values (?, ?, ?, 'assistant', 'agent_response', ?, '')",
            ("empty-fact-1", "conv-empty-content", "conv-empty-content", now.isoformat()),
        )
        conn.commit()
        detail = get_conversation_query(conn, "conv-empty-content")
        msgs = query_conversation_messages(conn, "conv-empty-content")

    assert detail["messages_total"] == 1
    assert msgs["total"] == 1
    assert len(msgs["messages"]) == 1
    assert msgs["messages"][0]["content"] == "有内容的消息"


def test_locate_conversation_message_rejects_empty_content_fact(tmp_path):
    """空 content 的 fact_id 不在分页中，locate 抛 LookupError。"""
    now = datetime.now(UTC).replace(microsecond=0)
    with connect(tmp_path / "observer.sqlite") as conn:
        ingest_telemetry(conn, {
            "batch_id": "b-loc-empty", **default_versions(),
            "collector_id": "c1", "source": "codex", "source_id": "codex-local",
            "agent_type": "codex", "source_kind": "codex_local", "cursor": "cur",
            "items": [
                _item("p1", "agent_prompt", "有内容", now.isoformat(), "conv-loc-empty"),
            ],
        })
        conn.execute(
            "insert into conversation_messages "
            "(fact_id, conversation_ref, base_ref, role, category, occurred_at, content) "
            "values (?, ?, ?, 'assistant', 'agent_response', ?, '')",
            ("empty-loc-fact", "conv-loc-empty", "conv-loc-empty", now.isoformat()),
        )
        conn.commit()
        try:
            locate_conversation_message(conn, "conv-loc-empty", "empty-loc-fact")
            raised = False
        except LookupError:
            raised = True

    assert raised is True
