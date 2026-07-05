"""risk_family taxonomy —— 单一真相与漂移守卫测试。"""
from __future__ import annotations

import re
from pathlib import Path

from app.behavior_signals.taxonomy import (
    ALL_SIGNAL_KINDS,
    FAMILIES,
    KIND_TO_FAMILY,
    UNCATEGORIZED,
    family_label,
    family_of,
    kinds_for_family,
    taxonomy_payload,
)

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "app" / "behavior_signals"


def test_registry_internal_consistency():
    family_ids = {family["id"] for family in FAMILIES}
    assert set(KIND_TO_FAMILY.values()) <= family_ids, "a kind maps to an undefined family"
    assert ALL_SIGNAL_KINDS == frozenset(KIND_TO_FAMILY), "ALL_SIGNAL_KINDS must derive from KIND_TO_FAMILY"
    assert len(family_ids) == len(FAMILIES), "family ids must be unique"
    for family_id in family_ids:
        assert kinds_for_family(family_id), f"family {family_id} has no mapped kinds"


def test_family_of_known_and_unknown():
    assert family_of("sensitive_content_exposure") == "data_exposure"
    assert family_of("tool_execution_failure") == "execution_error"
    assert family_of("unknown_usage_dominant") == "usage_cost"
    assert family_of("nonsense_kind") == UNCATEGORIZED
    assert family_of(None) == UNCATEGORIZED


def test_kinds_for_family_roundtrip():
    family_ids = {family["id"] for family in FAMILIES}
    for family_id in family_ids:
        kinds = kinds_for_family(family_id)
        assert kinds
        for kind in kinds:
            assert family_of(kind) == family_id


def test_family_label():
    assert family_label("data_exposure") == "数据泄露"
    assert family_label(UNCATEGORIZED) == "未归类"


def test_taxonomy_payload_shape():
    payload = taxonomy_payload()
    assert {family["id"] for family in payload["families"]} == {family["id"] for family in FAMILIES}
    assert payload["uncategorized"] == UNCATEGORIZED
    assert payload["kind_to_family"] == KIND_TO_FAMILY


def test_every_emitted_kind_literal_is_registered():
    """漂移守卫：包内任何 `signal_kind="..."` / `kind = "..."` 字面量都必须在 registry。

    覆盖直接赋值形式。execution.py 里 `kind = "X" if ... else "Y"` 的 else 分支
    （tool_execution_failure / tool_execution_timeout）正则只抓到头部的 X，这两个
    已注册；若将来在 else 分支引入新 kind，运行时 signal_summary 的 uncategorized
    桶会显眼暴露，作为第二道防线。
    """
    pattern = re.compile(r"\b(?:signal_kind|kind)\s*=\s*\"([a-z_]+)\"")
    found: set[str] = set()
    for py_file in PACKAGE_DIR.rglob("*.py"):
        if py_file.name == "taxonomy.py":
            continue
        found.update(pattern.findall(py_file.read_text(encoding="utf-8")))
    assert found, "expected to scan at least one emitted kind literal"
    unregistered = found - ALL_SIGNAL_KINDS
    assert not unregistered, f"emitted kinds missing from taxonomy: {sorted(unregistered)}"
