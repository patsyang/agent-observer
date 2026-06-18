# ao-spec fix warnings

读取 `review-findings.json`、`review.md`、`review-gate.json` 和相关实现证据。逐项修复 actionable `FAIL` 与 `WARN`，不得掩盖、删除或降级 finding。

必须写入：

- `$AO_ARTIFACTS_DIR/fix.md`
- `$AO_ARTIFACTS_DIR/fix-state.json`

执行要求：

- 对每个 actionable `FAIL`/`WARN` 写明 finding id、修改文件、验证命令、退出码和证据路径。
- 若 finding 指向前端用户行为，必须补真实 UI 行为验证；只改 HTML 字符串或只跑 API 单测不能关闭前端 finding。
- 若 finding 指向隐私、打包、服务端持久化或客户端采集，必须补对应行为证据，不能只更新文档。
- 修复后必须运行相关验证并记录证据。
- 所有 actionable findings 关闭后，`fix-state.json.status` 写 `NO_ACTIONABLE_WARNINGS`，同时写 `resolved_findings`、`unresolved_findings` 和 `verification`。
- 仍有未关闭 finding 时，`fix-state.json.status` 必须写 `ACTIONABLE_FINDINGS_REMAIN`，并列出原因。
- 最终回复只有在 `unresolved_findings` 为空时才允许包含 `NO_ACTIONABLE_WARNINGS`。
