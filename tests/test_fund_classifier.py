"""测试基金分类器。"""
import pytest
from fund_analyzer.fund_classifier import classify_fund, is_passive_index, is_active_fund

def test_nasdaq_passive():
    fc = classify_fund("270042", "广发纳斯达克100ETF联接(QDII)A")
    assert fc.fund_type == "passive_index"
    assert fc.benchmark_code == "^NDX"
    assert fc.is_qdii

def test_sp500_passive():
    fc = classify_fund("050025", "博时标普500ETF联接(QDII)")
    assert fc.fund_type == "passive_index"
    assert fc.benchmark_code == "^GSPC"

def test_csi300_passive():
    fc = classify_fund("110020", "易方达沪深300ETF联接")
    assert fc.fund_type == "passive_index"
    assert fc.benchmark_code == "000300"

def test_active_fund():
    fc = classify_fund("012920", "易方达全球成长精选混合(QDII)人民币A")
    assert fc.fund_type == "active_equity"

def test_is_passive():
    assert is_passive_index("广发纳斯达克100ETF联接")
    assert not is_passive_index("易方达全球成长精选混合")

def test_is_active():
    assert is_active_fund("易方达全球成长精选混合")
