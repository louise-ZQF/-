"""基金评分器：被动指数基金评分 + 主动权益基金评分。

两个独立模型，不混用。所有指标在同类基金内部标准化后进入评分。
"""
from __future__ import annotations

from typing import Dict, List, Optional


# ============================================================================
# 被动指数基金评分（100分）
# ============================================================================

PASSIVE_WEIGHTS = {
    "tracking_quality": 40,    # 跟踪差异 + 跟踪误差 + Beta + R²
    "cost": 20,                # 费率越低越好
    "stability": 15,           # 规模 + 成立时间 + 净值完整性
    "tradability": 10,         # 申购状态 + 限额
    "tracking_stability": 10,  # 滚动跟踪误差波动
    "structure": 5,            # 产品结构（直投/ETF联接/FOF）
}


def score_passive_index(fund: dict, tracking_metrics: dict) -> dict:
    """被动指数基金评分。fund 需包含: annual_fee, fund_size, inception_date, purchase_status。
    tracking_metrics 来自 benchmark_mapper.compute_tracking_metrics。
    """

    if not tracking_metrics:
        return {
            "model": "passive_index",
            "scores": {},
            "composite": 0,
            "risks": ["缺少基准对齐数据，无法评分"],
            "data_missing": True,
        }

    scores = {}

    # ---- 1. 跟踪质量 (40分) ----
    tg = tracking_metrics or {}
    te = tg.get("tracking_error")
    if te is None:
        return {
            "model": "passive_index",
            "composite": 0,
            "risks": ["跟踪误差数据缺失"],
            "data_missing": True,
        }
    td = tg.get("tracking_diff", -0.01)      # 跟踪差异（年化）
    beta = tg.get("beta", 1.0)
    r2 = tg.get("r_squared", 0.9)

    # 跟踪误差：越小越好。TE ≤ 0.02 → 100分，TE ≥ 0.10 → 0分
    te_score = max(0, min(100, (0.10 - te) / 0.08 * 100))

    # 跟踪差异稳定性：越接近稳定负值（费用损耗）越好
    td_expected = -fund.get("annual_fee", 0.006)  # 预期费用损耗
    td_deviation = abs(abs(td) - abs(td_expected))
    td_score = max(0, min(100, (0.02 - td_deviation) / 0.02 * 100))

    # Beta：越接近1越好
    beta_score = max(0, min(100, (0.15 - min(abs(beta - 1), 0.15)) / 0.15 * 100))

    # R²：越高越好
    r2_score = max(0, min(100, r2 * 100)) if r2 else 50

    scores["tracking_quality"] = round(
        te_score * 0.35 + td_score * 0.25 + beta_score * 0.20 + r2_score * 0.20, 1
    )

    # ---- 2. 成本 (20分) ----
    fee = fund.get("annual_fee")
    if fee is None:
        scores["cost"] = 50  # neutral, data missing
        fund.setdefault("data_quality", {})["fee_missing"] = True
    else:
        # 费率越低越好。fee ≤ 0.2% → 100，fee ≥ 2% → 0
        scores["cost"] = round(max(0, min(100, (0.02 - fee) / 0.018 * 100)), 1)

    # ---- 3. 运行稳定性 (15分) ----
    size = fund.get("fund_size")
    if size is None:
        size_score = 50  # neutral, data missing
        fund.setdefault("data_quality", {})["size_missing"] = True
    else:
        # 规模：2亿-200亿适合。太小清盘风险，太大不好管
        if size < 2e8:
            size_score = size / 2e8 * 50  # 0-50
        elif size < 5e9:
            size_score = 80  # 最佳区间
        elif size < 2e10:
            size_score = 70
        else:
            size_score = 50  # 太大
    scores["stability"] = round(size_score * 0.6 + 40, 1)  # 基础分40

    # ---- 4. 交易条件 (10分) ----
    status = fund.get("purchase_status", "open")
    limit = fund.get("daily_purchase_limit", 0)
    if status == "suspended":
        tradability = 0
    elif limit > 0 and limit < 10000:
        tradability = 30  # 限额太严
    elif limit > 0 and limit < 100000:
        tradability = 60
    else:
        tradability = 100
    scores["tradability"] = tradability

    # ---- 5. 跟踪稳定性 (10分) ----
    # 简化为：R²足够高就稳定
    scores["tracking_stability"] = min(100, r2_score * 1.2) if r2 else 50

    # ---- 6. 产品结构 (5分) ----
    name = fund.get("name", "")
    if "etf联接" in name.lower():
        structure = 85  # ETF联接次优
    elif "etf" in name.lower():
        structure = 90
    elif "fof" in name.lower():
        structure = 60  # FOF多一层费用
    else:
        structure = 75  # QDII直投
    scores["structure"] = structure

    # ---- 加权综合 ----
    composite = sum(
        scores[k] * PASSIVE_WEIGHTS[k] / 100
        for k in PASSIVE_WEIGHTS
    )

    return {
        "model": "passive_index",
        "scores": {k: round(v, 1) for k, v in scores.items()},
        "composite": round(composite, 1),
        "weights": PASSIVE_WEIGHTS,
    }


# ============================================================================
# 池内百分位标准化工具
# ============================================================================

def _pool_percentile(values: List[float], higher_better: bool = True) -> List[float]:
    """池内百分位 → 0-100 分。"""
    if not values or len(values) < 3:
        return [50.0] * len(values)

    # Sort and compute rank percentile
    indexed = sorted(enumerate(values), key=lambda x: x[1])
    n = len(indexed)
    scores = [0.0] * n
    for rank, (orig_idx, _) in enumerate(indexed):
        pct = rank / (n - 1)  # 0 to 1
        if not higher_better:
            pct = 1 - pct
        scores[orig_idx] = round(pct * 100, 1)
    return scores


# ============================================================================
# 主动权益基金评分（100分）
# ============================================================================

ACTIVE_WEIGHTS = {
    "benchmark_adj_return": 40,  # 超额收益 + 信息比率 + Alpha
    "downside_control": 30,      # 最大回撤 + 下行捕获率 + Sortino
    "consistency": 20,           # 滚动排名稳定性 + 正超额月份比例
    "manager_style": 10,         # 任职时间 + 风格漂移
    # cost/operational 数据不可用，权重已重分配
}


def score_active_equity(fund: dict, tracking_metrics: dict,
                        fund_rets: List[float], bench_rets: List[float]) -> dict:
    """主动权益基金评分。"""
    import math, statistics

    scores = {}
    tg = tracking_metrics or {}
    n = len(fund_rets) if fund_rets else 0

    # ---- 1. 基准调整后收益 (30分) ----
    # 信息比率
    ir = tg.get("info_ratio", 0)
    # 原始值，由 screen_funds_v2 做池内百分位标准化
    ir_score = ir  # raw, will be normalized in pool

    # 超额收益（年化）
    alpha = tg.get("alpha", 0)
    # 原始值，由 screen_funds_v2 做池内百分位标准化
    alpha_score = alpha  # raw, will be normalized in pool

    scores["benchmark_adj_return"] = round(ir_score * 0.5 + alpha_score * 0.5, 1)

    # ---- 2. 下行风险控制 (20分) ----
    # 下行捕获率
    if fund_rets and bench_rets and n >= 12:
        down_months_fund = []
        down_months_bench = []
        for i in range(min(n, len(bench_rets))):
            if bench_rets[i] < 0:
                down_months_fund.append(fund_rets[i])
                down_months_bench.append(bench_rets[i])
        if down_months_bench:
            down_capture = abs(statistics.mean(down_months_fund) / max(abs(statistics.mean(down_months_bench)), 0.001))
            dc_score = max(0, min(100, (1.5 - down_capture) / 1.0 * 100))
        else:
            dc_score = 60
    else:
        dc_score = 50

    # Sortino（简化：用下行标准差）
    if n >= 12:
        downs = [min(r, 0) ** 2 for r in fund_rets]
        sortino = sum(fund_rets) / n * 252 / max(math.sqrt(sum(downs)/n)*math.sqrt(252), 0.001)
        sortino_score = max(0, min(100, 50 + sortino * 20))
    else:
        sortino_score = 50

    # 最大回撤 — 基于真实净值计算
    from . import indicators as ind
    max_dd = 0
    navs_for_dd = fund.get("navs", [])
    if navs_for_dd and len(navs_for_dd) > 1:
        peak = navs_for_dd[0]
        for nav in navs_for_dd:
            if nav > peak: peak = nav
            dd = (nav - peak) / peak
            if dd < max_dd: max_dd = dd
        md_score = max(0, min(100, (0.5 + max_dd) / 0.5 * 100))
    else:
        md_score = None
    if md_score is not None:
        scores["downside_control"] = round(dc_score * 0.35 + sortino_score * 0.35 + md_score * 0.3, 1)
    else:
        scores["downside_control"] = round(dc_score * 0.5 + sortino_score * 0.5, 1)

    # ---- 3. 业绩稳定性 (20分) ----
    # 正超额月份比例
    if fund_rets and bench_rets and n >= 12:
        pos_months = sum(1 for i in range(min(n, len(bench_rets))) if fund_rets[i] > bench_rets[i])
        win_rate = pos_months / min(n, len(bench_rets))
        consistency_score = win_rate * 100
    else:
        consistency_score = 50
    scores["consistency"] = round(consistency_score, 1)

    # ---- 4. 基金经理与风格 (10分) ----
    mgr_years = fund.get("manager_years", 0)
    if mgr_years > 0:
        scores["manager_style"] = min(100, mgr_years * 20)
    else:
        scores["manager_style"] = 50

    # cost/operational 数据不可用，不参与评分（权重已重分配）

    # ---- 加权综合 ----
    composite = sum(
        scores[k] * ACTIVE_WEIGHTS[k] / 100
        for k in ACTIVE_WEIGHTS
    )

    return {
        "model": "active_equity",
        "scores": {k: round(v, 1) for k, v in scores.items()},
        "composite": round(composite, 1),
        "weights": ACTIVE_WEIGHTS,
    }
