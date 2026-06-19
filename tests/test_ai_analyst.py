import pytest
from fund_analyzer.ai_analyst import (
    build_fund_prompt, build_portfolio_prompt, parse_ai_response,
    AiSentiment, AiPortfolioAnalysis,
)
from fund_analyzer.models import (
    FundAnalysis, Holding, Metrics, AssetClass, Tracking,
)


def make_fa(code, name, ac=AssetClass.US_EQUITY, ret_1m=0.03):
    """Quick test fixture."""
    h = Holding(code=code, name=name, asset_class=ac, shares=1000, cost_nav=1.5,
                current_value=2000)
    m = Metrics(last_nav=1.8, ret_1m=ret_1m, ret_3m=0.08, rsi14=58,
                price_percentile=0.65, holding_return=0.20)
    return FundAnalysis(holding=h, metrics=m)


def test_build_fund_prompt():
    funds = [make_fa("270042", "广发纳指100")]
    news = {"270042": ["美股科技财报超预期", "美联储会议纪要偏鸽"]}
    prompt = build_fund_prompt(funds, news)
    assert "270042" in prompt
    assert "广发纳指100" in prompt
    assert "美股科技" in prompt


def test_build_fund_prompt_no_news():
    funds = [make_fa("110020", "易方达沪深300")]
    prompt = build_fund_prompt(funds)
    assert "110020" in prompt
    assert "易方达沪深300" in prompt


def test_build_portfolio_prompt():
    funds = [
        make_fa("270042", "广发纳指100", AssetClass.US_EQUITY),
        make_fa("110020", "易方达沪深300", AssetClass.CN_EQUITY),
    ]
    prompt = build_portfolio_prompt(funds, 5000)
    assert "客户组合" in prompt or "整体组合" in prompt or "投资组合" in prompt
    assert "美股" in prompt or "us" in prompt.lower()


def test_parse_ai_response_funds():
    text = """270042: 看好 | 科技财报驱动，纳指趋势向好，RSI中性 | 继续定投
110020: 谨慎 | A股情绪偏弱，估值分位偏高 | 暂停定投"""
    results = parse_ai_response(text)
    assert results["funds"]["270042"]["sentiment"] == "看好"
    assert results["funds"]["270042"]["suggestion"] == "继续定投"
    assert results["funds"]["110020"]["sentiment"] == "谨慎"


def test_parse_ai_response_portfolio():
    text = """### 组合分析
当前组合偏科技/美股，持仓集中度较高。近期全球科技面临监管风险。

### 定投调整建议
270042: 维持 | 趋势良好
110020: 减少50% | 短期性价比不高"""
    results = parse_ai_response(text)
    assert "科技" in results["portfolio_analysis"]
    assert "270042" in results["dca_adjustments"]


def test_ai_sentiment_defaults():
    s = AiSentiment(code="270042", sentiment="中性", reason="测试", suggestion="维持")
    assert s.code == "270042"
    assert s.sentiment == "中性"
    assert s.reason == "测试"
    assert s.suggestion == "维持"
    assert s.suggestion == "维持"


def test_ai_portfolio_analysis_empty():
    a = AiPortfolioAnalysis()
    assert a.funds == {}
    assert a.portfolio_analysis == ""
