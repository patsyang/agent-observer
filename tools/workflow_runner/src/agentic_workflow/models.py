from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .project_config import ProjectConfig, RuntimeAdapterConfig
from .stack_contract import StackContract, StackContractRef

PRIMARY_INPUTS = (
    "goal",
    "goal_path",
    "prd_path",
    "source_spec_path",
    "spec_path",
    "plan_path",
)


@dataclass(frozen=True)
class ArtifactSpec:
    path: str
    kind: str = "artifact"
    schema: str | None = None
    validators: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_raw(cls, value: object) -> "ArtifactSpec":
        if isinstance(value, str):
            return cls(path=value)
        if isinstance(value, dict):
            path = value.get("path")
            if not isinstance(path, str) or not path.strip():
                raise ValueError("required artifact object must include non-empty path")
            validators = value.get("validators", [])
            if validators is None:
                validators = []
            if not isinstance(validators, list) or not all(
                isinstance(item, str) for item in validators
            ):
                raise ValueError(f"artifact {path} validators must be a string array")
            schema = value.get("schema")
            if schema is not None and not isinstance(schema, str):
                raise ValueError(f"artifact {path} schema must be a string")
            kind = value.get("kind", "artifact")
            if not isinstance(kind, str) or not kind.strip():
                raise ValueError(f"artifact {path} kind must be a non-empty string")
            return cls(path=path, kind=kind, schema=schema, validators=tuple(validators))
        raise ValueError("required artifact must be a string or object")


@dataclass(frozen=True)
class NodeExecutionRequest:
    run_id: str
    workflow: str
    node_id: str
    node_type: str
    command_name: str | None
    prompt: str | None
    worktree_path: Path
    artifacts_dir: Path
    node_dir: Path
    runtime_env: dict[str, str]
    required_artifacts: tuple[ArtifactSpec, ...]
    timeout_seconds: int
    output_format: dict[str, object] | None = None
    extra_env: dict[str, str] | None = None
    log_suffix: str = ""

    @property
    def required_artifact_paths(self) -> list[str]:
        return [artifact.path for artifact in self.required_artifacts]


@dataclass(frozen=True)
class WorkflowDefinition:
    name: str
    title: str
    adapter: str
    contract_path: str
    primary_inputs: tuple[str, ...]
    stages: tuple[str, ...]
    verify_policy: str
    nodes: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    worktree: bool = False
    parallelism: int = 1
    state_schema: str | None = None
    artifact_schema: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowDefinition":
        return cls(
            name=str(data["name"]),
            title=str(data["title"]),
            adapter=str(data["adapter"]),
            contract_path=str(data["contract_path"]),
            primary_inputs=tuple(str(item) for item in data["primary_inputs"]),
            stages=tuple(str(item) for item in data["stages"]),
            verify_policy=str(data["verify_policy"]),
            nodes=tuple(dict(item) for item in data.get("nodes", [])),
            worktree=bool(data.get("worktree", False)),
            parallelism=int(data.get("parallelism", 1)),
            state_schema=_optional_str(data.get("state_schema")),
            artifact_schema=_optional_str(data.get("artifact_schema")),
        )


@dataclass(frozen=True)
class WorkflowInput:
    workflow: str
    goal: str | None = None
    goal_path: str | None = None
    prd_path: str | None = None
    source_spec_path: str | None = None
    spec_path: str | None = None
    plan_path: str | None = None
    scope: str | None = None
    project: str | None = None
    project_root: str | None = None

    def primary_values(self) -> dict[str, str]:
        values = {}
        for name in PRIMARY_INPUTS:
            value = getattr(self, name)
            if value:
                values[name] = value
        return values

    def to_dict(self) -> dict[str, str | None]:
        return {
            "workflow": self.workflow,
            "goal": self.goal,
            "goal_path": self.goal_path,
            "prd_path": self.prd_path,
            "source_spec_path": self.source_spec_path,
            "spec_path": self.spec_path,
            "plan_path": self.plan_path,
            "scope": self.scope,
            "project": self.project,
            "project_root": self.project_root,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "WorkflowInput":
        return cls(
            workflow=str(payload["workflow"]),
            goal=_optional_str(payload.get("goal")),
            goal_path=_optional_str(payload.get("goal_path")),
            prd_path=_optional_str(payload.get("prd_path")),
            source_spec_path=_optional_str(payload.get("source_spec_path")),
            spec_path=_optional_str(payload.get("spec_path")),
            plan_path=_optional_str(payload.get("plan_path")),
            scope=_optional_str(payload.get("scope")),
            project=_optional_str(payload.get("project")),
            project_root=_optional_str(payload.get("project_root")),
        )


@dataclass(frozen=True)
class RunContext:
    run_id: str
    repo_root: Path
    project_root: Path
    project_id: str | None
    project_name: str | None
    workspace_root: Path | None
    worktrees_dir: Path | None
    logs_dir: Path | None
    run_dir: Path
    definition: WorkflowDefinition
    workflow_input: WorkflowInput
    project_config: ProjectConfig | None = None
    runtime_adapter: RuntimeAdapterConfig | None = None
    verify_command: tuple[str, ...] | None = None
    stack_contract: StackContract | None = None
    stack_contract_ref: StackContractRef | None = None


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text or None
