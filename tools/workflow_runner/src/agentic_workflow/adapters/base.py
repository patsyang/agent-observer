from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from agentic_workflow.models import NodeExecutionRequest, RunContext


@dataclass(frozen=True)
class AdapterResult:
    return_code: int
    summary: str
    changed_files: list[str]


@dataclass(frozen=True)
class NodeAdapterResult:
    return_code: int
    output: str


class AgentRuntimeAdapter(Protocol):
    name: str

    def execute(self, context: RunContext) -> AdapterResult:
        """基于已准备的工作流上下文执行 Agent runtime。"""

    def execute_node(
        self,
        context: RunContext,
        *,
        node: dict[str, Any],
        node_id: str,
        artifacts_dir: Path,
        worktree_path: Path,
        required_artifacts: list[str],
        extra_env: dict[str, str] | None = None,
        log_suffix: str = "",
    ) -> NodeAdapterResult:
        """执行 workflow runner 调度的单个节点。"""

    def execute_node_request(
        self,
        context: RunContext,
        request: NodeExecutionRequest,
    ) -> NodeAdapterResult:
        """执行带结构化 artifact spec 的节点请求。"""
