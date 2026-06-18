import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from agentic_workflow.adapters._prompts import (
    build_adapter_node_prompt,
    build_adapter_prompt,
)
from agentic_workflow.adapters.base import AdapterResult, NodeAdapterResult
from agentic_workflow.events import append_event
from agentic_workflow.models import NodeExecutionRequest, RunContext
from agentic_workflow.subprocess_utils import run_command


WAITING_STATE_PATTERNS = (
    "请提供",
    "需要你提供",
    "我已就绪",
    "等待输入",
    "无法开始",
    "没有看到具体任务",
)


class CodexAdapter:
    name = "codex"

    def __init__(self, command: list[str] | None = None, timeout_seconds: int = 3600) -> None:
        self.command = command or ["codex"]
        self.timeout_seconds = timeout_seconds

    def execute(self, context: RunContext) -> AdapterResult:
        started = time.monotonic()
        prompt_path = context.run_dir / "codex-prompt.md"
        stdout_path = context.run_dir / "codex.stdout.log"
        stderr_path = context.run_dir / "codex.stderr.log"
        final_message_path = context.run_dir / "codex-final-message.md"
        prompt = build_codex_prompt(context)
        prompt_path.write_text(prompt, encoding="utf-8")

        result = run_command(
            [
                *self.command,
                "exec",
                "--cd",
                str(context.repo_root),
                "--sandbox",
                "workspace-write",
                "--output-last-message",
                str(final_message_path),
                "-",
            ],
            cwd=context.repo_root,
            stdin=prompt,
            timeout_seconds=self.timeout_seconds,
        )
        stdout_path.write_text(result.stdout, encoding="utf-8")
        stderr_path.write_text(result.stderr, encoding="utf-8")
        status = "passed" if result.return_code == 0 else "failed"
        duration_ms = int((time.monotonic() - started) * 1000)
        append_event(
            context.run_dir / "workflow-event.jsonl",
            run_id=context.run_id,
            workflow=context.definition.name,
            step="adapter:codex",
            status=status,
            message="Codex adapter 执行结束",
            artifact_path=str(final_message_path),
            duration_ms=duration_ms,
        )
        summary = _read_final_message(final_message_path, result.return_code)
        return AdapterResult(result.return_code, summary, _changed_files(context.repo_root))

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
        return _execute_codex_node(
            self.command,
            self.timeout_seconds,
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
        return _execute_codex_node(
            self.command,
            request.timeout_seconds or self.timeout_seconds,
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


def _execute_codex_node(
    command: list[str],
    timeout_seconds: int,
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
    node_dir = node_dir or context.run_dir / "nodes" / node_id
    node_dir.mkdir(parents=True, exist_ok=True)
    final_message_path = node_dir / f"codex-final-message{log_suffix}.md"
    result = run_command(
        [
            *command,
            "exec",
            "--cd",
            str(worktree_path),
            "--sandbox",
            "danger-full-access",
            "--output-last-message",
            str(final_message_path),
            "-",
        ],
        cwd=worktree_path,
        env=_node_env(
            context,
            node_id=node_id,
            artifacts_dir=artifacts_dir,
            worktree_path=worktree_path,
            required_artifacts=required_artifacts,
            extra_env=extra_env,
            runtime_env=runtime_env,
        ),
        stdin=build_codex_node_prompt(
            context,
            node=node,
            node_id=node_id,
            artifacts_dir=artifacts_dir,
            worktree_path=worktree_path,
            required_artifacts=required_artifacts,
            command_name=_optional_str(node.get("command")),
            command_content=_command_content(context, _optional_str(node.get("command"))),
            prompt=_optional_str(node.get("prompt")),
        ),
        timeout_seconds=timeout_seconds,
    )
    (node_dir / f"stdout{log_suffix}.log").write_text(result.stdout, encoding="utf-8")
    (node_dir / f"stderr{log_suffix}.log").write_text(result.stderr, encoding="utf-8")
    output = _codex_node_output(
        result.stdout,
        result.stderr,
        final_message_path,
        result.return_code,
    )
    missing = _missing_required_artifacts(artifacts_dir, required_artifacts)
    final_message = _read_final_message(final_message_path, result.return_code)
    waiting_state = _waiting_state_reason(final_message)
    return_code = _effective_node_return_code(result.return_code, missing, waiting_state)
    if missing:
        output = output + "\nmissing required artifacts: " + ", ".join(missing)
    if waiting_state:
        _write_adapter_diagnostics(
            node_dir,
            reason=waiting_state,
            final_message_path=final_message_path,
        )
        output = output + f"\nwaiting-state final message rejected: {waiting_state}"
    _append_codex_node_event(context, node_id, final_message_path, return_code, started)
    return NodeAdapterResult(
        return_code,
        output,
    )


def _append_codex_node_event(
    context: RunContext,
    node_id: str,
    final_message_path: Path,
    return_code: int,
    started: float,
) -> None:
    append_event(
        context.run_dir / "workflow-event.jsonl",
        run_id=context.run_id,
        workflow=context.definition.name,
        step=f"adapter:codex:{node_id}",
        status="passed" if return_code == 0 else "failed",
        message="Codex adapter 节点执行结束",
        artifact_path=str(final_message_path),
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def _codex_node_output(
    stdout: str,
    stderr: str,
    final_message_path: Path,
    return_code: int,
) -> str:
    return "\n".join(
        item
        for item in (stdout, stderr, _read_final_message(final_message_path, return_code))
        if item
    )


def _missing_required_artifacts(artifacts_dir: Path, required_artifacts: list[str]) -> list[str]:
    missing = []
    for name in required_artifacts:
        path = artifacts_dir / name
        if not path.exists() or (path.is_file() and path.stat().st_size == 0):
            missing.append(name)
    return missing


def _effective_node_return_code(
    return_code: int,
    missing: list[str],
    waiting_state: str | None = None,
) -> int:
    if return_code == 0 and waiting_state:
        return 66
    if return_code == 0 and missing:
        return 65
    return return_code


def _waiting_state_reason(final_message: str) -> str | None:
    normalized = final_message.strip()
    if not normalized:
        return None
    for pattern in WAITING_STATE_PATTERNS:
        if pattern in normalized:
            return pattern
    return None


def _write_adapter_diagnostics(
    node_dir: Path,
    *,
    reason: str,
    final_message_path: Path,
) -> None:
    (node_dir / "adapter-diagnostics.json").write_text(
        json.dumps(
            {
                "result": "FAIL",
                "reason": "waiting_state_final_message",
                "matched_text": reason,
                "final_message_path": str(final_message_path),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def build_codex_prompt(context: RunContext) -> str:
    return build_adapter_prompt(context, "Codex")


def build_codex_node_prompt(
    context: RunContext,
    *,
    node: dict[str, Any],
    node_id: str,
    artifacts_dir: Path,
    worktree_path: Path,
    required_artifacts: list[str],
    command_name: str | None = None,
    command_content: str = "",
    prompt: str | None = None,
) -> str:
    return build_adapter_node_prompt(
        context,
        adapter_label="Codex",
        node=node,
        node_id=node_id,
        artifacts_dir=artifacts_dir,
        worktree_path=worktree_path,
        required_artifacts=required_artifacts,
        command_name=command_name,
        command_content=command_content,
        prompt=prompt,
    )


def _node_task_instruction(
    *,
    workflow: str,
    node_id: str,
    required_artifacts: list[str],
) -> str:
    if workflow == "spec-driven":
        return _spec_driven_node_task(node_id)
    required = ", ".join(required_artifacts) or "节点要求的产物"
    return (
        f"- 根据运行说明完成 `{node_id}` 节点。\n"
        f"- 将 {required} 写入产物目录。\n"
        "- 如果信息不足，基于现有输入做最小合理假设并在产物中记录假设。"
    )


def _spec_driven_node_task(node_id: str) -> str:
    tasks = {
        "generate-product-prd": (
            "- 读取已解析输入中的 `imported_path` 或 `spec_path`，理解用户 PRD/规格。\n"
            "- 生成面向产品和验收的 `product-prd.md`，覆盖问题、目标、范围、关键流程、功能需求、非功能需求、隐私边界、验收标准和风险。\n"
            "- 不要等待补充输入；必要假设写入 `product-prd.md`。"
        ),
        "generate-product-state": (
            "- 读取 `imported-source.json` 中的 `imported_path` 或 workflow input 中的 `spec_path`/`plan_path`。\n"
            "- 生成 `product-prd.md`、`product-contract.json`、`stories.json` 和 `progress.md`。\n"
            "- 不要生成旧 `spec.md` seed；产品事实以 `product-contract.json` 和 `stories.json` 为准。"
        ),
        "validate-product-state": (
            "- 读取 `product-contract.json` 和 `stories.json`。\n"
            "- 检查产品目标、用户、workflow、隐私/安全、acceptance 和 story 依赖是否完整。\n"
            "- 写入 `product-state-gate.json` 和 `product-state-gate.md`。"
        ),
        "generate-production-spec": (
            "- 读取 `product-prd.md` 和已解析输入中的规格路径。\n"
            "- 生成可实现的 `production-spec.md`，包含数据模型、模块边界、接口/命令、验证策略、迁移/兼容和退出条件。"
        ),
        "generate-story-map": (
            "- 读取 `production-spec.md`。\n"
            "- 生成 `stories.json` 和 `task-graph.json`，把需求拆成可执行 story、依赖、验收点和验证命令。"
        ),
        "generate-implementation-plan": (
            "- 读取 `production-spec.md`、`stories.json` 和 `project-inspection.json`。\n"
            "- 生成人读 `plan.md`、`tasks.md`，以及权威 `tasks.json`、`task-graph.json`。\n"
            "- 每个 task 必须绑定 story/acceptance、component、files、verification_commands 和 done_signal。"
        ),
        "gate-implementation-plan": (
            "- 读取 `plan.md`、`tasks.md`、`tasks.json`、`task-graph.json`、`stories.json` 和 `product-contract.json`。\n"
            "- 校验 acceptance 覆盖、依赖无环、任务大小和验证命令。\n"
            "- 写入 `plan-gate.json` 和 `plan-gate.md`。"
        ),
        "implement-loop": (
            "- 按 `task-graph.json` 实施所有未完成任务并运行对应验证。\n"
            "- 写入 `implementation-state.json` 和 `progress.md`。\n"
            "- 只有任务和验证都完成时，最终回复才包含 `COMPLETE`。"
        ),
        "independent-review": (
            "- 审查实现、验证证据、隐私边界和未完成项。\n"
            "- 写入 `review.md`，用 PASS/FAIL 计数明确是否存在可行动问题。"
        ),
        "fix-loop": (
            "- 修复 `review.md` 中的可行动问题并写入 `fix.md`。\n"
            "- 只有没有可行动问题时，最终回复才包含 `NO_ACTIONABLE_WARNINGS`。"
        ),
        "release-readiness-gate": (
            "- 汇总实现范围、验证、风险和发布阻断项。\n"
            "- 写入 `release-readiness.md`，明确 PASS/FAIL 结论。"
        ),
        "e2e-proof": (
            "- 运行或汇总端到端行为验证证据。\n"
            "- 写入 `e2e-proof.md`，包含命令、退出码、关键断言和产物路径。"
        ),
        "acceptance-matrix": (
            "- 读取 PRD/spec/story/验证证据。\n"
            "- 写入 `acceptance-matrix.json`，每个验收项必须包含 acceptance_id、story_id、result=PASS 和非截图-only 的 behavioral evidence。"
        ),
    }
    return tasks.get(
        node_id,
        (
            f"- 根据 spec-driven 工作流上下文执行 `{node_id}` 节点。\n"
            "- 将节点 required artifacts 写入产物目录。\n"
            "- 信息不足时记录假设，不要等待补充输入。"
        ),
    )


def _read_optional_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _command_content(context: RunContext, command_name: str | None) -> str:
    if not command_name:
        return ""
    filename = f"{command_name}.md"
    candidates = [
        context.project_root / ".agentic" / "workflow" / "commands" / filename,
        context.repo_root / ".agentic" / "workflow" / "commands" / filename,
        context.repo_root / "commands" / filename,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.read_text(encoding="utf-8")
    return ""


def _format_command_section(
    command_name: str | None,
    command_content: str,
    prompt: str | None,
) -> str:
    if command_content:
        return f"`{command_name}`:\n\n```markdown\n{command_content}\n```"
    if prompt:
        return f"inline prompt:\n\n```text\n{prompt}\n```"
    return "未配置独立 command 文件；执行上方节点任务和节点定义。"


def _format_stack_contract_section(context: RunContext) -> str:
    if context.stack_contract_ref is None:
        return "- not_required"
    ref = context.stack_contract_ref
    return "\n".join(
        [
            f"- path: `{ref.path}`",
            f"- contract_id: `{ref.contract_id}`",
            f"- revision: `{ref.revision}`",
            f"- hash: `{ref.hash}`",
            "- 所有计划、实现、验证、review 和 acceptance 产物必须遵守该契约；如需偏离，必须失败并输出阻断原因，不能自行改用其他技术栈。",
        ]
    )


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _node_env(
    context: RunContext,
    *,
    node_id: str,
    artifacts_dir: Path,
    worktree_path: Path,
    required_artifacts: list[str],
    extra_env: dict[str, str] | None,
    runtime_env: dict[str, str] | None = None,
) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "AO_RUN_ID": context.run_id,
            "AO_WORKFLOW": context.definition.name,
            "AO_NODE_ID": node_id,
            "AO_ARTIFACTS_DIR": str(artifacts_dir),
            "AO_RUN_DIR": str(context.run_dir),
            "AO_PROJECT_ROOT": str(context.project_root),
            "AO_EXECUTION_ROOT": str(worktree_path),
            "AO_WORKTREE_PATH": str(worktree_path),
            "AO_REQUIRED_ARTIFACTS": json.dumps(required_artifacts, ensure_ascii=False),
        }
    )
    if extra_env:
        env.update(extra_env)
    if runtime_env:
        env.update(runtime_env)
    return env


def _read_final_message(path: Path, return_code: int) -> str:
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    return f"Codex adapter 已结束，退出码为 {return_code}。"


def _changed_files(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--short", "--untracked-files=all"],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        text=True,
    )
    if result.returncode != 0:
        return []
    files = []
    for line in result.stdout.splitlines():
        if len(line) > 3:
            files.append(line[3:].strip())
    return files
