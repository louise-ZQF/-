"""硬性过滤器：排除不适合统计/不可执行的基金。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional


# 规模阈值（同类 20% 分位以下警告，5000万以下严格过滤）
_MIN_SIZE_WARN_PCT = 0.20   # 同类 20% 分位
_MIN_SIZE_STRICT = 50000000  # 5000万（严格过滤）
_MIN_HISTORY_PASSIVE = 0.5   # 被动基金最少 0.5 年（~126 交易日）
_MIN_HISTORY_ACTIVE = 1      # 主动基金最少 1 年（~252 交易日，受限于 API 分页）
_MIN_MANAGER_TENURE = 1      # 基金经理最少任职 1 年


def compute_peer_size_threshold(funds: List[dict], percentile: float = _MIN_SIZE_WARN_PCT) -> float:
    """计算同类基金规模的百分位阈值。"""
    sizes = [f.get("fund_size", 0) for f in funds if f.get("fund_size", 0) > 0]
    if len(sizes) < 5:
        return _MIN_SIZE_STRICT
    sizes.sort()
    idx = max(0, int(len(sizes) * percentile))
    return sizes[idx]


def apply_hard_filters(funds: List[dict],
                       fund_type: str = "all",
                       as_of: date = None) -> tuple:
    """应用硬性过滤，返回 (通过列表, 被过滤列表)。

    funds: [{"code", "name", "fund_type", "inception_date", "fund_size",
             "manager_start_date", "purchase_status", "nav_days", ...}]
    """
    if as_of is None:
        as_of = date.today()

    passed = []
    filtered = []

    # 按同类计算规模阈值
    peer_threshold = compute_peer_size_threshold(funds)

    for f in funds:
        reasons = []

        # 1. 历史不足
        inception = f.get("inception_date")
        if inception:
            try:
                inc_date = datetime.strptime(str(inception)[:10], "%Y-%m-%d").date()
                years = (as_of - inc_date).days / 365.25
            except (ValueError, TypeError):
                years = 0
            min_years = _MIN_HISTORY_PASSIVE if f.get("is_passive") else _MIN_HISTORY_ACTIVE
            if years < min_years:
                reasons.append(f"历史不足{min_years}年({years:.1f}年)")

        # 2. 净值缺失严重
        nav_days = f.get("nav_days", 0)
        expected_days = f.get("expected_days", 252)
        if expected_days > 0 and nav_days / expected_days < 0.7:
            reasons.append(f"净值缺失{nav_days}/{expected_days}天")

        # 3. 规模过小（严格过滤）
        size = f.get("fund_size", 0)
        if size < _MIN_SIZE_STRICT:
            reasons.append(f"规模过小({size/1e4:.0f}万)")

        # 4. 基金经理任职不足
        mgr_start = f.get("manager_start_date")
        if mgr_start:
            try:
                mgr_date = datetime.strptime(str(mgr_start)[:10], "%Y-%m-%d").date()
                mgr_years = (as_of - mgr_date).days / 365.25
                if mgr_years < _MIN_MANAGER_TENURE and f.get("fund_type") == "active_equity":
                    reasons.append(f"经理任职不足{_MIN_MANAGER_TENURE}年({mgr_years:.1f}年)")
            except (ValueError, TypeError):
                pass

        # 5. 暂停申购
        if f.get("purchase_status") == "suspended":
            reasons.append("暂停申购")

        if reasons:
            f["filter_reasons"] = reasons
            filtered.append(f)
        else:
            passed.append(f)

        # 规模警告（不过滤，但标记）
        if size > 0 and size < peer_threshold and size >= _MIN_SIZE_STRICT:
            f["size_warning"] = True

    return passed, filtered
