"""分段百分位计算。

策略（对标 plan v3.1 §5.4 审查 I4 修正）：
- n < 20: 不返回百分位（小样本失真），返回 0，前端标灰
- n >= 20: 使用 nearest-rank 方法（排序后取 ceil(p/100*n) 位置）
  - 与 SQL NTILE(100) 在大样本下收敛，但小样本不会退化成 P95=P100
"""
from __future__ import annotations

import math


def compute_percentiles(
    values: list[float],
    percentiles: tuple[int, ...] = (50, 95, 99),
) -> dict[int, float]:
    """计算百分位，n < 20 时返回 0。"""
    n = len(values)
    if n < 20:
        return {p: 0.0 for p in percentiles}
    sorted_values = sorted(values)
    result: dict[int, float] = {}
    for p in percentiles:
        rank = math.ceil(p / 100 * n)
        rank = max(1, min(n, rank))
        result[p] = sorted_values[rank - 1]
    return result


def safe_avg(values: list[float]) -> float:
    """安全平均值，空列表返回 0。"""
    if not values:
        return 0.0
    return sum(values) / len(values)


def safe_max(values: list[float]) -> float:
    """安全最大值，空列表返回 0。"""
    if not values:
        return 0.0
    return max(values)