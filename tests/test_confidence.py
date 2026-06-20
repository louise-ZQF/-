"""测试置信度模块。"""
import pytest
from datetime import date
from fund_analyzer.confidence import compute_confidence, adjust_score_with_confidence

def test_confidence_capped():
    fund = {"inception_date": "2020-01-01", "nav_days": 1000, "expected_days": 252}
    result = compute_confidence(fund, as_of_date=date(2026, 6, 20))
    assert result["confidence"] <= 100
    assert result["data_completeness"] <= 100

def test_confidence_with_missing():
    fund = {"inception_date": None, "nav_days": 100, "expected_days": 252,
            "data_quality": {"fee_missing": True, "size_missing": True}}
    result = compute_confidence(fund, as_of_date=date(2026, 6, 20))
    assert result["confidence"] < 80

def test_adjust_score():
    assert adjust_score_with_confidence(80, 1.0) == 80
    assert adjust_score_with_confidence(80, 0.5) == 65
    assert abs(adjust_score_with_confidence(80, 0.0) - 50) < 0.01
