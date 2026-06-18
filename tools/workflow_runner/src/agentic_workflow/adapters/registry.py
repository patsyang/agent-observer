from pathlib import Path

from agentic_workflow.adapters.base import AgentRuntimeAdapter
from agentic_workflow.adapters.codex import CodexAdapter
from agentic_workflow.adapters.generic_cli import GenericCliAdapter


def create_adapter(
    name: str,
    *,
    command: list[str] | None = None,
    timeout_seconds: int = 3600,
    profile_path: Path | None = None,
) -> AgentRuntimeAdapter:
    if name == "codex":
        return CodexAdapter(command=command, timeout_seconds=timeout_seconds)
    if name == "generic-cli":
        return GenericCliAdapter(
            command=command,
            timeout_seconds=timeout_seconds,
            profile_path=profile_path,
        )
    raise ValueError(f"未知的 Agent runtime adapter：{name}")
