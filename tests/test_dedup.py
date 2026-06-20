"""测试去重模块。"""
import pytest
from fund_analyzer.share_class_dedup import find_share_class_pairs, deduplicate_share_classes, deduplicate_same_index

def test_find_pairs():
    funds = [
        {"code": "012920", "name": "易方达全球成长精选混合(QDII)人民币A"},
        {"code": "012922", "name": "易方达全球成长精选混合(QDII)人民币C"},
    ]
    pairs = find_share_class_pairs(funds)
    assert len(pairs) == 1

def test_deduplicate_share_classes():
    funds = [
        {"code": "012920", "name": "基金A", "annual_fee": 0.01},
        {"code": "012922", "name": "基金C", "annual_fee": 0.014},
    ]
    result = deduplicate_share_classes(funds)
    assert len(result) == 1

def test_deduplicate_same_index():
    funds = [
        {"code": "A", "benchmark_code": "^NDX", "composite_score": 80, "name": "A"},
        {"code": "B", "benchmark_code": "^NDX", "composite_score": 90, "name": "B"},
        {"code": "C", "benchmark_code": "^GSPC", "composite_score": 70, "name": "C"},
    ]
    result = deduplicate_same_index(funds)
    assert len(result) == 2
    ndx = [f for f in result if f["benchmark_code"] == "^NDX"]
    assert ndx[0]["composite_score"] == 90
