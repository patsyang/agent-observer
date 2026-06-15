from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    commands = discover_commands()
    if not commands:
        print("Project verification entrypoint: no project tests discovered; skipped.")
        return 0

    failed = False
    for command in commands:
        print(f"Project verification entrypoint: running {' '.join(command)}")
        result = subprocess.run(command, cwd=ROOT)
        if result.returncode != 0:
            failed = True
    return 1 if failed else 0


def discover_commands() -> list[list[str]]:
    commands: list[list[str]] = []
    if has_python_tests():
        commands.append([sys.executable, "-m", "pytest"])
    if (ROOT / "go.mod").is_file():
        commands.append(["go", "test", "./..."])
    node_command = node_test_command()
    if node_command:
        commands.append(node_command)
    return commands


def has_python_tests() -> bool:
    return any(
        path.exists()
        for path in (
            ROOT / "pytest.ini",
            ROOT / "pyproject.toml",
            ROOT / "setup.cfg",
            ROOT / "tests",
        )
    )


def node_test_command() -> list[str]:
    package_path = ROOT / "package.json"
    if not package_path.is_file():
        return []
    try:
        payload = json.loads(package_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    test_script = str(payload.get("scripts", {}).get("test", "")).strip()
    if not test_script or "no test specified" in test_script.lower():
        return []
    return ["npm", "test"]


if __name__ == "__main__":
    raise SystemExit(main())
