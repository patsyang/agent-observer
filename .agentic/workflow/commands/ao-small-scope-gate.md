# ao-small scope gate

读取 workflow input、`scope-resolution.json`、目标项目规则和 stack contract。判断目标是否真的是小修。

必须写入：

- `$AO_ARTIFACTS_DIR/small-scope.json`
- `$AO_ARTIFACTS_DIR/small-scope.md`

`small-scope.json` 必须包含 goal、change_type、observable_signal、allowed_files、forbidden_areas、requires_repro、verification_commands、upgrade_triggers、max_components、data_model_change_allowed、privacy_change_allowed。

如果跨多个组件、需要多个 task、改变数据模型、隐私、安全或产品能力，节点必须失败并建议 `/ao-plan` 或 `/ao-spec`。
