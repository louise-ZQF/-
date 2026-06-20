"""测试回测框架。"""
import pytest
from datetime import date
from fund_analyzer.backtest import BacktestResult, quick_backtest, compare_with_baselines


def test_backtest_result_empty():
    br = BacktestResult(method="test")
    assert br.mean_3m == 0
    assert br.win_rate_3m == 0
    assert len(br.dates) == 0


def test_backtest_result_with_data():
    br = BacktestResult(
        method="test",
        dates=["2026-01-01", "2026-04-01"],
        forward_3m=[0.05, 0.03],
        forward_6m=[0.10, 0.06],
        forward_12m=[0.20, 0.12],
    )
    assert br.mean_3m == 0.04
    assert br.win_rate_3m == 1.0
    d = br.to_dict()
    assert d["method"] == "test"
    assert d["n_periods"] == 2


def test_quick_backtest():
    funds = [
        {"code": "A", "name": "Fund A", "composite_score": 85},
        {"code": "B", "name": "Fund B", "composite_score": 72},
        {"code": "C", "name": "Fund C", "composite_score": 60},
        {"code": "D", "name": "Fund D", "composite_score": 55},
        {"code": "E", "name": "Fund E", "composite_score": 45},
    ]
    result = quick_backtest(funds)
    assert result["funds_analyzed"] == 5
    assert 45 < result["avg_composite_score"] < 85
    assert len(result["top_3"]) == 3
    assert result["top_3"][0]["score"] == 85


def test_quick_backtest_too_few():
    result = quick_backtest([{"code": "A", "name": "X", "composite_score": 80}])
    assert "error" in result


def test_compare_with_baselines():
    fund_pool = [
        {"code": "A", "ret_12m": 0.15, "annual_fee": 0.01, "ret_1y": 0.20},
        {"code": "B", "ret_12m": 0.10, "annual_fee": 0.005, "ret_1y": 0.12},
        {"code": "C", "ret_12m": 0.08, "annual_fee": 0.015, "ret_1y": 0.05},
    ] * 5
    screener = BacktestResult(method="screener", dates=["2026-01-01"], forward_12m=[0.12])
    results = compare_with_baselines(fund_pool, screener)
    assert "screener" in results
    assert "random" in results
    assert "lowest_fee" in results
    assert "highest_1y_return" in results
    assert "peer_average" in results
