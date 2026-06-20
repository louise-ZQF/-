"""基金元数据缓存：从天天基金 pingzhongdata JS 抓取成立日期 + fundf10 抓取年费率，存入 SQLite。

避免反复爬取，加速筛选器。
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from .db import get_meta, upsert_meta


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
    """获取基金元数据。优先读 SQLite，否则抓取 pingzhongdata JS。"""
    # 读 SQLite 缓存
    if not force_refresh:
        cached = get_meta(code)
        if cached:
            return cached

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

    # 存入 SQLite
    upsert_meta(code, info)
    return info


def get_inception_date(http, code: str) -> Optional[str]:
    """快捷获取成立日期。"""
    meta = get_metadata(http, code)
    return meta.get("inception_date")
