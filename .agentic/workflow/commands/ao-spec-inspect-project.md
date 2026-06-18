# ao-spec inspect project

只读检查目标 worktree。读取 `AGENTS.md`、项目配置、包管理文件、测试入口、前端入口、后端入口和打包入口。

必须写入 `$AO_ARTIFACTS_DIR/project-inspection.json` 和 `$AO_ARTIFACTS_DIR/project-inspection.md`。

`project-inspection.json` 必须包含 `tech_stack`、`commands`、`frontend`、`backend`、`packaging`、`similar_files`、`rules_files`。无法识别时写空数组或明确的 `exists=false`，不得省略字段。

