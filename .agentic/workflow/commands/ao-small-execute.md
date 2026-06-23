# ao-small execute

读取 workflow input、`scope-resolution.json`、目标项目规则和当前 diff。只做最小修改。

必须写入：

- `$AO_ARTIFACTS_DIR/implementation.md`
- `$AO_ARTIFACTS_DIR/changed-files.txt`

`implementation.md` 必须说明实际修改、行为影响和回归测试策略。`changed-files.txt` 必须列出本节点触达的真实路径，每行一个。
