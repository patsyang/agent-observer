from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentic_workflow.models import RunContext


def build_adapter_prompt(context: RunContext, adapter_label: str) -> str:
    instructions = (context.run_dir / "agent-instructions.md").read_text(encoding="utf-8")
    return f"""你正在通过 Agentic Factory 的 {adapter_label} runtime adapter 执行一次工作流。

请在仓库根目录 `{context.repo_root}` 中完成任务。

必须遵守：
- 读取并遵守 `AGENTS.md`。
- 读取 `.agentic/workflow/workflow-governance.md`。
- 读取 `{context.definition.contract_path}`。
- 执行下面的运行说明。
- 不要上传或写入原始 token、auth、prompt、日志正文。
- 使用 `python scripts/ao.py ...` 入口完成报告和验证。

{instructions}
"""


def build_adapter_node_prompt(
    context: RunContext,
    *,
    adapter_label: str,
    node: dict[str, Any],
    node_id: str,
    artifacts_dir: Path,
    worktree_path: Path,
    required_artifacts: list[str],
    command_name: str | None = None,
    command_content: str = "",
    prompt: str | None = None,
) -> str:
    instructions = (context.run_dir / "agent-instructions.md").read_text(encoding="utf-8")
    node_contract = json.dumps(node, ensure_ascii=False, indent=2)
    required = "\n".join(f"- `{name}`" for name in required_artifacts) or "- 无"
    imported_source = _read_optional_text(artifacts_dir / "imported-source.json")
    task = _node_task_instruction(
        workflow=context.definition.name,
        node_id=node_id,
        required_artifacts=required_artifacts,
    )
    command_section = _format_command_section(command_name, command_content, prompt)
    stack_section = _format_stack_contract_section(context)
    return f"""你正在通过 Agentic Factory 的 {adapter_label} runtime adapter 执行单个工作流节点。

必须在本次非交互执行中完成当前节点；不要回复“请提供任务”，不要等待用户补充。

工作目录：`{worktree_path}`
控制仓库：`{context.repo_root}`
目标项目：`{context.project_root}`
运行目录：`{context.run_dir}`
产物目录：`{artifacts_dir}`
workflow：`{context.definition.name}`
node：`{node_id}`
workflow_input：`{context.workflow_input.__dict__}`

项目级技术栈契约：

{stack_section}

必须遵守：
- 读取并遵守目标工作目录中的 `AGENTS.md`（如果存在）。
- 读取工作流契约 `{context.definition.contract_path}`。
- 读取 `{context.run_dir / "input.json"}`。
- 读取 `{context.run_dir / "artifacts" / "scope-resolution.json"}`。
- 如果上方存在项目级技术栈契约，必须读取契约文件并在关键 JSON/Markdown 产物中写入相同的 `stack_contract_ref`。
- 读取产物目录中已经存在的上游产物，并把它们作为当前节点输入。
- 只完成当前 node，不跳过 workflow runner 的 artifact gate。
- 必须把下列 required artifacts 写入产物目录，而不是写入仓库根目录：
{required}
- 产物必须可被后续节点直接使用，不能是占位、空文件、mock-only 证明或 screenshot-only proof。
- 不要上传或写入原始 token、auth、prompt、日志正文。
- 如果 node 定义包含 `until`，只有满足该条件时，最终回复才包含对应 `until` 字符串。
- 不要回复“已就绪”“请提供任务”“请提供输入”等等待态文本；本提示已经包含完整任务。

本节点必须立即执行的任务：

{task}

节点命令内容：

{command_section}

已解析输入：

```json
{imported_source or "{}"}
```

节点定义：

```json
{node_contract}
```

运行说明：

{instructions}
"""


def node_command_content(context: RunContext, command_name: str | None) -> str:
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


def optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


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
