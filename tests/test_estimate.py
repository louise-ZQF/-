import unittest
from datetime import date, timedelta

from fund_analyzer.estimate import estimate_beta_alpha, estimate_holding
from fund_analyzer.models import Tracking


def _series(start, rets):
    """由收益序列生成 (date, ret) 升序列表。"""
    d0 = date(2026, 1, 1)
    return [(d0 + timedelta(days=i), r) for i, r in enumerate(rets, start=start)]


class TestEstimate(unittest.TestCase):
    def test_two_pending_days_compounding(self):
        idx = _series(0, [0.005] * 28 + [0.012, 0.008])  # 末两日 +1.2%, +0.8%
        tk = Tracking(index="^NDX", beta=1.0, lag_days=2, currency_hedged=True)
        r = estimate_holding(base_nav=2.0, base_date=date(2026, 1, 30), tracking=tk,
                             index_rets=idx, annual_fee=0.0)
        self.assertEqual(len(r.pending_returns), 2)
        # 复利 (1.012*1.008 - 1) ≈ 0.020096
        self.assertAlmostEqual(r.cum_return, 1.012 * 1.008 - 1, places=5)
        self.assertAlmostEqual(r.implied_nav, 2.0 * (1 + r.cum_return), places=6)
        self.assertGreaterEqual(r.band, 0.0)

    def test_currency_unhedged_adds_fx(self):
        idx = _series(0, [0.0] * 28 + [0.0, 0.01])
        fx = _series(0, [0.0] * 28 + [0.0, 0.005])  # 最近一日人民币贬值/美元+0.5%
        tk_h = Tracking(index="^NDX", beta=1.0, lag_days=1, currency_hedged=True)
        tk_u = Tracking(index="^NDX", beta=1.0, lag_days=1, currency_hedged=False)
        rh = estimate_holding(base_nav=1.0, base_date=date(2026, 1, 30), tracking=tk_h,
                              index_rets=idx, fx_rets=fx, annual_fee=0.0)
        ru = estimate_holding(base_nav=1.0, base_date=date(2026, 1, 30), tracking=tk_u,
                              index_rets=idx, fx_rets=fx, annual_fee=0.0)
        # 未对冲应比对冲多出约 +0.5% 的汇率贡献
        self.assertAlmostEqual(ru.cum_return - rh.cum_return, 0.005, places=4)

    def test_no_index_no_estimate(self):
        tk = Tracking(index=None)
        r = estimate_holding(base_nav=1.0, base_date=date(2026, 1, 1), tracking=tk, index_rets=[])
        self.assertFalse(r.has_estimate)

    def test_beta_regression_recovers(self):
        # 构造 fund_ret = 1.25 * idx_ret，同日对齐
        idx = _series(0, [0.01, -0.008, 0.005, 0.012, -0.006] * 6)
        fund = [(d, 1.25 * r) for d, r in idx]
        alpha, beta, resid_std, r2, method = estimate_beta_alpha(fund, idx)
        self.assertAlmostEqual(beta, 1.25, places=2)
        self.assertIn("回归", method)

    def test_beta_fallback_when_insufficient(self):
        idx = _series(0, [0.01, -0.01])
        fund = [(d, r) for d, r in idx]
        alpha, beta, resid_std, r2, method = estimate_beta_alpha(fund, idx)
        self.assertEqual(beta, 1.0)
        self.assertIn("default", method)


if __name__ == "__main__":
    unittest.main()
