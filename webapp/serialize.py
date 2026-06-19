"""把分析结果（dataclass）转成前端友好的 JSON 字典。"""
from __future__ import annotations

from typing import List, Optional

from fund_analyzer.models import Action, FundAnalysis, PortfolioReport

# 操作建议 → 类别（前端据此上色）
_ACTION_KIND = {
    Action.BUY_MORE: "buy",
    Action.DCA_CONTINUE: "hold_pos",
    Action.HOLD: "hold",
    Action.DCA_PAUSE: "caution",
    Action.TRIM: "trim",
    Action.SELL: "sell",
}


def _downsample(points: list, max_n: int = 160) -> list:
    """历史净值降采样，控制前端载荷大小。"""
    if not points:
        return []
    pts = points[-max_n * 3:] if len(points) > max_n * 3 else list(points)
    step = max(1, len(pts) // max_n)
    out = pts[::step]
    if out and out[-1] is not pts[-1]:
        out.append(pts[-1])
    return [{"d": p.d.isoformat(), "nav": round(p.nav, 4)} for p in out]


def _signal_kind(vote: float, hard: bool) -> str:
    if hard:
        return "hard"
    if vote > 0:
        return "pos"
    if vote < 0:
        return "neg"
    return "neutral"


def fund_to_dict(fa: FundAnalysis) -> dict:
    m = fa.metrics
    h = fa.holding
    e = fa.estimate
    # 市值优先用 shares*nav，否则用用户填的 current_value
    mv = fa.market_value or h.current_value or None
    iv = fa.implied_value
    d = {
        "code": h.code,
        "name": h.name or h.code,
        "asset_class": h.asset_class.value,
        "is_dca": h.is_dca,
        "current_value": h.current_value,
        "dca_plan": {"frequency": h.dca_plan.frequency, "amount": h.dca_plan.amount} if h.dca_plan else None,
        "action": fa.action.value,
        "action_kind": _ACTION_KIND.get(fa.action, "hold"),
        "score": round(fa.score, 1),
        "rationale": fa.rationale,
        "market_value": mv,
        "implied_value": iv,
        "metrics": {
            "last_nav": m.last_nav,
            "holding_return": m.holding_return,
            "ret_1w": m.ret_1w, "ret_1m": m.ret_1m, "ret_3m": m.ret_3m, "ret_1y": m.ret_1y,
            "ma20": m.ma20, "ma60": m.ma60, "ma120": m.ma120,
            "rsi14": m.rsi14, "max_drawdown": m.max_drawdown,
            "vol_annual": m.vol_annual, "sharpe": m.sharpe,
            "price_percentile": m.price_percentile,
        },
        "signals": [
            {"name": s.name, "text": s.text, "kind": _signal_kind(s.vote, s.hard)}
            for s in fa.signals
        ],
        "history": _downsample(fa.history),
        "tracking": {
            "index": h.tracking.index,
            "lag_days": h.tracking.lag_days,
            "currency_hedged": h.tracking.currency_hedged,
        },
    }
    if e and e.has_estimate:
        d["estimate"] = {
            "cum_return": e.cum_return,
            "band": e.band,
            "implied_nav": e.implied_nav,
            "base_nav": e.base_nav,
            "method": e.method,
            "index": h.tracking.index,
            "lag_days": h.tracking.lag_days,
            "detail": e.detail,
        }
    else:
        d["estimate"] = None
    return d


def report_to_dict(rep: PortfolioReport, title: str, mode: str) -> dict:
    funds = [fund_to_dict(fa) for fa in rep.funds]

    # 资产大类分布（按市值，fallback 到 current_value）
    alloc = {}
    for fa in rep.funds:
        mv = fa.market_value or fa.holding.current_value or 0.0
        if mv:
            alloc[fa.holding.asset_class.value] = alloc.get(fa.holding.asset_class.value, 0.0) + mv
    total = sum(alloc.values()) or 1.0
    allocation = [
        {"label": k, "value": round(v, 2), "pct": v / total}
        for k, v in sorted(alloc.items(), key=lambda x: -x[1])
    ]

    total_return = None
    # total_value 优先用 rep 的，否则汇总 current_value
    tv = rep.total_value
    if tv is None:
        tv = sum(fa.holding.current_value for fa in rep.funds)
    tc = rep.total_cost
    if tv and tc:
        total_return = tv / tc - 1.0
    has_val = tv is not None and tv > 0

    # 重点提示
    highlight_kinds = {"buy", "caution", "trim", "sell"}
    highlights = [f for f in funds if f["action_kind"] in highlight_kinds]

    return {
        "as_of": rep.as_of.strftime("%Y-%m-%d %H:%M"),
        "title": title,
        "mode": mode,
        "overview": {
            "total_value": tv,
            "total_implied_value": rep.total_implied_value,
            "est_today_change": rep.est_today_change,
            "total_cost": tc,
            "total_return": total_return,
            "has_value": has_val,
        },
        "highlights": highlights,
        "funds": funds,
        "allocation": allocation,
        "portfolio_notes": rep.portfolio_notes,
        "market_brief": rep.market_brief,
    }
