"""工具失败分类测试：workflow gate / validation / crash / fallback / 截断边界。"""
from __future__ import annotations

import pytest

from app.behavior_signals.common import classify_tool_failure


@pytest.mark.parametrize(
    "reason,body,expected_sub_type,expected_priority",
    [
        # workflow gate 阻断
        ('{"blocked": true, "gate": "contract"}', "some envelope body", "workflow_gate_blocked", 30),
        # blocked=false 时落入 tool_crash
        ('{"blocked": false}', "ModuleNotFoundError: foo", "tool_crash", 95),
        # 非 dict reason 落入 fallback
        ("not json", "some body", "tool_fallback", 70),
        # 验证失败：pytest/vitest/eslint/npm build/tsc
        ("reason", "pytest tests failed with exit 1", "validation_failure", 60),
        ("reason", "npm run test — vitest failed", "validation_failure", 60),
        ("reason", "eslint found 3 errors", "validation_failure", 60),
        ("reason", "npm run build failed", "validation_failure", 60),
        ("reason", "tsc returned errors", "validation_failure", 60),
        # 工具崩溃：各类异常
        ("reason", "ModuleNotFoundError: No module named 'foo'", "tool_crash", 95),
        ("reason", "Traceback (most recent call last):\n  raise ValueError", "tool_crash", 95),
        ("reason", "FileNotFoundError: [Errno 2] No such file", "tool_crash", 95),
        ("reason", "PermissionError: [Errno 13] Permission denied", "tool_crash", 95),
        ("reason", "Exception: something broke", "tool_crash", 95),
        # 兜底
        ("reason", "some generic error message", "tool_fallback", 70),
        ("reason", "", "tool_fallback", 70),
        ("reason", None, "tool_fallback", 70),
    ],
)
def test_classify_tool_failure(reason, body, expected_sub_type, expected_priority):
    """分类器应正确识别 workflow gate / validation / crash / fallback 各类失败模式。"""
    result = classify_tool_failure(reason, body)
    assert result["sub_type"] == expected_sub_type
    assert result["priority"] == expected_priority


def test_snippet_beyond_2000_chars_falls_through():
    """错误模式出现在 2000 字符之后时应落入 fallback（截断保护）。"""
    long_prefix = "x" * 2100
    result = classify_tool_failure("reason", long_prefix + "ModuleNotFoundError: foo")
    assert result["sub_type"] == "tool_fallback"


def test_pattern_within_2000_chars_still_matched():
    """错误模式出现在 2000 字符之内时应正常匹配。"""
    result = classify_tool_failure("reason", "a" * 1000 + "ModuleNotFoundError: foo")
    assert result["sub_type"] == "tool_crash"
