"""离线演示数据：无需联网即可跑通「指标→估算→策略→报告」全流程。

仅用于演示与测试，数据是用固定随机种子生成的「拟真」序列，非真实行情。
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from typing import List, Tuple

from .models import AssetClass, Holding, NavPoint, Quote, Tracking


def _walk(start: float, n: int, mu: float, sigma: float, seed: int) -> List[float]:
    rnd = random.Random(seed)
    out = [start]
    for _ in range(n - 1):
        out.append(out[-1] * (1.0 + rnd.gauss(mu, sigma)))
    return out


def _ramp(vals: List[float], k: int, step: float) -> List[float]:
    """对最后 k 个点施加渐进的趋势（step>0 上行，<0 下行），用于制造高/低分位场景。"""
    out = list(vals)
    for i in range(1, k + 1):
        out[-i] = out[-i] * (1.0 + step * (k - i + 1))
    return out


def _navpoints(values: List[float], end: date) -> List[NavPoint]:
    pts: List[NavPoint] = []
    d = end - timedelta(days=len(values) - 1)
    prev = None
    for v in values:
        chg = (v / prev - 1.0) if prev else None
        pts.append(NavPoint(d=d, nav=round(v, 4), change=chg))
        prev = v
        d += timedelta(days=1)
    return pts


def _index_returns(navs: List[float], end: date) -> List[Tuple[date, float]]:
    out: List[Tuple[date, float]] = []
    for i in range(1, len(navs)):
        out.append((end - timedelta(days=len(navs) - 1 - i), navs[i] / navs[i - 1] - 1.0))
    return out


def build_demo():
    """返回 (holdings, nav_map, quote_map, index_map, fx_returns, market_brief)。"""
    today = date(2026, 6, 19)
    N = 300

    # —— 纳指100 QDII：长期上行 + 近期走高（高分位、已达止盈目标）——
    f1 = _ramp(_walk(1.00, N, 0.0006, 0.012, seed=1), k=12, step=0.0025)
    cost1 = round(f1[-1] / 1.36, 4)   # 持仓收益约 +36% → 触发目标止盈
    h1 = Holding(code="270042", name="（示例）纳指100指数QDII", asset_class=AssetClass.US_EQUITY,
                 shares=12000, cost_nav=cost1, target_weight=0.45, is_dca=True, annual_fee=0.008,
                 tracking=Tracking(index="^NDX", beta=1.0, lag_days=2, currency_hedged=False))

    # —— 标普500 QDII：稳健上行（持有 / 继续定投）——
    f2 = _walk(1.50, N, 0.0005, 0.009, seed=2)
    cost2 = round(f2[-1] / 1.12, 4)   # 约 +12%
    h2 = Holding(code="050025", name="（示例）标普500指数QDII", asset_class=AssetClass.US_EQUITY,
                 shares=8000, cost_nav=cost2, target_weight=0.30, is_dca=True, annual_fee=0.006,
                 tracking=Tracking(index="^GSPC", beta=0.98, lag_days=1, currency_hedged=False))

    # —— 沪深300（A股，无时差）：近期走弱（低位 / 超卖 → 适合定投）——
    f3 = _ramp(_walk(1.30, N, -0.0002, 0.011, seed=7), k=10, step=-0.004)
    cost3 = round(f3[-1] / 0.84, 4)   # 约 -16%（亏损、低分位）
    h3 = Holding(code="110020", name="（示例）沪深300指数", asset_class=AssetClass.CN_EQUITY,
                 shares=10000, cost_nav=cost3, target_weight=0.25, is_dca=True,
                 tracking=Tracking(index=None))

    holdings = [h1, h2, h3]
    nav_map = {
        "270042": _navpoints(f1, today),
        "050025": _navpoints(f2, today),
        "110020": _navpoints(f3, today),
    }
    quote_map = {
        h.code: Quote(code=h.code, name=h.name, nav=nav_map[h.code][-1].nav,
                      nav_date=today, source="demo")
        for h in holdings
    }

    # 指数行情：纳指最近两日明显上涨、标普最近一日上涨 → 估算出「尚未体现」的正收益
    ndx = _walk(15000, N, 0.0008, 0.012, seed=11)
    ndx[-2] = ndx[-3] * 1.018   # 倒数第2个交易日 +1.8%
    ndx[-1] = ndx[-2] * 1.011   # 最近一个交易日 +1.1%
    spx = _walk(5200, N, 0.0005, 0.008, seed=12)
    spx[-1] = spx[-2] * 1.009   # 最近一日 +0.9%
    index_map = {
        "^NDX": _index_returns(ndx, today),
        "^GSPC": _index_returns(spx, today),
    }
    # 汇率：美元兑人民币最近一日小幅升值（利好未对冲的美股 QDII）
    fx_vals = _walk(7.20, N, 0.0, 0.003, seed=20)
    fx_vals[-1] = fx_vals[-2] * 1.002
    fx_returns = _index_returns(fx_vals, today)

    market_brief = [
        "纳指100（2026-06-18）+1.10%", "标普500（2026-06-18）+0.90%",
        "道指（2026-06-18）+0.45%", "美元兑人民币 +0.20%（未对冲的美股 QDII 受其影响）",
        "（演示数据，非真实行情）",
    ]
    return holdings, nav_map, quote_map, index_map, fx_returns, market_brief
