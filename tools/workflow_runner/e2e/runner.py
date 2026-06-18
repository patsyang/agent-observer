from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WORKFLOW_RUNNER_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]


FAKE_CODEX = Path(__file__).with_name("fake_codex.py")
DEFINITIONS = ("small-change", "plan-execute", "spec-driven")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="ao-workflow-e2e-") as temp_dir:
        os.environ["AGENTIC_FACTORY_HOME"] = str(Path(temp_dir) / "home")
        repo_root = Path(temp_dir) / "control"
        project_root = Path(temp_dir) / "project"
        _create_project(repo_root, project_root)
        results = [
            _run_scenario(
                repo_root,
                project_root=project_root,
                run_id="run_small_change_e2e",
                workflow="small-change",
                args=[
                    "--scope",
                    "apps/agentic_factory",
                    "--goal",
                    "修复 Dashboard 未读消息显示",
                ],
                expected_nodes=["execute", "verify-and-fix", "review"],
            ),
            _run_scenario(
                repo_root,
                project_root=project_root,
                run_id="run_plan_execute_e2e",
                workflow="plan-execute",
                args=[
                    "--scope",
                    "apps/agentic_factory",
                    "--goal",
                    "实现 Dashboard 过滤与刷新闭环",
                ],
                expected_nodes=["plan", "parallel-workers", "review", "fix-loop"],
            ),
            _run_scenario(
                repo_root,
                project_root=project_root,
                run_id="run_spec_driven_e2e",
                workflow="spec-driven",
                args=[
                    "--spec-path",
                    "apps/agentic_factory/specs/001-demo/spec.md",
                ],
                expected_nodes=[
                    "generate-product-prd",
                    "generate-production-spec",
                    "generate-story-map",
                    "implement-loop",
                    "independent-review",
                    "fix-loop",
                    "release-readiness-gate",
                    "e2e-proof",
                    "acceptance-matrix",
                ],
            ),
        ]
        print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


def _create_project(repo_root: Path, project_root: Path) -> None:
    definitions_dir = repo_root / ".agentic" / "workflow" / "definitions"
    definitions_dir.mkdir(parents=True)
    for name in DEFINITIONS:
        source = REPO_ROOT / ".agentic" / "workflow" / "definitions" / f"{name}.json"
        shutil.copyfile(source, definitions_dir / f"{name}.json")

    app_root = project_root / "apps" / "agentic_factory"
    (app_root / "frontend" / "dashboard").mkdir(parents=True)
    (app_root / "specs" / "001-demo").mkdir(parents=True)
    (app_root / "specs" / "001-demo" / "spec.md").write_text(
        "# Demo Spec\n\nDashboard E2E acceptance.\n",
        encoding="utf-8",
    )
    _write_project_config(project_root)
    _git(project_root, "init")
    _git(project_root, "config", "user.email", "e2e@example.invalid")
    _git(project_root, "config", "user.name", "Workflow E2E")
    _git(project_root, "add", ".")
    _git(project_root, "commit", "-m", "initial e2e project")


def _run_scenario(
    repo_root: Path,
    *,
    project_root: Path,
    run_id: str,
    workflow: str,
    args: list[str],
    expected_nodes: list[str],
) -> dict[str, object]:
    argv = [
        "--repo-root",
        str(repo_root),
        "run",
        "--workflow",
        workflow,
        "--run-id",
        run_id,
        "--project-root",
        str(project_root),
        "--skip-verify",
        *args,
    ]
    exit_code = _call_workflow(argv)
    if exit_code != 0:
        raise AssertionError(f"{workflow} exited with {exit_code}")

    run_dir = _run_dir(run_id)
    run_state = _read_json(run_dir / "run.json")
    acceptance = _read_json(run_dir / "acceptance-matrix.json")
    actual_nodes = [node["node_id"] for node in run_state["nodes"]]
    if run_state["status"] != "PASSED":
        raise AssertionError(f"{workflow} status={run_state['status']}")
    if actual_nodes != expected_nodes:
        raise AssertionError(f"{workflow} nodes={actual_nodes}")
    if acceptance[0]["result"] != "PASS":
        raise AssertionError(f"{workflow} acceptance did not pass")
    if not (run_dir / "run-report.md").exists():
        raise AssertionError(f"{workflow} missing run-report.md")

    worktree = run_state["worktree"]
    if not worktree or not Path(worktree["path"]).exists():
        raise AssertionError(f"{workflow} missing worktree")

    status_code = _call_workflow(["--repo-root", str(repo_root), "status", "--run-id", run_id])
    resume_code = _call_workflow(["--repo-root", str(repo_root), "resume", "--run-id", run_id])
    if status_code != 0 or resume_code != 0:
        raise AssertionError(f"{workflow} status/resume failed")

    return {
        "workflow": workflow,
        "run_id": run_id,
        "project_scope": run_state["project_scope"],
        "nodes": actual_nodes,
        "worktree": worktree["path"],
        "acceptance": acceptance[0]["result"],
    }


def _write_project_config(project_root: Path) -> None:
    config_dir = project_root / ".agentic"
    config_dir.mkdir(parents=True)
    (config_dir / "project.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": "agentic-factory-e2e",
                "project_name": "agentic-factory-e2e",
                "adapter": {
                    "id": "codex",
                    "command": [sys.executable, str(FAKE_CODEX)],
                },
                "verify": {
                    "command": [sys.executable, "-c", "print('verify')"],
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _run_dir(run_id: str) -> Path:
    home = Path(os.environ["AGENTIC_FACTORY_HOME"])
    index = json.loads((home / "run-index.json").read_text(encoding="utf-8"))
    return Path(index["runs"][run_id]["run_dir"])


def _call_workflow(argv: list[str]) -> int:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(WORKFLOW_RUNNER_ROOT / "src")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from agentic_workflow.cli import main; main()",
            *argv,
        ],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
    return result.returncode


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _git(repo_root: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())


if __name__ == "__main__":
    raise SystemExit(main())
