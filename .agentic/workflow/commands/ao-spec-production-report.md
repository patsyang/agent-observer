# ao-spec production report

读取 run state、acceptance matrix、release-readiness、e2e-proof、changed files 和关键证据路径。

必须写入：

- `$AO_ARTIFACTS_DIR/production-report.json`
- `$AO_ARTIFACTS_DIR/production-report.md`

报告必须包含 run_id、workflow version、project root、workspace root、worktree path、input hash、commits、命令证据、DB/API/browser/package 证据、风险和失败时 resume command。

