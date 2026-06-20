"""测试因子评分模块。"""
import pytest
from fund_analyzer.factors import (
    compute_factor_scores, factors_to_dict,
    _momentum_score, _trend_quality_score, _price_position_score,
    _risk_adjusted_score, _vol_regime_score, _drawdown_recovery_score,
    FactorScores,
)

def make_uptrend_navs(n=200):
    import math
    return [100.0 * (1 + 0.001 * i + 0.0005 * math.sin(i/20)) for i in range(n)]

def test_compute_factor_scores():
    navs = make_uptrend_navs(200)
    fs = compute_factor_scores(navs)
    assert isinstance(fs, FactorScores)
    assert 0 <= fs.composite <= 100
    assert 0 <= fs.quality_score <= 100
    assert 0 <= fs.timing_score <= 100
    assert len(fs.notes) == 6

def test_factors_to_dict():
    navs = make_uptrend_navs(200)
    fs = compute_factor_scores(navs)
    d = factors_to_dict(fs)
    assert "scores" in d
    assert "quality_score" in d
    assert "timing_score" in d
    assert "composite" in d
    assert d["composite"] == fs.composite

def test_price_position_uptrend():
    navs = make_uptrend_navs(200)
    score, note = _price_position_score(navs)
    assert 0 <= score <= 100
    assert score < 60  # Near highs in uptrend

def test_risk_adjusted():
    navs = make_uptrend_navs(200)
    rets = [navs[i]/navs[i-1]-1 for i in range(1, len(navs)) if navs[i-1]]
    score, note = _risk_adjusted_score(rets, navs)
    assert 0 <= score <= 100

def test_data_insufficient():
    navs = [100.0, 101.0, 102.0]
    fs = compute_factor_scores(navs)
    assert fs.summary != ""
