"""扩充敏感数据规则测试：云服务商凭据 / 数据库连接串 / 其他平台 token + 排除规则。

TDD：先写测试（失败），再实现 rules.py 的规则和排除模式。
覆盖 Task 4 的 13 条新规则 + 3 条排除场景。
"""
from __future__ import annotations

import pytest

from app.sensitive import engine as det
from app.sensitive.rules import EXCLUSION_PATTERNS


def _matches_by_rule(text: str, rule_name: str):
    """返回 detect 结果中 reason_code == rule_name 的命中。"""
    return [m for m in det.detect(text) if m["reason_code"] == rule_name]


# ---------------------------------------------------------------------------
# 云服务商凭据（token）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "rule_name,text",
    [
        ("anthropic_api_key", "sk-ant-api03-" + "9f8e7d6c5b4a3210fedcba9876543210ABCDEF1234"),
        ("google_api_key", "AIza" + "9f8e7d6c5b4a3210fedcba9876543210ABCD"),
        ("stripe_live_key", "sk_live_" + "9f8e7d6c5b4a3210fedcba98"),
        ("slack_bot_token", "xoxb-1234567890-1234567890-9f8e7d6c5b4a3210fedcba98"),
        ("slack_user_token", "xoxp-1234567890-1234567890-1234567890-9f8e7d6c5b4a3210fedcba98"),
        ("slack_webhook_url", "https://hooks.slack.com/services/T9F8E7D6C/B5B4A321/9f8e7d6c5b4a3210fedcba9876543210"),
    ],
)
def test_cloud_provider_credentials_match(rule_name, text):
    hits = _matches_by_rule(text, rule_name)
    assert hits, f"{rule_name} 应命中: {text!r}"
    assert hits[0]["category"] == "token"
    assert hits[0]["confidence"] == "high"


# ---------------------------------------------------------------------------
# 数据库连接串（secret）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "rule_name,text",
    [
        ("postgres_connection", "postgresql://user:pass@host:5432/db"),
        ("mysql_connection", "mysql://user:pass@host:3306/db"),
        ("redis_connection", "redis://user:pass@host:6379"),
        ("mongodb_connection", "mongodb://user:pass@host:27017/db"),
    ],
)
def test_database_connection_strings_match(rule_name, text):
    hits = _matches_by_rule(text, rule_name)
    assert hits, f"{rule_name} 应命中: {text!r}"
    assert hits[0]["category"] == "secret"
    assert hits[0]["confidence"] == "high"


# ---------------------------------------------------------------------------
# 其他平台 token
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "rule_name,text",
    [
        ("npm_token", "npm_" + "9f8e7d6c5b4a3210fedcba9876543210ABCDEF"),
        ("linear_api_key", "lin_api_" + "9f8e7d6c5b4a3210fedcba9876543210ABCDEF1234"),
        ("figma_token", "figd_" + "9f8e7d6c5b4a3210fedcba9876543210ABCDEF1234"),
    ],
)
def test_other_platform_tokens_match(rule_name, text):
    hits = _matches_by_rule(text, rule_name)
    assert hits, f"{rule_name} 应命中: {text!r}"
    assert hits[0]["category"] == "token"
    assert hits[0]["confidence"] == "high"


# ---------------------------------------------------------------------------
# 排除规则：本地测试连接串 → confidence 降为 low
# ---------------------------------------------------------------------------

def test_exclusion_postgres_localhost():
    text = "postgresql://user:pass@localhost:5432/test"
    hits = _matches_by_rule(text, "postgres_connection")
    assert hits, "postgres_connection 应命中"
    assert hits[0]["confidence"] == "low"


def test_exclusion_postgres_127001():
    text = "postgresql://user:pass@127.0.0.1:5432/test"
    hits = _matches_by_rule(text, "postgres_connection")
    assert hits, "postgres_connection 应命中"
    assert hits[0]["confidence"] == "low"


def test_exclusion_aws_example_key():
    # AKIAIOSFODNN7EXAMPLE 是 AWS 官方文档示例 key，应被 EXCLUSION_PATTERNS 排除。
    assert any(p.search("AKIAIOSFODNN7EXAMPLE") for p in EXCLUSION_PATTERNS)
