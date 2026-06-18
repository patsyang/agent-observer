# ao-plan task graph gate

读取 `tasks.json` 和 `task-graph.json`。不写实现代码。

必须写入：

- `$AO_ARTIFACTS_DIR/task-graph-gate.json`

gate 必须检查 task id 唯一、依赖存在且无环、任务大小为 S/M、每个 task 有验收、组件、验证命令和 done signal。通过时 `result` 为 `PASS`。
