# ao-plan acceptance gate

读取 `acceptance-matrix.json`、`component-evidence.json` 和 `command-coverage.json`。

必须写入：

- `$AO_ARTIFACTS_DIR/acceptance-gate.json`

所有验收、组件和命令覆盖都通过时 `result` 为 `PASS`。
