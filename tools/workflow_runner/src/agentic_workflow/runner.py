import json
import time
from pathlib import Path
from uuid import uuid4

from .adapters import create_adapter
from .definitions import load_definition
from .events import append_event
from .infra_gates import CONTROL_PLANE_WORKFLOW, finalize_control_plane_run
from .models import RunContext, WorkflowInput
from .project_config import load_project_config
from .project_registry import resolve_project_root
from .reports import write_prepare_artifacts, write_run_report
from .stack_contract import (
    load_stack_contract,
    stack_contract_required,
    validate_stack_acceptance_artifacts,
)
from .subprocess_utils import run_command
from .workspace import ensure_workspace_ignored, write_run_index


ACTIVE_RUN_STATUSES = {
    "PREPARED",
    "RUNNING",
    "NEEDS_COMPLETE",
    "NEEDS_VERIFICATION",
}


def create_run_context(
    repo_root: Path,
    workflow_input: WorkflowInput,
    run_id: str | None = None,
) -> RunContext:
    definition = load_definition(repo_root, workflow_input.workflow)
    _validate_input(definition.primary_inputs, workflow_input)
    effective_run_id = run_id or f"run_{uuid4().hex[:12]}"
    project_root, project = resolve_project_root(
        control_repo_root=repo_root,
        project=workflow_input.project,
        project_root=workflow_input.project_root,
    )
    is_project_run = project is not None or project_root.resolve() != repo_root.resolve()
    project_config = load_project_config(project_root) if is_project_run else None
    stack_contract = (
        load_stack_contract(
            project_root,
            project_id=project.project_id if project else project_root.name,
        )
        if stack_contract_required(definition.name, is_project_run=is_project_run)
        else None
    )
    effective_workspace_root = project_root / ".agentic" if is_project_run else None
    effective_worktrees_dir = (
        project_config.runtime.resolve_worktrees_dir(project_root) if project_config else None
    )
    effective_logs_dir = project_config.runtime.resolve_logs_dir(project_root) if project_config else None
    effective_run_dir = (
        project_config.runtime.resolve_runs_dir(project_root) / effective_run_id
        if project_config
        else repo_root / "ai_docs" / "runs" / effective_run_id
    )
    return RunContext(
        run_id=effective_run_id,
        repo_root=repo_root,
        project_root=project_root,
        project_id=project.project_id if project else None,
        project_name=project.name if project else (project_root.name if is_project_run else None),
        workspace_root=effective_workspace_root,
        worktrees_dir=effective_worktrees_dir,
        logs_dir=effective_logs_dir,
        run_dir=effective_run_dir,
        definition=definition,
        workflow_input=workflow_input,
        project_config=project_config,
        runtime_adapter=project_config.adapter if project_config else None,
        verify_command=project_config.verify.command if project_config else None,
        stack_contract=stack_contract,
        stack_contract_ref=stack_contract.ref if stack_contract else None,
    )


def prepare_run(context: RunContext) -> Path:
    _assert_no_active_duplicate_run(context)
    if context.workspace_root is not None:
        ensure_workspace_ignored(context.project_root, context.workspace_root)
    write_prepare_artifacts(context)
    if context.workspace_root is not None:
        write_run_index(
            run_id=context.run_id,
            project_id=context.project_id,
            project_name=context.project_name,
            project_root=context.project_root,
            run_dir_path=context.run_dir,
            worktrees_dir_path=context.worktrees_dir,
            logs_dir_path=context.logs_dir,
        )
    append_event(
        context.run_dir / "workflow-event.jsonl",
        run_id=context.run_id,
        workflow=context.definition.name,
        step="prepare",
        status="passed",
        message="工作流运行已准备",
        artifact_path=str(context.run_dir / "agent-instructions.md"),
    )
    return context.run_dir


def _assert_no_active_duplicate_run(context: RunContext) -> None:
    runs_root = context.run_dir.parent
    if not runs_root.exists():
        return
    current_project_root = _normalize_path(context.project_root)
    current_primary = _normalized_primary_values(
        context.workflow_input.primary_values(),
        context.repo_root,
    )
    for run_json in runs_root.glob("*/run.json"):
        if run_json.parent.name == context.run_id:
            continue
        state = _read_run_state(run_json)
        if not state:
            continue
        status = str(state.get("status") or "").upper()
        if status not in ACTIVE_RUN_STATUSES:
            continue
        if state.get("workflow") != context.definition.name:
            continue
        project_root = state.get("project_root")
        if (
            not isinstance(project_root, str)
            or _normalize_path(Path(project_root)) != current_project_root
        ):
            continue
        workflow_input = state.get("workflow_input")
        if not isinstance(workflow_input, dict):
            continue
        prior_primary = _normalized_primary_values(
            WorkflowInput.from_dict(workflow_input).primary_values(),
            context.repo_root,
        )
        if prior_primary != current_primary:
            continue
        existing_run_id = str(state.get("run_id") or run_json.parent.name)
        raise RuntimeError(
            "已有活跃 workflow run 使用相同 workflow/project/primary input: "
            f"{existing_run_id} (status={status}). "
            f"请先执行 `python scripts/ao.py workflow resume --run-id {existing_run_id}` "
            f"或 `python scripts/ao.py workflow cleanup --run-id {existing_run_id}`。"
        )


def _read_run_state(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _normalized_primary_values(values: dict[str, str], repo_root: Path) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for name, value in values.items():
        if name.endswith("_path"):
            path = Path(value).expanduser()
            if not path.is_absolute():
                path = repo_root / path
            normalized[name] = _normalize_path(path)
        else:
            normalized[name] = value.strip()
    return normalized


def _normalize_path(path: Path) -> str:
    return str(path.resolve(strict=False)).replace("\\", "/").casefold()


def complete_run(
    context: RunContext,
    *,
    summary: str,
    changed_files: list[str],
    skip_verify: bool,
) -> int:
    started = time.monotonic()
    stack_gate = _run_stack_acceptance_gate(context)
    if context.definition.name == CONTROL_PLANE_WORKFLOW:
        gate_result = finalize_control_plane_run(context, skip_verify=skip_verify)
        return_code = gate_result.return_code
        status = gate_result.status.lower()
        verification = gate_result.verification
        changed_files = gate_result.changed_files
    else:
        verification = "已跳过"
        return_code = 0
        if not skip_verify:
            return_code, verification = _run_verification(
                context,
                verify_policy=context.definition.verify_policy,
                changed_files=changed_files,
            )
        status = "passed" if return_code == 0 else "failed"
    if stack_gate:
        verification = f"{verification}\n\nstack acceptance gate: PASSED"

    duration_ms = int((time.monotonic() - started) * 1000)
    write_run_report(
        context,
        status=status,
        summary=summary,
        verification=verification,
        changed_files=changed_files,
    )
    append_event(
        context.run_dir / "workflow-event.jsonl",
        run_id=context.run_id,
        workflow=context.definition.name,
        step="complete",
        status=status,
        message="工作流运行已完成",
        artifact_path=str(context.run_dir / "run-report.md"),
        duration_ms=duration_ms,
    )
    _write_completion_state(
        context,
        status=status.upper(),
        return_code=return_code,
        changed_files=changed_files,
    )
    return return_code


def _run_stack_acceptance_gate(context: RunContext) -> bool:
    if context.stack_contract is None:
        return False
    validate_stack_acceptance_artifacts(
        context.run_dir / "artifacts",
        contract=context.stack_contract,
        run_dir=context.run_dir,
    )
    return True


def execute_run(
    context: RunContext,
    *,
    adapter_name: str,
    adapter_command: list[str] | None,
    adapter_profile: str | None = None,
    skip_verify: bool,
    timeout_seconds: int,
) -> int:
    prepare_run(context)
    profile_path = _resolve_adapter_profile(context.repo_root, adapter_profile)
    adapter = create_adapter(
        adapter_name,
        command=adapter_command,
        timeout_seconds=timeout_seconds,
        profile_path=profile_path,
    )
    result = adapter.execute(context)
    if result.return_code != 0:
        write_run_report(
            context,
            status="failed",
            summary=result.summary,
            verification="adapter 执行失败，已跳过验证",
            changed_files=result.changed_files,
        )
        append_event(
            context.run_dir / "workflow-event.jsonl",
            run_id=context.run_id,
            workflow=context.definition.name,
            step="complete",
            status="failed",
            message="工作流运行在 adapter 阶段失败",
            artifact_path=str(context.run_dir / "run-report.md"),
        )
        _write_completion_state(
            context,
            status="FAILED",
            return_code=result.return_code,
            changed_files=result.changed_files,
        )
        return result.return_code
    return complete_run(
        context,
        summary=result.summary,
        changed_files=result.changed_files,
        skip_verify=skip_verify,
    )


def _validate_input(allowed_inputs: tuple[str, ...], workflow_input: WorkflowInput) -> None:
    primary_values = workflow_input.primary_values()
    if len(primary_values) != 1:
        allowed = ", ".join(allowed_inputs)
        raise ValueError(f"该工作流必须且只能提供一个主输入：{allowed}")
    selected = next(iter(primary_values))
    if selected not in allowed_inputs:
        allowed = ", ".join(allowed_inputs)
        raise ValueError(f"该工作流不允许输入 `{selected}`；允许输入：{allowed}")


def _format_verification(returncode: int, stdout: str | None, stderr: str | None) -> str:
    output = ((stdout or "") + "\n" + (stderr or "")).strip()
    if len(output) > 6000:
        output = output[-6000:]
    return f"退出码={returncode}\n\n```text\n{output}\n```"


def _run_verification(
    context: RunContext,
    *,
    verify_policy: str,
    changed_files: list[str],
    timeout_seconds: int = 180,
) -> tuple[int, str]:
    if verify_policy == "control-plane":
        commands = [
            ["python", "scripts/ao.py", "agentic-check"],
        ]
        if _touches_workflow_runner(changed_files):
            commands.append(
                [
                    "uv",
                    "run",
                    "--project",
                    "tools/workflow_runner",
                    "python",
                    "-m",
                    "pytest",
                    "tools/workflow_runner/tests",
                ]
            )
        return _run_verification_commands(
            context.repo_root,
            commands,
            timeout_seconds=timeout_seconds,
        )

    command = list(context.verify_command or ("python", "scripts/ao.py", "verify"))
    cwd = context.project_root if context.verify_command else context.repo_root
    return _run_verification_commands(cwd, [command], timeout_seconds=timeout_seconds)


def _run_verification_commands(
    repo_root: Path,
    commands: list[list[str]],
    *,
    timeout_seconds: int,
) -> tuple[int, str]:
    sections = []
    final_return_code = 0
    for command in commands:
        result = run_command(command, cwd=repo_root, timeout_seconds=timeout_seconds)
        if result.return_code != 0 and final_return_code == 0:
            final_return_code = result.return_code
        sections.append(
            "COMMAND: "
            + " ".join(command)
            + "\n"
            + _format_verification(result.return_code, result.stdout, result.stderr)
        )
        if result.return_code != 0:
            break
    return final_return_code, "\n\n".join(sections)


def _touches_workflow_runner(changed_files: list[str]) -> bool:
    normalized = [path.replace("\\", "/").lstrip("./") for path in changed_files]
    return any(
        path == "scripts/ao.py" or path.startswith("tools/workflow_runner/") for path in normalized
    )


def _resolve_adapter_profile(repo_root: Path, adapter_profile: str | None) -> Path | None:
    if not adapter_profile:
        return None
    path = Path(adapter_profile)
    return path if path.is_absolute() else repo_root / path


def _write_completion_state(
    context: RunContext,
    *,
    status: str,
    return_code: int,
    changed_files: list[str],
) -> None:
    state_path = context.run_dir / "run.json"
    if state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
    else:
        state = {
            "run_id": context.run_id,
            "workflow": context.definition.name,
            "project_root": str(context.project_root),
            "workflow_input": context.workflow_input.to_dict(),
        }
    state["status"] = status
    state["return_code"] = return_code
    state["changed_files"] = changed_files
    if status != "PASSED":
        state["complete_command"] = (
            f"python scripts/ao.py ao-infra complete --run-id {context.run_id}"
        )
    elif "complete_command" in state:
        state.pop("complete_command", None)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
