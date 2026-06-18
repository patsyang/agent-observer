# ao-spec review gate

读取 `review-findings.json`。统计 OK、WARN、FAIL，判断是否存在 release blocker。

必须写入 `$AO_ARTIFACTS_DIR/review-gate.json`。

存在 FAIL 时结果为 FAIL。存在 WARN 时进入 fix loop。无 WARN/FAIL 时写入 `NO_ACTIONABLE_WARNINGS` 信号。

