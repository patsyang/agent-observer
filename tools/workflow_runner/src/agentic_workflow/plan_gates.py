from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

REQUIRED_SECTIONS = (
    "Status",
    "Input Summary",
    "Scope and Non-goals",
    "Assumptions and Open Questions",
    "Architecture and Integration Decisions",
    "Task Graph",
    "Task Details",
    "Verification Plan",
    "Acceptance Matrix",
    "Risks",
    "Stop Conditions",
)
TASK_FIELDS = (
    "ACCEPTANCE",
    "COMPONENTS",
    "FILES",
    "TESTS",
    "VERIFY",
    "DONE",
    "DEPENDS",
    "SIZE",
)


@dataclass(frozen=True)
class PlanGateResult:
    ok: bool
    messages: list[str]


def check_plan_artifact(plan_path: Path) -> PlanGateResult:
    messages: list[str] = []
    if not plan_path.exists():
        return PlanGateResult(False, [f"plan: 文件不存在: {plan_path}"])
    if not plan_path.is_file():
        return PlanGateResult(False, [f"plan: 路径不是文件: {plan_path}"])

    text = plan_path.read_text(encoding="utf-8")
    headings = set(_headings(text))
    for section in REQUIRED_SECTIONS:
        if section not in headings:
            messages.append(f"plan: 缺少章节 ## {section}")

    status = _section_body(text, "Status")
    if _contains_blocked(status):
        messages.append("plan: 状态为 BLOCKED，不能进入实现")

    task_details = _section_body(text, "Task Details")
    if not _has_task(task_details):
        messages.append("plan: Task Details 必须包含 `### Task <id>: <title>`")
    for field in TASK_FIELDS:
        if not re.search(rf"^\s*-\s+\*\*{field}\*\*[：:]", task_details, re.M):
            messages.append(f"plan: Task Details 缺少 {field} 字段")
    if not re.search(r"`[^`]+`", _section_body(text, "Verification Plan")):
        messages.append("plan: Verification Plan 必须包含具体可执行命令")
    if not re.search(r"\b(AC|A)-[A-Za-z0-9_-]+\b|\bacceptance[_ -]?id\b", _section_body(text, "Acceptance Matrix"), re.I):
        messages.append("plan: Acceptance Matrix 必须包含验收项引用")
    if re.search(r"\bXL\b|\bL\b", task_details, re.I):
        messages.append("plan: 存在过大任务，必须继续拆分")
    return PlanGateResult(not messages, messages)


def format_plan_gate_result(result: PlanGateResult) -> str:
    if result.ok:
        return "plan gate PASS"
    return "\n".join(["plan gate FAIL", *[f"- {message}" for message in result.messages]])


def _headings(text: str) -> list[str]:
    result = []
    for match in re.finditer(r"^##+\s+(.+?)\s*$", text, re.M):
        result.append(re.sub(r"\s+#*$", "", match.group(1).strip()))
    return result


def _section_body(text: str, section: str) -> str:
    pattern = rf"^##\s+{re.escape(section)}\s*$\n(.*?)(?=^##\s+|\Z)"
    match = re.search(pattern, text, re.M | re.S)
    return match.group(1).strip() if match else ""


def _contains_blocked(text: str) -> bool:
    return bool(re.search(r"\bBLOCKED\b|状态\s*[：:]\s*阻塞", text, re.I))


def _has_task(text: str) -> bool:
    return bool(re.search(r"^###\s+Task\s+\S+[:：]\s+.+$", text, re.M | re.I))
