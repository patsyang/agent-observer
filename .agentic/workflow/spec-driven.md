# spec-driven 生产级 E2E 工作流契约

## 适用场景

- 新的大功能或从 0 启动的业务项目。
- 高风险功能。
- 涉及隐私、数据模型、日志查询、诊断机制、新 Agent 接入。
- 需要长期复用、可直接进入生产发布流程的产品能力。

## 输入参数

从 PRD 或 Spec 建档时必需：

- `project_name`
- `prd` 或 `spec`

从既有计划继续时必需：

- `project_name`
- `plan_path`

`project_name` 对应已注册业务项目。`prd` 和源 `spec` 作为 workflow input 传入，
不得在命令层提前写入目标项目主工作区；runner 必须先创建隔离 worktree，再由
`import-input` 系统节点把文档归档到 worktree 的 `specs/<feature>/`，只写入
`source-prd.md` 或 `source-spec.md`，不创建旧 `spec.md`、`plan.md`、`tasks.md`
seed。既有计划也必须绑定项目名，以便 workflow runner 读取目标项目的 runtime
adapter、verify command 和工作区。

## 生产级完成定义

`/ao-spec` 的目标不是 demo，也不是“截图存在”。完成必须表示交付物可以进入项目正常生产发布流程：

- 没有已知功能阻断。
- 没有未验证验收项被标记 `PASS`。
- 没有占位 UI、mock-only 路径、假集成或 screenshot-only proof。
- 主要用户角色能完成主流程，并看到成功、失败、禁用、恢复等状态反馈。
- 前端、后端、数据、隐私、安全、打包、运行和回滚关注点在适用时都有证据。
- Review 中的 `FAIL` 必须阻断 release；`WARN` 必须修复或给出非阻断理由。

## 运行阶段

```text
import-input
  -> inspect-project
  -> generate-product-state
  -> validate-product-state
  -> generate-production-spec
  -> gate-production-spec
  -> generate-implementation-plan
  -> gate-implementation-plan
  -> frontend-template-resolution
  -> gate-frontend-template
  -> implement-story-loop
  -> stabilize-state
  -> full-verify
  -> independent-review
  -> review-gate
  -> fix-warnings-loop
  -> release-readiness-gate
  -> final-e2e-proof
  -> acceptance-matrix
  -> production-report
  -> distill
```

## 必须产物

运行目录必须包含：

- `artifacts/imported-source.json`
- `artifacts/product-prd.md`
- `artifacts/product-contract.json`
- `artifacts/production-spec.md`
- `artifacts/api-contract.json`
- `artifacts/data-contract.json`
- `artifacts/stories.json`
- `artifacts/tasks.json`
- `artifacts/task-graph.json`
- `artifacts/implementation-state.json`
- `artifacts/progress.md`
- `artifacts/review.md`
- `artifacts/fix.md`
- `artifacts/release-readiness.md`
- `artifacts/e2e-proof.md`
- `artifacts/acceptance-matrix.json`
- `acceptance-matrix.json`
- `run.json`
- `run-report.md`

## Spec Production Gate

`production-spec.md` 必须包含：

- Product Outcome
- User Roles and Production Workflows
- Domain Objects and States
- Frontend Product Surface
- Backend and Data Contracts
- Error, Empty, Partial and Recovery States
- Security and Privacy Boundaries
- Operational Concerns
- Release Gates
- Acceptance Matrix Draft

以下情况必须失败：

- 只描述模块，不描述用户流程。
- 只描述数据展示，不描述用户动作。
- 缺失失败、空态、部分数据、恢复路径。
- 敏感数据场景缺失隐私和安全门禁。
- 可运行产品缺失部署、打包、运维或回滚关注点。
- 前端被定义为通用卡片/列表，缺少领域操作。
- 用截图替代用户行为断言。

## Story Production Gate

`product-contract.json` 和 `stories.json` 是产品事实来源。每个 story 必须包含：

- `id`
- `title`
- `user_value`
- `priority`
- `depends_on`
- `acceptance_ids`
- `acceptance_criteria`
- `technical_notes`
- `risk`
- `required_evidence`
- `passes`

拒绝以下 story：

- 只有技术层描述，例如“创建后端”或“创建前端”。
- 不能通过用户行为或系统契约证据演示。
- 没有验收标准。
- 没有验证命令或证据要求。
- 没有 release risk。
- 一个 story 混入多个互不相关的业务流程。

## Tech Stack Decision Gate

`/ao-spec` 不使用全局固定技术栈，也不允许在单次运行中临时猜测技术栈。业务项目必须先存在已确认的 `.agentic/stack-contract.json`，Runner 在 `prepare` 阶段读取该文件并把 `stack_contract_ref.contract_id`、`revision`、`hash` 写入 `input.json`、`run.json`、agent instructions 和每个节点环境变量。

技术栈基准必须来自项目级 stack contract：

1. 项目注册或项目治理命令中用户确认的 stack contract。
2. 目标项目已有实现、`AGENTS.md`、README、package files、构建脚本和验证命令。
3. PRD/Spec 中明确要求且已经写入 stack contract 的约束。

`inspect-project` 只负责发现现有实现和对照 stack contract；不得把发现结果当作新的选择覆盖 contract。`generate-production-spec` 必须把 contract 中的组件、源码根、命令和前端实现方式写入产品规格。`frontend-template-resolution` 必须从 contract 中选择前端实现模式和模板；如果 contract 未声明可用前端组件但产品需要前端，必须失败并要求先更新项目 stack contract。

技术栈选择不得只存在于 Markdown rationale、节点日志或 agent 自述中。关键产物必须写入同一个 `stack_contract_ref`；缺少可追溯 `stack_source`、源码根、测试命令、build 命令、e2e 命令、组件证据或 contract hash 时，门禁必须失败。

最终 `acceptance-matrix` 节点必须额外写出：

- `component-evidence.json`：每个实现组件对应的 contract component、源码根、语言/框架/包管理器、变更路径和证据。
- `command-coverage.json`：contract 中要求的验证命令、PRD 衍生验证命令、实际运行结果、证据路径和跳过理由。
- `acceptance-matrix.json`：每个 PASS 项必须包含 `stack_contract_ref`，且 evidence path 必须存在。

## Implement Loop

实现阶段必须按 story 循环执行：

```text
select-next-story
  -> build-story-work-packet
  -> run-agent
  -> run-targeted-verification
  -> update-story-state
  -> checkpoint
  -> repeat
```

选择规则：

- `passes == false`
- 依赖 story 已通过
- priority 最高

每轮 agent 只实现一个 story。每个 story 在标记 `PASS` 前必须通过受影响验证、写入证据路径，并且不得留下本 story 引入的失败。

涉及 UI/Dashboard/browser/form/viewport 的 story 必须加载前端实现契约：

- `independent_frontend`：必须在声明的前端源码根中实现，接入 test/build/e2e 命令，不得只用后端 handler 拼 HTML 代替。
- `existing_frontend_adaptation`：必须复用现有前端入口、路由、组件和测试约定。
- `server_rendered_equivalent`：只允许在已有 server-rendered 前端或明确产品约束下使用，并必须提供同等交互、状态、响应式、可访问性和 browser/e2e 证据。

## Independent Review

实现循环结束后必须执行独立 review。Review 只读，不修改代码或状态。Review 必须对每个 `passes: true` 的 story 给出：

- `OK`：有明确证据满足。
- `WARN`：可交付但需要改进、补覆盖或修一致性。
- `FAIL`：story 完成事实不成立或 release 被阻断。

Review 必须检查：

- story acceptance criteria
- git diff 或 changed files
- 测试和验证日志
- 产品规格
- 前端产品表面
- 安全和隐私边界
- 项目既有约定
- 跨 story 命名、类型、错误处理和日志一致性

## Fix Routing

- `WARN` 和可执行跨 story 发现进入 `fix-loop`。
- `FAIL` 是 release blocker，不得静默降级。
- `FAIL` 只能回到 implement-loop 修正、标记 `BLOCKED` 等待产品/架构决策，或在 release readiness 中阻断。
- Review 存在 unresolved `FAIL` 时，不得写入通过的 acceptance matrix。

## Production Frontend Gate

前端门禁是生产发布门禁，不是最低 UI 标准。必须证明真实用户能完成预期任务。

必须满足：

- 需要前端且目标项目没有现有前端时，默认产出独立前端实现契约和源码根；server-rendered 只能作为显式产品约束下的例外。
- 主流程能从主产品界面发起并完成。
- 核心对象有有意义的 label、状态、层级、详情、操作和反馈。
- 重要操作前可查看必要详情。
- 操作具备 success、failure、loading、disabled、recovery 状态。
- 需要比较多个对象时，必须有过滤、排序、分组或 drill-down。
- 空态说明原因和下一步。
- 错误态提供恢复动作，且不泄露原始技术输出。
- 响应式布局经过验证。
- Playwright 覆盖至少一个完整用户路径，不只验证页面加载。

以下情况立即阻断 release：

- UI 是占位、静态 mock 或装饰壳。
- UI 只是镜像 API 字段，没有领域工作流。
- UI 用硬编码成功数据伪装集成。
- 主流程不能通过 UI 完成。
- 关键状态未实现。
- 文本或控件在目标 viewport 重叠。
- E2E 只检查截图存在或页面加载。

`frontend-template-selection.json` 必须包含：

- `frontend_required`
- `template_id`
- `required_views`
- `required_components`
- `required_states`
- `required_interactions`
- `api_contracts`
- `e2e_scenarios`
- `visual_quality_rubric`
- `frontend_implementation.mode`
- `frontend_implementation.stack_source`
- `frontend_implementation.source_root`
- `frontend_implementation.test_commands`
- `frontend_implementation.build_commands`（独立前端或既有前端适配时必需）
- `frontend_implementation.e2e_commands`

## E2E Proof Gate

E2E proof 必须证明行为，不证明存在。每条 E2E 证据至少包含：

- setup command
- app/server startup evidence
- user action sequence
- backend 或 persistence assertion
- UI assertion after state change
- screenshot 或 trace
- cleanup evidence

拒绝：

- screenshot-only proof
- page-load-only proof
- 只断言静态文本的测试
- 绕过 UI 证明主流程
- 不存在的 evidence path
- 缺少 exit code 的验证日志

## Acceptance Matrix Gate

`acceptance-matrix.json` 是 release artifact。所有 `PASS` 必须包含：

- `acceptance_id`
- `story_id`
- `result`
- `evidence`
- evidence 中的 command、exit code、path 或 Playwright assertions

门禁必须校验：

- PRD 验收项全部出现且不重复。
- 顶层 `result` 为 `PASS`，v2 矩阵使用 `acceptance_items`。
- evidence path 存在。
- 失败或跳过的测试不能支撑 `PASS`。
- 前端验收有用户行为证据；UI/Dashboard/browser/form/viewport 相关验收必须包含 `browser` 或 `playwright` 证据，以及用户动作、反馈和持久化断言。
- 后端验收有 API 或持久化证据。
- 隐私/安全验收有扫描或策略证据。
- 原始 review 的 `FAIL/WARN` 必须由 `fix-state.json.resolved_findings` 逐项关闭，且每项有 exit code 0 的验证证据路径。
- unresolved `FAIL/WARN` 阻断 release。
- `acceptance-matrix` 节点写出产物后立即执行语义 gate；失败必须停在该节点，不能等 `production-report` 或 `distill` 后才暴露。

## Resume

失败时 `run.json` 必须写入：

- `status=FAILED`
- `failed_node`
- `error`
- `resume_command`

状态查看入口：

```text
python scripts/ao.py spec-driven resume --run-id <run_id>
```

恢复必须读取 `run.json` 中的节点状态，复用已有 worktree，跳过已 `PASSED` 节点，
从失败或未完成节点继续执行。恢复不得重复已 `PASS` 的 story，不得把 unresolved
`FAIL` 标记为通过。

## Runtime Adapter

`/ao-spec` 必须使用目标项目 `.agentic/project.json` 中声明的 runtime adapter。
该配置在项目初始化或注册后贯穿项目生命周期，不能在单次运行中静默替换。

必须满足：

- `adapter.id` 存在且为已注册 runtime adapter。
- `adapter.command` 是非空命令数组。
- `verify.command` 是非空命令数组。
- `project status` 能展示 adapter、command、validated_at、version 和 verify command。
- 每个 E2E 节点通过 runtime adapter 的 node-level 接口执行，由 adapter 负责封装 CLI 的非交互命令、工作目录、`--output-last-message` 和节点 required artifacts。

以下情况必须失败：

- 目标项目缺失 `.agentic/project.json`。
- `adapter.command` 为空或不可解析。
- 运行时没有项目 adapter 却进入 `spec-driven` 节点。
- 把 `adapter.command` 直接当作节点 provider 命令执行。
- fallback 到默认 Codex。
- 单次运行临时覆盖目标项目 runtime adapter。

## 失败处理

- Spec production gate 失败：只修正规格产物。
- Product state gate 失败：只修正 `product-contract.json`、`stories.json` 和 `product-prd.md`。
- Story production gate 失败：只修正 story map 和任务图。
- Implement loop 失败：保留当前 story 状态和证据，写入失败节点。
- Review 发现 `FAIL`：阻断 release，不写通过的 acceptance matrix。
- E2E proof 缺失或只有截图：失败。
- Acceptance evidence 缺失或路径不存在：失败。
- worktree 合并前主工作区漂移：失败并保留 worktree。
