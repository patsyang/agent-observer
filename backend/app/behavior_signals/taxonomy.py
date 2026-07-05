"""risk_family 分类 registry —— 风险分类的单一真相。

设计要点
--------
* ``risk_family`` 是后端领域实体（让前端不再自行组合过滤、支持服务端 ``GROUP BY``），
  但**不是持久化 DB 列**：family 在读取时由 ``signal_kind`` 经本 registry 计算。
  好处：零迁移、零回填；改一行映射，全历史信号立即重归类。
* ``KIND_TO_FAMILY`` 是唯一来源；``ALL_SIGNAL_KINDS`` 由它派生。
* 未知 ``signal_kind`` → ``UNCATEGORIZED``（"未归类"），前端显眼暴露；
  ``tests/test_risk_taxonomy.py`` 源码扫描守卫保证 builder 不会发射未登记的 kind。
* 新增第 5 类（如 governance）只需：在 ``FAMILIES`` 加一项 + 在 ``KIND_TO_FAMILY``
  把对应 kind 映射过去（前提是该 kind 已被某个 builder 发射）。
"""
from __future__ import annotations

# 4 个风险分类，按展示顺序排列。severity_anchor 是该类的代表性严重度，
# 仅供前端做语义高亮，不参与过滤。
FAMILIES: list[dict] = [
    {
        "id": "data_exposure",
        "label": "数据泄露",
        "description": "敏感内容进入会话上下文，需确认是否符合最小暴露原则。",
        "order": 1,
        "severity_anchor": "high",
    },
    {
        "id": "behavior_anomaly",
        "label": "行为异常",
        "description": "破坏性操作、变更越界、关键文件改动、卡循环、重复犯错等行为模式异常。",
        "order": 2,
        "severity_anchor": "high",
    },
    {
        "id": "execution_error",
        "label": "执行错误",
        "description": "工具或 Workflow 步骤失败、超时（含校验/门禁子分类）。",
        "order": 3,
        "severity_anchor": "medium",
    },
    {
        "id": "usage_cost",
        "label": "用量成本",
        "description": "用量突增、缓存命中率低、未知活动主导等用量成本异常。",
        "order": 4,
        "severity_anchor": "medium",
    },
]

# kind → family 的唯一映射。新增 signal_kind 必须在此登记，否则
# test_risk_taxonomy.py 的源码扫描守卫会失败。
KIND_TO_FAMILY: dict[str, str] = {
    "sensitive_content_exposure": "data_exposure",
    "destructive_operation_attempt": "behavior_anomaly",
    "change_volume_anomaly": "behavior_anomaly",
    "key_file_change": "behavior_anomaly",
    "agent_loop_stuck": "behavior_anomaly",
    "repeated_tool_failure": "behavior_anomaly",
    "tool_execution_failure": "execution_error",
    "tool_execution_timeout": "execution_error",
    "workflow_step_failure": "execution_error",
    "workflow_step_timeout": "execution_error",
    "usage_spike": "usage_cost",
    "low_cache_hit_rate": "usage_cost",
    "unknown_usage_dominant": "usage_cost",
}

ALL_SIGNAL_KINDS: frozenset[str] = frozenset(KIND_TO_FAMILY)

UNCATEGORIZED = "uncategorized"

_FAMILY_BY_ID: dict[str, dict] = {family["id"]: family for family in FAMILIES}


def family_of(kind: str | None) -> str:
    """Return the family id for a signal_kind, or ``UNCATEGORIZED`` if unmapped."""
    if not kind:
        return UNCATEGORIZED
    return KIND_TO_FAMILY.get(kind, UNCATEGORIZED)


def kinds_for_family(family: str) -> list[str]:
    """Return the signal_kind values that roll up to ``family``.

    Used to translate a family filter into a SQL ``signal_kind IN (...)`` clause.
    """
    if family == UNCATEGORIZED:
        return [kind for kind in ALL_SIGNAL_KINDS if kind not in KIND_TO_FAMILY]
    return [kind for kind, fam in KIND_TO_FAMILY.items() if fam == family]


def family_label(family: str) -> str:
    if family == UNCATEGORIZED:
        return "未归类"
    meta = _FAMILY_BY_ID.get(family)
    return meta["label"] if meta else family


def family_meta(family: str) -> dict | None:
    """Return the full family descriptor, or None for an unknown family id."""
    if family == UNCATEGORIZED:
        return {
            "id": UNCATEGORIZED,
            "label": "未归类",
            "description": "尚未登记到任何风险分类的信号，需补登 taxonomy。",
            "order": 999,
            "severity_anchor": None,
        }
    return _FAMILY_BY_ID.get(family)


def taxonomy_payload() -> dict:
    """Serialize the registry for ``GET /api/risk-taxonomy``."""
    return {
        "families": [dict(family) for family in FAMILIES],
        "kind_to_family": dict(KIND_TO_FAMILY),
        "uncategorized": UNCATEGORIZED,
    }
