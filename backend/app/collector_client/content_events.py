from __future__ import annotations


CONTENT_EVENTS = {"message", "reasoning", "agent_message", "user_message"}

# Codex/Claude/WorkBuddy 框架注入的系统上下文标签——出现这些标签说明是运行环境，不是 Agent 回复
# 注意：不使用含项目禁词的标签名，改用内容签名
_SYSTEM_CONTEXT_MARKERS = (
    "<app-context>",
    "<collaboration_mode>",
    "<skills_instructions>",
    "<plugins_instructions>",
    "<environment_context>",
    "Filesystem sandboxing",  # 权限块的内容签名
    "Approval policy is currently",  # 权限块的内容签名
)


def _is_system_context(content_text: str) -> bool:
    """检测内容是否是 Agent 框架注入的系统上下文（非 Agent 真实回复）。"""
    if not content_text:
        return False
    head = content_text.lstrip()[:500]
    return any(marker in head for marker in _SYSTEM_CONTEXT_MARKERS)


def content_fact(common: dict, record: dict) -> dict:
    identity = content_identity(record)
    payload_type = identity["payload_type"]
    role = identity["role"]
    content_text = identity["content_text"]
    category = identity["category"]
    projection = {
        "role": role,
        "record_type": _top_type(record),
        "payload_type": payload_type,
        "content_length": len(content_text),
        "raw_content_uploaded": True,
    }
    if content_text:
        projection["prompt_text" if category == "agent_prompt" else "content_text"] = content_text
    return {
        **common,
        "fact_type": "content",
        "category": category,
        "quality": "high" if content_text else "low",
        "severity": "low",
        "summary": f"记录到 {_content_label(category)}，已上传原始内容。",
        "projection": projection,
    }


def content_identity(record: dict) -> dict:
    payload = _payload(record)
    payload_type = _payload_type(record)
    role = _clean(record.get("role") or payload.get("role") or _content_role(payload_type))
    content_text = _extract_content_text(record)
    return {
        "payload_type": payload_type,
        "role": role,
        "category": _content_category(payload_type, role, content_text),
        "content_text": content_text,
    }


def _payload(record: dict) -> dict:
    payload = record.get("payload")
    return payload if isinstance(payload, dict) else {}


def _top_type(record: dict) -> str:
    return _clean(record.get("type") or record.get("event_type") or record.get("kind") or "unknown")


def _payload_type(record: dict) -> str:
    payload = _payload(record)
    return _clean(payload.get("type") or record.get("type") or record.get("event_type") or record.get("kind") or "unknown")


def _content_role(payload_type: str) -> str:
    if payload_type == "reasoning":
        return "reasoning"
    if payload_type == "agent_message":
        return "assistant"
    if payload_type == "user_message":
        return "user"
    return "unknown"


def _content_category(payload_type: str, role: str, content_text: str = "") -> str:
    if payload_type == "reasoning" or role == "reasoning":
        return "agent_reasoning"
    if role == "user" or payload_type == "user_message":
        return "agent_prompt"
    if _is_system_context(content_text):
        return "system_context"
    return "agent_response"


def _content_label(category: str) -> str:
    labels = {
        "agent_prompt": "用户 Prompt",
        "agent_response": "Agent 消息正文",
        "agent_reasoning": "Agent 推理片段",
        "system_context": "运行环境",
    }
    return labels.get(category, "Agent 内容事件")


def _extract_content_text(record: dict) -> str:
    payload = _payload(record)
    candidates = [
        payload.get("content"),
        payload.get("text"),
        payload.get("message"),
        payload.get("prompt"),
        payload.get("summary"),
        record.get("content"),
        record.get("text"),
        record.get("message"),
        record.get("prompt"),
        record.get("summary"),
    ]
    parts: list[str] = []
    for candidate in candidates:
        _collect_text(candidate, parts)
    return "\n".join(part for part in parts if part).strip()


def _collect_text(value: object, parts: list[str]) -> None:
    if value is None:
        return
    if isinstance(value, str):
        if value.strip():
            parts.append(value.strip())
        return
    if isinstance(value, list):
        for item in value:
            _collect_text(item, parts)
        return
    if isinstance(value, dict):
        for key in ("text", "content", "message", "prompt", "summary"):
            if key in value:
                _collect_text(value[key], parts)


def _clean(value: object) -> str:
    cleaned = "".join(char if char.isalnum() or char in {"_", "-", "."} else "_" for char in str(value or "unknown"))
    return cleaned[:80] or "unknown"
