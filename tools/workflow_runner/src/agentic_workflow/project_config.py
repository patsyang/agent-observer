from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROJECT_CONFIG_PATH = Path(".agentic") / "project.json"
DEFAULT_RUNS_DIR = Path(".agentic") / "runs"
DEFAULT_WORKTREES_DIR = Path(".agentic") / "worktrees"
DEFAULT_LOGS_DIR = Path(".agentic") / "logs"
KNOWN_RUNTIME_ADAPTERS = {"codex", "generic-cli"}


class ProjectConfigError(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeAdapterConfig:
    adapter_id: str
    command: tuple[str, ...]
    profile: Path | None = None
    validated_at: str | None = None
    version: str | None = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "id": self.adapter_id,
            "command": list(self.command),
        }
        if self.profile:
            payload["profile"] = self.profile.as_posix()
        if self.validated_at:
            payload["validated_at"] = self.validated_at
        if self.version:
            payload["version"] = self.version
        return payload


@dataclass(frozen=True)
class VerifyConfig:
    command: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {"command": list(self.command)}


@dataclass(frozen=True)
class RuntimeConfig:
    runs_dir: Path = DEFAULT_RUNS_DIR
    worktrees_dir: Path = DEFAULT_WORKTREES_DIR
    logs_dir: Path = DEFAULT_LOGS_DIR

    def to_dict(self) -> dict[str, str]:
        return {
            "runs_dir": self.runs_dir.as_posix(),
            "worktrees_dir": self.worktrees_dir.as_posix(),
            "logs_dir": self.logs_dir.as_posix(),
        }

    def resolve_runs_dir(self, project_root: Path) -> Path:
        return (project_root / self.runs_dir).resolve()

    def resolve_worktrees_dir(self, project_root: Path) -> Path:
        return (project_root / self.worktrees_dir).resolve()

    def resolve_logs_dir(self, project_root: Path) -> Path:
        return (project_root / self.logs_dir).resolve()


@dataclass(frozen=True)
class ProjectConfig:
    path: Path
    schema_version: int
    project_id: str
    project_name: str
    adapter: RuntimeAdapterConfig
    runtime: RuntimeConfig
    verify: VerifyConfig

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "project_name": self.project_name,
            "adapter": self.adapter.to_dict(),
            "runtime": self.runtime.to_dict(),
            "verify": self.verify.to_dict(),
        }


def load_project_config(project_root: Path) -> ProjectConfig:
    path = project_root / PROJECT_CONFIG_PATH
    if not path.exists():
        raise ProjectConfigError(f"project config not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ProjectConfigError(f"project config is not valid JSON: {path}") from error

    adapter = _adapter_config(payload.get("adapter"), path)
    runtime = _runtime_config(payload.get("runtime"), path)
    verify = VerifyConfig(command=_command(payload.get("verify"), path, "verify.command"))
    return ProjectConfig(
        path=path,
        schema_version=int(payload.get("schema_version") or 1),
        project_id=_required_string(payload, "project_id", path),
        project_name=_required_string(payload, "project_name", path),
        adapter=adapter,
        runtime=runtime,
        verify=verify,
    )


def adapter_health(adapter: RuntimeAdapterConfig) -> dict[str, object]:
    executable = adapter.command[0]
    resolved = _resolve_executable(executable)
    return {
        "ok": resolved is not None,
        "executable": executable,
        "resolved_path": str(resolved) if resolved else None,
    }


def verify_health(project_root: Path, verify: VerifyConfig) -> dict[str, object]:
    command = list(verify.command)
    if len(command) >= 2 and Path(command[1]).as_posix() == "scripts/ao.py":
        entrypoint = project_root / command[1]
        return {
            "ok": entrypoint.exists(),
            "entrypoint": str(entrypoint),
        }
    return {"ok": True, "entrypoint": None}


def _adapter_config(value: Any, path: Path) -> RuntimeAdapterConfig:
    if not isinstance(value, dict):
        raise ProjectConfigError(f"adapter object is required in {path}")
    adapter_id = _required_string(value, "id", path)
    if adapter_id not in KNOWN_RUNTIME_ADAPTERS:
        raise ProjectConfigError(f"unknown runtime adapter `{adapter_id}` in {path}")
    profile = _adapter_profile(value.get("profile"), path, adapter_id)
    return RuntimeAdapterConfig(
        adapter_id=adapter_id,
        command=_command(value, path, "adapter.command"),
        profile=profile,
        validated_at=_optional_string(value.get("validated_at")),
        version=_optional_string(value.get("version")),
    )


def _adapter_profile(value: Any, path: Path, adapter_id: str) -> Path | None:
    if adapter_id == "codex":
        return None
    if value is None:
        raise ProjectConfigError(f"adapter.profile is required for `{adapter_id}` in {path}")
    if not isinstance(value, str) or not value.strip():
        raise ProjectConfigError(f"adapter.profile must be a non-empty relative path in {path}")
    profile = Path(value.strip())
    if profile.is_absolute():
        raise ProjectConfigError(f"adapter.profile must be relative in {path}")
    if ".." in profile.parts:
        raise ProjectConfigError(f"adapter.profile must not contain `..` in {path}")
    return profile


def _command(value: Any, path: Path, field: str) -> tuple[str, ...]:
    if not isinstance(value, dict):
        raise ProjectConfigError(f"{field} object is required in {path}")
    command = value.get("command")
    if not isinstance(command, list) or not command:
        raise ProjectConfigError(f"{field} must be a non-empty array in {path}")
    normalized = tuple(str(item).strip() for item in command)
    if any(not item for item in normalized):
        raise ProjectConfigError(f"{field} contains an empty command segment in {path}")
    return normalized


def _runtime_config(value: Any, path: Path) -> RuntimeConfig:
    if value is None:
        return RuntimeConfig()
    if not isinstance(value, dict):
        raise ProjectConfigError(f"runtime object must be an object in {path}")
    return RuntimeConfig(
        runs_dir=_relative_path(value.get("runs_dir"), path, "runtime.runs_dir", DEFAULT_RUNS_DIR),
        worktrees_dir=_relative_path(
            value.get("worktrees_dir"),
            path,
            "runtime.worktrees_dir",
            DEFAULT_WORKTREES_DIR,
        ),
        logs_dir=_relative_path(value.get("logs_dir"), path, "runtime.logs_dir", DEFAULT_LOGS_DIR),
    )


def _relative_path(value: Any, path: Path, field: str, default: Path) -> Path:
    if value is None:
        return default
    if not isinstance(value, str) or not value.strip():
        raise ProjectConfigError(f"{field} must be a non-empty relative path in {path}")
    candidate = Path(value.strip())
    if candidate.is_absolute():
        raise ProjectConfigError(f"{field} must be relative in {path}")
    if ".." in candidate.parts:
        raise ProjectConfigError(f"{field} must not contain `..` in {path}")
    if candidate == Path("."):
        raise ProjectConfigError(f"{field} must not point to project root in {path}")
    return candidate


def _required_string(payload: dict[str, Any], field: str, path: Path) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ProjectConfigError(f"{field} is required in {path}")
    return value.strip()


def _optional_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _resolve_executable(executable: str) -> Path | None:
    candidate = Path(executable)
    if candidate.is_absolute() or candidate.parent != Path("."):
        return candidate if candidate.exists() else None
    resolved = shutil.which(executable)
    return Path(resolved) if resolved else None
