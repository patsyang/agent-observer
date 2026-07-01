from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SourceConfig:
    source_id: str
    agent_type: str
    source_kind: str
    display_name: str
    root: Path
    enabled: bool


@dataclass(frozen=True)
class CollectorConfig:
    server_url: str
    collector_id: str
    state_path: Path
    telemetry_mode: str
    collection_interval_seconds: float
    heartbeat_interval_seconds: float
    sources: list[SourceConfig]
    history_window_days: int
    max_events_per_cycle: int
    upload_batch_size: int
    evidence_mode: str
    workdir: Path | None = None

    def source_root(self, source_kind: str) -> Path:
        for source in self.sources:
            if source.source_kind == source_kind:
                return source.root
        return Path.home() / ".codex"


def load_config(workdir: Path) -> tuple[CollectorConfig | None, str | None]:
    config_path = workdir / "agent-observer.config.json"
    if not config_path.exists():
        return None, "missing_config"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    state_path = Path(str(payload.get("state_path", "agent-observer.state.json")))
    if not state_path.is_absolute():
        state_path = workdir / state_path
    try:
        sources = [_source_config(item, workdir) for item in payload.get("sources", []) if isinstance(item, dict)]
    except (KeyError, TypeError, ValueError):
        return None, "sources_required"
    if not sources:
        return None, "sources_required"
    return (
        CollectorConfig(
            server_url=str(payload["server_url"]).rstrip("/"),
            collector_id=str(payload.get("collector_id", "windows-collector")),
            workdir=workdir,
            state_path=state_path,
            telemetry_mode=str(payload.get("telemetry_mode", "fixture")),
            collection_interval_seconds=float(payload.get("collection_interval_seconds", 5)),
            heartbeat_interval_seconds=float(payload.get("heartbeat_interval_seconds", 10)),
            sources=sources,
            history_window_days=int(payload.get("history_window_days", 7)),
            max_events_per_cycle=int(payload.get("max_events_per_cycle", 500)),
            upload_batch_size=int(payload.get("upload_batch_size", 100)),
            evidence_mode=str(payload.get("evidence_mode", "structured_projection")),
        ),
        None,
    )


def _source_config(payload: dict, workdir: Path) -> SourceConfig:
    source_kind = str(payload["source_kind"])
    if source_kind == "workbuddy_local":
        default_root = Path.home() / ".workbuddy"
    elif source_kind == "claude_local":
        default_root = Path.home() / ".claude"
    else:
        default_root = Path.home() / ".codex"
    root = Path(os.path.expanduser(os.path.expandvars(str(payload.get("root", default_root)))))
    if not root.is_absolute():
        root = workdir / root
    source_id = str(payload["source_id"]).strip()
    agent_type = str(payload["agent_type"]).strip()
    source_kind = source_kind.strip()
    if not source_id or not agent_type or not source_kind:
        raise ValueError("sources_required")
    return SourceConfig(
        source_id=source_id,
        agent_type=agent_type,
        source_kind=source_kind,
        display_name=str(payload.get("display_name") or payload["source_id"]),
        root=root,
        enabled=bool(payload.get("enabled", True)),
    )
