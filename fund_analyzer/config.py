"""配置加载：settings.yaml（策略/阈值）与 holdings.yaml（持仓）。

敏感信息（邮箱授权码、收件人）一律从环境变量读取，绝不写进仓库文件。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

import yaml

from .models import AssetClass, Holding, Tracking


@dataclass
class StrategySettings:
    """策略阈值，均可在 settings.yaml 的 strategy: 段覆盖。"""

    take_profit_target: float = 0.30        # 目标止盈：持仓收益达到即提示分批止盈
    trailing_dd_after_profit: float = 0.10  # 回撤止盈：盈利后从高点回撤超过该比例提示止盈
    stop_loss: float = -0.20                # 卫星仓位的止损警戒（指数定投通常不止损）
    rebalance_band: float = 0.05            # 权重偏离目标超过该绝对值提示再平衡
    rsi_overbought: float = 75.0
    rsi_oversold: float = 30.0
    high_percentile: float = 0.80           # 净值分位高于此 → 高位（偏谨慎）
    low_percentile: float = 0.20            # 净值分位低于此 → 低位（偏积极）
    percentile_lookback: int = 504          # 估值分位回溯交易日（约 2 年）
    rf_annual: float = 0.02                 # 夏普用无风险利率


@dataclass
class DataSourceSettings:
    history_days: int = 400                 # 拉取多少自然日的历史净值
    cache_ttl_minutes: int = 30             # 行情缓存有效期
    cache_dir: str = "data/cache"
    request_timeout: int = 15
    # 指数行情代码 → 数据源 ticker 的映射（Yahoo 风格），可在 yaml 覆盖/扩展
    index_map: dict = field(default_factory=lambda: {
        "^GSPC": "^GSPC",     # 标普500
        "^NDX": "^NDX",       # 纳斯达克100
        "^IXIC": "^IXIC",     # 纳斯达克综合
        "^DJI": "^DJI",       # 道琼斯
        "^SOX": "^SOX",       # 费城半导体
        "USDCNY": "CNY=X",    # 美元兑人民币
    })


@dataclass
class Settings:
    base_currency: str = "CNY"
    strategy: StrategySettings = field(default_factory=StrategySettings)
    datasource: DataSourceSettings = field(default_factory=DataSourceSettings)
    report_title: str = "基金组合每日分析报告"


# ----------------------------------------------------------------------------
# 加载器
# ----------------------------------------------------------------------------

def _load_yaml(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_settings(path: str = "config/settings.yaml") -> Settings:
    raw = _load_yaml(path)
    s = Settings()
    if "base_currency" in raw:
        s.base_currency = raw["base_currency"]
    if "report_title" in raw:
        s.report_title = raw["report_title"]
    for k, v in (raw.get("strategy") or {}).items():
        if hasattr(s.strategy, k):
            setattr(s.strategy, k, v)
    ds = raw.get("datasource") or {}
    for k, v in ds.items():
        if k == "index_map" and isinstance(v, dict):
            s.datasource.index_map.update(v)
        elif hasattr(s.datasource, k):
            setattr(s.datasource, k, v)
    return s


def _parse_holding(d: dict) -> Holding:
    tk = d.get("tracking") or {}
    tracking = Tracking(
        index=tk.get("index"),
        beta=tk.get("beta", "auto"),
        lag_days=int(tk.get("lag_days", 1)),
        currency_hedged=bool(tk.get("currency_hedged", False)),
        fx_index=tk.get("fx_index", "USDCNY"),
    )
    ac = d.get("asset_class", "other")
    try:
        asset_class = AssetClass(ac)
    except ValueError:
        asset_class = AssetClass.OTHER
    return Holding(
        code=str(d["code"]).zfill(6) if str(d["code"]).isdigit() else str(d["code"]),
        name=d.get("name", ""),
        asset_class=asset_class,
        shares=float(d.get("shares", 0) or 0),
        cost_nav=float(d.get("cost_nav", 0) or 0),
        target_weight=(float(d["target_weight"]) if d.get("target_weight") is not None else None),
        is_dca=bool(d.get("is_dca", False)),
        annual_fee=float(d.get("annual_fee", 0) or 0),
        tracking=tracking,
        note=d.get("note", ""),
    )


def load_holdings(path: str = "config/holdings.yaml") -> List[Holding]:
    raw = _load_yaml(path)
    items = raw.get("holdings", raw if isinstance(raw, list) else [])
    return [_parse_holding(d) for d in items]


# ----------------------------------------------------------------------------
# 邮件配置（全部来自环境变量 / GitHub Secrets）
# ----------------------------------------------------------------------------

@dataclass
class EmailConfig:
    host: str = ""
    port: int = 465
    user: str = ""
    password: str = ""
    sender: str = ""
    recipients: List[str] = field(default_factory=list)
    use_ssl: bool = True

    @property
    def configured(self) -> bool:
        return bool(self.host and self.user and self.password and self.recipients)


# QQ / 163 常见 SMTP 预设
SMTP_PRESETS = {
    "qq": ("smtp.qq.com", 465),
    "163": ("smtp.163.com", 465),
    "126": ("smtp.126.com", 465),
    "gmail": ("smtp.gmail.com", 465),
}


def load_email_config() -> EmailConfig:
    """从环境变量读取邮件配置。

    SMTP_PROVIDER=qq|163|126|gmail 可自动填 host/port；也可显式给 SMTP_HOST/SMTP_PORT。
    SMTP_USER     发件邮箱（完整地址）
    SMTP_PASSWORD 授权码（不是登录密码！QQ/163 需在邮箱设置里开启 SMTP 并生成授权码）
    MAIL_TO       收件人，多个用逗号分隔（缺省=发给自己）
    MAIL_FROM     可选，显示的发件人，缺省=SMTP_USER
    """
    provider = (os.getenv("SMTP_PROVIDER") or "").lower().strip()
    host = os.getenv("SMTP_HOST", "").strip()
    port_env = os.getenv("SMTP_PORT", "").strip()
    if provider in SMTP_PRESETS and not host:
        host, preset_port = SMTP_PRESETS[provider]
        port = int(port_env) if port_env else preset_port
    else:
        port = int(port_env) if port_env else 465
    user = os.getenv("SMTP_USER", "").strip()
    to_raw = os.getenv("MAIL_TO", "").strip() or user
    recipients = [x.strip() for x in to_raw.split(",") if x.strip()]
    return EmailConfig(
        host=host,
        port=port,
        user=user,
        password=os.getenv("SMTP_PASSWORD", ""),
        sender=os.getenv("MAIL_FROM", "").strip() or user,
        recipients=recipients,
        use_ssl=(os.getenv("SMTP_USE_SSL", "true").lower() != "false"),
    )
