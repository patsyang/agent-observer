from __future__ import annotations

import re

SENSITIVE_MARKERS = {"token", "cookie", "secret", "auth", "credential"}

_TOKEN_SAFE_RE = re.compile(
    r"\b("
    r"token_count|tokens?|total_tokens|input_tokens|output_tokens|cached_input_tokens|"
    r"last_token_usage|total_token_usage|token_usage|token_budget|token_telemetry"
    r")\b"
    r"|\b(token|tokens)\s+(telemetry|usage|count|budget|accounting|rollup|summary|window)\b"
    r"|\b(telemetry|usage|count|budget|accounting|rollup|summary|window)\s+(token|tokens)\b",
    re.IGNORECASE,
)
_TOKEN_CREDENTIAL_RE = re.compile(
    r"\b(access|refresh|api|bearer|auth|session|credential|secret)[-_ ]?token\b"
    r"|\btoken[-_ ]?(secret|key|value)\b"
    r"|[\"']token[\"']\s*[:=]"
    r"|(?:^|[\s{,;])token\s*[:=]",
    re.IGNORECASE,
)


def sensitive_categories_from_text(value: object) -> list[str]:
    text = str(value or "").lower()
    if not text:
        return []
    categories: set[str] = set()
    if _looks_like_credential_token(text):
        categories.add("token")
    if re.search(r"\b(set-cookie|cookies?|cookie_jar)\b", text):
        categories.add("cookie")
    if re.search(r"\b(secret|secrets|client_secret)\b", text):
        categories.add("secret")
    if re.search(r"\b(credential|credentials)\b", text):
        categories.add("credential")
    if re.search(r"\b(auth|authentication|authorization)\b|auth[._/-]", text):
        categories.add("auth")
    return sorted(categories)


def _looks_like_credential_token(text: str) -> bool:
    if not re.search(r"\btoken(s)?\b|access_token|refresh_token|api_token|bearer", text):
        return False
    if _TOKEN_CREDENTIAL_RE.search(text):
        return True
    return not _TOKEN_SAFE_RE.search(text)
