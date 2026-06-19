from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.collector_client.config import CollectorConfig, load_config
from app.collector_client.state import load_state, save_state
from app.collector_client.telemetry import collect_facts


@dataclass(frozen=True)
class CommandResult:
    code: int
    output: str


Emit = Callable[[str], None]
HTTP_TIMEOUT_SECONDS = 60


def run(argv: list[str] | None = None, cwd: Path | None = None, emit: Emit | None = None) -> CommandResult:
    args = list(argv or [])
    workdir = cwd or Path.cwd()
    command = args[0] if args else "status"
    config, error = load_config(workdir)
    if command == "doctor":
        return _doctor(config, error)
    if error or config is None:
        return _json_result(2, {"status": "error", "error": error})
    if command == "status":
        return _json_result(0, _status_payload(config))
    if command == "start":
        return _start(config, emit)
    if command == "stop":
        return _set_running(config, False)
    if command == "run-once":
        return _run_once(config)
    return _json_result(2, {"status": "error", "error": "unknown_command"})


def _doctor(config: CollectorConfig | None, error: str | None) -> CommandResult:
    if error or config is None:
        return _json_result(2, {"status": "error", "diagnostic": error})
    try:
        _get_json(config.server_url, "/api/policy")
    except (OSError, ValueError, urllib.error.URLError) as exc:
        return _json_result(
            2,
            {
                "status": "error",
                "collector_id": config.collector_id,
                "server_url": config.server_url,
                "state_path": str(config.state_path),
                "server_reachable": False,
                "diagnostic": str(exc),
            },
        )
    return _json_result(
        0,
        {
            "status": "ok",
            "collector_id": config.collector_id,
            "server_url": config.server_url,
            "state_path": str(config.state_path),
            "codex_home": str(config.codex_home),
            "codex_sessions_present": (config.codex_home / "sessions").exists(),
            "evidence_mode": config.evidence_mode,
            "server_reachable": True,
            "diagnostic_pull": True,
        },
    )


def _set_running(config: CollectorConfig, running: bool) -> CommandResult:
    state = _load_configured_state(config)
    state["running"] = running
    if not running:
        try:
            _post_json(
                config.server_url,
                f"/api/collectors/{config.collector_id}/heartbeat",
                {"source_status": "offline", "reason_code": "collector_stopped", "outbox_backlog": len(state["outbox"])},
            )
        except (OSError, ValueError, urllib.error.URLError) as exc:
            state["last_error"] = str(exc)
    save_state(config.state_path, state)
    payload = _state_payload(state)
    payload.update({"status": "ok", "collector_id": config.collector_id})
    return _json_result(0, payload)


def _start(config: CollectorConfig, emit: Emit | None) -> CommandResult:
    state = _load_configured_state(config)
    state["running"] = True
    save_state(config.state_path, state)
    _emit(emit, {"status": "ok", "mode": "started", "collector_id": config.collector_id, **_state_payload(state)})

    cycles = 0
    max_cycles = _max_start_cycles()
    while load_state(config.state_path)["running"]:
        result = _run_once(config, heartbeat_reason="start_running")
        payload = json.loads(result.output)
        payload["mode"] = "cycle"
        _emit(emit, payload)
        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            state = load_state(config.state_path)
            state["running"] = False
            save_state(config.state_path, state)
            break
        if not _sleep_while_running(config):
            break

    return _json_result(
        0,
        {"status": "ok", "mode": "stopped", "collector_id": config.collector_id, **_state_payload(load_state(config.state_path))},
    )


def _run_once(config: CollectorConfig, heartbeat_reason: str = "run_once_completed") -> CommandResult:
    state = _load_configured_state(config)
    next_sequence = int(state["cursor"]["last_sequence"]) + 1
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
    history_source_keys = [
        str(item.get("source_refs", {}).get("source_key", ""))
        for item in facts
        if item.get("source_specific", {}).get("priority_stream") != "live_tail"
    ]
    history_source_keys = [
        source_key
        for source_key in history_source_keys
        if source_key and not source_key.startswith(("health:", "source-status:"))
    ]
    if history_source_keys:
        state["cursor"]["last_source_key"] = max(history_source_keys)
    live_source_keys = [
        str(item.get("source_refs", {}).get("source_key", ""))
        for item in facts
        if item.get("source_specific", {}).get("priority_stream") == "live_tail"
    ]
    if live_source_keys:
        remembered = set(str(item) for item in state["cursor"].get("recent_source_keys", []))
        remembered.update(source_key for source_key in live_source_keys if source_key)
        state["cursor"]["recent_source_keys"] = sorted(remembered)[-2000:]
    state["last_upload_at"] = datetime.now(timezone.utc).isoformat()
    state["last_error"] = None
    save_state(config.state_path, state)
    return _json_result(
        0,
        {
            "status": "ok",
            "uploaded": uploaded,
            "diagnostics": diagnostics,
            "collector_id": config.collector_id,
            **_state_payload(state),
        },
    )


def _upload_pending(config: CollectorConfig, state: dict[str, object], heartbeat_reason: str) -> int:
    outbox = state["outbox"]
    if not outbox:
        return 0
    upload_count = len(outbox)
    registered = _post_json(
        config.server_url,
        "/api/collectors/register",
        {
            "collector_id": config.collector_id,
            "display_name": config.collector_id,
            "hostname_hash": _hash(socket.gethostname()),
            "windows_username_hash": _hash(os.environ.get("USERNAME", "local-user")),
            "agent_type": "codex",
            "agent_version": "0.1.0",
            "source_status": "policy_not_fetched",
            "reason_code": "policy_not_fetched",
            "outbox_backlog": len(outbox),
        },
    )
    _apply_policy_to_state(state, registered.get("effective_policy"))
    batch = {
        "batch_id": f"{config.collector_id}-{int(outbox[0]['source_refs']['sequence'])}",
        "collector_id": config.collector_id,
        "source": "codex",
        "cursor": str(outbox[0]["source_refs"]["sequence"]),
        "items": list(outbox),
    }
    _post_json(config.server_url, "/api/telemetry/ingest", batch)
    outbox.clear()
    heartbeat_result = _post_json(
        config.server_url,
        f"/api/collectors/{config.collector_id}/heartbeat",
        {
            "source_status": "online" if heartbeat_reason == "start_running" else "offline",
            "reason_code": heartbeat_reason,
            "outbox_backlog": 0,
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


def _status_payload(config: CollectorConfig) -> dict[str, object]:
    state = _load_configured_state(config)
    payload = _state_payload(state)
    payload.update(
        {
            "status": "ok",
            "collector_id": config.collector_id,
            "server_url": config.server_url,
            "state_path": str(config.state_path),
        }
    )
    return payload


def _state_payload(state: dict[str, object]) -> dict[str, object]:
    return {
        "running": bool(state["running"]),
        "cursor": state["cursor"],
        "outbox_backlog": len(state["outbox"]),
        "last_upload_at": state["last_upload_at"],
        "last_error": state["last_error"],
        "raw_upload_enabled": bool(state.get("raw_upload_enabled", False)),
    }


def _load_configured_state(config: CollectorConfig) -> dict[str, object]:
    state = load_state(config.state_path)
    if "raw_upload_enabled" not in state:
        state["raw_upload_enabled"] = config.raw_upload_enabled
    return state


def _apply_policy_to_state(state: dict[str, object], policy: object) -> None:
    if isinstance(policy, dict) and "upload_raw" in policy:
        state["raw_upload_enabled"] = bool(policy["upload_raw"])


def _sleep_while_running(config: CollectorConfig) -> bool:
    remaining = max(0, int(config.collection_interval_seconds))
    if remaining == 0:
        return bool(load_state(config.state_path)["running"])
    deadline = time.monotonic() + remaining
    while time.monotonic() < deadline:
        if not load_state(config.state_path)["running"]:
            return False
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


def _get_json(server_url: str, path: str) -> dict[str, Any]:
    with urllib.request.urlopen(_url(server_url, path), timeout=HTTP_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json(server_url: str, path: str, payload: dict[str, object]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        _url(server_url, path),
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ValueError(f"http_error:{exc.code}") from exc


def _url(server_url: str, path: str) -> str:
    return server_url.rstrip("/") + path


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _json_result(code: int, payload: dict[str, object]) -> CommandResult:
    return CommandResult(code=code, output=json.dumps(payload, sort_keys=True))


def main() -> int:
    try:
        result = run(sys.argv[1:], emit=print)
    except (OSError, ValueError) as exc:
        result = _json_result(2, {"status": "error", "error": str(exc)})
    print(result.output)
    return result.code


if __name__ == "__main__":
    raise SystemExit(main())
