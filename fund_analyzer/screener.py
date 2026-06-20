"""基金筛选器 v2：分类建模 + 基准调整 + 稳健标准化 + 置信度 + 去重。

不再使用天天基金排行作为评分输入。
"""
from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from .datasource.base import HttpClient
from .datasource.eastmoney import EastMoney
from .datasource.market_index import MarketIndex
from .fund_classifier import classify_fund, is_passive_index
from .benchmark_mapper import (
    get_benchmark_info, get_qdii_lag, get_fx_code,
    align_nav_dates, compute_tracking_metrics,
    combine_index_and_fx, estimate_best_lag,
)
from .hard_filters import apply_hard_filters
from .robust_normalizer import normalize_funds
from .fund_scorers import score_passive_index, score_active_equity
from .share_class_dedup import deduplicate_share_classes, deduplicate_same_index
from .overlap_filter import remove_high_correlation
from .confidence import compute_confidence, adjust_score_with_confidence
from .factors import compute_factor_scores, FactorScores
from .metadata_cache import get_metadata


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class ScreenedFund:
    """筛选结果。"""
    code: str
    name: str
    fund_type: str          # "被动指数" | "主动权益"
    asset_region: str
    benchmark_code: str
    benchmark_name: str
    composite_score: float = 0.0
    confidence: float = 0.0
    final_score: float = 0.0
    peer_rank: str = ""
    model_type: str = ""     # "passive_index" | "active_equity"
    detail_scores: dict = field(default_factory=dict)
    strengths: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    dedup_note: str = ""


@dataclass
class Alert:
    """持仓提醒。"""
    code: str
    name: str
    alert_type: str  # "take_profit" | "increase_dca" | "reduce_dca" | "sell_warning" | "opportunity"
    level: str       # "🔴" | "🟡" | "🟢"
    message: str
    action: str      # 具体操作建议


# ============================================================================
# 天天基金排行 API（仅用于基金发现，不用于评分）
# ============================================================================

_RANK_URL = "http://fund.eastmoney.com/data/rankhandler.aspx"


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
    m = re.search(r'datas:\s*\[(.*?)\]\s*,', text, re.DOTALL)
    if not m:
        return []
    entries = re.findall(r'"([^"]+)"', m.group(1))
    rows = entries
    results = []
    for row in rows:
        parts = row.split(",")
        if len(parts) < 5:
            continue
        try:
            code = parts[0].strip()
            name = parts[1].strip()
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


def _fetch_full_universe(http: HttpClient, fund_type: str = "qdii",
                         max_pages: int = 5) -> List[dict]:
    """获取完整基金列表（分页，按代码排序，不按收益）。"""
    all_funds = []
    for page in range(1, max_pages + 1):
        rows = _fetch_rank(http, fund_type, "1nzf", page, 50)
        if not rows:
            break
        all_funds.extend(rows)
        if len(rows) < 50:
            break
    # 去重
    seen = set()
    unique = []
    for f in all_funds:
        if f["code"] not in seen:
            seen.add(f["code"])
            unique.append(f)
    return unique


# ============================================================================
# 新版筛选流程
# ============================================================================

def screen_funds_v2(http: HttpClient, em: EastMoney, mi: MarketIndex,
                    category: str = "us_qdii", top_n: int = 20) -> List[ScreenedFund]:
    """新版筛选主流程。

    1. 从排行API获取候选基金列表（仅作为基金发现）
    2. 对每只基金分类 + 匹配基准
    3. 拉历史净值 + 基准收益
    4. 计算跟踪指标 + 因子评分
    5. 同类内部稳健标准化
    6. 按类型分别评分
    7. 置信度调整
    8. A/C去重 + 同指数去重 + 高相关去重
    9. 排序输出
    """
    as_of = date.today()

    # Step 1: 获取候选基金
    candidates = []
    if category == "us_qdii":
        candidates = _fetch_full_universe(http, "qdii", max_pages=5)
    elif category == "a_stock":
        for ft in ["gp", "hh", "zs"]:
            candidates += _fetch_full_universe(http, ft, max_pages=3)
    else:
        candidates = _fetch_rank(http, "all", "1nzf", 1, 50)

    # 去重
    seen_codes = set()
    unique = []
    for c in candidates:
        if c["code"] not in seen_codes:
            seen_codes.add(c["code"])
            unique.append(c)

    # Step 2: 分类 + 获取数据（限制50只，控制耗时）
    classified_funds = []
    for c in unique[:50]:
        fc = classify_fund(c["code"], c["name"])

        # 拉净值
        navpoints = em.history(c["code"], size=300)
        if len(navpoints) < 40:
            continue
        navs = [p.nav for p in navpoints if p.nav]

        # 拉元数据（缓存24h，pingzhongdata JS） + fundf10 补充
        meta = get_metadata(http, c["code"])
        # 补充 fundf10 规模数据
        try:
            f10 = em.fund_info(c["code"]) or {}
            if f10.get("fund_size"):
                meta["fund_size"] = f10["fund_size"]
        except Exception:
            pass

        # 拉基准收益
        bm_info = get_benchmark_info(fc.benchmark_code)
        lag = get_qdii_lag(fc.benchmark_code) if fc.is_qdii else 1
        bench_rets = mi.returns(fc.benchmark_code, rng="2y")

        # QDII：合并汇率收益 → 人民币计价
        if fc.is_qdii and fc.asset_region in ("us", "hk"):
            fx_code = get_fx_code(fc.benchmark_code)
            if fx_code:
                fx_rets = mi.returns(fx_code, rng="2y")
                if fx_rets:
                    bench_rets = combine_index_and_fx(bench_rets, fx_rets)

        # 对齐（用 estimate_best_lag 优化滞后天数）
        fund_nav_tuples = [(p.d, p.nav) for p in navpoints]
        if len(bench_rets) >= 60:
            fund_rets = []
            for i in range(1, len(fund_nav_tuples)):
                d, nav = fund_nav_tuples[i]
                _, prev_nav = fund_nav_tuples[i - 1]
                if prev_nav and prev_nav > 0:
                    fund_rets.append((d, nav / prev_nav - 1.0))
            best_lag = estimate_best_lag(fund_rets, bench_rets)
            if best_lag != lag:
                lag = best_lag
        aligned = align_nav_dates(fund_nav_tuples, bench_rets, lag)

        # 跟踪指标
        tracking = compute_tracking_metrics(aligned) if aligned else {}

        # 因子评分
        fs = compute_factor_scores(navs)

        classified_funds.append({
            "code": c["code"],
            "name": c["name"],
            "fund_class": fc,
            "navpoints": navpoints,
            "navs": navs,
            "aligned": aligned,
            "tracking": tracking,
            "factors": fs,
            "ret_1y": c.get("ret_1y", 0),
            "ret_3y": c.get("ret_3y", 0),
            "annual_fee": meta.get("annual_fee"),
            "fund_size": meta.get("fund_size"),
            "benchmark_code": fc.benchmark_code,
            "is_passive": fc.fund_type == "passive_index",
            "inception_date": meta.get("inception_date") or str(navpoints[0].d) if navpoints else str(date.today()),
            "nav_days": len(navpoints),
            "expected_days": max(252, len(navpoints)),
            "purchase_status": meta.get("purchase_status", "unknown"),
            "peer_group": f"{fc.asset_region}_{fc.fund_type}",
            "data_quality": {
                "fee_missing": meta.get("annual_fee") is None,
                "fee_estimated": meta.get("annual_fee_estimated", False),
                "size_missing": meta.get("fund_size") is None,
                "inception_missing": meta.get("inception_date") is None,
            },
        })

    # Step 3: 硬性过滤
    passed, _ = apply_hard_filters(classified_funds, category, as_of)
    if not passed:
        return []

    # Step 4-5: 按类型评分 + 标准化
    for f in passed:
        fc = f["fund_class"]
        if fc.fund_type == "passive_index":
            result = score_passive_index(f, f["tracking"])
        else:
            fund_rets = []
            bench_rets_list = [r[2] for r in (f.get("aligned") or [])]
            navs = f.get("navs", [])
            if len(navs) >= 2:
                fund_rets = [navs[i]/navs[i-1]-1 for i in range(1, len(navs)) if navs[i-1]]
            result = score_active_equity(f, f["tracking"], fund_rets, bench_rets_list)

        f["model_type"] = result["model"]
        f["detail_scores"] = result["scores"]
        f["composite_score"] = result["composite"]

    # Step 6: 同类内部稳健标准化（composite_score + 各子指标）
    # 被动基金按 benchmark_code 分组，主动基金按地区+类型分组
    for f in passed:
        fc = f["fund_class"]
        if fc.fund_type == "passive_index":
            f["peer_group"] = f"{fc.benchmark_code}_{fc.fund_type}"
        else:
            f["peer_group"] = f"{fc.asset_region}_{fc.fund_type}"

    # 标准化所有基金的 composite_score
    passed = normalize_funds(passed, ["composite_score"], group_by="peer_group")
    for f in passed:
        f["composite_score"] = f.get("composite_score_score", f["composite_score"])

    # Step 7: 置信度调整
    for f in passed:
        conf = compute_confidence(f)
        f["confidence"] = conf["confidence"]
        f["final_score"] = round(adjust_score_with_confidence(
            f["composite_score"], conf["confidence"] / 100
        ), 1)

    # Step 8: 去重
    passed = deduplicate_share_classes(passed)
    passed = deduplicate_same_index(passed)

    # 高相关去重：计算各基金日收益，移除与已保留基金高度相关的
    returns_map = {}
    for f in passed:
        navs = f.get("navs", [])
        if len(navs) >= 20:
            rets = [navs[i]/navs[i-1]-1 for i in range(1, len(navs)) if navs[i-1]]
            if rets:
                returns_map[f["code"]] = rets
    if returns_map:
        passed.sort(key=lambda x: x.get("final_score", 0), reverse=True)
        passed = remove_high_correlation(passed, returns_map, threshold=0.95)

    # 按 final_score 排序
    passed.sort(key=lambda x: x["final_score"], reverse=True)

    # Step 9: 构建结果
    results = []
    for i, f in enumerate(passed[:top_n]):
        fc = f["fund_class"]
        bm_info = get_benchmark_info(fc.benchmark_code)
        peer_n = len([x for x in passed if x["peer_group"] == f["peer_group"]])
        ds = f.get("detail_scores", {})

        # 识别优势
        strengths = []
        for k, v in sorted(ds.items(), key=lambda x: -x[1]):
            if v >= 80:
                strengths.append(f"{k}: {v:.0f}/100")

        # 识别风险
        risks = []
        if f.get("size_warning"):
            risks.append("规模偏小")
        if f.get("purchase_status") == "suspended":
            risks.append("暂停申购")
        if f["confidence"] < 50:
            risks.append(f"置信度偏低({f['confidence']:.0f}%)")

        results.append(ScreenedFund(
            code=f["code"],
            name=f.get("name", ""),
            fund_type="被动指数" if fc.fund_type == "passive_index" else "主动权益",
            asset_region=fc.asset_region,
            benchmark_code=fc.benchmark_code,
            benchmark_name=bm_info.get("name", ""),
            composite_score=round(f.get("composite_score", 0), 1),
            confidence=round(f.get("confidence", 0), 1),
            final_score=f.get("final_score", 0),
            peer_rank=f"{i+1}/{peer_n}",
            model_type=f.get("model_type", ""),
            detail_scores=ds,
            strengths=strengths[:3],
            risks=risks[:3],
            dedup_note=f.get("dedup_note", ""),
        ))

    return results


# ============================================================================
# 智能持仓提醒（向后兼容）
# ============================================================================

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

        # 1. 止盈提醒
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

        # 2. 加大定投信号
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

        # 3. 减少定投信号
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

        # 4. 卖出警告
        if fs and fs.composite < 25 and fs.trend_quality < 30:
            alerts.append(Alert(
                code=code, name=name,
                alert_type="sell_warning",
                level="🔴",
                message=f"因子综合{fs.composite:.0f}分 趋势走坏 — 强烈建议减仓",
                action="建议减仓50%以上，转投货币/短债基金等待机会",
            ))

        # 5. 机会提醒（因子从弱转强）
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
