from __future__ import annotations

from app.collector_client.version import COLLECTOR_CLIENT_VERSION, COLLECTOR_PROTOCOL_VERSION


def default_versions() -> dict:
    """返回当前 collector 客户端的协议与实现版本，供测试构造 payload 时引用常量而非硬编码字符串。"""
    return {
        "protocol_version": COLLECTOR_PROTOCOL_VERSION,
        "agent_version": COLLECTOR_CLIENT_VERSION,
    }


def default_sources() -> list[dict]:
    return [
        {
            "source_id": "codex-local",
            "agent_type": "codex",
            "source_kind": "codex_local",
            "display_name": "Codex Local",
            "source_status": "online",
            "reason_code": "online",
            "capabilities": {"raw_upload_default": True},
        },
        {
            "source_id": "workbuddy-local",
            "agent_type": "workbuddy",
            "source_kind": "workbuddy_local",
            "display_name": "WorkBuddy Local",
            "source_status": "online",
            "reason_code": "online",
            "capabilities": {"raw_upload_default": True},
        },
    ]
