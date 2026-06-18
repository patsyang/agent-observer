import json
import subprocess
import sys
from pathlib import Path

import pytest

from agentic_workflow.e2e_runner import cleanup_run, read_run_status, resume_run, run_e2e_workflow
from agentic_workflow.models import WorkflowInput
from agentic_workflow.project_config import ProjectConfigError
from agentic_workflow.project_onboarding import (
    NeedsModelSelection,
    models_payload,
    register_project_onboarding,
    stack_profiles_payload,
)
from agentic_workflow.project_registry import (
    ProjectRegistryError,
    get_project,
    rebind_project,
    register_project,
)
from agentic_workflow.runner import complete_run, create_run_context, prepare_run


def write_definition(repo_root, name="small-change", verify_policy="targeted"):
    definition_dir = repo_root / ".agentic" / "workflow" / "definitions"
    definition_dir.mkdir(parents=True)
    (definition_dir / f"{name}.json").write_text(
        json.dumps(
            {
                "name": name,
                "title": "小改动",
                "adapter": "local-governed",
                "contract_path": ".agentic/workflow/small-change.md",
                "primary_inputs": ["goal", "goal_path"],
                "stages": ["implement", "verify", "report"],
                "verify_policy": verify_policy,
            }
        ),
        encoding="utf-8",
    )


def write_node_definition(repo_root, name="small-change", worktree=False):
    definition_dir = repo_root / ".agentic" / "workflow" / "definitions"
    definition_dir.mkdir(parents=True)
    (definition_dir / f"{name}.json").write_text(
        json.dumps(
            {
                "name": name,
                "title": "E2E 小改动",
                "adapter": "local-governed",
                "contract_path": ".agentic/workflow/small-change.md",
                "primary_inputs": ["goal", "goal_path"],
                "stages": ["scope-resolve", "execute", "review", "report"],
                "verify_policy": "targeted",
                "worktree": worktree,
                "nodes": [
                    {
                        "id": "execute",
                        "required_artifacts": ["implementation.md", "changed-files.txt"],
                    },
                    {"id": "review", "required_artifacts": ["review.md"]},
                ],
            }
        ),
        encoding="utf-8",
    )


def write_project_config(
    project_root,
    *,
    adapter_id="codex",
    adapter_command=None,
    adapter_profile=None,
    verify_command=None,
    runtime=None,
):
    adapter = {
        "id": adapter_id,
        "command": adapter_command or [sys.executable, "-c", "print('noop')"],
    }
    if adapter_profile:
        adapter["profile"] = adapter_profile
    payload = {
        "schema_version": 1,
        "project_id": project_root.name,
        "project_name": project_root.name,
        "adapter": adapter,
        "verify": {
            "command": verify_command or [sys.executable, "-c", "print('verify')"],
        },
    }
    if runtime is not None:
        payload["runtime"] = runtime
    config_dir = project_root / ".agentic"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "project.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    write_stack_contract(project_root)


def write_stack_contract(project_root):
    config_dir = project_root / ".agentic"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "stack-contract.json").write_text(
        json.dumps(
            {
                "contract_id": f"{project_root.name}-stack",
                "project_id": project_root.name,
                "revision": 1,
                "status": "confirmed",
                "components": [
                    {
                        "component_id": "app",
                        "kind": "service",
                        "language": "python",
                        "framework": "pytest",
                        "root": ".",
                        "package_manager": "pip",
                    }
                ],
                "commands": {
                    "verify_all": ["verify"],
                },
            }
        ),
        encoding="utf-8",
    )


def write_stack_artifacts(context, *, command="verify", include_command=True):
    ref = context.stack_contract_ref.to_dict()
    artifacts = context.run_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (context.run_dir / "logs").mkdir(parents=True, exist_ok=True)
    (context.run_dir / "logs" / "verify.txt").write_text("ok", encoding="utf-8")
    (artifacts / "acceptance-matrix.json").write_text(
        json.dumps(
            {
                "stack_contract_ref": ref,
                "acceptance": [
                    {
                        "acceptance_id": "A01",
                        "story_id": "S1",
                        "result": "PASS",
                        "evidence": [
                            {
                                "type": "command",
                                "command": command,
                                "exit_code": 0,
                                "log_path": "logs/verify.txt",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (artifacts / "component-evidence.json").write_text(
        json.dumps(
            {
                "stack_contract_ref": ref,
                "components": [{"component_id": "app", "evidence": ["implementation.md"]}],
            }
        ),
        encoding="utf-8",
    )
    commands = []
    if include_command:
        commands.append({"name": "verify_all", "command": command, "result": "PASS"})
    (artifacts / "command-coverage.json").write_text(
        json.dumps({"stack_contract_ref": ref, "commands": commands}),
        encoding="utf-8",
    )


def write_artifact_provider(path):
    path.write_text(
        "\n".join(
            [
                "import json, os",
                "from pathlib import Path",
                "artifacts = Path(os.environ['AO_ARTIFACTS_DIR'])",
                "for name in json.loads(os.environ.get('AO_REQUIRED_ARTIFACTS', '[]')):",
                "    target = artifacts / name",
                "    body = '{}' if name.endswith('.json') else f'# {name}\\n'",
                "    target.write_text(body, encoding='utf-8')",
                "print('COMPLETE')",
            ]
        ),
        encoding="utf-8",
    )


def write_fake_codex(path):
    path.write_text(
        "\n".join(
            [
                "import json, os, sys",
                "from pathlib import Path",
                "argv = sys.argv[1:]",
                "log = Path(os.environ['FAKE_CODEX_ARGV_LOG'])",
                "log.parent.mkdir(parents=True, exist_ok=True)",
                "with log.open('a', encoding='utf-8') as handle:",
                "    handle.write(json.dumps(argv, ensure_ascii=False) + '\\n')",
                "if not argv or argv[0] != 'exec':",
                "    print('missing codex exec', file=sys.stderr)",
                "    sys.exit(11)",
                "if '--cd' not in argv or '--output-last-message' not in argv:",
                "    print('missing codex execution flags', file=sys.stderr)",
                "    sys.exit(12)",
                "final_message = Path(argv[argv.index('--output-last-message') + 1])",
                "artifacts = Path(os.environ['AO_ARTIFACTS_DIR'])",
                "run_dir = Path(os.environ['AO_RUN_DIR'])",
                "for name in json.loads(os.environ.get('AO_REQUIRED_ARTIFACTS', '[]')):",
                "    target = artifacts / name",
                "    body = '{}' if name.endswith('.json') else f'# {name}\\n'",
                "    target.write_text(body, encoding='utf-8')",
                "if os.environ.get('AO_STACK_CONTRACT_HASH') and os.environ.get('AO_NODE_ID') in {'review', 'acceptance-matrix'}:",
                "    ref = {'contract_id': os.environ['AO_STACK_CONTRACT_ID'], 'revision': int(os.environ['AO_STACK_CONTRACT_REVISION']), 'hash': os.environ['AO_STACK_CONTRACT_HASH']}",
                "    (run_dir / 'logs').mkdir(exist_ok=True)",
                "    (run_dir / 'logs' / 'verify.txt').write_text('ok', encoding='utf-8')",
                "    matrix = {'stack_contract_ref': ref, 'acceptance': [{'acceptance_id': 'A01', 'story_id': 'S1', 'result': 'PASS', 'evidence': [{'type': 'command', 'command': 'verify', 'exit_code': 0, 'log_path': 'logs/verify.txt'}]}]}",
                "    components = {'stack_contract_ref': ref, 'components': [{'component_id': 'app', 'evidence': ['implementation.md']}]}",
                "    coverage = {'stack_contract_ref': ref, 'commands': [{'name': 'verify_all', 'command': 'verify', 'result': 'PASS'}]}",
                "    (artifacts / 'acceptance-matrix.json').write_text(json.dumps(matrix), encoding='utf-8')",
                "    (artifacts / 'component-evidence.json').write_text(json.dumps(components), encoding='utf-8')",
                "    (artifacts / 'command-coverage.json').write_text(json.dumps(coverage), encoding='utf-8')",
                "final_message.write_text('COMPLETE', encoding='utf-8')",
                "print('COMPLETE')",
            ]
        ),
        encoding="utf-8",
    )


def write_waiting_codex(path):
    path.write_text(
        "\n".join(
            [
                "import os, sys",
                "from pathlib import Path",
                "argv = sys.argv[1:]",
                "prompt = sys.stdin.buffer.read().decode('utf-8', errors='replace')",
                "Path(os.environ['FAKE_CODEX_PROMPT_LOG']).write_text(prompt, encoding='utf-8')",
                "final_message = Path(argv[argv.index('--output-last-message') + 1])",
                "final_message.write_text('请提供这个工作流节点的具体任务、输入和期望输出', encoding='utf-8')",
                "print('ready')",
            ]
        ),
        encoding="utf-8",
    )


def test_project_registry_registers_and_rebinds_in_agent_home(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    first_root = tmp_path / "apps" / "app-a"
    second_root = tmp_path / "projects" / "app-a"
    first_root.mkdir(parents=True)
    second_root.mkdir(parents=True)

    record = register_project(name="app-a", root=first_root)
    rebound = rebind_project(identifier=record.project_id, root=second_root)

    loaded = get_project("app-a")
    assert loaded is not None
    assert loaded.root_path == second_root.resolve()
    assert loaded.workspace_root == (second_root / ".agentic" / "workspace").resolve()
    assert rebound.created_at == record.created_at


def test_project_registry_accepts_explicit_workspace_root(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    project_root = tmp_path / "apps" / "app-a"
    project_root.mkdir(parents=True)

    record = register_project(
        name="app-a",
        root=project_root,
        workspace_root=Path(".agentic/custom-workspace"),
    )

    assert record.workspace_root == (project_root / ".agentic" / "custom-workspace").resolve()


def test_project_registry_rejects_legacy_records_without_workspace_root(
    tmp_path,
    monkeypatch,
):
    home = tmp_path / "home"
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(home))
    home.mkdir()
    (home / "registry.json").write_text(
        json.dumps(
            {
                "projects": {
                    "app-a": {
                        "project_id": "app-a",
                        "name": "app-a",
                        "root_path": str(tmp_path / "apps" / "app-a"),
                        "created_at": "2026-06-16T00:00:00",
                        "updated_at": "2026-06-16T00:00:00",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProjectRegistryError, match="缺少 workspace_root"):
        get_project("app-a")


def test_project_register_onboarding_requires_model_for_missing_project_config(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    infra_root = Path(__file__).resolve().parents[3]
    project_root = tmp_path / "apps" / "app-a"
    project_root.mkdir(parents=True)

    with pytest.raises(NeedsModelSelection) as error:
        register_project_onboarding(
            infra_root=infra_root,
            name="app-a",
            root=project_root,
        )

    assert error.value.payload["status"] == "NEEDS_MODEL_SELECTION"
    assert any(model["id"] == "codex-gpt-5" for model in error.value.payload["models"])
    assert get_project("app-a") is None
    assert not (project_root / ".agentic" / "project.json").exists()


def test_project_register_onboarding_uses_default_stack_profile_after_model_is_selected(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    infra_root = Path(__file__).resolve().parents[3]
    project_root = tmp_path / "apps" / "app-a"
    project_root.mkdir(parents=True)

    payload = register_project_onboarding(
        infra_root=infra_root,
        name="app-a",
        root=project_root,
        model_id="codex-gpt-5",
    )

    config = json.loads((project_root / ".agentic" / "project.json").read_text(encoding="utf-8"))
    contract = json.loads(
        (project_root / ".agentic" / "stack-contract.json").read_text(encoding="utf-8")
    )
    assert payload["status"] == "REGISTERED_READY"
    assert payload["stack"]["profile_id"] == "default-web-app"
    assert config["model"]["id"] == "codex-gpt-5"
    assert config["adapter"]["profile"] == ".agentic/runtime-adapters/codex.json"
    assert contract["profile_id"] == "default-web-app"
    assert contract["technology_stack"]["database"] == "SQLite"
    assert (project_root / ".agentic" / "runtime-adapters" / "codex.json").exists()
    assert get_project("app-a") is not None


def test_project_register_onboarding_generates_stack_contract_from_profile(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    infra_root = Path(__file__).resolve().parents[3]
    project_root = tmp_path / "apps" / "app-a"
    project_root.mkdir(parents=True)

    payload = register_project_onboarding(
        infra_root=infra_root,
        name="app-a",
        root=project_root,
        model_id="codex-gpt-5",
        stack_profile_id="default-web-app",
    )

    contract = json.loads(
        (project_root / ".agentic" / "stack-contract.json").read_text(encoding="utf-8")
    )
    assert payload["registration"]["name"] == "app-a"
    assert payload["stack"]["profile_id"] == "default-web-app"
    assert payload["readiness"]["stack_contract_status"] == "passed"
    assert payload["ready_for_workflows"] == ["ao-small", "ao-plan", "ao-spec"]
    assert contract["profile_id"] == "default-web-app"
    assert contract["technology_stack"]["frontend"] == "React + TypeScript + Vite + npm"
    assert contract["technology_stack"]["backend"] == "Python + FastAPI + pytest + uv/pip"
    assert contract["technology_stack"]["database"] == "SQLite"
    assert contract["commands"]["verify_all"] == ["python scripts/ao.py verify"]
    assert (project_root / "scripts" / "ao.py").exists()
    assert (project_root / "agentic.lock.json").exists()
    assert get_project("app-a") is not None


def test_profile_registered_project_can_prepare_business_workflow(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    infra_root = Path(__file__).resolve().parents[3]
    project_root = tmp_path / "apps" / "app-a"
    project_root.mkdir(parents=True)
    register_project_onboarding(
        infra_root=infra_root,
        name="app-a",
        root=project_root,
        model_id="codex-gpt-5",
        stack_profile_id="default-web-app",
    )

    context = create_run_context(
        infra_root,
        WorkflowInput(
            workflow="plan-execute",
            goal="准备业务 workflow",
            project="app-a",
        ),
        run_id="run_profile_prepare",
    )
    run_dir = prepare_run(context)

    assert run_dir == project_root / ".agentic" / "runs" / "run_profile_prepare"
    assert context.stack_contract_ref is not None
    assert context.stack_contract_ref.contract_id == "app-a-stack"


def test_project_register_onboarding_retains_existing_valid_model_without_model_arg(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    infra_root = Path(__file__).resolve().parents[3]
    project_root = tmp_path / "apps" / "app-a"
    project_root.mkdir(parents=True)
    config_dir = project_root / ".agentic"
    config_dir.mkdir()
    config_path = config_dir / "project.json"
    config_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": "app-a",
                "project_name": "app-a",
                "model": {"id": "codex-gpt-5"},
                "adapter": {"id": "codex", "command": [sys.executable, "-c", "print('ok')"]},
                "verify": {"command": [sys.executable, "-c", "print('verify')"]},
            }
        ),
        encoding="utf-8",
    )
    before = config_path.read_text(encoding="utf-8")

    payload = register_project_onboarding(
        infra_root=infra_root,
        name="app-a",
        root=project_root,
    )

    assert config_path.read_text(encoding="utf-8") == before
    contract = json.loads(
        (project_root / ".agentic" / "stack-contract.json").read_text(encoding="utf-8")
    )
    assert payload["status"] == "REGISTERED_READY"
    assert contract["profile_id"] == "default-web-app"
    assert get_project("app-a") is not None


def test_project_models_payload_hides_internal_models():
    infra_root = Path(__file__).resolve().parents[3]

    model_ids = [model["id"] for model in models_payload(infra_root)["models"]]

    assert "codex-gpt-5" in model_ids
    assert "qoder-cn-qwen" in model_ids
    assert "opencode-default" in model_ids
    assert "codex-gpt-5-codex-adapter" not in model_ids


def test_stack_profiles_payload_lists_default_web_app():
    infra_root = Path(__file__).resolve().parents[3]

    payload = stack_profiles_payload(infra_root)

    assert payload["default_profile"] == "default-web-app"
    default = next(profile for profile in payload["profiles"] if profile["id"] == "default-web-app")
    assert default["technology_stack"]["frontend"] == "React + TypeScript + Vite + npm"
    assert default["technology_stack"]["client"] == "无独立客户端"


def test_project_workflow_uses_target_project_adapter_and_worktree(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    control_root = tmp_path / "control"
    project_root = tmp_path / "apps" / "app-a"
    control_root.mkdir()
    project_root.mkdir(parents=True)
    write_node_definition(control_root, worktree=True)
    _git(project_root, "init")
    _git(project_root, "config", "user.email", "test@example.com")
    _git(project_root, "config", "user.name", "Test User")
    fake_codex = tmp_path / "fake_codex.py"
    argv_log = tmp_path / "codex-argv.jsonl"
    monkeypatch.setenv("FAKE_CODEX_ARGV_LOG", str(argv_log))
    write_fake_codex(fake_codex)
    write_project_config(project_root, adapter_command=[sys.executable, str(fake_codex)])
    (project_root / "README.md").write_text("# app-a\n", encoding="utf-8")
    _git(project_root, "add", "README.md", ".agentic/project.json")
    _git(project_root, "commit", "-m", "init app")
    context = create_run_context(
        control_root,
        WorkflowInput(
            workflow="small-change",
            goal="更新业务应用",
            project_root=str(project_root),
        ),
        run_id="run_project_e2e",
    )
    prepare_run(context)

    result = run_e2e_workflow(context, use_worktree=True)

    assert result.return_code == 0
    assert context.run_dir == project_root.resolve() / ".agentic" / "runs" / "run_project_e2e"
    assert context.worktrees_dir == project_root.resolve() / ".agentic" / "worktrees"
    assert context.logs_dir == project_root.resolve() / ".agentic" / "logs"
    assert not context.run_dir.is_relative_to(tmp_path / "home")
    run_state = read_run_status(control_root, "run_project_e2e")
    assert run_state["runtime_adapter"]["command"] == [sys.executable, str(fake_codex)]
    assert run_state["stack_contract"]["contract_id"] == "app-a-stack"
    worktree_path = run_state["worktree"]["path"]
    assert Path(worktree_path).is_relative_to(project_root / ".agentic" / "worktrees")
    assert Path(_git_show_toplevel(worktree_path)) == Path(worktree_path)
    logged_argv = [
        json.loads(line)
        for line in argv_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(logged_argv) == 2
    for argv in logged_argv:
        assert argv[0] == "exec"
        assert "--cd" in argv
        assert argv[argv.index("--cd") + 1] == worktree_path
        assert "--output-last-message" in argv
        assert argv[-1] == "-"
    assert not (control_root / "output" / "worktrees").exists()
    assert cleanup_run(control_root, "run_project_e2e", force=True) is True


def test_project_runtime_uses_generic_cli_codex_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    control_root = tmp_path / "control"
    project_root = tmp_path / "apps" / "app-a"
    control_root.mkdir()
    project_root.mkdir(parents=True)
    write_node_definition(control_root)
    fake_codex = tmp_path / "fake_codex.py"
    argv_log = tmp_path / "generic-codex-argv.jsonl"
    monkeypatch.setenv("FAKE_CODEX_ARGV_LOG", str(argv_log))
    write_fake_codex(fake_codex)
    profile_source = Path(__file__).resolve().parents[3] / ".agentic" / "runtime-adapters" / "codex.json"
    profile_target = project_root / ".agentic" / "runtime-adapters" / "codex.json"
    profile_target.parent.mkdir(parents=True, exist_ok=True)
    profile_target.write_text(profile_source.read_text(encoding="utf-8"), encoding="utf-8")
    write_project_config(
        project_root,
        adapter_id="generic-cli",
        adapter_command=[sys.executable, str(fake_codex)],
        adapter_profile=".agentic/runtime-adapters/codex.json",
    )
    context = create_run_context(
        control_root,
        WorkflowInput(
            workflow="small-change",
            goal="generic codex project",
            project_root=str(project_root),
        ),
        run_id="run_generic_codex_project",
    )
    prepare_run(context)

    result = run_e2e_workflow(context, use_worktree=False)

    assert result.return_code == 0
    run_state = read_run_status(control_root, "run_generic_codex_project")
    assert run_state["runtime_adapter"]["id"] == "generic-cli"
    assert run_state["runtime_adapter"]["profile"] == ".agentic/runtime-adapters/codex.json"
    events = [
        json.loads(line)
        for line in (context.run_dir / "workflow-event.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert "adapter:generic-cli:execute" in [event["step"] for event in events]
    assert (context.run_dir / "nodes" / "execute" / "generic-cli-final-message.md").exists()
    assert (context.run_dir / "nodes" / "execute" / "stdout.log").exists()
    assert argv_log.exists()


def test_business_project_workflow_requires_stack_contract(tmp_path):
    control_root = tmp_path / "control"
    project_root = tmp_path / "apps" / "app-a"
    control_root.mkdir()
    project_root.mkdir(parents=True)
    write_node_definition(control_root)
    config_dir = project_root / ".agentic"
    config_dir.mkdir(parents=True)
    (config_dir / "project.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": project_root.name,
                "project_name": project_root.name,
                "adapter": {"id": "codex", "command": [sys.executable, "-c", "print('noop')"]},
                "verify": {"command": [sys.executable, "-c", "print('verify')"]},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing project stack contract"):
        create_run_context(
            control_root,
            WorkflowInput(
                workflow="small-change",
                goal="更新业务应用",
                project_root=str(project_root),
            ),
            run_id="run_missing_stack_contract",
        )


def test_project_root_workflow_rejects_mismatched_stack_contract_project_id(tmp_path):
    control_root = tmp_path / "control"
    project_root = tmp_path / "apps" / "app-a"
    control_root.mkdir()
    project_root.mkdir(parents=True)
    write_node_definition(control_root)
    write_project_config(project_root)
    payload = json.loads((project_root / ".agentic" / "stack-contract.json").read_text())
    payload["project_id"] = "other-app"
    (project_root / ".agentic" / "stack-contract.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="stack contract project_id mismatch"):
        create_run_context(
            control_root,
            WorkflowInput(
                workflow="small-change",
                goal="更新业务应用",
                project_root=str(project_root),
            ),
            run_id="run_mismatched_stack_contract",
        )


def test_project_workflow_honors_custom_runtime_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    control_root = tmp_path / "control"
    project_root = tmp_path / "apps" / "app-a"
    control_root.mkdir()
    project_root.mkdir(parents=True)
    write_node_definition(control_root, worktree=True)
    _git(project_root, "init")
    _git(project_root, "config", "user.email", "test@example.com")
    _git(project_root, "config", "user.name", "Test User")
    fake_codex = tmp_path / "fake_codex.py"
    argv_log = tmp_path / "codex-custom-argv.jsonl"
    monkeypatch.setenv("FAKE_CODEX_ARGV_LOG", str(argv_log))
    write_fake_codex(fake_codex)
    write_project_config(
        project_root,
        adapter_command=[sys.executable, str(fake_codex)],
        runtime={
            "runs_dir": ".ao/runs",
            "worktrees_dir": ".ao/worktrees",
            "logs_dir": ".ao/logs",
        },
    )
    (project_root / "README.md").write_text("# app-a\n", encoding="utf-8")
    _git(project_root, "add", "README.md", ".agentic/project.json")
    _git(project_root, "commit", "-m", "init app")
    context = create_run_context(
        control_root,
        WorkflowInput(
            workflow="small-change",
            goal="更新业务应用",
            project_root=str(project_root),
        ),
        run_id="run_project_custom_runtime",
    )
    prepare_run(context)

    result = run_e2e_workflow(context, use_worktree=True)

    assert result.return_code == 0
    assert context.run_dir == project_root.resolve() / ".ao" / "runs" / "run_project_custom_runtime"
    assert context.worktrees_dir == project_root.resolve() / ".ao" / "worktrees"
    assert context.logs_dir == project_root.resolve() / ".ao" / "logs"
    run_state = read_run_status(control_root, "run_project_custom_runtime")
    worktree_path = Path(run_state["worktree"]["path"])
    assert worktree_path.is_relative_to(project_root / ".ao" / "worktrees")
    assert cleanup_run(control_root, "run_project_custom_runtime", force=True) is True


def test_project_runtime_rejects_paths_outside_project(tmp_path):
    control_root = tmp_path / "control"
    project_root = tmp_path / "apps" / "app-a"
    control_root.mkdir()
    project_root.mkdir(parents=True)
    write_node_definition(control_root)

    write_project_config(project_root, runtime={"runs_dir": "../runs"})
    with pytest.raises(ProjectConfigError, match="must not contain"):
        create_run_context(
            control_root,
            WorkflowInput(
                workflow="small-change",
                goal="更新业务应用",
                project_root=str(project_root),
            ),
            run_id="run_bad_parent",
        )

    write_project_config(project_root, runtime={"worktrees_dir": str(tmp_path / "outside")})
    with pytest.raises(ProjectConfigError, match="must be relative"):
        create_run_context(
            control_root,
            WorkflowInput(
                workflow="small-change",
                goal="更新业务应用",
                project_root=str(project_root),
            ),
            run_id="run_bad_absolute",
        )


def test_codex_node_prompt_uses_stdin_and_waiting_reply_fails(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    control_root = tmp_path / "control"
    project_root = tmp_path / "apps" / "app-a"
    control_root.mkdir()
    project_root.mkdir(parents=True)
    definition_dir = control_root / ".agentic" / "workflow" / "definitions"
    definition_dir.mkdir(parents=True)
    (definition_dir / "spec-driven.json").write_text(
        json.dumps(
            {
                "name": "spec-driven",
                "title": "Spec Driven",
                "adapter": "local-governed",
                "contract_path": ".agentic/workflow/spec-driven.md",
                "primary_inputs": ["goal"],
                "stages": ["generate-product-prd"],
                "verify_policy": "full",
                "nodes": [
                    {
                        "id": "generate-product-prd",
                        "required_artifacts": ["product-prd.md"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    fake_codex = tmp_path / "waiting_codex.py"
    prompt_log = tmp_path / "prompt.md"
    monkeypatch.setenv("FAKE_CODEX_PROMPT_LOG", str(prompt_log))
    write_waiting_codex(fake_codex)
    write_project_config(project_root, adapter_command=[sys.executable, str(fake_codex)])
    context = create_run_context(
        control_root,
        WorkflowInput(
            workflow="spec-driven",
            goal="生成产品 PRD",
            project_root=str(project_root),
        ),
        run_id="run_waiting_codex",
    )
    prepare_run(context)

    with pytest.raises(RuntimeError, match="adapter exited"):
        run_e2e_workflow(context, use_worktree=False)

    prompt = prompt_log.read_text(encoding="utf-8")
    assert "本节点必须立即执行的任务" in prompt
    assert "product-prd.md" in prompt
    run_state = read_run_status(control_root, "run_waiting_codex")
    assert run_state["status"] == "FAILED"
    assert run_state["failed_node"] == "generate-product-prd"


def test_acceptance_gate_failure_does_not_rewrite_last_node_status(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    control_root = tmp_path / "control"
    project_root = tmp_path / "apps" / "app-a"
    control_root.mkdir()
    project_root.mkdir(parents=True)
    definition_dir = control_root / ".agentic" / "workflow" / "definitions"
    definition_dir.mkdir(parents=True)
    (definition_dir / "spec-driven.json").write_text(
        json.dumps(
            {
                "name": "spec-driven",
                "title": "Spec Driven",
                "adapter": "local-governed",
                "contract_path": ".agentic/workflow/spec-driven.md",
                "primary_inputs": ["goal"],
                "stages": ["generate-product-prd"],
                "verify_policy": "full",
                "nodes": [
                    {
                        "id": "generate-product-prd",
                        "required_artifacts": ["product-prd.md"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    provider = tmp_path / "artifact_provider.py"
    write_artifact_provider(provider)
    write_project_config(project_root, adapter_command=[sys.executable, str(provider)])
    context = create_run_context(
        control_root,
        WorkflowInput(
            workflow="spec-driven",
            goal="生成产品 PRD",
            project_root=str(project_root),
        ),
        run_id="run_acceptance_gate_failure",
    )
    prepare_run(context)

    with pytest.raises(RuntimeError, match="acceptance-matrix"):
        run_e2e_workflow(context, use_worktree=False)

    run_state = read_run_status(control_root, "run_acceptance_gate_failure")
    assert run_state["failed_node"] == "acceptance-matrix"
    assert run_state["nodes"][0]["node_id"] == "generate-product-prd"
    assert run_state["nodes"][0]["status"] == "PASSED"


def test_project_workflow_requires_project_config(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    control_root = tmp_path / "control"
    project_root = tmp_path / "apps" / "app-a"
    control_root.mkdir()
    project_root.mkdir(parents=True)
    write_node_definition(control_root)

    with pytest.raises(ProjectConfigError, match="project config not found"):
        create_run_context(
            control_root,
            WorkflowInput(
                workflow="small-change",
                goal="更新业务应用",
                project_root=str(project_root),
            ),
            run_id="run_missing_project_config",
        )


def test_project_complete_uses_project_verify_command(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    control_root = tmp_path / "control"
    project_root = tmp_path / "apps" / "app-a"
    control_root.mkdir()
    project_root.mkdir(parents=True)
    write_definition(control_root)
    write_project_config(
        project_root,
        verify_command=[sys.executable, "-c", "print('project verify')"],
    )
    context = create_run_context(
        control_root,
        WorkflowInput(
            workflow="small-change",
            goal="更新业务应用",
            project_root=str(project_root),
        ),
        run_id="run_project_verify",
    )
    prepare_run(context)
    write_stack_artifacts(context)
    calls = []

    def fake_run_command(command, cwd, timeout_seconds):
        calls.append((command, cwd))
        return type("Result", (), {"return_code": 0, "stdout": "ok", "stderr": ""})()

    monkeypatch.setattr("agentic_workflow.runner.run_command", fake_run_command)

    assert complete_run(context, summary="done", changed_files=[], skip_verify=False) == 0
    assert calls == [([sys.executable, "-c", "print('project verify')"], project_root.resolve())]


def test_project_complete_cannot_skip_stack_acceptance_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    control_root = tmp_path / "control"
    project_root = tmp_path / "apps" / "app-a"
    control_root.mkdir()
    project_root.mkdir(parents=True)
    write_definition(control_root)
    write_project_config(project_root)
    context = create_run_context(
        control_root,
        WorkflowInput(
            workflow="small-change",
            goal="更新业务应用",
            project_root=str(project_root),
        ),
        run_id="run_project_complete_missing_stack_gate",
    )
    prepare_run(context)

    with pytest.raises(ValueError, match="missing stack-trace artifact"):
        complete_run(context, summary="done", changed_files=[], skip_verify=True)


def test_stack_acceptance_requires_verify_all_command_coverage(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    control_root = tmp_path / "control"
    project_root = tmp_path / "apps" / "app-a"
    control_root.mkdir()
    project_root.mkdir(parents=True)
    write_definition(control_root)
    write_project_config(project_root)
    context = create_run_context(
        control_root,
        WorkflowInput(
            workflow="small-change",
            goal="更新业务应用",
            project_root=str(project_root),
        ),
        run_id="run_missing_command_coverage",
    )
    prepare_run(context)
    write_stack_artifacts(context, include_command=False)

    with pytest.raises(ValueError, match="command-coverage.json"):
        complete_run(context, summary="done", changed_files=[], skip_verify=True)


def test_stack_acceptance_requires_all_contract_component_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    control_root = tmp_path / "control"
    project_root = tmp_path / "apps" / "app-a"
    control_root.mkdir()
    project_root.mkdir(parents=True)
    write_definition(control_root)
    write_project_config(project_root)
    contract_path = project_root / ".agentic" / "stack-contract.json"
    payload = json.loads(contract_path.read_text())
    payload["components"].append(
        {
            "component_id": "frontend",
            "kind": "frontend",
            "language": "typescript",
            "framework": "react",
            "root": "web",
            "package_manager": "npm",
        }
    )
    contract_path.write_text(json.dumps(payload), encoding="utf-8")
    context = create_run_context(
        control_root,
        WorkflowInput(
            workflow="small-change",
            goal="更新业务应用",
            project_root=str(project_root),
        ),
        run_id="run_missing_component_evidence",
    )
    prepare_run(context)
    write_stack_artifacts(context)

    with pytest.raises(ValueError, match="missing contract components: frontend"):
        complete_run(context, summary="done", changed_files=[], skip_verify=True)


def test_resume_revalidates_passed_stack_acceptance(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    control_root = tmp_path / "control"
    project_root = tmp_path / "apps" / "app-a"
    control_root.mkdir()
    project_root.mkdir(parents=True)
    write_definition(control_root)
    write_project_config(project_root)
    context = create_run_context(
        control_root,
        WorkflowInput(
            workflow="small-change",
            goal="更新业务应用",
            project_root=str(project_root),
        ),
        run_id="run_stale_stack_resume",
    )
    prepare_run(context)
    write_stack_artifacts(context)
    (context.run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": context.run_id,
                "workflow": context.definition.name,
                "status": "PASSED",
                "workflow_input": context.workflow_input.to_dict(),
                "acceptance_matrix": str(context.run_dir / "acceptance-matrix.json"),
            }
        ),
        encoding="utf-8",
    )
    payload = json.loads((project_root / ".agentic" / "stack-contract.json").read_text())
    payload["revision"] = 2
    (project_root / ".agentic" / "stack-contract.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="does not reference stack contract hash"):
        resume_run(control_root, "run_stale_stack_resume")


def _git(cwd, *args):
    result = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout.strip()


def _git_show_toplevel(cwd):
    return _git(cwd, "rev-parse", "--show-toplevel")
