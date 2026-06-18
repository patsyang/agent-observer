from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .project_config import ProjectConfigError, adapter_health, load_project_config, verify_health
from .stack_contract import StackContractError, load_stack_contract
from .workspace import agent_home, default_workspace_root

REGISTRY_FILE = "registry.json"


class ProjectRegistryError(ValueError):
    pass


@dataclass(frozen=True)
class ProjectRecord:
    project_id: str
    name: str
    root_path: Path
    workspace_root: Path
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "root_path": str(self.root_path),
            "workspace_root": str(self.workspace_root),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def register_project(
    *,
    name: str,
    root: Path,
    workspace_root: Path | None = None,
) -> ProjectRecord:
    root_path = root.resolve()
    if not root_path.exists() or not root_path.is_dir():
        raise ProjectRegistryError(f"项目目录不存在: {root}")
    workspace_root_path = _resolve_workspace_root(root_path, workspace_root)
    now = _now()
    payload = _load_registry()
    projects = _project_dict(payload)
    existing = projects.get(name)
    created_at = existing.get("created_at", now) if existing else now
    record = ProjectRecord(
        project_id=name,
        name=name,
        root_path=root_path,
        workspace_root=workspace_root_path,
        created_at=created_at,
        updated_at=now,
    )
    projects[name] = record.to_dict()
    _write_registry({"projects": projects})
    return record


def rebind_project(*, identifier: str, root: Path) -> ProjectRecord:
    existing = get_project(identifier)
    if existing is None:
        raise ProjectRegistryError(f"项目未注册: {identifier}")
    return register_project(name=existing.name, root=root)


def get_project(identifier: str) -> ProjectRecord | None:
    projects = _project_dict(_load_registry())
    item = projects.get(identifier)
    if item is None:
        for candidate in projects.values():
            if candidate.get("name") == identifier:
                item = candidate
                break
    return _record_from_dict(item) if item else None


def list_projects() -> list[ProjectRecord]:
    projects = _project_dict(_load_registry())
    return [_record_from_dict(item) for item in sorted(projects.values(), key=lambda v: v["name"])]


def project_status_payload(identifier: str) -> tuple[dict[str, object], bool]:
    record = get_project(identifier)
    if record is None:
        raise ProjectRegistryError(f"项目未注册: {identifier}")
    payload: dict[str, object] = record.to_dict()
    try:
        config = load_project_config(record.root_path)
    except ProjectConfigError as error:
        payload["project_config_status"] = "failed"
        payload["project_config_error"] = str(error)
        return payload, False

    health = adapter_health(config.adapter)
    try:
        stack_contract = load_stack_contract(record.root_path, project_id=record.project_id)
        payload["stack_contract_status"] = "passed"
        payload["stack_contract"] = stack_contract.ref.to_dict()
        stack_ok = True
    except StackContractError as error:
        payload["stack_contract_status"] = "failed"
        payload["stack_contract_error"] = str(error)
        stack_ok = False
    verify = verify_health(record.root_path, config.verify)
    payload["project_config_status"] = "passed" if health["ok"] and verify["ok"] else "failed"
    payload["project_config"] = config.to_dict()
    payload["adapter_health"] = health
    payload["verify_health"] = verify
    return payload, bool(health["ok"] and verify["ok"] and stack_ok)


def resolve_project_root(
    *,
    control_repo_root: Path,
    project: str | None,
    project_root: str | None,
) -> tuple[Path, ProjectRecord | None]:
    if project and project_root:
        raise ProjectRegistryError("不能同时提供 --project 和 --project-root")
    if project:
        record = get_project(project)
        if record is None:
            raise ProjectRegistryError(f"项目未注册: {project}")
        if not record.root_path.exists():
            raise ProjectRegistryError(f"项目目录不存在: {record.root_path}")
        return record.root_path, record
    if project_root:
        path = Path(project_root)
        resolved = path if path.is_absolute() else control_repo_root / path
        resolved = resolved.resolve()
        if not resolved.exists() or not resolved.is_dir():
            raise ProjectRegistryError(f"项目目录不存在: {project_root}")
        return resolved, None
    return control_repo_root.resolve(), None


def _load_registry() -> dict:
    path = _registry_path()
    if not path.exists():
        return {"projects": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"projects": {}}


def _write_registry(payload: dict) -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _registry_path() -> Path:
    return agent_home() / REGISTRY_FILE


def _project_dict(payload: dict) -> dict[str, dict]:
    projects = payload.get("projects", {})
    return dict(projects) if isinstance(projects, dict) else {}


def _record_from_dict(item: dict) -> ProjectRecord:
    if "workspace_root" not in item:
        name = item.get("name") or item.get("project_id") or "<unknown>"
        raise ProjectRegistryError(f"项目注册记录缺少 workspace_root: {name}")
    return ProjectRecord(
        project_id=str(item["project_id"]),
        name=str(item["name"]),
        root_path=Path(str(item["root_path"])),
        workspace_root=Path(str(item["workspace_root"])),
        created_at=str(item["created_at"]),
        updated_at=str(item["updated_at"]),
    )


def _resolve_workspace_root(project_root: Path, workspace_root: Path | None) -> Path:
    if workspace_root is None:
        return default_workspace_root(project_root)
    return (workspace_root if workspace_root.is_absolute() else project_root / workspace_root).resolve()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
