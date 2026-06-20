"""美股指数 / 汇率日线行情。

主源：Yahoo Finance chart 接口
    https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=2y&interval=1d
兜底：stooq CSV
    https://stooq.com/q/d/l/?s={sym}&i=d

返回统一为 (date, close) 升序列表；并提供 returns() 转日收益。
"""
from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Tuple

from .base import HttpClient

# Yahoo ticker → stooq symbol（兜底用）
_STOOQ_MAP: Dict[str, str] = {
    "^GSPC": "^spx",
    "^NDX": "^ndx",
    "^IXIC": "^ndq",
    "^DJI": "^dji",
    "^SOX": "^sox",
    "CNY=X": "usdcny",
}

# 内部代码 → Yahoo 可用 ticker（沪深300等国内指数）
_YAHOO_TICKER_MAP: Dict[str, str] = {
    "000300": "000300.SS",
    "000905": "000905.SS",
    "000016": "000016.SS",
}

# 市场情绪指标
_MARKET_INDICATORS = {
    "vix": {"ticker": "^VIX", "label": "VIX 恐慌指数", "low": 15, "high": 25, "desc": "<15=平静 15-20=正常 20-25=紧张 25-30=恐慌 >30=极度恐慌"},
    "dxy": {"ticker": "DX-Y.NYB", "label": "美元指数 DXY", "low": 95, "high": 105, "desc": ">105=强美元利空QDII <95=弱美元利好QDII"},
    "us10y": {"ticker": "^TNX", "label": "美国10年期国债收益率", "low": 3.0, "high": 5.0, "desc": "高利率压制科技股估值 低利率利好成长股"},
    "gold": {"ticker": "GC=F", "label": "黄金期货", "low": 1800, "high": 2200, "desc": "金价涨=避险情绪升 利空风险资产"},
    "oil": {"ticker": "CL=F", "label": "原油期货 WTI", "low": 60, "high": 90, "desc": "油价过高压制消费和经济 适度有利"},
    "btc": {"ticker": "BTC-USD", "label": "比特币", "low": 50000, "high": 100000, "desc": "风险偏好风向标 涨=risk-on"},
}

# 大行观点搜索关键词
_INSTITUTION_TOPICS = [
    "纳斯达克 科技股 2026 展望",
    "美联储 利率 降息 2026",
    "美股 估值 泡沫 回调",
    "AI 人工智能 科技 投资",
    "QDII 海外投资 2026",
    "中国 美股 资金流向",
    "全球科技股 机构观点",
]


class MarketIndex:
    def __init__(self, http: HttpClient):
        self.http = http

    # ---- 主源：Yahoo ----
    def _yahoo(self, ticker: str, rng: str = "2y") -> List[Tuple[date, float]]:
        yahoo_ticker = _YAHOO_TICKER_MAP.get(ticker, ticker)
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_ticker}"
               f"?range={rng}&interval=1d")
        text = self.http.get(url, cache_key=f"yahoo:{yahoo_ticker}:{rng}")
        if not text:
            return []
        try:
            data = json.loads(text)
            result = data["chart"]["result"][0]
            ts = result["timestamp"]
            closes = result["indicators"]["quote"][0]["close"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            return []
        out: List[Tuple[date, float]] = []
        for t, c in zip(ts, closes):
            if c is None:
                continue
            d = datetime.fromtimestamp(t, tz=timezone.utc).date()
            out.append((d, float(c)))
        out.sort(key=lambda x: x[0])
        return out

    # ---- 兜底：stooq ----
    def _stooq(self, ticker: str) -> List[Tuple[date, float]]:
        sym = _STOOQ_MAP.get(ticker)
        if not sym:
            return []
        url = f"https://stooq.com/q/d/l/?s={sym}&i=d"
        text = self.http.get(url, cache_key=f"stooq:{sym}")
        if not text:
            return []
        out: List[Tuple[date, float]] = []
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            try:
                d = datetime.strptime(row["Date"], "%Y-%m-%d").date()
                c = float(row["Close"])
            except (KeyError, ValueError):
                continue
            out.append((d, c))
        out.sort(key=lambda x: x[0])
        return out

    def closes(self, ticker: str, rng: str = "2y") -> List[Tuple[date, float]]:
        data = self._yahoo(ticker, rng)
        if not data:
            data = self._stooq(ticker)
        return data

    def returns(self, ticker: str, rng: str = "2y") -> List[Tuple[date, float]]:
        """日收益序列 (date, ret) 升序；date 取『较晚一日』。"""
        closes = self.closes(ticker, rng)
        out: List[Tuple[date, float]] = []
        for i in range(1, len(closes)):
            d0, c0 = closes[i - 1]
            d1, c1 = closes[i]
            if c0:
                out.append((d1, c1 / c0 - 1.0))
        return out

    def get_market_snapshot(self) -> List[dict]:
        """获取市场情绪指标快照（VIX、DXY、美债、黄金、原油、比特币）。"""
        import statistics
        indicators = []
        for key, cfg in _MARKET_INDICATORS.items():
            closes = self.closes(cfg["ticker"], rng="3mo")
            if not closes:
                continue
            current = closes[-1][1]
            prev = closes[0][1] if len(closes) > 1 else current
            # 计算近20日均值和标准差
            recent = [c[1] for c in closes[-20:]] if len(closes) >= 20 else [c[1] for c in closes]

            # 判断状态
            if current < cfg["low"]:
                level = "low"
                color = "#16a34a"  # green
            elif current > cfg["high"]:
                level = "high"
                color = "#dc2626"  # red
            else:
                level = "normal"
                color = "#f59e0b"  # amber

            # 计算 value 在 low-high 区间中的百分比位置（用于可视化）
            rng = cfg["high"] - cfg["low"]
            value_percent = max(5, min(95, (current - cfg["low"]) / rng * 100)) if rng > 0 else 50

            indicators.append({
                "key": key,
                "label": cfg["label"],
                "value": round(current, 2),
                "change_pct": round((current / prev - 1) * 100, 1) if prev else 0,
                "level": level,
                "color": color,
                "desc": cfg["desc"],
                "ma20": round(statistics.mean(recent), 2) if recent else None,
                "value_percent": round(value_percent, 0),
                "low": cfg["low"],
                "high": cfg["high"],
            })
        return indicators
