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
            "protocol_version": "agent-observer-telemetry/v2",
            "agent_version": "0.2.0",
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


def test_register_rejects_stale_collector_version(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        try:
            register_collector(
                conn,
                {
                    "hostname": "workstation-a",
                    "windows_username": "dev-user",
                    "agent_type": "codex",
                    "protocol_version": "agent-observer-telemetry/v2",
                    "agent_version": "0.1.0",
                },
            )
        except ValueError as exc:
            error = str(exc)
        else:
            error = ""

    assert error == "unsupported_collector_version"


def test_existing_collector_heartbeat_rejects_unsupported_protocol(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        registered = register_collector(
            conn,
            {
                "collector_id": "collector-existing",
                "hostname": "workstation-a",
                "windows_username": "dev-user",
                "agent_type": "codex",
                "protocol_version": "agent-observer-telemetry/v2",
                "agent_version": "0.2.0",
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
                "protocol_version": "agent-observer-telemetry/v2",
                "agent_version": "0.2.0",
            },
        )
        collectors = list_collectors(conn)
        heartbeat(
            conn,
            registered["collector_id"],
            {
                "protocol_version": "agent-observer-telemetry/v2",
                "agent_version": "0.2.0",
                "source_status": "online",
                "reason_code": "start_running",
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
                "protocol_version": "agent-observer-telemetry/v2",
                "agent_version": "0.2.0",
            },
        )
        collector_id = registered["collector_id"]
        for status in SOURCE_STATUSES:
            heartbeat(
                conn,
                collector_id,
                {
                    "source_status": status,
                    "protocol_version": "agent-observer-telemetry/v2",
                    "agent_version": "0.2.0",
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
                "protocol_version": "agent-observer-telemetry/v2",
                "agent_version": "0.2.0",
            },
        )
        heartbeat(
            conn,
            registered["collector_id"],
            {
                "protocol_version": "agent-observer-telemetry/v2",
                "agent_version": "0.2.0",
                "source_status": "online",
                "reason_code": "start_running",
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
    assert package["agent_version"] == "0.2.0"
    assert package["protocol_version"] == "agent-observer-telemetry/v2"
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
    assert config["collection_interval_seconds"] == 15
    assert config["heartbeat_interval_seconds"] == 10
    assert config["max_events_per_cycle"] == 100
    assert config["upload_batch_size"] == 50
    assert config["evidence_mode"] == "structured_projection"
    assert "raw_upload_enabled" not in config
    assert config["agent_version"] == "0.2.0"
    assert config["protocol_version"] == "agent-observer-telemetry/v2"
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


def test_collector_ingest_creates_chinese_facts_and_story(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        facts = []
        batch = {
            "batch_id": "collector-package-test-1",
            "protocol_version": "agent-observer-telemetry/v2",
            "agent_version": "0.2.0",
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
