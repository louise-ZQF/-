import os
import tempfile
import unittest

from webapp import serialize, service


class TestWebappService(unittest.TestCase):
    def test_demo_json_structure(self):
        d = service.build_demo_json()
        self.assertEqual(d["mode"], "demo")
        self.assertTrue(d["overview"]["has_value"])
        self.assertTrue(d["funds"])
        # 资产分布占比之和≈1
        self.assertAlmostEqual(sum(a["pct"] for a in d["allocation"]), 1.0, places=3)
        # QDII 基金应带时差估算
        qdii = [f for f in d["funds"] if f["tracking"]["index"]]
        self.assertTrue(qdii and all(f["estimate"] for f in qdii))
        # 每只基金有历史点用于画图
        self.assertTrue(all(f["history"] for f in d["funds"]))

    def test_fund_dict_fields(self):
        d = service.build_demo_json()
        f = d["funds"][0]
        for key in ("code", "name", "action", "action_kind", "score", "metrics", "signals"):
            self.assertIn(key, f)
        self.assertIn(f["action_kind"], {"buy", "hold_pos", "hold", "caution", "trim", "sell"})

    def test_holdings_save_read_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "holdings.yaml")
            n = service.save_holdings([
                {"code": "270042", "name": "纳指", "asset_class": "us_equity",
                 "shares": "1000", "cost_nav": "1.5", "is_dca": True,
                 "tracking": {"index": "^NDX", "lag_days": "2", "currency_hedged": False}},
                {"code": "", "name": "应被过滤"},  # 无代码 → 丢弃
            ], path=path)
            self.assertEqual(n, 1)
            rows = service.read_holdings_raw(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["code"], "270042")
            self.assertEqual(rows[0]["tracking"]["index"], "^NDX")
            self.assertEqual(rows[0]["shares"], 1000.0)

    def test_empty_live_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = service.build_live_json(holdings_path=os.path.join(tmp, "none.yaml"))
            self.assertTrue(d.get("empty"))
            self.assertIn("持仓", d["message"])


if __name__ == "__main__":
    unittest.main()
