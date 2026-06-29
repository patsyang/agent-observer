# plan-execute E2E 工作流契约

## 适用场景

- 普通功能开发。
- 用户只给一个明确 goal，需要 workflow 自动生成执行计划并开发。
- 用户已有 goal、spec 或标准 plan，希望完成一个开发闭环。
- 功能需要后端、前端、collector、测试或 e2e 同步推进，但不改变产品事实。

## 定位边界

`/ao-plan` 不是小号 `/ao-spec`。

- 它可以从自然语言 `goal` 生成 `slice-brief.md`、`plan.md`、`tasks.json` 和 `task-graph.json`。
- 它不能生成或改变产品级 `product-contract.json`、`stories.json` 或长期 acceptance matrix。
- 如果目标需要定义或改变产品目标、用户角色、业务对象、数据模型、安全、数据处理与上报模式或长期验收矩阵，工作流必须失败并建议升级 `/ao-spec`。
- 如果目标只有一个局部 bug、配置、文案或 UI 小调整，工作流可以失败并建议降级 `/ao-small`。

## 输入参数

必需四选一：

- `goal`
- `goal_path`
- `spec_path`
- `plan_path`

可选：

- `scope`

`plan_path` 是高级入口，不是免检通道；必须通过 plan contract gate 和 task graph gate。

目标文本命中多个项目时必须失败。用户需要使用 `--scope` 或 `--project` 指定边界。路径输入优先从路径解析 scope。

## 运行阶段

```text
scope-resolve -> create-worktree -> resolve-slice-brief -> generate-plan -> plan-contract-gate -> task-graph-gate -> execute-task-loop -> integration-verify -> independent-review -> review-gate -> fix-loop -> acceptance-gate -> merge-back -> report
```

## 必须产物

- `artifacts/scope-resolution.json`
- `artifacts/slice-brief.md`
- `artifacts/plan.md`
- `artifacts/tasks.json`
- `artifacts/task-graph.json`
- `artifacts/plan-gate.json`
- `artifacts/task-graph-gate.json`
- `artifacts/implementation.md`
- `artifacts/task-execution-state.json`
- `artifacts/changed-files.txt`
- `artifacts/verification.md`
- `artifacts/integration-verify.json`
- `artifacts/review.md`
- `artifacts/review-gate.json`
- `artifacts/fix.md`
- `artifacts/acceptance-matrix.json`
- `artifacts/component-evidence.json`
- `artifacts/command-coverage.json`
- `acceptance-matrix.json`
- `run.json`
- `run-report.md`

## Project Stack Contract

业务项目运行 `/ao-plan` 时必须先存在已确认的 `.agentic/stack-contract.json`。Runner 在 `prepare` 阶段读取该文件并把 `stack_contract_ref.contract_id`、`revision`、`hash` 写入 `input.json`、`run.json`、agent instructions 和节点环境变量。

`generate-plan` 节点不得重新发明技术栈。`plan.md`、`tasks.json` 和 `task-graph.json` 必须引用同一个 `stack_contract_ref`，并把每个 task 绑定到契约中的组件、源码根、验收项、验证命令和 done signal。无法映射到契约组件的 task 必须阻断在计划阶段，不能留给实现节点自行判断。

新增前端、后端、collector、CLI、测试或打包内容时，必须落在 stack contract 声明的根目录、语言、框架、包管理器和命令入口内；需要新增组件或更换栈时必须失败并要求更新项目 stack contract。

`fix-loop` 必须额外写出：

- `acceptance-matrix.json`：每个 PASS 项必须包含 `stack_contract_ref`、行为证据和存在的证据路径。
- `component-evidence.json`：列出每个受影响组件、任务映射、源码根、技术栈遵守证据。
- `command-coverage.json`：列出全量或受影响验证命令、实际执行结果、证据路径和跳过理由。

## Task Graph

每个 task 必须包含：

- `id`
- `title`
- `observable_outcome`
- `acceptance_refs`
- `component_refs`
- `files_expected`
- `tests_required`
- `verification_commands`
- `done_signal`
- `dependencies`
- `risk`
- `size`

每个 task 只能修改自己的 write boundary。越界修改直接失败。`size` 只允许 `S` 或 `M`；出现 `L` 或 `XL` 必须继续拆分。

## 执行规则

- 必须创建隔离 worktree。
- 一次 run 只创建一个 worktree；resume 同一 run 时必须复用原 worktree。
- 主工作区存在未提交变更时不得启动。隔离 worktree 基于 `HEAD` 创建，不会携带未提交改动；显式 `--allow-dirty-source` 只允许记录 dirty evidence 后继续。
- `plan-contract-gate` 和 `task-graph-gate` 通过后才能进入实现。
- 所有 task 必须绑定 acceptance、component、verification command 和 done signal。
- 集成后必须运行完整验证。
- review 阻断问题进入 `fix-loop`。
- `fix-loop` 最多 3 轮。
- acceptance matrix 全部 PASS 后才能 merge-back。

## 失败处理

- scope 不唯一：失败并列出候选 scope。
- plan 缺少 tasks 或 task graph：失败。
- task 缺少验收、组件、可观察结果（observable_outcome）、验证命令或 done signal：失败。
- task graph 存在循环依赖：失败。
- 实现越界修改：失败。
- required artifact 缺失：失败。
- 验证失败且修复轮次耗尽：失败。
- worktree 合并前主工作区漂移：失败并保留 worktree。
- 已完成 run 的 worktree/branch 使用 `workflow cleanup --merged` 清理；旧 worktree 不得作为启动新 run 的前置阻塞条件。
