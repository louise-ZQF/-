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


class MarketIndex:
    def __init__(self, http: HttpClient):
        self.http = http

    # ---- 主源：Yahoo ----
    def _yahoo(self, ticker: str, rng: str = "2y") -> List[Tuple[date, float]]:
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
               f"?range={rng}&interval=1d")
        text = self.http.get(url, cache_key=f"yahoo:{ticker}:{rng}")
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
