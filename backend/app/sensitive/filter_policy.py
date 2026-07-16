"""敏感检测过滤策略：ingest 和 backfill 共用，避免两条路径行为不一致。"""
from __future__ import annotations

# credential 类：tool_call（命令/代码）中仍需检测的类别
# - token: API key / Bearer token（脚本中硬编码是真实风险）
# - secret: 通用密钥
# - cookie: Cookie 值
# - sensitive_reference: 敏感文件路径引用（cat /etc/shadow 是真实风险）
_CREDENTIAL_CATEGORIES = frozenset({"token", "secret", "cookie", "sensitive_reference"})


def filter_sensitive_matches(item: dict, matches: list[dict]) -> list[dict]:
    """按 fact 的 fact_type + category 策略过滤敏感命中。

    策略：
    - content fact：全部保留（用户输入和 Agent 输出是 PII 真实泄露通道）
    - tool + tool_call（命令/代码）：只保留 credential 类
      （代码 diff 中的 PII 是示例字面量；脚本硬编码 API key 是真实风险）
    - tool + tool_result（工具输出）：全部保留
      （cat config.json / grep / MCP 查询返回可能含真实 PII）
    - 其他/未知：全部保留（兜底，不过度过滤）

    fact_type 或 category 为 None/空串/未设置时，全部保留（兜底）。
    """
    fact_type = item.get("fact_type") or ""
    category = item.get("category") or ""
    if fact_type != "tool":
        return matches
    if category != "tool_call":
        return matches
    return [m for m in matches if m.get("category") in _CREDENTIAL_CATEGORIES]
