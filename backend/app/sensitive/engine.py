"""敏感检测引擎：解码 → 逐规则扫描 → 去重 → 排除 → 定 confidence。

ingest 阶段 per-fact 调一次 detect_for_fact，命中即由调用方写 risk_signals +
projection.sensitive_matches。本模块吞异常（单条 fact 失败不波及 ingest 事务）。
"""
from __future__ import annotations

import json
import re
from typing import Any

from app.sensitive.rules import EXCLUSION_PATTERNS, RULES
from app.sensitive.types import SCAN_BYTE_CAP


def _matches_exclusion(value: str) -> bool:
    return any(pat.search(value) for pat in EXCLUSION_PATTERNS)


def _preview(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    if len(normalized) <= 48:
        return normalized
    return f"{normalized[:24]}...{normalized[-12:]}"


def _match_dict(rule: dict[str, Any], m: re.Match, confidence: str, source: str) -> dict[str, Any]:
    match_type = rule["match_type"]
    if rule["name"] == "authorization" and m.lastindex and m.lastindex >= 1:
        match_type = f"authorization_{m.group(1).lower()}"
    return {
        "category": rule["category"],
        "match_type": match_type,
        "confidence": confidence,
        "evidence_key": source,
        "matched_value": m.group(0)[:100],
        "matched_preview": _preview(m.group(0)),
        "reason_code": rule["reason"],
        "_span": (m.start(), m.end()),
    }


def _detect_impl(text: str, source: str) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    seen_spans: set[tuple[int, int, str]] = set()  # (start, end, category) 同 span 去重
    seen_values: set[tuple[str, str]] = set()  # (matched_value, category) 同值去重
    for rule in RULES:
        validator = rule["validator"]
        for m in rule["pattern"].finditer(text):  # finditer 多命中
            value = m.group(0)
            if validator is not None and not validator(value):  # per-match 校验，失败只丢该 match
                continue
            confidence = "low" if _matches_exclusion(value) else "high"
            span_key = (m.start(), m.end(), rule["category"])
            value_key = (value, rule["category"])
            if span_key in seen_spans:  # 同 span 同类别去重
                continue
            if value_key in seen_values:  # 同值同类别跨 span 去重
                continue
            seen_spans.add(span_key)
            seen_values.add(value_key)
            hits.append(_match_dict(rule, m, confidence, source))
    hits.sort(key=lambda h: h["_span"])
    for h in hits:
        h.pop("_span", None)
    return hits


def detect(text: str, *, source: str = "ingest") -> list[dict[str, Any]]:
    """对纯文本跑全部规则，返回 match dict 列表。

    finditer 多命中；Luhn/ISO 校验失败的单条 match 被丢弃；同 (span, category) 去重。
    任何异常都被吞掉返回空列表（避免拖垮 ingest 事务）。
    """
    if not text:
        return []
    try:
        return _detect_impl(text, source)
    except Exception:
        return []


def detect_for_fact(projection_json_text: str, raw_content: str | None, *, source: str = "ingest") -> list[dict[str, Any]]:
    """ingest 专用：拼接 projection_json + raw_content，解码、截断后扫描，只返回 high 命中。

    只取 high 是因为 risk_signal / projection.sensitive_matches 只持久化高可信命中；
    low（占位/示例/代码）不写库。

    扫描前用 _decode_for_scan 把 JSON 记录解码成可读文本（真换行）——raw_content 里
    换行被转义成字面 ``\\n``，直接扫会把 n 当成 email local-part 起始
    （``\\n15035344@qq.com`` → ``n15035344@qq.com``），并让行首装饰器
    ``@pytest.mark.asyncio`` 被误判为邮箱。解码后换行变空白，两类误判同时消失。
    """
    text = "\n".join(p for p in (projection_json_text or "", raw_content or "") if p)
    if not text:
        return []
    text = _decode_for_scan(text)
    text = text[:SCAN_BYTE_CAP]
    return [m for m in detect(text, source=source) if m["confidence"] == "high"]


def _decode_for_scan(text: str) -> str:
    """把 JSON 记录串解码为可读文本，换行还原为真换行。

    优先 json.loads 后取所有标量值（字符串 + 数字，字段间真换行分隔）；失败（多条记录
    拼接等）时，仅在文本看起来像 JSON（以 {/[/" 开头）时才反转义，否则原样返回——
    避免把非 JSON 纯文本（如 Windows 路径 C:\\Users\\new）里的反斜杠序列误破坏。
    两条路径都保证 ``\\n`` 不再以"反斜杠+n"形式进入正则。
    """
    stripped = text.lstrip()
    looks_json = stripped[:1] in ('{', '[', '"')
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        return _unescape_json_string(text) if looks_json else text
    parts: list[str] = []
    _collect_scalar_values(obj, parts)
    if parts:
        return "\n".join(parts)
    return _unescape_json_string(text) if looks_json else text


def _collect_scalar_values(obj: Any, out: list[str]) -> None:
    """递归收集字符串与数字值（数字也收，避免 {"phone": 13812345678} 漏检）。"""
    if isinstance(obj, str):
        if obj:
            out.append(obj)
    elif isinstance(obj, bool):  # bool 是 int 子类，先判；True/False 不当数字收
        return
    elif isinstance(obj, (int, float)):
        out.append(str(obj))
    elif isinstance(obj, dict):
        for value in obj.values():
            _collect_scalar_values(value, out)
    elif isinstance(obj, list):
        for value in obj:
            _collect_scalar_values(value, out)


def _unescape_json_string(text: str) -> str:
    """逐字符反转义常见 JSON 字符串转义（\\n \\t \\r \\" \\/ \\\\）。仅在文本像 JSON 时调用。"""
    return (
        text.replace("\\\\", "\x00")
        .replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace("\\r", "\r")
        .replace('\\"', '"')
        .replace("\\/", "/")
        .replace("\x00", "\\")
    )


def object_type_from_matches(matches: list[dict[str, Any]]) -> str:
    """从命中列表算 risk_signals.object_type（优先级对齐历史实现）。"""
    cats = {m["category"] for m in matches}
    if "phone" in cats:
        return "phone"
    if "email" in cats:
        return "email"
    if "id_card" in cats:
        return "id_card"
    if "bank_card" in cats:
        return "bank_card"
    if "token" in cats or "secret" in cats:
        return "credential"
    if "cookie" in cats:
        return "cookie"
    if "auth" in cats:
        return "auth"
    if cats:
        return sorted(cats)[0]
    return "sensitive_object"


def sensitive_matches_from_text(value: object, evidence_key: str = "text") -> list[dict[str, Any]]:
    """展示层/collector_client 用的便利函数：对任意文本跑 detect。"""
    return detect(str(value or ""), source=evidence_key)


def sensitive_categories_from_text(value: object) -> list[str]:
    return sorted({m["category"] for m in sensitive_matches_from_text(value)})
