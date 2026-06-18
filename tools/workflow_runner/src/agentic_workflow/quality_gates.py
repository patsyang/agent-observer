from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

EMPTY_VALUES = {"", "无", "暂无", "没有", "none", "n/a", "na", "not applicable"}
PRODUCTION_SPEC_SECTIONS = (
    "Product Outcome",
    "User Roles and Production Workflows",
    "Domain Objects and States",
    "Frontend Product Surface",
    "Backend and Data Contracts",
    "Error, Empty, Partial and Recovery States",
    "Security and Privacy Boundaries",
    "Operational Concerns",
    "Release Gates",
    "Acceptance Matrix Draft",
)
PLACEHOLDER_PATTERNS = (
    r"<[^>\n]+>",
    r"说明要构建什么",
    r"说明该任务",
    r"列出 API",
    r"# example",
    r"path/to/file",
    r"验收项必须可通过",
    r"可通过命令、文件、接口响应或 UI 状态判断",
    r"\|\s*\|\s*\|\s*\|\s*\|",
)


@dataclass(frozen=True)
class GateResult:
    ok: bool
    messages: list[str]


def check_spec_artifacts(
    *,
    spec_path: Path,
    plan_path: Path | None = None,
    tasks_path: Path | None = None,
) -> GateResult:
    messages: list[str] = []
    _check_markdown_file(spec_path, "spec", messages)
    if spec_path.exists():
        spec_text = spec_path.read_text(encoding="utf-8")
        messages.extend(_placeholder_messages(spec_text, "spec"))
        messages.extend(_missing_sections(spec_text, PRODUCTION_SPEC_SECTIONS, "spec"))
        open_questions = _section_body(spec_text, "Open Questions")
        if _has_real_content(open_questions):
            messages.append("spec: 开放问题未清空，不能进入实现")
        if "stack_contract_ref" not in spec_text and "stack contract" not in spec_text.lower():
            messages.append("spec: 必须引用 stack_contract_ref 或说明 stack contract 来源")
        if not _has_acceptance_reference(spec_text):
            messages.append("spec: Acceptance Matrix Draft 必须包含验收项引用")

    if plan_path is not None:
        _check_markdown_file(plan_path, "plan", messages)
        if plan_path.exists():
            plan_text = plan_path.read_text(encoding="utf-8")
            if _contains_blocked(plan_text):
                messages.append("plan: 存在 BLOCKED，不能进入实现")

    if tasks_path is not None:
        _check_markdown_file(tasks_path, "tasks", messages)
        if tasks_path.exists():
            tasks_text = tasks_path.read_text(encoding="utf-8")
            messages.extend(_placeholder_messages(tasks_text, "tasks"))

    return GateResult(ok=not messages, messages=messages)


def format_gate_result(result: GateResult) -> str:
    if result.ok:
        return "spec gate PASS"
    lines = ["spec gate FAIL"]
    lines.extend(f"- {message}" for message in result.messages)
    return "\n".join(lines)


def _check_markdown_file(path: Path, label: str, messages: list[str]) -> None:
    if not path.exists():
        messages.append(f"{label}: 文件不存在: {path}")
    elif not path.is_file():
        messages.append(f"{label}: 路径不是文件: {path}")


def _missing_sections(text: str, required: tuple[str, ...], label: str) -> list[str]:
    headings = set(_headings(text))
    return [f"{label}: 缺少章节 ## {section}" for section in required if section not in headings]


def _headings(text: str) -> list[str]:
    result = []
    for match in re.finditer(r"^##+\s+(.+?)\s*$", text, re.M):
        heading = re.sub(r"\s+#*$", "", match.group(1).strip())
        result.append(heading)
    return result


def _section_body(text: str, section: str) -> str:
    pattern = rf"^##\s+{re.escape(section)}\s*$\n(.*?)(?=^##\s+|\Z)"
    match = re.search(pattern, text, re.M | re.S)
    return match.group(1).strip() if match else ""


def _has_real_content(value: str) -> bool:
    lines = [
        _normalize(line)
        for line in value.splitlines()
        if line.strip() and not re.match(r"^\s*\|?\s*:?-{2,}", line)
    ]
    return any(line not in EMPTY_VALUES for line in lines)


def _normalize(value: str) -> str:
    value = re.sub(r"^[\s>*#\-\[\]xX.0-9]+", "", value.strip())
    value = re.sub(r"[*_`。.:：\s]+$", "", value)
    return re.sub(r"\s+", " ", value).lower()


def _has_check_item(text: str, section: str) -> bool:
    body = _section_body(text, section)
    return bool(re.search(r"^\s*-\s+\[[ xX]\]\s+\S", body, re.M))


def _has_acceptance_reference(text: str) -> bool:
    body = _section_body(text, "Acceptance Matrix Draft")
    return bool(re.search(r"\b(AC|A)-[A-Za-z0-9_-]+\b|\bacceptance[_ -]?id\b", body, re.I))


def _contains_blocked(text: str) -> bool:
    return bool(re.search(r"\bBLOCKED\b|状态\s*[：:]\s*阻塞", text, re.I))


def _placeholder_messages(text: str, label: str) -> list[str]:
    messages = []
    for pattern in PLACEHOLDER_PATTERNS:
        if re.search(pattern, text, re.I):
            messages.append(f"{label}: 仍包含模板占位或说明性文本: {pattern}")
    return messages
