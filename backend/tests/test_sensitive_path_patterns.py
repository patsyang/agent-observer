"""Tests for story-002: sensitive_path_access — Linux/Windows/generic path pattern matching.

Verifies that SENSITIVE_PATH_PATTERNS from workspace.py correctly identify
sensitive file access in command arguments, tool outputs, and file paths.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Ensure backend/app is importable
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from app.behavior_signals.workspace import SENSITIVE_PATH_PATTERNS


def _find(label: str):
    """Return the (Pattern, label) tuple for a given label."""
    for item in SENSITIVE_PATH_PATTERNS:
        if item[1] == label:
            return item
    assert False, f"No pattern with label {label}"


# ---------------------------------------------------------------------------
# Module-level constants verification
# ---------------------------------------------------------------------------

class TestSensitivePathPatternsConstants:
    """Verify the patterns module exports pre-compiled patterns."""

    def test_patterns_are_list_of_tuples(self):
        assert isinstance(SENSITIVE_PATH_PATTERNS, list)
        for item in SENSITIVE_PATH_PATTERNS:
            assert isinstance(item, tuple)
            assert len(item) == 2
            assert isinstance(item[0], re.Pattern)
            assert isinstance(item[1], str)

    def test_has_linux_patterns(self):
        labels = {label for _, label in SENSITIVE_PATH_PATTERNS}
        assert "linux_system_auth" in labels
        assert "linux_ssh_trust" in labels

    def test_has_windows_patterns(self):
        labels = {label for _, label in SENSITIVE_PATH_PATTERNS}
        assert "windows_credentials_store" in labels

    def test_has_macos_patterns(self):
        labels = {label for _, label in SENSITIVE_PATH_PATTERNS}
        assert "macos_keychain" in labels

    def test_has_generic_credential_patterns(self):
        labels = {label for _, label in SENSITIVE_PATH_PATTERNS}
        assert "env_file" in labels
        assert "credential_file" in labels
        assert "ssh_directory" in labels

    def test_all_patterns_precompiled(self):
        for pattern, _ in SENSITIVE_PATH_PATTERNS:
            assert isinstance(pattern, re.Pattern)

    def test_seven_patterns_total(self):
        assert len(SENSITIVE_PATH_PATTERNS) == 7


# ---------------------------------------------------------------------------
# Linux high-sensitivity path matching
# ---------------------------------------------------------------------------

class TestLinuxPaths:
    def test_etc_shadow_matches(self):
        pattern, _ = _find("linux_system_auth")
        assert pattern.search("/etc/shadow")
        assert pattern.search("/etc/passwd")
        assert pattern.search("/etc/sudoers")

    def test_etc_shadow_does_not_match_subdirs(self):
        pattern, _ = _find("linux_system_auth")
        # /etc/shadow.bak should NOT match (pattern anchored with $)
        assert not pattern.search("/etc/shadow.bak")
        # /etc/shadow.d/ should NOT match
        assert not pattern.search("/etc/shadow.d/")

    def test_root_ssh_authorized_keys_matches(self):
        pattern, _ = _find("linux_ssh_trust")
        assert pattern.search("/root/.ssh/authorized_keys")

    def test_root_ssh_authorized_keys_does_not_match_other(self):
        pattern, _ = _find("linux_ssh_trust")
        assert not pattern.search("/root/.ssh/known_hosts")


# ---------------------------------------------------------------------------
# Windows high-sensitivity path matching
# ---------------------------------------------------------------------------

class TestWindowsPaths:
    def test_windows_sam_matches(self):
        pattern, _ = _find("windows_credentials_store")
        assert pattern.search("C:\\Windows\\System32\\config\\SAM")
        assert pattern.search("C:\\WINDOWS\\System32\\config\\SECURITY")
        assert pattern.search("/Windows/System32/config/SYSTEM")

    def test_windows_case_insensitive(self):
        pattern, _ = _find("windows_credentials_store")
        assert pattern.search("c:\\windows\\system32\\config\\sam")

    def test_windows_does_not_match_non_config(self):
        pattern, _ = _find("windows_credentials_store")
        assert not pattern.search("C:\\Windows\\System32\\drivers\\etc\\hosts")


# ---------------------------------------------------------------------------
# macOS keychain path matching
# ---------------------------------------------------------------------------

class TestMacOSPaths:
    def test_keychains_matches(self):
        pattern, _ = _find("macos_keychain")
        assert pattern.search("Library/Keychains/db")

    def test_security_folder_matches(self):
        pattern, _ = _find("macos_keychain")
        assert pattern.search("Library/Security/Keychain")


# ---------------------------------------------------------------------------
# Generic credential file matching
# ---------------------------------------------------------------------------

class TestGenericCredentialFiles:
    def test_env_file_matches(self):
        pattern, _ = _find("env_file")
        assert pattern.search(".env")
        assert pattern.search("./.env")
        assert pattern.search("/some/path/.env")

    def test_env_local_matches(self):
        pattern, _ = _find("env_file")
        assert pattern.search(".env.local")
        assert pattern.search(".env.production")
        assert pattern.search("/project/.env.development")

    def test_netrc_matches(self):
        pattern, _ = _find("credential_file")
        assert pattern.search(".netrc")
        assert pattern.search(".credentials")
        assert pattern.search(".htpasswd")
        assert pattern.search(".npmrc")
        assert pattern.search(".pypirc")

    def test_ssh_directory_matches(self):
        pattern, _ = _find("ssh_directory")
        assert pattern.search(".ssh/id_rsa")
        assert pattern.search(".ssh/id_ed25519")
        assert pattern.search("/home/user/.ssh/authorized_keys")


# ---------------------------------------------------------------------------
# Path normalization — forward/backward slash handling
# ---------------------------------------------------------------------------

class TestPathNormalization:
    def test_backslash_env_matches(self):
        """Windows-style backslash paths should match env pattern."""
        pattern, _ = _find("env_file")
        assert pattern.search(".env")
        assert pattern.search("\\.env")

    def test_forward_slash_env_matches(self):
        """Unix-style forward slash paths should match env pattern."""
        pattern, _ = _find("env_file")
        assert pattern.search(".env")
        assert pattern.search("/.env")

    def test_mixed_slashes_in_command_argument(self):
        """Mixed slashes in command arguments should still match."""
        text = 'copy "C:\\Users\\admin\\.env" C:\\backup\\'
        pattern, _ = _find("env_file")
        assert pattern.search(text), "env_file pattern should match backslash path"


# ---------------------------------------------------------------------------
# Exclusion patterns — placeholder paths should NOT trigger
# ---------------------------------------------------------------------------

class TestExclusionPaths:
    def test_placeholder_path_not_matched(self):
        """Placeholder paths like /tmp/xxx should not match."""
        pattern_env, _ = _find("env_file")
        pattern_cred, _ = _find("credential_file")
        assert not pattern_env.search("/tmp/xxx"), "env_file should not match /tmp/xxx"
        assert not pattern_cred.search("/tmp/xxx"), "credential_file should not match /tmp/xxx"

    def test_normal_dotfiles_not_matched(self):
        """Normal dotfiles like .editorconfig should not match credential patterns."""
        pattern, _ = _find("credential_file")
        assert not pattern.search(".editorconfig")
        assert not pattern.search(".flake8")


# ---------------------------------------------------------------------------
# Integration: command arguments and tool output scanning
# ---------------------------------------------------------------------------

class TestCommandArgumentScanning:
    """Verify patterns detect sensitive paths in command arguments and tool output."""

    def test_cat_command_with_sensitive_file(self):
        """cat /etc/shadow should trigger linux_system_auth."""
        text = "cat /etc/shadow"
        pattern, _ = _find("linux_system_auth")
        assert pattern.search(text)

    def test_cp_command_with_env_file(self):
        """cp .env.local backup/ should trigger env_file."""
        text = "cp .env.local /backup/"
        pattern, _ = _find("env_file")
        assert pattern.search(text)

    def test_powershell_read_sam(self):
        """PowerShell reading SAM database should trigger windows_credentials_store."""
        text = 'Get-Content "C:\\Windows\\System32\\config\\SAM"'
        pattern, _ = _find("windows_credentials_store")
        assert pattern.search(text)

    def test_ssh_key_access(self):
        """Reading SSH private key should trigger ssh_directory."""
        text = "cat ~/.ssh/id_rsa"
        pattern, _ = _find("ssh_directory")
        assert pattern.search(text)

    def test_tool_output_contains_authorized_keys(self):
        """Tool output showing .ssh directory should match."""
        text = "ls -la /root/.ssh/\ntotal 12\ndrwx------ 2 root root 4096\n-rw------- 1 root root 1679 authorized_keys"
        # .ssh/ path should match ssh_directory pattern
        pattern, _ = _find("ssh_directory")
        assert pattern.search(text)
