"""组合暴露分析：指数重叠、地区集中度、货币风险。"""
from __future__ import annotations
from typing import Dict, List

def analyze_exposure(funds: List[dict]) -> dict:
    """分析组合暴露。

    funds: [{"code", "name", "benchmark_code", "asset_region", "current_value", "currency"}, ...]
    """
    total = sum(f.get("current_value", 0) or 0 for f in funds)
    if total <= 0:
        return {"error": "无市值数据"}

    # 1. 基准指数暴露
    by_benchmark: Dict[str, dict] = {}
    for f in funds:
        bm = f.get("benchmark_code", "unknown")
        val = f.get("current_value", 0) or 0
        if bm not in by_benchmark:
            by_benchmark[bm] = {"value": 0, "funds": [], "pct": 0}
        by_benchmark[bm]["value"] += val
        by_benchmark[bm]["funds"].append(f["code"])

    for bm, info in by_benchmark.items():
        info["pct"] = round(info["value"] / total * 100, 1)

    # 2. 地区暴露
    by_region: Dict[str, float] = {}
    for f in funds:
        region = f.get("asset_region", "other")
        val = f.get("current_value", 0) or 0
        by_region[region] = by_region.get(region, 0) + val

    # 3. 币种暴露
    _REGION_CURRENCY = {"us": "USD", "cn": "CNY", "hk": "HKD", "global": "USD"}
    by_currency: Dict[str, float] = {}
    for f in funds:
        curr = f.get("currency") or _REGION_CURRENCY.get(f.get("asset_region", ""), "CNY")
        val = f.get("current_value", 0) or 0
        by_currency[curr] = by_currency.get(curr, 0) + val

    # 4. 集中度警告
    warnings = []
    for bm, info in sorted(by_benchmark.items(), key=lambda x: -x[1]["pct"]):
        if info["pct"] > 50:
            warnings.append(f"⚠️ {bm} 暴露 {info['pct']}%，过于集中")
        if len(info["funds"]) > 2:
            warnings.append(f"💡 {bm} 持有 {len(info['funds'])} 只基金，存在重复")

    # 5. 纳斯达克/美股科技特殊检查
    us_tech_pct = sum(
        f.get("current_value", 0) or 0
        for f in funds
        if f.get("benchmark_code") in ("^NDX", "^IXIC") or "纳斯达克" in f.get("name", "")
    ) / max(total, 1) * 100
    if us_tech_pct > 60:
        warnings.append(f"🔴 美股科技/纳斯达克估算暴露 {us_tech_pct:.0f}%，系统性风险高")

    return {
        "total_value": round(total, 2),
        "by_benchmark": {bm: {"pct": info["pct"], "funds": info["funds"]} for bm, info in sorted(by_benchmark.items(), key=lambda x: -x[1]["pct"])},
        "by_region": {r: round(v/total*100, 1) for r, v in sorted(by_region.items(), key=lambda x: -x[1])},
        "by_currency": {c: round(v/total*100, 1) for c, v in sorted(by_currency.items(), key=lambda x: -x[1])},
        "warnings": warnings,
        "us_tech_pct": round(us_tech_pct, 1),
    }
