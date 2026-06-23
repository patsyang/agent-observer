from __future__ import annotations


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
