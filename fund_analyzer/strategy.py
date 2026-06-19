"""策略引擎：把指标 + 持仓状态 → 可执行的操作建议。

方法论来源（均为公开、被广泛使用的指数/基金投资规则，非个人臆断）：
    * 估值定投：低估区间加大定投、高估区间分批止盈（指数基金估值百分位法）；
    * 目标止盈法：达到预设收益目标即分批止盈；
    * 回撤止盈法：盈利后从高点回撤超过阈值即止盈，避免坐过山车；
    * 趋势/动量过滤：均线多空排列、RSI 超买超卖做辅助；
    * 再平衡：权重偏离目标过大时把组合拉回目标配置（组合层处理，见 portfolio.py）。

每条规则产出一个 Signal(vote, text, hard)，vote 为方向票（正=偏多，负=偏空）。
汇总分数映射到操作建议，同时「硬触发」（已达止盈线/回撤止盈）会强制至少减仓。

注意：这是规则化的量化参考，不是投资建议；阈值都可在 settings.yaml 调整。
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from .config import StrategySettings
from .models import Action, FundAnalysis, Signal


def _current_drawdown(navs: Sequence[float]) -> Optional[float]:
    """当前净值相对区间最高点的回撤（<=0）。"""
    if not navs:
        return None
    peak = max(navs)
    if peak <= 0:
        return None
    return navs[-1] / peak - 1.0


def evaluate(analysis: FundAnalysis, navs: Sequence[float], st: StrategySettings) -> None:
    """就地填充 analysis.signals / action / score / rationale。"""
    m = analysis.metrics
    h = analysis.holding
    signals: List[Signal] = []

    # A. 估值分位（核心：低买高卖的纪律）
    if m.price_percentile is not None:
        pct = m.price_percentile
        yrs = st.percentile_lookback / 252.0
        if pct <= st.low_percentile:
            signals.append(Signal("估值分位", +1.5,
                f"净值处于近{yrs:.1f}年低位（分位{pct*100:.0f}%），估值偏低，适合定投/分批买入"))
        elif pct >= st.high_percentile:
            signals.append(Signal("估值分位", -1.5,
                f"净值处于近{yrs:.1f}年高位（分位{pct*100:.0f}%），警惕高位回调风险"))
        else:
            signals.append(Signal("估值分位", 0.0,
                f"净值分位{pct*100:.0f}%，估值中性"))

    # B. 趋势（均线排列）
    if m.last_nav and m.ma20 and m.ma60:
        if m.last_nav > m.ma20 > m.ma60:
            signals.append(Signal("趋势", +1.0, "多头排列（净值 > MA20 > MA60），中短期趋势向上"))
        elif m.last_nav < m.ma20 < m.ma60:
            signals.append(Signal("趋势", -1.0, "空头排列（净值 < MA20 < MA60），中短期趋势向下"))
        else:
            signals.append(Signal("趋势", 0.0, "均线纠缠，趋势不明"))

    # C. RSI 超买超卖
    if m.rsi14 is not None:
        if m.rsi14 >= st.rsi_overbought:
            signals.append(Signal("RSI", -1.0, f"RSI={m.rsi14:.0f} 超买，短期偏热"))
        elif m.rsi14 <= st.rsi_oversold:
            signals.append(Signal("RSI", +1.0, f"RSI={m.rsi14:.0f} 超卖，短期偏冷（可能是定投良机）"))

    # D. 目标止盈（硬触发）
    hard_take_profit = False
    if m.holding_return is not None and h.shares > 0:
        if m.holding_return >= st.take_profit_target:
            hard_take_profit = True
            signals.append(Signal("目标止盈", -2.0,
                f"持仓收益 {m.holding_return*100:+.1f}% 已达目标止盈线 {st.take_profit_target*100:.0f}%，"
                f"建议分批止盈、落袋部分利润", hard=True))

    # E. 回撤止盈（硬触发）：盈利状态下从高点回撤过大
    cur_dd = _current_drawdown(navs)
    if (m.holding_return is not None and m.holding_return > 0.10
            and cur_dd is not None and cur_dd <= -st.trailing_dd_after_profit):
        hard_take_profit = True
        signals.append(Signal("回撤止盈", -1.5,
            f"盈利后从区间高点回撤 {cur_dd*100:.1f}%（超过 {st.trailing_dd_after_profit*100:.0f}% 阈值），"
            f"触发回撤止盈，建议保护利润", hard=True))

    # F. 止损警戒（指数定投通常不止损，仅提示复核）
    if m.holding_return is not None and h.shares > 0 and m.holding_return <= st.stop_loss:
        signals.append(Signal("止损警戒", -1.0,
            f"持仓亏损 {m.holding_return*100:.1f}% 触及警戒线 {st.stop_loss*100:.0f}%；"
            f"若为宽基指数定投可继续，若为主动/行业基金请复核基本面", hard=True))

    # 汇总
    score = sum(s.vote for s in signals)
    analysis.signals = signals
    analysis.score = score
    analysis.action = _decide_action(score, hard_take_profit, h.is_dca)
    # rationale：硬触发优先，其后按 |vote| 排序取前几条
    ordered = sorted(signals, key=lambda s: (not s.hard, -abs(s.vote)))
    analysis.rationale = "；".join(s.text for s in ordered[:3])


def _decide_action(score: float, hard_take_profit: bool, is_dca: bool) -> Action:
    if hard_take_profit:
        # 已达止盈条件：至少减仓；若整体信号也很弱则更倾向卖出
        return Action.SELL if score <= -3.0 else Action.TRIM
    if score >= 1.5:
        return Action.BUY_MORE
    if score >= 0.5:
        return Action.DCA_CONTINUE if is_dca else Action.HOLD
    if score > -0.5:
        return Action.HOLD
    if score > -1.5:
        return Action.DCA_PAUSE if is_dca else Action.HOLD
    return Action.TRIM
