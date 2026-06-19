from __future__ import annotations

import json
import subprocess
import zipfile

from app.collector_client.cli import run
from app.collectors.service import heartbeat, list_collectors, register_collector
from app.db.connection import SOURCE_STATUSES, connect
from app.ingest.service import ingest_telemetry
from app.package.builder import build_windows_package
from app.policy import update_effective_policy
from app.stories.service import list_stories


def _write_codex_fixture(codex_home):
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    records = [
        {
            "timestamp": "2026-06-18T10:00:00+00:00",
            "type": "tool_result",
            "tool": "shell",
            "exit_code": 1,
            "phase": "test",
            "conversation_id": "conversation-package",
            "session_id": "session-package",
            "summary": "test command failed",
        },
        {
            "timestamp": "2026-06-18T10:02:00+00:00",
            "type": "usage",
            "total_tokens": 120,
            "activity_tags": ["test_run"],
            "conversation_id": "conversation-package",
            "session_id": "session-package",
        },
        {
            "timestamp": "2026-06-18T10:03:00+00:00",
            "type": "message",
            "role": "user",
            "content": "请检查 Dashboard 为什么看不到原始 Prompt",
            "conversation_id": "conversation-package",
            "session_id": "session-package",
        },
    ]
    (sessions / "session-package.jsonl").write_text("\n".join(json.dumps(item) for item in records), encoding="utf-8")


def test_register_reuses_collector_and_returns_policy(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        payload = {
            "hostname": "workstation-a",
            "windows_username": "dev-user",
            "agent_type": "codex",
            "agent_version": "0.1.0",
        }
        first = register_collector(conn, payload)
        second = register_collector(conn, payload)
        collectors = list_collectors(conn)

    assert first["collector_id"] == second["collector_id"]
    assert first["effective_policy"]["policy_version"] == 1
    assert len(collectors) == 1
    assert collectors[0]["source_status"] == "policy_not_fetched"
    assert collectors[0]["windows_username_hash"] != "dev-user"


def test_collector_list_reports_effective_raw_upload_policy(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        update_effective_policy(
            conn,
            {
                "expected_version": 1,
                "template_enabled": True,
                "upload_raw": True,
                "collection_policy": "collect codex source with raw evidence",
                "diagnostic_policy": "whitelist diagnostics",
            },
        )
        registered = register_collector(
            conn,
            {
                "collector_id": "raw-policy-collector",
                "hostname": "workstation-a",
                "windows_username": "dev-user",
                "agent_type": "codex",
            },
        )
        collectors = list_collectors(conn)
        heartbeat(conn, registered["collector_id"], {"source_status": "online", "reason_code": "start_running"})
        from app.collectors.service import update_collector_raw_upload

        updated = update_collector_raw_upload(conn, registered["collector_id"], False)

    assert collectors[0]["raw_upload_enabled"] is True
    assert collectors[0]["raw_upload_override"] is False
    assert collectors[0]["raw_upload_source"] == "global_policy"
    assert updated["raw_upload_enabled"] is False
    assert updated["raw_upload_override"] is True
    assert updated["raw_upload_source"] == "collector_override"


def test_heartbeat_persists_all_source_status_reasons(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        registered = register_collector(
            conn,
            {
                "hostname": "workstation-a",
                "windows_username": "dev-user",
                "agent_type": "codex",
            },
        )
        collector_id = registered["collector_id"]
        for status in SOURCE_STATUSES:
            heartbeat(
                conn,
                collector_id,
                {
                    "source_status": status,
                    "reason_code": status,
                    "outbox_backlog": 2 if status == "outbox_backlog" else 0,
                },
            )
            current = list_collectors(conn)[0]
            assert current["source_status"] == status
            assert current["reason_code"] == status


def test_stale_heartbeat_is_reported_offline_without_deleting_collector(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        registered = register_collector(
            conn,
            {
                "collector_id": "stale-collector",
                "hostname": "workstation-a",
                "windows_username": "dev-user",
                "agent_type": "codex",
            },
        )
        heartbeat(conn, registered["collector_id"], {"source_status": "online", "reason_code": "start_running"})
        conn.execute(
            "update collectors set last_heartbeat_at = '2026-06-18T00:00:00+00:00' where collector_id = ?",
            (registered["collector_id"],),
        )
        conn.commit()
        collectors = list_collectors(conn)

    assert collectors[0]["collector_id"] == "stale-collector"
    assert collectors[0]["source_status"] == "offline"
    assert collectors[0]["reason_code"] == "heartbeat_stale"


def test_package_contains_adjacent_config_with_policy(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        package = build_windows_package(conn, tmp_path / "packages")

    assert package["filename"] == "agent-observer-windows.zip"
    assert package["sha256"]
    with zipfile.ZipFile(package["path"]) as archive:
        names = set(archive.namelist())
        assert "agent-observer.cmd" in names
        assert "agent-observer.config.json" in archive.namelist()
        assert "app/collector_client/cli.py" in names
        config = json.loads(archive.read("agent-observer.config.json"))
    assert config["server_url"] == "http://127.0.0.1:8765"
    assert config["collector_id"] == "windows-collector"
    assert config["history_window_days"] == 7
    assert config["max_events_per_cycle"] == 500
    assert config["evidence_mode"] == "structured_projection"
    assert config["raw_upload_enabled"] is False
    assert config["effective_policy"]["policy_version"] == 1


def test_collector_ingest_creates_chinese_facts_and_story(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        facts = []
        batch = {
            "batch_id": "collector-package-test-1",
            "collector_id": "package-test",
            "source": "codex",
            "cursor": "1",
            "items": facts,
        }
        from app.collector_client.telemetry import collect_facts

        codex_home = tmp_path / ".codex"
        _write_codex_fixture(codex_home)
        facts.extend(collect_facts("package-test", 1, "safe_probe", codex_home=codex_home))
        result = ingest_telemetry(conn, batch)
        stories = list_stories(conn)
        summaries = [row["summary"] for row in conn.execute("select summary from observed_facts order by fact_id").fetchall()]

    assert result["accepted"] >= 2
    assert any("采集器完成一次本机链路自检" in summary for summary in summaries)
    assert any("错误指纹" in summary for summary in summaries)
    assert stories["stories"]
    assert any("错误指纹" in story["conclusion"] for story in stories["stories"])


def test_packaged_collector_status_doctor_and_run_once_paths(tmp_path, monkeypatch):
    package_path = tmp_path / "agent-observer-windows.zip"
    with connect(tmp_path / "observer.sqlite") as conn:
        build_windows_package(conn, tmp_path)

    extract_dir = tmp_path / "unzipped"
    with zipfile.ZipFile(package_path) as archive:
        archive.extractall(extract_dir)

    config_path = extract_dir / "agent-observer.config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["collector_id"] = "package-test"
    config["collection_interval_seconds"] = 0
    config["codex_home"] = str(extract_dir / ".codex")
    config_path.write_text(json.dumps(config), encoding="utf-8")
    _write_codex_fixture(extract_dir / ".codex")

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
    assert status_payload["cursor"]["last_sequence"] == 0

    calls: list[tuple[str, str]] = []

    uploaded_batches: list[dict[str, object]] = []

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

    monkeypatch.setattr("app.collector_client.cli._post_json", fake_post)
    monkeypatch.setattr("app.collector_client.cli._get_json", fake_get)

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
    assert status_after_once["cursor"]["last_sequence"] == 1

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
    assert calls == [
        ("POST", "/api/collectors/register"),
        ("POST", "/api/telemetry/ingest"),
        ("POST", "/api/collectors/package-test/heartbeat"),
        ("GET", "/api/collectors/package-test/diagnostics/next"),
        ("POST", "/api/collectors/register"),
        ("POST", "/api/telemetry/ingest"),
        ("POST", "/api/collectors/package-test/heartbeat"),
        ("GET", "/api/collectors/package-test/diagnostics/next"),
    ]
    assert any(item.get("raw_content") for batch in uploaded_batches[1:] for item in batch["items"])

    stop = json.loads(run(["stop"], cwd=extract_dir).output)
    assert stop["running"] is False


def test_packaged_collector_first_run_uses_download_raw_setting(tmp_path, monkeypatch):
    package_path = tmp_path / "agent-observer-windows.zip"
    with connect(tmp_path / "observer.sqlite") as conn:
        build_windows_package(conn, tmp_path)

    extract_dir = tmp_path / "unzipped-raw"
    with zipfile.ZipFile(package_path) as archive:
        archive.extractall(extract_dir)

    config_path = extract_dir / "agent-observer.config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["collector_id"] = "package-raw-test"
    config["codex_home"] = str(extract_dir / ".codex")
    config["raw_upload_enabled"] = True
    config["effective_policy"]["upload_raw"] = True
    config_path.write_text(json.dumps(config), encoding="utf-8")
    _write_codex_fixture(extract_dir / ".codex")

    uploaded_batches: list[dict[str, object]] = []

    def fake_post(_server_url: str, path: str, payload: dict[str, object]) -> dict[str, object]:
        if path == "/api/telemetry/ingest":
            uploaded_batches.append(payload)
        return {"status": "ok", "effective_policy": {"upload_raw": True, "raw_upload_source": "global_policy"}}

    def fake_get(_server_url: str, _path: str) -> dict[str, object]:
        return {"status": "none"}

    monkeypatch.setattr("app.collector_client.cli._post_json", fake_post)
    monkeypatch.setattr("app.collector_client.cli._get_json", fake_get)

    result = run(["run-once"], cwd=extract_dir)
    batch_items = uploaded_batches[0]["items"]
    prompt = next(item for item in batch_items if item["category"] == "codex_prompt")

    assert result.code == 0
    assert prompt["upload_raw"] is True
    assert prompt["raw_content"]
    assert prompt["projection"]["prompt_text"] == "请检查 Dashboard 为什么看不到原始 Prompt"
