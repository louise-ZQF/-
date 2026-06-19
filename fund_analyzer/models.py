"""数据模型。

刻意使用标准库 dataclass，避免引入 pydantic 等额外依赖。
金额/比例统一约定：
    * 比例（涨跌幅、权重、收益率）一律用「小数」表示，例如 0.0123 表示 +1.23%。
      仅在展示层（report）转成百分比字符串。
    * 净值（NAV）保留原始浮点。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional


class AssetClass(str, Enum):
    """资产大类，用于组合层的配置与再平衡。"""

    US_EQUITY = "us_equity"      # 美股（含纳指/标普/美股科技等 QDII）
    CN_EQUITY = "cn_equity"      # A 股 / 港股
    HK_EQUITY = "hk_equity"
    GLOBAL_EQUITY = "global_equity"
    COMMODITY = "commodity"      # 黄金 / 原油等
    BOND = "bond"
    CASH = "cash"
    OTHER = "other"


class Action(str, Enum):
    """对单只基金的操作建议（从看多到看空排序）。"""

    BUY_MORE = "加大定投/分批买入"
    DCA_CONTINUE = "继续定投"
    HOLD = "持有观望"
    DCA_PAUSE = "暂停定投"
    TRIM = "部分止盈/减仓"
    SELL = "考虑卖出"


@dataclass
class Tracking:
    """QDII / 指数基金的「跟踪标的」配置，供时差估算引擎使用。

    index:           跟踪的指数行情代码（数据源内部代码，如 '^NDX' '^GSPC'）。
    beta:            基金对指数的敏感度。'auto' 表示用历史净值回归估计；否则为固定浮点。
    lag_days:        基金净值相对指数收盘「滞后」的交易日数（A 股 QDII 常见 1~2 天）。
    currency_hedged: 是否做了汇率对冲。False 时叠加 USD/CNY 变动。
    fx_index:        汇率行情代码（默认人民币兑美元）。
    """

    index: Optional[str] = None
    beta: object = "auto"          # 'auto' 或 float
    lag_days: int = 1
    currency_hedged: bool = False
    fx_index: str = "USDCNY"

    @property
    def beta_value(self) -> Optional[float]:
        return None if self.beta == "auto" else float(self.beta)


@dataclass
class Holding:
    """一笔持仓。

    cost_nav 与 shares 用于计算市值与持仓收益；若用户只想做信号分析，
    可只填 code / asset_class / tracking，市值类字段留空。
    """

    code: str
    name: str = ""
    asset_class: AssetClass = AssetClass.OTHER
    shares: float = 0.0            # 持有份额
    cost_nav: float = 0.0          # 持仓成本（单位净值口径的平均成本）
    target_weight: Optional[float] = None  # 目标权重（小数），用于再平衡
    is_dca: bool = False           # 是否正在定投
    annual_fee: float = 0.0        # 年综合费率（管理+托管），用于估算的费用拖累
    tracking: Tracking = field(default_factory=Tracking)
    note: str = ""

    @property
    def cost_amount(self) -> float:
        return self.shares * self.cost_nav


@dataclass
class Quote:
    """某只基金的最新行情（已公布净值 + 平台实时估值）。"""

    code: str
    name: str = ""
    nav: Optional[float] = None        # 最新「已公布」单位净值
    nav_date: Optional[date] = None    # 该净值对应日期
    prev_nav: Optional[float] = None
    # 平台（天天基金）给的盘中实时估值，QDII 常常不准/缺失，仅作参考
    gsz: Optional[float] = None
    gsz_change: Optional[float] = None  # 小数
    gsz_time: Optional[str] = None
    source: str = ""


@dataclass
class NavPoint:
    """历史净值的一个数据点。"""

    d: date
    nav: float                 # 单位净值
    cum_nav: Optional[float] = None  # 累计净值
    change: Optional[float] = None   # 当日涨跌幅（小数）


@dataclass
class EstimateResult:
    """QDII 时差收益估算结果（核心产物）。

    pending_returns: 尚未体现在「已公布净值」里的、逐个交易日的估算收益（小数）。
    cum_return:      上述若干日累计估算收益（小数）。
    implied_nav:     在最新已公布净值基础上推算出的「应有净值」。
    band:            约 1 个标准差的误差带（小数），来自历史跟踪误差。
    detail:          人类可读的推导说明（逐日）。
    """

    code: str
    base_nav: Optional[float] = None
    base_date: Optional[date] = None
    pending_returns: list = field(default_factory=list)
    cum_return: float = 0.0
    implied_nav: Optional[float] = None
    band: float = 0.0
    beta_used: Optional[float] = None
    method: str = ""
    detail: list = field(default_factory=list)

    @property
    def has_estimate(self) -> bool:
        return bool(self.pending_returns)


@dataclass
class Signal:
    """单条策略信号。

    vote ∈ [-2, +2]：正=偏多（倾向买入/继续），负=偏空（倾向减仓/暂停）。
    hard:  是否为「硬触发」（如已达止盈目标），在汇总时会被特别标注。
    """

    name: str
    vote: float
    text: str
    hard: bool = False


@dataclass
class Metrics:
    """单只基金的关键量化指标快照。"""

    last_nav: Optional[float] = None
    ret_1w: Optional[float] = None
    ret_1m: Optional[float] = None
    ret_3m: Optional[float] = None
    ret_1y: Optional[float] = None
    ma20: Optional[float] = None
    ma60: Optional[float] = None
    ma120: Optional[float] = None
    rsi14: Optional[float] = None
    max_drawdown: Optional[float] = None
    vol_annual: Optional[float] = None
    sharpe: Optional[float] = None
    price_percentile: Optional[float] = None  # 当前净值在回溯窗口内的分位（0~1）
    holding_return: Optional[float] = None     # 相对成本的持仓收益（小数）


@dataclass
class FundAnalysis:
    """单只基金的完整分析结果。"""

    holding: Holding
    quote: Optional[Quote] = None
    metrics: Metrics = field(default_factory=Metrics)
    estimate: Optional[EstimateResult] = None
    signals: list = field(default_factory=list)
    action: Action = Action.HOLD
    score: float = 0.0
    rationale: str = ""
    history: list = field(default_factory=list)   # list[NavPoint]，供前端画净值走势

    @property
    def market_value(self) -> Optional[float]:
        """以最新已公布净值计的市值。"""
        if self.quote and self.quote.nav and self.holding.shares:
            return self.quote.nav * self.holding.shares
        return None

    @property
    def implied_value(self) -> Optional[float]:
        """以时差估算「应有净值」计的市值（用于看『今天真实赚了多少』）。"""
        if self.estimate and self.estimate.implied_nav and self.holding.shares:
            return self.estimate.implied_nav * self.holding.shares
        return self.market_value


@dataclass
class PortfolioReport:
    """组合层汇总报告。"""

    as_of: datetime
    funds: list = field(default_factory=list)        # list[FundAnalysis]
    total_value: Optional[float] = None
    total_implied_value: Optional[float] = None
    total_cost: Optional[float] = None
    est_today_change: Optional[float] = None         # 组合「时差估算」当日涨跌（小数）
    portfolio_notes: list = field(default_factory=list)
    market_brief: list = field(default_factory=list)  # 市场情报摘要
