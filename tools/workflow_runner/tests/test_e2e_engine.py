import json
import subprocess
import sys
from pathlib import Path

import pytest

from agentic_workflow.e2e_runner import cleanup_run, resume_run, run_e2e_workflow
from agentic_workflow.e2e_runner import _changed_files
from agentic_workflow.e2e_state import record_node
from agentic_workflow.models import WorkflowInput
from agentic_workflow.runner import create_run_context, prepare_run


def write_definition(
    repo_root: Path,
    *,
    name: str,
    primary_inputs: list[str],
    nodes: list[dict[str, object]],
    worktree: bool = False,
) -> None:
    definition_dir = repo_root / ".agentic" / "workflow" / "definitions"
    definition_dir.mkdir(parents=True)
    (definition_dir / f"{name}.json").write_text(
        json.dumps(
            {
                "name": name,
                "title": name,
                "adapter": "local-governed",
                "contract_path": f".agentic/workflow/{name}.md",
                "primary_inputs": primary_inputs,
                "stages": [str(node["id"]) for node in nodes],
                "verify_policy": "targeted",
                "worktree": worktree,
                "nodes": nodes,
            }
        ),
        encoding="utf-8",
    )


def write_project_config(project_root: Path, adapter_command: list[str]) -> None:
    config_dir = project_root / ".agentic"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "project.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": project_root.name,
                "project_name": project_root.name,
                "adapter": {"id": "codex", "command": adapter_command},
                "verify": {"command": [sys.executable, "-c", "print('verify')"]},
            }
        ),
        encoding="utf-8",
    )
    write_stack_contract(project_root)


def write_stack_contract(project_root: Path) -> None:
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
                "commands": {"verify_all": [sys.executable + " -c \"print('verify')\""]},
            }
        ),
        encoding="utf-8",
    )


def write_resume_fake_codex(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "import json, os, sys",
                "from pathlib import Path",
                "argv = sys.argv[1:]",
                "node = os.environ['AO_NODE_ID']",
                "artifacts = Path(os.environ['AO_ARTIFACTS_DIR'])",
                "log = artifacts / 'node-log.txt'",
                "with log.open('a', encoding='utf-8') as handle:",
                "    handle.write(node + '\\n')",
                "final_message = Path(argv[argv.index('--output-last-message') + 1])",
                "if node == 'review' and not (artifacts / 'allow-review.txt').exists():",
                "    final_message.write_text('review failed', encoding='utf-8')",
                "    print('review failed', file=sys.stderr)",
                "    sys.exit(7)",
                "for name in json.loads(os.environ.get('AO_REQUIRED_ARTIFACTS', '[]')):",
                "    (artifacts / name).write_text(f'{node} wrote {name}\\n', encoding='utf-8')",
                "final_message.write_text('COMPLETE', encoding='utf-8')",
                "print('COMPLETE')",
            ]
        ),
        encoding="utf-8",
    )


def test_resume_reruns_only_failed_node(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    control_root = tmp_path / "control"
    project_root = tmp_path / "apps" / "app-a"
    control_root.mkdir()
    project_root.mkdir(parents=True)
    write_definition(
        control_root,
        name="two-node",
        primary_inputs=["goal"],
        nodes=[
            {"id": "execute", "required_artifacts": ["implementation.md"]},
            {"id": "review", "required_artifacts": ["review.md"]},
        ],
    )
    fake_codex = tmp_path / "fake_codex.py"
    write_resume_fake_codex(fake_codex)
    write_project_config(project_root, [sys.executable, str(fake_codex)])
    context = create_run_context(
        control_root,
        WorkflowInput(
            workflow="two-node",
            goal="resume test",
            project_root=str(project_root),
        ),
        run_id="run_resume",
    )
    prepare_run(context)

    with pytest.raises(RuntimeError, match="review"):
        run_e2e_workflow(context, use_worktree=False)

    state = json.loads((context.run_dir / "run.json").read_text(encoding="utf-8"))
    assert state["status"] == "FAILED"
    assert Path(state["artifacts_dir"]) == context.run_dir / "artifacts"
    assert state["nodes"][0]["status"] == "PASSED"
    assert state["nodes"][1]["status"] == "FAILED"
    state["nodes"][0]["error"] = "stale missing artifact"
    (context.run_dir / "run.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    (context.run_dir / "artifacts" / "allow-review.txt").write_text("ok", encoding="utf-8")
    result = resume_run(control_root, "run_resume")

    assert result.return_code == 0
    assert (context.run_dir / "artifacts" / "node-log.txt").read_text(
        encoding="utf-8"
    ).splitlines() == ["execute", "review", "review"]
    resumed = json.loads((context.run_dir / "run.json").read_text(encoding="utf-8"))
    assert resumed["status"] == "PASSED"
    assert "error" not in resumed["nodes"][0]


def test_record_node_clears_stale_error_after_success() -> None:
    run_state: dict[str, object] = {}
    record_node(run_state, "execute", status="FAILED", error="missing artifact")
    record_node(run_state, "execute", status="RUNNING")
    record_node(run_state, "execute", status="PASSED", output="ok")

    nodes = run_state["nodes"]
    assert isinstance(nodes, list)
    assert nodes[0]["status"] == "PASSED"
    assert "error" not in nodes[0]


def test_changed_files_omits_python_cache_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    (repo / "app.py").write_text("print('ok')\n", encoding="utf-8")
    cache = repo / "pkg" / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "module.cpython-313.pyc").write_bytes(b"pyc")

    assert _changed_files(repo) == ["app.py"]


def test_prd_import_happens_inside_worktree_without_dirtying_project_root(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    control_root = tmp_path / "control"
    project_root = tmp_path / "apps" / "app-a"
    control_root.mkdir()
    project_root.mkdir(parents=True)
    write_definition(
        control_root,
        name="import-only",
        primary_inputs=["prd_path"],
        worktree=True,
        nodes=[
            {
                "id": "import-prd",
                "type": "system-import",
                "required_artifacts": ["imported-source.json"],
            }
        ],
    )
    write_project_config(project_root, [sys.executable, "-c", "print('unused')"])
    _git(project_root, "init")
    _git(project_root, "config", "user.email", "test@example.com")
    _git(project_root, "config", "user.name", "Test User")
    (project_root / "README.md").write_text("# app-a\n", encoding="utf-8")
    _git(project_root, "add", "README.md", ".agentic/project.json")
    _git(project_root, "commit", "-m", "init app")
    source = control_root / "prd.md"
    source.write_text("# Billing Export\n\n需求正文", encoding="utf-8")
    context = create_run_context(
        control_root,
        WorkflowInput(
            workflow="import-only",
            prd_path=str(source),
            project_root=str(project_root),
        ),
        run_id="run_import",
    )
    prepare_run(context)

    result = run_e2e_workflow(context, use_worktree=True)

    assert result.return_code == 0
    state = json.loads((context.run_dir / "run.json").read_text(encoding="utf-8"))
    worktree_path = Path(state["worktree"]["path"])
    assert (worktree_path / "specs" / "001-billing-export" / "source-prd.md").exists()
    assert not (worktree_path / "specs" / "001-billing-export" / "spec.md").exists()
    assert (context.run_dir / "artifacts" / "imported-source.json").exists()
    assert _git(project_root, "status", "--porcelain") == ""
    assert cleanup_run(control_root, "run_import", force=True) is True


def test_implement_story_loop_requires_all_stories_passed_even_if_output_says_complete(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    control_root = tmp_path / "control"
    project_root = tmp_path / "apps" / "app-a"
    control_root.mkdir()
    project_root.mkdir(parents=True)
    write_definition(
        control_root,
        name="loop-test",
        primary_inputs=["goal"],
        nodes=[
            {
                "id": "implement-story-loop",
                "type": "loop",
                "until": "COMPLETE",
                "max_iterations": 3,
                "required_artifacts": ["implementation-state.json", "progress.md"],
            },
            {"id": "after", "depends_on": ["implement-story-loop"], "required_artifacts": ["after.md"]},
        ],
    )
    fake_codex = tmp_path / "fake_loop_codex.py"
    fake_codex.write_text(
        "\n".join(
            [
                "import json, os, sys",
                "from pathlib import Path",
                "argv = sys.argv[1:]",
                "node = os.environ['AO_NODE_ID']",
                "iteration = int(os.environ.get('AO_LOOP_ITERATION', '0') or '0')",
                "artifacts = Path(os.environ['AO_ARTIFACTS_DIR'])",
                "with (artifacts / 'loop-log.txt').open('a', encoding='utf-8') as handle:",
                "    handle.write(f'{node}:{iteration}\\n')",
                "final_message = Path(argv[argv.index('--output-last-message') + 1])",
                "if node == 'implement-story-loop':",
                "    (artifacts / 'implementation-state.json').write_text('{\"status\":\"ok\"}', encoding='utf-8')",
                "    (artifacts / 'progress.md').write_text('real progress', encoding='utf-8')",
                "    passed = iteration >= 2",
                "    stories = [{'id':'S1','passes':True}, {'id':'S2','passes':passed}]",
                "    (artifacts / 'stories.json').write_text(json.dumps(stories), encoding='utf-8')",
                "    final_message.write_text('COMPLETE', encoding='utf-8')",
                "    print('COMPLETE')",
                "else:",
                "    (artifacts / 'after.md').write_text('after node', encoding='utf-8')",
                "    final_message.write_text('after', encoding='utf-8')",
                "    print('after')",
            ]
        ),
        encoding="utf-8",
    )
    write_project_config(project_root, [sys.executable, str(fake_codex)])
    context = create_run_context(
        control_root,
        WorkflowInput(workflow="loop-test", goal="loop", project_root=str(project_root)),
        run_id="run_loop_completion",
    )
    prepare_run(context)

    result = run_e2e_workflow(context, use_worktree=False)

    assert result.return_code == 0
    assert (context.run_dir / "artifacts" / "loop-log.txt").read_text(
        encoding="utf-8"
    ).splitlines() == [
        "implement-story-loop:1",
        "implement-story-loop:2",
        "after:0",
    ]


def test_spec_driven_acceptance_matrix_gate_stops_before_downstream_report(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    control_root = tmp_path / "control"
    project_root = tmp_path / "apps" / "app-a"
    control_root.mkdir()
    project_root.mkdir(parents=True)
    write_definition(
        control_root,
        name="spec-driven",
        primary_inputs=["goal"],
        nodes=[
            {"id": "acceptance-matrix", "required_artifacts": ["acceptance-matrix.json"]},
            {
                "id": "production-report",
                "depends_on": ["acceptance-matrix"],
                "required_artifacts": ["production-report.json"],
            },
        ],
    )
    fake_codex = tmp_path / "fake_acceptance_codex.py"
    fake_codex.write_text(
        "\n".join(
            [
                "import json, os, sys",
                "from pathlib import Path",
                "argv = sys.argv[1:]",
                "node = os.environ['AO_NODE_ID']",
                "artifacts = Path(os.environ['AO_ARTIFACTS_DIR'])",
                "final_message = Path(argv[argv.index('--output-last-message') + 1])",
                "if node == 'acceptance-matrix':",
                "    matrix = {'result':'PASS','acceptance_items':[{'acceptance_id':'AC-012','story_id':'ST-008','result':'PASS','behavior':'Dashboard UI marks a message handled','evidence':{'evidence_types':['command'],'commands':[{'command':'go test ./...','exit_code':0,'source':'artifacts/verify.txt'}]}}]}",
                "    (artifacts / 'verify.txt').write_text('ok', encoding='utf-8')",
                "    (artifacts / 'acceptance-matrix.json').write_text(json.dumps(matrix), encoding='utf-8')",
                "else:",
                "    (artifacts / 'production-report.json').write_text('{\"result\":\"PASS\"}', encoding='utf-8')",
                "final_message.write_text(node, encoding='utf-8')",
                "print(node)",
            ]
        ),
        encoding="utf-8",
    )
    write_project_config(project_root, [sys.executable, str(fake_codex)])
    context = create_run_context(
        control_root,
        WorkflowInput(workflow="spec-driven", goal="ui gate", project_root=str(project_root)),
        run_id="run_acceptance_gate",
    )
    prepare_run(context)

    with pytest.raises(RuntimeError, match="browser/UI evidence"):
        run_e2e_workflow(context, use_worktree=False)

    state = json.loads((context.run_dir / "run.json").read_text(encoding="utf-8"))
    assert state["failed_node"] == "acceptance-matrix"
    assert not (context.run_dir / "artifacts" / "production-report.json").exists()


def test_spec_driven_frontend_selection_gate_stops_before_implementation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AGENTIC_FACTORY_HOME", str(tmp_path / "home"))
    control_root = tmp_path / "control"
    project_root = tmp_path / "apps" / "app-a"
    control_root.mkdir()
    project_root.mkdir(parents=True)
    write_definition(
        control_root,
        name="spec-driven",
        primary_inputs=["goal"],
        nodes=[
            {
                "id": "frontend-template-resolution",
                "required_artifacts": [
                    "frontend-template-selection.json",
                    "frontend-template-rationale.md",
                ],
            },
            {
                "id": "implement-story-loop",
                "depends_on": ["frontend-template-resolution"],
                "required_artifacts": ["implementation-state.json"],
            },
        ],
    )
    fake_codex = tmp_path / "fake_frontend_codex.py"
    fake_codex.write_text(
        "\n".join(
            [
                "import json, os, sys",
                "from pathlib import Path",
                "argv = sys.argv[1:]",
                "node = os.environ['AO_NODE_ID']",
                "artifacts = Path(os.environ['AO_ARTIFACTS_DIR'])",
                "final_message = Path(argv[argv.index('--output-last-message') + 1])",
                "if node == 'frontend-template-resolution':",
                "    (artifacts / 'project-inspection.json').write_text(json.dumps({'frontend': {'exists': False}}), encoding='utf-8')",
                "    (artifacts / 'production-spec.md').write_text('## Frontend Product Surface\\nDashboard UI', encoding='utf-8')",
                "    selection = {'frontend_required': True, 'template_id': 'observability-dashboard', 'required_views': ['summary'], 'required_components': ['AppShell'], 'required_states': ['loading'], 'required_interactions': ['navigate'], 'api_contracts': ['GET /api/dashboard/summary'], 'e2e_scenarios': ['open summary'], 'visual_quality_rubric': ['operational density']}",
                "    (artifacts / 'frontend-template-selection.json').write_text(json.dumps(selection), encoding='utf-8')",
                "    (artifacts / 'frontend-template-rationale.md').write_text('# rationale\\nreal text', encoding='utf-8')",
                "else:",
                "    (artifacts / 'implementation-state.json').write_text('{\"status\":\"PASSED\"}', encoding='utf-8')",
                "final_message.write_text(node, encoding='utf-8')",
                "print(node)",
            ]
        ),
        encoding="utf-8",
    )
    write_project_config(project_root, [sys.executable, str(fake_codex)])
    context = create_run_context(
        control_root,
        WorkflowInput(workflow="spec-driven", goal="frontend gate", project_root=str(project_root)),
        run_id="run_frontend_selection_gate",
    )
    prepare_run(context)

    with pytest.raises(RuntimeError, match="frontend_implementation"):
        run_e2e_workflow(context, use_worktree=False)

    state = json.loads((context.run_dir / "run.json").read_text(encoding="utf-8"))
    assert state["failed_node"] == "frontend-template-resolution"
    assert not (context.run_dir / "artifacts" / "implementation-state.json").exists()


def _git(cwd: Path | str, *args: str) -> str:
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
