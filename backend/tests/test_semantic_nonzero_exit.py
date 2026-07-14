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


@pytest.mark.parametrize(
    "command,expected_category",
    [
        # 真正的权限变更命令应识别为 permission_change
        ("chmod 755 /etc/config/file", "permission_change"),
        ("chown root:root /etc/shadow", "permission_change"),
        ("icacls C:\\Users\\admin\\file /grant Users:F", "permission_change"),
        ("takeown /f C:\\Windows\\system32\\file", "permission_change"),
        ("Set-Acl -Path C:\\file -AclObject $acl", "permission_change"),
        ("attrib +r C:\\file.txt", "permission_change"),
        ("attrib -r C:\\file.txt", "permission_change"),
        # attrib 带标志（递归设置只读）也应识别为 permission_change
        ("attrib /s +r *.txt", "permission_change"),
        ("attrib /s /d +h C:\\folder", "permission_change"),
        # cacls/xcacls（旧版 Windows 权限修改工具）
        ("cacls file /e /p users:f", "permission_change"),
        ("xcacls file /e /p users:f", "permission_change"),
    ],
)
def test_command_category_permission_change_positive(command, expected_category):
    """真正的权限变更命令应识别为 permission_change。"""
    assert command_category(command) == expected_category


@pytest.mark.parametrize(
    "command",
    [
        # 命令文本中含 "permission" 字样但不是权限变更命令
        "Resolve-Path D:/workspace/permission-config.md",
        "Get-Content D:/docs/permissions.md | Select-String 'admin'",
        "cat permission_report.txt",
        "rg 'permission' D:/workspace/docs",
        # 命令文本中含 "type" 字样但不是 type 命令
        "Get-Content file.txt | Where-Object { $_ -match 'type' }",
        "rg '--type=md' D:/workspace",
    ],
)
def test_command_category_permission_change_no_false_positive(command):
    """含 permission/type 字样但非权限变更/非 type 命令不应被误判。

    回归：旧逻辑用 ``"permission" in lowered`` 子串匹配，会把任何文本中
    出现 "permission" 的命令误判为权限变更（如 Markdown 表头、属性名、文档路径）。
    """
    category = command_category(command)
    assert category != "permission_change", (
        f"命令 {command!r} 不应被识别为 permission_change，实际为 {category!r}"
    )


@pytest.mark.parametrize(
    "command,expected_category",
    [
        # type 命令仍应识别为 file_read
        ("type file.txt", "file_read"),
        ("type C:\\Windows\\System32\\drivers\\etc\\hosts", "file_read"),
        # get-content / cat 也应识别为 file_read
        ("Get-Content file.txt", "file_read"),
        ("cat file.txt", "file_read"),
    ],
)
def test_command_category_type_still_file_read(command, expected_category):
    """type 命令应识别为 file_read（回归：拆分 'type ' 子串匹配为词边界正则）。"""
    assert command_category(command) == expected_category


@pytest.mark.parametrize(
    "command,expected_category",
    [
        # --type= 参数不应被识别为 file_read（回归：\btype\b 会误匹配 --type=）
        ("python --type=md file.py", "shell"),
        # concat 不应被识别为 file_read（回归：'cat ' 子串匹配 'concat '）
        ("concat file1 file2", "shell"),
    ],
)
def test_command_category_file_read_no_false_positive(command, expected_category):
    """含 type/cat 子串但非 file_read 命令不应被误判。

    回归1：``\\btype\\b`` 会匹配 ``--type=md`` 中的 type（'-' 是非单词字符，形成词边界），
    收紧为 ``\\btype\\s`` 要求 type 后跟空白。

    回归2：``"cat " in lowered`` 子串匹配会误判 ``concat file1 file2``，
    收紧为 ``\\bcat\\s`` 词边界正则。
    """
    assert command_category(command) == expected_category


@pytest.mark.parametrize(
    "command,expected_category",
    [
        # 搜索 pattern 中含 "RM-06" 等含 rm/del 的标识符不应被误判为破坏性
        # 旧逻辑 \b(rm|del|erase|rmdir)\b 会匹配 "rm-06" 中的 "rm"（- 是非单词字符，形成词边界）
        ('rg -n "RM-06|命中对象|lower-grid" "output/ai-prd-kit-v2/..."', "search"),
        ('rg -n "DEL-001|delete-flag" "src/"', "search"),
        ('rg "RM-2024" .', "search"),
        # 真正的 rm/del 命令仍应为 destructive
        ("rm -rf /tmp/test", "destructive"),
        ("rm /tmp/file", "destructive"),
        ("del file.txt", "destructive"),
        ("sudo rm -rf /var/log/app", "destructive"),
    ],
)
def test_command_category_rm_in_search_pattern_not_destructive(command, expected_category):
    """搜索 pattern 中含 rm/del 标识符不应被误判为破坏性命令。

    回归：``\\b(rm|del|erase|rmdir)\\b`` 会匹配 ``"RM-06"`` 中的 ``rm``
    （``-`` 是非单词字符，``rm`` 后形成词边界）。收紧为 ``\\b(rm|del|erase|rmdir)\\b(?!\\-)``
    排除 rm 后紧跟 ``-`` 的情况（标识符常见形式，如 RM-06、del-file）。
    """
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
