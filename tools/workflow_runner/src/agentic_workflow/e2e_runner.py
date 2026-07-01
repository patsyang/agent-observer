from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .adapters import create_adapter
from .adapters.base import AgentRuntimeAdapter
from .e2e_inputs import run_system_import_node
from .e2e_state import (
    build_run_state,
    ensure_dependencies_passed,
    load_run_state,
    node_passed,
    record_node,
    resolve_worktree_state,
    write_run_state,
)
from .events import append_event
from .models import ArtifactSpec, NodeExecutionRequest, RunContext, WorkflowInput
from .production_gates import (
    validate_acceptance_matrix,
    validate_frontend_template_selection,
    validate_required_artifact_specs,
)
from .project_scope import resolve_project_scope, write_scope_resolution
from .reports import write_run_report
from .runner import create_run_context
from .stack_contract import stack_runtime_env, validate_stack_acceptance_artifacts, validate_stack_trace
from .workspace import find_run, resolve_run_dir
from .worktree import WorktreeManager, WorktreeState


@dataclass(frozen=True)
class WorkflowRunResult:
    return_code: int
    summary: str
    changed_files: list[str]


DEFAULT_REQUIRED_ARTIFACTS = {
    "small-change": {
        "small-scope-gate": ["small-scope.json", "small-scope.md"],
        "repro-or-signal": ["repro.md"],
        "execute": ["implementation.md", "changed-files.txt"],
        "verify-and-fix": ["verification.json", "verification.md"],
        "independent-review": [
            "review.md",
            "acceptance-matrix.json",
            "component-evidence.json",
            "command-coverage.json",
        ],
        "small-acceptance-gate": ["small-acceptance-gate.json"],
    },
    "plan-execute": {
        "resolve-slice-brief": ["slice-brief.md"],
        "generate-plan": ["plan.md", "tasks.json", "task-graph.json"],
        "plan-contract-gate": ["plan-gate.json", "plan-gate.md"],
        "task-graph-gate": ["task-graph-gate.json"],
        "execute-task-loop": ["implementation.md", "changed-files.txt", "verification.md"],
        "integration-verify": ["integration-verify.json", "integration-verify.md"],
        "independent-review": ["review.md"],
        "review-gate": ["review-gate.json"],
        "fix-loop": [
            "fix.md",
            "acceptance-matrix.json",
            "component-evidence.json",
            "command-coverage.json",
        ],
        "acceptance-gate": ["acceptance-gate.json"],
    },
    "spec-driven": {
        "import-input": ["imported-source.json"],
        "generate-product-state": ["product-prd.md", "product-contract.json", "stories.json", "progress.md"],
        "generate-production-spec": ["production-spec.md", "api-contract.json", "data-contract.json"],
        "generate-implementation-plan": ["plan.md", "tasks.md", "tasks.json", "task-graph.json"],
        "implement-story-loop": ["implementation-state.json", "progress.md"],
        "independent-review": ["review.md"],
        "fix-loop": ["fix.md"],
        "release-readiness-gate": ["release-readiness.md"],
        "final-e2e-proof": ["e2e-proof.md"],
        "acceptance-matrix": ["acceptance-matrix.json"],
    },
}


def run_e2e_workflow(
    context: RunContext,
    *,
    use_worktree: bool = True,
    resume: bool = False,
) -> WorkflowRunResult:
    started = time.monotonic()
    artifacts_dir = context.run_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    scope = resolve_project_scope(context.project_root, context.workflow_input)
    scope_path = write_scope_resolution(context.run_dir, scope)
    existing_state = load_run_state(context) if resume else None
    worktree_state = resolve_worktree_state(
        context,
        existing_state=existing_state,
        use_worktree=use_worktree,
        create_worktree=_create_worktree,
    )
    run_state = build_run_state(
        context,
        existing_state=existing_state,
        worktree_state=worktree_state,
        project_scope=scope.project_scope,
        write_set=scope.write_set,
    )
    write_run_state(context, run_state)
    append_event(
        context.run_dir / "workflow-event.jsonl",
        run_id=context.run_id,
        workflow=context.definition.name,
        step="scope-resolve",
        status="passed",
        message=f"project_scope={scope.project_scope}",
        artifact_path=str(scope_path),
    )

    execution_root = worktree_state.path if worktree_state else context.project_root
    try:
        _execute_nodes(
            context,
            run_state=run_state,
            artifacts_dir=artifacts_dir,
            execution_root=execution_root,
        )
        run_state["current_node"] = "acceptance-matrix"
        return _finish_successful_run(
            context,
            run_state=run_state,
            artifacts_dir=artifacts_dir,
            execution_root=execution_root,
            project_scope=scope.project_scope,
            started=started,
        )
    except Exception as error:
        _record_run_failure(context, run_state, error=error, artifacts_dir=artifacts_dir)
        raise


def read_run_status(repo_root: Path, run_id: str) -> dict[str, object]:
    path = resolve_run_dir(repo_root, run_id) / "run.json"
    if not path.exists():
        raise FileNotFoundError(f"run not found: {run_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def resume_run(repo_root: Path, run_id: str) -> WorkflowRunResult:
    status = read_run_status(repo_root, run_id)
    if status.get("status") == "CLEANED":
        raise RuntimeError(f"run {run_id} was cleaned and cannot be resumed")
    workflow_input = status.get("workflow_input")
    if not isinstance(workflow_input, dict):
        raise RuntimeError(f"run {run_id} missing workflow_input; cannot resume")
    context = create_run_context(
        repo_root,
        WorkflowInput.from_dict(workflow_input),
        run_id=run_id,
    )
    if context.definition.name == "control-plane-change":
        from .runner import complete_run

        changed_files = _changed_files_from_state(context, status)
        return_code = complete_run(
            context,
            summary=f"resume finalizer for {context.definition.name}",
            changed_files=changed_files,
            skip_verify=False,
        )
        return WorkflowRunResult(
            return_code=return_code,
            summary="control-plane resume finalized through completion gate",
            changed_files=changed_files,
        )
    if status.get("status") == "PASSED":
        _validate_completed_stack_run(context)
        acceptance_path = str(status.get("acceptance_matrix") or context.run_dir / "acceptance-matrix.json")
        summary = f"workflow {context.definition.name} already passed; acceptance={acceptance_path}"
        changed_files = _changed_files_from_state(context, status)
        write_run_report(
            context,
            status="passed",
            summary=summary,
            verification="workflow status: PASSED",
            changed_files=changed_files,
            artifacts=_report_artifacts(acceptance_path),
        )
        return WorkflowRunResult(return_code=0, summary=summary, changed_files=changed_files)
    append_event(
        context.run_dir / "workflow-event.jsonl",
        run_id=context.run_id,
        workflow=context.definition.name,
        step="resume",
        status="started",
        message="workflow resume started",
        artifact_path=str(context.run_dir),
    )
    use_worktree = bool(status.get("worktree"))
    return run_e2e_workflow(context, resume=True, use_worktree=use_worktree)


def cleanup_run(repo_root: Path, run_id: str, *, force: bool = False) -> bool:
    indexed_run = find_run(run_id)
    if indexed_run:
        project_root = Path(str(indexed_run["project_root"]))
        run_dir = Path(str(indexed_run["run_dir"]))
        workspace_root = run_dir.parent.parent
        worktrees_dir = (
            Path(str(indexed_run["worktrees_dir"]))
            if indexed_run.get("worktrees_dir")
            else None
        )
        removed = WorktreeManager(
            project_root,
            workspace_root,
            worktrees_dir=worktrees_dir,
        ).cleanup(run_id, force=force)
        _mark_run_cleaned(run_dir)
        return removed
    removed = WorktreeManager(repo_root).cleanup(run_id, force=force)
    _mark_run_cleaned(resolve_run_dir(repo_root, run_id))
    return removed


def _mark_run_cleaned(run_dir: Path) -> None:
    state_path = run_dir / "run.json"
    if not state_path.exists():
        return
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    if not isinstance(state, dict):
        return
    state["status"] = "CLEANED"
    for key in ("current_node", "failed_node", "error", "resume_command", "complete_command"):
        state.pop(key, None)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _execute_nodes(
    context: RunContext,
    *,
    run_state: dict[str, object],
    artifacts_dir: Path,
    execution_root: Path,
) -> None:
    runtime_adapter = _create_node_runtime_adapter(context)
    for node in _nodes(context):
        node_id = str(node["id"])
        if node_passed(run_state, node_id):
            _validate_required_artifacts(context, node_id, artifacts_dir)
            record_node(run_state, node_id, status="PASSED")
            write_run_state(context, run_state)
            append_event(
                context.run_dir / "workflow-event.jsonl",
                run_id=context.run_id,
                workflow=context.definition.name,
                step=node_id,
                status="skipped",
                message="node already passed",
                artifact_path=str(artifacts_dir),
            )
            continue
        run_state["current_node"] = node_id
        ensure_dependencies_passed(run_state, node)
        record_node(run_state, node_id, status="RUNNING")
        write_run_state(context, run_state)
        node_result = _run_node(
            context,
            node=node,
            node_id=node_id,
            runtime_adapter=runtime_adapter,
            artifacts_dir=artifacts_dir,
            worktree_path=execution_root,
        )
        _validate_required_artifacts(context, node_id, artifacts_dir)
        record_node(
            run_state,
            node_id,
            status="PASSED",
            output=node_result["output"],
            details=node_result["details"],
        )
        write_run_state(context, run_state)


def _record_run_failure(
    context: RunContext,
    run_state: dict[str, object],
    *,
    error: Exception,
    artifacts_dir: Path,
) -> None:
    node_id = str(run_state.get("current_node") or "workflow")
    run_state["status"] = "FAILED"
    run_state["failed_node"] = node_id
    run_state["error"] = str(error)
    run_state["resume_command"] = f"python scripts/ao.py workflow resume --run-id {context.run_id}"
    if node_id != "workflow":
        record_node(run_state, node_id, status="FAILED", error=str(error))
    write_run_state(context, run_state)
    write_run_report(
        context,
        status="failed",
        summary=str(error),
        verification=f"FAILED: {error}",
        changed_files=[],
        artifacts=["run state: `run.json`", "artifacts: `artifacts/`"],
    )
    append_event(
        context.run_dir / "workflow-event.jsonl",
        run_id=context.run_id,
        workflow=context.definition.name,
        step=node_id,
        status="failed",
        message=str(error),
        artifact_path=str(artifacts_dir),
    )


def _finish_successful_run(
    context: RunContext,
    *,
    run_state: dict[str, object],
    artifacts_dir: Path,
    execution_root: Path,
    project_scope: str,
    started: float,
) -> WorkflowRunResult:
    acceptance_path = _write_acceptance_matrix(context, artifacts_dir)
    duration_ms = int((time.monotonic() - started) * 1000)
    run_state["status"] = "PASSED"
    run_state["duration_ms"] = duration_ms
    run_state["acceptance_matrix"] = str(acceptance_path)
    for key in ("current_node", "failed_node", "error", "resume_command"):
        run_state.pop(key, None)
    write_run_state(context, run_state)
    append_event(
        context.run_dir / "workflow-event.jsonl",
        run_id=context.run_id,
        workflow=context.definition.name,
        step="acceptance-matrix",
        status="passed",
        message="acceptance matrix passed",
        artifact_path=str(acceptance_path),
        duration_ms=duration_ms,
    )
    changed_root = execution_root
    changed_files = _changed_files(changed_root)
    summary = f"workflow {context.definition.name} passed; acceptance={acceptance_path}"
    write_run_report(
        context,
        status="passed",
        summary=summary,
        verification="workflow status: PASSED\nacceptance matrix gate: PASSED",
        changed_files=changed_files,
        artifacts=_report_artifacts(str(acceptance_path)),
    )
    return WorkflowRunResult(
        return_code=0,
        summary=summary,
        changed_files=changed_files,
    )


def _report_artifacts(acceptance_path: str) -> list[str]:
    return [
        "run state: `run.json`",
        "artifacts: `artifacts/`",
        "acceptance matrix: `acceptance-matrix.json`",
        f"acceptance path: `{acceptance_path}`",
    ]


def _changed_files_from_state(context: RunContext, state: dict[str, object]) -> list[str]:
    worktree = state.get("worktree")
    if isinstance(worktree, dict):
        raw_path = worktree.get("path")
        if isinstance(raw_path, str):
            path = Path(raw_path)
            if path.exists():
                return _changed_files(path)
    return _changed_files(context.project_root)


def _create_worktree(context: RunContext, *, use_worktree: bool) -> WorktreeState | None:
    if not use_worktree:
        return None
    if not context.definition.worktree:
        return None
    manager = WorktreeManager(
        context.project_root,
        context.workspace_root,
        worktrees_dir=context.worktrees_dir,
        allowed_untracked_roots=tuple(
            path
            for path in (context.run_dir.parent, context.worktrees_dir, context.logs_dir)
            if path is not None
        ),
    )
    state = manager.create(workflow=context.definition.name, run_id=context.run_id)
    append_event(
        context.run_dir / "workflow-event.jsonl",
        run_id=context.run_id,
        workflow=context.definition.name,
        step="create-worktree",
        status="passed",
        message=f"worktree={state.path}",
        artifact_path=str(state.path),
    )
    return state


def _nodes(context: RunContext) -> list[dict[str, object]]:
    if context.definition.nodes:
        return [dict(node) for node in context.definition.nodes if "id" in node]
    return [
        {"id": node_id}
        for node_id in DEFAULT_REQUIRED_ARTIFACTS.get(context.definition.name, {})
    ]


def _run_node(
    context: RunContext,
    *,
    node: dict[str, object],
    node_id: str,
    runtime_adapter: AgentRuntimeAdapter | None,
    artifacts_dir: Path,
    worktree_path: Path,
) -> dict[str, object]:
    append_event(
        context.run_dir / "workflow-event.jsonl",
        run_id=context.run_id,
        workflow=context.definition.name,
        step=node_id,
        status="started",
        message="node started",
        artifact_path=str(artifacts_dir),
    )
    if str(node.get("type", "")) == "system-import":
        output = run_system_import_node(
            context,
            artifacts_dir=artifacts_dir,
            worktree_path=worktree_path,
        )
        details: dict[str, object] = {"kind": "system-import"}
    elif str(node.get("type", "")) == "loop":
        loop_result = _run_loop_node(
            context,
            node=node,
            node_id=node_id,
            runtime_adapter=runtime_adapter,
            artifacts_dir=artifacts_dir,
            worktree_path=worktree_path,
        )
        output = str(loop_result["output"])
        details = {"iterations": loop_result["iterations"]}
    elif runtime_adapter:
        output = _execute_runtime_adapter_node(
            context,
            node=node,
            node_id=node_id,
            runtime_adapter=runtime_adapter,
            artifacts_dir=artifacts_dir,
            worktree_path=worktree_path,
        )
        details = {"kind": "adapter"}
    else:
        _ensure_default_node_execution_allowed(context)
        _write_default_artifacts(context, node_id, artifacts_dir)
        output = "default artifacts written"
        details = {"kind": "default"}
    append_event(
        context.run_dir / "workflow-event.jsonl",
        run_id=context.run_id,
        workflow=context.definition.name,
        step=node_id,
        status="passed",
        message="node passed",
        artifact_path=str(artifacts_dir),
    )
    return {"output": output, "details": details}


def _validate_required_artifacts(context: RunContext, node_id: str, artifacts_dir: Path) -> None:
    try:
        validate_required_artifact_specs(
            _required_artifact_specs(context, node_id),
            artifacts_dir=artifacts_dir,
        )
        _validate_stack_trace_artifacts(context, node_id, artifacts_dir)
        if context.definition.name == "spec-driven" and node_id in {
            "frontend-template-resolution",
            "gate-frontend-template",
        }:
            _validate_spec_driven_frontend_template_selection(artifacts_dir)
        if context.definition.name == "spec-driven" and node_id == "acceptance-matrix":
            _validate_spec_driven_acceptance_matrix(context, artifacts_dir)
    except Exception as error:
        raise RuntimeError(f"node {node_id} artifact gate failed: {error}") from error


def _required_artifacts(context: RunContext, node_id: str) -> list[str]:
    return [artifact.path for artifact in _required_artifact_specs(context, node_id)]


def _required_artifact_specs(context: RunContext, node_id: str) -> list[ArtifactSpec]:
    for node in context.definition.nodes:
        if node.get("id") == node_id:
            return [
                ArtifactSpec.from_raw(item)
                for item in node.get("required_artifacts", [])
            ]
    return [
        ArtifactSpec.from_raw(item)
        for item in DEFAULT_REQUIRED_ARTIFACTS.get(context.definition.name, {}).get(node_id, [])
    ]


def _write_default_artifacts(context: RunContext, node_id: str, artifacts_dir: Path) -> None:
    for name in _required_artifacts(context, node_id):
        path = artifacts_dir / name
        if not path.exists():
            path.write_text(
                f"# {name}\n\nworkflow={context.definition.name}\nnode={node_id}\n",
                encoding="utf-8",
            )


def _write_acceptance_matrix(context: RunContext, artifacts_dir: Path) -> Path:
    path = context.run_dir / "acceptance-matrix.json"
    production_path = artifacts_dir / "acceptance-matrix.json"
    if context.definition.name == "spec-driven" or context.stack_contract_ref:
        if not production_path.exists():
            raise RuntimeError(
                f"{context.definition.name} missing production acceptance-matrix.json"
            )
        if context.definition.name == "spec-driven":
            _validate_spec_driven_acceptance_matrix(context, artifacts_dir)
        if context.stack_contract:
            validate_stack_acceptance_artifacts(
                artifacts_dir,
                contract=context.stack_contract,
                run_dir=context.run_dir,
            )
        shutil.copyfile(production_path, path)
        return path

    payload = [
        {
            "acceptance_id": "A001",
            "source": context.workflow_input.workflow,
            "expected_behavior": "workflow runs to E2E completion",
            "evidence_type": "artifact",
            "evidence_path": str(artifacts_dir),
            "command": "python scripts/ao.py workflow run",
            "result": "PASS",
        }
    ]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _validate_spec_driven_acceptance_matrix(context: RunContext, artifacts_dir: Path) -> None:
    validate_acceptance_matrix(
        artifacts_dir / "acceptance-matrix.json",
        run_dir=context.run_dir,
        review_path=artifacts_dir / "review-findings.json",
        fix_path=artifacts_dir / "fix-state.json",
    )


def _validate_spec_driven_frontend_template_selection(artifacts_dir: Path) -> None:
    validate_frontend_template_selection(
        artifacts_dir / "frontend-template-selection.json",
        project_inspection_path=artifacts_dir / "project-inspection.json",
        production_spec_path=artifacts_dir / "production-spec.md",
    )


def _validate_stack_trace_artifacts(
    context: RunContext,
    node_id: str,
    artifacts_dir: Path,
) -> None:
    if context.stack_contract_ref is None:
        return
    for spec in _required_artifact_specs(context, node_id):
        if "stack_trace" in spec.validators:
            validate_stack_trace(artifacts_dir / spec.path, context.stack_contract_ref)


def _run_loop_node(
    context: RunContext,
    *,
    node: dict[str, object],
    node_id: str,
    runtime_adapter: AgentRuntimeAdapter | None,
    artifacts_dir: Path,
    worktree_path: Path,
) -> dict[str, object]:
    until = str(node.get("until") or "COMPLETE")
    max_iterations = int(node.get("max_iterations") or 1)
    last_output = ""
    consecutive_failures = 0
    for iteration in range(1, max_iterations + 1):
        iteration_succeeded = False
        try:
            if runtime_adapter:
                last_output = _execute_runtime_adapter_node(
                    context,
                    node=node,
                    node_id=node_id,
                    runtime_adapter=runtime_adapter,
                    artifacts_dir=artifacts_dir,
                    worktree_path=worktree_path,
                    extra_env={"AO_LOOP_ITERATION": str(iteration)},
                    log_suffix=f"-{iteration}",
                )
            else:
                _ensure_default_node_execution_allowed(context)
                _write_default_artifacts(context, node_id, artifacts_dir)
                last_output = until
            _validate_required_artifacts(context, node_id, artifacts_dir)
            iteration_succeeded = True
        except RuntimeError as error:
            consecutive_failures += 1
            last_output = str(error)
            append_event(
                context.run_dir / "workflow-event.jsonl",
                run_id=context.run_id,
                workflow=context.definition.name,
                step=f"loop:{node_id}",
                status="failed",
                message=f"iteration {iteration} failed (consecutive={consecutive_failures}): {error}",
                artifact_path=str(artifacts_dir),
            )
            if consecutive_failures >= 3:
                raise
        # 即使 iteration 失败，until 可能在之前的 iteration 中已达成，需要检查。
        if _loop_reached_until(
            node_id=node_id,
            until=until,
            artifacts_dir=artifacts_dir,
            output=last_output,
        ):
            return {"iterations": iteration, "output": last_output}
        # 只有 iteration "成功"但 until 未满足时，才检查 max_turns 截断导致的假成功。
        # error_max_turns 在 generic_cli._return_code_for_profile 中返回 0（软成功），
        # 但 loop 节点需要 until 实际达成。若连续 3 次 max_turns 截断仍未达成，
        # 停止 loop 避免无限重试（story 可能需要手动干预或提高 --max-turns）。
        if iteration_succeeded and _output_indicates_max_turns_truncation(last_output):
            consecutive_failures += 1
            append_event(
                context.run_dir / "workflow-event.jsonl",
                run_id=context.run_id,
                workflow=context.definition.name,
                step=f"loop:{node_id}",
                status="failed",
                message=f"iteration {iteration} hit max_turns without reaching until={until!r} (consecutive={consecutive_failures})",
                artifact_path=str(artifacts_dir),
            )
            if consecutive_failures >= 3:
                raise RuntimeError(
                    f"loop node {node_id} aborted: {consecutive_failures} consecutive iterations "
                    f"hit max_turns without reaching until={until!r}; "
                    f"consider raising --max-turns or splitting the story"
                )
        elif iteration_succeeded:
            consecutive_failures = 0
    raise RuntimeError(
        f"loop node {node_id} did not reach until={until!r} "
        f"after {max_iterations} iterations; last output length={len(last_output)}"
    )


def _loop_reached_until(
    *,
    node_id: str,
    until: str,
    artifacts_dir: Path,
    output: str,
) -> bool:
    if node_id == "implement-story-loop":
        return _all_stories_passed(artifacts_dir / "stories.json")
    return _output_contains_completion_signal(output, until)


def _output_indicates_max_turns_truncation(output: str) -> bool:
    # claude code CLI 在 --output-format json 下，max_turns 截断时输出：
    # {"type":"result","subtype":"error_max_turns",...,"terminal_reason":"max_turns",...}
    # generic_cli._return_code_for_profile 将其视为软成功（返回 0），
    # 但 loop 节点需要识别这种"假成功"以避免无限重试。
    return (
        '"subtype":"error_max_turns"' in output
        or '"subtype": "error_max_turns"' in output
        or '"terminal_reason":"max_turns"' in output
        or '"terminal_reason": "max_turns"' in output
    )


def _all_stories_passed(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    stories = payload.get("stories") if isinstance(payload, dict) else payload
    if not isinstance(stories, list) or not stories:
        return False
    return all(isinstance(story, dict) and story.get("passes") is True for story in stories)


def _output_contains_completion_signal(output: str, until: str) -> bool:
    promise = f"<promise>{until}</promise>"
    if promise in output:
        return True
    return any(line.strip() == until for line in output.splitlines())


def _create_node_runtime_adapter(context: RunContext) -> AgentRuntimeAdapter | None:
    if context.runtime_adapter:
        profile_path = None
        if context.runtime_adapter.profile is not None:
            profile_path = context.project_root / context.runtime_adapter.profile
        return create_adapter(
            context.runtime_adapter.adapter_id,
            command=list(context.runtime_adapter.command),
            profile_path=profile_path,
        )
    return None


def _ensure_default_node_execution_allowed(context: RunContext) -> None:
    if context.definition.name == "spec-driven":
        raise RuntimeError("project runtime adapter is required for spec-driven runs")
    if context.project_root.resolve() != context.repo_root.resolve():
        raise RuntimeError("project runtime adapter is required for project workflow runs")


def _execute_runtime_adapter_node(
    context: RunContext,
    *,
    node: dict[str, object],
    node_id: str,
    runtime_adapter: AgentRuntimeAdapter,
    artifacts_dir: Path,
    worktree_path: Path,
    extra_env: dict[str, str] | None = None,
    log_suffix: str = "",
) -> str:
    artifact_specs = tuple(_required_artifact_specs(context, node_id))
    request = NodeExecutionRequest(
        run_id=context.run_id,
        workflow=context.definition.name,
        node_id=node_id,
        node_type=str(node.get("type") or "adapter_command"),
        command_name=str(node["command"]) if isinstance(node.get("command"), str) else None,
        prompt=str(node["prompt"]) if isinstance(node.get("prompt"), str) else None,
        worktree_path=worktree_path,
        artifacts_dir=artifacts_dir,
        node_dir=context.run_dir / "nodes" / node_id,
        runtime_env=_runtime_env_for_node(context),
        required_artifacts=artifact_specs,
        timeout_seconds=int(node.get("timeout_seconds") or 3600),
        output_format=node.get("output_format") if isinstance(node.get("output_format"), dict) else None,
        extra_env=extra_env,
        log_suffix=log_suffix,
    )
    if hasattr(runtime_adapter, "execute_node_request"):
        result = runtime_adapter.execute_node_request(context, request)
    else:
        result = runtime_adapter.execute_node(
            context,
            node=node,
            node_id=node_id,
            artifacts_dir=artifacts_dir,
            worktree_path=worktree_path,
            required_artifacts=[artifact.path for artifact in artifact_specs],
            extra_env=extra_env,
            log_suffix=log_suffix,
        )
    if result.return_code != 0:
        raise RuntimeError(f"node failed: {node_id}: adapter exited {result.return_code}")
    return result.output


def _runtime_env_for_node(context: RunContext) -> dict[str, str]:
    return stack_runtime_env(context.stack_contract)


def _validate_completed_stack_run(context: RunContext) -> None:
    if context.stack_contract is None:
        return
    validate_stack_acceptance_artifacts(
        context.run_dir / "artifacts",
        contract=context.stack_contract,
        run_dir=context.run_dir,
    )


def _changed_files(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--short", "--untracked-files=all"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        return []
    return [
        path
        for line in result.stdout.splitlines()
        if len(line) > 3
        for path in [line[3:].strip()]
        if _is_reportable_changed_file(path)
    ]


def _is_reportable_changed_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    parts = normalized.split("/")
    return "__pycache__" not in parts and not normalized.endswith(".pyc")
