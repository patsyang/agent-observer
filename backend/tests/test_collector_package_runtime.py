from __future__ import annotations

import json
import subprocess
import zipfile

from app.collector_client.cli import run
from app.db.connection import connect
from app.package.builder import build_windows_package
from backend.tests.test_collectors_policy_package import _write_codex_fixture


EFFECTIVE_POLICY = {
    "policy_version": 2,
    "raw_upload_mode": "always_on",
    "collection_interval_seconds": 3,
    "max_events_per_cycle": 700,
    "upload_batch_size": 120,
}


def _prepare_packaged_collector(tmp_path, extract_name: str):
    package_path = tmp_path / "agent-observer-windows.zip"
    with connect(tmp_path / "observer.sqlite") as conn:
        build_windows_package(conn, tmp_path)

    extract_dir = tmp_path / extract_name
    with zipfile.ZipFile(package_path) as archive:
        archive.extractall(extract_dir)

    config_path = extract_dir / "agent-observer.config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["collector_id"] = "package-test"
    config["collection_interval_seconds"] = 0
    for source in config["sources"]:
        if source["source_kind"] == "codex_local":
            source["root"] = str(extract_dir / ".codex")
        if source["source_kind"] == "workbuddy_local":
            source["root"] = str(extract_dir / ".workbuddy")
    config_path.write_text(json.dumps(config), encoding="utf-8")
    _write_codex_fixture(extract_dir / ".codex")
    _write_workbuddy_fixture(extract_dir / ".workbuddy")
    return extract_dir


def _write_workbuddy_fixture(root):
    project_dir = root / "projects" / "demo"
    project_dir.mkdir(parents=True, exist_ok=True)
    with (project_dir / "conversation.jsonl").open("w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "type": "message",
                    "role": "assistant",
                    "content": "WorkBuddy 已完成本地任务观察",
                    "sessionId": "workbuddy-session",
                    "timestamp": 1781345565734,
                    "cwd": "D:/workspace/app",
                    "providerData": {
                        "model": "deepseek-v4-pro",
                        "provider": "tencent",
                        "usage": {
                            "inputTokens": 1000,
                            "outputTokens": 120,
                            "totalTokens": 1120,
                            "inputTokensDetails": [{"cached_tokens": 800}],
                            "outputTokensDetails": [{"reasoning_tokens": 40}],
                        },
                        "rawUsage": {
                            "prompt_tokens": 1000,
                            "completion_tokens": 120,
                            "total_tokens": 1120,
                            "prompt_cache_hit_tokens": 800,
                            "prompt_cache_write_tokens": 30,
                            "credit": 2.5,
                            "completion_tokens_details": {"reasoning_tokens": 40},
                        },
                    },
                    "message": {"usage": {"input_tokens": 1000, "output_tokens": 120, "total_tokens": 1120, "cache_read_input_tokens": 800}},
                }
            )
            + "\n"
        )


def _install_fake_transport(monkeypatch, calls: list[tuple[str, str]], uploaded_batches: list[dict[str, object]]) -> None:
    def fake_post(_server_url: str, path: str, payload: dict[str, object]) -> dict[str, object]:
        calls.append(("POST", path))
        if path == "/api/telemetry/ingest":
            uploaded_batches.append(payload)
        return {"status": "ok", "effective_policy": EFFECTIVE_POLICY}

    def fake_get(_server_url: str, path: str) -> dict[str, object]:
        calls.append(("GET", path))
        if path.endswith("/enrichments/next"):
            return {"status": "none"}
        return {"enabled": True}

    monkeypatch.setattr("app.collector_client.cli._get_json", fake_get)
    monkeypatch.setattr("app.collector_client.runtime._get_json", fake_get)
    monkeypatch.setattr("app.collector_client.runtime._post_json", fake_post)


def test_packaged_collector_status_doctor_and_run_once_paths(tmp_path, monkeypatch):
    extract_dir = _prepare_packaged_collector(tmp_path, "unzipped")

    status = subprocess.run(
        [str(extract_dir / "agent-observer.cmd"), "status"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert status.returncode == 0
    status_payload = json.loads(status.stdout)
    assert status_payload["running"] is False
    assert status_payload["outbox_backlog"] == 0
    assert "cursor" not in status_payload
    assert status_payload["cursor_summary"]["last_sequence"] == 0

    calls: list[tuple[str, str]] = []
    uploaded_batches: list[dict[str, object]] = []
    register_payloads: list[dict[str, object]] = []
    heartbeat_payloads: list[dict[str, object]] = []
    _install_fake_transport(monkeypatch, calls, uploaded_batches)

    def fake_post_with_payload(_server_url: str, path: str, payload: dict[str, object]) -> dict[str, object]:
        calls.append(("POST", path))
        if path == "/api/collectors/register":
            register_payloads.append(payload)
        if path.endswith("/heartbeat"):
            heartbeat_payloads.append(payload)
        if path == "/api/telemetry/ingest":
            uploaded_batches.append(payload)
        return {"status": "ok", "effective_policy": EFFECTIVE_POLICY}

    monkeypatch.setattr("app.collector_client.runtime._post_json", fake_post_with_payload)

    doctor = run(["doctor"], cwd=extract_dir)
    assert doctor.code == 0
    doctor_payload = json.loads(doctor.output)
    assert doctor_payload["collector_id"] == "package-test"
    assert doctor_payload["server_reachable"] is True
    assert calls == [("GET", "/api/policy")]

    calls.clear()
    result = run(["run-once"], cwd=extract_dir)
    assert result.code == 0
    assert calls[0] == ("POST", "/api/collectors/register")
    assert calls.count(("POST", "/api/telemetry/ingest")) == 2
    assert calls.count(("POST", "/api/collectors/package-test/heartbeat")) >= 3
    assert calls[-1] == ("GET", "/api/collectors/package-test/enrichments/next")
    assert register_payloads[0]["protocol_version"] == "agent-observer-telemetry/v3"
    assert register_payloads[0]["agent_version"] == "0.3.0"
    assert {source["source_kind"] for source in register_payloads[0]["sources"]} == {"codex_local", "workbuddy_local"}
    assert all(payload["protocol_version"] == "agent-observer-telemetry/v3" for payload in heartbeat_payloads)
    assert all(payload["agent_version"] == "0.3.0" for payload in heartbeat_payloads)
    state = json.loads((extract_dir / "agent-observer.state.json").read_text(encoding="utf-8"))
    assert state["outbox"] == []
    assert state["cursor"]["last_sequence"] == 1
    assert state["effective_policy"]["collection_interval_seconds"] == 3
    assert state["effective_policy"]["max_events_per_cycle"] == 700
    assert state["effective_policy"]["upload_batch_size"] == 120
    assert "raw_upload_enabled" not in state
    assert state["last_upload_at"]
    batch_items = uploaded_batches[0]["items"]
    assert uploaded_batches[0]["protocol_version"] == "agent-observer-telemetry/v3"
    assert uploaded_batches[0]["agent_version"] == "0.3.0"
    assert {batch["source_kind"] for batch in uploaded_batches[:2]} == {"codex_local", "workbuddy_local"}
    assert len(batch_items) >= 2
    assert not any(item["category"] in {"collector_health", "collector_source_status"} for batch in uploaded_batches for item in batch["items"])
    assert any(item.get("error_signature") for item in batch_items)

    status_after_once = json.loads(run(["status"], cwd=extract_dir).output)
    assert status_after_once["outbox_backlog"] == 0
    assert "cursor" not in status_after_once
    assert status_after_once["cursor_summary"]["last_sequence"] == 1

    with (extract_dir / ".codex" / "sessions" / "session-package.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(
            "\n"
            + json.dumps(
                {
                    "timestamp": "2026-06-18T10:03:00+00:00",
                    "type": "tool_result",
                    "tool": "shell",
                    "exit_code": 1,
                    "phase": "raw-check",
                    "conversation_id": "conversation-package",
                    "session_id": "session-package",
                    "raw_message": "operator needs original evidence",
                }
            )
        )

    calls.clear()
    waits = {"count": 0}

    def stop_after_two_cycles(config, emit=None):
        waits["count"] += 1
        if waits["count"] < 2:
            return True
        state = json.loads(config.state_path.read_text(encoding="utf-8"))
        state["running"] = False
        config.state_path.write_text(json.dumps(state), encoding="utf-8")
        return False

    monkeypatch.setattr("app.collector_client.runtime._sleep_while_running", stop_after_two_cycles)
    start = run(["start"], cwd=extract_dir)
    start_payload = json.loads(start.output)
    assert start.code == 0
    assert start_payload["mode"] == "stopped"
    assert start_payload["running"] is False
    assert start_payload["cursor"]["last_sequence"] == 3
    assert calls.count(("POST", "/api/collectors/register")) == 1
    assert calls.count(("POST", "/api/telemetry/ingest")) == 2
    assert calls.count(("POST", "/api/collectors/package-test/heartbeat")) >= 4
    assert calls.count(("GET", "/api/collectors/package-test/enrichments/next")) == 2
    assert any(item.get("raw_content") for batch in uploaded_batches[1:] for item in batch["items"])

    stop = json.loads(run(["stop"], cwd=extract_dir).output)
    assert stop["running"] is False


def test_packaged_collector_first_run_uploads_raw_content_without_config_switch(tmp_path, monkeypatch):
    extract_dir = _prepare_packaged_collector(tmp_path, "unzipped-raw")

    calls: list[tuple[str, str]] = []
    uploaded_batches: list[dict[str, object]] = []
    _install_fake_transport(monkeypatch, calls, uploaded_batches)

    result = run(["run-once"], cwd=extract_dir)
    batch_items = uploaded_batches[0]["items"]
    prompt = next(item for item in batch_items if item["category"] == "agent_prompt")

    assert result.code == 0
    assert prompt["upload_raw"] is True
    assert prompt["raw_content"]
    assert prompt["projection"]["prompt_text"] == "请检查 Dashboard 为什么看不到原始 Prompt"


def test_packaged_collector_runs_tool_failure_enrichment_from_local_sessions(tmp_path, monkeypatch):
    extract_dir = _prepare_packaged_collector(tmp_path, "unzipped-enrichment")
    session_path = extract_dir / ".codex" / "sessions" / "session-package.jsonl"
    with session_path.open("a", encoding="utf-8") as handle:
        handle.write(
            "\n"
            + "\n".join(
                json.dumps(record)
                for record in [
                    {
                        "timestamp": "2026-06-18T10:04:00+00:00",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "name": "exec_command",
                            "call_id": "call-enrichment-001",
                            "arguments": json.dumps({"command": "npm test -- broken.spec.ts", "workdir": "D:/workspace/app"}),
                        },
                        "conversation_id": "conversation-package",
                        "session_id": "session-package",
                    },
                    {
                        "timestamp": "2026-06-18T10:05:00+00:00",
                        "type": "response_item",
                        "payload": {
                            "type": "function_call_output",
                            "call_id": "call-enrichment-001",
                            "output": "Exit code: 1\nWall time: 2.4 seconds\nstderr: assertion failed",
                        },
                        "conversation_id": "conversation-package",
                        "session_id": "session-package",
                    },
                ]
            )
        )

    result_payloads: list[dict[str, object]] = []
    next_calls = 0

    def fake_get(_server_url: str, path: str) -> dict[str, object]:
        nonlocal next_calls
        if path.endswith("/enrichments/next"):
            next_calls += 1
            if next_calls == 1:
                return {
                    "job_id": "enrichment-job-001",
                    "collector_id": "package-test",
                    "capability_id": "codex_tool_failure_context",
                    "status": "pending",
                    "command": {
                        "command_id": "collect_codex_tool_failure_context",
                        "signal_id": "signal-001",
                        "capability_id": "codex_tool_failure_context",
                        "evidence_refs": [{"conversation_ref": "conversation-package"}],
                    },
                }
            return {"status": "none"}
        return {"enabled": True}

    def fake_post(_server_url: str, path: str, payload: dict[str, object]) -> dict[str, object]:
        if path.endswith("/enrichments/enrichment-job-001/result"):
            result_payloads.append(payload)
        return {"status": "ok", "effective_policy": {"raw_upload_mode": "always_on"}}

    monkeypatch.setattr("app.collector_client.cli._get_json", fake_get)
    monkeypatch.setattr("app.collector_client.runtime._get_json", fake_get)
    monkeypatch.setattr("app.collector_client.runtime._post_json", fake_post)

    result = run(["run-once"], cwd=extract_dir)

    assert result.code == 0
    assert result_payloads
    payload = result_payloads[0]
    projection = payload["projection"]
    assert payload["status"] == "succeeded"
    assert projection["output_schema"] == "tool_failure_context.v1"
    assert projection["matched_failures"][0]["exit_code"] == 1
    assert projection["matched_failures"][0]["call_id"] == "call-enrichment-001"
    assert projection["matched_failures"][0]["command_excerpt"] == "npm test -- broken.spec.ts"
    assert projection["redaction"]["raw_content_uploaded"] is False
