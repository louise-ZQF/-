"""自选基金决策引擎：质量×择时 → 买入结论 + 组合相关性 + 买点提醒。"""
from __future__ import annotations

import math
import os
import statistics
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

import yaml

from .models import WatchItem, AssetClass, Tracking


WATCHLIST_FILE = "config/watchlist.yaml"


# ---------------------------------------------------------------------------
# 读写
# ---------------------------------------------------------------------------

def load_watchlist() -> List[WatchItem]:
    if not os.path.exists(WATCHLIST_FILE):
        return []
    with open(WATCHLIST_FILE, "r") as f:
        raw = yaml.safe_load(f) or {}
    items = raw.get("watchlist", []) or []
    result = []
    for d in items:
        try:
            ac = d.get("asset_class", "other")
            try:
                asset_class = AssetClass(ac)
            except ValueError:
                asset_class = AssetClass.OTHER
            tk = d.get("tracking") or {}
            tracking = Tracking(
                index=tk.get("index"),
                lag_days=int(tk.get("lag_days", 1)),
                currency_hedged=bool(tk.get("currency_hedged", False)),
            )
            result.append(WatchItem(
                code=str(d["code"]),
                name=d.get("name", ""),
                asset_class=asset_class,
                added_at=d.get("added_at", ""),
                note=d.get("note", ""),
                target_buy=d.get("target_buy"),
                tracking=tracking,
                annual_fee=float(d.get("annual_fee", 0) or 0),
            ))
        except (KeyError, ValueError):
            continue
    return result


def save_watchlist(items: List[WatchItem]):
    os.makedirs(os.path.dirname(WATCHLIST_FILE), exist_ok=True)
    data = {
        "watchlist": [
            {
                "code": w.code, "name": w.name, "asset_class": w.asset_class.value,
                "added_at": w.added_at, "note": w.note,
                "target_buy": w.target_buy,
                "tracking": {"index": w.tracking.index, "lag_days": w.tracking.lag_days,
                             "currency_hedged": w.tracking.currency_hedged},
                "annual_fee": w.annual_fee,
            }
            for w in items
        ]
    }
    with open(WATCHLIST_FILE, "w") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


# ---------------------------------------------------------------------------
# 决策引擎：质量分 × 择时分 → 买入结论
# ---------------------------------------------------------------------------

def decide_buy(quality_score: float, timing_score: float,
               correlation_warning: str = "") -> dict:
    """买入决策矩阵。

    质量高 + 时机好 → 买入
    质量高 + 时机差 → 等回调
    质量中 + 时机好 → 小仓试探
    质量低 → 不买
    """
    if quality_score >= 65:
        if timing_score >= 65:
            return {"decision": "buy", "label": "✅ 值得买入", "color": "#16a34a",
                    "advice": "质量优+时机好，可分批建仓或启动定投"}
        elif timing_score >= 40:
            return {"decision": "wait", "label": "⏳ 等回调", "color": "#f59e0b",
                    "advice": "质量优但时机一般，先加入观察，等估值回落或RSI回调再买"}
        else:
            return {"decision": "wait", "label": "⏳ 等更好时机", "color": "#f59e0b",
                    "advice": "质量优但当前高位，建议设买点提醒等回调"}
    elif quality_score >= 40:
        if timing_score >= 60:
            return {"decision": "small", "label": "🟡 小仓试探", "color": "#f59e0b",
                    "advice": "质量中等但时机不错，可极小仓位试探，不适合重仓"}
        else:
            return {"decision": "skip", "label": "🔴 暂不建议", "color": "#dc2626",
                    "advice": "质量中等+时机一般，优先选更优质的标的"}
    else:
        return {"decision": "skip", "label": "🔴 不建议买入", "color": "#dc2626",
                "advice": "质量偏低，建议换一只同类型的优质基金"}


# ---------------------------------------------------------------------------
# 组合相关性
# ---------------------------------------------------------------------------

def compute_correlation(watch_navs: List[float],
                        holdings_navs_map: Dict[str, List[float]]) -> List[dict]:
    """计算自选基金与各持仓基金的相关性。

    watch_navs: 自选基金的净值收益率序列
    holdings_navs_map: {持仓代码: 净值收益率序列}
    返回: [{code, name, correlation, warning}]
    """
    if len(watch_navs) < 20:
        return []
    watch_rets = [watch_navs[i]/watch_navs[i-1]-1 for i in range(1, len(watch_navs)) if watch_navs[i-1]]
    results = []
    for code, navs in holdings_navs_map.items():
        if len(navs) < 20:
            continue
        h_rets = [navs[i]/navs[i-1]-1 for i in range(1, len(navs)) if navs[i-1]]
        # 对齐长度
        min_len = min(len(watch_rets), len(h_rets))
        if min_len < 10:
            continue
        w = watch_rets[-min_len:]
        h = h_rets[-min_len:]
        # Pearson correlation
        try:
            w_mean = statistics.mean(w)
            h_mean = statistics.mean(h)
            w_std = statistics.stdev(w) if len(w) > 1 else 0
            h_std = statistics.stdev(h) if len(h) > 1 else 0
            if w_std == 0 or h_std == 0:
                continue
            corr = sum((w[i]-w_mean)*(h[i]-h_mean) for i in range(min_len)) / ((min_len-1)*w_std*h_std)
            corr = max(-1, min(1, corr))
            if corr > 0.7:
                warning = f"⚠️ 与你持仓高度相关(r={corr:.2f})，买入≈加仓同类，分散度提升有限"
            elif corr > 0.4:
                warning = f"中等相关(r={corr:.2f})，有一定分散效果"
            else:
                warning = f"✅ 低相关(r={corr:.2f})，分散效果好"
            results.append({"code": code, "correlation": round(corr, 2), "warning": warning})
        except Exception:
            continue
    return sorted(results, key=lambda x: -x["correlation"])


# ---------------------------------------------------------------------------
# 买点提醒
# ---------------------------------------------------------------------------

def check_buy_alerts(watch_items: List[WatchItem],
                     factor_data: Dict[str, any]) -> List[dict]:
    """检查自选基金是否触发买点提醒。"""
    alerts = []
    for w in watch_items:
        fs = factor_data.get(w.code)
        if not fs:
            continue
        tb = w.target_buy or {}
        triggered = []
        if tb.get("valuation_pct") and fs.value >= 100 - tb["valuation_pct"] * 100:
            triggered.append(f"估值分位达标({fs.value:.0f})")
        if tb.get("rsi_below") and fs.momentum <= 50:  # momentum low ≈ RSI low
            triggered.append(f"动量偏弱({fs.momentum:.0f})")
        if triggered:
            alerts.append({
                "code": w.code, "name": w.name,
                "message": f"{w.name} 接近买点：" + "、".join(triggered),
                "level": "🟢",
                "action": f"可考虑分批建仓或设提醒",
            })
    return alerts
