"""Tests for configurable key-file patterns (story-007).

Covers:
- Default fallback patterns hit expected paths
- Custom key_file_patterns.json overrides defaults
- Malformed JSON falls back to defaults
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from app.behavior_signals.common import (
    FALLBACK_KEY_PATH_PATTERNS,
    load_key_file_patterns,
)
from app.behavior_signals.helpers import key_path_label


class TestFallbackPatterns:
    """Default patterns should match common project files."""

    @pytest.mark.parametrize(
        "path,label",
        [
            (".gitignore", "项目忽略规则"),
            ("src/.gitignore", "项目忽略规则"),
            ("db/migrations/001_init.sql", "数据库迁移"),
            ("migrations/002_add_users.sql", "数据库迁移"),
            ("src/collector.py", "采集器实现"),
            ("lib/collector_client.js", "采集器实现"),
            ("workflow/steps/deploy.yaml", "工作流或命令入口"),
            ("commands/build.sh", "工作流或命令入口"),
            ("policy/release.json", "策略或发布配置"),
            ("stack-contract.json", "策略或发布配置"),
            ("agentic.lock", "策略或发布配置"),
            ("package.json", "Node.js 包配置"),
            ("frontend/package.json", "Node.js 包配置"),
            ("pyproject.toml", "Python 项目配置"),
            ("Cargo.toml", "Rust 项目配置"),
            ("go.mod", "Go 模块配置"),
            ("pom.xml", "Java Maven 配置"),
            ("build.gradle", "Java Gradle 配置"),
            ("package-lock.json", "依赖锁文件"),
            ("yarn.lock", "依赖锁文件"),
            (".env", "环境变量配置"),
            (".env.local", "环境变量配置"),
            ("Makefile", "构建入口"),
            ("Makefile.in", "构建入口"),
            ("Dockerfile", "容器构建配置"),
            ("Dockerfile.prod", "容器构建配置"),
            (".github/workflows/ci.yml", "CI 配置"),
            (".gitlab-ci.yml", "CI 配置"),
            ("tsconfig.json", "TypeScript 编译配置"),
            ("requirements.txt", "Python 依赖"),
            ("requirements-dev.txt", "Python 依赖"),
            ("setup.py", "Python 安装脚本"),
        ],
    )
    def test_fallback_hits(self, path: str, label: str) -> None:
        result = key_path_label(path)
        assert result == label, f"Expected '{label}' for '{path}', got '{result}'"

    def test_fallback_no_match(self) -> None:
        assert key_path_label("src/utils/helpers.py") == ""
        assert key_path_label("README.md") == ""
        assert key_path_label("") == ""


class TestLoadKeyFilePatterns:
    """load_key_file_patterns() returns correct pattern lists."""

    def test_default_fallback(self) -> None:
        patterns = load_key_file_patterns(None)
        assert isinstance(patterns, list)
        assert len(patterns) > 5
        for pat_str, label in patterns:
            assert isinstance(pat_str, str)
            assert isinstance(label, str)

    def test_custom_config(self, tmp_path: Path) -> None:
        config = {
            "patterns": [
                {"pattern": "^\\.myconfig$", "label": "我的配置"},
                {"pattern": "^custom/.*$", "label": "自定义路径"},
            ]
        }
        config_file = tmp_path / "key_file_patterns.json"
        config_file.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

        patterns = load_key_file_patterns(str(tmp_path))
        assert len(patterns) == 2
        assert patterns[0][0].startswith("^") and ".myconfig" in patterns[0][0]
        assert patterns[0][1] == "我的配置"
        assert patterns[1] == ("^custom/.*$", "自定义路径")

    def test_malformed_json_fallback(self, tmp_path: Path) -> None:
        config_file = tmp_path / "key_file_patterns.json"
        config_file.write_text("{broken", encoding="utf-8")

        patterns = load_key_file_patterns(str(tmp_path))
        # Should fall back to defaults
        assert len(patterns) == len(FALLBACK_KEY_PATH_PATTERNS)

    def test_empty_patterns_fallback(self, tmp_path: Path) -> None:
        config_file = tmp_path / "key_file_patterns.json"
        config_file.write_text(json.dumps({"patterns": []}), encoding="utf-8")

        patterns = load_key_file_patterns(str(tmp_path))
        # Empty patterns list -> fall back to defaults
        assert len(patterns) == len(FALLBACK_KEY_PATH_PATTERNS)

    def test_missing_fields_fallback(self, tmp_path: Path) -> None:
        config_file = tmp_path / "key_file_patterns.json"
        config_file.write_text(
            json.dumps({"patterns": [{"label": "no-pattern"}]}),
            encoding="utf-8",
        )

        patterns = load_key_file_patterns(str(tmp_path))
        # Entry missing 'pattern' -> skipped, fall back
        assert len(patterns) == len(FALLBACK_KEY_PATH_PATTERNS)

    def test_no_config_file(self, tmp_path: Path) -> None:
        patterns = load_key_file_patterns(str(tmp_path))
        assert len(patterns) == len(FALLBACK_KEY_PATH_PATTERNS)


class TestCustomOverride:
    """Custom config should override defaults for matching paths."""

    def test_custom_pattern_hits(self, tmp_path: Path) -> None:
        config = {
            "patterns": [
                {"pattern": "^myproject/.*\\.ts$", "label": "TS 源码"},
            ]
        }
        config_file = tmp_path / "key_file_patterns.json"
        config_file.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

        patterns = load_key_file_patterns(str(tmp_path))
        assert len(patterns) == 1
        assert key_path_label("myproject/src/index.ts", str(tmp_path)) == "TS 源码"
        # Paths not matching custom config should return empty (no fallback)
        assert key_path_label(".gitignore", str(tmp_path)) == ""

    def test_custom_partial_override(self, tmp_path: Path) -> None:
        config = {
            "patterns": [
                {"pattern": "^\\.gitignore$", "label": "Git 忽略"},
                {"pattern": "^Dockerfile$", "label": "Docker"},
            ]
        }
        config_file = tmp_path / "key_file_patterns.json"
        config_file.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

        assert key_path_label(".gitignore", str(tmp_path)) == "Git 忽略"
        assert key_path_label("Dockerfile", str(tmp_path)) == "Docker"
        # Non-matching paths return empty (custom config replaces defaults entirely)
        assert key_path_label("package.json", str(tmp_path)) == ""
