"""基金元数据缓存：从天天基金 pingzhongdata JS 抓取成立日期 + fundf10 抓取年费率，存入 SQLite。

避免反复爬取，加速筛选器。
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from .db import get_meta, upsert_meta


def _scrape_fees(http, code: str) -> Optional[float]:
    """从多个数据源抓取综合年费率。"""
    # Source 1: F10DataApi (returns HTML table)
    try:
        url = f"http://fundf10.eastmoney.com/F10DataApi.aspx?type=jjfl&code={code}"
        text = http.get(url, cache_key=f"fund_fee_api:{code}",
                        headers={"Referer": "http://fund.eastmoney.com/"})
        if text:
            mgmt = cust = sales = 0.0
            found = False
            for pattern, var in [
                (r'管理费[^<]*</td><td[^>]*>\s*([\d.]+)\s*%', 'mgmt'),
                (r'托管费[^<]*</td><td[^>]*>\s*([\d.]+)\s*%', 'cust'),
                (r'销售服务费[^<]*</td><td[^>]*>\s*([\d.]+)\s*%', 'sales'),
            ]:
                m = re.search(pattern, text)
                if m:
                    if var == 'mgmt': mgmt = float(m.group(1)) / 100; found = True
                    elif var == 'cust': cust = float(m.group(1)) / 100; found = True
                    elif var == 'sales': sales = float(m.group(1)) / 100; found = True
            if found:
                return round(mgmt + cust + sales, 4)
    except Exception:
        pass

    # Source 2: pingzhongdata JS — estimate from purchase rate
    try:
        js_url = f"http://fund.eastmoney.com/pingzhongdata/{code}.js"
        js_text = http.get(js_url, cache_key=f"fund_meta_js:{code}",
                           headers={"Referer": "http://fund.eastmoney.com/"})
        if js_text:
            m = re.search(r'fund_sourceRate\s*=\s*"([\d.]+)"', js_text)
            if m:
                purchase_rate = float(m.group(1)) / 100
                # Rough heuristic for QDII: mgmt ≈ purchase_rate * 0.4, cust ≈ purchase_rate * 0.15
                estimated = round(purchase_rate * 0.4 + purchase_rate * 0.15, 4)
                return estimated
    except Exception:
        pass

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
            # 经理名称
            m = re.search(r'fS_manager\s*=\s*"([^"]+)"', js_text)
            if m:
                info["manager_name"] = m.group(1)
            # 经理任职起始日期
            m = re.search(r'fS_managerStartDate\s*=\s*"(\d{4}-\d{2}-\d{2})"', js_text)
            if m:
                info["manager_start_date"] = m.group(1)
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


def test_scraper(http):
    """对已知基金运行诊断，打印哪些数据源可用。"""
    code = "270042"
    print(f"\n=== 基金元数据抓取诊断: {code} ===")

    # Test F10DataApi
    try:
        url = f"http://fundf10.eastmoney.com/F10DataApi.aspx?type=jjfl&code={code}"
        text = http.get(url, cache_key=f"test_fee_api:{code}",
                        headers={"Referer": "http://fund.eastmoney.com/"})
        if text:
            mgmt = re.search(r'管理费[^<]*</td><td[^>]*>\s*([\d.]+)\s*%', text)
            cust = re.search(r'托管费[^<]*</td><td[^>]*>\s*([\d.]+)\s*%', text)
            sales = re.search(r'销售服务费[^<]*</td><td[^>]*>\s*([\d.]+)\s*%', text)
            print(f"F10DataApi: {'OK' if any([mgmt, cust, sales]) else 'FAIL'} "
                  f"(管理={mgmt.group(1)+'%' if mgmt else 'N/A'}, "
                  f"托管={cust.group(1)+'%' if cust else 'N/A'}, "
                  f"销售={sales.group(1)+'%' if sales else 'N/A'})")
        else:
            print("F10DataApi: no response")
    except Exception as e:
        print(f"F10DataApi: error - {e}")

    # Test pingzhongdata
    try:
        js_url = f"http://fund.eastmoney.com/pingzhongdata/{code}.js"
        js_text = http.get(js_url, cache_key=f"test_meta_js:{code}",
                           headers={"Referer": "http://fund.eastmoney.com/"})
        if js_text:
            name = re.search(r'fS_name\s*=\s*"([^"]+)"', js_text)
            date = re.search(r'fS_establishDate\s*=\s*"(\d{4}-\d{2}-\d{2})"', js_text)
            mgr = re.search(r'fS_manager\s*=\s*"([^"]+)"', js_text)
            rate = re.search(r'fund_sourceRate\s*=\s*"([\d.]+)"', js_text)
            print(f"pingzhongdata: OK (name={name.group(1) if name else 'N/A'}, "
                  f"date={date.group(1) if date else 'N/A'}, "
                  f"manager={mgr.group(1) if mgr else 'N/A'}, "
                  f"sourceRate={rate.group(1) if rate else 'N/A'})")
        else:
            print("pingzhongdata: no response")
    except Exception as e:
        print(f"pingzhongdata: error - {e}")

    # Test full metadata
    meta = get_metadata(http, code)
    print(f"Metadata result: {meta}")
    print("=== 诊断完成 ===\n")
    return meta
