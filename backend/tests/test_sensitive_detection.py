from __future__ import annotations

from app.sensitive import sensitive_matches_from_text


def test_sensitive_detection_ignores_token_and_auth_business_words():
    text = "token telemetry token_usage Token 指标 auth status authentication flow auth policy"

    assert sensitive_matches_from_text(text) == []


def test_sensitive_detection_requires_real_values():
    # 用真实形态的值（高熵、非占位），验证 token/secret/cookie 各子类型都能 high 命中。
    # 不用 abcdefgh / sk-proj-abc... 这类占位串——它们应被排除规则降级。
    text = (
        "Authorization: Bearer 9f8e7d6c5b4a3210fedcba9876543210 "
        "Authorization: Basic YmFzaWMtY3JlZGVudGlhbC12YWx1ZQ== "
        "Authorization: token ghp_9f8e7d6c5b4a3210fedcba9876543210 "
        "api_token=9f8e7d6c5b4a3210fedcba98 "
        "OPENAI_API_KEY=sk-proj-9f8e7d6c5b4a3210fedcba9876543210ABCDEF123456 "
        "client_secret=9f8e7d6c5b4a3210 "
        "Set-Cookie: session=9f8e7d6c5b4a3210fedcba9876543210"
    )

    matches = sensitive_matches_from_text(text)
    categories = {match["category"] for match in matches}
    match_types = {match["match_type"] for match in matches}

    assert categories == {"token", "secret", "cookie"}
    assert {"authorization_bearer", "authorization_basic", "authorization_token", "token_assignment", "secret_assignment", "cookie_assignment"} <= match_types
    assert all(match["confidence"] == "high" for match in matches), matches
    assert all(match["matched_value"] for match in matches)
