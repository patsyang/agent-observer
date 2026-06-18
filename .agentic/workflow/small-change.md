# small-change E2E 工作流契约

## 适用场景

- 单一 bug 修复。
- 单一配置、文案、样式、脚本细节调整。
- 单一低风险控制面小改动。
- 能解析到唯一 `project_scope` 和单一 `write_set` 的小目标。

## 定位边界

`/ao-small` 的核心是小修准入门禁，不是短计划。

- 它可以从一句局部问题生成 `repro.md`、`small-scope.json` 和 `verification.json`。
- 它不生成 `plan.md`、`tasks.json` 或 `task-graph.json`。
- 如果一个目标需要多个 task 才能描述清楚，必须失败并建议升级 `/ao-plan`。
- 如果目标新增或改变产品能力、数据模型、隐私、安全或长期验收，必须失败并建议升级 `/ao-spec`。

## 输入参数

必需二选一：

- `goal`
- `goal_path`

可选：

- `scope`

未提供 `scope` 时，`scope-resolve` 必须从目标文本、输入路径、仓库结构中解析出唯一 `project_scope`。存在多个候选时工作流失败，用户必须用 `--scope` 或 `--project` 重新启动。

## 运行阶段

```text
scope-resolve -> create-worktree -> small-scope-gate -> repro-or-signal -> execute -> verify-and-fix -> independent-review -> small-acceptance-gate -> merge-back -> report
```

## 必须产物

- `artifacts/scope-resolution.json`
- `artifacts/small-scope.json`
- `artifacts/small-scope.md`
- `artifacts/repro.md`
- `artifacts/implementation.md`
- `artifacts/changed-files.txt`
- `artifacts/verification.json`
- `artifacts/verification.md`
- `artifacts/review.md`
- `artifacts/acceptance-matrix.json`
- `artifacts/component-evidence.json`
- `artifacts/command-coverage.json`
- `artifacts/small-acceptance-gate.json`
- `acceptance-matrix.json`
- `run.json`
- `run-report.md`

## Project Stack Contract

业务项目运行 `/ao-small` 时必须先存在已确认的 `.agentic/stack-contract.json`。Runner 在 `prepare` 阶段读取该文件并把 `stack_contract_ref.contract_id`、`revision`、`hash` 写入 `input.json`、`run.json`、agent instructions 和节点环境变量。

所有实现、验证、review 和验收产物必须遵守同一个项目级技术栈契约；如当前小修需要偏离契约，工作流必须失败并说明需要用户重新确认 stack contract，不能在小修中临时选择其它语言、框架、包管理器、源码根或验证入口。

`independent-review` 节点必须额外写出：

- `acceptance-matrix.json`：每个 PASS 项必须包含 `stack_contract_ref`、行为证据和存在的证据路径。
- `component-evidence.json`：列出受影响组件、源码根、遵守的语言/框架/包管理器、证据路径。
- `command-coverage.json`：列出本次应运行命令、实际命令、结果和跳过原因；缺少原因的跳过不允许通过。

## Small Scope

`small-scope.json` 必须包含：

- `goal`
- `change_type`
- `observable_signal`
- `allowed_files`
- `forbidden_areas`
- `requires_repro`
- `verification_commands`
- `upgrade_triggers`
- `max_components`
- `data_model_change_allowed`
- `privacy_change_allowed`

`max_components` 必须小于等于 1。`data_model_change_allowed` 和 `privacy_change_allowed` 必须为 `false`。

## 执行规则

- 必须创建隔离 worktree。
- 主工作区存在未提交变更时不得启动。
- `write_set` 必须只有一个小边界。
- 变更文件必须落在 `write_set` 内。
- Bug 修复必须补回归测试。
- 验证失败进入 `verify-and-fix`。
- review 存在阻断问题时工作流失败。
- acceptance matrix 不允许 `PENDING`、`SKIPPED` 或缺证据项。

## 失败处理

- scope 不唯一：失败并列出候选 scope。
- 超出小改动边界：失败并提示使用 `/ao-plan` 或 `/ao-spec`。
- required artifact 缺失：失败并保留 run 目录。
- worktree 合并前主工作区漂移：失败并保留 worktree。
