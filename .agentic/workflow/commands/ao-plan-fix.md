# ao-plan fix

读取 `review.md`、`review-gate.json` 和当前 diff。只修复 review 中的可行动问题。

必须写入：

- `$AO_ARTIFACTS_DIR/fix.md`
- `$AO_ARTIFACTS_DIR/acceptance-matrix.json`
- `$AO_ARTIFACTS_DIR/component-evidence.json`
- `$AO_ARTIFACTS_DIR/command-coverage.json`

不得引入计划外功能。所有 PASS 验收必须有行为证据和存在的证据路径。
