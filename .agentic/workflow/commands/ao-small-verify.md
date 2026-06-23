# ao-small verify

读取 workflow input、`implementation.md`、`changed-files.txt` 和目标项目 verify command。运行受影响验证或说明不可运行原因。

必须写入：

- `$AO_ARTIFACTS_DIR/verification.md`

`verification.md` 必须记录命令、结果、失败修复过程或无法运行原因。Bug 修复必须说明回归测试证据。
