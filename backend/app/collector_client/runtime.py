from __future__ import annotations

import json
import os
import signal
import socket
import threading
import time
import traceback
import urllib.error
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.collector_client.config import CollectorConfig
from app.collector_client.enrichment import run_enrichment
from app.collector_client.state import load_state, patch_state, save_state
from app.collector_client.status import (
    _already_running,
    _cursor_payload,
    _facts_summary,
    _load_configured_state,
    _state_payload,
    _utc_now,
)
from app.collector_client.sources import collect_sources, source_statuses
from app.collector_client.sources.base import SourceResult
from app.collector_client.transport import _get_json, _hash, _post_json, is_timeout_error
from app.collector_client.upload_ack import confirm_batch_after_timeout
from app.collector_client.version import COLLECTOR_CLIENT_VERSION, COLLECTOR_PROTOCOL_VERSION

Emit = Callable[[str], None]

MAX_BACKOFF_SECONDS = 60


@dataclass(frozen=True)
class CommandResult:
    code: int
    output: str


def _backoff_seconds(consecutive_errors: int) -> float:
    """连续失败时的指数退避：5, 10, 20, 40, 60, 60, ..."""
    if consecutive_errors <= 0:
        return 0
    return min(5 * (2 ** (consecutive_errors - 1)), MAX_BACKOFF_SECONDS)


def _outbox_soft_limit(state: dict[str, object]) -> int:
    """从 state.effective_policy 读取 outbox_soft_limit，缺失时回退到默认值 5000。"""
    policy = state.get("effective_policy")
    if isinstance(policy, dict):
        try:
            value = int(policy.get("outbox_soft_limit") or 0)
            if 500 <= value <= 50000:
                return value
        except (TypeError, ValueError):
            pass
    return 5000


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
                    "protocol_version": COLLECTOR_PROTOCOL_VERSION,
                    "agent_version": COLLECTOR_CLIENT_VERSION,
                    "source_status": "offline",
                    "runtime_phase": "stopping",
                    "reason_code": "collector_stopped",
                    "outbox_backlog": len(state["outbox"]),
                    "last_error": state.get("last_error"),
                    "sources": source_statuses(config),
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
    _emit(
        emit,
        {
            "status": "ok",
            "mode": "started",
            "collector_id": config.collector_id,
            "sources_summary": _configured_source_summaries(config),
            **_state_payload(state, compact=True),
        },
    )

    cycles = 0
    stop_heartbeat = threading.Event()

    def _handle_signal(_signum, _frame):
        try:
            patch_state(config.state_path, {"running": False})
        except Exception:
            pass
        stop_heartbeat.set()

    try:
        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)
    except (OSError, ValueError):
        pass

    heartbeat_thread = threading.Thread(target=_heartbeat_loop, args=(config, stop_heartbeat), daemon=True)
    heartbeat_thread.start()
    consecutive_errors = 0
    while True:
        try:
            if not load_state(config.state_path)["running"]:
                break
        except Exception:
            time.sleep(5)
            continue
        cycle_no = cycles + 1
        try:
            cycle_started_at = time.monotonic()
            state = load_state(config.state_path)
            effective_config = _refresh_policy_config(config, state, "collecting", "collecting")
            state = load_state(config.state_path)
            state["last_cycle_started_at"] = _utc_now()
            state["process_heartbeat_at"] = state["last_cycle_started_at"]
            state["runtime_phase"] = "collecting"
            state["source_status"] = "online"
            state["reason_code"] = "collecting"
            save_state(config.state_path, state)
            _emit(
                emit,
                {
                    "status": "ok",
                    "mode": "cycle_started",
                    "collector_id": config.collector_id,
                    "cycle": cycle_no,
                    "sources_summary": _configured_source_summaries(config),
                },
            )
            result = _run_once(effective_config, heartbeat_reason="start_running", register=False, emit=emit, cycle=cycle_no)
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
            consecutive_errors = 0
            if not _sleep_while_running(_config_with_policy(config, load_state(config.state_path)), emit):
                break
        except Exception as exc:
            try:
                patch_state(config.state_path, {"last_error": str(exc)})
            except Exception:
                pass
            consecutive_errors += 1
            backoff = _backoff_seconds(consecutive_errors)
            _emit(
                emit,
                {
                    "status": "error",
                    "mode": "cycle_error",
                    "collector_id": config.collector_id,
                    "cycle": cycle_no,
                    "error": str(exc),
                    "exception_type": type(exc).__name__,
                    "traceback": traceback.format_exc(),
                    "consecutive_errors": consecutive_errors,
                    "backoff_seconds": backoff,
                },
            )
            time.sleep(backoff)
            continue
    stop_heartbeat.set()
    heartbeat_thread.join(timeout=2)
    return _json_result(
        0,
        {"status": "ok", "mode": "stopped", "collector_id": config.collector_id, **_state_payload(load_state(config.state_path))},
    )

def _run_once(
    config: CollectorConfig,
    heartbeat_reason: str = "run_once_completed",
    register: bool = True,
    emit: Emit | None = None,
    cycle: int | None = None,
) -> CommandResult:
    state = _load_configured_state(config)
    if register:
        try:
            _register_collector(config, state, "starting", "started")
        except (OSError, ValueError, urllib.error.URLError) as exc:
            state["last_error"] = str(exc)
            state["reason_code"] = "policy_not_fetched"
            save_state(config.state_path, state)
        state = _load_configured_state(config)
    config = _refresh_policy_config(config, state, "collecting", "collecting")
    state = _load_configured_state(config)
    next_sequence = int(state["cursor"]["last_sequence"]) + 1
    state["runtime_phase"] = "collecting"
    state["source_status"] = "online"
    state["reason_code"] = "collecting"
    save_state(config.state_path, state)
    if len(state.get("outbox", [])) >= _outbox_soft_limit(state):
        # outbox 积压超限，跳过采集只上传，避免雪崩
        facts = []
        source_results = []
        state["reason_code"] = "outbox_backlog"
    else:
        source_results = collect_sources(config, state, next_sequence, emit=lambda payload: _emit(emit, payload), cycle=cycle)
        facts = [fact for result in source_results for fact in result.facts]
    state["outbox"].extend(facts)
    state["runtime_phase"] = "uploading" if state["outbox"] else "idle"
    state["reason_code"] = "uploading" if state["outbox"] else heartbeat_reason
    state["last_error"] = None
    save_state(config.state_path, state)
    try:
        uploaded = _upload_pending(config, state, heartbeat_reason, emit=emit, cycle=cycle)
        enrichments = _run_pending_enrichment(config)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        state["last_error"] = str(exc)
        save_state(config.state_path, state)
        _emit(
            emit,
            {
                "status": "error",
                "mode": "runtime_error",
                "collector_id": config.collector_id,
                "cycle": cycle,
                "error": str(exc),
                "exception_type": type(exc).__name__,
                "traceback": traceback.format_exc(),
                **_state_payload(state, compact=True),
            },
        )
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
            "enrichments": enrichments,
            "collector_id": config.collector_id,
            "facts_summary": _facts_summary(facts),
            "sources_summary": _source_run_summaries(source_results),
            **_state_payload(state),
        },
    )

def _upload_pending(
    config: CollectorConfig,
    state: dict[str, object],
    heartbeat_reason: str,
    emit: Emit | None = None,
    cycle: int | None = None,
) -> int:
    outbox = state["outbox"]
    if not outbox:
        return 0
    upload_count = len(outbox)
    batch_index = 0
    started_at = time.monotonic()
    while outbox:
        batch_index += 1
        chunk = _next_upload_chunk(outbox, max(1, int(config.upload_batch_size)))
        source_meta = _fact_source_meta(chunk[0])
        batch = {
            "batch_id": f"{config.collector_id}-{source_meta['source_id']}-{int(chunk[0]['source_refs']['sequence'])}-{batch_index}",
            "protocol_version": COLLECTOR_PROTOCOL_VERSION,
            "agent_version": COLLECTOR_CLIENT_VERSION,
            "collector_id": config.collector_id,
            "source_id": source_meta["source_id"],
            "source": source_meta["agent_type"],
            "agent_type": source_meta["agent_type"],
            "source_kind": source_meta["source_kind"],
            "cursor": str(chunk[0]["source_refs"]["sequence"]),
            "items": chunk,
        }
        try:
            _post_json(config.server_url, "/api/telemetry/ingest", batch)
        except (OSError, TimeoutError, urllib.error.URLError, ValueError) as exc:
            if not is_timeout_error(exc):
                raise
            confirmed = confirm_batch_after_timeout(
                config,
                str(batch["batch_id"]),
                emit_payload=lambda payload: _emit(emit, payload),
                cycle=cycle,
            )
            if not confirmed:
                raise TimeoutError("batch_acceptance_unconfirmed") from exc
        del outbox[: len(chunk)]
        state["last_upload_at"] = datetime.now(timezone.utc).isoformat()
        try:
            save_state(config.state_path, state)
        except OSError:
            outbox[:0] = chunk
            raise
        _send_heartbeat(config, state, "uploading", "uploading")
        save_state(config.state_path, state)
    result = _post_heartbeat(config, state, "idle" if heartbeat_reason == "run_once_completed" else "waiting", heartbeat_reason)
    _remember_effective_policy(state, result)
    save_state(config.state_path, state)
    _emit(
        emit,
        {
            "status": "ok",
            "mode": "upload_completed",
            "cycle": cycle,
            "uploaded": upload_count,
            "batches": batch_index,
            "outbox_backlog": len(outbox),
            "duration_ms": int((time.monotonic() - started_at) * 1000),
        },
    )
    return upload_count

def _run_pending_enrichment(config: CollectorConfig) -> int:
    try:
        job = _get_json(config.server_url, f"/api/collectors/{config.collector_id}/enrichments/next")
    except (OSError, ValueError, urllib.error.URLError):
        return 0
    if not job or job.get("status") == "none":
        return 0
    job_id = job.get("job_id")
    if not job_id:
        return 0
    try:
        result = run_enrichment(config, job)
        _post_json(config.server_url, f"/api/collectors/{config.collector_id}/enrichments/{job_id}/result", result)
    except Exception:
        return 0
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
            "protocol_version": COLLECTOR_PROTOCOL_VERSION,
            "agent_version": COLLECTOR_CLIENT_VERSION,
            "source_status": "online",
            "runtime_phase": phase,
            "reason_code": reason_code,
            "outbox_backlog": len(state.get("outbox", [])),
            "last_cycle_duration_ms": state.get("last_cycle_duration_ms"),
            "last_error": state.get("last_error"),
            "sources": source_statuses(config),
        },
    )
    _remember_effective_policy(state, result)
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
            result = _post_heartbeat(
                config,
                state,
                str(state.get("runtime_phase") or "idle"),
                str(state.get("reason_code") or "waiting"),
            )
            _remember_effective_policy(state, result)
            if isinstance(result, dict) and isinstance(result.get("effective_policy"), dict):
                patch_state(config.state_path, {"effective_policy": state.get("effective_policy")})
        except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError):
            continue

def _send_heartbeat(config: CollectorConfig, state: dict[str, object], phase: str, reason_code: str) -> dict[str, Any]:
    state["process_heartbeat_at"] = _utc_now()
    state["runtime_phase"] = phase
    state["source_status"] = "online"
    state["reason_code"] = reason_code
    save_state(config.state_path, state)
    result = _post_heartbeat(config, state, phase, reason_code)
    _remember_effective_policy(state, result)
    save_state(config.state_path, state)
    return result

def _post_heartbeat(config: CollectorConfig, state: dict[str, object], phase: str, reason_code: str) -> dict[str, Any]:
    return _post_json(
        config.server_url,
        f"/api/collectors/{config.collector_id}/heartbeat",
        {
            "protocol_version": COLLECTOR_PROTOCOL_VERSION,
            "agent_version": COLLECTOR_CLIENT_VERSION,
            "source_status": "online",
            "runtime_phase": phase,
            "reason_code": reason_code,
            "outbox_backlog": len(state.get("outbox", [])),
            "last_cycle_duration_ms": state.get("last_cycle_duration_ms"),
            "last_error": state.get("last_error"),
            "sources": source_statuses(config),
        },
    )


def _refresh_policy_config(config: CollectorConfig, state: dict[str, object], phase: str, reason_code: str) -> CollectorConfig:
    try:
        result = _post_heartbeat(config, state, phase, reason_code)
        _remember_effective_policy(state, result)
        save_state(config.state_path, state)
    except (OSError, ValueError, urllib.error.URLError, json.JSONDecodeError):
        pass
    return _config_with_policy(config, state)


def _remember_effective_policy(state: dict[str, object], response: dict[str, Any] | None) -> None:
    if not isinstance(response, dict):
        return
    policy = response.get("effective_policy")
    if not isinstance(policy, dict):
        return
    state["effective_policy"] = {
        "policy_version": policy.get("policy_version"),
        "collection_interval_seconds": _policy_int(policy, "collection_interval_seconds"),
        "max_events_per_cycle": _policy_int(policy, "max_events_per_cycle"),
        "upload_batch_size": _policy_int(policy, "upload_batch_size"),
        "outbox_soft_limit": _policy_int(policy, "outbox_soft_limit"),
    }


def _config_with_policy(config: CollectorConfig, state: dict[str, object]) -> CollectorConfig:
    policy = state.get("effective_policy")
    if not isinstance(policy, dict):
        return config
    values = {
        "collection_interval_seconds": _bounded_policy_value(
            policy.get("collection_interval_seconds"),
            config.collection_interval_seconds,
            1,
            300,
        ),
        "max_events_per_cycle": _bounded_policy_value(policy.get("max_events_per_cycle"), config.max_events_per_cycle, 100, 5000),
        "upload_batch_size": _bounded_policy_value(policy.get("upload_batch_size"), config.upload_batch_size, 20, 500),
    }
    return replace(config, **values)


def _policy_int(policy: dict[str, object], key: str) -> int | None:
    try:
        return int(policy[key])
    except (KeyError, TypeError, ValueError):
        return None


def _bounded_policy_value(value: object, fallback: int | float, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return int(fallback)
    if parsed < minimum or parsed > maximum:
        return int(fallback)
    return parsed


def _next_upload_chunk(outbox: list, limit: int) -> list[dict]:
    first_meta = _fact_source_meta(outbox[0])
    chunk: list[dict] = []
    for item in outbox[:limit]:
        if _fact_source_meta(item) != first_meta:
            break
        chunk.append(item)
    return chunk


def _fact_source_meta(fact: dict) -> dict[str, str]:
    refs = fact.get("source_refs") if isinstance(fact.get("source_refs"), dict) else {}
    return {
        "source_id": str(refs.get("source_id") or "unknown-source"),
        "agent_type": str(refs.get("agent_type") or "unknown"),
        "source_kind": str(refs.get("source_kind") or "unknown"),
    }


def _configured_source_summaries(config: CollectorConfig) -> list[dict[str, object]]:
    return [
        {
            "source_id": source.source_id,
            "agent_type": source.agent_type,
            "display_name": source.display_name,
            "status": "enabled" if source.enabled else "disabled",
            "reason_code": "configured" if source.enabled else "disabled",
            "generated": 0,
            "types": {},
        }
        for source in config.sources
    ]


def _source_run_summaries(results: list[SourceResult]) -> list[dict[str, object]]:
    return [
        {
            "source_id": result.config.source_id,
            "agent_type": result.config.agent_type,
            "display_name": result.config.display_name,
            "status": result.status,
            "reason_code": result.reason_code,
            **_facts_summary(result.facts),
        }
        for result in results
    ]

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
                    "sources_summary": _configured_source_summaries(config),
                    **_state_payload(state, compact=True),
                    "next_cycle_at": next_cycle_at,
                },
            )
        time.sleep(min(0.5, deadline - time.monotonic()))
    return bool(load_state(config.state_path)["running"])

def _emit(emit: Emit | None, payload: dict[str, object]) -> None:
    if emit:
        emit(json.dumps(payload, sort_keys=True))
