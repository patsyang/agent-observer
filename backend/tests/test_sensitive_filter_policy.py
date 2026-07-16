"""敏感检测过滤策略测试。

验证 filter_sensitive_matches 按 fact_type + category 正确过滤敏感命中。
"""
from __future__ import annotations

from app.sensitive.filter_policy import filter_sensitive_matches


def _match(category: str, value: str = "test") -> dict:
    return {"category": category, "matched_value": value, "confidence": "high"}


def test_tool_call_code_diff_pii_filtered():
    """tool_call 中的代码 diff 示例 PII 应被过滤。"""
    item = {"fact_type": "tool", "category": "tool_call"}
    matches = [
        _match("phone", "13800138000"),
        _match("email", "test@example.com"),
        _match("id_card", "310101199001011234"),
        _match("bank_card", "6222021001112223"),
    ]
    result = filter_sensitive_matches(item, matches)
    assert result == [], f"tool_call 中的 PII 应被过滤: {result}"


def test_tool_call_credential_kept():
    """tool_call 中的 credential 类应保留。"""
    item = {"fact_type": "tool", "category": "tool_call"}
    matches = [
        _match("token", "sk-proj-abc123"),
        _match("secret", "password123"),
        _match("cookie", "session=abc"),
        _match("sensitive_reference", "/etc/shadow"),
    ]
    result = filter_sensitive_matches(item, matches)
    assert len(result) == 4, f"tool_call 中的 credential 应全部保留: {result}"
    categories = {m["category"] for m in result}
    assert categories == {"token", "secret", "cookie", "sensitive_reference"}


def test_tool_call_mixed_only_credential_kept():
    """tool_call 中 PII 被过滤，credential 保留。"""
    item = {"fact_type": "tool", "category": "tool_call"}
    matches = [
        _match("phone", "13800138000"),
        _match("token", "sk-proj-abc123"),
        _match("bank_card", "6222021001112223"),
        _match("secret", "password123"),
    ]
    result = filter_sensitive_matches(item, matches)
    assert len(result) == 2, f"应只剩 credential: {result}"
    categories = {m["category"] for m in result}
    assert categories == {"token", "secret"}


def test_tool_result_real_pii_kept():
    """tool_result 中的真实 PII 应保留。"""
    item = {"fact_type": "tool", "category": "tool_result"}
    matches = [
        _match("phone", "13800138000"),
        _match("email", "test@example.com"),
        _match("id_card", "310101199001011234"),
    ]
    result = filter_sensitive_matches(item, matches)
    assert len(result) == 3, f"tool_result 中的 PII 应全部保留: {result}"


def test_tool_result_credential_kept():
    """tool_result 中的 credential 也应保留。"""
    item = {"fact_type": "tool", "category": "tool_result"}
    matches = [
        _match("phone", "13800138000"),
        _match("token", "sk-proj-abc123"),
    ]
    result = filter_sensitive_matches(item, matches)
    assert len(result) == 2, f"tool_result 中全部应保留: {result}"


def test_content_fact_all_kept():
    """content fact 全部保留。"""
    item = {"fact_type": "content", "category": "agent_prompt"}
    matches = [
        _match("phone", "13521661669"),
        _match("token", "sk-proj-abc123"),
        _match("email", "test@example.com"),
    ]
    result = filter_sensitive_matches(item, matches)
    assert len(result) == 3, f"content fact 应全部保留: {result}"


def test_risk_fact_all_kept():
    """risk fact 走兜底，全部保留。"""
    item = {"fact_type": "risk", "category": "file_change"}
    matches = [_match("phone", "13800138000")]
    result = filter_sensitive_matches(item, matches)
    assert len(result) == 1, f"risk fact 应走兜底全保留: {result}"


def test_fact_type_missing_all_kept():
    """fact_type 缺失时全部保留（兜底）。"""
    item = {}
    matches = [_match("phone", "13800138000"), _match("token", "sk-xxx")]
    result = filter_sensitive_matches(item, matches)
    assert len(result) == 2, f"fact_type 缺失应走兜底全保留: {result}"


def test_category_missing_all_kept():
    """fact_type=tool 但 category 缺失时全部保留（兜底）。"""
    item = {"fact_type": "tool"}
    matches = [_match("phone", "13800138000")]
    result = filter_sensitive_matches(item, matches)
    assert len(result) == 1, f"category 缺失应走兜底全保留: {result}"


def test_category_empty_string_all_kept():
    """fact_type=tool 但 category 为空串时全部保留（兜底）。"""
    item = {"fact_type": "tool", "category": ""}
    matches = [_match("phone", "13800138000")]
    result = filter_sensitive_matches(item, matches)
    assert len(result) == 1, f"category 空串应走兜底全保留: {result}"


def test_filter_idempotent():
    """过滤幂等性：调用两次结果一致。"""
    item = {"fact_type": "tool", "category": "tool_call"}
    matches = [_match("phone", "13800138000"), _match("token", "sk-xxx")]
    result1 = filter_sensitive_matches(item, matches)
    result2 = filter_sensitive_matches(item, result1)
    assert result1 == result2, f"过滤应幂等: {result1} != {result2}"


def test_empty_matches_returns_empty():
    """空 matches 输入返回空。"""
    item = {"fact_type": "tool", "category": "tool_call"}
    result = filter_sensitive_matches(item, [])
    assert result == []


def test_mcp_tool_result_all_kept():
    """MCP 工具结果（category=tool_result）全部保留。"""
    item = {"fact_type": "tool", "category": "tool_result"}
    matches = [
        _match("phone", "13800138000"),
        _match("token", "sk-proj-abc123"),
        _match("email", "test@example.com"),
    ]
    result = filter_sensitive_matches(item, matches)
    assert len(result) == 3, f"MCP 工具结果应全部保留: {result}"
