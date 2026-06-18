# ao-plan execute task loop

读取 `slice-brief.md`、`plan.md`、`tasks.json`、`task-graph.json` 和 gate 产物。按依赖顺序实现任务。

必须写入：

- `$AO_ARTIFACTS_DIR/implementation.md`
- `$AO_ARTIFACTS_DIR/changed-files.txt`
- `$AO_ARTIFACTS_DIR/verification.md`

每个 task 只能修改自己的组件和 write boundary。需要改变产品事实或 stack contract 时停止并报告，不要自行扩展。
