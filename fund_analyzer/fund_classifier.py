"""基金分类器：区分被动指数/主动/QDII，为不同评分模型提供路由。"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class FundClass:
    code: str
    name: str
    fund_type: str          # "passive_index" | "active_equity" | "active_hybrid" | "bond" | "other"
    asset_region: str       # "us" | "cn" | "hk" | "global" | "other"
    benchmark_code: str     # 匹配的基准代码
    is_qdii: bool = False
    inception_date: Optional[str] = None


# 被动指数基金关键词 → (类型, 地区, 基准)
_PASSIVE_INDEX_MAP = [
    # 纳斯达克系列
    (["纳斯达克100", "纳指100", "nasdaq100", "nasdaq 100"], "passive_index", "us", "^NDX"),
    (["纳斯达克", "纳指", "nasdaq"], "passive_index", "us", "^IXIC"),
    # 标普系列
    (["标普500", "s&p500", "sp500", "标普 500", "s&p 500"], "passive_index", "us", "^GSPC"),
    (["标普", "s&p"], "passive_index", "us", "^GSPC"),
    # 道指
    (["道琼斯", "道指", "dji"], "passive_index", "us", "^DJI"),
    # 费城半导体
    (["费城半导体", "sox", "半导体etf"], "passive_index", "us", "^SOX"),
    # 沪深300
    (["沪深300", "csi300", "hs300"], "passive_index", "cn", "000300"),
    # 中证500
    (["中证500", "csi500"], "passive_index", "cn", "000905"),
    # 上证50
    (["上证50", "sse50"], "passive_index", "cn", "000016"),
    # 创业板
    (["创业板", "gem"], "passive_index", "cn", "399006"),
    # 科创
    (["科创50", "star50"], "passive_index", "cn", "000688"),
    # 恒生
    (["恒生科技", "hstech"], "passive_index", "hk", "^HSTECH"),
    (["恒生", "hsi", "恒指"], "passive_index", "hk", "^HSI"),
    # 全球
    (["msci全球", "msci world", "全球指数"], "passive_index", "global", "MSCI_WORLD"),
    # 债券
    (["国债", "利率债", "信用债", "纯债", "中债"], "bond", "cn", "CBA001"),
    # 黄金
    (["黄金", "gold"], "passive_index", "us", "GC=F"),
]


def classify_fund(code: str, name: str) -> FundClass:
    """根据基金名称自动分类。"""
    name_lower = name.lower()

    for keywords, ftype, region, benchmark in _PASSIVE_INDEX_MAP:
        for kw in keywords:
            if kw.lower() in name_lower:
                return FundClass(
                    code=code, name=name,
                    fund_type=ftype, asset_region=region,
                    benchmark_code=benchmark,
                    is_qdii=(region == "us" or region == "hk" or region == "global"),
                )

    # 默认：主动权益基金
    is_qdii = any(kw in name_lower for kw in ["qdii", "美元", "海外", "全球"])
    region = "global" if is_qdii else "cn"
    return FundClass(
        code=code, name=name,
        fund_type="active_equity", asset_region=region,
        benchmark_code="000300" if region == "cn" else "^GSPC",
        is_qdii=is_qdii,
    )


def is_passive_index(name: str) -> bool:
    """快速判断是否为被动指数基金。"""
    fc = classify_fund("", name)
    return fc.fund_type == "passive_index"


def is_active_fund(name: str) -> bool:
    """快速判断是否为主动基金。"""
    return not is_passive_index(name)
