from __future__ import annotations

import json
import re
from typing import Any

from app.sensitivity import sensitive_categories_from_text


def projection_preview(
    projection: dict[str, Any],
    raw_content: str | None,
    summary: str,
    category: str = "",
) -> str:
    prompt = _string_value(projection, "prompt_text")
    if prompt:
        return f"Prompt: {_truncate(prompt)}"
    content = _string_value(projection, "content_text") or _string_value(projection, "message_text")
    if content:
        role = _role_label(_string_value(projection, "role"))
        return f"{role}: {_truncate(content)}"
    reasoning = _string_value(projection, "reasoning_text")
    if reasoning:
        return f"推理片段: {_truncate(reasoning)}"

    tool = _string_value(projection, "tool") or _string_value(projection, "tool_name")
    command_category = _string_value(projection, "command_category")
    exit_code = projection.get("exit_code")
    if tool:
        pieces = [f"工具 {tool}"]
        if command_category:
            pieces.append(f"类别 {command_category}")
        if exit_code is not None:
            pieces.append(f"退出码 {exit_code}")
        return "，".join(pieces)

    units = projection.get("units")
    activity_tag = _activity_label(_string_value(projection, "activity_tag"))
    if units is not None:
        return f"用量 {int(units):,} token，活动 {activity_tag}"

    has_risk_projection = _has_risk_projection(projection, category)
    sensitive_hits = []
    object_type = ""
    if has_risk_projection:
        sensitive_hits = _sensitive_hits(projection) or _sensitive_hits_from_text(raw_content or "")
        object_type = _normalized_object_type(_string_value(projection, "object_type"), sensitive_hits)
        if object_type in {"credential", "auth"} and not sensitive_hits:
            has_risk_projection = False
            object_type = ""
    risk_type = _string_value(projection, "risk_type") or _category_risk_label(category)
    if has_risk_projection and (object_type or risk_type):
        object_label = _object_label(object_type)
        hit_text = f"，命中 {'、'.join(sensitive_hits)}" if sensitive_hits else ""
        if risk_type and object_label:
            return f"{risk_type}: {object_label}{hit_text}"
        return f"{risk_type or object_label}{hit_text}"

    raw_text = _raw_text_preview(raw_content)
    if raw_text:
        return raw_text

    content_length = projection.get("content_length")
    if content_length is not None:
        content_name = _content_name(category)
        return f"{content_name}，长度 {int(content_length):,} 字符，未上传原文"

    normalized_error = _string_value(projection, "normalized_error")
    if normalized_error:
        return f"错误归一化: {normalized_error}"

    return _truncate(summary)


def source_event_type(source_specific: dict[str, Any]) -> str:
    value = source_specific.get("codex_event_type") or source_specific.get("event_type") or "unknown"
    return str(value)


def source_label(source_refs: dict[str, Any]) -> str:
    if collector_id := source_refs.get("collector_id"):
        return f"采集器 {short_ref(str(collector_id))}"
    base = "Codex 会话"
    if conversation_ref := source_refs.get("conversation_ref"):
        base = f"{base} {short_ref(str(conversation_ref))}"
    elif source_key := source_refs.get("source_key"):
        base = f"{base} {short_ref(str(source_key))}"
    elif source_hash := source_refs.get("source_path_hash"):
        base = f"{base} {short_ref(str(source_hash))}"
    line_value = source_refs.get("line") or source_refs.get("line_number") or source_refs.get("record_index")
    if line_value is not None:
        return f"{base} · 行 {line_value}"
    return base


def raw_available(upload_raw: bool, raw_content: str | None) -> bool:
    return bool(upload_raw and raw_content)


def raw_status_label(upload_raw: bool, raw_content: str | None) -> str:
    if raw_available(upload_raw, raw_content):
        return "已上传原文"
    if upload_raw:
        return "已请求原文但本条无原文"
    return "仅结构化字段"


def short_ref(value: str, prefix: int = 12, suffix: int = 8) -> str:
    if len(value) <= prefix + suffix + 3:
        return value
    return f"{value[:prefix]}...{value[-suffix:]}"


def _raw_text_preview(raw_content: str | None) -> str:
    if not raw_content:
        return ""
    parsed = _try_json(raw_content)
    if parsed is None:
        return f"原文: {_truncate(raw_content)}"
    text = _extract_text(parsed)
    if text:
        return f"原文: {_truncate(text)}"
    return f"原始 JSON: {_truncate(json.dumps(parsed, ensure_ascii=False, sort_keys=True))}"


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(part for item in value if (part := _extract_text(item)))
    if not isinstance(value, dict):
        return ""
    for key in ("text", "content", "message", "prompt", "output", "result"):
        if key in value:
            text = _extract_text(value[key])
            if text:
                return text
    payload = value.get("payload")
    if payload is not None:
        text = _extract_text(payload)
        if text:
            return text
    return ""


def _try_json(value: str) -> Any | None:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _string_value(mapping: dict[str, Any], key: str) -> str:
    value = mapping.get(key)
    return value if isinstance(value, str) else ""


def _truncate(value: str, limit: int = 220) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1]}…"


def _role_label(role: str) -> str:
    return {
        "user": "用户消息",
        "assistant": "模型消息",
        "system": "系统消息",
        "tool": "工具消息",
    }.get(role, "消息")


def _activity_label(value: str) -> str:
    return {
        "codex_turn": "Codex 对话",
        "bug_fix": "缺陷修复",
        "implementation": "实现开发",
        "test_run": "测试运行",
        "unknown": "未识别",
    }.get(value, value or "未识别")


def _object_label(value: str) -> str:
    return {
        "configuration": "配置对象",
        "file_path": "文件路径",
        "workspace_file": "工作区文件",
        "workspace": "工作区",
        "command": "命令",
        "auth": "认证对象",
        "credential": "认证凭据对象",
        "sensitive_reference": "敏感引用",
    }.get(value, value)


def _sensitive_hits(projection: dict[str, Any]) -> list[str]:
    value = projection.get("sensitive_categories")
    if not isinstance(value, list):
        return []
    return [str(item) for item in value[:5] if str(item) != "sensitive_reference"]


def _sensitive_hits_from_text(value: str) -> list[str]:
    return sensitive_categories_from_text(value)


def _normalized_object_type(object_type: str, sensitive_hits: list[str]) -> str:
    if object_type == "credential" and sensitive_hits == ["auth"]:
        return "auth"
    if not object_type and sensitive_hits:
        if any(hit in {"token", "secret", "credential", "cookie"} for hit in sensitive_hits):
            return "credential"
        if "auth" in sensitive_hits:
            return "auth"
    return object_type


def _has_risk_projection(projection: dict[str, Any], category: str) -> bool:
    return bool(
        projection.get("object_type")
        or projection.get("risk_type")
        or projection.get("sensitive_categories")
        or category in {"high_risk_operation", "sensitive_touch", "sensitive_object_touch"}
    )


def _category_risk_label(category: str) -> str:
    return {
        "high_risk_operation": "高风险操作",
        "sensitive_touch": "敏感对象触达",
        "sensitive_object_touch": "敏感对象触达",
    }.get(category, "")


def _content_name(category: str) -> str:
    return {
        "codex_prompt": "用户 Prompt",
        "codex_message": "Codex 消息",
        "codex_reasoning": "推理片段",
    }.get(category, "内容事件")
