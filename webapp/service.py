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
    """分析自选基金列表，返回每只的看好/不看好+买入建议。"""
    from fund_analyzer.ai_analyst import call_deepseek, parse_ai_response
    from fund_analyzer.config import load_settings, _parse_holding
    from fund_analyzer.datasource.base import HttpClient
    from fund_analyzer.datasource.eastmoney import EastMoney
    from fund_analyzer.datasource.market_index import MarketIndex
    from fund_analyzer.portfolio import analyze_fund, compute_metrics
    from fund_analyzer.importer import search_fund

    settings = load_settings(DEFAULT_SETTINGS)
    http = HttpClient(
        cache_dir=settings.datasource.cache_dir,
        ttl_minutes=settings.datasource.cache_ttl_minutes,
        timeout=settings.datasource.request_timeout,
    )
    em = EastMoney(http)
    mi = MarketIndex(http)
    indicators = mi.get_market_snapshot()

    # 市场情绪摘要
    market_summary = "\n".join(
        f"{i['label']}: {i['value']}（{'偏高' if i['level']=='high' else '偏低' if i['level']=='low' else '正常'}）"
        for i in indicators[:6]
    )

    results = []
    for code in codes:
        # 获取基金信息
        info = search_fund(code, em)
        if not info:
            results.append({"code": code, "error": "未找到该基金"})
            continue

        # 获取历史净值 + 实时行情
        navpoints = em.history(code, size=100)
        quote = em.realtime(code)

        # 构造临时 Holding + 计算指标
        h = _parse_holding({"code": code, "name": info.name, "asset_class": info.asset_class})
        m = compute_metrics(h, navpoints, quote, settings)
        fa = analyze_fund(h, navpoints, quote, [], [], settings)

        # 构建买入分析 prompt
        fund_text = f"""基金代码: {code}
名称: {info.name}
类型: {info.asset_class}
最新净值: {m.last_nav}
近1周: {(m.ret_1w or 0)*100:+.1f}%  近1月: {(m.ret_1m or 0)*100:+.1f}%  近3月: {(m.ret_3m or 0)*100:+.1f}%
RSI(14): {m.rsi14:.0f}  估值分位: {(m.price_percentile or 0)*100:.0f}%  最大回撤: {(m.max_drawdown or 0)*100:.1f}%
年化波动: {(m.vol_annual or 0)*100:.1f}%  夏普: {m.sharpe or 0:.2f}"""

        prompt = f"""你是顶级基金分析师。判断这只基金现在是否值得买入。

{fund_text}

## 当前市场环境
{market_summary}

## 请给出判断（简洁，3-4句）：
1. 看好/中性/不看好 — 为什么？
2. 现在适合买入吗？如果适合，建议什么价位/策略？
3. 最大的风险和最大的机会各一句话

格式：
判断: 看好/中性/不看好
适合买入: 是/否/等回调
建议: （具体操作建议）
风险: （最大风险）
机会: （最大机会）"""

        resp = call_deepseek(prompt, system="你是顶级基金分析师，回答简洁、具体、可执行。只输出结果，不解释。")
        if not resp:
            results.append({
                "code": code, "name": info.name, "asset_class": info.asset_class,
                "metrics": {
                    "last_nav": m.last_nav, "ret_1m": m.ret_1m, "ret_3m": m.ret_3m,
                    "rsi14": m.rsi14, "price_percentile": m.price_percentile,
                    "max_drawdown": m.max_drawdown, "vol_annual": m.vol_annual, "sharpe": m.sharpe,
                },
                "error": "AI 分析暂时不可用（请设置 DEEPSEEK_API_KEY）",
            })
            continue

        # 解析 AI 回复
        lines = resp.strip().splitlines()
        ai = {}
        for line in lines:
            for key in ["判断", "适合买入", "建议", "风险", "机会"]:
                if line.startswith(f"{key}:") or line.startswith(f"{key}："):
                    ai[key] = line.split(":", 1)[-1].split("：", 1)[-1].strip()

        results.append({
            "code": code,
            "name": info.name,
            "asset_class": info.asset_class,
            "metrics": {
                "last_nav": m.last_nav, "ret_1m": m.ret_1m, "ret_3m": m.ret_3m,
                "rsi14": m.rsi14, "price_percentile": m.price_percentile,
                "max_drawdown": m.max_drawdown, "vol_annual": m.vol_annual, "sharpe": m.sharpe,
            },
            "judgment": ai.get("判断", "—"),
            "buy_signal": ai.get("适合买入", "—"),
            "advice": ai.get("建议", "—"),
            "risk": ai.get("风险", "—"),
            "opportunity": ai.get("机会", "—"),
        })

    return results


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
