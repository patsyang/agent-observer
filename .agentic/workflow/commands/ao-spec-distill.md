# ao-spec distill

读取 implementation、verification、review、fix、production-report。提取可复用经验，不直接修改 AGENTS 或 reference。

必须写入：

- `$AO_ARTIFACTS_DIR/distill-result.json`
- `$AO_ARTIFACTS_DIR/distill-result.md`

Markdown 必须包含“决策与发现”“踩坑记录”“规范改进建议”“后续任务注意”。无内容时写“无”。

