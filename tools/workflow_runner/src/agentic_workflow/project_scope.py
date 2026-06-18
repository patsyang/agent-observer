from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .models import WorkflowInput


class ScopeResolutionError(ValueError):
    pass


@dataclass(frozen=True)
class ScopeResolution:
    project_scope: str
    write_set: tuple[str, ...]
    confidence: str
    evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "project_scope": self.project_scope,
            "write_set": list(self.write_set),
            "confidence": self.confidence,
            "evidence": list(self.evidence),
        }


def resolve_project_scope(repo_root: Path, workflow_input: WorkflowInput) -> ScopeResolution:
    if workflow_input.scope:
        return _resolve_explicit_scope(repo_root, workflow_input.scope)

    if workflow_input.project or workflow_input.project_root:
        project_scope = workflow_input.project or Path(workflow_input.project_root or "").name
        return ScopeResolution(
            project_scope=project_scope or "project",
            write_set=("**",),
            confidence="project",
            evidence=("用户显式绑定目标项目，默认写入边界为目标项目仓库",),
        )

    path_scope = _scope_from_primary_path(repo_root, workflow_input)
    if path_scope is not None:
        return path_scope

    if workflow_input.goal:
        return _scope_from_goal(repo_root, workflow_input.goal)

    raise ScopeResolutionError("无法解析 project_scope：缺少 scope、路径输入和目标文本")


def write_scope_resolution(run_dir: Path, resolution: ScopeResolution) -> Path:
    path = run_dir / "artifacts" / "scope-resolution.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(resolution.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def _resolve_explicit_scope(repo_root: Path, scope: str) -> ScopeResolution:
    allowed_literals = {"control-plane", "repo"}
    if scope in allowed_literals:
        return ScopeResolution(
            project_scope=scope,
            write_set=_default_write_set(scope),
            confidence="explicit",
            evidence=(f"用户显式指定 scope={scope}",),
        )

    path = repo_root / scope
    if scope == "agentic-infra" and path.exists():
        return ScopeResolution(
            project_scope=scope,
            write_set=_default_write_set(scope),
            confidence="explicit",
            evidence=(f"用户显式指定 scope={scope}",),
        )
    if scope.startswith("apps/") and path.exists() and path.is_dir():
        normalized_scope = scope.replace("\\", "/")
        return ScopeResolution(
            project_scope=normalized_scope,
            write_set=(f"{normalized_scope}/**",),
            confidence="explicit",
            evidence=(f"用户显式指定 scope={scope}",),
        )
    raise ScopeResolutionError(f"scope 不存在或不被允许: {scope}")


def _scope_from_primary_path(
    repo_root: Path,
    workflow_input: WorkflowInput,
) -> ScopeResolution | None:
    for value in (
        workflow_input.prd_path,
        workflow_input.source_spec_path,
        workflow_input.spec_path,
        workflow_input.plan_path,
        workflow_input.goal_path,
    ):
        if not value:
            continue
        path = Path(value)
        candidate = path if path.is_absolute() else repo_root / path
        try:
            relative = candidate.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            continue
        parts = relative.split("/")
        if len(parts) >= 2 and parts[0] == "apps":
            scope = f"apps/{parts[1]}"
            return ScopeResolution(
                project_scope=scope,
                write_set=(f"{scope}/**",),
                confidence="path",
                evidence=(f"输入路径位于 {scope}",),
            )
        if parts and parts[0] == "agentic-infra":
            return ScopeResolution(
                project_scope="agentic-infra",
                write_set=_default_write_set("agentic-infra"),
                confidence="path",
                evidence=("输入路径位于 agentic-infra",),
            )
    return None


def _scope_from_goal(repo_root: Path, goal: str) -> ScopeResolution:
    normalized = goal.lower()
    candidates: dict[str, list[str]] = {}

    for app_dir in sorted((repo_root / "apps").glob("*")) if (repo_root / "apps").exists() else []:
        if not app_dir.is_dir():
            continue
        scope = f"apps/{app_dir.name}"
        evidence = _match_app_goal(app_dir, normalized)
        if evidence:
            candidates[scope] = evidence

    control_tokens = ("workflow", "/ao", "runner", "control-plane", "command", "skill")
    if any(token in normalized for token in control_tokens):
        candidates["control-plane"] = ["目标文本命中控制面关键词"]

    if len(candidates) == 1:
        scope, evidence = next(iter(candidates.items()))
        return ScopeResolution(
            project_scope=scope,
            write_set=_default_write_set(scope),
            confidence="goal",
            evidence=tuple(evidence),
        )
    if not candidates:
        raise ScopeResolutionError("目标文本无法定位唯一 project_scope")
    details = ", ".join(sorted(candidates))
    raise ScopeResolutionError(f"目标文本命中多个候选 scope: {details}；请使用 --scope")


def _match_app_goal(app_dir: Path, normalized_goal: str) -> list[str]:
    evidence: list[str] = []
    token_to_path = {
        "dashboard": "dashboard",
        "collector": "collector",
        "outbox": "outbox",
        "backend": "backend",
        "frontend": "frontend",
    }
    for token, path_hint in token_to_path.items():
        if token not in normalized_goal:
            continue
        if _contains_path_token(app_dir, path_hint):
            evidence.append(f"目标文本命中 {token}，且 {app_dir.name} 包含对应模块")
    return evidence


def _contains_path_token(root: Path, token: str) -> bool:
    token = token.lower()
    return any(token in path.name.lower() for path in root.rglob("*"))


def _default_write_set(scope: str) -> tuple[str, ...]:
    if scope.startswith("apps/"):
        return (f"{scope}/**",)
    if scope == "agentic-infra":
        return ("agentic-infra/**",)
    if scope == "control-plane":
        return (
            "commands/**",
            ".codex/skills/**",
            ".agentic/workflow/**",
            "scripts/ao.py",
            "tools/workflow_runner/**",
            "agentic-infra/**",
            "agentic.lock.json",
        )
    return ("**",)
