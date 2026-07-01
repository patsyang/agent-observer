"""Tests for classify_tool_failure — story-003."""

from __future__ import annotations

import pytest

from app.behavior_signals.common import classify_tool_failure


class TestWorkflowGateBlocked:
    def test_blocked_true_returns_low_priority(self):
        result = classify_tool_failure(
            '{"blocked": true, "gate": "contract"}',
            "some envelope body",
        )
        assert result["sub_type"] == "workflow_gate_blocked"
        assert result["priority"] == 30

    def test_blocked_false_not_matched(self):
        result = classify_tool_failure(
            '{"blocked": false}',
            "ModuleNotFoundError: foo",
        )
        assert result["sub_type"] == "tool_crash"
        assert result["priority"] == 95

    def test_non_dict_reason_falls_through(self):
        result = classify_tool_failure("not json", "some body")
        assert result["sub_type"] == "tool_fallback"


class TestValidationFailure:
    def test_pytest_pattern(self):
        result = classify_tool_failure("reason", "pytest tests failed with exit 1")
        assert result["sub_type"] == "validation_failure"
        assert result["priority"] == 60

    def test_vitest_pattern(self):
        result = classify_tool_failure("reason", "npm run test — vitest failed")
        assert result["sub_type"] == "validation_failure"
        assert result["priority"] == 60

    def test_eslint_pattern(self):
        result = classify_tool_failure("reason", "eslint found 3 errors")
        assert result["sub_type"] == "validation_failure"
        assert result["priority"] == 60

    def test_npm_build_pattern(self):
        result = classify_tool_failure("reason", "npm run build failed")
        assert result["sub_type"] == "validation_failure"
        assert result["priority"] == 60

    def test_tsc_pattern(self):
        result = classify_tool_failure("reason", "tsc returned errors")
        assert result["sub_type"] == "validation_failure"
        assert result["priority"] == 60


class TestToolCrash:
    def test_import_error(self):
        result = classify_tool_failure("reason", "ModuleNotFoundError: No module named 'foo'")
        assert result["sub_type"] == "tool_crash"
        assert result["priority"] == 95

    def test_traceback(self):
        result = classify_tool_failure("reason", "Traceback (most recent call last):\n  raise ValueError")
        assert result["sub_type"] == "tool_crash"
        assert result["priority"] == 95

    def test_file_not_found(self):
        result = classify_tool_failure("reason", "FileNotFoundError: [Errno 2] No such file")
        assert result["sub_type"] == "tool_crash"
        assert result["priority"] == 95

    def test_permission_denied(self):
        result = classify_tool_failure("reason", "PermissionError: [Errno 13] Permission denied")
        assert result["sub_type"] == "tool_crash"
        assert result["priority"] == 95

    def test_case_insensitive_exception(self):
        result = classify_tool_failure("reason", "Exception: something broke")
        assert result["sub_type"] == "tool_crash"
        assert result["priority"] == 95


class TestFallback:
    def test_unmatched_pattern(self):
        result = classify_tool_failure("reason", "some generic error message")
        assert result["sub_type"] == "tool_fallback"
        assert result["priority"] == 70

    def test_empty_body(self):
        result = classify_tool_failure("reason", "")
        assert result["sub_type"] == "tool_fallback"

    def test_none_body(self):
        result = classify_tool_failure("reason", None)
        assert result["sub_type"] == "tool_fallback"


class TestEnvelopeBodyLimit:
    def test_snippet_limited_to_2000_chars(self):
        # Long body where error pattern is beyond 2000 chars should fall through
        long_prefix = "x" * 2100
        result = classify_tool_failure("reason", long_prefix + "ModuleNotFoundError: foo")
        assert result["sub_type"] == "tool_fallback"

    def test_pattern_within_2000_chars(self):
        result = classify_tool_failure("reason", "a" * 1000 + "ModuleNotFoundError: foo")
        assert result["sub_type"] == "tool_crash"
