# ao-spec full verify

读取 `tasks.json`、`implementation-state.json` 和目标项目 verify command。运行全量验证或汇总已运行证据，区分 PASS、EXISTING_FAIL、INTRODUCED_FAIL、ENV_FAIL。

必须写入：

- `$AO_ARTIFACTS_DIR/full-verify.json`
- `$AO_ARTIFACTS_DIR/full-verify.md`

本 run 引入的失败必须标 FAIL。

