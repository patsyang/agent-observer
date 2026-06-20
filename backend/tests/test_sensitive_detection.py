from __future__ import annotations

from app.sensitivity import sensitive_matches_from_text


def test_sensitive_detection_ignores_token_and_auth_business_words():
    text = "token telemetry token_usage Token 指标 auth status authentication flow auth policy"

    assert sensitive_matches_from_text(text) == []


def test_sensitive_detection_requires_real_values():
    text = (
        "Authorization: Bearer abcdefghijklmnop "
        "Authorization: Basic YmFzaWMtY3JlZGVudGlhbC12YWx1ZQ== "
        "Authorization: token ghp_abcdefghijklmnopqrstuvwxyz123456 "
        "api_token=abcdef1234567890 "
        "OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz "
        "client_secret=secret1234 "
        "Set-Cookie: session=abcdefghijklmnop"
    )

    matches = sensitive_matches_from_text(text)
    categories = {match["category"] for match in matches}
    match_types = {match["match_type"] for match in matches}

    assert categories == {"token", "secret", "cookie"}
    assert {"authorization_bearer", "authorization_basic", "authorization_token", "token_assignment", "secret_assignment", "cookie_assignment"} <= match_types
    assert all(match["confidence"] == "high" for match in matches)
    assert all(match["matched_value"] for match in matches)
