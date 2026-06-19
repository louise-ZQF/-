"""置信度评分：历史长度 × 数据完整度 × 指标稳定性。"""
from __future__ import annotations

import statistics
from datetime import date, datetime
from typing import Dict, List, Optional


def compute_confidence(fund: dict, rolling_scores: List[float] = None,
                       as_of_date: date = None) -> dict:
    """计算基金评分的置信度。

    fund 字段: inception_date, nav_days, expected_days
    rolling_scores: 滚动窗口的历史综合分列表
    """
    import datetime
    if as_of_date is None:
        as_of_date = datetime.date.today()

    # 1. 历史长度分
    inception = fund.get("inception_date")
    history_years = 0
    if inception:
        try:
            inc_date = datetime.datetime.strptime(str(inception)[:10], "%Y-%m-%d").date()
            history_years = (as_of_date - inc_date).days / 365.25
        except (ValueError, TypeError):
            pass
    history_score = min(history_years / 5, 1.0)

    # 2. 数据完整度 — 封顶 100%
    nav_days = fund.get("nav_days", 0)
    expected_days = max(fund.get("expected_days", 252), 1)
    data_completeness = min(nav_days / expected_days, 1.0)

    # 3. 指标稳定性（滚动评分的标准差越小越稳定）
    metric_stability = 1.0
    if rolling_scores and len(rolling_scores) >= 3:
        import statistics
        std = statistics.stdev(rolling_scores)
        metric_stability = max(0.0, 1.0 - std / 30)  # std=30 → 0

    # 4. 数据质量惩罚
    dq = fund.get("data_quality", {})
    dq_penalty = 0
    for key in ["fee_missing", "size_missing", "inception_missing", "benchmark_approximate"]:
        if dq.get(key):
            dq_penalty += 0.1
    dq_penalty = min(dq_penalty, 0.4)

    confidence = (history_score * 0.4 + data_completeness * 0.3 + metric_stability * 0.3) * (1 - dq_penalty)

    return {
        "confidence": round(max(0, min(100, confidence * 100)), 1),
        "history_years": round(history_years, 1),
        "history_score": round(history_score * 100, 1),
        "data_completeness": round(data_completeness * 100, 1),
        "metric_stability": round(metric_stability * 100, 1),
        "dq_penalty": round(dq_penalty * 100, 1),
        "level": "高" if confidence > 0.7 else ("中" if confidence > 0.4 else "低"),
    }


def adjust_score_with_confidence(raw_score: float, confidence: float) -> float:
    """置信度调整：低置信度的基金向50分回归。

    final = 50 + (raw - 50) × confidence
    高置信度 → 评分不变，低置信度 → 向50分收缩。
    """
    return 50 + (raw_score - 50) * confidence
