# ao-small acceptance gate

读取 `small-scope.json`、`verification.json`、`review.md`、`acceptance-matrix.json`、`component-evidence.json` 和 `command-coverage.json`。

必须写入：

- `$AO_ARTIFACTS_DIR/small-acceptance-gate.json`

通过时 `result` 为 `PASS`。若发现多组件、新数据模型、隐私、安全或产品能力变化，必须失败并建议升级。
