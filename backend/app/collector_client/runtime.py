from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.collector_client.config import CollectorConfig
from app.collector_client.state import load_state, patch_state, save_state
from app.collector_client.status import (
    _already_running,
    _cursor_payload,
    _facts_summary,
    _load_configured_state,
    _state_payload,
    _utc_now,
)
from app.collector_client.telemetry import collect_facts
from app.collector_client.transport import _get_json, _hash, _post_json

Emit = Callable[[str], None]


@dataclass(frozen=True)
class CommandResult:
    code: int
    output: str


def _json_result(code: int, payload: dict[str, object]) -> CommandResult:
    return CommandResult(code=code, output=json.dumps(payload, sort_keys=True))


def _set_running(config: CollectorConfig, running: bool) -> CommandResult:
    state = _load_configured_state(config)
    state["running"] = running
    if not running:
        state["runtime_phase"] = "stopping"
        state["source_status"] = "offline"
        state["reason_code"] = "collector_stopped"
        try:
            _post_json(
                config.server_url,
                f"/api/collectors/{config.collector_id}/heartbeat",
                {
                    "source_status": "offline",
                    "runtime_phase": "stopping",
                    "reason_code": "collector_stopped",
                    "outbox_backlog": len(state["outbox"]),
                    "last_error": state.get("last_error"),
                },
            )
        except (OSError, ValueError, urllib.error.URLError) as exc:
            state["last_error"] = str(exc)
    save_state(config.state_path, state)
    payload = _state_payload(state)
    payload.update({"status": "ok", "collector_id": config.collector_id})
    return _json_result(0, payload)

def _start(config: CollectorConfig, emit: Emit | None) -> CommandResult:
    state = _load_configured_state(config)
    if _already_running(state, config):
        return _json_result(0, {"status": "ok", "mode": "already_running", "collector_id": config.collector_id, **_state_payload(state, compact=True)})
    state["running"] = True
    state["runtime_phase"] = "starting"
    state["source_status"] = "online"
    state["reason_code"] = "started"
    state["process_id"] = os.getpid()
    state["started_at"] = _utc_now()
    state["process_heartbeat_at"] = state["started_at"]
    save_state(config.state_path, state)
    try:
        _register_collector(config, state, "starting", "started")
    except (OSError, ValueError, urllib.error.URLError) as exc:
        state["last_error"] = str(exc)
        save_state(config.state_path, state)
    _emit(emit, {"status": "ok", "mode": "started", "collector_id": config.collector_id, **_state_payload(state, compact=True)})

    cycles = 0
    max_cycles = _max_start_cycles()
    stop_heartbeat = threading.Event()
    heartbeat_thread = threading.Thread(target=_heartbeat_loop, args=(config, stop_heartbeat), daemon=True)
    heartbeat_thread.start()
    while load_state(config.state_path)["running"]:
        cycle_no = cycles + 1
        cycle_started_at = time.monotonic()
        state = load_state(config.state_path)
        state["last_cycle_started_at"] = _utc_now()
        state["process_heartbeat_at"] = state["last_cycle_started_at"]
        state["runtime_phase"] = "collecting"
        state["source_status"] = "online"
        state["reason_code"] = "collecting"
        save_state(config.state_path, state)
        _emit(emit, {"status": "ok", "mode": "cycle_started", "collector_id": config.collector_id, "cycle": cycle_no})
        result = _run_once(config, heartbeat_reason="start_running", register=False)
        payload = json.loads(result.output)
        payload["mode"] = "cycle" if result.code == 0 else "cycle_error"
        payload["cycle"] = cycle_no
        payload["last_cycle_duration_ms"] = int((time.monotonic() - cycle_started_at) * 1000)
        state = load_state(config.state_path)
        state["last_cycle_duration_ms"] = payload["last_cycle_duration_ms"]
        state["last_cycle_finished_at"] = _utc_now()
        state["last_cycle_summary"] = payload.get("facts_summary", {})
        state["process_heartbeat_at"] = state["last_cycle_finished_at"]
        save_state(config.state_path, state)
        if isinstance(payload.get("cursor"), dict):
            payload["cursor"] = _cursor_payload(payload.get("cursor", {}))
        _emit(emit, payload)
        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            state = load_state(config.state_path)
            state["running"] = False
            save_state(config.state_path, state)
            break
        if not _sleep_while_running(config, emit):
            break
    stop_heartbeat.set()
    heartbeat_thread.join(timeout=2)
    return _json_result(
        0,
        {"status": "ok", "mode": "stopped", "collector_id": config.collector_id, **_state_payload(load_state(config.state_path))},
    )

def _run_once(config: CollectorConfig, heartbeat_reason: str = "run_once_completed", register: bool = True) -> CommandResult:
    state = _load_configured_state(config)
    if register:
        _register_collector(config, state, "starting", "started")
    next_sequence = int(state["cursor"]["last_sequence"]) + 1
    state["runtime_phase"] = "collecting"
    state["source_status"] = "online"
    state["reason_code"] = "collecting"
    save_state(config.state_path, state)
    facts = collect_facts(
        config.collector_id,
        next_sequence,
        config.telemetry_mode,
        codex_home=config.codex_home,
        history_window_days=config.history_window_days,
        max_events=config.max_events_per_cycle,
        cursor=state["cursor"],
        upload_raw=bool(state.get("raw_upload_enabled", config.raw_upload_enabled)),
    )
    state["outbox"].extend(facts)
    state["runtime_phase"] = "uploading" if state["outbox"] else "idle"
    state["reason_code"] = "uploading" if state["outbox"] else heartbeat_reason
    state["last_error"] = None
    save_state(config.state_path, state)
    try:
        uploaded = _upload_pending(config, state, heartbeat_reason)
        diagnostics = _run_pending_diagnostic(config)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        state["last_error"] = str(exc)
        save_state(config.state_path, state)
        return _json_result(2, {"status": "error", "collector_id": config.collector_id, "error": str(exc), **_state_payload(state)})
    state["cursor"]["last_sequence"] = next_sequence
    state["last_upload_at"] = datetime.now(timezone.utc).isoformat()
    state["last_error"] = None
    state["runtime_phase"] = "idle" if heartbeat_reason == "run_once_completed" else "waiting"
    state["reason_code"] = heartbeat_reason
    state["process_heartbeat_at"] = _utc_now()
    save_state(config.state_path, state)
    return _json_result(
        0,
        {
            "status": "ok",
            "uploaded": uploaded,
            "diagnostics": diagnostics,
            "collector_id": config.collector_id,
            "facts_summary": _facts_summary(facts),
            **_state_payload(state),
        },
    )

def _upload_pending(config: CollectorConfig, state: dict[str, object], heartbeat_reason: str) -> int:
    outbox = state["outbox"]
    if not outbox:
        return 0
    upload_count = len(outbox)
    batch_index = 0
    while outbox:
        batch_index += 1
        chunk = list(outbox[: max(1, int(config.upload_batch_size))])
        batch = {
            "batch_id": f"{config.collector_id}-{int(chunk[0]['source_refs']['sequence'])}-{batch_index}",
            "collector_id": config.collector_id,
            "source": "codex",
            "cursor": str(chunk[0]["source_refs"]["sequence"]),
            "items": chunk,
        }
        _post_json(config.server_url, "/api/telemetry/ingest", batch)
        del outbox[: len(chunk)]
        state["last_upload_at"] = datetime.now(timezone.utc).isoformat()
        save_state(config.state_path, state)
        heartbeat_result = _send_heartbeat(config, state, "uploading", "uploading")
        _apply_policy_to_state(state, heartbeat_result.get("effective_policy"))
        save_state(config.state_path, state)
    heartbeat_result = _post_json(
        config.server_url,
        f"/api/collectors/{config.collector_id}/heartbeat",
        {
            "source_status": "online",
            "runtime_phase": "idle" if heartbeat_reason == "run_once_completed" else "waiting",
            "reason_code": heartbeat_reason,
            "outbox_backlog": 0,
            "last_cycle_duration_ms": state.get("last_cycle_duration_ms"),
            "last_error": state.get("last_error"),
        },
    )
    _apply_policy_to_state(state, heartbeat_result.get("effective_policy"))
    return upload_count

def _run_pending_diagnostic(config: CollectorConfig) -> int:
    try:
        job = _get_json(config.server_url, f"/api/collectors/{config.collector_id}/diagnostics/next")
    except (OSError, ValueError, urllib.error.URLError):
        return 0
    if not job or job.get("status") == "none":
        return 0
    command = job.get("command") or {}
    if command.get("command_id") != "collect_codex_error_context":
        result = {"status": "unavailable", "summary": "白名单中不存在该补证能力", "projection": {"reason_code": "missing_capability"}}
    else:
        result = {
            "status": "succeeded",
            "summary": "客户端完成 Codex 错误上下文白名单补证，已生成结构化结果。",
            "projection": {
                "capability_id": job.get("capability_id"),
                "evidence_ref_count": len(command.get("args", {}).get("evidence_refs", [])),
                "raw_content_uploaded": False,
            },
        }
    _post_json(config.server_url, f"/api/collectors/{config.collector_id}/diagnostics/{job['job_id']}/result", result)
    return 1

def _register_collector(config: CollectorConfig, state: dict[str, object], phase: str, reason_code: str) -> dict[str, Any]:
    result = _post_json(
        config.server_url,
        "/api/collectors/register",
        {
            "collector_id": config.collector_id,
            "display_name": config.collector_id,
            "hostname_hash": _hash(socket.gethostname()),
            "windows_username_hash": _hash(os.environ.get("USERNAME", "local-user")),
            "agent_type": "codex",
            "agent_version": "0.1.0",
            "source_status": "online",
            "runtime_phase": phase,
            "reason_code": reason_code,
            "outbox_backlog": len(state.get("outbox", [])),
            "last_cycle_duration_ms": state.get("last_cycle_duration_ms"),
            "last_error": state.get("last_error"),
        },
    )
    _apply_policy_to_state(state, result.get("effective_policy"))
    save_state(config.state_path, state)
    return result

def _heartbeat_loop(config: CollectorConfig, stop_event: threading.Event) -> None:
    while not stop_event.wait(max(1.0, float(config.heartbeat_interval_seconds))):
        try:
            state = load_state(config.state_path)
            if not state.get("running"):
                return
            state = patch_state(
                config.state_path,
                {
                    "process_heartbeat_at": _utc_now(),
                    "runtime_phase": str(state.get("runtime_phase") or "idle"),
                    "source_status": "online",
                    "reason_code": str(state.get("reason_code") or "waiting"),
                },
            )
            _post_heartbeat(
                config,
                state,
                str(state.get("runtime_phase") or "idle"),
                str(state.get("reason_code") or "waiting"),
            )
        except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError):
            continue

def _send_heartbeat(config: CollectorConfig, state: dict[str, object], phase: str, reason_code: str) -> dict[str, Any]:
    state["process_heartbeat_at"] = _utc_now()
    state["runtime_phase"] = phase
    state["source_status"] = "online"
    state["reason_code"] = reason_code
    save_state(config.state_path, state)
    result = _post_heartbeat(config, state, phase, reason_code)
    _apply_policy_to_state(state, result.get("effective_policy"))
    save_state(config.state_path, state)
    return result

def _post_heartbeat(config: CollectorConfig, state: dict[str, object], phase: str, reason_code: str) -> dict[str, Any]:
    return _post_json(
        config.server_url,
        f"/api/collectors/{config.collector_id}/heartbeat",
        {
            "source_status": "online",
            "runtime_phase": phase,
            "reason_code": reason_code,
            "outbox_backlog": len(state.get("outbox", [])),
            "last_cycle_duration_ms": state.get("last_cycle_duration_ms"),
            "last_error": state.get("last_error"),
        },
    )

def _apply_policy_to_state(state: dict[str, object], policy: object) -> None:
    if isinstance(policy, dict) and "upload_raw" in policy:
        state["raw_upload_enabled"] = bool(policy["upload_raw"])

def _sleep_while_running(config: CollectorConfig, emit: Emit | None = None) -> bool:
    remaining = max(0, int(config.collection_interval_seconds))
    if remaining == 0:
        return bool(load_state(config.state_path)["running"])
    deadline = time.monotonic() + remaining
    last_notice = 0.0
    next_cycle_at = (datetime.now(timezone.utc) + timedelta(seconds=max(0, deadline - time.monotonic()))).isoformat()
    state = load_state(config.state_path)
    state["runtime_phase"] = "waiting"
    state["reason_code"] = "waiting"
    state["next_cycle_at"] = next_cycle_at
    save_state(config.state_path, state)
    while time.monotonic() < deadline:
        if not load_state(config.state_path)["running"]:
            return False
        now = time.monotonic()
        if now - last_notice >= 10 or last_notice == 0:
            last_notice = now
            state = load_state(config.state_path)
            _emit(
                emit,
                {
                    "status": "ok",
                    "mode": "waiting",
                    "collector_id": config.collector_id,
                    "seconds_until_next_cycle": max(0, int(deadline - now)),
                    **_state_payload(state, compact=True),
                    "next_cycle_at": next_cycle_at,
                },
            )
        time.sleep(min(0.5, deadline - time.monotonic()))
    return bool(load_state(config.state_path)["running"])

def _max_start_cycles() -> int | None:
    raw = os.environ.get("AGENT_OBSERVER_START_MAX_CYCLES")
    if not raw:
        return None
    try:
        return max(1, int(raw))
    except ValueError:
        return None

def _emit(emit: Emit | None, payload: dict[str, object]) -> None:
    if emit:
        emit(json.dumps(payload, sort_keys=True))
