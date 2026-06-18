# ao-small verify

读取 `small-scope.json`、`repro.md`、`implementation.md` 和目标项目 verify command。运行定向验证或说明不可运行原因。

必须写入：

- `$AO_ARTIFACTS_DIR/verification.json`
- `$AO_ARTIFACTS_DIR/verification.md`

`verification.json` 必须包含 commands、expected_results 和 regression_tests。
