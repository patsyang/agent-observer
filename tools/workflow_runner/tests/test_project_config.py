import json
import sys

import pytest

from agentic_workflow.project_config import ProjectConfigError, load_project_config
from agentic_workflow.project_registry import project_status_payload, register_project


def write_project_config(project_root, payload):
    path = project_root / ".agentic" / "project.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def write_stack_contract(project_root):
    path = project_root / ".agentic" / "stack-contract.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "contract_id": "app-a-stack",
                "project_id": "app-a",
                "revision": 1,
                "status": "confirmed",
                "components": [
                    {
                        "component_id": "app",
                        "kind": "service",
                        "language": "python",
                        "framework": "pytest",
                        "root": ".",
                    }
                ],
                "commands": {"verify_all": [sys.executable + " -c \"print('verify')\""]},
            }
        ),
        encoding="utf-8",
    )


def valid_project_payload():
    return {
        "schema_version": 1,
        "project_id": "app-a",
        "project_name": "app-a",
        "adapter": {
            "id": "codex",
            "command": [sys.executable],
            "validated_at": "2026-06-15T00:00:00+00:00",
            "version": "test",
        },
        "verify": {"command": [sys.executable, "-c", "print('verify')"]},
    }


def test_load_project_config_reads_adapter_and_verify_command(tmp_path):
    project_root = tmp_path / "app-a"
    project_root.mkdir()
    write_project_config(project_root, valid_project_payload())

    config = load_project_config(project_root)

    assert config.adapter.adapter_id == "codex"
    assert config.adapter.command == (sys.executable,)
    assert config.verify.command == (sys.executable, "-c", "print('verify')")


def test_load_project_config_accepts_generic_cli_with_profile(tmp_path):
    project_root = tmp_path / "app-a"
    project_root.mkdir()
    payload = valid_project_payload()
    payload["adapter"] = {
        "id": "generic-cli",
        "command": ["qoderclicn"],
        "profile": ".agentic/runtime-adapters/qoder-cn.json",
    }
    write_project_config(project_root, payload)

    config = load_project_config(project_root)

    assert config.adapter.adapter_id == "generic-cli"
    assert config.adapter.command == ("qoderclicn",)
    assert config.adapter.profile.as_posix() == ".agentic/runtime-adapters/qoder-cn.json"


def test_load_project_config_accepts_opencode_generic_cli_profile(tmp_path):
    project_root = tmp_path / "app-a"
    project_root.mkdir()
    payload = valid_project_payload()
    payload["adapter"] = {
        "id": "generic-cli",
        "command": ["opencode"],
        "profile": ".agentic/runtime-adapters/opencode.json",
    }
    write_project_config(project_root, payload)

    config = load_project_config(project_root)

    assert config.adapter.adapter_id == "generic-cli"
    assert config.adapter.command == ("opencode",)
    assert config.adapter.profile.as_posix() == ".agentic/runtime-adapters/opencode.json"


def test_generic_cli_requires_profile(tmp_path):
    project_root = tmp_path / "app-a"
    project_root.mkdir()
    payload = valid_project_payload()
    payload["adapter"] = {"id": "generic-cli", "command": ["qoderclicn"]}
    write_project_config(project_root, payload)

    with pytest.raises(ProjectConfigError, match="adapter.profile is required"):
        load_project_config(project_root)


def test_runtime_profile_must_be_relative(tmp_path):
    project_root = tmp_path / "app-a"
    project_root.mkdir()
    payload = valid_project_payload()
    payload["adapter"] = {
        "id": "generic-cli",
        "command": ["qoderclicn"],
        "profile": str(tmp_path / "profile.json"),
    }
    write_project_config(project_root, payload)

    with pytest.raises(ProjectConfigError, match="adapter.profile must be relative"):
        load_project_config(project_root)


def test_runtime_profile_rejects_parent_traversal(tmp_path):
    project_root = tmp_path / "app-a"
    project_root.mkdir()
    payload = valid_project_payload()
    payload["adapter"] = {
        "id": "generic-cli",
        "command": ["qoderclicn"],
        "profile": "../profile.json",
    }
    write_project_config(project_root, payload)

    with pytest.raises(ProjectConfigError, match="adapter.profile must not contain"):
        load_project_config(project_root)


def test_load_project_config_requires_adapter_command(tmp_path):
    project_root = tmp_path / "app-a"
    project_root.mkdir()
    payload = valid_project_payload()
    payload["adapter"]["command"] = []
    write_project_config(project_root, payload)

    with pytest.raises(ProjectConfigError, match="adapter.command must be a non-empty array"):
        load_project_config(project_root)


def test_project_status_reports_adapter_health(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    project_root = tmp_path / "app-a"
    project_root.mkdir()
    write_project_config(project_root, valid_project_payload())
    write_stack_contract(project_root)
    register_project(name="app-a", root=project_root)

    payload, ok = project_status_payload("app-a")

    assert ok is True
    assert payload["project_config_status"] == "passed"
    assert payload["workspace_root"] == str(project_root / ".agentic" / "workspace")
    assert payload["project_config"]["adapter"]["command"] == [sys.executable]
    assert payload["adapter_health"]["ok"] is True
    assert payload["stack_contract_status"] == "passed"
