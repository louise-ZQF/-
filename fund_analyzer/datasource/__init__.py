"""数据源适配器。

eastmoney      天天基金：实时估值 + 历史净值
market_index   美股指数 / 汇率日线（Yahoo Finance，stooq 兜底）

所有适配器：
    * 失败时返回空/None 而非抛异常，保证主流程稳健降级；
    * 带本地文件缓存（TTL 可配），减少请求、便于离线复跑。
"""
from .eastmoney import EastMoney
from .market_index import MarketIndex

__all__ = ["EastMoney", "MarketIndex"]
