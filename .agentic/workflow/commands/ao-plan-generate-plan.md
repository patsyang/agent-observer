# ao-plan generate plan

读取 `slice-brief.md`、目标项目 stack contract、已有 spec/plan 输入和真实代码结构。只做计划，不写实现代码。

必须写入：

- `$AO_ARTIFACTS_DIR/plan.md`
- `$AO_ARTIFACTS_DIR/tasks.json`
- `$AO_ARTIFACTS_DIR/task-graph.json`

每个 task 必须绑定 acceptance、component、observable_outcome、expected files、required tests、verification commands、done signal、dependencies、risk 和 size。size 只允许 S 或 M。

`plan.md` 是人读投影；`tasks.json` 和 `task-graph.json` 是执行事实源。

`task-graph.json` 必须使用以下字段名：顶层 `tasks`（任务数组，不是 `nodes`）、`edges`（依赖边数组，每项含 `from`/`to`）、`execution_order`、`global_write_set`、`forbidden_write_set`。`tasks` 中每个 task 必须含 `id`、`verification_commands`、`done_signal`、`component_refs`、`acceptance_refs`。
