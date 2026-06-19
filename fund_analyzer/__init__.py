"""fund_analyzer —— 基金组合智能分析与每日建议系统。

模块总览：
    models      数据模型（持仓 / 行情 / 净值 / 建议 / 估算结果）
    config      配置加载（settings.yaml + holdings.yaml）
    indicators  技术与统计指标（均线 / RSI / 最大回撤 / 夏普 / 波动率 / 百分位）
    estimate    QDII「T+时差」收益估算引擎（核心功能）
    strategy    策略引擎（止盈 / 止损 / 定投 / 再平衡 → 操作建议）
    portfolio   组合层聚合分析
    report      中文报告生成（Markdown / HTML）
    emailer     SMTP 邮件发送（QQ / 163）
    datasource  数据源适配器（天天基金 / 美股指数行情）
    cli         命令行入口

设计原则：
    1. 纯逻辑（indicators/estimate/strategy/report）与 IO（datasource/emailer）解耦，
       便于离线单元测试；
    2. 所有「预测 / 建议」均为基于公开规则的量化参考，不构成投资建议（见 README 免责声明）。
"""

__version__ = "0.1.0"
__all__ = ["__version__"]
