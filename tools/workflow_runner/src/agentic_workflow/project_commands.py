from __future__ import annotations

import json
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
    business_commands = _business_verify_commands(repo_root)
    if business_commands:
        return _run_many(business_commands)
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


def _business_verify_commands(repo_root: Path) -> list[tuple[list[str], Path]]:
    commands: list[tuple[list[str], Path]] = []
    if (repo_root / "backend" / "tests").exists():
        commands.append(([sys.executable, "-m", "pytest", "backend/tests"], repo_root))
    frontend_package = repo_root / "frontend" / "package.json"
    frontend_scripts = _package_scripts(frontend_package)
    if "test" in frontend_scripts:
        commands.append((["npm", "--prefix", "frontend", "test", "--", "--run"], repo_root))
    if "build" in frontend_scripts:
        commands.append((["npm", "--prefix", "frontend", "run", "build"], repo_root))
    if "e2e" in frontend_scripts:
        commands.append((["npm", "--prefix", "frontend", "run", "e2e"], repo_root))
    return commands


def _package_scripts(package_path: Path) -> dict[str, str]:
    if not package_path.exists():
        return {}
    payload = json.loads(package_path.read_text(encoding="utf-8"))
    scripts = payload.get("scripts", {})
    return scripts if isinstance(scripts, dict) else {}


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
