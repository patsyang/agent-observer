import json
import sys
from pathlib import Path

import pytest

from agentic_workflow.adapters.codex import build_codex_node_prompt
from agentic_workflow.e2e_runner import cleanup_run, run_e2e_workflow
from agentic_workflow.models import WorkflowInput
from agentic_workflow.project_scope import ScopeResolutionError, resolve_project_scope
from agentic_workflow.runner import complete_run, create_run_context, execute_run, prepare_run


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
                "parallelism": 1,
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


def test_prepare_run_writes_standard_artifacts(tmp_path):
    write_definition(tmp_path)
    context = create_run_context(
        tmp_path,
        WorkflowInput(workflow="small-change", goal="修复状态文案"),
        run_id="run_test",
    )

    run_dir = prepare_run(context)

    assert (run_dir / "input.json").exists()
    assert (run_dir / "agent-instructions.md").exists()
    assert (run_dir / "run-report.md").exists()
    events = (run_dir / "workflow-event.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(events[0])["workflow"] == "small-change"


def test_prepare_run_rejects_active_duplicate_primary_input(tmp_path):
    write_definition(tmp_path)
    first = create_run_context(
        tmp_path,
        WorkflowInput(workflow="small-change", goal="修复状态文案"),
        run_id="run_first",
    )
    second = create_run_context(
        tmp_path,
        WorkflowInput(workflow="small-change", goal="修复状态文案"),
        run_id="run_second",
    )

    prepare_run(first)

    with pytest.raises(RuntimeError, match="已有活跃 workflow run.*run_first"):
        prepare_run(second)
    assert not second.run_dir.exists()


def test_prepare_run_allows_duplicate_after_cleanup(tmp_path):
    write_definition(tmp_path)
    first = create_run_context(
        tmp_path,
        WorkflowInput(workflow="small-change", goal="修复状态文案"),
        run_id="run_first",
    )
    second = create_run_context(
        tmp_path,
        WorkflowInput(workflow="small-change", goal="修复状态文案"),
        run_id="run_second",
    )
    prepare_run(first)

    assert cleanup_run(tmp_path, "run_first", force=True) is False
    prepare_run(second)

    state = json.loads((first.run_dir / "run.json").read_text(encoding="utf-8"))
    assert state["status"] == "CLEANED"
    assert second.run_dir.exists()


def test_execute_run_marks_failed_adapter_run_terminal(tmp_path):
    write_definition(tmp_path)
    fake_codex = tmp_path / "fake_codex.py"
    fake_codex.write_text(
        "\n".join(
            [
                "import sys",
                "print('adapter failed')",
                "sys.exit(3)",
            ]
        ),
        encoding="utf-8",
    )
    first = create_run_context(
        tmp_path,
        WorkflowInput(workflow="small-change", goal="验证失败重跑"),
        run_id="run_failed_adapter",
    )

    return_code = execute_run(
        first,
        adapter_name="codex",
        adapter_command=[sys.executable, str(fake_codex)],
        skip_verify=True,
        timeout_seconds=10,
    )

    assert return_code == 3
    state = json.loads((first.run_dir / "run.json").read_text(encoding="utf-8"))
    assert state["status"] == "FAILED"
    second = create_run_context(
        tmp_path,
        WorkflowInput(workflow="small-change", goal="验证失败重跑"),
        run_id="run_after_failed_adapter",
    )
    prepare_run(second)
    assert second.run_dir.exists()


def test_rejects_multiple_primary_inputs(tmp_path):
    write_definition(tmp_path)

    with pytest.raises(ValueError, match="必须且只能提供一个主输入"):
        create_run_context(
            tmp_path,
            WorkflowInput(workflow="small-change", goal="a", goal_path="b.md"),
        )


def test_rejects_disallowed_primary_input(tmp_path):
    write_definition(tmp_path)

    with pytest.raises(ValueError, match="不允许输入"):
        create_run_context(
            tmp_path,
            WorkflowInput(workflow="small-change", spec_path="feature.md"),
        )


def test_execute_run_uses_codex_adapter_contract(tmp_path):
    write_definition(tmp_path)
    fake_codex = tmp_path / "fake_codex.py"
    fake_codex.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "import sys",
                "args = sys.argv[1:]",
                "output = Path(args[args.index('--output-last-message') + 1])",
                "output.write_text('模拟 Codex 执行完成', encoding='utf-8')",
                "print('模拟 Codex 标准输出')",
            ]
        ),
        encoding="utf-8",
    )
    context = create_run_context(
        tmp_path,
        WorkflowInput(workflow="small-change", goal="验证 Codex adapter"),
        run_id="run_codex_adapter_test",
    )

    return_code = execute_run(
        context,
        adapter_name="codex",
        adapter_command=[sys.executable, str(fake_codex)],
        skip_verify=True,
        timeout_seconds=10,
    )

    run_dir = tmp_path / "ai_docs" / "runs" / "run_codex_adapter_test"
    assert return_code == 0
    assert (run_dir / "codex-prompt.md").exists()
    assert (run_dir / "codex.stdout.log").read_text(encoding="utf-8").strip()
    assert "模拟 Codex 执行完成" in (run_dir / "codex-final-message.md").read_text(encoding="utf-8")
    events = [
        json.loads(line)
        for line in (run_dir / "workflow-event.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["step"] for event in events] == ["prepare", "adapter:codex", "complete"]


def test_codex_node_prompt_contains_task_and_required_artifacts(tmp_path):
    write_node_definition(tmp_path)
    context = create_run_context(
        tmp_path,
        WorkflowInput(workflow="small-change", goal="验证节点 prompt"),
        run_id="run_node_prompt",
    )
    prepare_run(context)
    artifacts_dir = context.run_dir / "artifacts"

    prompt = build_codex_node_prompt(
        context,
        node={"id": "execute", "required_artifacts": ["implementation.md"]},
        node_id="execute",
        artifacts_dir=artifacts_dir,
        worktree_path=Path(tmp_path),
        required_artifacts=["implementation.md"],
    )

    assert "不要回复“请提供任务”" in prompt
    assert "node：`execute`" in prompt
    assert "workflow_input" in prompt
    assert str(artifacts_dir) in prompt
    assert "implementation.md" in prompt


def test_control_plane_complete_uses_control_plane_verification(tmp_path, monkeypatch):
    write_definition(tmp_path, name="control-plane-change", verify_policy="control-plane")
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "init")
    context = create_run_context(
        tmp_path,
        WorkflowInput(workflow="control-plane-change", goal="更新控制面"),
        run_id="run_control_plane",
    )
    prepare_run(context)
    (context.run_dir / "changed-files.json").write_text(
        json.dumps({"paths": []}),
        encoding="utf-8",
    )
    commands = []

    def fake_run_command(command, cwd, timeout_seconds):
        commands.append(command)
        return type("Result", (), {"return_code": 0, "stdout": "ok", "stderr": ""})()

    monkeypatch.setattr("agentic_workflow.infra_gates.run_command", fake_run_command)

    return_code = complete_run(
        context,
        summary="done",
        changed_files=["AGENTS.md"],
        skip_verify=False,
    )

    assert return_code == 0
    assert commands == [["python", "scripts/ao.py", "agentic-check"]]


def test_default_complete_uses_python_project_verify(tmp_path, monkeypatch):
    write_definition(tmp_path)
    context = create_run_context(
        tmp_path,
        WorkflowInput(workflow="small-change", goal="更新功能"),
        run_id="run_default_verify",
    )
    prepare_run(context)
    commands = []

    def fake_run_command(command, cwd, timeout_seconds):
        commands.append(command)
        return type("Result", (), {"return_code": 0, "stdout": "ok", "stderr": ""})()

    monkeypatch.setattr("agentic_workflow.runner.run_command", fake_run_command)

    return_code = complete_run(
        context,
        summary="done",
        changed_files=["apps/example.py"],
        skip_verify=False,
    )

    assert return_code == 0
    assert commands == [["python", "scripts/ao.py", "verify"]]


def test_control_plane_complete_runs_runner_tests_for_ao_entry_changes(tmp_path, monkeypatch):
    write_definition(tmp_path, name="control-plane-change", verify_policy="control-plane")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "ao.py").write_text("print('old')\n", encoding="utf-8")
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test User")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "init")
    context = create_run_context(
        tmp_path,
        WorkflowInput(workflow="control-plane-change", goal="更新控制面"),
        run_id="run_control_plane_tests",
    )
    prepare_run(context)
    (tmp_path / "scripts" / "ao.py").write_text("print('new')\n", encoding="utf-8")
    (context.run_dir / "changed-files.json").write_text(
        json.dumps(
            {
                "paths": [
                    {"path": "scripts/ao.py", "status": "modified", "old_path": None}
                ]
            }
        ),
        encoding="utf-8",
    )
    review_dir = context.run_dir / "review"
    review_dir.mkdir()
    (review_dir / "raw-findings.json").write_text(
        json.dumps({"reviewer": {"kind": "sub_agent", "agent_id": "agent-test"}, "findings": []}),
        encoding="utf-8",
    )
    (review_dir / "output.md").write_text("No blocking findings found.\n", encoding="utf-8")
    commands = []

    def fake_run_command(command, cwd, timeout_seconds):
        commands.append(command)
        return type("Result", (), {"return_code": 0, "stdout": "ok", "stderr": ""})()

    monkeypatch.setattr("agentic_workflow.infra_gates.run_command", fake_run_command)

    return_code = complete_run(
        context,
        summary="done",
        changed_files=["scripts/ao.py"],
        skip_verify=False,
    )

    assert return_code == 0
    assert commands == [
        ["python", "scripts/ao.py", "agentic-check"],
        [
            "uv",
            "run",
            "--project",
            "tools/workflow_runner",
            "python",
            "-m",
            "pytest",
            "tools/workflow_runner/tests",
        ],
        ["python", "scripts/ao.py", "--help"],
        ["python", "scripts/ao.py", "workflow", "--help"],
        ["python", "scripts/ao.py", "ao-infra", "--help"],
    ]


def test_scope_requires_explicit_value_when_goal_matches_multiple_apps(tmp_path):
    (tmp_path / "apps" / "one" / "frontend" / "DashboardPage.tsx").mkdir(parents=True)
    (tmp_path / "apps" / "two" / "frontend" / "DashboardPage.tsx").mkdir(parents=True)

    with pytest.raises(ScopeResolutionError, match="多个候选 scope"):
        resolve_project_scope(
            tmp_path,
            WorkflowInput(workflow="small-change", goal="修复 Dashboard 未读消息"),
        )


def test_scope_accepts_explicit_app_scope(tmp_path):
    (tmp_path / "apps" / "agentic_factory").mkdir(parents=True)

    result = resolve_project_scope(
        tmp_path,
        WorkflowInput(
            workflow="small-change",
            goal="修复 Dashboard 未读消息",
            scope="apps/agentic_factory",
        ),
    )

    assert result.project_scope == "apps/agentic_factory"
    assert result.write_set == ("apps/agentic_factory/**",)


def test_run_e2e_workflow_writes_artifacts_and_acceptance_matrix(tmp_path):
    write_node_definition(tmp_path, worktree=True)
    (tmp_path / "apps" / "agentic_factory").mkdir(parents=True)
    context = create_run_context(
        tmp_path,
        WorkflowInput(
            workflow="small-change",
            goal="修复 Dashboard 未读消息",
            scope="apps/agentic_factory",
        ),
        run_id="run_e2e",
    )
    prepare_run(context)

    result = run_e2e_workflow(context, use_worktree=False)

    assert result.return_code == 0
    run_state = json.loads((context.run_dir / "run.json").read_text(encoding="utf-8"))
    assert run_state["status"] == "PASSED"
    assert run_state["project_scope"] == "apps/agentic_factory"
    assert run_state["worktree"] is None
    assert (context.run_dir / "artifacts" / "scope-resolution.json").exists()
    assert (context.run_dir / "artifacts" / "implementation.md").exists()
    acceptance_path = context.run_dir / "acceptance-matrix.json"
    acceptance = json.loads(acceptance_path.read_text(encoding="utf-8"))
    assert acceptance[0]["result"] == "PASS"
    report = (context.run_dir / "run-report.md").read_text(encoding="utf-8")
    assert "status: `passed`" in report
    assert "acceptance matrix gate: PASSED" in report
    assert "acceptance-matrix.json" in report


def _git(cwd: Path | str, *args: str) -> str:
    import subprocess

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
