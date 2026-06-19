import base64
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
        self.assertAlmostEqual(sum(a["pct"] for a in d["allocation"]), 1.0, places=3)
        qdii = [f for f in d["funds"] if f["tracking"]["index"]]
        self.assertTrue(qdii and all(f["estimate"] for f in qdii))
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
                {"code": "", "name": "应被过滤"},
            ], path=path)
            self.assertEqual(n, 1)
            rows = service.read_holdings_raw(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["code"], "270042")
            self.assertEqual(rows[0]["tracking"]["index"], "^NDX")
            self.assertEqual(rows[0]["shares"], 1000.0)

    def test_holdings_yaml_env_materializes(self):
        """部署用：文件不存在但有 HOLDINGS_YAML 环境变量时落地成文件。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "h.yaml")
            os.environ["HOLDINGS_YAML"] = 'holdings:\n  - code: "510300"\n'
            self.addCleanup(lambda: os.environ.pop("HOLDINGS_YAML", None))
            rows = service.read_holdings_raw(path)
            self.assertTrue(os.path.exists(path))
            self.assertEqual(rows[0]["code"], "510300")

    def test_empty_live_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = service.build_live_json(holdings_path_override=os.path.join(tmp, "none.yaml"))
            self.assertTrue(d.get("empty"))
            self.assertIn("持仓", d["message"])


class TestWebappAuth(unittest.TestCase):
    """部署用：设置 APP_PASSWORD 后全站需认证，健康检查除外。"""

    def setUp(self):
        os.environ["APP_PASSWORD"] = "secret"
        self.addCleanup(lambda: os.environ.pop("APP_PASSWORD", None))
        from webapp.app import create_app
        self.client = create_app().test_client()

    def _auth(self, user="", pw="secret"):
        token = base64.b64encode(f"{user}:{pw}".encode()).decode()
        return {"Authorization": "Basic " + token}

    def test_health_open(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)

    def test_root_requires_auth(self):
        self.assertEqual(self.client.get("/").status_code, 401)

    def test_correct_password_ok(self):
        self.assertEqual(self.client.get("/", headers=self._auth()).status_code, 200)

    def test_wrong_password_rejected(self):
        self.assertEqual(self.client.get("/", headers=self._auth(pw="nope")).status_code, 401)


if __name__ == "__main__":
    unittest.main()
