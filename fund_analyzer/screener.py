"""基金筛选器 + 智能买卖提醒。

数据源: 天天基金排行 API + 历史净值 API
筛选维度:
  - 美股 QDII: 长期收益 + 夏普比率 + 最大回撤
  - A股基金: 夏普比率 + 估值分位 + 波动率

智能提醒（基于持仓 + 量化因子）:
  - 🎯 止盈: 持仓收益超阈值
  - 📈 加大定投: 因子好转 + 估值低位
  - ⚠️ 减少定投: 因子恶化 + 估值高位
  - 🛑 卖出信号: 趋势走坏 + 回撤加深
"""
from __future__ import annotations

import re
import statistics
import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple

from .datasource.base import HttpClient


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class ScreenedFund:
    """筛选结果中的一只基金。"""
    code: str
    name: str
    fund_type: str          # "QDII美股" | "A股" | "混合" | "债券"
    ret_1y: float = 0.0     # 近1年收益（小数）
    ret_3y: float = 0.0     # 近3年收益
    sharpe: float = 0.0     # 估算夏普比率
    max_dd: float = 0.0     # 最大回撤（小数）
    vol_annual: float = 0.0 # 年化波动
    factor_score: float = 0.0  # 综合因子评分 0-100
    recommendation: str = ""   # "强烈推荐" | "推荐" | "关注" | "观望"


@dataclass
class Alert:
    """持仓提醒。"""
    code: str
    name: str
    alert_type: str  # "take_profit" | "increase_dca" | "reduce_dca" | "sell_warning" | "opportunity"
    level: str       # "🔴" | "🟡" | "🟢"
    message: str
    action: str      # 具体操作建议


# ---------------------------------------------------------------------------
# 天天基金排行 API
# ---------------------------------------------------------------------------

_RANK_URL = "http://fund.eastmoney.com/data/rankhandler.aspx"

# 基金类型筛选参数
_TYPE_MAP = {
    "all": "all",
    "stock": "gp",       # 股票型
    "hybrid": "hh",      # 混合型
    "bond": "zq",        # 债券型
    "index": "zs",       # 指数型
    "qdii": "qdii",      # QDII
}

# 排序指标
_SORT_MAP = {
    "ret_1y": "1nzf",     # 近1年涨幅
    "ret_3y": "3nzf",     # 近3年涨幅
    "ret_6m": "6yzf",     # 近6月涨幅
    "ret_3m": "3yzf",     # 近3月涨幅
}


def _fetch_rank(http: HttpClient, fund_type: str = "all", sort_by: str = "1nzf",
                page: int = 1, page_size: int = 50) -> List[dict]:
    """调用天天基金排行 API，返回基金列表。"""
    url = (f"{_RANK_URL}?op=ph&dt=kf&ft={fund_type}&rs=&gs=0"
           f"&sc={sort_by}&st=desc&qdii=&tabSubtype=,,,,,&pi={page}&pn={page_size}&dx=1")
    text = http.get(url, cache_key=f"rank:{fund_type}:{sort_by}:{page}",
                    headers={
                        "Referer": "http://fund.eastmoney.com/fund.html",
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                    })
    if not text:
        return []

    # 返回格式: var rankData = {datas:[...], allRecords:...}
    # 注意：天天基金的 JSON key 没有引号，不能用 json.loads
    # 直接用正则提取 datas 数组中的每个字符串
    m = re.search(r'datas:\s*\[(.*?)\]\s*,', text, re.DOTALL)
    if not m:
        return []
    # 按 \" 分割每个基金条目
    entries = re.findall(r'"([^"]+)"', m.group(1))
    rows = entries
    results = []
    for row in rows:
        # 格式: "000001,基金名称,基金类型,近1年涨幅,近3年涨幅,...,"
        parts = row.split(",")
        if len(parts) < 5:
            continue
        try:
            code = parts[0].strip()
            name = parts[1].strip()
            # 字段: code,name,pinyin,date,nav,cum_nav,日涨幅,近1周,近1月,近3月,近6月,近1年,近2年,近3年,...
            # 0    1    2      3    4   5        6      7     8     9     10    11     12     13
            ret_1y_str = parts[11] if len(parts) > 11 else "0"
            ret_3y_str = parts[13] if len(parts) > 13 else "0"
            ret_1y = float(ret_1y_str) / 100.0 if ret_1y_str else 0
            ret_3y = float(ret_3y_str) / 100.0 if ret_3y_str else 0
        except (ValueError, IndexError):
            continue
        results.append({
            "code": code,
            "name": name,
            "ret_1y": ret_1y,
            "ret_3y": ret_3y,
        })
    return results


def _estimate_sharpe_from_navs(navs: List[float]) -> float:
    """从净值序列估算年化夏普比率。"""
    if len(navs) < 60:
        return 0.0
    rets = [navs[i] / navs[i - 1] - 1 for i in range(1, len(navs)) if navs[i - 1]]
    if not rets:
        return 0.0
    ann_ret = sum(rets) / len(rets) * 252
    ann_vol = statistics.stdev(rets) * math.sqrt(252) if len(rets) > 1 else 0.0
    if ann_vol < 0.001:
        return 0.0
    return (ann_ret - 0.02) / ann_vol  # rf = 2%


def _estimate_max_dd(navs: List[float]) -> float:
    """从净值序列算最大回撤。"""
    if not navs:
        return 0.0
    peak = navs[0]
    max_dd = 0.0
    for nav in navs:
        if nav > peak:
            peak = nav
        dd = (nav - peak) / peak
        if dd < max_dd:
            max_dd = dd
    return max_dd


# ---------------------------------------------------------------------------
# 筛选逻辑
# ---------------------------------------------------------------------------

QDII_US_KEYWORDS = [
    "纳斯达克", "纳指", "标普", "美股", "道琼斯", "费城半导体",
    "全球科技", "全球成长", "全球高端", "全球产业", "全球新",
    "新兴市场", "海外", "QDII", "美国", "美元", "摩根",
    "互联", "移动互联",
]


def _is_us_qdii(name: str) -> bool:
    """判断是否为美股相关 QDII。"""
    for kw in QDII_US_KEYWORDS:
        if kw in name:
            return True
    return False


def _is_a_stock(name: str) -> bool:
    """判断是否为 A 股基金。"""
    a_keywords = ["沪深300", "中证500", "上证50", "创业板", "科创", "A股",
                  "红利", "消费", "医药", "新能源", "半导体", "中国"]
    for kw in a_keywords:
        if kw in name:
            return True
    return not _is_us_qdii(name)


def screen_funds(http: HttpClient, em,
                 category: str = "us_qdii", top_n: int = 20) -> List[ScreenedFund]:
    """筛选基金。

    category: "us_qdii" | "a_stock" | "all"
    """
    # 1. 从排行 API 获取候选基金
    candidates = []
    if category == "us_qdii":
        # QDII 排行 + 可能的关键词基金
        for ft in ["qdii", "all"]:
            candidates += _fetch_rank(http, ft, _SORT_MAP["ret_1y"], 1, 50)
    elif category == "a_stock":
        for ft in ["gp", "hh", "zs"]:
            candidates += _fetch_rank(http, ft, _SORT_MAP["ret_1y"], 1, 30)
    else:
        candidates = _fetch_rank(http, "all", _SORT_MAP["ret_1y"], 1, 50)

    # 去重
    seen = set()
    unique = []
    for c in candidates:
        if c["code"] not in seen:
            seen.add(c["code"])
            unique.append(c)

    # 2. 对每只基金计算更详细的指标
    results = []
    for c in unique:
        # 类型判断
        if category == "us_qdii" and not _is_us_qdii(c["name"]):
            continue
        elif category == "a_stock" and not _is_a_stock(c["name"]):
            continue

        # 获取历史净值计算夏普和回撤
        navpoints = em.history(c["code"], size=200)  # TODO: increase to 750 for production use
        if len(navpoints) < 40:
            continue
        navs = [p.nav for p in navpoints if p.nav]

        sharpe = _estimate_sharpe_from_navs(navs)
        max_dd = _estimate_max_dd(navs)
        vol_annual = statistics.stdev(
            [navs[i] / navs[i - 1] - 1 for i in range(1, len(navs)) if navs[i - 1]]
        ) * math.sqrt(252) if len(navs) > 1 else 0

        # 用因子评分做综合判断
        from .factors import compute_factor_scores
        fs = compute_factor_scores(navs)
        factor_score = fs.composite

        # 确定推荐等级
        if factor_score >= 75 and sharpe > 1.0 and max_dd > -0.15:
            rec = "强烈推荐"
        elif factor_score >= 60 and sharpe > 0.6:
            rec = "推荐"
        elif factor_score >= 45:
            rec = "关注"
        else:
            rec = "观望"

        # 按类别过滤最低标准
        if category == "us_qdii":
            if c["ret_1y"] < 0.0:  # 只筛掉负收益的
                continue
        elif category == "a_stock":
            if sharpe < 0.2:  # A 股至少夏普 > 0.2
                continue

        results.append(ScreenedFund(
            code=c["code"],
            name=c["name"],
            fund_type="QDII美股" if _is_us_qdii(c["name"]) else "A股",
            ret_1y=c["ret_1y"],
            ret_3y=c["ret_3y"],
            sharpe=round(sharpe, 2),
            max_dd=round(max_dd, 3),
            vol_annual=round(vol_annual, 3) if vol_annual else 0,
            factor_score=round(factor_score, 1),
            recommendation=rec,
        ))

        if len(results) >= top_n:
            break

    # 按综合因子排序
    results.sort(key=lambda x: x.factor_score, reverse=True)
    return results


# ---------------------------------------------------------------------------
# 智能持仓提醒
# ---------------------------------------------------------------------------

def generate_alerts(funds: List, factor_data: dict = None, settings=None) -> List[Alert]:
    """基于当前持仓 + 量化因子，生成智能提醒列表。

    funds: FundAnalysis 对象列表
    factor_data: {code: FactorScores} 映射
    """
    alerts = []
    for fa in funds:
        h = fa.holding
        m = fa.metrics
        code = h.code
        name = h.name or code

        # 需要因子数据
        fs = (factor_data or {}).get(code)
        if not fs and fa.history:
            navs = [p.nav for p in fa.history if p.nav]
            if navs:
                from .factors import compute_factor_scores
                fs = compute_factor_scores(navs)

        # 1. 🎯 止盈提醒
        if m.holding_return and m.holding_return > 0.25:
            alerts.append(Alert(
                code=code, name=name,
                alert_type="take_profit",
                level="🔴",
                message=f"持仓收益 已达 +{m.holding_return*100:.0f}%，超过25%止盈线",
                action=f"建议分批止盈至少{min(50, int(m.holding_return*100))}%，锁定利润",
            ))
        elif m.holding_return and m.holding_return > 0.15:
            alerts.append(Alert(
                code=code, name=name,
                alert_type="take_profit",
                level="🟡",
                message=f"持仓收益 +{m.holding_return*100:.0f}%，接近止盈线",
                action="设好回撤止盈（从最高点回落 8% 就卖），保护利润",
            ))

        # 2. 📈 加大定投信号
        if fs and fs.composite >= 70 and fs.value >= 60:
            if h.is_dca and h.dca_plan:
                new_amt = h.dca_plan.amount * 1.5
                alerts.append(Alert(
                    code=code, name=name,
                    alert_type="increase_dca",
                    level="🟢",
                    message=f"因子综合{fs.composite:.0f}分 估值偏低 — 定投良机",
                    action=f"建议将定投从 ¥{h.dca_plan.amount:.0f} 增至 ¥{new_amt:.0f}/期",
                ))
        elif fs and fs.composite >= 70:
            alerts.append(Alert(
                code=code, name=name,
                alert_type="increase_dca",
                level="🟢",
                message=f"因子综合{fs.composite:.0f}分 多因子共振向上",
                action="建议启动或保持定投，可考虑一次性追加仓位",
            ))

        # 3. ⚠️ 减少定投信号
        if fs and fs.composite < 35 and fs.value < 40:
            if h.is_dca and h.dca_plan:
                new_amt = h.dca_plan.amount * 0.5
                alerts.append(Alert(
                    code=code, name=name,
                    alert_type="reduce_dca",
                    level="🟡",
                    message=f"因子综合{fs.composite:.0f}分 估值偏高 趋势走弱",
                    action=f"建议定投减半至 ¥{new_amt:.0f}/期，或暂停观望",
                ))

        # 4. 🛑 卖出警告
        if fs and fs.composite < 25 and fs.trend_quality < 30:
            alerts.append(Alert(
                code=code, name=name,
                alert_type="sell_warning",
                level="🔴",
                message=f"因子综合{fs.composite:.0f}分 趋势走坏 — 强烈建议减仓",
                action="建议减仓50%以上，转投货币/短债基金等待机会",
            ))

        # 5. 💡 机会提醒（因子从弱转强）
        if fs and fs.composite >= 55 and m.ret_1w and m.ret_1w > 0.02:
            if not any(a.code == code and a.alert_type == "increase_dca" for a in alerts):
                alerts.append(Alert(
                    code=code, name=name,
                    alert_type="opportunity",
                    level="🟢",
                    message=f"因子回升至{fs.composite:.0f}分 近1周 +{m.ret_1w*100:.1f}%",
                    action="关注是否形成趋势反转，确认后可加仓",
                ))

    # 按严重程度排序
    level_order = {"🔴": 0, "🟡": 1, "🟢": 2}
    alerts.sort(key=lambda a: level_order.get(a.level, 3))
    return alerts
