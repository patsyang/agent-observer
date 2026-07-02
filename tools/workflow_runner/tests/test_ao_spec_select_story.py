"""ao_spec_select_story helper 脚本测试。

通过子进程调用脚本，验证 story 选择、状态判定与工作包切片抽取行为，
与 implement-story 命令在运行时的真实调用方式一致。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent / "scripts" / "ao_spec_select_story.py"
)


def _run(artifacts_dir: Path, *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(artifacts_dir)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=full_env,
    )


def _write_stories(artifacts_dir: Path, stories: list[dict[str, object]]) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "stories.json").write_text(
        json.dumps(stories, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_tasks(artifacts_dir: Path, tasks: list[dict[str, object]]) -> None:
    (artifacts_dir / "tasks.json").write_text(
        json.dumps({"tasks": tasks}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _story(
    sid: str,
    priority: int,
    *,
    passes: bool = False,
    depends_on: list[str] | None = None,
    title: str = "",
    technical_notes: list[str] | None = None,
    required_evidence_paths: list[str] | None = None,
) -> dict[str, object]:
    return {
        "id": sid,
        "title": title or f"{sid} 标题",
        "user_value": f"{sid} 用户价值",
        "acceptance_ids": ["ACC-001"],
        "acceptance_criteria": ["标准 A", "测试通过"],
        "technical_notes": technical_notes or ["实现要点 A"],
        "depends_on": depends_on or [],
        "priority": priority,
        "risk": "P0",
        "required_evidence": ["单元测试"],
        "required_evidence_paths": required_evidence_paths or ["tests/test_x.py"],
        "passes": passes,
        "status": "done" if passes else "pending",
    }


def _task(
    task_id: str,
    story_id: str,
    *,
    verification_commands: list[str] | None = None,
    done_signal: str = "TASK-PASS",
    files_expected: list[str] | None = None,
    tests_required: list[str] | None = None,
    technical_notes: list[str] | None = None,
    size: str = "M",
    phase: int = 1,
) -> dict[str, object]:
    return {
        "id": task_id,
        "title": f"{task_id} 标题",
        "story_id": story_id,
        "size": size,
        "phase": phase,
        "done_signal": done_signal,
        "files_expected": files_expected or ["src/app.py"],
        "tests_required": tests_required or ["tests/test_x.py"],
        "verification_commands": verification_commands or ["pytest tests/test_x.py"],
        "technical_notes": technical_notes or ["task 要点"],
    }


def test_selects_lowest_priority_actionable_story(tmp_path: Path) -> None:
    """应选出 passes=False、依赖已满足且 priority 最小的 story。"""
    artifacts_dir = tmp_path / "artifacts"
    _write_stories(
        artifacts_dir,
        [
            _story("story-001", 1, passes=True),
            _story("story-002", 2, depends_on=["story-001"]),
            _story("story-003", 1),
        ],
    )
    result = _run(artifacts_dir)
    assert result.returncode == 0, result.stderr
    assert "STATUS: ACTIONABLE" in result.stdout
    assert "SELECTED: story-003" in result.stdout or "ID: story-003" in result.stdout
    assert "- story-003 [TODO] prio=1 deps=[]  <-- SELECTED" in result.stdout


def test_status_complete_when_all_stories_pass(tmp_path: Path) -> None:
    """所有 story passes=true 时 STATUS 为 COMPLETE。"""
    artifacts_dir = tmp_path / "artifacts"
    _write_stories(
        artifacts_dir,
        [
            _story("story-001", 1, passes=True),
            _story("story-002", 2, passes=True, depends_on=["story-001"]),
        ],
    )
    result = _run(artifacts_dir)
    assert result.returncode == 0, result.stderr
    assert "STATUS: COMPLETE" in result.stdout
    assert "STORIES_REMAINING: 0" in result.stdout


def test_status_blocked_when_dependencies_unmet(tmp_path: Path) -> None:
    """有未完成 story 但依赖未满足时 STATUS 为 BLOCKED。"""
    artifacts_dir = tmp_path / "artifacts"
    _write_stories(
        artifacts_dir,
        [
            _story("story-001", 1, passes=False),
            _story("story-002", 2, passes=False, depends_on=["story-001"]),
        ],
    )
    # story-001 可选（无依赖），story-002 依赖 story-001 未通过
    # 但 story-001 priority=1 更小，会被选中，所以 STATUS 是 ACTIONABLE
    # 改为 story-001 passes=true，story-002 依赖未完成的 story-003
    _write_stories(
        artifacts_dir,
        [
            _story("story-001", 1, passes=True),
            _story("story-002", 2, passes=False, depends_on=["story-003"]),
            _story("story-003", 1, passes=False, depends_on=["story-001"]),
        ],
    )
    # story-003 依赖 story-001（已通过）→ 可选，priority=1
    # 所以 STATUS 仍是 ACTIONABLE，选中 story-003
    # 要测 BLOCKED：让所有未完成 story 的依赖都未满足
    _write_stories(
        artifacts_dir,
        [
            _story("story-001", 1, passes=False),
            _story("story-002", 2, passes=False, depends_on=["story-001"]),
        ],
    )
    # story-001 无依赖且 passes=false → 可选，STATUS=ACTIONABLE
    # 真正的 BLOCKED：未完成的 story 都有未完成依赖
    _write_stories(
        artifacts_dir,
        [
            _story("story-001", 1, passes=False, depends_on=["story-002"]),
            _story("story-002", 2, passes=False, depends_on=["story-001"]),
        ],
    )
    result = _run(artifacts_dir)
    assert result.returncode == 0, result.stderr
    assert "STATUS: BLOCKED" in result.stdout


def test_includes_related_task_info(tmp_path: Path) -> None:
    """工作包含关联 task 的 verification_commands / done_signal / files_expected。"""
    artifacts_dir = tmp_path / "artifacts"
    _write_stories(artifacts_dir, [_story("story-001", 1)])
    _write_tasks(
        artifacts_dir,
        [
            _task(
                "TASK-001",
                "story-001",
                verification_commands=["pytest tests/test_a.py", "pytest tests/test_b.py"],
                done_signal="TASK-001-PASS",
                files_expected=["src/a.py", "src/b.py"],
                tests_required=["tests/test_a.py"],
                technical_notes=["task 要点 A"],
            ),
        ],
    )
    result = _run(artifacts_dir)
    assert result.returncode == 0, result.stderr
    assert "TASK: TASK-001" in result.stdout
    assert "done_signal: TASK-001-PASS" in result.stdout
    assert "pytest tests/test_a.py" in result.stdout
    assert "pytest tests/test_b.py" in result.stdout
    assert "src/a.py" in result.stdout
    assert "tests/test_a.py" in result.stdout
    assert "task 要点 A" in result.stdout


def test_tasks_missing_is_non_blocking(tmp_path: Path) -> None:
    """tasks.json 缺失时脚本仍能输出 story 工作包（task 信息为可选增强）。"""
    artifacts_dir = tmp_path / "artifacts"
    _write_stories(artifacts_dir, [_story("story-001", 1)])
    # 不写 tasks.json
    result = _run(artifacts_dir)
    assert result.returncode == 0, result.stderr
    assert "STATUS: ACTIONABLE" in result.stdout
    assert "ID: story-001" in result.stdout
    assert "关联 TASK：无" in result.stdout


def test_stories_json_missing_returns_nonzero(tmp_path: Path) -> None:
    """stories.json 缺失时返回非 0 退出码。"""
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    result = _run(artifacts_dir)
    assert result.returncode != 0
    assert "stories.json 不存在" in result.stderr


def test_env_var_fallback(tmp_path: Path) -> None:
    """argv 未传 artifacts_dir 时回退 AO_ARTIFACTS_DIR 环境变量。"""
    artifacts_dir = tmp_path / "artifacts"
    _write_stories(artifacts_dir, [_story("story-001", 1)])
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "AO_ARTIFACTS_DIR": str(artifacts_dir)},
    )
    assert result.returncode == 0, result.stderr
    assert "STATUS: ACTIONABLE" in result.stdout


def test_does_not_output_other_story_details(tmp_path: Path) -> None:
    """工作包只含选中 story 的明细，不输出其他 story 的 technical_notes。"""
    artifacts_dir = tmp_path / "artifacts"
    _write_stories(
        artifacts_dir,
        [
            _story(
                "story-001",
                1,
                technical_notes=["story-001 专属要点"],
                required_evidence_paths=["tests/test_s001.py"],
            ),
            _story(
                "story-002",
                2,
                depends_on=["story-001"],
                technical_notes=["story-002 专属要点"],
                required_evidence_paths=["tests/test_s002.py"],
            ),
        ],
    )
    result = _run(artifacts_dir)
    assert result.returncode == 0, result.stderr
    # story-001 被选中（priority=1）
    assert "story-001 专属要点" in result.stdout
    # story-002 的明细不应出现（只在索引里显示状态）
    assert "story-002 专属要点" not in result.stdout
    assert "tests/test_s002.py" not in result.stdout
    # 但 story-002 应在索引里
    assert "story-002 [TODO]" in result.stdout


def test_priority_fallback_for_non_int_priority(tmp_path: Path) -> None:
    """priority 非整数时按最大值排序（不崩溃）。"""
    artifacts_dir = tmp_path / "artifacts"
    _write_stories(
        artifacts_dir,
        [
            {"id": "story-x", "title": "X", "passes": False, "depends_on": [], "priority": "high"},
            {"id": "story-y", "title": "Y", "passes": False, "depends_on": [], "priority": 1},
        ],
    )
    result = _run(artifacts_dir)
    assert result.returncode == 0, result.stderr
    # story-y priority=1 应被选中
    assert "ID: story-y" in result.stdout
