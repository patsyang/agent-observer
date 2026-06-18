from __future__ import annotations

import json
from collections.abc import Callable

from .models import RunContext
from .worktree import WorktreeState


def load_run_state(context: RunContext) -> dict[str, object]:
    path = context.run_dir / "run.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_run_state(context: RunContext, payload: dict[str, object]) -> None:
    (context.run_dir / "run.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_run_state(
    context: RunContext,
    *,
    existing_state: dict[str, object] | None,
    worktree_state: WorktreeState | None,
    project_scope: str,
    write_set: tuple[str, ...],
) -> dict[str, object]:
    prior_nodes = []
    if existing_state and isinstance(existing_state.get("nodes"), list):
        prior_nodes = list(existing_state["nodes"])
    return {
        "run_id": context.run_id,
        "workflow": context.definition.name,
        "status": "RUNNING",
        "project_root": str(context.project_root),
        "runtime_adapter": context.runtime_adapter.to_dict()
        if context.runtime_adapter
        else None,
        "stack_contract": context.stack_contract_ref.to_dict()
        if context.stack_contract_ref
        else None,
        "artifacts_dir": str(context.run_dir / "artifacts"),
        "project_scope": project_scope,
        "write_set": list(write_set),
        "workflow_input": context.workflow_input.to_dict(),
        "worktree": worktree_state.to_dict() if worktree_state else None,
        "nodes": prior_nodes,
    }


def resolve_worktree_state(
    context: RunContext,
    *,
    existing_state: dict[str, object] | None,
    use_worktree: bool,
    create_worktree: Callable[..., WorktreeState | None],
) -> WorktreeState | None:
    if existing_state and isinstance(existing_state.get("worktree"), dict):
        state = WorktreeState.from_dict(existing_state["worktree"])
        if state.path.exists():
            return state
    return create_worktree(context, use_worktree=use_worktree)


def node_passed(run_state: dict[str, object], node_id: str) -> bool:
    return any(
        isinstance(node, dict)
        and node.get("node_id") == node_id
        and node.get("status") == "PASSED"
        for node in run_state.get("nodes", [])
        if isinstance(node, dict)
    )


def ensure_dependencies_passed(
    run_state: dict[str, object],
    node: dict[str, object],
) -> None:
    for dependency in node.get("depends_on", []):
        if not node_passed(run_state, str(dependency)):
            raise RuntimeError(f"node {node['id']} dependency not passed: {dependency}")


def record_node(
    run_state: dict[str, object],
    node_id: str,
    *,
    status: str,
    output: object | None = None,
    details: object | None = None,
    error: str | None = None,
) -> None:
    nodes = run_state.setdefault("nodes", [])
    if not isinstance(nodes, list):
        run_state["nodes"] = nodes = []
    record = next(
        (
            node
            for node in nodes
            if isinstance(node, dict) and node.get("node_id") == node_id
        ),
        None,
    )
    if record is None:
        record = {"node_id": node_id}
        nodes.append(record)
    record["status"] = status
    if output is not None:
        record["output"] = str(output)[-4000:]
    if details is not None:
        record["details"] = details
    if error is not None:
        record["error"] = error
    elif status != "FAILED":
        record.pop("error", None)
