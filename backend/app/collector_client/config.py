from __future__ import annotations

import getpass
import hashlib
import json
import os
import re
import socket
from dataclasses import dataclass
from pathlib import Path

from app.collector_client.discovery import discover_sources


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


_DEFAULTS = {
    "telemetry_mode": "fixture",
    "collection_interval_seconds": 10,
    "heartbeat_interval_seconds": 10,
    "history_window_days": 7,
    "max_events_per_cycle": 500,
    "upload_batch_size": 100,
    "evidence_mode": "structured_projection",
}


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
    server_url = payload.get("server_url")
    if not server_url:
        return None, "missing_server_url"
    return (
        CollectorConfig(
            server_url=str(server_url).rstrip("/"),
            collector_id=str(payload.get("collector_id", "windows-collector")),
            workdir=workdir,
            state_path=state_path,
            telemetry_mode=str(payload.get("telemetry_mode", _DEFAULTS["telemetry_mode"])),
            collection_interval_seconds=float(payload.get("collection_interval_seconds", _DEFAULTS["collection_interval_seconds"])),
            heartbeat_interval_seconds=float(payload.get("heartbeat_interval_seconds", _DEFAULTS["heartbeat_interval_seconds"])),
            sources=sources,
            history_window_days=int(payload.get("history_window_days", _DEFAULTS["history_window_days"])),
            max_events_per_cycle=int(payload.get("max_events_per_cycle", _DEFAULTS["max_events_per_cycle"])),
            upload_batch_size=int(payload.get("upload_batch_size", _DEFAULTS["upload_batch_size"])),
            evidence_mode=str(payload.get("evidence_mode", _DEFAULTS["evidence_mode"])),
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


def _default_collector_id() -> str:
    """生成 URL 安全的 collector_id。

    非 ASCII 用户名用 SHA-256 hash 替代；ASCII 但含 URL 不安全字符时替换为 -。
    """
    username = getpass.getuser()
    hostname = socket.gethostname()
    try:
        username.encode("ascii")
    except UnicodeEncodeError:
        digest = hashlib.sha256(username.encode("utf-8")).hexdigest()[:12]
        return f"collector-{digest}"
    raw = f"{hostname}-{username}"
    return re.sub(r"[^A-Za-z0-9._-]", "-", raw)


def _default_config_payload(config: CollectorConfig) -> dict:
    """序列化 CollectorConfig 为 JSON 可写 dict。"""
    state_path = config.state_path
    if config.workdir is not None and state_path.is_absolute():
        try:
            state_path = state_path.relative_to(config.workdir)
        except ValueError:
            pass
    return {
        "server_url": config.server_url,
        "collector_id": config.collector_id,
        "state_path": str(state_path),
        "telemetry_mode": config.telemetry_mode,
        "collection_interval_seconds": config.collection_interval_seconds,
        "heartbeat_interval_seconds": config.heartbeat_interval_seconds,
        "sources": [
            {
                "source_id": source.source_id,
                "agent_type": source.agent_type,
                "source_kind": source.source_kind,
                "display_name": source.display_name,
                "root": str(source.root),
                "enabled": source.enabled,
            }
            for source in config.sources
        ],
        "history_window_days": config.history_window_days,
        "max_events_per_cycle": config.max_events_per_cycle,
        "upload_batch_size": config.upload_batch_size,
        "evidence_mode": config.evidence_mode,
    }


def auto_config(
    workdir: Path,
    server_url: str | None = None,
) -> tuple[CollectorConfig | None, str | None]:
    """自动发现 Agent 并生成配置文件。

    不修改 load_config 的现有行为；仅在调用时写一次文件。
    """
    discovered = discover_sources()
    if not discovered:
        return None, "no_agent_found"
    if server_url:
        resolved_url = server_url
    else:
        port = os.environ.get("AGENT_OBSERVER_PORT", "8765")
        resolved_url = f"http://localhost:{port}"
    sources = [
        SourceConfig(
            source_id=f"{item.agent_type}-local",
            agent_type=item.agent_type,
            source_kind=item.source_kind,
            display_name=item.display_name,
            root=item.root,
            enabled=True,
        )
        for item in discovered
    ]
    config = CollectorConfig(
        server_url=resolved_url,
        collector_id=_default_collector_id(),
        workdir=workdir,
        state_path=workdir / "agent-observer.state.json",
        telemetry_mode=_DEFAULTS["telemetry_mode"],
        collection_interval_seconds=float(_DEFAULTS["collection_interval_seconds"]),
        heartbeat_interval_seconds=float(_DEFAULTS["heartbeat_interval_seconds"]),
        sources=sources,
        history_window_days=_DEFAULTS["history_window_days"],
        max_events_per_cycle=_DEFAULTS["max_events_per_cycle"],
        upload_batch_size=_DEFAULTS["upload_batch_size"],
        evidence_mode=_DEFAULTS["evidence_mode"],
    )
    config_path = workdir / "agent-observer.config.json"
    config_path.write_text(
        json.dumps(_default_config_payload(config), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return config, None
