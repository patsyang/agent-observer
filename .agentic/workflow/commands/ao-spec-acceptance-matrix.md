# ao-spec acceptance matrix

读取 product contract、stories、tasks、implementation-state、review、fix、release-readiness 和 e2e-proof。

必须写入 `$AO_ARTIFACTS_DIR/acceptance-matrix.json`。

每个 acceptance item 必须有 acceptance_id、story_id、result、behavior、evidence。PASS 必须有 command/API/DB/browser/package/privacy 等行为证据，不能只有截图或 Markdown 自述。

结构要求：

- 顶层 `result` 必须为 `PASS`。
- v2 结构使用 `acceptance_items` 数组；兼容旧结构时仍必须表达同等字段。
- 引用 review 时必须同时引用 `review-findings.json`、`review-gate.json` 和 `fix-state.json`。
- 若原始 review 存在 `FAIL` 或 `WARN`，矩阵中必须记录已关闭 finding id、关闭证据和 `unresolved_findings=[]`；不能只因为后续节点自称 PASS 就忽略原始 blocker。
- UI、Dashboard、browser、form、viewport、product-surface 相关验收必须包含 `browser` 或 `playwright` 类型证据，且要说明用户动作、导航/提交方式、反馈状态和持久化断言；command/API 证据不能单独支撑 UI 验收 PASS。
