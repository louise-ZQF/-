import unittest
from datetime import datetime

from fund_analyzer.config import load_settings
from fund_analyzer.demo import build_demo
from fund_analyzer.portfolio import analyze_fund, build_report
from fund_analyzer.report import render_html, render_markdown, subject_line


class TestReportPipeline(unittest.TestCase):
    def setUp(self):
        self.settings = load_settings("___nonexistent___.yaml")  # 用默认配置
        holdings, nav_map, quote_map, index_map, fx, brief = build_demo()
        funds = []
        for h in holdings:
            idx = index_map.get(h.tracking.index, [])
            fxr = fx if (h.tracking.index and not h.tracking.currency_hedged) else []
            funds.append(analyze_fund(h, nav_map[h.code], quote_map.get(h.code), idx, fxr, self.settings))
        self.rep = build_report(funds, self.settings, market_brief=brief,
                                as_of=datetime(2026, 6, 19, 9, 0))

    def test_totals(self):
        self.assertIsNotNone(self.rep.total_value)
        self.assertIsNotNone(self.rep.est_today_change)

    def test_estimate_present_for_qdii(self):
        qdii = [f for f in self.rep.funds if f.holding.tracking.index]
        self.assertTrue(all(f.estimate and f.estimate.has_estimate for f in qdii))

    def test_markdown_render(self):
        md = render_markdown(self.rep, self.settings.report_title)
        self.assertIn("组合概览", md)
        self.assertIn("时差估算", md)
        self.assertIn("免责声明", md)

    def test_html_render(self):
        html = render_html(self.rep, self.settings.report_title)
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn("时差估算", html)

    def test_subject_line(self):
        s = subject_line(self.rep, "基金分析")
        self.assertIn("基金分析", s)


if __name__ == "__main__":
    unittest.main()
