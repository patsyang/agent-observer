from __future__ import annotations

import re

SENSITIVE_MARKERS = {"token", "cookie", "secret", "auth", "credential"}

_SECRET_VALUE = r"([A-Za-z0-9._~+/=-]{8,})"
_TOKEN_VALUE = r"([A-Za-z0-9._~+/=-]{16,})"
_TOKEN_VALUE_RE = re.compile(
    rf"\b(access_token|api_key|api_token|openai_api_key|refresh_token|session_token|token)\b[\"'\s]*[:=][\"'\s]*{_TOKEN_VALUE}",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    rf"\b(client_secret|secret|password|credential)\b[\"'\s]*[:=][\"'\s]*{_SECRET_VALUE}",
    re.IGNORECASE,
)
_AUTHORIZATION_RE = re.compile(r"\bAuthorization\s*:\s*(Bearer|Basic|token)\s+([A-Za-z0-9._~+/=-]{16,})", re.IGNORECASE)
_COOKIE_RE = re.compile(r"\b(Set-Cookie|Cookie)\s*:\s*([^=;\s]{2,})=([^;\s]{8,})", re.IGNORECASE)


def sensitive_categories_from_text(value: object) -> list[str]:
    return sorted({match["category"] for match in sensitive_matches_from_text(value)})


def sensitive_matches_from_text(value: object, evidence_key: str = "text") -> list[dict[str, str]]:
    text = str(value or "")
    if not text:
        return []
    matches: list[dict[str, str]] = []
    for match in _AUTHORIZATION_RE.finditer(text):
        value = _normalized_match(match.group(0))
        scheme = match.group(1).lower()
        matches.append(_match("token", f"authorization_{scheme}", "authorization_value", evidence_key, value))
    for regex, category, match_type, reason in (
        (_TOKEN_VALUE_RE, "token", "token_assignment", "token_value"),
        (_SECRET_VALUE_RE, "secret", "secret_assignment", "secret_value"),
        (_COOKIE_RE, "cookie", "cookie_assignment", "cookie_value"),
    ):
        for match in regex.finditer(text):
            value = _normalized_match(match.group(0))
            if value:
                matches.append(_match(category, match_type, reason, evidence_key, value))
    return matches


def sensitive_matches_from_record(record: dict, payload: dict, args: dict) -> list[dict[str, str]]:
    matches: list[dict[str, str]] = []
    categories = record.get("sensitive_categories") or []
    if isinstance(categories, str):
        categories = [categories]
    if str(record.get("sensitivity_confidence") or "").lower() == "high":
        for category in categories:
            normalized = str(category).lower()
            if normalized in SENSITIVE_MARKERS:
                matches.append(
                    {
                        "category": normalized,
                        "match_type": "explicit_category",
                        "confidence": "high",
                        "evidence_key": "sensitive_categories",
                        "matched_preview": normalized,
                        "matched_value": normalized,
                        "reason_code": "explicit_high_confidence",
                    }
                )
    for key, value in (
        ("command", args.get("command")),
        ("path", args.get("path")),
        ("workdir", args.get("workdir")),
        ("payload_name", payload.get("name")),
    ):
        matches.extend(sensitive_matches_from_text(value, key))
    return matches


def _match(category: str, match_type: str, reason: str, evidence_key: str, value: str) -> dict[str, str]:
    return {
        "category": category,
        "match_type": match_type,
        "confidence": "high",
        "evidence_key": evidence_key,
        "matched_preview": _preview(value),
        "matched_value": value,
        "reason_code": reason,
    }


def _normalized_match(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _preview(value: str) -> str:
    normalized = _normalized_match(value)
    if len(normalized) <= 48:
        return normalized
    return f"{normalized[:24]}...{normalized[-12:]}"
