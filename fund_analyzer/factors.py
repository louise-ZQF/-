"""量化多因子评分体系。

统一使用 fund_analyzer.indicators 中的函数（sma/ema/rsi/returns/max_dd/sharpe等），
因子层只做评分映射，不重复实现统计函数。
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from . import indicators as ind


@dataclass
class FactorScores:
    """单只基金的因子评分。"""
    momentum: float = 50.0
    trend_quality: float = 50.0
    value: float = 50.0
    risk_adjusted: float = 50.0
    vol_regime: float = 50.0
    drawdown_recovery: float = 50.0
    composite: float = 50.0
    notes: List[str] = field(default_factory=list)
    summary: str = ""
    labels: tuple = ("动量", "趋势质量", "估值", "风险调整", "波动状态", "回撤恢复")


WEIGHTS = {
    "momentum": 0.25, "trend_quality": 0.20, "value": 0.15,
    "risk_adjusted": 0.20, "vol_regime": 0.10, "drawdown_recovery": 0.10,
}


def _returns_from_navs(navs: Sequence[float]) -> List[float]:
    """净值 → 日收益率序列。"""
    return [navs[i] / navs[i - 1] - 1.0 for i in range(1, len(navs)) if navs[i - 1]]


# ---------------------------------------------------------------------------
# 因子计算
# ---------------------------------------------------------------------------

def _momentum_score(navs: Sequence[float]) -> Tuple[float, str]:
    """动量因子：多时间框架收益 × 加速度。"""
    if len(navs) < 21:
        return 50.0, "数据不足"

    ret_1w = navs[-1] / max(navs[-6], 0.0001) - 1 if len(navs) >= 6 else 0
    ret_1m = navs[-1] / max(navs[-22], 0.0001) - 1 if len(navs) >= 22 else 0
    ret_3m = navs[-1] / max(navs[-66], 0.0001) - 1 if len(navs) >= 66 else 0

    # 加速度：近期动量是否在改善
    accel = ret_1m - ret_3m if ret_3m != 0 else 0

    # 合成原始分（-1 ~ +1 映射到 0-100）
    raw = (ret_1w * 0.2 + ret_1m * 0.4 + ret_3m * 0.3 + accel * 0.1)
    score = 50 + raw * 80  # 放大到有区分度
    score = max(0, min(100, score))

    # 解读
    if score >= 80:
        note = f"动量极强(1周{ret_1w*100:+.1f}% 1月{ret_1m*100:+.1f}%)"
    elif score >= 60:
        note = f"动量偏强(1月{ret_1m*100:+.1f}% 3月{ret_3m*100:+.1f}%)"
    elif score >= 40:
        note = f"动量中性(1月{ret_1m*100:+.1f}%)"
    elif score >= 20:
        note = f"动量偏弱(1月{ret_1m*100:+.1f}%)"
    else:
        note = f"动量极弱(1周{ret_1w*100:+.1f}% 1月{ret_1m*100:+.1f}%)"

    return round(score, 1), note


def _trend_quality_score(navs: Sequence[float]) -> Tuple[float, str]:
    """趋势质量：MACD + 均线排列 + ADX 近似。"""
    if len(navs) < 60:
        return 50.0, "数据不足"

    # MACD (12/26/9) — 需要 EMA 序列，本地实现
    def _ema_seq(seq, w):
        if len(seq) < 2: return list(seq)
        k = 2.0 / (w + 1)
        out = [seq[0]]
        for x in seq[1:]: out.append(x * k + out[-1] * (1 - k))
        return out

    ema12 = _ema_seq(navs, 12)
    ema26 = _ema_seq(navs, 26)
    macd_line = ema12[-1] - ema26[-1]
    signal = _ema_seq([ema12[i] - ema26[i] for i in range(len(navs))], 9)
    macd_hist = macd_line - signal[-1]

    # 均线排列：多/空/纠缠
    ma20 = ind.sma(navs, 20)
    ma60 = ind.sma(navs, 60)
    if ma20 and ma60 and navs[-1]:
        if navs[-1] > ma20 > ma60:
            alignment = 1.0  # 多头
        elif navs[-1] < ma20 < ma60:
            alignment = 0.0  # 空头
        else:
            alignment = 0.5  # 纠缠
    else:
        alignment = 0.5

    # ADX 近似（用 14 日方向性运动）
    if len(navs) >= 15:
        up_moves = [max(navs[i] - navs[i - 1], 0) for i in range(-14, 0)]
        down_moves = [max(navs[i - 1] - navs[i], 0) for i in range(-14, 0)]
        avg_up = sum(up_moves) / 14 if up_moves else 0
        avg_down = sum(down_moves) / 14 if down_moves else 0
        dx = abs(avg_up - avg_down) / max(avg_up + avg_down, 0.0001)
        adx_strength = min(1.0, dx * 2)  # 0-1
    else:
        adx_strength = 0.5

    # 综合：MACD 方向(0.4) + 均线排列(0.3) + ADX强度(0.3)
    macd_signal = 1.0 if macd_hist > 0 else (0.0 if macd_hist < -0.001 else 0.5)
    raw = macd_signal * 0.4 + alignment * 0.3 + adx_strength * 0.3
    score = raw * 100

    if score >= 70:
        note = "趋势强劲，多头排列"
    elif score >= 55:
        note = "趋势偏多，均线向上"
    elif score >= 45:
        note = "趋势不明，均线纠缠"
    elif score >= 30:
        note = "趋势偏弱"
    else:
        note = "趋势走坏，空头排列"

    return round(score, 1), note


def _value_score(navs: Sequence[float]) -> Tuple[float, str]:
    """估值因子：当前净值在历史区间中的位置。"""
    if len(navs) < 60:
        return 50.0, "数据不足"

    current = navs[-1]
    hist = navs[-252:] if len(navs) >= 252 else navs  # 最多1年
    percentile = sum(1 for n in hist if n <= current) / len(hist)

    # 低估 = 高分（值得买），高估 = 低分
    # 分位 < 20% → 低估 → 80-100分
    # 分位 > 80% → 高估 → 0-20分
    score = (1 - percentile) * 100

    if percentile <= 0.15:
        note = f"极度低估(分位{percentile*100:.0f}%)，历史底部"
    elif percentile <= 0.30:
        note = f"偏低估值(分位{percentile*100:.0f}%)，有安全边际"
    elif percentile <= 0.70:
        note = f"估值合理(分位{percentile*100:.0f}%)"
    elif percentile <= 0.85:
        note = f"估值偏高(分位{percentile*100:.0f}%)，注意风险"
    else:
        note = f"极度高估(分位{percentile*100:.0f}%)，历史高位"

    return round(score, 1), note


def _risk_adjusted_score(rets: Sequence[float]) -> Tuple[float, str]:
    """风险调整收益：Sharpe + Sortino + Calmar。"""
    if len(rets) < 20:
        return 50.0, "数据不足"

    # 年化
    ann_ret = sum(rets) / len(rets) * 252
    ann_vol = statistics.stdev(rets) * math.sqrt(252) if len(rets) > 1 else 0.0
    sharpe = (ann_ret - 0.02) / max(ann_vol, 0.001)  # rf=2%

    # Sortino: 下行标准差
    downs = [min(r, 0) ** 2 for r in rets]
    dd_std = math.sqrt(sum(downs) / len(downs)) if downs else 0.0
    sortino = (ann_ret - 0.02) / max(dd_std * math.sqrt(252), 0.001)

    # Calmar: 用真实最大回撤
    md = ind.max_drawdown(navs) or -0.01
    calmar = ann_ret / max(abs(md), 0.001)

    # 合成：Sharpe(0.4) + Sortino(0.3) + Calmar(0.3)
    # 每个指标映射到 0-100
    def _map_ratio(r: float, center: float = 0.5) -> float:
        return min(100, max(0, 50 + (r - center) * 40))

    s_score = _map_ratio(sharpe, 0.3)
    so_score = _map_ratio(sortino, 0.5)
    c_score = _map_ratio(calmar, 0.8)
    score = s_score * 0.4 + so_score * 0.3 + c_score * 0.3

    if score >= 70:
        note = f"风险调整优秀(Sharpe {sharpe:.1f})"
    elif score >= 55:
        note = f"风险调整良好(Sharpe {sharpe:.1f})"
    elif score >= 40:
        note = f"风险调整一般(Sharpe {sharpe:.1f})"
    else:
        note = f"风险调整较差(Sharpe {sharpe:.1f})"

    return round(score, 1), note


def _vol_regime_score(rets: Sequence[float]) -> Tuple[float, str]:
    """波动率状态：波动在扩张还是收缩。"""
    if len(rets) < 40:
        return 50.0, "数据不足"

    # 近期 vs 远期 波动率
    recent_vol = (statistics.stdev(rets[-10:]) if len(rets) >= 10 else 0.0) if len(rets) >= 10 else _std(rets)
    older_vol = (statistics.stdev(rets[-40:-10]) if len(rets) >= 40 else 0.0) if len(rets) >= 40 else _std(rets)
    vol_ratio = recent_vol / max(older_vol, 0.0001)

    # 波动收缩 = 高分（市场稳定），波动扩张 = 低分
    if vol_ratio < 0.7:
        score = 80  # 明显收缩
    elif vol_ratio < 0.9:
        score = 65  # 轻微收缩
    elif vol_ratio < 1.1:
        score = 50  # 稳定
    elif vol_ratio < 1.5:
        score = 35  # 轻微扩张
    else:
        score = 15  # 剧烈扩张

    if score >= 70:
        note = "波动收缩中，市场趋稳"
    elif score >= 50:
        note = "波动率正常"
    else:
        note = f"波动扩张(近期{(recent_vol*100):.1f}% vs 远期{(older_vol*100):.1f}%)"

    return round(score, 1), note


def _drawdown_recovery_score(navs: Sequence[float]) -> Tuple[float, str]:
    """回撤恢复：当前距最高点 + 回撤幅度。"""
    if len(navs) < 20:
        return 50.0, "数据不足"

    peak = max(navs)
    current = navs[-1]
    dd_pct = (current - peak) / max(peak, 0.0001)

    # 距最高点的距离映射
    if dd_pct >= -0.02:
        score = 85  # 接近新高
    elif dd_pct >= -0.05:
        score = 70
    elif dd_pct >= -0.10:
        score = 55
    elif dd_pct >= -0.20:
        score = 35
    else:
        score = 15

    # 考虑恢复速度：如果最近在涨，适当加分
    ret_1w = navs[-1] / max(navs[-6], 0.0001) - 1 if len(navs) >= 6 else 0
    if ret_1w > 0.02:
        score = min(100, score + 10)

    if score >= 75:
        note = f"接近历史新高(回撤{dd_pct*100:.1f}%)"
    elif score >= 55:
        note = f"小幅回撤({dd_pct*100:.1f}%)，可接受"
    else:
        note = f"深度回撤({dd_pct*100:.1f}%)，注意风险"

    return round(score, 1), note


# ---------------------------------------------------------------------------
# 综合评分
# ---------------------------------------------------------------------------

def compute_factor_scores(navs: Sequence[float]) -> FactorScores:
    """计算所有因子评分。navs 是单位净值序列（升序）。"""
    fs = FactorScores()

    if len(navs) < 20:
        fs.summary = "历史数据不足（<20个交易日），无法计算因子评分"
        fs.notes = [fs.summary]
        return fs

    rets = _returns_from_navs(navs)

    # 逐因子计算
    fs.momentum, n_mom = _momentum_score(navs)
    fs.trend_quality, n_trend = _trend_quality_score(navs)
    fs.value, n_val = _value_score(navs)
    fs.risk_adjusted, n_ra = _risk_adjusted_score(rets)
    fs.vol_regime, n_vol = _vol_regime_score(rets)
    fs.drawdown_recovery, n_dd = _drawdown_recovery_score(navs)

    fs.notes = [n_mom, n_trend, n_val, n_ra, n_vol, n_dd]

    # 加权综合
    fs.composite = round(
        fs.momentum * WEIGHTS["momentum"]
        + fs.trend_quality * WEIGHTS["trend_quality"]
        + fs.value * WEIGHTS["value"]
        + fs.risk_adjusted * WEIGHTS["risk_adjusted"]
        + fs.vol_regime * WEIGHTS["vol_regime"]
        + fs.drawdown_recovery * WEIGHTS["drawdown_recovery"],
        1,
    )

    # 综合解读
    if fs.composite >= 80:
        fs.summary = f"综合{fs.composite:.0f}分·强烈看好 — 多因子共振向上，趋势+动量+风险调整均优"
    elif fs.composite >= 65:
        fs.summary = f"综合{fs.composite:.0f}分·偏多 — 多数因子积极，可考虑配置"
    elif fs.composite >= 50:
        fs.summary = f"综合{fs.composite:.0f}分·中性 — 因子多空交织，需精选时机"
    elif fs.composite >= 35:
        fs.summary = f"综合{fs.composite:.0f}分·偏弱 — 多数因子走弱，建议观望或轻仓"
    else:
        fs.summary = f"综合{fs.composite:.0f}分·规避 — 多因子共振向下，不建议介入"

    return fs


def factors_to_dict(fs: FactorScores) -> dict:
    """转为前端友好的字典。"""
    return {
        "scores": {
            "momentum": fs.momentum,
            "trend_quality": fs.trend_quality,
            "value": fs.value,
            "risk_adjusted": fs.risk_adjusted,
            "vol_regime": fs.vol_regime,
            "drawdown_recovery": fs.drawdown_recovery,
        },
        "composite": fs.composite,
        "labels": list(fs.labels),
        "notes": fs.notes,
        "summary": fs.summary,
    }
