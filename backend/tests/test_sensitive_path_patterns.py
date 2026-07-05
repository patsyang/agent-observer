"""敏感路径模式匹配测试：Linux/Windows/macOS/generic 路径模式与命令参数扫描。

用 parametrize 表驱动合并原本 30 个独立测试函数，覆盖相同场景。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

import pytest

from app.behavior_signals.workspace import SENSITIVE_PATH_PATTERNS


def _find(label: str):
    """Return the (Pattern, label) tuple for a given label."""
    for item in SENSITIVE_PATH_PATTERNS:
        if item[1] == label:
            return item
    assert False, f"No pattern with label {label}"


def test_patterns_structure():
    """模式导出为 list[tuple[re.Pattern, str]]，覆盖各平台与通用凭证。"""
    assert isinstance(SENSITIVE_PATH_PATTERNS, list)
    labels = set()
    for pattern, label in SENSITIVE_PATH_PATTERNS:
        assert isinstance(pattern, re.Pattern)
        assert isinstance(label, str)
        labels.add(label)
    for required in (
        "linux_system_auth",
        "linux_ssh_trust",
        "windows_credentials_store",
        "macos_keychain",
        "env_file",
        "credential_file",
        "ssh_directory",
    ):
        assert required in labels


@pytest.mark.parametrize(
    "label,should_match,should_not_match",
    [
        (
            "linux_system_auth",
            ["/etc/shadow", "/etc/passwd", "/etc/sudoers"],
            ["/etc/shadow.bak", "/etc/shadow.d/"],
        ),
        (
            "linux_ssh_trust",
            ["/root/.ssh/authorized_keys"],
            ["/root/.ssh/known_hosts"],
        ),
        (
            "windows_credentials_store",
            [
                "C:\\Windows\\System32\\config\\SAM",
                "C:\\WINDOWS\\System32\\config\\SECURITY",
                "/Windows/System32/config/SYSTEM",
                "c:\\windows\\system32\\config\\sam",
            ],
            ["C:\\Windows\\System32\\drivers\\etc\\hosts"],
        ),
        (
            "macos_keychain",
            ["Library/Keychains/db", "Library/Security/Keychain"],
            ["Library/Preferences/"],
        ),
        (
            "env_file",
            [".env", "./.env", "/some/path/.env", ".env.local", ".env.production", "/project/.env.development"],
            ["/tmp/xxx"],
        ),
        (
            "credential_file",
            [".netrc", ".credentials", ".htpasswd", ".npmrc", ".pypirc"],
            [".editorconfig", ".flake8", "/tmp/xxx"],
        ),
        (
            "ssh_directory",
            [".ssh/id_rsa", ".ssh/id_ed25519", "/home/user/.ssh/authorized_keys"],
            [".ssh_backup/id_rsa"],
        ),
    ],
)
def test_sensitive_path_match(label, should_match, should_not_match):
    """各平台/通用凭证模式应匹配敏感路径，不匹配无关路径。"""
    pattern, _ = _find(label)
    for path in should_match:
        assert pattern.search(path), f"{label} 应匹配 {path}"
    for path in should_not_match:
        assert not pattern.search(path), f"{label} 不应匹配 {path}"


@pytest.mark.parametrize(
    "text,expected_label",
    [
        # 路径分隔符归一化
        ("\\.env", "env_file"),
        ("/.env", "env_file"),
        ('copy "C:\\Users\\admin\\.env" C:\\backup\\', "env_file"),
        # 命令参数扫描
        ("cat /etc/shadow", "linux_system_auth"),
        ("cp .env.local /backup/", "env_file"),
        ('Get-Content "C:\\Windows\\System32\\config\\SAM"', "windows_credentials_store"),
        ("cat ~/.ssh/id_rsa", "ssh_directory"),
        # 工具输出多行扫描
        (
            "ls -la /root/.ssh/\ntotal 12\ndrwx------ 2 root root 4096\n-rw------- 1 root root 1679 authorized_keys",
            "ssh_directory",
        ),
    ],
)
def test_sensitive_path_in_command_or_output(text, expected_label):
    """模式应能从命令参数、工具输出、混合斜杠路径中识别敏感路径。"""
    pattern, _ = _find(expected_label)
    assert pattern.search(text), f"{expected_label} 应从文本中识别敏感路径: {text!r}"
