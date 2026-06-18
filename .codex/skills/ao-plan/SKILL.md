---
name: ao-plan
description: 执行当前项目的普通功能时使用。对应 plan-execute E2E 工作流，适合已有明确需求、计划或规格后的端到端开发。
---

# ao-plan

本 Skill 服务 `/ao-plan` 命令，执行 `plan-execute` E2E 工作流。用户可以只给 goal；workflow 负责生成标准 slice brief、plan、tasks 和 task graph 后再执行。

## 触发场景

- 用户给出一个明确功能目标。
- 用户已有 plan、goal 或 spec，希望完成一个开发闭环。
- 功能需要后端、前端、collector、测试或 e2e 同步推进。
- 需求不需要重新定义产品目标、用户角色、业务对象、数据模型、隐私或安全边界。

## 输入

命令后的内容可以是自然语言目标或文件路径，也可以带已注册业务项目：

```text
/ao-plan 实现客户端 outbox 上传，断网时本地排队，恢复后继续上传
/ao-plan --project app-a 实现客户端 outbox 上传，断网时本地排队，恢复后继续上传
/ao-plan ai_docs/plans/outbox-upload.md
```

长期业务项目使用 `--project <name>`；一次性目标仓库可使用 `--project-root <path>`。
`scope` 只用于目标仓库内显式写入边界，或 `agentic-infra`、`control-plane`、`repo`。

## 执行规则

1. 全程使用中文输出。
2. 读取 `AGENTS.md`。
3. 读取 `commands/ao-plan.md`。
4. 读取 `.agentic/workflow/workflow-governance.md`。
5. 读取 `.agentic/workflow/plan-execute.md`。
6. 读取 `.agentic/workflow/definitions/plan-execute.json`。
7. 业务项目运行前必须能读取 confirmed `.agentic/stack-contract.json`；缺失时停止并要求先确认项目级技术栈契约。
8. 根据用户输入使用 `python scripts/ao.py plan-execute run ...` 启动完整运行。
9. 读取命令输出 `run_dir` 中的 `agent-instructions.md`；控制面 run_dir 位于 `ai_docs/runs/<run_id>/`，业务项目 run_dir 位于目标项目 `runtime.runs_dir/<run_id>/`。
10. workflow 必须完成 scope-resolve、slice brief、plan generation、plan contract gate、task graph gate、task loop、integration verify、independent review、fix、acceptance 和 run-report.md。
11. 未提供 `plan_path` 时，workflow 必须先生成 `slice-brief.md`、标准 `plan.md`、`tasks.json` 和 `task-graph.json`。
12. `plan_path` 是高级入口，必须被 gate；缺少验收、组件、验证命令、done signal 或依赖图时不得执行。
13. `plan.md`、`tasks.json` 和 `task-graph.json` 必须引用同一 `stack_contract_ref`，task 必须绑定契约组件、源码根、验收项、验证命令和 done signal。
14. 最终必须产出带同一 `stack_contract_ref` 的 `acceptance-matrix.json`、`component-evidence.json`、`command-coverage.json`。
15. 未提供 project、project_root 或 scope 且命中多个项目时停止，要求用户使用 `--project`。
16. 每个 task 必须声明 `write_set`，worker 只能修改自己的 `write_set`。
17. 交付前必须运行项目验证入口。

## 禁止事项

- 不要绕过 workflow runner。
- 不要生成或改变产品级 `product-contract.json`、`stories.json` 或长期 acceptance matrix。
- 不要把大 PRD 当成普通小功能直接实现；涉及产品事实变化时停止并建议 `/ao-spec`。
- 不要在目标项目不唯一时自行选择项目。
- 不要上传或写入原始日志、token、auth、prompt 或敏感输出。
- 不要自动切换工作流，除非用户明确要求。
