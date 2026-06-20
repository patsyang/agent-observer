from __future__ import annotations

import json
import subprocess
import zipfile

from app.collector_client.cli import run
from app.db.connection import connect
from app.package.builder import build_windows_package
from backend.tests.test_collectors_policy_package import _write_codex_fixture


def _prepare_packaged_collector(tmp_path, extract_name: str, *, raw_upload: bool = False):
    package_path = tmp_path / "agent-observer-windows.zip"
    with connect(tmp_path / "observer.sqlite") as conn:
        build_windows_package(conn, tmp_path)

    extract_dir = tmp_path / extract_name
    with zipfile.ZipFile(package_path) as archive:
        archive.extractall(extract_dir)

    config_path = extract_dir / "agent-observer.config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["collector_id"] = "package-raw-test" if raw_upload else "package-test"
    config["collection_interval_seconds"] = 0
    config["codex_home"] = str(extract_dir / ".codex")
    if raw_upload:
        config["raw_upload_enabled"] = True
        config["effective_policy"]["upload_raw"] = True
    config_path.write_text(json.dumps(config), encoding="utf-8")
    _write_codex_fixture(extract_dir / ".codex")
    return extract_dir


def _install_fake_transport(monkeypatch, calls: list[tuple[str, str]], uploaded_batches: list[dict[str, object]]) -> None:
    def fake_post(_server_url: str, path: str, payload: dict[str, object]) -> dict[str, object]:
        calls.append(("POST", path))
        if path == "/api/telemetry/ingest":
            uploaded_batches.append(payload)
        return {"status": "ok", "effective_policy": {"upload_raw": True, "raw_upload_source": "collector_override"}}

    def fake_get(_server_url: str, path: str) -> dict[str, object]:
        calls.append(("GET", path))
        if path.endswith("/diagnostics/next"):
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
    _install_fake_transport(monkeypatch, calls, uploaded_batches)

    doctor = run(["doctor"], cwd=extract_dir)
    assert doctor.code == 0
    doctor_payload = json.loads(doctor.output)
    assert doctor_payload["collector_id"] == "package-test"
    assert doctor_payload["server_reachable"] is True
    assert calls == [("GET", "/api/policy")]

    calls.clear()
    result = run(["run-once"], cwd=extract_dir)
    assert result.code == 0
    assert calls == [
        ("POST", "/api/collectors/register"),
        ("POST", "/api/telemetry/ingest"),
        ("POST", "/api/collectors/package-test/heartbeat"),
        ("POST", "/api/collectors/package-test/heartbeat"),
        ("GET", "/api/collectors/package-test/diagnostics/next"),
    ]
    state = json.loads((extract_dir / "agent-observer.state.json").read_text(encoding="utf-8"))
    assert state["outbox"] == []
    assert state["cursor"]["last_sequence"] == 1
    assert state["raw_upload_enabled"] is True
    assert state["last_upload_at"]
    batch_items = uploaded_batches[0]["items"]
    assert len(batch_items) >= 2
    assert any("采集器完成一次本机链路自检" in item["summary"] for item in batch_items)
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
    monkeypatch.setenv("AGENT_OBSERVER_START_MAX_CYCLES", "2")
    start = run(["start"], cwd=extract_dir)
    start_payload = json.loads(start.output)
    assert start.code == 0
    assert start_payload["mode"] == "stopped"
    assert start_payload["running"] is False
    assert start_payload["cursor"]["last_sequence"] == 3
    assert calls.count(("POST", "/api/collectors/register")) == 1
    assert calls.count(("POST", "/api/telemetry/ingest")) == 2
    assert calls.count(("POST", "/api/collectors/package-test/heartbeat")) >= 4
    assert calls.count(("GET", "/api/collectors/package-test/diagnostics/next")) == 2
    assert any(item.get("raw_content") for batch in uploaded_batches[1:] for item in batch["items"])

    stop = json.loads(run(["stop"], cwd=extract_dir).output)
    assert stop["running"] is False


def test_packaged_collector_first_run_uses_download_raw_setting(tmp_path, monkeypatch):
    extract_dir = _prepare_packaged_collector(tmp_path, "unzipped-raw", raw_upload=True)

    calls: list[tuple[str, str]] = []
    uploaded_batches: list[dict[str, object]] = []
    _install_fake_transport(monkeypatch, calls, uploaded_batches)

    result = run(["run-once"], cwd=extract_dir)
    batch_items = uploaded_batches[0]["items"]
    prompt = next(item for item in batch_items if item["category"] == "codex_prompt")

    assert result.code == 0
    assert prompt["upload_raw"] is True
    assert prompt["raw_content"]
    assert prompt["projection"]["prompt_text"] == "请检查 Dashboard 为什么看不到原始 Prompt"
