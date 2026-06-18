# ao-plan resolve slice brief

读取 workflow input、`scope-resolution.json`、目标项目规则、stack contract 和已有上游规格或 plan。只做输入规范化，不写实现代码。

必须写入：

- `$AO_ARTIFACTS_DIR/slice-brief.md`

`slice-brief.md` 必须说明本次目标、来源上下文、scope、non-goals、existing contracts、integration points、acceptance、verification expectations 和 stop conditions。

如果输入需要新增或改变产品事实、数据模型、隐私、安全或长期验收矩阵，写明升级 `/ao-spec` 的原因并让节点失败。
