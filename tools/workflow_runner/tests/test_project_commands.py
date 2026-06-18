from pathlib import Path

from agentic_workflow import project_commands


def test_lint_uses_workflow_runner_even_when_app_sources_exist(tmp_path: Path, monkeypatch) -> None:
    create_app_sources(tmp_path)
    commands = []

    def fake_run(command: list[str], cwd: Path) -> int:
        commands.append((command, cwd))
        return 0

    monkeypatch.setattr(project_commands, "_run", fake_run)

    assert project_commands.lint(tmp_path) == 0

    assert [command for command, _cwd in commands] == [
        ["uv", "run", "ruff", "check", "src", "tests", "e2e"]
    ]
    assert commands[0][1] == tmp_path / "tools/workflow_runner"


def test_test_uses_workflow_runner_even_when_app_sources_exist(tmp_path: Path, monkeypatch) -> None:
    create_app_sources(tmp_path)
    commands = []

    def fake_run(command: list[str], cwd: Path) -> int:
        commands.append((command, cwd))
        return 0

    monkeypatch.setattr(project_commands, "_run", fake_run)

    assert project_commands.test(tmp_path) == 0

    assert [command for command, _cwd in commands] == [["uv", "run", "python", "-m", "pytest"]]
    assert commands[0][1] == tmp_path / "tools/workflow_runner"


def test_e2e_uses_workflow_runner_even_when_app_sources_exist(tmp_path: Path, monkeypatch) -> None:
    create_app_sources(tmp_path)
    commands = []

    def fake_run(command: list[str], cwd: Path) -> int:
        commands.append((command, cwd))
        return 0

    monkeypatch.setattr(project_commands, "_run", fake_run)

    assert project_commands.e2e(tmp_path) == 0

    assert [command for command, _cwd in commands] == [
        [project_commands.sys.executable, "tools/workflow_runner/e2e/runner.py"]
    ]
    assert commands[0][1] == tmp_path


def create_app_sources(repo_root: Path) -> None:
    app = repo_root / "apps" / "agentic_factory"
    for name in ("backend", "collector", "frontend", "e2e"):
        (app / name).mkdir(parents=True)
