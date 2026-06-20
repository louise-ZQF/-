"""基金元数据缓存：从天天基金 pingzhongdata JS 抓取成立日期 + fundf10 抓取年费率，存入本地 JSON。

避免反复爬取，加速筛选器。
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime
from typing import Dict, Optional

CACHE_FILE = "data/fund_meta.json"


def _load_cache() -> dict:
    if not os.path.exists(CACHE_FILE):
        return {}
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_cache(cache: dict):
    os.makedirs("data", exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _scrape_fees(http, code: str) -> Optional[float]:
    """从 fundf10 费率页面抓取综合年费率。"""
    try:
        url = f"http://fundf10.eastmoney.com/jjfl_{code}.html"
        text = http.get(url, cache_key=f"fund_fee:{code}",
                        headers={"Referer": "http://fund.eastmoney.com/"})
        if not text:
            return None

        mgmt = cust = sales = 0.0
        found = False

        m = re.search(r'管理费率[：:<\s/td>]*</td>\s*<td[^>]*>\s*([\d.]+)%', text)
        if m: mgmt = float(m.group(1)) / 100; found = True

        m = re.search(r'托管费率[：:<\s/td>]*</td>\s*<td[^>]*>\s*([\d.]+)%', text)
        if m: cust = float(m.group(1)) / 100; found = True

        m = re.search(r'销售服务费[：:<\s/td>]*</td>\s*<td[^>]*>\s*([\d.]+)%', text)
        if m: sales = float(m.group(1)) / 100; found = True

        if found:
            return round(mgmt + cust + sales, 4)
        return None
    except Exception:
        return None


def get_metadata(http, code: str, force_refresh: bool = False) -> dict:
    """获取基金元数据。优先读缓存（24h有效），否则抓取 pingzhongdata JS。"""
    cache = _load_cache()

    # 读缓存
    if not force_refresh and code in cache:
        entry = cache[code]
        cached_at = entry.get("_ts", "")
        try:
            cached_date = datetime.strptime(cached_at[:10], "%Y-%m-%d").date()
            if (date.today() - cached_date).days < 1:
                return {k: v for k, v in entry.items() if not k.startswith("_")}
        except (ValueError, TypeError):
            pass

    # 抓取
    info = {}
    try:
        js_url = f"http://fund.eastmoney.com/pingzhongdata/{code}.js"
        js_text = http.get(js_url, cache_key=f"fund_meta_js:{code}",
                           headers={"Referer": "http://fund.eastmoney.com/"})
        if js_text:
            # 成立日期
            m = re.search(r'fS_establishDate\s*=\s*"(\d{4}-\d{2}-\d{2})"', js_text)
            if m:
                info["inception_date"] = m.group(1)
            # 名称
            m = re.search(r'fS_name\s*=\s*"([^"]+)"', js_text)
            if m:
                info["name"] = m.group(1)
    except Exception:
        pass

    info["annual_fee"] = _scrape_fees(http, code)
    info["_ts"] = date.today().isoformat()
    cache[code] = info

    # 只保留最近 1000 条
    if len(cache) > 1000:
        keys = sorted(cache.keys(), key=lambda k: cache[k].get("_ts", ""), reverse=True)
        cache = {k: cache[k] for k in keys[:1000]}

    _save_cache(cache)
    return {k: v for k, v in info.items() if not k.startswith("_")}


def get_inception_date(http, code: str) -> Optional[str]:
    """快捷获取成立日期。"""
    meta = get_metadata(http, code)
    return meta.get("inception_date")
