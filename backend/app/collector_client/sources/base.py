from __future__ import annotations

from dataclasses import dataclass

from app.collector_client.config import SourceConfig


@dataclass(frozen=True)
class SourceResult:
    config: SourceConfig
    status: str
    reason_code: str
    facts: list[dict]


def source_payload(config: SourceConfig, status: str = "online", reason_code: str | None = None) -> dict:
    return {
        "source_id": config.source_id,
        "agent_type": config.agent_type,
        "source_kind": config.source_kind,
        "display_name": config.display_name,
        "source_status": status,
        "reason_code": reason_code or status,
        "capabilities": {
            "raw_upload_default": True,
            "local_source": True,
        },
    }


def stamp_source(facts: list[dict], config: SourceConfig) -> list[dict]:
    for fact in facts:
        refs = fact.setdefault("source_refs", {})
        refs["source_id"] = config.source_id
        refs["agent_type"] = config.agent_type
        refs["source_kind"] = config.source_kind
        fact.setdefault("source_specific", {})
    return facts
