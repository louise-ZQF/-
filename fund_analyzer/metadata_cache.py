"""基金元数据缓存：从天天基金 pingzhongdata JS 抓取成立日期 + fundf10 抓取年费率，存入 SQLite。

避免反复爬取，加速筛选器。
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

from .db import get_meta, upsert_meta

# Conservative fee estimates by fund type, used when scraping fails
_TYPE_FEE_ESTIMATES = {
    "us_equity_passive": 0.0075,  # US index QDII: ~0.6% mgmt + 0.15% custody
    "us_equity_active": 0.015,    # Active QDII: ~1.2% mgmt + 0.3% other
    "cn_equity_passive": 0.005,   # A-share index: ~0.5%
    "cn_equity_active": 0.015,    # A-share active: ~1.5%
    "hk_equity": 0.008,
    "bond": 0.003,
}


def _estimate_by_type(fc) -> Optional[float]:
    """按基金类型返回保守费率估计。"""
    if not fc:
        return None
    if fc.fund_type == "bond":
        return _TYPE_FEE_ESTIMATES["bond"]
    fe_map = {
        ("us", "passive_index"): "us_equity_passive",
        ("us", "active_equity"): "us_equity_active",
        ("cn", "passive_index"): "cn_equity_passive",
        ("cn", "active_equity"): "cn_equity_active",
        ("hk", "passive_index"): "hk_equity",
        ("hk", "active_equity"): "hk_equity",
    }
    key = fe_map.get((fc.asset_region, fc.fund_type))
    if key:
        return _TYPE_FEE_ESTIMATES[key]
    # Fallback for unhandled combos (global, active_hybrid, other)
    if fc.fund_type in ("passive_index",):
        return _TYPE_FEE_ESTIMATES["cn_equity_passive"]
    return _TYPE_FEE_ESTIMATES["cn_equity_active"]


def _scrape_fees(http, code: str, name: str = ""):
    """从多个数据源抓取综合年费率。返回 (fee, estimated) 元组。"""
    # Source 1: F10DataApi (returns HTML table or XML)
    try:
        url = f"http://fundf10.eastmoney.com/F10DataApi.aspx?type=jjfl&code={code}"
        text = http.get(url, cache_key=f"fund_fee_api:{code}",
                        headers={"Referer": "http://fund.eastmoney.com/"})
        if text:
            mgmt = cust = sales = 0.0
            found = False
            # Primary: HTML table pattern (管理费</td><td>1.50%</td>)
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
            # Fallback: simpler label-value patterns (管理费:1.50%)
            if not found:
                for pattern, var in [
                    (r'管理费[：:]\s*([\d.]+)\s*%', 'mgmt'),
                    (r'托管费[：:]\s*([\d.]+)\s*%', 'cust'),
                    (r'销售服务费[：:]\s*([\d.]+)\s*%', 'sales'),
                ]:
                    m = re.search(pattern, text)
                    if m:
                        if var == 'mgmt': mgmt = float(m.group(1)) / 100; found = True
                        elif var == 'cust': cust = float(m.group(1)) / 100; found = True
                        elif var == 'sales': sales = float(m.group(1)) / 100; found = True
            if found:
                return (round(mgmt + cust + sales, 4), False)
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
                return (estimated, True)
    except Exception:
        pass

    # Source 3: Type-based conservative estimate
    if name:
        from .fund_classifier import classify_fund
        try:
            fc = classify_fund(code, name)
            fee = _estimate_by_type(fc)
            if fee is not None:
                return (fee, True)
        except Exception:
            pass

    return (None, False)


def _scrape_fees_v2(http, code: str) -> Optional[float]:
    """Multi-source fee scraping. Returns combined annual fee (mgmt + cust) or None."""
    import re

    # Source 1: Try the F10DataApi for fee info
    try:
        url = f"http://fundf10.eastmoney.com/F10DataApi.aspx?type=jjfl&code={code}"
        text = http.get(url, cache_key=f"fee_v2:{code}",
                        headers={"Referer": "http://fund.eastmoney.com/"})
        if text:
            mgmt = cust = 0.0
            found = False
            for pattern, target in [
                (r'管理费[^<]*</t[dh]>\s*<t[dh][^>]*>\s*([\d.]+)\s*%', 'mgmt'),
                (r'托管费[^<]*</t[dh]>\s*<t[dh][^>]*>\s*([\d.]+)\s*%', 'cust'),
            ]:
                m = re.search(pattern, text)
                if m and target == 'mgmt':
                    mgmt = float(m.group(1)) / 100
                    found = True
                elif m and target == 'cust':
                    cust = float(m.group(1)) / 100
                    found = True
            if found:
                return round(mgmt + cust, 4)
    except Exception:
        pass

    return None


def get_metadata(http, code: str, force_refresh: bool = False) -> dict:
    """获取基金元数据。优先读 SQLite，否则抓取 pingzhongdata JS。"""
    # 读 SQLite 缓存 (up to 7 days old)
    if not force_refresh:
        cached = get_meta(code)
        if cached:
            cached_date_str = cached.get("updated_at")
            if cached_date_str:
                try:
                    cached_date = date.fromisoformat(cached_date_str)
                    if (date.today() - cached_date).days < 7:
                        return cached
                except ValueError:
                    pass
            else:
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
            # 经理名称 (via simple variable, fallback)
            m = re.search(r'fS_manager\s*=\s*"([^"]+)"', js_text)
            if m:
                info["manager_name"] = m.group(1)
            # 经理任职起始日期 (fallback)
            m = re.search(r'fS_managerStartDate\s*=\s*"(\d{4}-\d{2}-\d{2})"', js_text)
            if m:
                info["manager_start_date"] = m.group(1)

            # Extract fund size from Data_fluctuationScale
            m = re.search(r'Data_fluctuationScale\s*=\s*(\{.*?\});', js_text, re.DOTALL)
            if m:
                try:
                    import json as _json
                    scale_data = _json.loads(m.group(1))
                    series_list = scale_data.get("series", [])
                    for s in series_list:
                        if "资产规模" in s.get("name", ""):
                            data_points = s.get("data", [])
                            for v in reversed(data_points):
                                if v is not None and v > 0:
                                    info["fund_size"] = float(v) * 1e8
                                    break
                    # Try to extract inception_date from Data_fluctuationScale categories
                    if "inception_date" not in info:
                        categories = scale_data.get("categories", [])
                        if categories:
                            for cat in categories:
                                if re.match(r'\d{4}-\d{2}-\d{2}', str(cat)):
                                    info["inception_date"] = str(cat)
                                    break
                except Exception:
                    pass

            # Extract manager info from Data_currentFundManager (structured JSON)
            m = re.search(r'Data_currentFundManager\s*=\s*(\{.*?\});', js_text, re.DOTALL)
            if m:
                try:
                    import json as _json
                    mgr_data = _json.loads(m.group(1))
                    info["manager_name"] = mgr_data.get("name", "")
                    start_date = mgr_data.get("startDate", "")
                    if start_date:
                        info["manager_start_date"] = start_date
                        from datetime import datetime
                        try:
                            sd = datetime.strptime(start_date[:10], "%Y-%m-%d").date()
                            info["manager_years"] = round((date.today() - sd).days / 365.25, 1)
                        except Exception:
                            pass
                except Exception:
                    pass
    except Exception:
        pass

    fee = _scrape_fees_v2(http, code)
    info["annual_fee"] = fee

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
