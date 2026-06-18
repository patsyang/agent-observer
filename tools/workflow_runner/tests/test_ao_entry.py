import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def load_ao_module():
    src = Path(__file__).resolve().parents[1] / "src"
    sys.path.insert(0, str(src))
    from agentic_workflow import ao_entry

    return ao_entry


def test_build_alias_complete_reads_summary_and_changed_files(tmp_path: Path) -> None:
    ao = load_ao_module()
    summary = tmp_path / "summary.txt"
    changed = tmp_path / "changed.txt"
    summary.write_text("done", encoding="utf-8")
    changed.write_text("AGENTS.md\ncommands/ao-small.md\n", encoding="utf-8")
    args = SimpleNamespace(
        action="complete",
        run_id="run_123",
        goal="goal",
        goal_path=None,
        spec_path=None,
        plan_path=None,
        summary=None,
        summary_file=str(summary),
        changed_file=["README.md,package.json"],
        changed_files_file=str(changed),
        skip_verify=True,
    )

    command = ao.build_alias_args("small-change", args)

    assert command[:4] == ["complete", "--workflow", "small-change", "--run-id"]
    summary_index = command.index("--summary")
    assert command[summary_index : summary_index + 2] == ["--summary", "done"]
    assert command.count("--changed-file") == 4
    assert "AGENTS.md" in command
    assert "commands/ao-small.md" in command
    assert "--skip-verify" in command


def test_file_inputs_are_resolved_from_repo_root(tmp_path: Path, monkeypatch) -> None:
    ao = load_ao_module()
    fake_repo = tmp_path / "repo"
    monkeypatch.setattr(ao, "REPO_ROOT", fake_repo)
    summary = fake_repo / "output" / "tmp" / "ao-entry-summary-test.txt"
    changed = fake_repo / "output" / "tmp" / "ao-entry-changed-test.txt"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text("repo summary", encoding="utf-8")
    changed.write_text("AGENTS.md\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    args = SimpleNamespace(
        action="complete",
        run_id="run_123",
        goal="goal",
        goal_path=None,
        spec_path=None,
        plan_path=None,
        summary=None,
        summary_file="output/tmp/ao-entry-summary-test.txt",
        changed_file=None,
        changed_files_file="output/tmp/ao-entry-changed-test.txt",
        skip_verify=False,
    )

    command = ao.build_alias_args("small-change", args)

    assert "repo summary" in command
    assert "AGENTS.md" in command


def test_build_workflow_list_is_direct_command() -> None:
    ao = load_ao_module()
    args = SimpleNamespace(action="list")

    assert ao.build_workflow_args(args) == ["list"]


def test_build_workflow_status_uses_only_run_id() -> None:
    ao = load_ao_module()
    args = SimpleNamespace(action="status", run_id="run_123")

    assert ao.build_workflow_args(args) == ["status", "--run-id", "run_123"]


def test_build_workflow_validate_maps_workflow_name() -> None:
    ao = load_ao_module()
    args = SimpleNamespace(action="validate", workflow="spec-driven")

    assert ao.build_workflow_args(args) == ["validate", "--workflow", "spec-driven"]


def test_build_workflow_execute_maps_adapter_profile() -> None:
    ao = load_ao_module()
    args = SimpleNamespace(
        action="execute",
        workflow="small-change",
        scope=None,
        project=None,
        project_root=None,
        run_id=None,
        goal="goal",
        goal_path=None,
        prd_path=None,
        source_spec_path=None,
        spec_path=None,
        plan_path=None,
        adapter="generic-cli",
        adapter_command=["codex"],
        adapter_profile=".agentic/runtime-adapters/codex.json",
        timeout_seconds=12,
        skip_verify=True,
    )

    command = ao.build_workflow_args(args)

    assert command == [
        "execute",
        "--workflow",
        "small-change",
        "--goal",
        "goal",
        "--adapter",
        "generic-cli",
        "--adapter-command",
        "codex",
        "--adapter-profile",
        ".agentic/runtime-adapters/codex.json",
        "--timeout-seconds",
        "12",
        "--skip-verify",
    ]


def test_build_ao_infra_alias_targets_control_plane_workflow() -> None:
    ao = load_ao_module()
    args = SimpleNamespace(
        action="prepare",
        run_id=None,
        goal="update control plane",
        goal_path=None,
        spec_path=None,
        plan_path=None,
    )

    command = ao.build_alias_args("ao-infra", args)

    assert command[:4] == ["prepare", "--workflow", "control-plane-change", "--goal"]


def test_build_cli_adapter_args_maps_to_generic_cli_execute() -> None:
    ao = load_ao_module()
    args = SimpleNamespace(
        workflow="small-change",
        scope=None,
        project=None,
        project_root=None,
        run_id=None,
        goal="goal",
        goal_path=None,
        prd_path=None,
        source_spec_path=None,
        spec_path=None,
        plan_path=None,
        runtime_executable="qoderclicn",
        runtime_profile=".agentic/runtime-adapters/qoder-cn.json",
        timeout_seconds=99,
        skip_verify=True,
    )

    command = ao.build_cli_adapter_args(args)

    assert command == [
        "execute",
        "--adapter",
        "generic-cli",
        "--adapter-command",
        "qoderclicn",
        "--adapter-profile",
        ".agentic/runtime-adapters/qoder-cn.json",
        "--workflow",
        "small-change",
        "--goal",
        "goal",
        "--timeout-seconds",
        "99",
        "--skip-verify",
    ]


def test_build_spec_driven_defaults_project_name_to_registered_project(monkeypatch) -> None:
    ao = load_ao_module()
    args = SimpleNamespace(
        action="run",
        project_name="app-a",
        prd="D:\\workspace\\prd\\app-a.md",
        spec=None,
        project=None,
        project_root=None,
        scope=None,
        run_id=None,
        goal=None,
        goal_path=None,
        plan_path=None,

        skip_verify=False,
        no_worktree=False,
    )

    command = ao.build_spec_driven_args(args)

    assert "--project" in command
    assert "app-a" in command
    assert "--prd-path" in command
    assert "D:\\workspace\\prd\\app-a.md" in command


def test_build_spec_driven_plan_requires_project_name() -> None:
    ao = load_ao_module()
    args = SimpleNamespace(
        action="run",
        project_name=None,
        prd=None,
        spec=None,
        project=None,
        project_root=None,
        scope=None,
        run_id=None,
        goal=None,
        goal_path=None,
        spec_path=None,
        plan_path="D:\\workspace\\plans\\app-a-plan.md",

        skip_verify=False,
        no_worktree=False,
    )

    with pytest.raises(SystemExit, match="--project-name or --project is required"):
        ao.build_spec_driven_args(args)


def test_build_spec_driven_plan_rejects_project_root_without_project_name() -> None:
    ao = load_ao_module()
    args = SimpleNamespace(
        action="run",
        project_name=None,
        prd=None,
        spec=None,
        project=None,
        project_root="D:\\workspace\\apps\\app-a",
        scope=None,
        run_id=None,
        goal=None,
        goal_path=None,
        spec_path=None,
        plan_path="D:\\workspace\\plans\\app-a-plan.md",

        skip_verify=False,
        no_worktree=False,
    )

    with pytest.raises(SystemExit, match="--project-name or --project is required"):
        ao.build_spec_driven_args(args)


def test_build_spec_driven_plan_maps_project_name_to_project() -> None:
    ao = load_ao_module()
    args = SimpleNamespace(
        action="run",
        project_name="app-a",
        prd=None,
        spec=None,
        project=None,
        project_root=None,
        scope=None,
        run_id=None,
        goal=None,
        goal_path=None,
        spec_path=None,
        plan_path="D:\\workspace\\plans\\app-a-plan.md",

        skip_verify=False,
        no_worktree=False,
    )

    command = ao.build_spec_driven_args(args)

    assert command[:3] == ["run", "--workflow", "spec-driven"]
    assert command[command.index("--project") + 1] == "app-a"
    assert command[command.index("--plan-path") + 1] == "D:\\workspace\\plans\\app-a-plan.md"


def test_build_spec_driven_existing_spec_path_maps_project_name_to_project() -> None:
    ao = load_ao_module()
    args = SimpleNamespace(
        action="run",
        project_name="app-a",
        prd=None,
        spec=None,
        project=None,
        project_root=None,
        scope=None,
        run_id=None,
        goal=None,
        goal_path=None,
        spec_path="D:\\workspace\\apps\\app-a\\specs\\001-feature\\spec.md",
        plan_path=None,

        skip_verify=False,
        no_worktree=False,
    )

    command = ao.build_spec_driven_args(args)

    assert command[:3] == ["run", "--workflow", "spec-driven"]
    assert command[command.index("--project") + 1] == "app-a"
    assert command[command.index("--spec-path") + 1].endswith("001-feature\\spec.md")


def test_build_spec_driven_resume_uses_run_id() -> None:
    ao = load_ao_module()
    args = SimpleNamespace(action="resume", run_id="run_failed")

    command = ao.build_spec_driven_args(args)

    assert command == ["resume", "--run-id", "run_failed"]


def test_project_models_dispatch_hides_internal_models(capsys) -> None:
    ao = load_ao_module()
    args = SimpleNamespace(project_action="models")

    assert ao.run_project_registry_command(args) == 0

    payload = json.loads(capsys.readouterr().out)
    model_ids = [model["id"] for model in payload["models"]]
    assert "codex-gpt-5" in model_ids
    assert "qoder-cn-qwen" in model_ids
    assert "opencode-default" in model_ids
    assert "codex-gpt-5-codex-adapter" not in model_ids


def test_project_stack_profiles_dispatch_lists_default_profile(capsys) -> None:
    ao = load_ao_module()
    args = SimpleNamespace(project_action="stack", stack_action="profiles")

    assert ao.run_project_registry_command(args) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["default_profile"] == "default-web-app"
    default = next(profile for profile in payload["profiles"] if profile["id"] == "default-web-app")
    assert default["technology_stack"]["backend"] == "Python + FastAPI + pytest + uv/pip"


def test_ao_script_emits_utf8_chinese_json_when_captured() -> None:
    repo_root = Path(__file__).resolve().parents[3]

    result = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "ao.py"), "project", "stack", "profiles"],
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    stdout = result.stdout.decode("utf-8")
    assert "默认 Web 应用" in stdout
    assert "无独立客户端" in stdout


def test_project_register_dispatch_requires_model_before_creating_missing_root(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    ao = load_ao_module()
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    project_root = tmp_path / "apps" / "app-a"
    args = SimpleNamespace(
        project_action="register",
        name="app-a",
        root=str(project_root),
        workspace_root=None,
        model=None,
        stack_profile=None,
    )

    assert ao.run_project_registry_command(args) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "NEEDS_MODEL_SELECTION"
    assert any(model["id"] == "codex-gpt-5" for model in payload["models"])
    assert not project_root.exists()
    assert not (tmp_path / "home" / "registry.json").exists()


def test_project_register_dispatch_uses_default_stack_profile_with_model(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    ao = load_ao_module()
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    project_root = tmp_path / "apps" / "app-a"
    project_root.mkdir(parents=True)
    args = SimpleNamespace(
        project_action="register",
        name="app-a",
        root=str(project_root),
        workspace_root=None,
        model="codex-gpt-5",
        stack_profile=None,
    )

    assert ao.run_project_registry_command(args) == 0

    payload = json.loads(capsys.readouterr().out)
    config = json.loads((project_root / ".agentic" / "project.json").read_text(encoding="utf-8"))
    contract = json.loads(
        (project_root / ".agentic" / "stack-contract.json").read_text(encoding="utf-8")
    )
    registry = json.loads((tmp_path / "home" / "registry.json").read_text(encoding="utf-8"))
    assert payload["status"] == "REGISTERED_READY"
    assert payload["stack"]["profile_id"] == "default-web-app"
    assert config["model"]["id"] == "codex-gpt-5"
    assert contract["profile_id"] == "default-web-app"
    assert "app-a" in registry["projects"]


def test_project_register_dispatch_generates_stack_contract_with_profile(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    ao = load_ao_module()
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    project_root = tmp_path / "apps" / "app-a"
    project_root.mkdir(parents=True)
    args = SimpleNamespace(
        project_action="register",
        name="app-a",
        root=str(project_root),
        workspace_root=None,
        model="codex-gpt-5",
        stack_profile="default-web-app",
    )

    assert ao.run_project_registry_command(args) == 0

    payload = json.loads(capsys.readouterr().out)
    config = json.loads((project_root / ".agentic" / "project.json").read_text(encoding="utf-8"))
    contract = json.loads(
        (project_root / ".agentic" / "stack-contract.json").read_text(encoding="utf-8")
    )
    registry = json.loads((tmp_path / "home" / "registry.json").read_text(encoding="utf-8"))
    assert payload["stack"]["profile_id"] == "default-web-app"
    assert payload["readiness"]["stack_contract_status"] == "passed"
    assert config["model"]["id"] == "codex-gpt-5"
    assert contract["technology_stack"]["database"] == "SQLite"
    assert "app-a" in registry["projects"]


def test_agentic_check_returns_nonzero_for_drift(tmp_path: Path, monkeypatch) -> None:
    ao = load_ao_module()
    output = tmp_path / "plan.json"
    output.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "path": "AGENTS.md",
                        "status": "conflict",
                        "current_sha256": "a",
                        "baseline_sha256": "b",
                        "infra_sha256": "c",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    def fake_run_agentic_capture(_args):
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(ao, "run_agentic_capture", fake_run_agentic_capture)
    args = SimpleNamespace(
        project_root=str(tmp_path),
        infra_root=str(tmp_path),
        output=str(output),
    )

    assert ao.run_agentic_check(args) == 1


def test_agentic_check_passes_when_all_items_unchanged(tmp_path: Path, monkeypatch) -> None:
    ao = load_ao_module()
    output = tmp_path / "plan.json"
    output.write_text(
        json.dumps({"items": [{"path": "AGENTS.md", "status": "unchanged"}]}),
        encoding="utf-8",
    )

    def fake_run_agentic_capture(_args):
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(ao, "run_agentic_capture", fake_run_agentic_capture)
    args = SimpleNamespace(
        project_root=str(tmp_path),
        infra_root=str(tmp_path),
        output=str(output),
    )

    assert ao.run_agentic_check(args) == 0
