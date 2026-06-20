"""集成测试：筛选器管线。"""
import pytest
from datetime import date
from fund_analyzer.fund_classifier import classify_fund, peer_group_key
from fund_analyzer.benchmark_mapper import (
    get_benchmark_info, get_qdii_lag, get_fx_code,
    combine_index_and_fx, estimate_best_lag, align_nav_dates, compute_tracking_metrics,
)


def test_classify_then_benchmark():
    """分类 → 基准匹配 → 检查一致性。"""
    # All US passive index funds should have Yahoo-compatible benchmarks
    funds = [
        ("270042", "广发纳斯达克100ETF联接(QDII)A"),
        ("050025", "博时标普500ETF联接(QDII)"),
        ("110020", "易方达沪深300ETF联接"),
    ]
    for code, name in funds:
        fc = classify_fund(code, name)
        info = get_benchmark_info(fc.benchmark_code)
        assert info["name"]  # Benchmark should have a name
        if fc.is_qdii and fc.asset_region == "us":
            assert get_qdii_lag(fc.benchmark_code) >= 1


def test_peer_group_key():
    from fund_analyzer.fund_classifier import FundClass
    fc = FundClass("000000", "test", "passive_index", "us", "^NDX", True)
    assert "^NDX_passive" in peer_group_key(fc)

    fc2 = FundClass("000000", "test", "active_equity", "cn", "000300", False)
    assert "cn" in peer_group_key(fc2) and "active" in peer_group_key(fc2)


def test_combine_index_and_fx():
    from datetime import date
    index_rets = [(date(2026, 1, 5), 0.01), (date(2026, 1, 6), -0.005)]
    fx_rets = [(date(2026, 1, 5), 0.003), (date(2026, 1, 6), -0.001)]
    combined = combine_index_and_fx(index_rets, fx_rets)
    assert len(combined) == 2
    # (1.01)*(1.003)-1 ≈ 0.01303
    assert abs(combined[0][1] - 0.01303) < 0.0001


def test_align_and_tracking():
    from datetime import date, timedelta
    # Simulate: fund nav published 2 days after benchmark
    base = date(2026, 1, 1)
    fund_navs = [(base + timedelta(days=i), 100 * (1 + 0.001 * i)) for i in range(100)]
    bench_rets = [(base + timedelta(days=i), 0.001 if i % 2 == 0 else -0.0005) for i in range(100)]

    aligned = align_nav_dates(fund_navs, bench_rets, 0)
    if aligned:
        metrics = compute_tracking_metrics(aligned)
        assert "tracking_error" in metrics
        assert "beta" in metrics
        assert -5 <= metrics.get("beta", 1) <= 5


def test_estimate_best_lag():
    from datetime import date, timedelta
    base = date(2026, 1, 1)
    fund_rets = [(base + timedelta(days=i), 0.001) for i in range(60)]
    bench_rets = [(base + timedelta(days=i), 0.001) for i in range(60)]
    lag = estimate_best_lag(fund_rets, bench_rets)
    assert isinstance(lag, int)
    assert 0 <= lag <= 4


def test_fx_code_for_qdii():
    assert get_fx_code("^NDX") == "USDCNY"
    assert get_fx_code("^GSPC") == "USDCNY"
    assert get_fx_code("^HSI") == "HKDCNY"
    assert get_fx_code("000300") is None  # CNY, no FX needed
