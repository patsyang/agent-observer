from __future__ import annotations


CONTENT_EVENTS = {"message", "reasoning", "agent_message", "user_message"}


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
        "category": _content_category(payload_type, role),
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


def _content_category(payload_type: str, role: str) -> str:
    if payload_type == "reasoning" or role == "reasoning":
        return "agent_reasoning"
    if role == "user" or payload_type == "user_message":
        return "agent_prompt"
    return "agent_response"


def _content_label(category: str) -> str:
    labels = {
        "agent_prompt": "用户 Prompt",
        "agent_response": "Agent 消息正文",
        "agent_reasoning": "Agent 推理片段",
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
