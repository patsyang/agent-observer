from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

HOME_ENV = "AGENTIC_FACTORY_HOME"
RUN_INDEX = "run-index.json"


def agent_home() -> Path:
    configured = os.environ.get(HOME_ENV)
    return (Path(configured) if configured else Path.home() / ".agentic_factory").resolve()


def project_slug(project_root: Path, name: str | None = None) -> str:
    root = project_root.resolve()
    digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:8]
    base = name or root.name or "project"
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "-", base).strip("-") or "project"
    return f"{safe_name}-{digest}"


def default_workspace_root(project_root: Path) -> Path:
    return (project_root / ".agentic" / "workspace").resolve()


def workspace_root(project_root: Path, name: str | None = None) -> Path:
    return default_workspace_root(project_root)


def run_dir(project_root: Path, run_id: str, name: str | None = None) -> Path:
    return workspace_root(project_root, name=name) / "runs" / run_id


def ensure_workspace_ignored(project_root: Path, workspace_root_path: Path) -> None:
    root = project_root.resolve()
    workspace = workspace_root_path.resolve()
    try:
        relative = workspace.relative_to(root)
    except ValueError:
        return
    git_dir = root / ".git"
    if not git_dir.is_dir():
        return
    pattern = f"/{relative.as_posix().rstrip('/')}/"
    exclude = git_dir / "info" / "exclude"
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if pattern in {line.strip() for line in existing.splitlines()}:
        return
    exclude.parent.mkdir(parents=True, exist_ok=True)
    suffix = "" if not existing or existing.endswith("\n") else "\n"
    exclude.write_text(f"{existing}{suffix}{pattern}\n", encoding="utf-8")


def write_run_index(
    *,
    run_id: str,
    project_id: str | None,
    project_name: str | None,
    project_root: Path,
    run_dir_path: Path,
    worktrees_dir_path: Path | None = None,
    logs_dir_path: Path | None = None,
) -> None:
    home = agent_home()
    home.mkdir(parents=True, exist_ok=True)
    path = home / RUN_INDEX
    index = _read_json(path, default={})
    runs = dict(index.get("runs", {}))
    runs[run_id] = {
        "project_id": project_id,
        "project_name": project_name,
        "project_root": str(project_root.resolve()),
        "run_dir": str(run_dir_path.resolve()),
        "worktrees_dir": str(worktrees_dir_path.resolve()) if worktrees_dir_path else None,
        "logs_dir": str(logs_dir_path.resolve()) if logs_dir_path else None,
    }
    path.write_text(
        json.dumps({"runs": runs}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def find_run(run_id: str) -> dict[str, str] | None:
    path = agent_home() / RUN_INDEX
    payload = _read_json(path, default={})
    runs = payload.get("runs", {})
    item = runs.get(run_id)
    return dict(item) if isinstance(item, dict) else None


def resolve_run_dir(repo_root: Path, run_id: str) -> Path:
    local_run_dir = repo_root / "ai_docs" / "runs" / run_id
    if local_run_dir.exists():
        return local_run_dir
    run = find_run(run_id)
    if run and run.get("run_dir"):
        return Path(run["run_dir"])
    return local_run_dir


def _read_json(path: Path, *, default: dict) -> dict:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default
