# ao-spec validate product state

读取 `product-prd.md`、`product-contract.json`、`stories.json`。检查 PRD 验收覆盖、story 依赖、story 尺寸、open questions 和占位文本。

必须写入：

- `$AO_ARTIFACTS_DIR/product-state-gate.json`
- `$AO_ARTIFACTS_DIR/product-state-gate.md`

如果发现未覆盖验收、模板残留、空 story、不可执行 story 或 unresolved open questions，gate 结果必须为 FAIL，不得继续声称可实现。

