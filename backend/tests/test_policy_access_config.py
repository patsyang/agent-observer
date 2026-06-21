from __future__ import annotations

import json

import pytest

from app.collectors.service import (
    delete_collector,
    heartbeat,
    list_collectors,
    register_collector,
    update_collector_display_name,
)
from app.db.connection import connect
from app.policy import get_effective_policy, recent_audit, update_effective_policy

CLIENT_PROTOCOL = {
    "protocol_version": "agent-observer-telemetry/v2",
    "agent_version": "0.2.0",
}


def test_policy_update_increments_version_and_writes_fixed_account_audit(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        initial = get_effective_policy(conn)
        updated = update_effective_policy(
            conn,
            {
                "expected_version": initial["policy_version"],
                "enrichment_mode": "disabled",
            },
        )
        audit = recent_audit(conn)

    assert updated["policy_version"] == initial["policy_version"] + 1
    assert updated["raw_upload_mode"] == "always_on"
    assert updated["enrichment_mode"] == "disabled"
    assert audit["events"][0]["action"] == "policy_changed"
    assert audit["events"][0]["actor"] == "fixed-management-account"
    assert audit["events"][0]["metadata"] == {
        "after_version": 2,
        "before_version": 1,
        "enrichment_mode": "disabled",
        "reason_code": "operator_policy_update",
        "raw_upload_mode": "always_on",
    }


def test_policy_update_requires_current_version_and_rejects_unknown_fields(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        with pytest.raises(ValueError, match="policy_version_conflict"):
            update_effective_policy(conn, {"expected_version": 99})

        with pytest.raises(ValueError, match="unsupported_enrichment_mode"):
            update_effective_policy(conn, {"expected_version": 1, "enrichment_mode": "custom text"})

        with pytest.raises(ValueError, match="unsupported_policy_field"):
            update_effective_policy(conn, {"expected_version": 1, "unknown_policy": False, "enrichment_mode": "enabled"})



def test_collector_policy_no_longer_exposes_raw_upload_override_state(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        registered = register_collector(
            conn,
            {
                "collector_id": "collector-raw",
                "display_name": "Collector raw",
                "hostname": "raw-host",
                "windows_username": "dev-user",
                "agent_type": "codex",
                **CLIENT_PROTOCOL,
            },
        )
        heartbeat(
            conn,
            registered["collector_id"],
            {**CLIENT_PROTOCOL, "source_status": "online", "reason_code": "start_running"},
        )
        heartbeat_result = heartbeat(
            conn,
            registered["collector_id"],
            {**CLIENT_PROTOCOL, "source_status": "online", "reason_code": "start_running"},
        )
        collector = list_collectors(conn)[0]

    assert heartbeat_result["effective_policy"]["raw_upload_mode"] == "always_on"
    assert "raw_upload_enabled" not in heartbeat_result["effective_policy"]
    assert "raw_upload_source" not in heartbeat_result["effective_policy"]
    assert "raw_upload_enabled" not in collector
    assert "raw_upload_override" not in collector


def test_display_label_change_writes_fixed_account_audit(tmp_path):
    with connect(tmp_path / "observer.sqlite") as conn:
        registered = register_collector(
            conn,
            {
                "hostname": "policy-host",
                "windows_username": "synthetic-user",
                "agent_type": "codex",
                **CLIENT_PROTOCOL,
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
                **CLIENT_PROTOCOL,
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
