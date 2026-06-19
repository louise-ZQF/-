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
    rep = Analyzer(settings).run(holdings)
    return report_to_dict(rep, settings.report_title, "live")


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
    """规整前端提交的单条持仓，去掉空值、保证类型。"""
    code = str(d.get("code", "")).strip()
    out: dict = {"code": code}
    if d.get("name"):
        out["name"] = str(d["name"]).strip()
    out["asset_class"] = d.get("asset_class") or "other"
    for k in ("shares", "cost_nav", "annual_fee"):
        v = d.get(k)
        if v not in (None, "", 0, "0"):
            try:
                out[k] = float(v)
            except (TypeError, ValueError):
                pass
    tw = d.get("target_weight")
    if tw not in (None, ""):
        try:
            out["target_weight"] = float(tw)
        except (TypeError, ValueError):
            pass
    out["is_dca"] = bool(d.get("is_dca", False))
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


def save_holdings(holdings: List[dict], path: Optional[str] = None) -> int:
    path = path or holdings_path()
    cleaned = [_clean_holding(h) for h in holdings if str(h.get("code", "")).strip()]
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# 由可视化网站「持仓管理」生成；也可手动编辑。\n")
        yaml.safe_dump({"holdings": cleaned}, f, allow_unicode=True, sort_keys=False)
    return len(cleaned)
