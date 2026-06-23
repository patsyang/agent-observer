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
from app.behavior_signals.service import list_signals
from source_payloads import default_sources


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


def _write_workbuddy_fixture(workbuddy_home):
    projects = workbuddy_home / "projects" / "demo"
    projects.mkdir(parents=True)
    records = [
        {
            "timestamp": "2026-06-18T10:04:00+00:00",
            "type": "message",
            "role": "user",
            "content": "请检查 WorkBuddy 采集",
            "sessionId": "session-workbuddy-package",
        },
        {
            "timestamp": "2026-06-18T10:05:00+00:00",
            "type": "function_call_result",
            "name": "shell",
            "output": "1 passed",
            "sessionId": "session-workbuddy-package",
        },
    ]
    (projects / "conversation.jsonl").write_text("\n".join(json.dumps(item) for item in records), encoding="utf-8")


def test_register_reuses_collector_and_returns_policy(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        payload = {
            "hostname": "workstation-a",
            "windows_username": "dev-user",
            "agent_type": "codex",
            "protocol_version": "agent-observer-telemetry/v3",
            "agent_version": "0.3.0",
            "sources": default_sources(),
        }
        first = register_collector(conn, payload)
        second = register_collector(conn, payload)
        collectors = list_collectors(conn)

    assert first["collector_id"] == second["collector_id"]
    assert first["effective_policy"]["policy_version"] == 1
    assert len(collectors) == 1
    assert collectors[0]["source_status"] == "online"
    assert collectors[0]["runtime_phase"] == "idle"
    assert collectors[0]["windows_username_hash"] != "dev-user"


def test_collectors_can_share_default_source_ids_without_stealing_rows(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        register_collector(
            conn,
            {
                "collector_id": "collector-a",
                "hostname": "workstation-a",
                "windows_username": "dev-user-a",
                "agent_type": "codex",
                "protocol_version": "agent-observer-telemetry/v3",
                "agent_version": "0.3.0",
                "sources": default_sources(),
            },
        )
        register_collector(
            conn,
            {
                "collector_id": "collector-b",
                "hostname": "workstation-b",
                "windows_username": "dev-user-b",
                "agent_type": "codex",
                "protocol_version": "agent-observer-telemetry/v3",
                "agent_version": "0.3.0",
                "sources": default_sources(),
            },
        )
        collectors = {item["collector_id"]: item for item in list_collectors(conn)}

    assert {source["source_id"] for source in collectors["collector-a"]["sources"]} == {"codex-local", "workbuddy-local"}
    assert {source["source_id"] for source in collectors["collector-b"]["sources"]} == {"codex-local", "workbuddy-local"}


def test_register_rejects_stale_collector_version(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        try:
            register_collector(
                conn,
                {
                    "hostname": "workstation-a",
                    "windows_username": "dev-user",
                    "agent_type": "codex",
                    "protocol_version": "agent-observer-telemetry/v3",
                    "agent_version": "0.1.0",
                    "sources": default_sources(),
                },
            )
        except ValueError as exc:
            error = str(exc)
        else:
            error = ""

    assert error == "unsupported_collector_version"


def test_register_requires_sources(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        try:
            register_collector(
                conn,
                {
                    "hostname": "workstation-a",
                    "windows_username": "dev-user",
                    "protocol_version": "agent-observer-telemetry/v3",
                    "agent_version": "0.3.0",
                },
            )
        except ValueError as exc:
            error = str(exc)
        else:
            error = ""

    assert error == "sources_required"


def test_register_rejects_partially_invalid_sources(tmp_path):
    sources = default_sources() + [{"source_id": "broken-source", "agent_type": "custom"}]
    with connect(tmp_path / "observer.sqlite") as conn:
        try:
            register_collector(
                conn,
                {
                    "hostname": "workstation-a",
                    "windows_username": "dev-user",
                    "protocol_version": "agent-observer-telemetry/v3",
                    "agent_version": "0.3.0",
                    "sources": sources,
                },
            )
        except ValueError as exc:
            error = str(exc)
        else:
            error = ""

    assert error == "sources_required"


def test_existing_collector_heartbeat_rejects_unsupported_protocol(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        registered = register_collector(
            conn,
            {
                "collector_id": "collector-existing",
                "hostname": "workstation-a",
                "windows_username": "dev-user",
                "agent_type": "codex",
                "protocol_version": "agent-observer-telemetry/v3",
                "agent_version": "0.3.0",
                "sources": default_sources(),
            },
        )
        try:
            heartbeat(
                conn,
                registered["collector_id"],
                {
                    "agent_version": "0.1.0",
                    "source_status": "online",
                    "reason_code": "start_running",
                    "sources": default_sources(),
                },
            )
        except ValueError as exc:
            error = str(exc)
        else:
            error = ""

    assert error == "unsupported_collector_protocol"


def test_collector_list_does_not_expose_raw_upload_override_state(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        update_effective_policy(
            conn,
            {
                "expected_version": 1,
                "enrichment_mode": "enabled",
            },
        )
        registered = register_collector(
            conn,
            {
                "collector_id": "raw-policy-collector",
                "hostname": "workstation-a",
                "windows_username": "dev-user",
                "agent_type": "codex",
                "protocol_version": "agent-observer-telemetry/v3",
                "agent_version": "0.3.0",
                "sources": default_sources(),
            },
        )
        collectors = list_collectors(conn)
        heartbeat(
            conn,
            registered["collector_id"],
            {
                "protocol_version": "agent-observer-telemetry/v3",
                "agent_version": "0.3.0",
                "source_status": "online",
                "reason_code": "start_running",
                "sources": default_sources(),
            },
        )

    assert "raw_upload_enabled" not in collectors[0]
    assert "raw_upload_override" not in collectors[0]
    assert "raw_upload_source" not in collectors[0]


def test_heartbeat_persists_all_source_status_reasons(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        registered = register_collector(
            conn,
            {
                "hostname": "workstation-a",
                "windows_username": "dev-user",
                "agent_type": "codex",
                "protocol_version": "agent-observer-telemetry/v3",
                "agent_version": "0.3.0",
                "sources": default_sources(),
            },
        )
        collector_id = registered["collector_id"]
        for status in SOURCE_STATUSES:
            heartbeat(
                conn,
                collector_id,
                {
                    "source_status": status,
                    "protocol_version": "agent-observer-telemetry/v3",
                    "agent_version": "0.3.0",
                    "reason_code": status,
                    "outbox_backlog": 2 if status == "outbox_backlog" else 0,
                    "sources": default_sources(),
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
                "protocol_version": "agent-observer-telemetry/v3",
                "agent_version": "0.3.0",
                "sources": default_sources(),
            },
        )
        heartbeat(
            conn,
            registered["collector_id"],
            {
                "protocol_version": "agent-observer-telemetry/v3",
                "agent_version": "0.3.0",
                "source_status": "online",
                "reason_code": "start_running",
                "sources": default_sources(),
            },
        )
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
    assert package["server_url"] == "http://127.0.0.1:8765"
    assert package["agent_version"] == "0.3.0"
    assert package["protocol_version"] == "agent-observer-telemetry/v3"
    with zipfile.ZipFile(package["path"]) as archive:
        names = set(archive.namelist())
        assert "agent-observer.cmd" in names
        assert "agent-observer.config.json" in archive.namelist()
        assert "app/collector_client/cli.py" in names
        assert "app/collector_client/content_dedup.py" in names
        assert "app/collector_client/runtime.py" in names
        assert "app/collector_client/source_reader.py" in names
        assert "app/collector_client/fact_mapper.py" in names
        assert "app/collector_client/version.py" in names
        source_text = "\n".join(
            archive.read(name).decode("utf-8")
            for name in names
            if name.startswith("app/collector_client/") and name.endswith(".py")
        )
        config = json.loads(archive.read("agent-observer.config.json"))
    assert "associated_units" not in source_text
    assert "attributed_units" not in source_text
    assert "usage_kind" not in source_text
    assert "additive" not in source_text
    assert config["server_url"] == "http://127.0.0.1:8765"
    assert config["collector_id"] == "windows-collector"
    assert config["history_window_days"] == 7
    assert config["collection_interval_seconds"] == 5
    assert config["heartbeat_interval_seconds"] == 10
    assert config["max_events_per_cycle"] == 500
    assert config["upload_batch_size"] == 100
    assert config["evidence_mode"] == "structured_projection"
    assert "raw_upload_enabled" not in config
    assert config["agent_version"] == "0.3.0"
    assert config["protocol_version"] == "agent-observer-telemetry/v3"
    assert {source["source_id"] for source in config["sources"]} == {"codex-local", "workbuddy-local"}
    assert "effective_policy" not in config
    assert "template_enabled" not in config
    assert "collection_policy" not in config
    assert "enrichment_policy" not in config


def test_package_server_url_can_be_overridden_for_e2e(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_OBSERVER_PUBLIC_BASE_URL", "http://127.0.0.1:8766/")
    with connect(tmp_path / "observer.sqlite") as conn:
        package = build_windows_package(conn, tmp_path / "packages")

    assert package["server_url"] == "http://127.0.0.1:8766"
    with zipfile.ZipFile(package["path"]) as archive:
        config = json.loads(archive.read("agent-observer.config.json"))
    assert config["server_url"] == "http://127.0.0.1:8766"


def test_packaged_collector_collects_codex_and_workbuddy_fixtures(tmp_path, monkeypatch):
    with connect(tmp_path / "observer.sqlite") as conn:
        package = build_windows_package(conn, tmp_path / "packages")
    extract_dir = tmp_path / "package"
    with zipfile.ZipFile(package["path"]) as archive:
        archive.extractall(extract_dir)
    codex_home = extract_dir / ".codex"
    workbuddy_home = extract_dir / ".workbuddy"
    _write_codex_fixture(codex_home)
    _write_workbuddy_fixture(workbuddy_home)
    config_path = extract_dir / "agent-observer.config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["state_path"] = "agent-observer.state.json"
    config["collector_id"] = "packaged-fixture"
    config["sources"][0]["root"] = str(codex_home)
    config["sources"][1]["root"] = str(workbuddy_home)
    config_path.write_text(json.dumps(config), encoding="utf-8")
    posts = []

    def fake_post(_server_url, path, payload):
        posts.append((path, payload))
        return {"effective_policy": {"raw_upload_mode": "always_on"}}

    monkeypatch.setattr("app.collector_client.runtime._post_json", fake_post)
    monkeypatch.setattr("app.collector_client.runtime._get_json", lambda *_args, **_kwargs: {"status": "none"})

    result = run(["run-once"], cwd=extract_dir)
    payload = json.loads(result.output)
    ingest_batches = [payload for path, payload in posts if path == "/api/telemetry/ingest"]

    assert result.code == 0
    assert payload["uploaded"] >= 4
    assert {batch["source_id"] for batch in ingest_batches} == {"codex-local", "workbuddy-local"}
    workbuddy_categories = {item["category"] for batch in ingest_batches if batch["source_id"] == "workbuddy-local" for item in batch["items"]}
    assert {"agent_prompt", "tool_result"} <= workbuddy_categories


def test_collector_ingest_creates_chinese_facts_and_signal(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        facts = []
        batch = {
            "batch_id": "collector-package-test-1",
            "protocol_version": "agent-observer-telemetry/v3",
            "agent_version": "0.3.0",
            "collector_id": "package-test",
            "source": "codex",
        "source_id": "codex-local",
        "agent_type": "codex",
        "source_kind": "codex_local",
            "cursor": "1",
            "items": facts,
        }
        from app.collector_client.telemetry import collect_facts

        codex_home = tmp_path / ".codex"
        _write_codex_fixture(codex_home)
        facts.extend(collect_facts("package-test", 1, "safe_probe", codex_home=codex_home))
        result = ingest_telemetry(conn, batch)
        signals = list_signals(conn, window="all")
        rows = conn.execute("select category, summary from observed_facts order by fact_id").fetchall()
        categories = {row["category"] for row in rows}
        summaries = [row["summary"] for row in rows]

    assert result["accepted"] >= 2
    assert "collector_health" not in categories
    assert "collector_source_status" not in categories
    assert any("工具执行失败" in summary for summary in summaries)
    assert signals["signals"]
    assert any(signal["signal_kind"] == "tool_execution_failure" for signal in signals["signals"])
