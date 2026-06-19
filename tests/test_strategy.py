import unittest

from fund_analyzer.config import StrategySettings
from fund_analyzer.models import Action, FundAnalysis, Holding, Metrics
from fund_analyzer.strategy import evaluate


def _fa(metrics, navs, is_dca=True, shares=1000.0, cost=1.0):
    h = Holding(code="000001", name="t", shares=shares, cost_nav=cost, is_dca=is_dca)
    fa = FundAnalysis(holding=h, metrics=metrics)
    evaluate(fa, navs, StrategySettings())
    return fa


class TestStrategy(unittest.TestCase):
    def test_target_take_profit_is_hard(self):
        m = Metrics(last_nav=1.5, holding_return=0.40, price_percentile=0.85,
                    ma20=1.4, ma60=1.3, rsi14=72)
        fa = _fa(m, [1.0, 1.2, 1.5])
        self.assertIn(fa.action, (Action.TRIM, Action.SELL))
        self.assertTrue(any(s.hard for s in fa.signals))

    def test_low_valuation_oversold_buys(self):
        m = Metrics(last_nav=0.8, holding_return=-0.15, price_percentile=0.05,
                    ma20=0.85, ma60=0.9, rsi14=25)
        fa = _fa(m, [1.2, 1.0, 0.8])
        self.assertEqual(fa.action, Action.BUY_MORE)

    def test_high_valuation_pressures_down(self):
        m = Metrics(last_nav=2.0, holding_return=0.10, price_percentile=0.95,
                    ma20=1.9, ma60=1.7, rsi14=80)
        fa = _fa(m, [1.0, 1.5, 2.0])
        self.assertLess(fa.score, 0)

    def test_trailing_drawdown_take_profit(self):
        # 盈利后从高点(2.0)回撤到1.7 → -15% > 10% 阈值，触发回撤止盈
        m = Metrics(last_nav=1.7, holding_return=0.20, price_percentile=0.6,
                    ma20=1.8, ma60=1.6, rsi14=50)
        fa = _fa(m, [1.0, 1.5, 2.0, 1.85, 1.7])
        self.assertTrue(any("回撤止盈" in s.name for s in fa.signals))
        self.assertIn(fa.action, (Action.TRIM, Action.SELL))

    def test_neutral_holds(self):
        m = Metrics(last_nav=1.0, holding_return=0.02, price_percentile=0.5,
                    ma20=1.0, ma60=1.0, rsi14=50)
        fa = _fa(m, [0.98, 1.0, 1.0])
        self.assertEqual(fa.action, Action.HOLD)


if __name__ == "__main__":
    unittest.main()
