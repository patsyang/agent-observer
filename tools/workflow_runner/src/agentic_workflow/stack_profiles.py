from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

STACK_PROFILE_CATALOG_PATH = Path(".agentic") / "stack-profiles" / "catalog.json"


class StackProfileError(ValueError):
    pass


def load_stack_profile_catalog(infra_root: Path) -> dict[str, Any]:
    path = infra_root / STACK_PROFILE_CATALOG_PATH
    if not path.exists():
        raise StackProfileError(f"stack profile catalog not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise StackProfileError(f"stack profile catalog schema_version must be 1: {path}")
    default_profile = payload.get("default_profile")
    profiles = payload.get("profiles")
    if not isinstance(default_profile, str) or not default_profile.strip():
        raise StackProfileError(f"stack profile catalog default_profile is required: {path}")
    if not isinstance(profiles, list) or not profiles:
        raise StackProfileError(f"stack profile catalog profiles must be a non-empty array: {path}")
    seen: set[str] = set()
    for item in profiles:
        if not isinstance(item, dict):
            raise StackProfileError(f"stack profile item must be an object: {path}")
        profile_id = item.get("id")
        if not isinstance(profile_id, str) or not profile_id.strip():
            raise StackProfileError(f"stack profile id is required: {path}")
        seen.add(profile_id)
        if not isinstance(item.get("technology_stack"), dict):
            raise StackProfileError(f"stack profile technology_stack is required: {profile_id}")
        components = item.get("components")
        if not isinstance(components, list) or not components:
            raise StackProfileError(f"stack profile components must be non-empty: {profile_id}")
        commands = item.get("commands")
        if not isinstance(commands, dict) or not _valid_command(commands.get("verify_all")):
            raise StackProfileError(f"stack profile commands.verify_all is required: {profile_id}")
    if default_profile not in seen:
        raise StackProfileError(f"stack profile default_profile not found: {default_profile}")
    return payload


def list_stack_profiles(infra_root: Path) -> dict[str, Any]:
    catalog = load_stack_profile_catalog(infra_root)
    default_profile = catalog["default_profile"]
    return {
        "default_profile": default_profile,
        "profiles": [
            {
                "id": item["id"],
                "label": item.get("label") or item["id"],
                "description": item.get("description") or "",
                "technology_stack": item["technology_stack"],
                "default": item["id"] == default_profile,
                "commands": item["commands"],
            }
            for item in catalog["profiles"]
        ],
    }


def resolve_stack_profile(infra_root: Path, profile_id: str | None) -> dict[str, Any]:
    catalog = load_stack_profile_catalog(infra_root)
    selected = profile_id or catalog["default_profile"]
    for item in catalog["profiles"]:
        if item["id"] == selected:
            return copy.deepcopy(item)
    raise StackProfileError(f"unknown stack profile id: {selected}")


def build_stack_contract_from_profile(
    *,
    infra_root: Path,
    project_id: str,
    profile_id: str | None,
) -> dict[str, Any]:
    profile = resolve_stack_profile(infra_root, profile_id)
    return {
        "contract_id": f"{project_id}-stack",
        "project_id": project_id,
        "revision": 1,
        "status": "confirmed",
        "profile_id": profile["id"],
        "profile_label": profile.get("label") or profile["id"],
        "technology_stack": profile["technology_stack"],
        "components": profile["components"],
        "commands": profile["commands"],
    }


def _valid_command(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    return isinstance(value, list) and bool(value) and all(
        isinstance(item, str) and item.strip() for item in value
    )
