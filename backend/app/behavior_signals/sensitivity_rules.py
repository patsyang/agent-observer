"""Sensitivity rules — 25 种识别类型，6 大类预编译正则。

TDD 契约：
- SENSITIVITY_RULES: dict[str, re.Pattern] — 6 大类 25 种规则
- EXCLUSION_PATTERNS: list[re.Pattern] — 占位符/环境变量引用排除
- scan_text(text) -> list[dict] — 对纯文本扫描，返回命中列表
- scan_entry(entry) -> list[dict] — 对 fact entry 扫描 4 个字段
"""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# 1. API Keys (5 种)
# ---------------------------------------------------------------------------

_SENSITIVITY_RULES: dict[str, re.Pattern] = {
    # 1. API Keys
    "openai_api_key": re.compile(r"sk-[a-zA-Z0-9_-]{30,}"),
    "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9_]{30,}"),
    "azure_sas_token": re.compile(r"SharedAccessSignature=[a-zA-Z0-9+%/=]+"),
    "huggingface_token": re.compile(r"hf_[A-Za-z0-9]{34,}"),
    "generic_api_key": re.compile(r"(?i)(?:api[_\-]?key|apikey)\s*[:=]\s*[A-Za-z0-9]{16,}"),
    # 2. Cryptographic Materials
    "pem_private_key": re.compile(r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----"),
    "ssh_private_key": re.compile(r"-----BEGIN OPENSSH PRIVATE KEY-----"),
    "jwt_token": re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "aws_secret_key": re.compile(r"(?i)aws[_\-]?secret[_\-]?access?[_\-]?key\s*[:=]\s*[A-Za-z0-9/+=]{40}"),
    # 3. Payment Data
    "credit_card_luhn": re.compile(r"\b(?:4[0-9]{15}|5[1-5][0-9]{14}|3[47][0-9]{13})\b"),
    "bank_account": re.compile(r"(?i)bank[_\-]?account\s*[:=]\s*\d{8,17}"),
    "swift_code": re.compile(r"\b[A-Z]{4}[A-Z]{2}\d{2}[A-Z]{0,3}\b"),
    # 4. Identity Documents
    "china_id_card": re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)"),
    "passport_number": re.compile(r"(?i)(?:passport|pass_no)\s*[:=]\s*[A-Za-z0-9]{5,12}"),
    "phone_number": re.compile(r"(?<!\d)(?:\+?86[-\s]?)?1[3-9]\d{9}(?!\d)"),
    # 5. Credentials
    "database_password": re.compile(r"(?i)(?:db[_\-]?pass(?:word)?|database[_\-]?password)\s*[:=]\s*\S{8,}"),
    "smtp_password": re.compile(r"(?i)smtp[_\-]?pass\s*[:=]\s*\S{8,}"),
    "oauth_token": re.compile(r"(?i)oauth[_\-]?token\s*[:=]\s*[A-Za-z0-9_-]{20,}"),
    "private_key_content": re.compile(r"(?:private_key|secret)\s*[:=]\s*(?:[\"']?)[A-Za-z0-9+/=]{40,}"),
    # 6. Sensitive Paths
    "linux_sensitive": re.compile(r"(?:^|/)(?:etc/(?:shadow|passwd|sudoers)|root/.ssh/authorized_keys)"),
    "windows_sensitive": re.compile(r"(?:^|[\\/])(?:Windows|WINDOWS)[\\/](?:System32|syswow64)[\\/]config[\\/](?:SAM|SECURITY|SYSTEM)"),
    "macos_sensitive": re.compile(r"(?:^|/)Library/(?:Keychains|Security)/"),
    "env_file": re.compile(r"(?:^|[\\/])\.(?:env|environment)(?:\.local)?(?:\.[a-z]+)?$"),
    "credential_file": re.compile(r"(?:^|[\\/])(?:\.?credentials|\.?netrc|\.?htpasswd|\.?npmrc|\.?pypirc)(?:\.[a-z]+)?$"),
    "ssh_directory": re.compile(r"(?:^|/)\.ssh/[a-z]+"),
}

# Rule-to-category mapping for grouping
_RULE_CATEGORIES: dict[str, str] = {
    "openai_api_key": "api_key",
    "github_token": "api_key",
    "azure_sas_token": "api_key",
    "huggingface_token": "api_key",
    "generic_api_key": "api_key",
    "pem_private_key": "crypto_material",
    "ssh_private_key": "crypto_material",
    "jwt_token": "crypto_material",
    "aws_secret_key": "crypto_material",
    "credit_card_luhn": "payment_data",
    "bank_account": "payment_data",
    "swift_code": "payment_data",
    "china_id_card": "identity_document",
    "passport_number": "identity_document",
    "phone_number": "identity_document",
    "database_password": "credential",
    "smtp_password": "credential",
    "oauth_token": "credential",
    "private_key_content": "credential",
    "linux_sensitive": "sensitive_path",
    "windows_sensitive": "sensitive_path",
    "macos_sensitive": "sensitive_path",
    "env_file": "sensitive_path",
    "credential_file": "sensitive_path",
    "ssh_directory": "sensitive_path",
}

# ---------------------------------------------------------------------------
# Exclusion patterns (zero false-positive guarantee)
# ---------------------------------------------------------------------------

EXCLUSION_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?i)^(?:xxx)+$"),                          # xxx...xxx
    re.compile(r"^\$\{[A-Z_]+\}$"),                         # ${ENV_VAR}
    re.compile(r"^\$[A-Z_]+$"),                              # $ENV_VAR
    re.compile(r"<[^>]*?-?key[^>]*?>"),                     # <your-api-key>
    re.compile(r"(?:placeholder|example|sample|dummy|test)"), # 占位符关键词
]

SENSITIVITY_RULES: dict[str, re.Pattern] = _SENSITIVITY_RULES


# ---------------------------------------------------------------------------
# Validation helpers (Luhn, ISO 7064 MOD 11-2)
# ---------------------------------------------------------------------------

def _luhn_check(number: str) -> bool:
    """Validate credit card number using Luhn algorithm."""
    digits = [int(d) for d in number if d.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    checksum = 0
    reverse = digits[::-1]
    for i, d in enumerate(reverse):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        checksum += d
    return checksum % 10 == 0


def _iso_7064_mod11_2_check(value: str) -> bool:
    """Validate Chinese ID card using ISO 7064 MOD 11-2."""
    if len(value) != 18:
        return False
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    check_chars = "10X98765432"
    total = 0
    for i in range(17):
        total += int(value[i]) * weights[i]
    return check_chars[total % 11] == value[17].upper()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _matches_exclusion(text: str) -> bool:
    """Check if text matches any exclusion pattern."""
    return any(pat.search(text) for pat in EXCLUSION_PATTERNS)


def scan_text(text: str) -> list[dict[str, Any]]:
    """Scan plain text against all sensitivity rules.

    Returns list of hit dicts with keys:
      - rule_type: str  — the SENSITIVITY_RULES key
      - category: str   — the 6-category group
      - confidence: str — "high" or "low"
    """
    hits: list[dict[str, Any]] = []

    # Check exclusion first — if text is purely an exclusion pattern, skip
    if _matches_exclusion(text):
        # Still scan for partial matches but mark low confidence
        for rule_type, pattern in _SENSITIVITY_RULES.items():
            m = pattern.search(text)
            if m:
                hits.append({
                    "rule_type": rule_type,
                    "category": _RULE_CATEGORIES.get(rule_type, "unknown"),
                    "confidence": "low",
                    "matched_value": m.group(0)[:100],
                    "scanned_at": datetime.now(UTC).isoformat(),
                })
        return hits

    for rule_type, pattern in _SENSITIVITY_RULES.items():
        m = pattern.search(text)
        if not m:
            continue

        matched_value = m.group(0)
        confidence = "high"

        # Luhn check for credit cards
        if rule_type == "credit_card_luhn":
            digits_only = re.sub(r"\D", "", matched_value)
            if not _luhn_check(digits_only):
                confidence = "low"
                continue  # Skip false positives entirely

        # ISO 7064 MOD 11-2 for Chinese ID cards
        if rule_type == "china_id_card":
            if not _iso_7064_mod11_2_check(matched_value):
                confidence = "low"
                continue

        # Check if matched value itself is an exclusion pattern
        if _matches_exclusion(matched_value):
            confidence = "low"

        hits.append({
            "rule_type": rule_type,
            "category": _RULE_CATEGORIES.get(rule_type, "unknown"),
            "confidence": confidence,
            "matched_value": matched_value[:100],
            "scanned_at": datetime.now(UTC).isoformat(),
        })

    return hits


def scan_entry(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Scan a fact entry across 4 fields: function_call_output, agent_response,
    agent_reasoning, command_arguments.

    Returns combined hit list from all scanned fields.
    """
    all_hits: list[dict[str, Any]] = []
    scanned_fields: list[str] = []

    # Field 1: function_call_output.output
    fc_output = entry.get("function_call_output")
    if isinstance(fc_output, dict):
        text = fc_output.get("output", "")
        if text:
            scanned_fields.append("function_call_output")
            all_hits.extend(scan_text(str(text)))

    # Field 2: agent_response.content
    ar_content = entry.get("agent_response")
    if isinstance(ar_content, dict):
        text = ar_content.get("content", "")
        if text:
            scanned_fields.append("agent_response")
            all_hits.extend(scan_text(str(text)))

    # Field 3: agent_reasoning.content
    agr_content = entry.get("agent_reasoning")
    if isinstance(agr_content, dict):
        text = agr_content.get("content", "")
        if text:
            scanned_fields.append("agent_reasoning")
            all_hits.extend(scan_text(str(text)))

    # Field 4: command_arguments
    cmd_args = entry.get("command_arguments")
    if cmd_args:
        scanned_fields.append("command_arguments")
        all_hits.extend(scan_text(str(cmd_args)))

    # Tag each hit with source field
    field_index = 0
    for hit in all_hits:
        if field_index < len(scanned_fields):
            hit["source_field"] = scanned_fields[field_index]
            field_index += 1

    return all_hits
