# ao-plan contract gate

读取 `slice-brief.md`、`plan.md`、`tasks.json` 和 `task-graph.json`。不写实现代码。

必须写入：

- `$AO_ARTIFACTS_DIR/plan-gate.json`
- `$AO_ARTIFACTS_DIR/plan-gate.md`

gate 必须检查：

- plan 没有 BLOCKED。
- task 全部有 acceptance、component、verification command 和 done signal。
- task graph 无环。
- 未重定义产品事实。
- `stack_contract_ref` 一致。

通过时 `plan-gate.json.result` 必须为 `PASS`。
