from __future__ import annotations

import json

import pytest

from app.collectors.service import (
    delete_collector,
    heartbeat,
    list_collectors,
    register_collector,
    update_collector_display_name,
    update_collector_raw_upload,
)
from app.db.connection import connect
from app.policy import get_effective_policy, recent_audit, update_effective_policy


def test_policy_update_increments_version_and_writes_fixed_account_audit(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        initial = get_effective_policy(conn)
        updated = update_effective_policy(
            conn,
            {
                "expected_version": initial["policy_version"],
                "template_enabled": False,
                "upload_raw": True,
                "collection_policy": "codex deterministic events only",
                "diagnostic_policy": "queue whitelist diagnostics when offline",
            },
        )
        audit = recent_audit(conn)

    assert updated["policy_version"] == initial["policy_version"] + 1
    assert updated["template_enabled"] is False
    assert updated["upload_raw"] is True
    assert audit["events"][0]["action"] == "policy_changed"
    assert audit["events"][0]["actor"] == "fixed-management-account"
    assert audit["events"][0]["metadata"] == {
        "after_version": 2,
        "before_version": 1,
        "reason_code": "operator_policy_update",
        "template_enabled": False,
        "upload_raw": True,
    }


def test_policy_update_requires_current_version_and_accepts_raw_text(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        with pytest.raises(ValueError, match="policy_version_conflict"):
            update_effective_policy(conn, {"expected_version": 99, "collection_policy": "codex only"})

        updated = update_effective_policy(
            conn,
            {
                "expected_version": 1,
                "collection_policy": "raw log prompt token collection",
                "diagnostic_policy": "whitelist only",
            },
        )

    assert updated["collection_policy"] == "raw log prompt token collection"


def test_online_collector_raw_upload_override_is_returned_on_heartbeat(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        registered = register_collector(
            conn,
            {
                "collector_id": "collector-raw",
                "display_name": "Collector raw",
                "hostname": "raw-host",
                "windows_username": "dev-user",
                "agent_type": "codex",
            },
        )
        heartbeat(conn, registered["collector_id"], {"source_status": "online", "reason_code": "start_running"})

        updated = update_collector_raw_upload(conn, registered["collector_id"], True)
        heartbeat_result = heartbeat(
            conn,
            registered["collector_id"],
            {"source_status": "online", "reason_code": "start_running"},
        )
        collector = list_collectors(conn)[0]

    assert updated["raw_upload_enabled"] is True
    assert updated["raw_upload_override"] is True
    assert heartbeat_result["effective_policy"]["upload_raw"] is True
    assert heartbeat_result["effective_policy"]["raw_upload_source"] == "collector_override"
    assert collector["raw_upload_enabled"] is True
    assert collector["raw_upload_override"] is True


def test_display_label_change_writes_fixed_account_audit(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        registered = register_collector(
            conn,
            {
                "hostname": "policy-host",
                "windows_username": "synthetic-user",
                "agent_type": "codex",
                "agent_version": "0.1.0",
            },
        )
        collector = update_collector_display_name(conn, registered["collector_id"], "Workbench collector")
        row = conn.execute("select * from audit_logs where action = 'display_label_changed'").fetchone()

    assert collector["display_name"] == "Workbench collector"
    assert row["actor"] == "fixed-management-account"
    assert json.loads(row["metadata_json"]) == {
        "after_label": "Workbench collector",
        "before_label": "policy-host",
        "reason_code": "operator_label_update",
    }


def test_delete_collector_removes_management_row_and_writes_audit(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        registered = register_collector(
            conn,
            {
                "collector_id": "stale-collector",
                "display_name": "Stale collector",
                "hostname": "stale-host",
                "windows_username": "synthetic-user",
                "agent_type": "codex",
                "agent_version": "0.1.0",
                "source_status": "offline",
                "reason_code": "heartbeat_stale",
            },
        )
        deleted = delete_collector(conn, registered["collector_id"])
        collectors = list_collectors(conn)
        row = conn.execute("select * from audit_logs where action = 'collector_removed'").fetchone()

    assert deleted == {
        "collector_id": "stale-collector",
        "removed": True,
        "reason_code": "operator_cleanup",
    }
    assert collectors == []
    assert row["actor"] == "fixed-management-account"
    assert json.loads(row["metadata_json"]) == {
        "before_label": "Stale collector",
        "reason_code": "operator_cleanup",
        "source_status": "offline",
    }
