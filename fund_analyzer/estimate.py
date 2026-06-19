"""QDII「T+时差」收益估算引擎 —— 本系统的核心功能。

背景
----
国内的 QDII 基金（投资美股/海外的基金）净值是 T+1 / T+2 公布的：美股今晚（北京时间
凌晨）收盘后，对应的基金净值要过 1~2 个交易日才会更新到国内平台。这导致你「看到的净值」
其实滞后于真实价值。

本引擎做两件事：
    1. 把「已经发生、但还没体现在最新公布净值里」的美股指数涨跌，换算成基金的「应有净值」，
       让你今天就估算出「其实已经赚/亏了多少」；
    2. 给出一个基于历史跟踪误差的误差带（约 ±1 个标准差），提醒你这是估算而非确定值。

模型
----
对某只跟踪指数 I 的 QDII，单日基金收益近似为：

    r_fund ≈ alpha + beta * r_index  ( + r_fx，若未做汇率对冲 )  - fee_daily

其中：
    beta    基金对指数的敏感度（指数型基金通常≈1；可在配置里写死，或用历史净值回归 'auto'）。
    alpha   截距（通常很小）。
    r_fx    人民币兑美元当日变动（未对冲时，美元升值利好持有美元资产的国内投资者）。
    fee_daily  管理费/托管费等的日均拖累（年费率 / 252）。

「待体现」的交易日：把最近 lag_days 个指数交易日的涨跌视为「尚未反映到最新公布净值」，
逐日复利得到累计估算收益。lag_days 可按基金实际公布节奏校准（常见 1 或 2）。

局限（务必知悉）
----------------
    * 这是「跟踪 + 回归」近似，遇到指数成分调整、汇率剧烈波动、基金现金仓位变化、
      申赎冲击等会有偏差；
    * lag_days 是经验值，最好用一次「指数涨跌 vs 次日基金实际涨跌」做一次校准；
    * 对主动管理型 QDII（非纯指数）误差更大，仅供参考。
"""
from __future__ import annotations

import bisect
import math
from datetime import date
from typing import List, Optional, Sequence, Tuple

from .indicators import ols
from .models import EstimateResult, Tracking


def _nearest_prev_value(dates: Sequence[date], values: Sequence[float], target: date) -> Optional[float]:
    """返回 dates 中 <= target 的最近一个对应 value（dates 升序）。"""
    i = bisect.bisect_right(dates, target) - 1
    if i < 0:
        return None
    return values[i]


def estimate_beta_alpha(
    fund_rets: Sequence[Tuple[date, float]],
    index_rets: Sequence[Tuple[date, float]],
    min_overlap: int = 20,
) -> Tuple[float, float, float, float, str]:
    """用历史日收益回归估计 (alpha, beta, resid_std, r2, method)。

    采用「就近对齐」：基金某日收益 r_fund(D) 对齐到指数中 <= D 的最近一个交易日收益。
    这是为了在两套交易日历（A股 vs 美股）下做稳健近似；若重叠样本不足则回退 beta=1。
    """
    if not fund_rets or not index_rets:
        return 0.0, 1.0, 0.0, 0.0, "default(beta=1)"
    idx_dates = [d for d, _ in index_rets]
    idx_vals = [v for _, v in index_rets]
    xs, ys = [], []
    for d, rf in fund_rets:
        ri = _nearest_prev_value(idx_dates, idx_vals, d)
        if ri is not None:
            xs.append(ri)
            ys.append(rf)
    if len(xs) < min_overlap:
        return 0.0, 1.0, 0.0, 0.0, "default(beta=1, 样本不足)"
    alpha, beta, resid_std, r2 = ols(xs, ys)
    # 合理性夹逼：指数基金 beta 不应离谱
    beta = max(0.2, min(2.5, beta))
    return alpha, beta, resid_std, r2, f"回归(n={len(xs)}, R²={r2:.2f})"


def estimate_holding(
    *,
    base_nav: Optional[float],
    base_date: Optional[date],
    tracking: Tracking,
    index_rets: Sequence[Tuple[date, float]],
    fx_rets: Optional[Sequence[Tuple[date, float]]] = None,
    fund_rets: Optional[Sequence[Tuple[date, float]]] = None,
    annual_fee: float = 0.0,
    default_daily_band: float = 0.004,
) -> EstimateResult:
    """对单只 QDII 估算「待体现」累计收益与应有净值。

    index_rets / fx_rets / fund_rets 均为 (date, 小数收益) 的升序列表。
    """
    res = EstimateResult(code="", base_nav=base_nav, base_date=base_date)
    if not index_rets or tracking.index is None:
        res.method = "无跟踪指数，跳过估算"
        return res

    # 1) 确定 beta / alpha / 残差标准差
    if tracking.beta_value is not None:
        beta = tracking.beta_value
        alpha = 0.0
        if fund_rets:
            _, _, resid_std, _, _ = estimate_beta_alpha(fund_rets, index_rets)
        else:
            resid_std = default_daily_band
        method = f"固定 beta={beta:g}"
    else:
        alpha, beta, resid_std, r2, method = estimate_beta_alpha(fund_rets or [], index_rets)
    if not resid_std:
        resid_std = default_daily_band
    res.beta_used = beta

    # 2) 取「最近 lag_days 个指数交易日」作为待体现收益
    lag = max(1, int(tracking.lag_days))
    pending_idx = list(index_rets)[-lag:]
    fee_daily = (annual_fee or 0.0) / 252.0

    # 3) 汇率对齐（未对冲时叠加）
    fx_dates = [d for d, _ in (fx_rets or [])]
    fx_vals = [v for _, v in (fx_rets or [])]

    per_day: List[float] = []
    detail: List[str] = []
    for d, ri in pending_idx:
        r = alpha + beta * ri
        fx_txt = ""
        if not tracking.currency_hedged and fx_dates:
            rfx = _nearest_prev_value(fx_dates, fx_vals, d) or 0.0
            r += rfx
            fx_txt = f" + 汇率{rfx*100:+.2f}%"
        r -= fee_daily
        per_day.append(r)
        detail.append(
            f"{d.isoformat()}：指数{ri*100:+.2f}% × β{beta:.2f}{fx_txt} − 费{fee_daily*100:.3f}% "
            f"→ 估{r*100:+.2f}%"
        )

    # 4) 复利累计 + 误差带
    cum = 1.0
    for r in per_day:
        cum *= (1.0 + r)
    cum -= 1.0
    band = resid_std * math.sqrt(len(per_day)) if per_day else 0.0

    res.pending_returns = per_day
    res.cum_return = cum
    res.band = band
    res.method = method
    res.detail = detail
    if base_nav:
        res.implied_nav = base_nav * (1.0 + cum)
    return res
