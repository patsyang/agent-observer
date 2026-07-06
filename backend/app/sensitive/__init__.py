"""敏感数据识别门面 —— 全系统唯一的敏感检测入口。

调用方（ingest / collector_client / 展示层 / 回填脚本）只 import 本模块公开的函数，
永远不直接触碰 ``rules`` / ``engine`` / ``validators`` 内部。检测用哪些规则、
用什么引擎，是本包的实现细节，对外只暴露稳定契约。

公开 API：
    detect(text, *, source)
    detect_for_fact(projection_json_text, raw_content, *, source)
    object_type_from_matches(matches)
    sensitive_matches_from_text(value, evidence_key)
    sensitive_categories_from_text(value)
"""
from app.sensitive.engine import (
    detect,
    detect_for_fact,
    object_type_from_matches,
    sensitive_matches_from_text,
    sensitive_categories_from_text,
)

__all__ = [
    "detect",
    "detect_for_fact",
    "object_type_from_matches",
    "sensitive_matches_from_text",
    "sensitive_categories_from_text",
]
