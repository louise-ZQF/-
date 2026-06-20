"""基金经理风格契合度评分卡 — 六维评估基金投资风格。

基于基金经理郑希的公开投资方法蒸馏而来，每维 0-100 分。
此评分衡量"风格特征"，非基金优劣判断。
"""
from __future__ import annotations
from typing import Dict, List

DIMENSIONS: Dict[str, dict] = {
    "cycle_positioning": {"label": "景气方向/通胀属性", "weight": 25,
        "desc": "重仓是否集中在新技术落地、供给端创造需求的景气方向"},
    "roe_elasticity": {"label": "ROE低位弹性偏好", "weight": 20,
        "desc": "是否偏好ROE从低到高的修复弹性（而非高ROE白马）"},
    "global_advantage": {"label": "全球视野/中国比较优势", "weight": 15,
        "desc": "方向是否落在全球技术周期+中国有比较优势的环节"},
    "liquidity": {"label": "流动性管理", "weight": 10,
        "desc": "重仓股流动性、规模与持仓风格匹配度"},
    "concentration_cycling": {"label": "集中度与周期拼接", "weight": 15,
        "desc": "是否适度集中+动态调仓（高换手=周期拼接=加分）"},
    "performance_validation": {"label": "业绩与回撤印证", "weight": 15,
        "desc": "是否靠选对景气方向赚到了景气的钱"},
}


def score_manager_style(fund: dict, navs: List[float]) -> dict:
    """评估基金的风格特征。

    fund: {"name", "code", "asset_class", "fund_type", "factors", ...}
    navs: 净值序列
    返回: {dimension_scores, composite, style_label, analysis}
    """
    scores = {}
    factor_scores = fund.get("factors") or {}
    fs_scores = factor_scores.get("scores", {}) if isinstance(factor_scores, dict) else {}

    # Helper: extract individual score from factor dict
    def _fs(key: str, default: float = 50) -> float:
        return fs_scores.get(key, default) if isinstance(fs_scores, dict) else default

    # 1. 景气方向 (25): 用动量+趋势代理 — 强动量=大概率踩在景气方向上
    mom = _fs("momentum", 50)
    trend = _fs("trend_quality", 50)
    scores["cycle_positioning"] = round(mom * 0.6 + trend * 0.4, 1)

    # 2. ROE弹性 (20): 中高波动+中小市值偏好=弹性标的
    vol = _fs("vol_regime", 50)
    scores["roe_elasticity"] = round(max(50, vol), 1)

    # 3. 全球视野 (15): QDII/海外=高分，纯A股=中等
    region = fund.get("asset_region", fund.get("asset_class", "cn"))
    if region in ("us", "global", "us_equity", "global_equity"):
        scores["global_advantage"] = 85
    elif region in ("hk", "hk_equity"):
        scores["global_advantage"] = 70
    else:
        scores["global_advantage"] = 40

    # 4. 流动性 (10): 用规模代理
    size = fund.get("fund_size")
    if size is None:
        scores["liquidity"] = 60
    elif size < 2e8:
        scores["liquidity"] = 70  # 小规模=灵活
    elif size < 1e9:
        scores["liquidity"] = 80
    else:
        scores["liquidity"] = 50  # 太大可能影响灵活性

    # 5. 集中度+周期拼接 (15): 用趋势质量+回撤恢复代理
    dd_recovery = _fs("drawdown_recovery", 50)
    scores["concentration_cycling"] = round(trend * 0.5 + dd_recovery * 0.5, 1)

    # 6. 业绩印证 (15): 用风险调整收益代理
    risk_adj = _fs("risk_adjusted", 50)
    scores["performance_validation"] = round(risk_adj, 1)

    # 加权综合
    composite = sum(scores[k] * DIMENSIONS[k]["weight"] / 100 for k in DIMENSIONS)

    # 风格标签
    if composite >= 70:
        style = "成长景气型（类似郑希风格）"
    elif composite >= 55:
        style = "偏成长"
    elif composite >= 40:
        style = "均衡型"
    else:
        style = "偏防御/价值"

    return {
        "dimensions": {k: {"label": DIMENSIONS[k]["label"], "score": scores[k], "weight": DIMENSIONS[k]["weight"]}
                       for k in DIMENSIONS},
        "composite": round(composite, 1),
        "style_label": style,
        "analysis": _generate_style_analysis(scores, composite, style),
    }


def _generate_style_analysis(scores: dict, composite: float, style: str) -> str:
    """生成风格分析文字。"""
    top = sorted(scores.items(), key=lambda x: -x[1])[:2]
    bottom = sorted(scores.items(), key=lambda x: x[1])[:2]
    top_labels = [DIMENSIONS[k]["label"] for k, v in top]
    bottom_labels = [DIMENSIONS[k]["label"] for k, v in bottom]
    return f"风格: {style}({composite:.0f}分)。优势维度: {'、'.join(top_labels)}。偏弱维度: {'、'.join(bottom_labels)}。"
