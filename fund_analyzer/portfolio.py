"""组合层编排：拉数据 → 算指标 → 时差估算 → 策略 → 组合建议 → 报告对象。

设计成两层：
    * 纯函数 analyze_fund() / build_report()：给定已取好的数据即可计算，便于离线测试与 demo；
    * Analyzer 类：负责真正联网取数（天天基金 + 指数行情），再调用纯函数。
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from . import indicators as ind
from .config import Settings
from .datasource import EastMoney, MarketIndex
from .datasource.base import HttpClient
from .estimate import estimate_holding
from .models import (
    AssetClass, FundAnalysis, Holding, Metrics, NavPoint, PortfolioReport, Quote,
)
from .strategy import evaluate


# ----------------------------------------------------------------------------
# 纯函数层
# ----------------------------------------------------------------------------

def compute_metrics(holding: Holding, navpoints: Sequence[NavPoint],
                    quote: Optional[Quote], st: Settings) -> Metrics:
    navs = [p.nav for p in navpoints]
    m = Metrics()
    if not navs:
        return m
    m.last_nav = navs[-1]
    m.ret_1w = ind.trailing_return(navs, 5)
    m.ret_1m = ind.trailing_return(navs, 21)
    m.ret_3m = ind.trailing_return(navs, 63)
    m.ret_1y = ind.trailing_return(navs, 252)
    m.ma20 = ind.sma(navs, 20)
    m.ma60 = ind.sma(navs, 60)
    m.ma120 = ind.sma(navs, 120)
    m.rsi14 = ind.rsi(navs, 14)
    m.max_drawdown = ind.max_drawdown(navs)
    rets = ind.returns_from_navs(navs)
    m.vol_annual = ind.annualized_volatility(rets)
    m.sharpe = ind.sharpe(rets, rf_annual=st.strategy.rf_annual)
    window = navs[-st.strategy.percentile_lookback:]
    m.price_percentile = ind.percentile_rank(window, navs[-1])
    if holding.cost_nav and holding.cost_nav > 0:
        m.holding_return = m.last_nav / holding.cost_nav - 1.0
    return m


def analyze_fund(holding: Holding, navpoints: Sequence[NavPoint], quote: Optional[Quote],
                 index_rets: Sequence[Tuple], fx_rets: Sequence[Tuple], st: Settings) -> FundAnalysis:
    fa = FundAnalysis(holding=holding, quote=quote)
    fa.metrics = compute_metrics(holding, navpoints, quote, st)
    fa.history = list(navpoints)

    # 时差估算（仅对配置了跟踪指数的 QDII）
    if holding.tracking.index and index_rets:
        navs = [p.nav for p in navpoints]
        fund_rets = [(navpoints[i].d, navs[i] / navs[i - 1] - 1.0)
                     for i in range(1, len(navs)) if navs[i - 1]]
        base_nav = navs[-1] if navs else (quote.nav if quote else None)
        base_date = navpoints[-1].d if navpoints else (quote.nav_date if quote else None)
        est = estimate_holding(
            base_nav=base_nav, base_date=base_date, tracking=holding.tracking,
            index_rets=index_rets, fx_rets=fx_rets, fund_rets=fund_rets,
            annual_fee=holding.annual_fee,
        )
        est.code = holding.code
        fa.estimate = est

    evaluate(fa, [p.nav for p in navpoints], st.strategy)
    return fa


def build_report(funds: List[FundAnalysis], st: Settings,
                 market_brief: Optional[List[str]] = None,
                 as_of: Optional[datetime] = None) -> PortfolioReport:
    rep = PortfolioReport(as_of=as_of or datetime.now(), funds=funds,
                          market_brief=market_brief or [])

    total_value = 0.0
    total_implied = 0.0
    total_cost = 0.0
    has_value = False
    for fa in funds:
        mv = fa.market_value
        iv = fa.implied_value
        if mv is not None:
            total_value += mv
            total_implied += (iv if iv is not None else mv)
            has_value = True
        total_cost += fa.holding.cost_amount

    if has_value:
        rep.total_value = total_value
        rep.total_implied_value = total_implied
        rep.total_cost = total_cost or None
        if total_value > 0:
            rep.est_today_change = total_implied / total_value - 1.0

    rep.portfolio_notes = _portfolio_notes(funds, total_value, st)
    return rep


def _portfolio_notes(funds: List[FundAnalysis], total_value: float, st: Settings) -> List[str]:
    notes: List[str] = []
    if total_value <= 0:
        notes.append("未填写持仓份额/成本，当前仅做信号分析；补全 holdings.yaml 后可看市值、收益与再平衡建议。")
        return notes

    # 资产大类分布
    by_class: Dict[str, float] = {}
    for fa in funds:
        mv = fa.market_value or 0.0
        by_class[fa.holding.asset_class.value] = by_class.get(fa.holding.asset_class.value, 0.0) + mv
    dist = "、".join(f"{k}:{v/total_value*100:.0f}%" for k, v in sorted(by_class.items(), key=lambda x: -x[1]))
    notes.append(f"当前资产分布 → {dist}")

    # 单一资产集中度提醒
    for k, v in by_class.items():
        if v / total_value > 0.7:
            notes.append(f"⚠️ {k} 占比 {v/total_value*100:.0f}%，集中度较高，注意单一市场风险（你以美股 QDII 为主，需留意美股系统性回调）。")

    # 再平衡（基于目标权重）
    for fa in funds:
        tw = fa.holding.target_weight
        mv = fa.market_value
        if tw is None or mv is None:
            continue
        cur = mv / total_value
        drift = cur - tw
        if abs(drift) >= st.strategy.rebalance_band:
            verb = "超配，可考虑减仓再平衡" if drift > 0 else "低配，可考虑加仓再平衡"
            notes.append(
                f"再平衡：{fa.holding.name or fa.holding.code} 当前 {cur*100:.0f}% vs 目标 {tw*100:.0f}%"
                f"（偏离 {drift*100:+.0f}pct），{verb}。")
    return notes


# ----------------------------------------------------------------------------
# 联网编排层
# ----------------------------------------------------------------------------

class Analyzer:
    def __init__(self, settings: Settings):
        self.st = settings
        http = HttpClient(
            cache_dir=settings.datasource.cache_dir,
            ttl_minutes=settings.datasource.cache_ttl_minutes,
            timeout=settings.datasource.request_timeout,
        )
        self.em = EastMoney(http)
        self.mi = MarketIndex(http)
        self._index_cache: Dict[str, List[Tuple]] = {}

    def _index_returns(self, code: Optional[str]) -> List[Tuple]:
        if not code:
            return []
        if code not in self._index_cache:
            ticker = self.st.datasource.index_map.get(code, code)
            self._index_cache[code] = self.mi.returns(ticker)
        return self._index_cache[code]

    def run(self, holdings: List[Holding]) -> PortfolioReport:
        funds: List[FundAnalysis] = []
        for h in holdings:
            navpoints = self.em.history(h.code, size=100)
            quote = self.em.realtime(h.code)
            if quote and not h.name:
                h.name = quote.name
            index_rets = self._index_returns(h.tracking.index)
            fx_rets = self._index_returns(h.tracking.fx_index) if (
                h.tracking.index and not h.tracking.currency_hedged) else []
            funds.append(analyze_fund(h, navpoints, quote, index_rets, fx_rets, self.st))

        brief = self._market_brief()
        return build_report(funds, self.st, market_brief=brief)

    def _market_brief(self) -> List[str]:
        """抓取主要美股指数最近一日表现，作为「市场情报」摘要。"""
        brief: List[str] = []
        names = {"^GSPC": "标普500", "^NDX": "纳指100", "^DJI": "道指", "^SOX": "费城半导体"}
        for code, label in names.items():
            rets = self._index_returns(code)
            if rets:
                d, r = rets[-1]
                brief.append(f"{label}（{d.isoformat()}）{r*100:+.2f}%")
        fx = self._index_returns("USDCNY")
        if fx:
            d, r = fx[-1]
            brief.append(f"美元兑人民币 {r*100:+.2f}%（未对冲的美股 QDII 受其影响）")
        return brief

    def market_indicators(self) -> list:
        """获取市场情绪指标快照。"""
        return self.mi.get_market_snapshot()
