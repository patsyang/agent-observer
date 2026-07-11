"""语义性非零退出码测试：search/git 等命令的 exit 1 不应被误判为工具执行失败。"""
from __future__ import annotations

import json

import pytest

from app.collector_client.telemetry import collect_facts
from app.collector_client.telemetry_utils import (
    SEMANTIC_NONZERO_EXIT,
    is_semantic_nonzero_exit,
    command_category,
)


# --- is_semantic_nonzero_exit 单元测试 ---


@pytest.mark.parametrize(
    "category,exit_code,expected",
    [
        # search 类：exit 1 是语义结果
        ("search", 1, True),
        ("search", 2, False),
        ("search", 0, False),
        # git 类：exit 1 是语义结果
        ("git", 1, True),
        ("git", 2, False),
        # 其他类别没有语义性退出码
        ("shell", 1, False),
        ("test", 1, False),
        ("build", 1, False),
        ("destructive", 1, False),
        # 空字符串
        ("", 1, False),
    ],
)
def test_is_semantic_nonzero_exit(category, exit_code, expected):
    assert is_semantic_nonzero_exit(category, exit_code) is expected


def test_semantic_nonzero_exit_registry_has_expected_categories():
    """SEMANTIC_NONZERO_EXIT 至少覆盖 search 和 git。"""
    assert "search" in SEMANTIC_NONZERO_EXIT
    assert "git" in SEMANTIC_NONZERO_EXIT
    assert 1 in SEMANTIC_NONZERO_EXIT["search"]
    assert 1 in SEMANTIC_NONZERO_EXIT["git"]


@pytest.mark.parametrize(
    "command,expected_category",
    [
        ("rg -n -F 'test-pattern' file1.md file2.html", "search"),
        ("rg --files -g package.json -g tsconfig.json", "search"),
        ("findstr /s 'pattern' *.txt", "search"),
        ("Get-ChildItem | Select-String 'pattern'", "search"),
        ("git diff --stat", "git"),
        ("git status", "git"),
        ("tsc --noEmit", "build"),
        ("npx tsc", "build"),
    ],
)
def test_command_category_search_and_git(command, expected_category):
    """command_category 应正确识别 search 和 git 类命令。"""
    assert command_category(command) == expected_category


# --- 端到端测试：rg exit 1 不应产生 tool_execution_failure ---


def _rg_call_record(call_id: str, search_term: str = "test-pattern") -> dict:
    return {
        "timestamp": "2026-07-10T10:00:00.000Z",
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "name": "shell_command",
            "call_id": call_id,
            "arguments": json.dumps(
                {
                    "command": f"rg -n -F '{search_term}' 'D:/workspace/some_file.md'",
                    "workdir": "D:/workspace",
                }
            ),
        },
    }


def _rg_output_record(call_id: str, exit_code: int = 1) -> dict:
    output_body = "" if exit_code == 1 else "3:some matching line\n"
    return {
        "timestamp": "2026-07-10T10:00:01.000Z",
        "type": "response_item",
        "payload": {
            "type": "function_call_output",
            "call_id": call_id,
            "output": f"Process exited with code {exit_code}\nWall time: 0.2 seconds\nOutput:\n{output_body}",
        },
    }


def test_rg_no_match_not_reported_as_error(tmp_path):
    """rg 搜索无匹配（exit 1）不应被判定为 tool_execution_failure。"""
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    records = [
        _rg_call_record("call-rg-001"),
        _rg_output_record("call-rg-001", exit_code=1),
    ]
    (sessions / "rg-session.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records), encoding="utf-8"
    )

    facts = collect_facts("collector-test", 1, "codex_local", codex_home=codex_home)
    error_facts = [f for f in facts if f.get("category") == "tool_execution_failure"]
    tool_facts = [f for f in facts if f.get("fact_type") == "tool"]

    assert len(error_facts) == 0, f"rg no-match 应不产生 tool_execution_failure，但产生了 {len(error_facts)} 条"
    assert len(tool_facts) >= 1, "rg no-match 应产生普通 tool fact（而非 error fact）"


def test_rg_match_reported_as_tool(tmp_path):
    """rg 搜索有匹配（exit 0）应正常产生 tool fact。"""
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    records = [
        _rg_call_record("call-rg-002"),
        _rg_output_record("call-rg-002", exit_code=0),
    ]
    (sessions / "rg-session2.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records), encoding="utf-8"
    )

    facts = collect_facts("collector-test", 1, "codex_local", codex_home=codex_home)
    error_facts = [f for f in facts if f.get("category") == "tool_execution_failure"]

    assert len(error_facts) == 0, "rg 有匹配不应产生 error fact"


def test_rg_real_error_still_reported(tmp_path):
    """rg 执行错误（exit 2）仍应被判定为 tool_execution_failure。"""
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    records = [
        _rg_call_record("call-rg-003"),
        _rg_output_record("call-rg-003", exit_code=2),
    ]
    (sessions / "rg-session3.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records), encoding="utf-8"
    )

    facts = collect_facts("collector-test", 1, "codex_local", codex_home=codex_home)
    error_facts = [f for f in facts if f.get("category") == "tool_execution_failure"]

    assert len(error_facts) >= 1, "rg exit 2（真正错误）应产生 tool_execution_failure"


def test_git_diff_no_change_not_reported_as_error(tmp_path):
    """git diff 无差异（exit 1）不应被判定为 tool_execution_failure。"""
    codex_home = tmp_path / ".codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)

    call_record = {
        "timestamp": "2026-07-10T11:00:00.000Z",
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "name": "shell_command",
            "call_id": "call-git-001",
            "arguments": json.dumps(
                {
                    "command": "git diff --stat HEAD~1",
                    "workdir": "D:/workspace",
                }
            ),
        },
    }
    output_record = {
        "timestamp": "2026-07-10T11:00:01.000Z",
        "type": "response_item",
        "payload": {
            "type": "function_call_output",
            "call_id": "call-git-001",
            "output": "Process exited with code 1\nWall time: 0.1 seconds\nOutput:\n",
        },
    }

    (sessions / "git-session.jsonl").write_text(
        "\n".join(json.dumps(r) for r in [call_record, output_record]), encoding="utf-8"
    )

    facts = collect_facts("collector-test", 1, "codex_local", codex_home=codex_home)
    error_facts = [f for f in facts if f.get("category") == "tool_execution_failure"]

    assert len(error_facts) == 0, "git diff 无差异（exit 1）不应产生 tool_execution_failure"
