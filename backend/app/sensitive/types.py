"""敏感命中（Match）的字段契约与扫描常量。"""
from __future__ import annotations

# 检测对 fact 文本的总长度上限，防止超大 raw_content 拖垮 ingest 热路径。
SCAN_BYTE_CAP = 262144  # 256 KiB

# Match dict 字段（保持 legacy 形状，下游展示/聚合零改动）：
#   category        str   phone / email / id_card / bank_card / token / secret / cookie / sensitive_reference
#   match_type      str   规则名，或细化（如 authorization_bearer）
#   confidence      str   "high" | "low"（low = 占位/示例/代码，detect_for_fact 只取 high 写库）
#   evidence_key    str   来源标记（ingest / backfill / text）
#   matched_value   str   命中原文（截断 100 字符）
#   matched_preview str   预览（去空白、截断 48）
#   reason_code     str   规则 reason（如 unionpay / email_address）
