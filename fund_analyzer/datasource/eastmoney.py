"""天天基金（东方财富）数据源。

接口（均为公开网页接口，可能随官网调整，失败会自动降级）：
    实时估值: https://fundgz.1234567.com.cn/js/{code}.js
              返回 jsonpgz({...})，字段：dwjz=上一日净值, gsz=估算净值,
              gszzl=估算涨跌幅(%), gztime=估值时间, jzrq=净值日期, name=基金名
    历史净值: https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex=1&pageSize=N
              需带 Referer。返回 JSON：Data.LSJZList[{FSRQ 日期, DWJZ 单位净值,
              LJJZ 累计净值, JZZZL 当日涨跌幅(%)}]
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import List, Optional

from ..models import NavPoint, Quote
from .base import HttpClient

_JSONP_RE = re.compile(r"jsonpgz\((.*)\)\s*;?\s*$", re.S)


def _to_float(x) -> Optional[float]:
    try:
        if x in (None, "", "---"):
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _to_date(s: str) -> Optional[date]:
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


class EastMoney:
    def __init__(self, http: HttpClient):
        self.http = http

    # ---- 实时估值 ----
    def realtime(self, code: str) -> Optional[Quote]:
        url = f"https://fundgz.1234567.com.cn/js/{code}.js"
        # 实时估值不长期缓存（盘中会变），用很短的 key
        text = self.http.get(url, cache_key=f"gz:{code}")
        if not text:
            return None
        mt = _JSONP_RE.search(text.strip())
        if not mt:
            return None
        try:
            d = json.loads(mt.group(1))
        except json.JSONDecodeError:
            return None
        gszzl = _to_float(d.get("gszzl"))
        return Quote(
            code=code,
            name=d.get("name", ""),
            nav=_to_float(d.get("dwjz")),
            nav_date=_to_date(d.get("jzrq", "")),
            gsz=_to_float(d.get("gsz")),
            gsz_change=(gszzl / 100.0 if gszzl is not None else None),
            gsz_time=d.get("gztime"),
            source="eastmoney",
        )

    # ---- 基金元数据 ----
    def fund_info(self, code: str) -> dict:
        """获取基金元数据：规模、费率、成立日期、申购状态。"""
        url = f"http://fund.eastmoney.com/f10/jbgk_{code}.html"
        text = self.http.get(url, cache_key=f"fund_info:{code}",
                             headers={"Referer": "http://fund.eastmoney.com/"})
        if not text:
            return {}

        info = {}

        # 成立日期
        m = re.search(r'成立日期[：:]\s*(\d{4}-\d{2}-\d{2})', text)
        if m:
            info["inception_date"] = m.group(1)

        # 基金规模（取数字部分）
        m = re.search(r'基金规模[：:]\s*([\d.]+)\s*(亿元|万元|元)', text)
        if m:
            val = float(m.group(1))
            unit = m.group(2)
            if unit == "亿元":
                val *= 1e8
            elif unit == "万元":
                val *= 1e4
            info["fund_size"] = val

        # 管理费率
        m = re.search(r'管理费率[：:]\s*([\d.]+)%', text)
        if m:
            info["management_fee"] = float(m.group(1)) / 100

        # 托管费率
        m = re.search(r'托管费率[：:]\s*([\d.]+)%', text)
        if m:
            info["custodian_fee"] = float(m.group(1)) / 100

        # 销售服务费
        m = re.search(r'销售服务费率[：:]\s*([\d.]+)%', text)
        if m:
            info["sales_service_fee"] = float(m.group(1)) / 100

        # 申购状态
        if "暂停申购" in text:
            info["purchase_status"] = "suspended"
        elif "开放申购" in text:
            info["purchase_status"] = "open"
        else:
            info["purchase_status"] = "unknown"

        # 日申购限额
        m = re.search(r'日累计申购上限[：:]\s*([\d.]+)\s*(万元|元)', text)
        if m:
            val = float(m.group(1))
            if m.group(2) == "万元":
                val *= 10000
            info["daily_purchase_limit"] = val

        # 业绩比较基准
        m = re.search(r'业绩比较基准[：:]\s*(.+?)(?:\n|<)', text)
        if m:
            info["benchmark_text"] = m.group(1).strip()[:100]

        # 基金经理 + 任职日期
        m = re.search(r'基金经理[：:].*?(\d{4}-\d{2}-\d{2})', text)
        if m:
            info["manager_start_date"] = m.group(1)

        # 计算综合年费率
        mgmt = info.get("management_fee", 0)
        cust = info.get("custodian_fee", 0)
        sales = info.get("sales_service_fee", 0)
        info["annual_fee"] = round(mgmt + cust + sales, 4) if (mgmt or cust or sales) else None

        return info

    # ---- 历史净值 ----
    _PAGE_SIZE = 20  # API 单页最大条数

    def history(self, code: str, size: int = 300) -> List[NavPoint]:
        """获取历史净值，自动分页。"""
        points: List[NavPoint] = []
        needed = min(size, 300)  # 最多 300 条
        pages = (needed + self._PAGE_SIZE - 1) // self._PAGE_SIZE
        for page in range(1, pages + 1):
            page_size = min(self._PAGE_SIZE, needed - len(points))
            url = (f"https://api.fund.eastmoney.com/f10/lsjz?"
                   f"fundCode={code}&pageIndex={page}&pageSize={page_size}")
            text = self.http.get(
                url,
                headers={"Referer": "https://fundf10.eastmoney.com/",
                         "Accept": "application/json, text/javascript, */*; q=0.01"},
                cache_key=f"lsjz:{code}:{page}:{page_size}",
            )
            if not text:
                break
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                break
            rows = (((payload or {}).get("Data") or {}).get("LSJZList")) or []
            if not rows:
                break
            for row in rows:
                d = _to_date(row.get("FSRQ", ""))
                nav = _to_float(row.get("DWJZ"))
                if d is None or nav is None:
                    continue
                chg = _to_float(row.get("JZZZL"))
                points.append(NavPoint(
                    d=d,
                    nav=nav,
                    cum_nav=_to_float(row.get("LJJZ")),
                    change=(chg / 100.0 if chg is not None else None),
                ))
        points.sort(key=lambda p: p.d)
        return points
