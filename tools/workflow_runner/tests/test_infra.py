import json
import shutil
from pathlib import Path

from agentic_workflow.infra_files import InfraFile, entry_bytes
from agentic_workflow.infra import configure_project_runtime, init_project, plan_update

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_init_project_creates_agentic_development_project(tmp_path: Path) -> None:
    project = tmp_path / "new-product"

    result = init_project(
        infra_root=REPO_ROOT,
        target_root=project,
        project_name="New Product",
    )

    assert result["infra_version"] == "0.1.0"
    assert (project / "AGENTS.md").exists()
    assert (project / "commands" / "ao-spec.md").exists()
    assert (project / "commands" / "ao-infra.md").exists()
    assert (project / ".codex" / "skills" / "ao-spec" / "SKILL.md").exists()
    assert (project / ".codex" / "skills" / "ao-infra" / "SKILL.md").exists()
    assert (project / ".agentic" / "workflow" / "definitions" / "spec-driven.json").exists()
    assert (
        project / ".agentic" / "workflow" / "definitions" / "control-plane-change.json"
    ).exists()
    assert (project / ".agentic" / "workflow" / "templates" / "spec" / "production-spec.md").exists()
    assert (project / ".agentic" / "workflow" / "templates" / "plan" / "slice-brief.md").exists()
    assert (project / ".agentic" / "workflow" / "schemas" / "task-graph.schema.json").exists()
    assert (project / ".agentic" / "runtime-adapters" / "codex.json").exists()
    assert (project / ".agentic" / "runtime-adapters" / "qoder-cn.json").exists()
    assert (project / ".agentic" / "runtime-adapters" / "opencode.json").exists()
    assert (project / ".agentic" / "runtime-adapters" / "model-catalog.json").exists()
    project_config = json.loads((project / ".agentic" / "project.json").read_text(encoding="utf-8"))
    assert project_config["model"]["id"] == "codex-gpt-5"
    assert project_config["adapter"] == {
        "id": "generic-cli",
        "command": ["codex"],
        "profile": ".agentic/runtime-adapters/codex.json",
    }
    assert not (project / ".agentic" / "spec-templates" / "spec.md").exists()
    assert (project / "scripts" / "ao.py").exists()
    assert not list((project / "scripts").glob("*.ps1"))
    assert (project / "tools" / "workflow_runner" / "pyproject.toml").exists()
    assert not (project / "ai_docs").exists()
    assert not (project / "backend").exists()
    assert not (project / "frontend").exists()
    assert not (project / "collector").exists()
    assert not (project / "apps" / "agentic_factory").exists()
    assert not (project / "refs" / "workflow").exists()

    lock = json.loads((project / "agentic.lock.json").read_text(encoding="utf-8"))
    assert lock["project_name"] == "New Product"
    assert "commands/ao-spec.md" in lock["files"]
    assert "commands/ao-infra.md" in lock["files"]
    assert ".agentic/workflow/spec-driven.md" in lock["files"]
    assert ".agentic/workflow/control-plane-change.md" in lock["files"]
    assert "scripts/ao.py" in lock["files"]
    assert "tools/workflow_runner/pyproject.toml" in lock["files"]
    assert ".agentic/runtime-adapters/codex.json" in lock["files"]
    assert ".agentic/runtime-adapters/opencode.json" in lock["files"]
    assert not any(path.startswith("ai_docs/") for path in lock["files"])
    assert "README.md" not in lock["files"]
    assert ".agentic/project.json" not in lock["files"]
    assert "# New Product" in (project / "README.md").read_text(encoding="utf-8")
    command_text = (project / "commands" / "ao-spec.md").read_text(encoding="utf-8")
    assert "/ao-spec <项目名> -prd <PRD路径>" in command_text
    assert "source-prd.md" in command_text


def test_update_project_reports_unchanged_for_fresh_init(tmp_path: Path) -> None:
    project = tmp_path / "new-product"
    init_project(
        infra_root=REPO_ROOT,
        target_root=project,
        project_name="New Product",
    )

    plan = plan_update(project_root=project, infra_root=REPO_ROOT)

    assert plan["summary"] == {"unchanged": len(plan["items"])}


def test_update_project_reports_conflict_for_dual_changes(tmp_path: Path) -> None:
    project = tmp_path / "new-product"
    init_project(
        infra_root=REPO_ROOT,
        target_root=project,
        project_name="New Product",
    )
    _append_text(project / "commands" / "ao-spec.md", "\n本地项目修改\n")

    infra_root = tmp_path / "infra"
    _copy_infra_source(infra_root)
    _append_text(
        infra_root / "agentic-infra" / "templates" / "project" / "commands" / "ao-spec.md",
        "\ninfra 新版本修改\n",
    )

    plan = plan_update(project_root=project, infra_root=infra_root)
    item = next(item for item in plan["items"] if item["path"] == "commands/ao-spec.md")

    assert item["status"] == "conflict"


def test_init_project_writes_generic_cli_adapter_for_qoder_model(tmp_path: Path) -> None:
    project = tmp_path / "new-product"

    result = init_project(
        infra_root=REPO_ROOT,
        target_root=project,
        project_name="New Product",
        model_id="qoder-cn-qwen",
    )

    config = json.loads((project / ".agentic" / "project.json").read_text(encoding="utf-8"))
    assert result["model_id"] == "qoder-cn-qwen"
    assert config["model"]["id"] == "qoder-cn-qwen"
    assert config["adapter"] == {
        "id": "generic-cli",
        "command": ["qoderclicn"],
        "profile": ".agentic/runtime-adapters/qoder-cn.json",
    }


def test_init_project_writes_generic_cli_adapter_for_opencode_model(tmp_path: Path) -> None:
    project = tmp_path / "new-product"

    result = init_project(
        infra_root=REPO_ROOT,
        target_root=project,
        project_name="New Product",
        model_id="opencode-default",
    )

    config = json.loads((project / ".agentic" / "project.json").read_text(encoding="utf-8"))
    catalog = json.loads(
        (project / ".agentic" / "runtime-adapters" / "model-catalog.json").read_text(
            encoding="utf-8"
        )
    )
    assert result["model_id"] == "opencode-default"
    assert config["model"]["id"] == "opencode-default"
    assert config["adapter"] == {
        "id": "generic-cli",
        "command": ["opencode"],
        "profile": ".agentic/runtime-adapters/opencode.json",
    }
    assert any(model["id"] == "opencode-default" for model in catalog["models"])


def test_init_project_rejects_unknown_model(tmp_path: Path) -> None:
    project = tmp_path / "new-product"

    try:
        init_project(
            infra_root=REPO_ROOT,
            target_root=project,
            project_name="New Product",
            model_id="missing-model",
        )
    except ValueError as error:
        assert "unknown model id" in str(error)
    else:
        raise AssertionError("unknown model must fail")


def test_configure_runtime_preserves_existing_project_config_fields(tmp_path: Path) -> None:
    project = tmp_path / "new-product"
    (project / ".agentic").mkdir(parents=True)
    (project / ".agentic" / "project.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": "stable-id",
                "project_name": "Stable Name",
                "runtime": {
                    "runs_dir": ".ao/runs",
                    "worktrees_dir": ".ao/worktrees",
                    "logs_dir": ".ao/logs",
                },
                "adapter": {"id": "codex", "command": ["codex"]},
                "verify": {"command": ["python", "-m", "pytest"]},
            }
        ),
        encoding="utf-8",
    )

    configure_project_runtime(
        infra_root=REPO_ROOT,
        project_root=project,
        project_name="Display Name",
        model_id="qoder-cn-qwen",
    )

    config = json.loads((project / ".agentic" / "project.json").read_text(encoding="utf-8"))
    assert config["project_id"] == "stable-id"
    assert config["project_name"] == "Stable Name"
    assert config["runtime"]["runs_dir"] == ".ao/runs"
    assert config["verify"]["command"] == ["python", "-m", "pytest"]
    assert config["model"]["id"] == "qoder-cn-qwen"
    assert config["adapter"]["profile"] == ".agentic/runtime-adapters/qoder-cn.json"
    assert (project / ".agentic" / "runtime-adapters" / "qoder-cn.json").exists()


def test_configure_runtime_fails_before_writing_missing_profile(tmp_path: Path) -> None:
    project = tmp_path / "new-product"
    (project / ".agentic").mkdir(parents=True)
    config = project / ".agentic" / "project.json"
    config.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": "stable-id",
                "project_name": "Stable Name",
                "adapter": {"id": "codex", "command": ["codex"]},
                "verify": {"command": ["python", "-m", "pytest"]},
            }
        ),
        encoding="utf-8",
    )
    infra_root = tmp_path / "infra"
    _copy_infra_source(infra_root)
    shutil.copytree(REPO_ROOT / ".agentic", infra_root / ".agentic")
    (infra_root / ".agentic" / "runtime-adapters" / "qoder-cn.json").unlink()

    try:
        configure_project_runtime(
            infra_root=infra_root,
            project_root=project,
            project_name="Stable Name",
            model_id="qoder-cn-qwen",
        )
    except ValueError as error:
        assert "runtime profile source not found" in str(error)
    else:
        raise AssertionError("missing profile must fail")

    unchanged = json.loads(config.read_text(encoding="utf-8"))
    assert unchanged["adapter"] == {"id": "codex", "command": ["codex"]}


def test_entry_bytes_preserves_crlf_when_rendering(tmp_path: Path) -> None:
    source = tmp_path / "template.md"
    source.write_bytes(b"# {{PROJECT_NAME}}\r\n\r\ncontent\r\n")

    rendered = entry_bytes(
        InfraFile(path="template.md", source=source, render=True),
        {"PROJECT_NAME": "Demo"},
    )

    assert rendered == b"# Demo\r\n\r\ncontent\r\n"


def _append_text(path: Path, text: str) -> None:
    path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")


def _copy_infra_source(target_root: Path) -> None:
    shutil.copytree(REPO_ROOT / "agentic-infra", target_root / "agentic-infra")
    shutil.copytree(
        REPO_ROOT / "tools" / "workflow_runner",
        target_root / "tools" / "workflow_runner",
        ignore=shutil.ignore_patterns(
            ".venv",
            ".pytest_cache",
            ".ruff_cache",
            "__pycache__",
            "*.pyc",
            "*.pyo",
        ),
    )
