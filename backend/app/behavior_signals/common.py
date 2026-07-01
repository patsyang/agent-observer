from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime

from app.time_ranges import window_cutoff_iso

_TRACEBACK_PATTERNS = re.compile(r"traceback|raise\s+\w+error|raise\s+\w+exception|\w*(?:Error|Exception):", re.IGNORECASE)
_IMPORT_ERROR_PATTERNS = re.compile(r"module not found|cannot import|no module named|import error|moduleNotFoundError", re.IGNORECASE)
_FILE_ERROR_PATTERNS = re.compile(r"file not found|no such file|directory not found|permission denied|fileNotFoundError|no such directory", re.IGNORECASE)
_COMMAND_CATEGORIES = {
    "test": re.compile(r"\b(pytest|vitest|jest|mocha)\b", re.IGNORECASE),
    "lint": re.compile(r"\b(tsc|eslint|prettier|mypy|flake8|ruff)\b", re.IGNORECASE),
    "build": re.compile(r"\b(npm\s+run\s+build|yarn\s+build|vite\s+build|webpack)\b", re.IGNORECASE),
}

# Expanded default key file patterns covering common project structures.
# Individual projects can override these by providing a key_file_patterns.json
# at their project root.
# Order matters: more specific patterns must come before generic ones.
FALLBACK_KEY_PATH_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(^|/)package\.json$", re.I), "Node.js 包配置"),
    (re.compile(r"(^|/)tsconfig\.json$", re.I), "TypeScript 编译配置"),
    (re.compile(r"(^|/)pyproject\.toml$", re.I), "Python 项目配置"),
    (re.compile(r"(^|/)Cargo\.toml$", re.I), "Rust 项目配置"),
    (re.compile(r"(^|/)go\.mod$", re.I), "Go 模块配置"),
    (re.compile(r"(^|/)pom\.xml$", re.I), "Java Maven 配置"),
    (re.compile(r"(^|/)build\.gradle", re.I), "Java Gradle 配置"),
    (re.compile(r"(^|/)setup\.py$", re.I), "Python 安装脚本"),
    (re.compile(r"(^|/)policy/|^stack-contract|^agentic\.lock$", re.I), "策略或发布配置"),
    (re.compile(r"(^|/).*-lock\.json$|\.lock$|\.lockb$|\.podlock$", re.I), "依赖锁文件"),
    (re.compile(r"(^|/)\.gitignore$", re.I), "项目忽略规则"),
    (re.compile(r"(^|/)\.env($|\.)", re.I), "环境变量配置"),
    (re.compile(r"(^|/)Makefile($|\.in$)", re.I), "构建入口"),
    (re.compile(r"(^|/)Dockerfile", re.I), "容器构建配置"),
    (re.compile(r"(^|/)requirements(-\w+)?\.txt$", re.I), "Python 依赖"),
    (re.compile(r"(^|/)\.github/|(^|/)\.gitlab-ci|(^|/)\.circleci|(^|/)jenkinsfile", re.I), "CI 配置"),
    (re.compile(r"db/migrations?|migration", re.I), "数据库迁移"),
    (re.compile(r"collector|collector_client", re.I), "采集器实现"),
    (re.compile(r"(^|/)workflow/|commands?/", re.I), "工作流或命令入口"),
    (re.compile(r"(^|/)policy/|^stack-contract|^agentic\.lock$", re.I), "策略或发布配置"),
]


def load_key_file_patterns(project_root: str | None = None) -> list[tuple[str, str]]:
    """Load key file patterns from project config, falling back to defaults.

    Returns a list of (regex_pattern_string, label) tuples.  The caller is
    responsible for compiling the regex strings into Pattern objects.

    If a *project_root* is provided, the function looks for
    ``{project_root}/key_file_patterns.json``.  When the file exists and
    contains valid JSON it is used; otherwise the built-in FALLBACK patterns
    are returned.

    The JSON format is::

        {
          "patterns": [
            {"pattern": "^(.*/)?Makefile$", "label": "构建入口"},
            ...
          ]
        }

    Each entry must have a ``pattern`` (valid regex string) and a ``label``
    (human-readable category name).
    """
    config_path = None
    if project_root:
        config_path = os.path.join(project_root, "key_file_patterns.json")

    if config_path and os.path.isfile(config_path):
        try:
            raw = json.loads(open(config_path, encoding="utf-8").read())
            entries = raw.get("patterns")
            if isinstance(entries, list):
                compiled: list[tuple[str, str]] = []
                for entry in entries:
                    pat_str = entry.get("pattern")
                    label = entry.get("label")
                    if isinstance(pat_str, str) and isinstance(label, str) and pat_str.strip():
                        compiled.append((pat_str.strip(), label.strip()))
                if compiled:
                    return compiled
        except (json.JSONDecodeError, OSError):
            pass
        # Config file existed but was malformed — silently fall through

    # Return compiled fallback patterns as (regex_string, label) pairs
    return [(p.pattern, label) for p, label in FALLBACK_KEY_PATH_PATTERNS]


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def loads(value: str | None) -> dict:
    try:
        return json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}


def snapshot_hash(value: dict) -> str:
    stable = {key: item for key, item in value.items() if key != "reason"}
    return hashlib.sha256(dumps(stable).encode("utf-8")).hexdigest()


def signal_id(signal_key: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", signal_key).strip("-").lower()
    return f"signal-{slug[:96]}"


def window_cutoff(window: str) -> str | None:
    return window_cutoff_iso(window)


def classify_tool_failure(reason: str, envelope_body: str) -> dict:
    """Classify a tool failure into a precise sub-type and compute priority.

    Returns a dict with keys:
      - sub_type: one of 'workflow_gate_blocked', 'validation_failure',
                  'tool_crash', 'tool_fallback'
      - priority: integer priority score
      - detail: human-readable description
    """
    # 1. Workflow gate blocked
    try:
        gate = json.loads(reason)
        if isinstance(gate, dict) and gate.get("blocked") is True:
            return {
                "sub_type": "workflow_gate_blocked",
                "priority": 30,
                "detail": "Workflow gate blocked",
            }
    except (json.JSONDecodeError, TypeError):
        pass

    # Extract a limited snippet for pattern matching (first 2000 chars)
    snippet = (envelope_body or "")[:2000]

    # 2. Validation failure (test/lint/build command failure)
    for cmd_cat, pat in _COMMAND_CATEGORIES.items():
        if pat.search(snippet):
            return {
                "sub_type": "validation_failure",
                "priority": 60,
                "detail": f"Command category: {cmd_cat}",
            }

    # 3. Tool crash (specific error patterns)
    if _IMPORT_ERROR_PATTERNS.search(snippet):
        return {
            "sub_type": "tool_crash",
            "priority": 95,
            "detail": "Import/module resolution error",
        }
    if _FILE_ERROR_PATTERNS.search(snippet):
        return {
            "sub_type": "tool_crash",
            "priority": 95,
            "detail": "File/directory not found or permission denied",
        }
    if _TRACEBACK_PATTERNS.search(snippet):
        return {
            "sub_type": "tool_crash",
            "priority": 95,
            "detail": "Runtime traceback/exception",
        }

    # 4. Fallback
    return {
        "sub_type": "tool_fallback",
        "priority": 70,
        "detail": "Unmatched failure pattern",
    }
