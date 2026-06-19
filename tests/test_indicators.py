import unittest

from fund_analyzer import indicators as ind


class TestIndicators(unittest.TestCase):
    def test_sma(self):
        self.assertAlmostEqual(ind.sma([1, 2, 3, 4, 5], 5), 3.0)
        self.assertAlmostEqual(ind.sma([1, 2, 3, 4, 5], 2), 4.5)
        self.assertIsNone(ind.sma([1, 2], 5))

    def test_returns(self):
        r = ind.returns_from_navs([1.0, 1.1, 1.045])
        self.assertAlmostEqual(r[0], 0.1, places=6)
        self.assertAlmostEqual(r[1], -0.05, places=6)

    def test_max_drawdown(self):
        # 峰值 2.0 → 谷值 1.0，回撤 -50%
        self.assertAlmostEqual(ind.max_drawdown([1.0, 2.0, 1.0, 1.5]), -0.5, places=6)
        self.assertIsNone(ind.max_drawdown([1.0]))

    def test_rsi_monotonic_up(self):
        navs = [1.0 + 0.01 * i for i in range(30)]  # 一路上涨
        self.assertAlmostEqual(ind.rsi(navs, 14), 100.0, places=6)

    def test_rsi_range(self):
        navs = [1.0, 1.02, 0.99, 1.03, 1.01, 1.04, 1.00, 1.05, 1.02, 1.06,
                1.03, 1.07, 1.04, 1.08, 1.05, 1.09]
        v = ind.rsi(navs, 14)
        self.assertTrue(0.0 <= v <= 100.0)

    def test_percentile_rank(self):
        s = [1, 2, 3, 4, 5]
        self.assertAlmostEqual(ind.percentile_rank(s, 5), 1.0)
        self.assertAlmostEqual(ind.percentile_rank(s, 1), 0.2)

    def test_trailing_return(self):
        navs = [1.0, 1.1, 1.2, 1.3]
        self.assertAlmostEqual(ind.trailing_return(navs, 1), 1.3 / 1.2 - 1, places=6)
        self.assertIsNone(ind.trailing_return(navs, 10))

    def test_ols_recovers_beta(self):
        xs = [i * 0.001 for i in range(-50, 50)]
        ys = [0.0005 + 1.3 * x for x in xs]  # 无噪声，应精确还原
        alpha, beta, resid_std, r2 = ind.ols(xs, ys)
        self.assertAlmostEqual(beta, 1.3, places=4)
        self.assertAlmostEqual(alpha, 0.0005, places=5)
        self.assertAlmostEqual(r2, 1.0, places=4)

    def test_sharpe_and_vol(self):
        rets = [0.001, -0.002, 0.0015, 0.0005, -0.001, 0.002]
        self.assertIsNotNone(ind.annualized_volatility(rets))
        self.assertIsNotNone(ind.sharpe(rets))


if __name__ == "__main__":
    unittest.main()
