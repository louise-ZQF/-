"""基金重叠度过滤器。"""
from __future__ import annotations

import statistics
from typing import Dict, List, Optional


def compute_return_correlation(rets_a: List[float], rets_b: List[float]) -> Optional[float]:
    """计算两只基金的日收益相关系数。"""
    n = min(len(rets_a), len(rets_b))
    if n < 20:
        return None
    a = rets_a[-n:]
    b = rets_b[-n:]
    try:
        a_mean = statistics.mean(a)
        b_mean = statistics.mean(b)
        a_std = statistics.stdev(a)
        b_std = statistics.stdev(b)
        if a_std == 0 or b_std == 0:
            return None
        corr = sum((a[i] - a_mean) * (b[i] - b_mean) for i in range(n)) / ((n - 1) * a_std * b_std)
        return max(-1.0, min(1.0, corr))
    except Exception:
        return None


def remove_high_correlation(funds: List[dict],
                            returns_map: Dict[str, List[float]],
                            threshold: float = 0.95) -> List[dict]:
    """移除高度相关的基金，保留综合分最高的。

    funds: 基金列表（已按综合分排序）
    returns_map: {code: [日收益]}
    """
    keep = []
    for f in funds:
        code = f.get("code", "")
        frets = returns_map.get(code, [])
        is_dup = False
        for kept in keep:
            kcode = kept.get("code", "")
            krets = returns_map.get(kcode, [])
            corr = compute_return_correlation(frets, krets)
            if corr is not None and corr > threshold:
                is_dup = True
                break
        if not is_dup:
            keep.append(f)
        else:
            f["dedup_note"] = f"与{keep[-1].get('code','?')}高度相关(r>{threshold})，已去重"

    return keep
