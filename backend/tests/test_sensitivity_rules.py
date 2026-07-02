"""Tests for story-001: sensitivity_rules — 25 种识别类型 + 6 大类正则库."""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Ensure backend/app is importable
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from app.behavior_signals import sensitivity_rules


# ---------------------------------------------------------------------------
# Module-level constants verification
# ---------------------------------------------------------------------------

class TestSensitivityRulesConstants:
    """Verify the 6 categories, 25 rule types, and exclusion patterns exist."""

    def test_has_six_categories(self):
        assert set(sensitivity_rules.SENSITIVITY_RULES.keys()) == {
            "openai_api_key",
            "github_token",
            "azure_sas_token",
            "huggingface_token",
            "generic_api_key",
            "pem_private_key",
            "ssh_private_key",
            "jwt_token",
            "aws_secret_key",
            "credit_card_luhn",
            "bank_account",
            "swift_code",
            "china_id_card",
            "passport_number",
            "phone_number",
            "database_password",
            "smtp_password",
            "oauth_token",
            "private_key_content",
            "linux_sensitive",
            "windows_sensitive",
            "macos_sensitive",
            "env_file",
            "credential_file",
            "ssh_directory",
        }

    def test_has_25_rule_types(self):
        assert len(sensitivity_rules.SENSITIVITY_RULES) == 25

    def test_all_patterns_compiled(self):
        for name, pattern in sensitivity_rules.SENSITIVITY_RULES.items():
            assert isinstance(pattern, re.Pattern), (
                f"{name} is not a compiled re.Pattern"
            )

    def test_exclusion_patterns_exist(self):
        assert len(sensitivity_rules.EXCLUSION_PATTERNS) >= 5

    def test_exclusion_patterns_compiled(self):
        for pat in sensitivity_rules.EXCLUSION_PATTERNS:
            assert isinstance(pat, re.Pattern)


# ---------------------------------------------------------------------------
# Category 1: API Keys — 5 types
# ---------------------------------------------------------------------------

class TestApiKeys:
    def test_openai_api_key_matches(self):
        text = "OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz1234567890ABCDEF"
        hits = sensitivity_rules.scan_text(text)
        categories = {h["rule_type"] for h in hits}
        assert "openai_api_key" in categories

    def test_github_token_matches(self):
        text = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh"
        hits = sensitivity_rules.scan_text(text)
        categories = {h["rule_type"] for h in hits}
        assert "github_token" in categories

    def test_azure_sas_token_matches(self):
        text = "DefaultEndpointsProtocol=https;SharedAccessSignature=signature123"
        hits = sensitivity_rules.scan_text(text)
        categories = {h["rule_type"] for h in hits}
        assert "azure_sas_token" in categories

    def test_huggingface_token_matches(self):
        text = "hf_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh"
        hits = sensitivity_rules.scan_text(text)
        categories = {h["rule_type"] for h in hits}
        assert "huggingface_token" in categories

    def test_generic_api_key_matches(self):
        text = "api_key: ABCDEFGHIJKLMNOP"
        hits = sensitivity_rules.scan_text(text)
        categories = {h["rule_type"] for h in hits}
        assert "generic_api_key" in categories


# ---------------------------------------------------------------------------
# Category 2: Cryptographic Materials — 4 types
# ---------------------------------------------------------------------------

class TestCryptoMaterials:
    def test_pem_private_key_matches(self):
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIE..."
        hits = sensitivity_rules.scan_text(text)
        categories = {h["rule_type"] for h in hits}
        assert "pem_private_key" in categories

    def test_ssh_private_key_matches(self):
        text = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnN..."
        hits = sensitivity_rules.scan_text(text)
        categories = {h["rule_type"] for h in hits}
        assert "ssh_private_key" in categories

    def test_jwt_token_matches(self):
        text = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        hits = sensitivity_rules.scan_text(text)
        categories = {h["rule_type"] for h in hits}
        assert "jwt_token" in categories

    def test_aws_secret_key_matches(self):
        text = "aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
        hits = sensitivity_rules.scan_text(text)
        categories = {h["rule_type"] for h in hits}
        assert "aws_secret_key" in categories


# ---------------------------------------------------------------------------
# Category 3: Payment Data — 3 types
# ---------------------------------------------------------------------------

class TestPaymentData:
    def test_credit_card_luhn_valid(self):
        # Visa: 4532015112830366 passes Luhn
        text = "card=4532015112830366"
        hits = sensitivity_rules.scan_text(text)
        categories = {h["rule_type"] for h in hits}
        assert "credit_card_luhn" in categories

    def test_bank_account_matches(self):
        text = "bank_account: 12345678901234567"
        hits = sensitivity_rules.scan_text(text)
        categories = {h["rule_type"] for h in hits}
        assert "bank_account" in categories


# ---------------------------------------------------------------------------
# Category 4: Identity Documents — 3 types
# ---------------------------------------------------------------------------

class TestIdentityDocuments:
    def test_china_id_card_valid(self):
        # Valid Chinese ID (ISO 7064 MOD 11-2, checksum=7)
        text = "id_card=110101199001011237"
        hits = sensitivity_rules.scan_text(text)
        categories = {h["rule_type"] for h in hits}
        assert "china_id_card" in categories

    def test_phone_number_matches(self):
        text = "phone=13812345678"
        hits = sensitivity_rules.scan_text(text)
        categories = {h["rule_type"] for h in hits}
        assert "phone_number" in categories


# ---------------------------------------------------------------------------
# Category 5: Credentials — 4 types
# ---------------------------------------------------------------------------

class TestCredentials:
    def test_database_password_matches(self):
        text = "db_password=mysecretpassword123"
        hits = sensitivity_rules.scan_text(text)
        categories = {h["rule_type"] for h in hits}
        assert "database_password" in categories

    def test_smtp_password_matches(self):
        text = "smtp_pass: smtpsecret123"
        hits = sensitivity_rules.scan_text(text)
        categories = {h["rule_type"] for h in hits}
        assert "smtp_password" in categories

    def test_oauth_token_matches(self):
        text = "oauth_token=abcdefghijABCDEFGHIJ1234567890"
        hits = sensitivity_rules.scan_text(text)
        categories = {h["rule_type"] for h in hits}
        assert "oauth_token" in categories


# ---------------------------------------------------------------------------
# Category 6: Sensitive Paths — 6 types
# ---------------------------------------------------------------------------

class TestSensitivePaths:
    def test_linux_sensitive_path_matches(self):
        text = "/etc/shadow"
        hits = sensitivity_rules.scan_text(text)
        categories = {h["rule_type"] for h in hits}
        assert "linux_sensitive" in categories

    def test_windows_sensitive_path_matches(self):
        text = "C:\\Windows\\System32\\config\\SAM"
        hits = sensitivity_rules.scan_text(text)
        categories = {h["rule_type"] for h in hits}
        assert "windows_sensitive" in categories

    def test_env_file_matches(self):
        text = ".env.local"
        hits = sensitivity_rules.scan_text(text)
        categories = {h["rule_type"] for h in hits}
        assert "env_file" in categories

    def test_credential_file_matches(self):
        text = ".npmrc"
        hits = sensitivity_rules.scan_text(text)
        categories = {h["rule_type"] for h in hits}
        assert "credential_file" in categories

    def test_ssh_directory_matches(self):
        text = ".ssh/id_rsa"
        hits = sensitivity_rules.scan_text(text)
        categories = {h["rule_type"] for h in hits}
        assert "ssh_directory" in categories


# ---------------------------------------------------------------------------
# Exclusion patterns — zero false positives
# ---------------------------------------------------------------------------

class TestExclusionPatterns:
    def test_placeholder_xxx_not_matched(self):
        text = "xxx xxx xxx xxx"
        hits = sensitivity_rules.scan_text(text)
        assert hits == []

    def test_env_var_reference_not_matched(self):
        text = "${API_KEY}"
        hits = sensitivity_rules.scan_text(text)
        assert hits == []

    def test_dollar_var_not_matched(self):
        text = "$ENV_VAR"
        hits = sensitivity_rules.scan_text(text)
        assert hits == []

    def test_html_placeholder_not_matched(self):
        text = "<your-api-key>"
        hits = sensitivity_rules.scan_text(text)
        assert hits == []

    def test_placeholder_keywords_not_matched(self):
        text = "this is a placeholder example sample dummy test value"
        hits = sensitivity_rules.scan_text(text)
        assert hits == []

    def test_random_numbers_not_credited_as_cc(self):
        # Random digit strings that fail Luhn should not match credit_card
        text = "1234567890123456"
        hits = sensitivity_rules.scan_text(text)
        cc_hits = [h for h in hits if h["rule_type"] == "credit_card_luhn"]
        assert cc_hits == []


# ---------------------------------------------------------------------------
# scan_entry — field expansion across 4 fields
# ---------------------------------------------------------------------------

class TestScanEntryFields:
    def test_scans_function_call_output(self):
        entry = {
            "fact_type": "tool_result",
            "category": "tool_execution_failure",
            "function_call_output": {"output": "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890ABCDEF"},
        }
        hits = sensitivity_rules.scan_entry(entry)
        assert any(h["rule_type"] == "openai_api_key" for h in hits)

    def test_scans_agent_response_content(self):
        entry = {
            "fact_type": "agent_response",
            "category": "agent_response",
            "agent_response": {"content": "Here is your JWT: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"},
        }
        hits = sensitivity_rules.scan_entry(entry)
        assert any(h["rule_type"] == "jwt_token" for h in hits)

    def test_scans_agent_reasoning_content(self):
        entry = {
            "fact_type": "agent_reasoning",
            "category": "agent_reasoning",
            "agent_reasoning": {"content": "The API key is sk-proj-abcdefghijklmnopqrstuvwxyz1234567890ABCDEF"},
        }
        hits = sensitivity_rules.scan_entry(entry)
        assert any(h["rule_type"] == "openai_api_key" for h in hits)

    def test_scans_command_arguments(self):
        entry = {
            "fact_type": "tool_call",
            "category": "tool_call",
            "command_arguments": "OPENAI_API_KEY=sk-proj-abcdefghijklmnopqrstuvwxyz1234567890ABCDEF",
        }
        hits = sensitivity_rules.scan_entry(entry)
        assert any(h["rule_type"] == "openai_api_key" for h in hits)


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

class TestConfidenceScoring:
    def test_exclusion_lowers_confidence(self):
        # Text matches a rule but also matches an exclusion pattern
        text = "sk-proj-placeholder-value"
        hits = sensitivity_rules.scan_text(text)
        if hits:
            # Should be marked low confidence due to exclusion overlap
            assert any(h["confidence"] == "low" for h in hits)

    def test_clean_match_is_high_confidence(self):
        text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA..."
        hits = sensitivity_rules.scan_text(text)
        assert all(h["confidence"] == "high" for h in hits)
