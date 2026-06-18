from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .infra import (
    configure_project_runtime,
    init_project,
    list_model_choices,
    resolve_model_config,
)
from .project_config import (
    PROJECT_CONFIG_PATH,
    ProjectConfigError,
    adapter_health,
    load_project_config,
    verify_health,
)
from .project_registry import ProjectRecord, register_project
from .stack_contract import STACK_CONTRACT_RELATIVE_PATH, StackContractError, load_stack_contract
from .stack_profiles import build_stack_contract_from_profile, list_stack_profiles


NEEDS_MODEL_SELECTION = "NEEDS_MODEL_SELECTION"
REGISTERED = "REGISTERED"
REGISTERED_READY = "REGISTERED_READY"


@dataclass(frozen=True)
class NeedsModelSelection(ValueError):
    payload: dict[str, Any]

    def __str__(self) -> str:
        return str(self.payload.get("message") or NEEDS_MODEL_SELECTION)


def register_project_onboarding(
    *,
    infra_root: Path,
    name: str,
    root: Path,
    model_id: str | None = None,
    stack_profile_id: str | None = None,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    root_path = root.resolve()
    config_path = root_path / PROJECT_CONFIG_PATH
    existing_model_id = _existing_valid_model_id(infra_root, config_path) if config_path.exists() else None
    needs_model = model_id is None and existing_model_id is None
    if needs_model:
        raise NeedsModelSelection(_needs_model_payload(infra_root, name=name, root=root_path))

    selected_model = model_id or existing_model_id
    runtime: dict[str, Any]
    if root_path.exists():
        if _can_initialize_infra(root_path):
            init_result = init_project(
                infra_root=infra_root,
                target_root=root_path,
                project_name=name,
                model_id=str(selected_model),
                force=True,
            )
            runtime = {
                "project_root": str(root_path),
                "model_id": init_result["model_id"],
                "status": "initialized",
            }
        elif model_id is not None or existing_model_id is None:
            runtime = configure_project_runtime(
                infra_root=infra_root,
                project_root=root_path,
                project_name=name,
                model_id=str(selected_model),
            )
        else:
            runtime = {
                "project_root": str(root_path),
                "model_id": selected_model,
                "adapter": _raw_adapter(config_path),
                "status": "retained",
            }
    else:
        init_result = init_project(
            infra_root=infra_root,
            target_root=root_path,
            project_name=name,
            model_id=str(selected_model),
            force=False,
        )
        runtime = {
            "project_root": str(root_path),
            "model_id": init_result["model_id"],
            "status": "initialized",
        }

    stack = _ensure_stack_contract(
        infra_root=infra_root,
        project_root=root_path,
        project_id=name,
        stack_profile_id=stack_profile_id,
    )

    record = register_project(name=name, root=root_path, workspace_root=workspace_root)
    readiness = _readiness_payload(infra_root=infra_root, record=record)
    status = (
        REGISTERED_READY
        if readiness.get("project_config_status") == "passed"
        and readiness.get("stack_contract_status") == "passed"
        and readiness.get("verify_health", {}).get("ok") is not False
        else REGISTERED
    )
    return {
        "status": status,
        "registration": record.to_dict(),
        "runtime": runtime,
        "stack": stack,
        "ready_for_workflows": ["ao-small", "ao-plan", "ao-spec"] if status == REGISTERED_READY else [],
        "readiness": readiness,
    }


def models_payload(infra_root: Path) -> dict[str, Any]:
    return {"models": list_model_choices(infra_root)}


def stack_profiles_payload(infra_root: Path) -> dict[str, Any]:
    return list_stack_profiles(infra_root)


def _needs_model_payload(infra_root: Path, *, name: str, root: Path) -> dict[str, Any]:
    return {
        "status": NEEDS_MODEL_SELECTION,
        "message": "项目缺少 runtime 模型配置，请选择一个模型后重新执行。",
        "models": list_model_choices(infra_root),
        "retry": (
            f"python scripts/ao.py project register --name {name} "
            f"--root {root} --model <model_id>"
        ),
    }


def _existing_valid_model_id(infra_root: Path, config_path: Path) -> str | None:
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    model = payload.get("model")
    if not isinstance(model, dict):
        return None
    model_id = model.get("id")
    if not isinstance(model_id, str) or not model_id.strip():
        return None
    try:
        resolve_model_config(infra_root, model_id=model_id.strip())
    except ValueError:
        return None
    return model_id.strip()


def _ensure_stack_contract(
    *,
    infra_root: Path,
    project_root: Path,
    project_id: str,
    stack_profile_id: str | None,
) -> dict[str, Any]:
    try:
        contract = load_stack_contract(project_root, project_id=project_id)
    except StackContractError:
        payload = build_stack_contract_from_profile(
            infra_root=infra_root,
            project_id=project_id,
            profile_id=stack_profile_id,
        )
        path = project_root / STACK_CONTRACT_RELATIVE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        contract = load_stack_contract(project_root, project_id=project_id)
        return {
            "status": "configured",
            "profile_id": payload["profile_id"],
            "technology_stack": payload["technology_stack"],
            "contract": contract.ref.to_dict(),
        }
    return {
        "status": "retained",
        "profile_id": contract.payload.get("profile_id"),
        "technology_stack": contract.payload.get("technology_stack"),
        "contract": contract.ref.to_dict(),
    }

def _raw_adapter(config_path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    adapter = payload.get("adapter") if isinstance(payload, dict) else None
    return adapter if isinstance(adapter, dict) else None


def _can_initialize_infra(project_root: Path) -> bool:
    if (project_root / PROJECT_CONFIG_PATH).exists():
        return False
    if (project_root / "agentic.lock.json").exists() and (project_root / "scripts" / "ao.py").exists():
        return False
    children = [item.name for item in project_root.iterdir()]
    return not children or all(name in {".agentic"} for name in children)


def _readiness_payload(*, infra_root: Path, record: ProjectRecord) -> dict[str, Any]:
    del infra_root
    payload: dict[str, Any] = {}
    try:
        config = load_project_config(record.root_path)
    except ProjectConfigError as error:
        return {
            "project_config_status": "failed",
            "project_config_error": str(error),
        }
    health = adapter_health(config.adapter)
    verify = verify_health(record.root_path, config.verify)
    payload["project_config_status"] = "passed" if health["ok"] and verify["ok"] else "failed"
    payload["project_config"] = config.to_dict()
    payload["adapter_health"] = health
    payload["verify_health"] = verify
    try:
        contract = load_stack_contract(record.root_path, project_id=record.project_id)
    except StackContractError as error:
        payload["stack_contract_status"] = "failed"
        payload["stack_contract_error"] = str(error)
        payload["next"] = "run /ao-project stack confirm <project> --from <stack-contract.json>"
    else:
        payload["stack_contract_status"] = "passed"
        payload["stack_contract"] = contract.ref.to_dict()
    return payload
