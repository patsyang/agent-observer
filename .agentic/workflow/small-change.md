# small-change E2E 工作流契约

## 适用场景

- 明确小修、局部 bug 修复。
- 小 UI、文案、配置、查询行为修正。
- 已有行为的局部修正，可用受影响测试或人工检查闭环。

## 定位边界

`/ao-small` 的核心是轻量 small-change 闭环，不是 LLM 生成 scope 契约，也不是短计划。

- 它不生成 `plan.md`、`tasks.json` 或 `task-graph.json`。
- 如果一个目标需要多个 task 才能描述清楚，必须失败并建议升级 `/ao-plan`。
- 如果目标新增或改变产品能力、数据模型、安全、数据处理与上报模式或长期验收，必须失败并建议升级 `/ao-spec`。

## 输入参数

必需二选一：

- `goal`
- `goal_path`

可选：

- `scope`

未提供 `scope` 时，`scope-resolve` 必须从目标文本、输入路径、仓库结构中解析出唯一 `project_scope`。存在多个候选时工作流失败，用户必须用 `--scope` 或 `--project` 重新启动。

## 运行阶段

```text
validate-input -> execute -> verify-and-fix -> independent-review -> report
```

## 必须产物

- `artifacts/scope-resolution.json`
- `artifacts/implementation.md`
- `artifacts/changed-files.txt`
- `artifacts/verification.md`
- `artifacts/review.md`
- `run.json`
- `run-report.md`

`acceptance-matrix.json` 如由 runner 写入，仅作为通用 run 报告元数据，不是 small adapter 节点必需产物。

## Project Stack Contract

业务项目运行 `/ao-small` 时必须先存在已确认的 `.agentic/stack-contract.json`。Runner 在 `prepare` 阶段读取该文件并把 `stack_contract_ref.contract_id`、`revision`、`hash` 写入 `input.json`、`run.json`、agent instructions 和节点环境变量。

实现、验证和 review 必须遵守同一个项目级技术栈契约；如当前小修需要偏离契约，工作流必须失败并说明需要用户重新确认 stack contract，不能在小修中临时选择其它语言、框架、包管理器、源码根或验证入口。

## 执行规则

- Bug 修复必须补回归测试。
- 验证失败进入 `verify-and-fix`。
- review 存在阻断问题时工作流失败。
- final/report 阶段必须基于真实 git diff 做确定性边界检查。
- 业务 small 不得修改控制面、managed infra、collector/telemetry 协议或数据库迁移；命中必须失败并建议升级 `/ao-plan` 或 `/ao-spec`。

## 失败处理

- scope 不唯一：失败并列出候选 scope。
- 超出小改动边界：失败并提示使用 `/ao-plan` 或 `/ao-spec`。
- required artifact 缺失：失败并保留 run 目录。
