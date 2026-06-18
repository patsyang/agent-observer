import json

from .models import RunContext


def write_prepare_artifacts(context: RunContext) -> None:
    context.run_dir.mkdir(parents=True, exist_ok=True)
    input_path = context.run_dir / "input.json"
    input_path.write_text(
        json.dumps(
            {
                "run_id": context.run_id,
                "workflow": context.workflow_input.workflow,
                "primary_input": context.workflow_input.primary_values(),
                "project": {
                    "project_id": context.project_id,
                    "project_name": context.project_name,
                    "project_root": str(context.project_root),
                    "workspace_root": str(context.workspace_root)
                    if context.workspace_root is not None
                        else None,
                },
                "stack_contract": context.stack_contract_ref.to_dict()
                if context.stack_contract_ref
                else None,
                "definition": {
                    "adapter": context.definition.adapter,
                    "contract_path": context.definition.contract_path,
                    "stages": list(context.definition.stages),
                    "verify_policy": context.definition.verify_policy,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    write_agent_instructions(context)
    (context.run_dir / "run.json").write_text(
        json.dumps(
            {
                "run_id": context.run_id,
                "workflow": context.definition.name,
                "status": "PREPARED",
                "project_root": str(context.project_root),
                "workflow_input": context.workflow_input.to_dict(),
                "complete_command": (
                    f"python scripts/ao.py workflow complete --workflow {context.definition.name} "
                    f"--run-id {context.run_id}"
                ),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    write_run_report(context, status="prepared", summary="工作流运行已准备，等待 Agent 执行。")


def write_agent_instructions(context: RunContext) -> None:
    stages = "\n".join(f"- {stage}" for stage in context.definition.stages)
    inputs = "\n".join(
        f"- {key}: {value}" for key, value in context.workflow_input.primary_values().items()
    )
    text = f"""# Agent 执行说明

## 运行信息

- run_id: `{context.run_id}`
- workflow: `{context.definition.name}`
- adapter: `{context.definition.adapter}`
- contract: `{context.definition.contract_path}`
- project: `{context.project_name or "control-plane"}`
- project_root: `{context.project_root}`
- artifacts_dir: `{context.run_dir}`
- stack_contract: `{context.stack_contract_ref.contract_id if context.stack_contract_ref else "not_required"}`
- stack_contract_hash: `{context.stack_contract_ref.hash if context.stack_contract_ref else "not_required"}`

## 输入

{inputs}

## 必须阶段

{stages}

## 治理要求

- 读取 `.agentic/workflow/workflow-governance.md`。
- 读取 `{context.definition.contract_path}`。
- 如存在项目级 stack contract，必须读取 `{context.stack_contract_ref.path if context.stack_contract_ref else "not_required"}`，并在关键产物中写入相同的 `stack_contract_ref`。
- 遵守 `AGENTS.md` 中的 TDD 和隐私规则。
- 完成任务前，将最终结果写入本运行目录。
"""
    (context.run_dir / "agent-instructions.md").write_text(text, encoding="utf-8")


def write_run_report(
    context: RunContext,
    *,
    status: str,
    summary: str,
    verification: str = "未运行",
    changed_files: list[str] | None = None,
    artifacts: list[str] | None = None,
) -> None:
    changed = "\n".join(f"- {path}" for path in changed_files or []) or "- 无"
    artifact_lines = [
        "- input: `input.json`",
        "- events: `workflow-event.jsonl`",
        "- instructions: `agent-instructions.md`",
    ]
    artifact_lines.extend(f"- {artifact}" for artifact in artifacts or [])
    artifact_text = "\n".join(artifact_lines)
    text = f"""# 工作流运行报告

## 运行信息

- run_id: `{context.run_id}`
- workflow: `{context.definition.name}`
- adapter: `{context.definition.adapter}`
- status: `{status}`

## 输入

```json
{json.dumps(context.workflow_input.primary_values(), ensure_ascii=False, indent=2)}
```

## 摘要

{summary}

## 变更文件

{changed}

## 验证结果

{verification}

## 产物

{artifact_text}

## 风险

- 未声明额外风险；如存在未覆盖风险，完成方必须在交付前补充本节。
"""
    (context.run_dir / "run-report.md").write_text(text, encoding="utf-8")
