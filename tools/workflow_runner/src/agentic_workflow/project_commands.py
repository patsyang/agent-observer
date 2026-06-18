from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from .dev_server import dev, status_dev, stop_dev

APP_ROOT = Path("apps/agentic_factory")
WORKFLOW_RUNNER_ROOT = Path("tools/workflow_runner")


def run_project_command(repo_root: Path, command: str) -> int:
    actions = {
        "setup": setup,
        "lint": lint,
        "test": test,
        "e2e": e2e,
        "verify": verify,
        "package-collector": package_collector,
        "dev": dev,
        "stop-dev": stop_dev,
        "status-dev": status_dev,
    }
    return actions[command](repo_root)


def setup(repo_root: Path) -> int:
    return _run(["uv", "sync", "--project", str(WORKFLOW_RUNNER_ROOT)], repo_root)


def lint(repo_root: Path) -> int:
    return _run(
        ["uv", "run", "ruff", "check", "src", "tests", "e2e"],
        repo_root / WORKFLOW_RUNNER_ROOT,
    )


def test(repo_root: Path) -> int:
    return _run(["uv", "run", "python", "-m", "pytest"], repo_root / WORKFLOW_RUNNER_ROOT)


def e2e(repo_root: Path) -> int:
    return _run([sys.executable, "tools/workflow_runner/e2e/runner.py"], repo_root)


def verify(repo_root: Path) -> int:
    return _run_many(
        [([sys.executable, "scripts/ao.py", name], repo_root) for name in _verify_steps()]
    )


def package_collector(repo_root: Path) -> int:
    app = repo_root / APP_ROOT
    target = repo_root / "dist/collector/python"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    code = _run(["uv", "build", "--project", str(app / "collector")], repo_root)
    if code:
        return code
    for path in (app / "collector/dist").glob("*"):
        destination = target / path.name
        if path.is_dir():
            shutil.copytree(path, destination)
        else:
            shutil.copy2(path, destination)
    print(f"Collector package written to {target}")
    return 0


def _verify_steps() -> tuple[str, ...]:
    return ("agentic-check", "lint", "test", "e2e")


def _run_many(commands: list[tuple[list[str], Path]]) -> int:
    for command, cwd in commands:
        code = _run(command, cwd)
        if code:
            return code
    return 0


def _run(command: list[str], cwd: Path) -> int:
    print("+ " + " ".join(str(part) for part in command))
    return subprocess.run(_resolve_command(command), cwd=cwd, check=False).returncode


def _resolve_command(command: list[str]) -> list[str]:
    executable = shutil.which(command[0])
    return [executable, *command[1:]] if executable else command
