from __future__ import annotations

import json
import sys
import urllib.error
from datetime import datetime
from pathlib import Path
from typing import Callable

from app.collector_client.config import CollectorConfig, load_config
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


def _human_log_line(payload: dict[str, object]) -> str:
    mode = str(payload.get("mode") or "")
    now = datetime.now().strftime("%H:%M:%S")
    if mode == "started":
        raw_status = "开启" if payload.get("raw_upload_enabled") else "关闭"
        return f"[{now}] 启动 collector: {payload.get('collector_id')}，原文上报: {raw_status}"
    if mode == "cycle_started":
        return f"[{now}] 第 {payload.get('cycle')} 轮采集开始"
    if mode == "cycle":
        return _human_cycle_line(now, payload)
    if mode == "cycle_error":
        return _human_cycle_error_line(now, payload)
    if mode == "waiting":
        seconds = _display_wait_seconds(int(payload.get("seconds_until_next_cycle") or 0))
        return f"[{now}] 运行中，等待下一轮采集，剩余 {seconds} 秒"
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
    diagnostics = int(payload.get("diagnostics") or 0)
    return (
        f"[{now}] 第 {payload.get('cycle')} 轮完成: "
        f"生成 {generated} 条事实，上传 {payload.get('uploaded', 0)} 条"
        f"{type_text}，补证 {diagnostics}，outbox {payload.get('outbox_backlog', 0)}，耗时 {duration_ms / 1000:.1f}s"
    )


def _human_cycle_error_line(now: str, payload: dict[str, object]) -> str:
    duration_ms = int(payload.get("last_cycle_duration_ms") or 0)
    error = str(payload.get("error") or payload.get("last_error") or "未知错误")
    return (
        f"[{now}] 第 {payload.get('cycle')} 轮失败: {error}，"
        f"outbox {payload.get('outbox_backlog', 0)}，耗时 {duration_ms / 1000:.1f}s，下轮继续重试"
    )


def _human_type_counts(types: dict[str, object]) -> str:
    labels = {
        "error": "错误",
        "risk": "风险",
        "usage": "用量",
        "tool": "工具",
        "collector_health": "自检",
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
    human_start = command == "start" and not json_mode and sys.stdout.isatty()

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
    except (OSError, ValueError) as exc:
        result = _json_result(2, {"status": "error", "error": str(exc)})
    if not human_start:
        print(result.output)
    else:
        print(_human_log_line({**json.loads(result.output), "mode": "stopped"}))
    return result.code



if __name__ == "__main__":
    raise SystemExit(main())
