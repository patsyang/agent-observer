# ao-spec final e2e proof

基于 release profile 执行或汇总最终黑盒验收。证据必须覆盖启动命令、PID/URL、API、DB、browser、package 和 cleanup。

必须写入：

- `$AO_ARTIFACTS_DIR/e2e-proof.json`
- `$AO_ARTIFACTS_DIR/e2e-proof.md`

禁止 screenshot-only proof，禁止 mock-only final proof，禁止包含敏感原文。

