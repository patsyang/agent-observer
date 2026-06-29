# ao-plan execute task loop

读取 `slice-brief.md`、`plan.md`、`tasks.json`、`task-graph.json` 和 gate 产物。按依赖顺序实现任务。

必须写入：

- `$AO_ARTIFACTS_DIR/implementation.md`
- `$AO_ARTIFACTS_DIR/changed-files.txt`
- `$AO_ARTIFACTS_DIR/verification.md`

每个 task 只能修改自己的组件和 write boundary。需要改变产品事实或 stack contract 时停止并报告，不要自行扩展。

必须写入 `$AO_ARTIFACTS_DIR/task-execution-state.json` 作为 task completion 权威产物：
- `schema` 必须为 `agentic-task-execution-state/v1`。
- `tasks` 必须覆盖 `tasks.json` / `task-graph.json` 中所有 task。
- 每个 task 必须包含 `id` 和 `status`，status 只允许 `pending`、`running`、`completed`、`done`、`passed`、`failed`、`blocked`。
- `completed`、`done`、`passed` 的 task 必须包含非空 `evidence` 或 `verification_results`，引用验证命令、产物路径或可观察行为证据。
  - 字段名只允许 `evidence` 或 `verification_results`；不要使用 `verification`、`verifications`、`proof`、`results` 等其他变体名。
  - `evidence` / `verification_results` 必须是非空 list，每项是包含 `command`、`result`、`summary` 等字段的对象。
- `failed`、`blocked` 的 task 必须包含 `blocked_reason` 或 `failure_summary`。
