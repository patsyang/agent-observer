from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CollectorConfig:
    server_url: str
    collector_id: str
    state_path: Path
    telemetry_mode: str
    collection_interval_seconds: float
    heartbeat_interval_seconds: float
    codex_home: Path
    history_window_days: int
    max_events_per_cycle: int
    upload_batch_size: int
    evidence_mode: str


def load_config(workdir: Path) -> tuple[CollectorConfig | None, str | None]:
    config_path = workdir / "agent-observer.config.json"
    if not config_path.exists():
        return None, "missing_config"
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    state_path = Path(str(payload.get("state_path", "agent-observer.state.json")))
    if not state_path.is_absolute():
        state_path = workdir / state_path
    codex_home = Path(os.path.expandvars(str(payload.get("codex_home", Path.home() / ".codex"))))
    if not codex_home.is_absolute():
        codex_home = workdir / codex_home
    return (
        CollectorConfig(
            server_url=str(payload["server_url"]).rstrip("/"),
            collector_id=str(payload.get("collector_id", "windows-collector")),
            state_path=state_path,
            telemetry_mode=str(payload.get("telemetry_mode", "fixture")),
            collection_interval_seconds=float(payload.get("collection_interval_seconds", 15)),
            heartbeat_interval_seconds=float(payload.get("heartbeat_interval_seconds", 10)),
            codex_home=codex_home,
            history_window_days=int(payload.get("history_window_days", 7)),
            max_events_per_cycle=int(payload.get("max_events_per_cycle", 100)),
            upload_batch_size=int(payload.get("upload_batch_size", 50)),
            evidence_mode=str(payload.get("evidence_mode", "structured_projection")),
        ),
        None,
    )
