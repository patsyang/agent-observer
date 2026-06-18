# ao-plan review gate

读取 `review.md`。判断是否可以进入 fix loop 或 acceptance。

必须写入：

- `$AO_ARTIFACTS_DIR/review-gate.json`

存在 unresolved FAIL 时 `result` 不得为 `PASS`。
