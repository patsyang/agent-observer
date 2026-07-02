"""为 spec-driven implement-story-loop 节点做选择性加载：选出下一个可执行 story 并打印工作包。

每轮迭代由 implement-story 命令在 shell 中调用本脚本，输出只含"当前 story 切片 +
关联 task + 验证命令 + story 索引"，使 agent 无需全量读取 stories.json /
tasks.json / production-spec.md / project-inspection.json 等大文件，从而压缩每轮
驻留上下文，避免单 session context 累积超限。

设计参考 sw-factory 的 archon_ralph_select_story.py：脚本只读，不修改任何状态文件，
不产生提交。任何错误（参数缺失、stories.json 不存在或解析失败）以非 0 退出码返回，
由命令侧回退到直接读文件，保证零回归。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _force_utf8_streams() -> None:
    """强制 stdout/stderr 以 UTF-8 输出，避免在 GBK 等非 UTF-8 终端下破坏工作包中文。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def main(argv: list[str]) -> int:
    """解析 stories.json + tasks.json，选出下一个可执行 story，打印工作包到 stdout。"""
    _force_utf8_streams()
    artifacts_dir = _resolve_artifacts_dir(argv)
    if artifacts_dir is None:
        print(
            "用法: ao_spec_select_story.py <artifacts_dir>（或设置环境变量 AO_ARTIFACTS_DIR）",
            file=sys.stderr,
        )
        return 2

    stories_path = artifacts_dir / "stories.json"
    if not stories_path.exists():
        print(f"stories.json 不存在: {stories_path}", file=sys.stderr)
        return 1

    try:
        stories = json.loads(stories_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as error:
        print(f"stories.json 解析失败: {error}", file=sys.stderr)
        return 1
    if not isinstance(stories, list):
        print("stories.json 顶层必须是数组", file=sys.stderr)
        return 1

    tasks = _load_tasks(artifacts_dir / "tasks.json")

    total = len(stories)
    done_ids = {_story_id(s) for s in stories if s.get("passes")}
    remaining = total - len(done_ids)

    selected = _select_story(stories, done_ids)
    if remaining == 0:
        status = "COMPLETE"
    elif selected is None:
        status = "BLOCKED"
    else:
        status = "ACTIONABLE"

    print(
        _render_packet(
            status=status,
            selected=selected,
            total=total,
            done=len(done_ids),
            remaining=remaining,
            stories=stories,
            done_ids=done_ids,
            tasks=tasks,
        )
    )
    return 0


def _resolve_artifacts_dir(argv: list[str]) -> Path | None:
    """优先使用 argv[1]；缺省时回退环境变量 AO_ARTIFACTS_DIR。"""
    if len(argv) >= 2 and argv[1].strip():
        return Path(argv[1])
    env_dir = os.environ.get("AO_ARTIFACTS_DIR")
    if env_dir:
        return Path(env_dir)
    return None


def _load_tasks(path: Path) -> list[dict[str, Any]]:
    """读取 tasks.json；缺失或格式错误时返回空列表（非阻塞，task 信息为可选增强）。"""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, dict):
        tasks = data.get("tasks")
        if isinstance(tasks, list):
            return [item for item in tasks if isinstance(item, dict)]
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _story_id(story: dict[str, Any]) -> str:
    value = story.get("id")
    return value if isinstance(value, str) else ""


def _depends_on(story: dict[str, Any]) -> list[str]:
    value = story.get("depends_on")
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _priority(story: dict[str, Any]) -> int:
    value = story.get("priority")
    return value if isinstance(value, int) else 1_000_000


def _select_story(
    stories: list[dict[str, Any]], done_ids: set[str]
) -> dict[str, Any] | None:
    """选 passes==False 且依赖全部已完成、priority 最小的 story。"""
    candidates = [
        story
        for story in stories
        if not story.get("passes") and set(_depends_on(story)) <= done_ids
    ]
    if not candidates:
        return None
    return min(candidates, key=_priority)


def _tasks_for_story(tasks: list[dict[str, Any]], story_id: str) -> list[dict[str, Any]]:
    """返回绑定到指定 story 的所有 task（task.story_id == story_id）。"""
    return [task for task in tasks if task.get("story_id") == story_id]


def _render_packet(
    *,
    status: str,
    selected: dict[str, Any] | None,
    total: int,
    done: int,
    remaining: int,
    stories: list[dict[str, Any]],
    done_ids: set[str],
    tasks: list[dict[str, Any]],
) -> str:
    """组装面向 agent 的紧凑工作包文本。"""
    lines: list[str] = [
        "=== AO-SPEC STORY WORK PACKET ===",
        f"STATUS: {status}",
        f"STORIES_TOTAL: {total}",
        f"STORIES_DONE: {done}",
        f"STORIES_REMAINING: {remaining}",
    ]

    if selected is not None:
        sid = _story_id(selected)
        lines += [
            "",
            "--- 当前 STORY ---",
            f"ID: {sid}",
            f"TITLE: {selected.get('title', '')}",
            f"PRIORITY: {_priority(selected)}",
            f"DEPENDS_ON: {', '.join(_depends_on(selected)) or '-'}",
            f"RISK: {selected.get('risk', '')}",
            f"USER_VALUE: {selected.get('user_value', '')}",
            f"ACCEPTANCE_IDS: {', '.join(selected.get('acceptance_ids') or []) or '-'}",
            "ACCEPTANCE_CRITERIA:",
            *(_bullet_list(selected.get("acceptance_criteria"))),
            "TECHNICAL_NOTES:",
            *(_bullet_list(selected.get("technical_notes"))),
            "REQUIRED_EVIDENCE:",
            *(_bullet_list(selected.get("required_evidence"))),
            "REQUIRED_EVIDENCE_PATHS:",
            *(_bullet_list(selected.get("required_evidence_paths"))),
        ]

        related = _tasks_for_story(tasks, sid)
        if related:
            lines += ["", "--- 关联 TASK（验证命令与完成信号） ---"]
            for task in related:
                lines += [
                    f"TASK: {task.get('id', '')} | size={task.get('size', '')} | phase={task.get('phase', '')}",
                    f"  done_signal: {task.get('done_signal', '')}",
                    f"  files_expected: {', '.join(task.get('files_expected') or []) or '-'}",
                    f"  tests_required: {', '.join(task.get('tests_required') or []) or '-'}",
                    "  verification_commands:",
                    *(f"    - {cmd}" for cmd in (task.get("verification_commands") or [])),
                    "  task_technical_notes:",
                    *(f"    - {note}" for note in (task.get("technical_notes") or [])),
                ]
        else:
            lines += ["", "--- 关联 TASK：无（tasks.json 未提供或无匹配） ---"]

    lines += [
        "",
        "--- STORY 索引（依赖核对用，仅状态） ---",
    ]
    selected_id = _story_id(selected) if selected else ""
    for story in stories:
        sid = _story_id(story)
        mark = "PASS" if story.get("passes") else "TODO"
        deps = ", ".join(_depends_on(story))
        suffix = "  <-- SELECTED" if sid and sid == selected_id else ""
        lines.append(
            f"- {sid} [{mark}] prio={_priority(story)} deps=[{deps}]{suffix}"
        )

    return "\n".join(lines)


def _bullet_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["- (无)"]
    items = [item for item in value if isinstance(item, str) and item.strip()]
    if not items:
        return ["- (无)"]
    return [f"- {item}" for item in items]


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
