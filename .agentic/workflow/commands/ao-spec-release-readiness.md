# ao-spec release readiness

读取所有 gate、review、fix、frontend、package、real-data、e2e 和 acceptance 证据。只能根据证据判定，不接受自述通过。

必须写入：

- `$AO_ARTIFACTS_DIR/release-readiness.json`
- `$AO_ARTIFACTS_DIR/release-readiness.md`

任一 required gate 失败、证据缺失、review FAIL 未关闭或路径指向旧 workspace 时，结果必须为 FAIL。

review 关闭规则：

- `review-gate.json` 为 FAIL 时，不得直接放行。
- 只有 `fix-state.json.status == "NO_ACTIONABLE_WARNINGS"`，且 `unresolved_findings` 为空，且 `resolved_findings` 覆盖全部 review FAIL/WARN finding id，并且每个 resolved finding 有验证命令、退出码 0 和证据路径时，才允许将旧 review FAIL 视为已关闭。
- 对前端 finding，resolved evidence 必须包含真实 UI 行为验证；没有浏览器/交互/断言证据时仍视为未关闭。
- 若关闭证据不足，`release-readiness.json.result` 必须为 `FAIL`，并列出缺失证据。
- 判断 closure 时必须以 `review-findings.json.findings[*].id` 为源头，逐个核对 `fix-state.json.resolved_findings[*].id`、验证命令、退出码和证据路径；不得只检查 `fix-state.json.status`。
- 若使用 Playwright 之外的 browser-equivalent proof，必须在风险中写明限制，并覆盖 rendered UI action、redirect/recovery、persistence 和 responsive evidence。
