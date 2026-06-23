from __future__ import annotations

from typing import Any


UNIT_BASIS = "non_cached_input_plus_output"


def normalized_usage_projection(
    *,
    activity_tag: str,
    input_tokens: object = 0,
    output_tokens: object = 0,
    total_tokens: object = 0,
    cached_input_tokens: object = 0,
    cache_write_input_tokens: object = 0,
    reasoning_output_tokens: object = 0,
    model: object = "",
    provider: object = "",
    credit: object = 0,
    cache_observed: bool | None = None,
    raw_usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    input_value = _int(input_tokens)
    output_value = _int(output_tokens)
    total_value = _int(total_tokens)
    cached_value = _int(cached_input_tokens)
    cache_write_value = _int(cache_write_input_tokens)
    reasoning_value = _int(reasoning_output_tokens)
    has_split = input_value > 0 or output_value > 0
    units = max(0, input_value - cached_value) + output_value if has_split else total_value
    observed = bool(cache_observed) if cache_observed is not None else has_split
    projection: dict[str, Any] = {
        "units": units,
        "activity_tag": activity_tag,
        "input_tokens": input_value,
        "output_tokens": output_value,
        "total_tokens": total_value or input_value + output_value,
        "cached_input_tokens": cached_value,
        "cache_write_input_tokens": cache_write_value,
        "reasoning_output_tokens": reasoning_value,
        "model": str(model or ""),
        "provider": str(provider or ""),
        "credit": _float(credit),
        "unit_basis": UNIT_BASIS,
        "observability_level": "full" if has_split else "total_only",
        "cache_observed": observed and has_split,
    }
    if raw_usage:
        projection["raw_usage"] = raw_usage
    return projection


def usage_signal_from_projection(
    projection: dict[str, Any],
    *,
    scope: str,
    session_id: str,
    conversation_id: str,
    project_ref: str,
    account_ref: str = "local",
) -> dict[str, Any]:
    return {
        "scope": scope,
        "units": _int(projection.get("units")),
        "activity_tag": str(projection.get("activity_tag") or "unknown"),
        "session_id": session_id or "unknown",
        "conversation_id": conversation_id or "unknown",
        "project_ref": project_ref or "unknown",
        "account_ref": account_ref or "local",
        "input_tokens": _int(projection.get("input_tokens")),
        "output_tokens": _int(projection.get("output_tokens")),
        "total_tokens": _int(projection.get("total_tokens")),
        "cached_input_tokens": _int(projection.get("cached_input_tokens")),
        "cache_write_input_tokens": _int(projection.get("cache_write_input_tokens")),
        "reasoning_output_tokens": _int(projection.get("reasoning_output_tokens")),
        "model": str(projection.get("model") or ""),
        "provider": str(projection.get("provider") or ""),
        "credit": _float(projection.get("credit")),
        "unit_basis": str(projection.get("unit_basis") or UNIT_BASIS),
        "observability_level": str(projection.get("observability_level") or "total_only"),
        "cache_observed": bool(projection.get("cache_observed")),
    }


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
