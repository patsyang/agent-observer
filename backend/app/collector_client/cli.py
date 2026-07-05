from __future__ import annotations

import json
import sys
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Callable

from app.collector_client.config import CollectorConfig, load_config
from app.collector_client.local_log import local_log_emit
from app.collector_client.runtime import CommandResult, _json_result, _post_heartbeat, _run_once, _set_running, _start
from app.collector_client.status import _state_payload, _status_payload
from app.collector_client.transport import _get_json, _post_json

Emit = Callable[[str], None]


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
        return _json_result(0, _status_payload(config, verbose="--verbose" in args))
    local_emit = local_log_emit(config.workdir or config.state_path.parent, config.collector_id)
    if command == "start":
        return _start(config, _mirror_emit(local_emit, emit))
    if command == "stop":
        return _set_running(config, False)
    if command == "run-once":
        local_emit(
            json.dumps(
                {
                    "status": "ok",
                    "mode": "cycle_started",
                    "collector_id": config.collector_id,
                    "cycle": 1,
                    "sources_summary": [
                        {
                            "source_id": source.source_id,
                            "agent_type": source.agent_type,
                            "display_name": source.display_name,
                            "status": "enabled" if source.enabled else "disabled",
                        }
                        for source in config.sources
                    ],
                },
                sort_keys=True,
            )
        )
        result = _run_once(config, emit=local_emit, cycle=1)
        payload = json.loads(result.output)
        payload["mode"] = "cycle" if result.code == 0 else "cycle_error"
        payload["cycle"] = 1
        local_emit(json.dumps(payload, sort_keys=True))
        return result
    return _json_result(2, {"status": "error", "error": "unknown_command"})


def _mirror_emit(local_emit: Emit, emit: Emit | None) -> Emit:
    def mirrored(line: str) -> None:
        local_emit(line)
        if emit:
            emit(line)

    return mirrored


def _doctor(config: CollectorConfig | None, error: str | None) -> CommandResult:
    if error or config is None:
        return _json_result(2, {"status": "error", "enrichment": error})
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
                "enrichment": str(exc),
            },
        )
    codex_home = config.source_root("codex_local")
    return _json_result(
        0,
        {
            "status": "ok",
            "collector_id": config.collector_id,
            "server_url": config.server_url,
            "state_path": str(config.state_path),
            "sources": [
                {
                    "source_id": source.source_id,
                    "agent_type": source.agent_type,
                    "source_kind": source.source_kind,
                    "root": str(source.root),
                    "enabled": source.enabled,
                    "present": source.root.exists(),
                }
                for source in config.sources
            ],
            "codex_home": str(codex_home),
            "codex_sessions_present": (codex_home / "sessions").exists(),
            "evidence_mode": config.evidence_mode,
            "server_reachable": True,
            "enrichment_pull": True,
        },
    )


def _human_log_line(payload: dict[str, object]) -> str:
    mode = str(payload.get("mode") or "")
    now = datetime.now().strftime("%H:%M:%S")
    if mode == "started":
        return f"[{now}] 启动 collector: {payload.get('collector_id')}，采集 {_human_sources(payload)}，原始输入输出上传已启用"
    if mode == "cycle_started":
        return f"[{now}] 第 {payload.get('cycle')} 轮采集开始: {_human_sources(payload)}"
    if mode == "source_started":
        return f"[{now}] {_source_label(payload)} 开始采集"
    if mode == "source_completed":
        return _human_source_completed_line(now, payload)
    if mode == "upload_completed":
        return _human_upload_completed_line(now, payload)
    if mode == "upload_timeout_check":
        return f"[{now}] 上传超时，正在确认服务端接收状态"
    if mode == "upload_timeout_confirmed":
        return f"[{now}] 服务端已确认接收：{int(payload.get('accepted') or 0)} 条"
    if mode == "upload_timeout_missing":
        return f"[{now}] 服务端未确认接收：保留本地 outbox，下轮重试"
    if mode == "cycle":
        return _human_cycle_line(now, payload)
    if mode == "cycle_error":
        return _human_cycle_error_line(now, payload)
    if mode == "waiting":
        seconds = _display_wait_seconds(int(payload.get("seconds_until_next_cycle") or 0))
        return f"[{now}] 等待下一轮采集：{seconds} 秒"
    if mode == "stopped":
        return f"[{now}] collector 已停止，outbox 剩余 {payload.get('outbox_backlog', 0)} 条"
    if payload.get("status") == "error":
        return f"[{now}] 运行失败: {payload.get('error') or payload.get('last_error')}"
    return f"[{now}] {payload.get('status', 'ok')}"


def _human_cycle_line(now: str, payload: dict[str, object]) -> str:
    summary = payload.get("facts_summary") if isinstance(payload.get("facts_summary"), dict) else {}
    types = summary.get("types") if isinstance(summary.get("types"), dict) else {}
    generated = int(summary.get("generated") or 0)
    type_text = _human_type_counts(types)
    duration_ms = int(payload.get("last_cycle_duration_ms") or 0)
    enrichments = int(payload.get("enrichments") or 0)
    return (
        f"[{now}] 第 {payload.get('cycle')} 轮完成: "
        f"生成 {generated} 条事实，上传 {payload.get('uploaded', 0)} 条"
        f"{type_text}；{_human_source_counts(payload)}，补证 {enrichments}，outbox {payload.get('outbox_backlog', 0)}，耗时 {duration_ms / 1000:.1f}s"
    )


def _human_cycle_error_line(now: str, payload: dict[str, object]) -> str:
    duration_ms = int(payload.get("last_cycle_duration_ms") or 0)
    error = _safe_error_text(payload.get("error") or payload.get("last_error") or "未知错误")
    return (
        f"[{now}] 第 {payload.get('cycle')} 轮失败: {error}，"
        f"outbox {payload.get('outbox_backlog', 0)}，耗时 {duration_ms / 1000:.1f}s，下轮继续重试"
    )


def _human_source_completed_line(now: str, payload: dict[str, object]) -> str:
    label = _source_label(payload)
    status = str(payload.get("source_status") or "")
    reason = str(payload.get("reason_code") or status or "source_error")
    duration_ms = int(payload.get("duration_ms") or 0)
    if status == "degraded" or reason == "source_error":
        return f"[{now}] {label} 采集失败：{reason}，下轮继续"
    return f"[{now}] {label} 完成：生成 {int(payload.get('generated') or 0)} 条，耗时 {duration_ms / 1000:.1f}s"


def _human_upload_completed_line(now: str, payload: dict[str, object]) -> str:
    duration_ms = int(payload.get("duration_ms") or 0)
    return (
        f"[{now}] 上传完成：{int(payload.get('uploaded') or 0)} 条，"
        f"{int(payload.get('batches') or 0)} 批，outbox {int(payload.get('outbox_backlog') or 0)}，耗时 {duration_ms / 1000:.1f}s"
    )


def _safe_error_text(value: object) -> str:
    text = str(value or "未知错误")
    if _looks_like_path(text):
        return "采集或上传失败"
    return text


def _human_sources(payload: dict[str, object]) -> str:
    summaries = payload.get("sources_summary")
    if not isinstance(summaries, list):
        return "全部 Agent"
    labels = [_source_label(item) for item in summaries if isinstance(item, dict)]
    return "、".join(label for label in labels if label) or "全部 Agent"


def _human_source_counts(payload: dict[str, object]) -> str:
    summaries = payload.get("sources_summary")
    if not isinstance(summaries, list):
        return "按 Agent 未分组"
    parts = []
    for item in summaries:
        if not isinstance(item, dict):
            continue
        label = _source_label(item)
        generated = int(item.get("generated") or 0)
        status = str(item.get("status") or "")
        reason = str(item.get("reason_code") or "")
        detail = _human_type_counts(item.get("types") if isinstance(item.get("types"), dict) else {})
        suffix = detail if generated else f"（{reason or status}）"
        parts.append(f"{label} {generated} 条{suffix}")
    return "；".join(parts) if parts else "按 Agent 未分组"


def _source_label(item: dict[str, object]) -> str:
    agent_type = str(item.get("agent_type") or "").strip().lower()
    if agent_type in {"codex", "workbuddy"}:
        return {"codex": "Codex", "workbuddy": "WorkBuddy"}[agent_type]
    default_label = agent_type or "未知 Agent"
    display_name = str(item.get("display_name") or "").strip()
    if display_name and display_name.lower() not in {agent_type, f"{agent_type} local"} and not _looks_like_path(display_name):
        return display_name
    return default_label


def _looks_like_path(value: str) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in ("\\", "/", ".json", ".jsonl", ".ndjson", ".codex", ".workbuddy", "users", ":"))


def _human_type_counts(types: dict[str, object]) -> str:
    # Labels describe fact_type classification (what kind of raw event was
    # collected), NOT risk detection results. Risk signal detection is done
    # server-side via behavior_signals. Using "事件" suffix makes this clear.
    labels = {
        "error": "错误事件",
        "risk": "风险事件",
        "usage": "用量事件",
        "tool": "工具事件",
        "unknown": "未归类",
    }
    parts = [f"{label} {int(types[key])}" for key, label in labels.items() if int(types.get(key) or 0) > 0]
    return f"（{', '.join(parts)}）" if parts else ""


def _display_wait_seconds(seconds: int) -> int:
    if seconds <= 0:
        return 0
    return max(5, ((seconds + 4) // 5) * 5)


def main() -> int:
    argv = sys.argv[1:]
    json_mode = "--json" in argv
    argv = [arg for arg in argv if arg != "--json"]
    command = argv[0] if argv else "status"
    human_start = command == "start" and not json_mode

    def emit_line(line: str) -> None:
        if not human_start:
            print(line)
            return
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            print(line)
            return
        print(_human_log_line(payload))

    try:
        result = run(argv, emit=emit_line)
    except Exception as exc:
        result = _json_result(2, {"status": "error", "error": str(exc)})
    if not human_start:
        print(result.output)
    else:
        print(_human_log_line({**json.loads(result.output), "mode": "stopped"}))
    return result.code



if __name__ == "__main__":
    raise SystemExit(main())
