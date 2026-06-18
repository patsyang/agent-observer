from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .infra_files import (
    baseline_hash,
    build_variables,
    entry_bytes,
    iter_managed_files,
    iter_template_files,
    sha256_bytes,
    sha256_file,
    update_status,
    write_entry,
)

LOCK_FILE = "agentic.lock.json"
MANIFEST_PATH = Path("agentic-infra") / "manifest.json"
MODEL_CATALOG_PATH = Path(".agentic") / "runtime-adapters" / "model-catalog.json"


def load_manifest(infra_root: Path) -> dict[str, Any]:
    manifest_path = infra_root / MANIFEST_PATH
    if not manifest_path.exists():
        raise ValueError(f"infra manifest not found: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def init_project(
    *,
    infra_root: Path,
    target_root: Path,
    project_name: str,
    model_id: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    manifest = load_manifest(infra_root)
    target_root = target_root.resolve()
    if target_root.exists() and any(target_root.iterdir()) and not force:
        raise ValueError(f"target directory is not empty: {target_root}")

    variables = build_variables(project_name)
    target_root.mkdir(parents=True, exist_ok=True)

    managed_files = list(iter_managed_files(infra_root, manifest))
    init_files = list(iter_template_files(infra_root, manifest, "init_only_files"))
    for entry in [*managed_files, *init_files]:
        write_entry(target_root, entry, variables)

    model_config = resolve_model_config(infra_root, model_id=model_id)
    write_project_runtime_config(
        target_root,
        project_name=project_name,
        model_config=model_config,
    )

    lock = build_lock(
        project_root=target_root,
        infra_root=infra_root,
        project_name=project_name,
    )
    write_lock(target_root, lock)
    return {
        "target_root": str(target_root),
        "infra_version": manifest["infra_version"],
        "managed_files": len(managed_files),
        "init_only_files": len(init_files),
        "lock_file": str(target_root / LOCK_FILE),
        "model_id": model_config["id"],
    }


def configure_project_runtime(
    *,
    infra_root: Path,
    project_root: Path,
    project_name: str,
    model_id: str,
) -> dict[str, Any]:
    model_config = resolve_model_config(infra_root, model_id=model_id)
    resolved_project = project_root.resolve()
    ensure_model_profile_installed(
        infra_root=infra_root,
        project_root=resolved_project,
        model_config=model_config,
    )
    update_project_runtime_config(resolved_project, project_name=project_name, model_config=model_config)
    return {
        "project_root": str(resolved_project),
        "model_id": model_config["id"],
        "adapter": model_config["adapter"],
    }


def resolve_model_config(infra_root: Path, *, model_id: str | None) -> dict[str, Any]:
    catalog = load_model_catalog(infra_root)
    selected = model_id or str(catalog["default_model"])
    for item in catalog["models"]:
        if item["id"] == selected:
            return dict(item)
    raise ValueError(f"unknown model id: {selected}")


def list_model_choices(infra_root: Path) -> list[dict[str, object]]:
    catalog = load_model_catalog(infra_root)
    default_model = catalog["default_model"]
    choices = []
    for item in catalog["models"]:
        if item.get("visible") is False:
            continue
        choices.append(
            {
                "id": item["id"],
                "label": item.get("label") or item["id"],
                "default": item["id"] == default_model,
            }
        )
    return choices


def load_model_catalog(infra_root: Path) -> dict[str, Any]:
    path = infra_root / MODEL_CATALOG_PATH
    if not path.exists():
        raise ValueError(f"model catalog not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError(f"model catalog schema_version must be 1: {path}")
    if not isinstance(payload.get("default_model"), str):
        raise ValueError(f"model catalog default_model is required: {path}")
    models = payload.get("models")
    if not isinstance(models, list) or not models:
        raise ValueError(f"model catalog models must be a non-empty array: {path}")
    for item in models:
        if not isinstance(item, dict):
            raise ValueError(f"model catalog model item must be an object: {path}")
        if not isinstance(item.get("id"), str) or not item["id"].strip():
            raise ValueError(f"model catalog model id is required: {path}")
        adapter = item.get("adapter")
        if not isinstance(adapter, dict):
            raise ValueError(f"model catalog model adapter is required: {path}")
        if not isinstance(adapter.get("id"), str) or not adapter["id"].strip():
            raise ValueError(f"model catalog adapter id is required: {path}")
        command = adapter.get("command")
        if not isinstance(command, list) or not command:
            raise ValueError(f"model catalog adapter command is required: {path}")
    return payload


def write_project_runtime_config(
    project_root: Path,
    *,
    project_name: str,
    model_config: dict[str, Any],
) -> None:
    variables = build_variables(project_name)
    path = project_root / ".agentic" / "project.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "project_id": variables["PROJECT_SLUG"],
                "project_name": project_name,
                "model": {"id": model_config["id"]},
                "adapter": model_config["adapter"],
                "verify": {"command": ["python", "scripts/ao.py", "verify"]},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def update_project_runtime_config(
    project_root: Path,
    *,
    project_name: str,
    model_config: dict[str, Any],
) -> None:
    path = project_root / ".agentic" / "project.json"
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"project config must be an object: {path}")
    else:
        variables = build_variables(project_name)
        payload = {
            "schema_version": 1,
            "project_id": variables["PROJECT_SLUG"],
            "project_name": project_name,
            "verify": {"command": ["python", "scripts/ao.py", "verify"]},
        }
    payload["model"] = {"id": model_config["id"]}
    payload["adapter"] = model_config["adapter"]
    if "verify" not in payload:
        payload["verify"] = {"command": ["python", "scripts/ao.py", "verify"]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ensure_model_profile_installed(
    *,
    infra_root: Path,
    project_root: Path,
    model_config: dict[str, Any],
) -> None:
    adapter = model_config.get("adapter")
    if not isinstance(adapter, dict) or adapter.get("id") != "generic-cli":
        return
    profile = adapter.get("profile")
    if not isinstance(profile, str) or not profile.strip():
        raise ValueError(f"generic-cli model `{model_config.get('id')}` must define adapter.profile")
    profile_path = Path(profile)
    if profile_path.is_absolute() or ".." in profile_path.parts:
        raise ValueError(f"adapter.profile must be a safe relative path: {profile}")
    source = infra_root / profile_path
    if not source.exists():
        raise ValueError(f"runtime profile source not found: {source}")
    target = project_root / profile_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())


def plan_update(
    *,
    project_root: Path,
    infra_root: Path,
) -> dict[str, Any]:
    manifest = load_manifest(infra_root)
    lock = read_lock(project_root)
    variables = lock.get("variables") or build_variables(lock.get("project_name") or "Project")
    baseline_files = lock.get("files", {})
    items = []

    for entry in iter_managed_files(infra_root, manifest):
        project_file = project_root / Path(entry.path)
        current_hash = sha256_file(project_file) if project_file.exists() else None
        previous_hash = baseline_hash(baseline_files.get(entry.path))
        infra_hash = sha256_bytes(entry_bytes(entry, variables))
        items.append(
            {
                "path": entry.path,
                "status": update_status(current_hash, previous_hash, infra_hash),
                "current_sha256": current_hash,
                "baseline_sha256": previous_hash,
                "infra_sha256": infra_hash,
            }
        )

    summary: dict[str, int] = {}
    for item in items:
        summary[item["status"]] = summary.get(item["status"], 0) + 1

    return {
        "schema_version": 1,
        "project_root": str(project_root.resolve()),
        "infra_version": manifest["infra_version"],
        "summary": dict(sorted(summary.items())),
        "items": items,
    }


def write_update_plan(plan: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_lock(
    *,
    project_root: Path,
    infra_root: Path,
    project_name: str,
) -> dict[str, Any]:
    manifest = load_manifest(infra_root)
    files = {}
    for entry in iter_managed_files(infra_root, manifest):
        project_file = project_root / Path(entry.path)
        if not project_file.exists():
            raise ValueError(f"managed file was not created: {entry.path}")
        files[entry.path] = {"sha256": sha256_file(project_file)}
    return {
        "schema_version": 1,
        "infra_name": manifest["infra_name"],
        "infra_version": manifest["infra_version"],
        "project_name": project_name,
        "variables": build_variables(project_name),
        "files": dict(sorted(files.items())),
    }


def read_lock(project_root: Path) -> dict[str, Any]:
    lock_path = project_root / LOCK_FILE
    if not lock_path.exists():
        raise ValueError(f"agentic lock not found: {lock_path}")
    return json.loads(lock_path.read_text(encoding="utf-8"))


def write_lock(project_root: Path, lock: dict[str, Any]) -> None:
    (project_root / LOCK_FILE).write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
