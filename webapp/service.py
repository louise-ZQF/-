"""服务层：为 Web API 组织数据（演示/实时报告、持仓读写）。

部署相关：
    * 持仓文件路径可用环境变量 HOLDINGS_PATH 覆盖（指向持久盘，避免临时文件系统丢数据）；
    * 若文件不存在但设置了 HOLDINGS_YAML 环境变量，则把它落地成文件（适合无持久盘的平台，
      用 Secret/环境变量注入持仓）。
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import List, Optional

import yaml

from fund_analyzer.config import load_holdings, load_settings
from fund_analyzer.portfolio import Analyzer, analyze_fund, build_report

from .serialize import report_to_dict

EXAMPLE_HOLDINGS = "config/holdings.example.yaml"
DEFAULT_SETTINGS = os.getenv("SETTINGS_PATH", "config/settings.yaml")


def holdings_path() -> str:
    return os.getenv("HOLDINGS_PATH", "config/holdings.yaml")


def _ensure_holdings_file(path: str) -> None:
    """文件不存在但有 HOLDINGS_YAML 环境变量时，落地成文件。"""
    if os.path.exists(path):
        return
    raw = os.getenv("HOLDINGS_YAML")
    if not raw:
        return
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(raw)
    except OSError:
        pass


def build_demo_json() -> dict:
    from fund_analyzer.demo import build_demo
    settings = load_settings(DEFAULT_SETTINGS)
    holdings, nav_map, quote_map, index_map, fx_returns, brief = build_demo()
    funds = []
    for h in holdings:
        idx = index_map.get(h.tracking.index, [])
        fx = fx_returns if (h.tracking.index and not h.tracking.currency_hedged) else []
        funds.append(analyze_fund(h, nav_map[h.code], quote_map.get(h.code), idx, fx, settings))
    rep = build_report(funds, settings, market_brief=brief, as_of=datetime(2026, 6, 19, 9, 0))
    return report_to_dict(rep, settings.report_title + "（演示数据）", "demo")


def build_live_json(holdings_path_override: Optional[str] = None) -> dict:
    settings = load_settings(DEFAULT_SETTINGS)
    path = holdings_path_override or holdings_path()
    _ensure_holdings_file(path)
    holdings = load_holdings(path)
    if not holdings:
        return {
            "mode": "live", "empty": True,
            "message": "尚未配置持仓。请在「持仓管理」里添加你的基金，或先点「演示数据」查看效果。",
            "as_of": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "funds": [], "highlights": [], "allocation": [],
            "portfolio_notes": [], "market_brief": [],
            "overview": {"has_value": False},
        }
    analyzer = Analyzer(settings)
    rep = analyzer.run(holdings)
    indicators = analyzer.market_indicators()
    result = report_to_dict(rep, settings.report_title, "live")
    if indicators:
        result["market_indicators"] = indicators

    # 自动保存每日快照
    tv = result["overview"].get("total_value") or 0
    tc = result["overview"].get("total_cost") or 0
    invested = sum(float(h.current_value or 0) for h in holdings)
    save_daily_snapshot(tv, tc, invested, len(holdings))

    return result


# ----------------------------------------------------------------------------
# 持仓读写（供前端编辑器）
# ----------------------------------------------------------------------------

def read_holdings_raw(path: Optional[str] = None) -> List[dict]:
    path = path or holdings_path()
    _ensure_holdings_file(path)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    items = raw.get("holdings", raw if isinstance(raw, list) else [])
    return items or []


def read_example_holdings() -> List[dict]:
    src = EXAMPLE_HOLDINGS if os.path.exists(EXAMPLE_HOLDINGS) else None
    if not src:
        return []
    with open(src, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return raw.get("holdings", []) or []


def _clean_holding(d: dict) -> dict:
    """规整前端提交的单条持仓，去掉空值、自动补全缺失字段。"""
    code = str(d.get("code", "")).strip()
    out: dict = {"code": code}

    # 有 name 就用，否则自动补全
    if d.get("name") and str(d.get("name")).strip():
        out["name"] = str(d["name"]).strip()

    # 自动补全：如果用户只填了代码+金额(+定投)，帮他把剩余字段补上
    has_tracking = bool((d.get("tracking") or {}).get("index"))
    has_asset = bool(d.get("asset_class") and d.get("asset_class") != "other")
    need_autofill = not (d.get("name") and has_asset and has_tracking)

    if need_autofill:
        info = auto_fill_fund(code)
        if info:
            if not d.get("name"):
                out["name"] = info["name"]
            out["asset_class"] = info["asset_class"]
            out["annual_fee"] = info["annual_fee"]
            if info.get("cost_nav") is not None:
                out["cost_nav"] = info["cost_nav"]
            tk = info.get("tracking") or {}
            if tk.get("index"):
                out["tracking"] = {
                    "index": tk["index"],
                    "lag_days": tk.get("lag_days", 1),
                    "currency_hedged": tk.get("currency_hedged", False),
                    "beta": "auto",
                }
        else:
            out["asset_class"] = d.get("asset_class") or "other"
    else:
        out["asset_class"] = d.get("asset_class") or "other"

    for k in ("shares", "cost_nav", "annual_fee"):
        v = d.get(k)
        if v not in (None, "", 0, "0"):
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                pass
    if "annual_fee" not in out and d.get("annual_fee"):
        out["annual_fee"] = float(d.get("annual_fee", 0) or 0)

    tw = d.get("target_weight")
    if tw not in (None, ""):
        try:
            out["target_weight"] = float(tw)
        except (TypeError, ValueError):
            pass
    out["is_dca"] = bool(d.get("is_dca", False))

    # current_value
    cv = d.get("current_value")
    if cv not in (None, "", 0, "0"):
        try:
            out["current_value"] = float(cv)
        except (TypeError, ValueError):
            pass

    # dca_plan
    dp = d.get("dca_plan") or {}
    if dp and dp.get("amount"):
        out["dca_plan"] = {
            "frequency": dp.get("frequency", "daily"),
            "amount": float(dp["amount"]),
            "enabled": bool(dp.get("enabled", True)),
        }

    # tracking（已有则保留）
    if not need_autofill:
        tk = d.get("tracking") or {}
        index = (tk.get("index") or "").strip()
        if index:
            tracking = {"index": index, "lag_days": int(tk.get("lag_days", 1) or 1),
                        "currency_hedged": bool(tk.get("currency_hedged", False))}
            beta = tk.get("beta", "auto")
            tracking["beta"] = beta if beta in (None, "", "auto") else float(beta)
            out["tracking"] = tracking

    if d.get("note"):
        out["note"] = str(d["note"]).strip()
    return out


# ---------------------------------------------------------------------------
# 自选基金分析
# ---------------------------------------------------------------------------

def analyze_watchlist(codes: List[str]) -> List[dict]:
    """分析自选基金列表 — 基于因子引擎的质量×择时分决策。"""
    from fund_analyzer.config import load_settings
    from fund_analyzer.datasource.base import HttpClient
    from fund_analyzer.datasource.eastmoney import EastMoney
    from fund_analyzer.factors import compute_factor_scores, factors_to_dict
    from fund_analyzer.importer import search_fund
    from fund_analyzer.models import AssetClass, Holding
    from fund_analyzer.portfolio import compute_metrics
    from fund_analyzer.watchlist import decide_buy

    settings = load_settings(DEFAULT_SETTINGS)
    http = HttpClient(
        cache_dir=settings.datasource.cache_dir,
        ttl_minutes=settings.datasource.cache_ttl_minutes,
        timeout=settings.datasource.request_timeout,
    )
    em = EastMoney(http)

    results = []
    for code in codes:
        info = search_fund(code, em)
        if not info:
            results.append({"code": code, "error": "未找到该基金"})
            continue

        navpoints = em.history(code, size=100)
        navs = [p.nav for p in navpoints if p.nav]
        quote = em.realtime(code)

        # 因子评分
        factor_scores = compute_factor_scores(navs, info.annual_fee) if navs else None
        factor_dict = factors_to_dict(factor_scores) if factor_scores else None

        # Metrics
        try:
            ac = AssetClass(info.asset_class)
        except ValueError:
            ac = AssetClass.OTHER
        h = Holding(code=code, name=info.name, asset_class=ac)
        m = compute_metrics(h, navpoints, quote, settings)

        # 决策
        quality_score = factor_scores.quality_score if factor_scores else 0
        timing_score = factor_scores.timing_score if factor_scores else 0
        decision = decide_buy(quality_score, timing_score)

        results.append({
            "code": code,
            "name": info.name,
            "asset_class": info.asset_class,
            "metrics": {
                "last_nav": m.last_nav,
                "ret_1w": m.ret_1w, "ret_1m": m.ret_1m, "ret_3m": m.ret_3m,
                "rsi14": m.rsi14, "price_percentile": m.price_percentile,
                "max_drawdown": m.max_drawdown, "vol_annual": m.vol_annual, "sharpe": m.sharpe,
            },
            "factors": factor_dict,
            "decision": decision,
        })

    return results


def analyze_watchlist_full(codes: List[str]) -> dict:
    """完整分析：因子评分 + 择时决策 + 持仓相关性 + 买点提醒。"""
    from fund_analyzer.config import load_settings
    from fund_analyzer.datasource.base import HttpClient
    from fund_analyzer.datasource.eastmoney import EastMoney
    from fund_analyzer.factors import compute_factor_scores, factors_to_dict
    from fund_analyzer.importer import search_fund
    from fund_analyzer.manager_scorecard import score_manager_style
    from fund_analyzer.models import AssetClass, Holding
    from fund_analyzer.portfolio import compute_metrics
    from fund_analyzer.watchlist import decide_buy, compute_correlation, load_watchlist

    settings = load_settings(DEFAULT_SETTINGS)
    http = HttpClient(
        cache_dir=settings.datasource.cache_dir,
        ttl_minutes=settings.datasource.cache_ttl_minutes,
        timeout=settings.datasource.request_timeout,
    )
    em = EastMoney(http)

    # 加载持仓 → 取净值用于相关性
    holdings_raw = read_holdings_raw() or []
    holdings_navs_map = {}
    for h in holdings_raw:
        hcode = str(h.get("code", "")).strip()
        if hcode:
            pts = em.history(hcode, size=100)
            nv = [p.nav for p in pts if p.nav]
            if len(nv) >= 20:
                holdings_navs_map[hcode] = nv

    results = []
    all_factor_data = {}
    for code in codes:
        info = search_fund(code, em)
        if not info:
            results.append({"code": code, "error": "未找到该基金"})
            continue

        navpoints = em.history(code, size=100)
        navs = [p.nav for p in navpoints if p.nav]
        quote = em.realtime(code)

        factor_scores = compute_factor_scores(navs, info.annual_fee) if navs else None
        factor_dict = factors_to_dict(factor_scores) if factor_scores else None

        try:
            ac = AssetClass(info.asset_class)
        except ValueError:
            ac = AssetClass.OTHER
        h = Holding(code=code, name=info.name, asset_class=ac)
        m = compute_metrics(h, navpoints, quote, settings)

        quality_score = factor_scores.quality_score if factor_scores else 0
        timing_score = factor_scores.timing_score if factor_scores else 0
        decision = decide_buy(quality_score, timing_score)

        # 相关性
        correlation = compute_correlation(navs, holdings_navs_map) if navs else []

        # 基金经理风格评分
        fund_style_info = {
            "name": info.name,
            "code": code,
            "asset_class": info.asset_class,
            "factors": factor_dict,
        }
        style_result = score_manager_style(fund_style_info, navs)

        results.append({
            "code": code,
            "name": info.name,
            "asset_class": info.asset_class,
            "metrics": {
                "last_nav": m.last_nav,
                "ret_1w": m.ret_1w, "ret_1m": m.ret_1m, "ret_3m": m.ret_3m,
                "rsi14": m.rsi14, "price_percentile": m.price_percentile,
                "max_drawdown": m.max_drawdown, "vol_annual": m.vol_annual, "sharpe": m.sharpe,
            },
            "factors": factor_dict,
            "decision": decision,
            "correlation": correlation,
            "manager_style": style_result,
        })
        if factor_scores:
            all_factor_data[code] = factor_scores

    # 买点提醒（基于已保存的自选列表）
    watch_items = load_watchlist()
    from fund_analyzer.watchlist import check_buy_alerts
    alerts = check_buy_alerts(watch_items, all_factor_data)

    return {"results": results, "alerts": alerts}


# ---------------------------------------------------------------------------
# 自选基金 CRUD
# ---------------------------------------------------------------------------

def get_watchlist() -> list:
    """读取自选列表。"""
    from fund_analyzer.watchlist import load_watchlist
    items = load_watchlist()
    return [{
        "code": w.code, "name": w.name, "asset_class": w.asset_class.value,
        "added_at": w.added_at, "note": w.note, "target_buy": w.target_buy,
        "annual_fee": w.annual_fee,
    } for w in items]


def add_watch_item(data: dict) -> dict:
    """添加或更新自选基金。"""
    from fund_analyzer.config import load_settings
    from fund_analyzer.datasource.base import HttpClient
    from fund_analyzer.datasource.eastmoney import EastMoney
    from fund_analyzer.importer import search_fund
    from fund_analyzer.models import AssetClass, WatchItem
    from fund_analyzer.watchlist import load_watchlist, save_watchlist

    code = str(data.get("code", "")).strip()
    if not code:
        return {"ok": False, "error": "基金代码不能为空"}

    # 自动补全基金信息
    settings = load_settings(DEFAULT_SETTINGS)
    http = HttpClient(
        cache_dir=settings.datasource.cache_dir,
        ttl_minutes=settings.datasource.cache_ttl_minutes,
        timeout=settings.datasource.request_timeout,
    )
    em = EastMoney(http)
    info = search_fund(code, em)

    items = load_watchlist()
    existing = next((i for i, w in enumerate(items) if w.code == code), None)

    if existing is not None:
        w = items[existing]
        if data.get("name"):
            w.name = str(data["name"])
        if data.get("note"):
            w.note = str(data["note"])
        if data.get("target_buy") is not None:
            w.target_buy = data["target_buy"]
        if data.get("annual_fee") is not None:
            w.annual_fee = float(data["annual_fee"])
    else:
        try:
            ac = AssetClass(data.get("asset_class", "other")) if data.get("asset_class") else AssetClass.OTHER
        except ValueError:
            ac = AssetClass.OTHER
        w = WatchItem(
            code=code,
            name=data.get("name", info.name if info else ""),
            asset_class=ac,
            added_at=data.get("added_at", datetime.now().strftime("%Y-%m-%d")),
            note=data.get("note", ""),
            target_buy=data.get("target_buy"),
            annual_fee=float(data.get("annual_fee", info.annual_fee if info else 0) or 0),
        )
        items.append(w)

    save_watchlist(items)
    return {"ok": True, "code": code}


def remove_watch_item(code: str) -> dict:
    """从自选列表删除。"""
    from fund_analyzer.watchlist import load_watchlist, save_watchlist
    items = load_watchlist()
    before = len(items)
    items = [w for w in items if w.code != code]
    if len(items) == before:
        return {"ok": False, "error": f"未找到基金 {code}"}
    save_watchlist(items)
    return {"ok": True, "code": code}


# ---------------------------------------------------------------------------
# 基金筛选
# ---------------------------------------------------------------------------

def run_screener(category: str = "us_qdii") -> dict:
    """运行新版基金筛选器。"""
    from fund_analyzer.backtest import quick_backtest
    from fund_analyzer.config import load_settings
    from fund_analyzer.datasource.base import HttpClient
    from fund_analyzer.datasource.eastmoney import EastMoney
    from fund_analyzer.datasource.market_index import MarketIndex
    from fund_analyzer.screener import screen_funds_v2

    settings = load_settings(DEFAULT_SETTINGS)
    http = HttpClient(
        cache_dir=settings.datasource.cache_dir,
        ttl_minutes=settings.datasource.cache_ttl_minutes,
        timeout=settings.datasource.request_timeout,
    )
    em = EastMoney(http)
    mi = MarketIndex(http)
    funds = screen_funds_v2(http, em, mi, category=category, top_n=20)

    fund_list = [
        {"code": f.code, "name": f.name, "fund_type": f.fund_type,
         "benchmark_name": f.benchmark_name, "composite_score": f.composite_score,
         "confidence": f.confidence, "final_score": f.final_score,
         "peer_rank": f.peer_rank, "model_type": f.model_type,
         "detail_scores": f.detail_scores,
         "strengths": f.strengths, "risks": f.risks,
         "ret_1y": f.ret_1y, "ret_3y": f.ret_3y, "sharpe": f.sharpe,
         "annual_fee": f.annual_fee, "fund_size": f.fund_size}
        for f in funds
    ]

    backtest_result = quick_backtest(fund_list)

    return {"funds": fund_list, "backtest": backtest_result}


def generate_alerts(funds_raw: List[dict]) -> list:
    """为当前持仓生成智能提醒。"""
    from fund_analyzer.config import load_settings, _parse_holding
    from fund_analyzer.datasource.base import HttpClient
    from fund_analyzer.datasource.eastmoney import EastMoney
    from fund_analyzer.portfolio import analyze_fund
    from fund_analyzer.factors import compute_factor_scores
    from fund_analyzer.screener import generate_alerts as gen_alerts

    settings = load_settings(DEFAULT_SETTINGS)
    holdings = [_parse_holding(h) for h in funds_raw]
    http = HttpClient(
        cache_dir=settings.datasource.cache_dir,
        ttl_minutes=settings.datasource.cache_ttl_minutes,
        timeout=settings.datasource.request_timeout,
    )
    em = EastMoney(http)

    fas = []
    factor_data = {}
    for h in holdings:
        navpoints = em.history(h.code, size=100)
        quote = em.realtime(h.code)
        fa = analyze_fund(h, navpoints, quote, [], [], settings)
        fas.append(fa)
        navs = [p.nav for p in navpoints if p.nav]
        if navs:
            factor_data[h.code] = compute_factor_scores(navs)

    return gen_alerts(fas, factor_data, settings)


# ---------------------------------------------------------------------------
# XIRR 真实收益
# ---------------------------------------------------------------------------

def compute_xirr() -> dict:
    """计算投资组合 XIRR 真实年化收益。"""
    from fund_analyzer.xirr import (
        load_transactions, auto_dca_transactions, compute_xirr as calc_xirr,
    )
    from datetime import date

    holdings = read_holdings_raw()
    if not holdings:
        return {"error": "请先保存持仓"}

    # 加载交易记录 + 从定投计划自动生成
    txs = load_transactions()
    if not txs:
        txs = auto_dca_transactions(holdings)

    # 计算当前总市值
    from fund_analyzer.config import load_settings
    from fund_analyzer.datasource.base import HttpClient
    from fund_analyzer.datasource.eastmoney import EastMoney
    settings = load_settings(DEFAULT_SETTINGS)
    http = HttpClient(
        cache_dir=settings.datasource.cache_dir,
        ttl_minutes=settings.datasource.cache_ttl_minutes,
        timeout=settings.datasource.request_timeout,
    )
    em = EastMoney(http)
    total_value = 0.0
    for h in holdings:
        cv = float(h.get("current_value", 0) or 0)
        if cv <= 0 and h.get("shares"):
            q = em.realtime(str(h.get("code", "")))
            cv = float(h.get("shares", 0)) * (q.nav if q and q.nav else 1)
        total_value += cv

    result = calc_xirr(txs, total_value, date.today())

    return {
        "xirr": round(result.xirr * 100, 2),        # 百分比
        "total_invested": round(result.total_invested, 2),
        "total_return": round(result.total_return, 2),
        "return_pct": round(result.return_pct * 100, 2),
        "annualized": round(result.annualized_return * 100, 2),
        "years": round(result.years, 2),
        "transactions_count": len(txs),
    }


# ---------------------------------------------------------------------------
# 收益曲线
# ---------------------------------------------------------------------------

def get_return_curve(days: int = 90) -> List[dict]:
    """获取收益曲线数据。"""
    from fund_analyzer.snapshot import load_snapshots
    return load_snapshots(days)


def save_daily_snapshot(total_value: float, total_cost: float, total_invested: float,
                        fund_count: int):
    """保存每日快照（供报告流程调用）。"""
    try:
        from fund_analyzer.snapshot import save_snapshot
        save_snapshot(total_value, total_cost, total_invested, fund_count)
    except Exception:
        pass  # 快照失败不影响主流程


# ---------------------------------------------------------------------------
# 真实 PE/PB 估值
# ---------------------------------------------------------------------------

def get_valuation(code: str) -> dict:
    """获取基金真实 PE/PB 估值分位（来自天天基金）。"""
    from fund_analyzer.datasource.base import HttpClient
    from fund_analyzer.datasource.eastmoney import EastMoney
    from fund_analyzer.config import load_settings
    import re, json

    settings = load_settings(DEFAULT_SETTINGS)
    http = HttpClient(
        cache_dir=settings.datasource.cache_dir,
        ttl_minutes=120,  # 估值数据变化慢
        timeout=settings.datasource.request_timeout,
    )

    # 从天天基金 fundf10 页面抓 PE/PB 数据
    url = f"http://fund.eastmoney.com/f10/tsdata_{code}.html"
    text = http.get(url, cache_key=f"valuation:{code}",
                    headers={"Referer": "http://fund.eastmoney.com/"})
    if not text:
        return {"code": code, "error": "获取估值数据失败"}

    pe_data = _extract_valuation(text, "市盈率")
    pb_data = _extract_valuation(text, "市净率")

    return {
        "code": code,
        "pe_current": pe_data.get("current"),
        "pe_percentile": pe_data.get("percentile"),
        "pe_high": pe_data.get("high"),
        "pe_low": pe_data.get("low"),
        "pb_current": pb_data.get("current"),
        "pb_percentile": pb_data.get("percentile"),
        "note": "数据来自天天基金，仅供参考",
    }


def _extract_valuation(html: str, label: str) -> dict:
    """从天天基金页面提取估值数据。"""
    import re
    # 搜索包含 label 的 JSON 数据块
    pattern = rf'{label}.*?"current":\s*([\d.]+).*?"percentile":\s*([\d.]+)'
    m = re.search(pattern, html, re.DOTALL)
    if m:
        return {
            "current": float(m.group(1)),
            "percentile": float(m.group(2)),
        }
    return {}


def save_holdings(holdings: List[dict], path: Optional[str] = None) -> int:
    path = path or holdings_path()
    cleaned = [_clean_holding(h) for h in holdings if str(h.get("code", "")).strip()]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# 由可视化网站「持仓管理」生成；也可手动编辑。\n")
        yaml.safe_dump({"holdings": cleaned}, f, allow_unicode=True, sort_keys=False)
    return len(cleaned)


# ---------------------------------------------------------------------------
# 导入服务
# ---------------------------------------------------------------------------

def auto_fill_fund(code: str) -> Optional[dict]:
    """输入代码，从天天基金自动补全信息。"""
    from fund_analyzer.config import load_settings
    from fund_analyzer.datasource.base import HttpClient
    from fund_analyzer.datasource.eastmoney import EastMoney
    from fund_analyzer.importer import search_fund

    settings = load_settings(DEFAULT_SETTINGS)
    http = HttpClient(
        cache_dir=settings.datasource.cache_dir,
        ttl_minutes=settings.datasource.cache_ttl_minutes,
        timeout=settings.datasource.request_timeout,
    )
    em = EastMoney(http)
    info = search_fund(code, em)
    if not info:
        return None

    # Fetch current nav for cost baseline
    q = em.realtime(code)
    cost_nav = q.nav if q and q.nav else None

    return {
        "code": info.code,
        "name": info.name,
        "asset_class": info.asset_class,
        "tracking": {
            "index": info.tracking_index or "",
            "lag_days": info.tracking_lag_days,
            "currency_hedged": False,
        },
        "annual_fee": info.annual_fee,
        "dca_plan": None,
        "cost_nav": cost_nav,
    }


def batch_auto_fill(codes: List[str]) -> List[dict]:
    """批量自动补全。"""
    results = []
    for code in codes:
        info = auto_fill_fund(code)
        if info:
            results.append(info)
    return results


def ocr_import(image_data: bytes) -> List[dict]:
    """OCR 截图 → 自动补全的持仓列表。"""
    from fund_analyzer.importer import ocr_funds_from_image

    pairs = ocr_funds_from_image(image_data)
    results = []
    for code, amount in pairs:
        info = auto_fill_fund(code)
        if info:
            info["current_value"] = amount
            results.append(info)
    return results


def run_ai_analysis(funds: List[dict]) -> dict:
    """对已有持仓运行 AI 分析。"""
    from fund_analyzer.ai_analyst import ai_analyze_portfolio, search_news_for_fund
    from fund_analyzer.config import load_settings, _parse_holding
    from fund_analyzer.datasource.base import HttpClient
    from fund_analyzer.datasource.eastmoney import EastMoney
    from fund_analyzer.datasource.market_index import MarketIndex
    from fund_analyzer.portfolio import analyze_fund

    settings = load_settings(DEFAULT_SETTINGS)
    holdings = [_parse_holding(h) for h in funds]
    http = HttpClient(
        cache_dir=settings.datasource.cache_dir,
        ttl_minutes=settings.datasource.cache_ttl_minutes,
        timeout=settings.datasource.request_timeout,
    )
    em = EastMoney(http)
    mi = MarketIndex(http)

    fas = []
    for h in holdings:
        navpoints = em.history(h.code, size=100)
        quote = em.realtime(h.code)
        fas.append(analyze_fund(h, navpoints, quote, [], [], settings))

    total_value = sum(fa.market_value or 0 for fa in fas)

    # 市场情绪指标
    indicators = mi.get_market_snapshot()

    # 搜索新闻
    news = {}
    for fa in fas:
        n = search_news_for_fund(fa.holding.name)
        if n:
            news[fa.holding.code] = n

    analysis = ai_analyze_portfolio(fas, news, total_value, indicators)

    return {
        "funds": {
            code: {
                "sentiment": s.sentiment,
                "reason": s.reason,
                "suggestion": s.suggestion,
            }
            for code, s in analysis.funds.items()
        },
        "portfolio_analysis": analysis.portfolio_analysis,
        "sector_bias": analysis.sector_bias,
        "macro_note": analysis.macro_note,
        "dca_adjustments": analysis.dca_adjustments,
        "news_feed": [
            {"type": n["type"], "text": n["text"], "code": n.get("code", "")}
            for n in analysis.news_feed
        ],
    }
