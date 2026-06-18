# ao-plan integration verify

读取 `implementation.md`、`changed-files.txt`、`verification.md`、目标项目 verify command 和 stack contract。运行或汇总本切片需要的集成验证。

必须写入：

- `$AO_ARTIFACTS_DIR/integration-verify.json`
- `$AO_ARTIFACTS_DIR/integration-verify.md`

通过时 `integration-verify.json.result` 必须为 `PASS`，并包含命令、退出码和证据路径。
