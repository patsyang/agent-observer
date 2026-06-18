# ao-small execute

读取 `small-scope.json`、`repro.md` 和目标项目规则。只做最小修改。

必须写入：

- `$AO_ARTIFACTS_DIR/implementation.md`
- `$AO_ARTIFACTS_DIR/changed-files.txt`

修改必须落在 `small-scope.json.allowed_files` 或明确允许的单一组件内。
