"""稳健标准化：中位数+MAD、同类内部分组、异常值截断。"""
from __future__ import annotations

import statistics
from typing import Dict, List, Optional, Sequence


def mad(values: Sequence[float]) -> float:
    """Median Absolute Deviation。"""
    if len(values) < 2:
        return 0.0
    med = statistics.median(values)
    abs_devs = [abs(v - med) for v in values]
    return statistics.median(abs_devs)


def robust_zscore(values: Sequence[float]) -> List[float]:
    """稳健 z-score（中位数 + MAD）。"""
    if len(values) < 3:
        return [0.0] * len(values)
    med = statistics.median(values)
    m = mad(values)
    if m < 1e-9:
        return [0.0] * len(values)
    return [(v - med) / (1.4826 * m) for v in values]


def zscore_to_percentile(zscores: List[float]) -> List[float]:
    """z-score → 0-100 分位（截断在 [-3, 3]）。"""
    clipped = [max(-3.0, min(3.0, z)) for z in zscores]
    return [max(0.0, min(100.0, (z + 3) / 6 * 100)) for z in clipped]


def normalize_group(funds: List[dict], metric_key: str,
                    group_key: str = "group") -> List[dict]:
    """同类基金内部标准化一个指标。

    funds: [{"code":..., "group":..., metric_key: value}, ...]
    返回: 每个 fund 添加 {metric_key}_score: 0-100
    """
    # 分组
    groups: Dict[str, List[dict]] = {}
    for f in funds:
        g = f.get(group_key, "default")
        groups.setdefault(g, []).append(f)

    # 组内标准化
    for g, members in groups.items():
        values = [m[metric_key] for m in members]
        if len(values) < 3:
            for m in members:
                m[f"{metric_key}_score"] = 50.0
            continue
        zs = robust_zscore(values)
        scores = zscore_to_percentile(zs)
        for m, s in zip(members, scores):
            m[f"{metric_key}_score"] = round(s, 1)

    return funds


def normalize_funds(funds: List[dict],
                    metrics: List[str],
                    group_by: str = "peer_group") -> List[dict]:
    """对基金列表的所有指标进行同类内部标准化。

    peer_group 例如 "us_passive_index"、"cn_active_equity" 等。
    """
    for metric in metrics:
        funds = normalize_group(funds, metric, group_by)
    return funds
