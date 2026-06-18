# ao-spec gate implementation plan

读取 `plan.md`、`tasks.md`、`tasks.json`、`task-graph.json`、`stories.json`、`product-contract.json`。

必须写入：

- `$AO_ARTIFACTS_DIR/plan-gate.json`
- `$AO_ARTIFACTS_DIR/plan-gate.md`

检查任务覆盖全部 story 和 acceptance，检查每个 task 有验证命令和 done signal，检查依赖图无环，检查 Markdown 和 JSON 一致，拒绝模板残留。

