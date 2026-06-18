# ao-spec stabilize state

读取 `stories.json`、`implementation-state.json`、`progress.md`。检查 story 状态和实现状态一致，清理 stale error，记录最终 story 统计。

必须写入 `$AO_ARTIFACTS_DIR/stabilize-state.json`。

`stabilize-state.json` 必须包含顶层 `"status"`。一致且可继续时写 `"STABLE"`；发现 blocked、failed、inconsistent 或 stale error 无法清理时写非通过状态并列出原因。

稳定化要求借鉴 sw-factory archon-ralph：

- 不以模型输出文本中的 `COMPLETE` 作为唯一完成依据。
- 必须检查 `stories.json` 所有 story 均 `passes=true`。
- 必须检查 `implementation-state.json`、`stories.json`、`progress.md` 的 story 统计一致。
- 若目标 worktree 还有未完成写入或状态不一致，写非通过状态，不得进入 review。
