# /ao-spec

从 PRD、规格或大功能启动产品级开发，执行 `spec-driven` E2E 工作流。

## 用法

```text
/ao-spec <项目名> -prd <PRD路径>
/ao-spec <项目名> -spec <规格路径>
/ao-spec <项目名> -plan <计划路径>
```

## 规则

- Skill：`.codex/skills/ao-spec/SKILL.md`
- `/ao-spec` 用于建立或改变产品事实：产品目标、用户、业务对象、状态、数据模型、隐私、安全、验收矩阵或多 story 能力。
- 从 0 开发时使用 `<项目名> -prd <路径>` 或 `<项目名> -spec <路径>`。
- 项目名对应已注册业务项目，例如 `app-a`；业务应用代码和规格都属于目标项目仓库。
- 业务项目运行前必须存在 confirmed `.agentic/stack-contract.json`；缺失时 prepare 阶段失败，先使用 `/ao-project -r <项目> <项目根目录>` 完成一步式项目接入并确认技术栈 profile。
- `-prd` 输入由 workflow runner 在隔离 worktree 内归档为 `specs/NNN-english-slug/source-prd.md`。
- `-spec` 输入由 workflow runner 在隔离 worktree 内归档为 `specs/NNN-english-slug/source-spec.md`。
- import 阶段只归档原始输入，不创建旧 `spec.md`、`plan.md`、`tasks.md` seed。
- `NNN-english-slug` 由 workflow runner 生成，不让用户手写。
- 读取本 command 文件后，继续读取 `.codex/skills/ao-spec/SKILL.md`。
- 再读取 `.agentic/workflow/spec-driven.md` 和 `.agentic/workflow/definitions/spec-driven.json`。
- 使用 `python scripts/ao.py spec-driven run --project-name <项目名> --prd <路径>`、`--project-name <项目名> --spec <路径>` 或 `--project-name <项目名> --plan-path <计划路径>` 启动完整运行。
- 使用 `-plan <计划路径>` 时仍必须提供项目名，映射到 `python scripts/ao.py spec-driven run --project-name <项目名> --plan-path <计划路径>`，不创建新的 feature 目录。
- 运行时必须读取目标项目 `.agentic/project.json` 中的 runtime adapter 和 `verify.command`；缺失或无效时失败。
- 运行时必须读取目标项目 `.agentic/stack-contract.json`，并把同一个 `stack_contract_ref` 传递到规格、计划、实现、验证、review 和 acceptance 产物。
- 不允许 fallback 到默认 Codex，不允许单次运行临时覆盖目标项目 runtime adapter。
- 必须读取命令输出 `run_dir` 中的 `agent-instructions.md`；控制面 run_dir 位于 `ai_docs/runs/<run_id>/`，业务项目 run_dir 位于目标项目 `runtime.runs_dir/<run_id>/`。
- workflow 必须完成 product state、production spec、implementation plan、task graph、实现循环、验证、独立审查、修复、release readiness、E2E proof、验收矩阵和报告。
- 产品事实以 `product-contract.json` 和 `stories.json` 为准；实施事实以 `tasks.json` 和 `task-graph.json` 为准；Markdown 只是人读投影。
- 进入实现前必须通过 product-state gate、production-spec gate 和 task-graph gate。
- 门禁失败时只允许修正对应契约产物，不允许继续写实现代码。
- 必须按 PRD 验收项完整执行，不能只完成单个切片后标记 passed。
- 交付物必须达到可进入生产发布流程的 release candidate；占位 UI、mock-only 路径、假集成、screenshot-only proof 不得通过。
- `review.md` 中 unresolved `FAIL` 必须阻断 release，不能写入通过的 acceptance matrix。
- 前端验收必须包含真实用户行为证据，不能只验证页面加载、截图存在或静态文本。
- 需要前端时必须产出并执行 `frontend-template-selection.json.frontend_implementation`；技术栈来源、源码根和 test/build/e2e 命令不明确时不得进入实现。
- 最终 `acceptance-matrix` 节点必须产出 `component-evidence.json` 和 `command-coverage.json`，缺失或 contract hash 不一致时不得通过。
- 最终 `run-report.md` 由 workflow run 写入；失败时输出 run_id、失败节点和 resume 命令。
- 失败后使用 `python scripts/ao.py spec-driven resume --run-id <run_id>` 查看失败节点和恢复指针。

## 分流

- 如果用户只给一个不改变产品事实的中等功能目标，改用 `/ao-plan`。
- 如果用户只给一个局部 bug、小配置、小 UI 或文案调整，改用 `/ao-small`。

## 示例

```text
/ao-spec agentic_factory -prd D:\workspace\prd\agentic_factory.md
/ao-spec agentic_factory -spec D:\workspace\prd\agentic_factory-spec.md
/ao-spec agentic_factory -plan D:\workspace\plans\agentic_factory-plan.md
```
