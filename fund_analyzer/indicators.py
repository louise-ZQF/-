"""技术与统计指标（纯函数，无外部依赖，便于离线测试）。

约定：
    * 序列按时间「从旧到新」排列。
    * 收益率/涨跌幅一律用小数（0.01 = 1%）。
    * 数据不足时返回 None，而不是抛异常，方便上层稳健处理。
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple


def returns_from_navs(navs: Sequence[float]) -> List[float]:
    """由净值序列计算逐期简单收益率。"""
    out: List[float] = []
    for i in range(1, len(navs)):
        prev = navs[i - 1]
        if prev:
            out.append(navs[i] / prev - 1.0)
        else:
            out.append(0.0)
    return out


def sma(series: Sequence[float], window: int) -> Optional[float]:
    """简单移动平均（取最近 window 个）。"""
    if window <= 0 or len(series) < window:
        return None
    return sum(series[-window:]) / window


def ema(series: Sequence[float], window: int) -> Optional[float]:
    """指数移动平均。"""
    if window <= 0 or len(series) < window:
        return None
    k = 2.0 / (window + 1.0)
    e = series[0]
    for x in series[1:]:
        e = x * k + e * (1.0 - k)
    return e


def rsi(navs: Sequence[float], period: int = 14) -> Optional[float]:
    """RSI（Wilder 平滑）。>70 常视为超买，<30 超卖。"""
    if len(navs) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(navs)):
        chg = navs[i] - navs[i - 1]
        gains.append(max(chg, 0.0))
        losses.append(max(-chg, 0.0))
    # 初始平均
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    # Wilder 平滑
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def max_drawdown(navs: Sequence[float]) -> Optional[float]:
    """最大回撤（返回负的小数，例如 -0.235 表示 -23.5%）。"""
    if len(navs) < 2:
        return None
    peak = navs[0]
    mdd = 0.0
    for x in navs:
        if x > peak:
            peak = x
        if peak > 0:
            dd = x / peak - 1.0
            if dd < mdd:
                mdd = dd
    return mdd


def annualized_volatility(returns: Sequence[float], periods: int = 252) -> Optional[float]:
    """年化波动率（按日频，periods=252）。"""
    if len(returns) < 2:
        return None
    mu = sum(returns) / len(returns)
    var = sum((r - mu) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(var) * math.sqrt(periods)


def sharpe(returns: Sequence[float], rf_annual: float = 0.02, periods: int = 252) -> Optional[float]:
    """年化夏普比率（rf_annual 为年化无风险利率）。"""
    if len(returns) < 2:
        return None
    rf_period = rf_annual / periods
    excess = [r - rf_period for r in returns]
    mu = sum(excess) / len(excess)
    var = sum((r - mu) ** 2 for r in excess) / (len(excess) - 1)
    sd = math.sqrt(var)
    if sd == 0:
        return None
    return (mu / sd) * math.sqrt(periods)


def cumulative_return(navs: Sequence[float]) -> Optional[float]:
    """区间累计收益（首尾净值）。"""
    if len(navs) < 2 or not navs[0]:
        return None
    return navs[-1] / navs[0] - 1.0


def trailing_return(navs: Sequence[float], lookback: int) -> Optional[float]:
    """最近 lookback 期的收益率（lookback 为整数期数）。"""
    if lookback <= 0 or len(navs) < lookback + 1 or not navs[-lookback - 1]:
        return None
    return navs[-1] / navs[-lookback - 1] - 1.0


def percentile_rank(series: Sequence[float], value: float) -> Optional[float]:
    """value 在 series 中的分位（0~1）。0.2 表示比 20% 的历史值高（处于偏低位置）。"""
    if not series:
        return None
    below = sum(1 for x in series if x <= value)
    return below / len(series)


def ols(xs: Sequence[float], ys: Sequence[float]) -> Tuple[float, float, float, float]:
    """一元最小二乘回归 y = alpha + beta*x。

    返回 (alpha, beta, resid_std, r2)。用于由「基金收益 vs 指数收益」估计 beta。
    """
    n = len(xs)
    if n < 2 or n != len(ys):
        return 0.0, 1.0, 0.0, 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    beta = sxy / sxx if sxx else 0.0
    alpha = my - beta * mx
    resid = [y - (alpha + beta * x) for x, y in zip(xs, ys)]
    if n > 2:
        rmu = sum(resid) / n
        resid_std = math.sqrt(sum((r - rmu) ** 2 for r in resid) / (n - 2))
    else:
        resid_std = 0.0
    sst = sum((y - my) ** 2 for y in ys)
    ssr = sum(r * r for r in resid)
    r2 = 1.0 - ssr / sst if sst else 0.0
    return alpha, beta, resid_std, r2
