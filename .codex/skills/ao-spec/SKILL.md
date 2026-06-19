---
name: ao-spec
description: 从 PRD、规格或大功能开始开发当前项目时使用。对应 spec-driven E2E 工作流，适合从 0 启动项目、高风险功能、数据处理或数据模型变更。
---

# ao-spec

本 Skill 服务 `/ao-spec` 命令，执行 `spec-driven` E2E 工作流。它用于建立或改变产品事实，不是普通功能切片入口。

## 触发场景

- 用户已有 PRD，希望从 0 开始开发项目。
- 用户已有规格文档，希望跑完整开发闭环。
- 功能涉及架构、数据模型、数据处理、安全或跨端流程。
- 需要生成或改变产品目标、用户、业务对象、状态、story、长期验收矩阵。

## 输入

从 0 开发时，命令后的内容应包含项目名、文档类型和源文档路径：

```text
/ao-spec agentic_factory -prd D:\workspace\prd\agentic_factory.md
/ao-spec agentic_factory -spec D:\workspace\prd\agentic_factory-spec.md
/ao-spec agentic_factory -plan D:\workspace\plans\agentic_factory-plan.md
```

项目名对应已注册业务项目；业务应用代码、规格、计划和 runtime adapter 都属于目标项目仓库。使用 `-plan` 时仍必须提供项目名，直接读取既有计划。如果用户没有提供必要路径或项目名，先询问缺失项，不要猜测。

## 执行规则

1. 全程使用中文输出。
2. 读取 `AGENTS.md`。
3. 读取 `commands/ao-spec.md`。
4. 读取 `.agentic/workflow/workflow-governance.md`。
5. 读取 `.agentic/workflow/spec-driven.md`。
6. 读取 `.agentic/workflow/definitions/spec-driven.json`。
7. 使用 `python scripts/ao.py spec-driven run --project-name <项目名> --prd <路径>`、`--project-name <项目名> --spec <路径>` 或 `--project-name <项目名> --plan-path <计划路径>` 启动完整运行。
8. 读取命令输出 `run_dir` 中的 `agent-instructions.md`；控制面 run_dir 位于 `ai_docs/runs/<run_id>/`，业务项目 run_dir 位于目标项目 `runtime.runs_dir/<run_id>/`。
9. 读取归档后的目标项目 `specs/NNN-english-slug/prd.md` 或 `spec.md`。
10. 运行时必须读取目标项目 `.agentic/project.json` 中的 runtime adapter 和 `verify.command`；缺失或无效时失败。
11. 业务项目运行前必须能读取 confirmed `.agentic/stack-contract.json`；缺失时停止并要求先确认项目级技术栈契约。
12. 不允许 fallback 到默认 Codex，不允许单次运行临时覆盖目标项目 runtime adapter 或 stack contract。
13. workflow import 阶段只归档 `source-prd.md` 或 `source-spec.md`，不得创建旧 `spec.md`、`plan.md`、`tasks.md` seed。
14. workflow 必须完成 product state、production spec、implementation plan、task graph、implement story loop、full verify、independent review、fix loop、release readiness、E2E proof、acceptance matrix 和 run-report.md。
15. 产品事实以 `product-contract.json` 和 `stories.json` 为准；实施事实以 `tasks.json` 和 `task-graph.json` 为准；Markdown 只是人读投影。
16. 进入实现前必须通过 product-state gate、production-spec gate 和 task-graph gate。
17. PRD 验收项必须全部进入 acceptance matrix，不能只完成单个切片后标记 passed。
18. 交付物必须达到可进入生产发布流程的 release candidate；占位 UI、mock-only 路径、假集成、screenshot-only proof 不得通过。
19. `review.md` 中 unresolved `FAIL` 必须阻断 release，不得写入通过的 acceptance matrix。
20. 前端验收必须包含真实用户行为证据，不能只验证页面加载、截图存在或静态文本。
21. 需要前端时必须检查 `frontend-template-selection.json.frontend_implementation`：技术栈来源、源码根、test/build/e2e 命令必须来自项目级 stack contract 并传入实现循环；从 0 项目默认独立前端，server-rendered 只能作为 contract 明确允许的例外。
22. 最终必须产出带同一 `stack_contract_ref` 的 `acceptance-matrix.json`、`component-evidence.json`、`command-coverage.json`。
23. 交付前必须运行项目验证入口；失败后使用 `python scripts/ao.py spec-driven resume --run-id <run_id>` 从失败节点继续。

## 禁止事项

- 不要绕过 workflow runner 自建运行目录。
- 不要让用户手写 `NNN-english-slug` feature 目录名。
- 不要跳过 product contract、stories、task graph 直接堆实现。
- 不要把普通 goal 脑补成产品级 spec；不改变产品事实的目标应走 `/ao-plan`。
- 不要把 PRD 降级成单个垂直切片。
- 不要自动切换到其他工作流，除非用户明确要求。
