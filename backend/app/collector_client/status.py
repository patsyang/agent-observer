from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from app.collector_client.config import CollectorConfig
from app.collector_client.state import load_state, patch_state

STALE_HEARTBEAT_GRACE_SECONDS = 90


def _status_payload(config: CollectorConfig, *, verbose: bool = False) -> dict[str, object]:
    state = _load_configured_state(config)
    payload = _state_payload(state, compact=not verbose)
    liveness = _liveness(state, config.collection_interval_seconds)
    if liveness == "stale_state":
        payload["running"] = False
    payload.update(
        {
            "status": "ok",
            "collector_id": config.collector_id,
            "server_url": config.server_url,
            "state_path": str(config.state_path),
            "liveness": liveness,
            "message": _liveness_message(liveness),
        }
    )
    return payload

def _state_payload(state: dict[str, object], *, compact: bool = False) -> dict[str, object]:
    payload = {
        "running": bool(state["running"]),
        "cursor_summary": _cursor_payload(state.get("cursor", {})),
        "outbox_backlog": len(state["outbox"]),
        "last_upload_at": state["last_upload_at"],
        "last_error": state["last_error"],
        "runtime_phase": state.get("runtime_phase", "idle"),
        "reason_code": state.get("reason_code"),
        "source_status": state.get("source_status"),
        "process_id": state.get("process_id"),
        "started_at": state.get("started_at"),
        "process_heartbeat_at": state.get("process_heartbeat_at"),
        "last_cycle_started_at": state.get("last_cycle_started_at"),
        "last_cycle_finished_at": state.get("last_cycle_finished_at"),
        "last_cycle_duration_ms": state.get("last_cycle_duration_ms"),
        "next_cycle_at": state.get("next_cycle_at"),
        "last_cycle_summary": state.get("last_cycle_summary"),
    }
    if not compact:
        payload["cursor"] = state.get("cursor", {})
    return payload

def _cursor_payload(cursor: object) -> dict[str, object]:
    if not isinstance(cursor, dict):
        return {"last_sequence": 0, "source_file_count": 0, "live_tail_source_key_count": 0}
    sources = cursor.get("sources")
    source_count = len(sources) if isinstance(sources, dict) else 0
    live_tail = cursor.get("live_tail_source_keys")
    live_tail_count = len(live_tail) if isinstance(live_tail, list) else 0
    return {
        "last_sequence": int(cursor.get("last_sequence") or 0),
        "source_file_count": source_count,
        "live_tail_source_key_count": live_tail_count,
    }

def _facts_summary(facts: list[dict]) -> dict[str, object]:
    by_type: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for fact in facts:
        fact_type = str(fact.get("fact_type") or "unknown")
        category = str(fact.get("category") or "unknown")
        by_type[fact_type] = by_type.get(fact_type, 0) + 1
        by_category[category] = by_category.get(category, 0) + 1
    return {"generated": len(facts), "types": by_type, "categories": by_category}

def _source_keys_from_fact(fact: dict) -> list[str]:
    refs = fact.get("source_refs")
    if not isinstance(refs, dict):
        return []
    keys = [str(refs.get("source_key") or "")]
    alternates = refs.get("alternate_source_keys")
    if isinstance(alternates, list):
        keys.extend(str(item) for item in alternates)
    return [key for key in keys if key]

def _load_configured_state(config: CollectorConfig) -> dict[str, object]:
    return load_state(config.state_path)

def _already_running(state: dict[str, object], config: CollectorConfig) -> bool:
    if not state.get("running"):
        return False
    liveness = _liveness(state, config.collection_interval_seconds)
    if liveness == "stale_state":
        patch_state(config.state_path, {"running": False, "reason_code": "stale_state_reset"})
        return False
    return liveness in {"alive", "busy"}

def _liveness(state: dict[str, object], interval_seconds: int) -> str:
    if not bool(state.get("running")):
        return "stopped"
    if not _process_exists(state.get("process_id")):
        return "stale_state"
    heartbeat = _parse_datetime(state.get("process_heartbeat_at"))
    if not heartbeat:
        return "unknown"
    max_age = max(STALE_HEARTBEAT_GRACE_SECONDS, int(interval_seconds) * 2 + STALE_HEARTBEAT_GRACE_SECONDS)
    if datetime.now(timezone.utc) - heartbeat > timedelta(seconds=max_age):
        return "busy"
    return "alive"

def _liveness_message(liveness: str) -> str:
    return {
        "alive": "采集器进程仍在更新本地心跳。",
        "busy": "采集器进程仍存在，可能正在执行采集、上传或补证。",
        "stopped": "采集器未处于运行状态。",
        "stale_state": "上次进程心跳已过期，可能异常退出。",
    }.get(liveness, "无法确认采集器进程是否仍在运行。")

def _process_exists(value: object) -> bool:
    try:
        pid = int(value or 0)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True

def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
