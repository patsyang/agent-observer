# ao-plan generate plan

读取 `slice-brief.md`、目标项目 stack contract、已有 spec/plan 输入和真实代码结构。只做计划，不写实现代码。

必须写入：

- `$AO_ARTIFACTS_DIR/plan.md`
- `$AO_ARTIFACTS_DIR/tasks.json`
- `$AO_ARTIFACTS_DIR/task-graph.json`

每个 task 必须绑定 acceptance、component、expected files、required tests、verification commands、done signal、dependencies、risk 和 size。size 只允许 S 或 M。

`plan.md` 是人读投影；`tasks.json` 和 `task-graph.json` 是执行事实源。
