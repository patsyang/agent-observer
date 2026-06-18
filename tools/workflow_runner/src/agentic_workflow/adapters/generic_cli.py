from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from agentic_workflow.adapters._prompts import (
    build_adapter_node_prompt,
    build_adapter_prompt,
    node_command_content,
    optional_str,
)
from agentic_workflow.adapters.adapter_runtime import (
    changed_files,
    effective_node_return_code,
    missing_required_artifacts,
    node_env,
    read_final_message,
    waiting_state_reason,
    write_adapter_diagnostics,
)
from agentic_workflow.adapters.base import AdapterResult, NodeAdapterResult
from agentic_workflow.events import append_event
from agentic_workflow.models import NodeExecutionRequest, RunContext
from agentic_workflow.runtime_profile import (
    RuntimeProfile,
    RuntimeProfileError,
    conditions_pass,
    json_path_value,
    last_non_empty_line,
    load_runtime_profile,
    parse_stdout_json,
    render_template,
    resolve_executable,
    stdout_jsonl_text,
)
from agentic_workflow.subprocess_utils import run_command


class GenericCliAdapter:
    name = "generic-cli"

    def __init__(
        self,
        command: list[str] | None = None,
        timeout_seconds: int = 3600,
        profile_path: Path | None = None,
    ) -> None:
        if not command:
            raise ValueError("generic-cli adapter requires a runtime command")
        if profile_path is None:
            raise ValueError("generic-cli adapter requires a runtime profile")
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.profile_path = profile_path

    def execute(self, context: RunContext) -> AdapterResult:
        started = time.monotonic()
        profile = load_runtime_profile(self.profile_path)
        prompt_path = context.run_dir / profile.prompt_file_name
        stdout_path = context.run_dir / "generic-cli.stdout.log"
        stderr_path = context.run_dir / "generic-cli.stderr.log"
        final_message_path = context.run_dir / "generic-cli-final-message.md"
        prompt = build_adapter_prompt(context, "Generic CLI")
        if profile.prompt_write_file:
            prompt_path.write_text(prompt, encoding="utf-8")

        result = run_command(
            _command_for_profile(
                self.command,
                profile,
                cwd=context.repo_root,
                context=context,
                node_dir=context.run_dir,
                artifacts_dir=context.run_dir / "artifacts",
                prompt_path=prompt_path,
                final_message_path=final_message_path,
                prompt=prompt,
                node_id="",
            ),
            cwd=context.repo_root,
            stdin=_stdin_for_profile(profile, prompt),
            timeout_seconds=self.timeout_seconds,
        )
        stdout_path.write_text(result.stdout, encoding="utf-8")
        stderr_path.write_text(result.stderr, encoding="utf-8")
        payload = _stdout_payload(profile, result.stdout)
        final_message = _final_message_for_profile(
            profile,
            stdout=result.stdout,
            payload=payload,
            final_message_path=final_message_path,
            return_code=result.return_code,
        )
        final_message_path.write_text(final_message, encoding="utf-8")
        return_code = _return_code_for_profile(profile, result.return_code, payload)
        status = "passed" if return_code == 0 else "failed"
        append_event(
            context.run_dir / "workflow-event.jsonl",
            run_id=context.run_id,
            workflow=context.definition.name,
            step="adapter:generic-cli",
            status=status,
            message="Generic CLI adapter 执行结束",
            artifact_path=str(final_message_path),
            duration_ms=int((time.monotonic() - started) * 1000),
        )
        summary = read_final_message(
            final_message_path,
            return_code,
            adapter_label="Generic CLI",
        )
        return AdapterResult(return_code, summary, changed_files(context.repo_root))

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
        return _execute_generic_cli_node(
            self.command,
            self.timeout_seconds,
            self.profile_path,
            context,
            node=node,
            node_id=node_id,
            artifacts_dir=artifacts_dir,
            worktree_path=worktree_path,
            required_artifacts=required_artifacts,
            extra_env=extra_env,
            log_suffix=log_suffix,
        )

    def execute_node_request(
        self,
        context: RunContext,
        request: NodeExecutionRequest,
    ) -> NodeAdapterResult:
        return _execute_generic_cli_node(
            self.command,
            request.timeout_seconds or self.timeout_seconds,
            self.profile_path,
            context,
            node={
                "id": request.node_id,
                "type": request.node_type,
                "command": request.command_name,
                "prompt": request.prompt,
                "output_format": request.output_format,
            },
            node_id=request.node_id,
            artifacts_dir=request.artifacts_dir,
            worktree_path=request.worktree_path,
            required_artifacts=request.required_artifact_paths,
            extra_env=request.extra_env,
            log_suffix=request.log_suffix,
            node_dir=request.node_dir,
            runtime_env=request.runtime_env,
        )


def _execute_generic_cli_node(
    command: list[str],
    timeout_seconds: int,
    profile_path: Path,
    context: RunContext,
    *,
    node: dict[str, Any],
    node_id: str,
    artifacts_dir: Path,
    worktree_path: Path,
    required_artifacts: list[str],
    extra_env: dict[str, str] | None,
    log_suffix: str,
    node_dir: Path | None = None,
    runtime_env: dict[str, str] | None = None,
) -> NodeAdapterResult:
    started = time.monotonic()
    profile = load_runtime_profile(profile_path)
    node_dir = node_dir or context.run_dir / "nodes" / node_id
    node_dir.mkdir(parents=True, exist_ok=True)
    final_message_path = node_dir / f"generic-cli-final-message{log_suffix}.md"
    prompt_path = node_dir / profile.prompt_file_name
    prompt = build_adapter_node_prompt(
        context,
        adapter_label="Generic CLI",
        node=node,
        node_id=node_id,
        artifacts_dir=artifacts_dir,
        worktree_path=worktree_path,
        required_artifacts=required_artifacts,
        command_name=optional_str(node.get("command")),
        command_content=node_command_content(context, optional_str(node.get("command"))),
        prompt=optional_str(node.get("prompt")),
    )
    if profile.prompt_write_file:
        prompt_path.write_text(prompt, encoding="utf-8")

    result = run_command(
        _command_for_profile(
            command,
            profile,
            cwd=worktree_path,
            context=context,
            node_dir=node_dir,
            artifacts_dir=artifacts_dir,
            prompt_path=prompt_path,
            final_message_path=final_message_path,
            prompt=prompt,
            node_id=node_id,
        ),
        cwd=worktree_path,
        env=node_env(
            context,
            node_id=node_id,
            artifacts_dir=artifacts_dir,
            worktree_path=worktree_path,
            required_artifacts=required_artifacts,
            extra_env=extra_env,
            runtime_env=runtime_env,
        ),
        stdin=_stdin_for_profile(profile, prompt),
        timeout_seconds=timeout_seconds,
    )
    (node_dir / f"stdout{log_suffix}.log").write_text(result.stdout, encoding="utf-8")
    (node_dir / f"stderr{log_suffix}.log").write_text(result.stderr, encoding="utf-8")
    payload = _stdout_payload(profile, result.stdout)
    final_message = _final_message_for_profile(
        profile,
        stdout=result.stdout,
        payload=payload,
        final_message_path=final_message_path,
        return_code=result.return_code,
    )
    final_message_path.write_text(final_message, encoding="utf-8")
    missing = missing_required_artifacts(artifacts_dir, required_artifacts)
    waiting_state = waiting_state_reason(final_message)
    return_code = _return_code_for_profile(profile, result.return_code, payload)
    return_code = effective_node_return_code(return_code, missing, waiting_state)
    output = "\n".join(item for item in (result.stdout, result.stderr, final_message) if item)
    if missing:
        output = output + "\nmissing required artifacts: " + ", ".join(missing)
    if waiting_state:
        write_adapter_diagnostics(
            node_dir,
            reason=waiting_state,
            final_message_path=final_message_path,
        )
        output = output + f"\nwaiting-state final message rejected: {waiting_state}"
    append_event(
        context.run_dir / "workflow-event.jsonl",
        run_id=context.run_id,
        workflow=context.definition.name,
        step=f"adapter:generic-cli:{node_id}",
        status="passed" if return_code == 0 else "failed",
        message="Generic CLI adapter 节点执行结束",
        artifact_path=str(final_message_path),
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return NodeAdapterResult(return_code, output)


def _command_for_profile(
    command: list[str],
    profile: RuntimeProfile,
    *,
    cwd: Path,
    context: RunContext,
    node_dir: Path,
    artifacts_dir: Path,
    prompt_path: Path,
    final_message_path: Path,
    prompt: str,
    node_id: str,
) -> list[str]:
    values = {
        "cwd": str(cwd),
        "repo_root": str(context.repo_root),
        "project_root": str(context.project_root),
        "run_dir": str(context.run_dir),
        "node_dir": str(node_dir),
        "artifacts_dir": str(artifacts_dir),
        "prompt_file": str(prompt_path),
        "final_message_path": str(final_message_path),
        "node_id": node_id,
        "workflow": context.definition.name,
        "prompt": prompt,
    }
    args = [render_template(item, values) for item in profile.invocation_args]
    return [*resolve_executable(command), *args]


def _stdin_for_profile(profile: RuntimeProfile, prompt: str) -> str | None:
    if profile.invocation_stdin is None:
        return None
    return render_template(profile.invocation_stdin, {"prompt": prompt})


def _stdout_payload(profile: RuntimeProfile, stdout: str) -> object | None:
    if profile.final_message_source != "stdout_json" and not profile.success_json_conditions:
        return None
    try:
        return parse_stdout_json(stdout)
    except RuntimeProfileError:
        return None


def _final_message_for_profile(
    profile: RuntimeProfile,
    *,
    stdout: str,
    payload: object | None,
    final_message_path: Path,
    return_code: int,
) -> str:
    if profile.final_message_source == "final_message_file":
        return read_final_message(
            final_message_path,
            return_code,
            adapter_label="Generic CLI",
        )
    if profile.final_message_source == "stdout_text":
        return stdout.strip()
    if profile.final_message_source == "stdout_jsonl_text":
        text = stdout_jsonl_text(stdout)
        if text:
            return text
    if payload is not None and profile.final_message_json_path:
        try:
            value = json_path_value(payload, profile.final_message_json_path)
            return str(value).strip()
        except RuntimeProfileError:
            pass
    if profile.final_message_fallback == "last_non_empty_stdout_line":
        return last_non_empty_line(stdout)
    return ""


def _return_code_for_profile(
    profile: RuntimeProfile,
    process_return_code: int,
    payload: object | None,
) -> int:
    if process_return_code not in profile.success_exit_codes:
        return process_return_code or 1
    if profile.success_json_conditions and (
        payload is None or not conditions_pass(payload, profile.success_json_conditions)
    ):
        return 1
    return 0
