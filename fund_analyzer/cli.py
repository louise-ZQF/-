"""命令行入口。

用法示例：
    python -m fund_analyzer demo                 # 离线演示，生成报告到 output/
    python -m fund_analyzer report               # 联网分析真实持仓（读 config/）
    python -m fund_analyzer report --email        # 分析并发邮件
    python -m fund_analyzer estimate 270042 --index ^NDX --lag 2   # 单只时差估算
    python -m fund_analyzer email-test            # 测试 SMTP 配置
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

from .config import load_email_config, load_holdings, load_settings
from .emailer import send_email
from .models import Tracking
from .portfolio import Analyzer, analyze_fund, build_report
from .report import render_html, render_markdown, subject_line


def _write_outputs(rep, settings, out_dir="output"):
    os.makedirs(out_dir, exist_ok=True)
    stamp = rep.as_of.strftime("%Y%m%d")
    md = render_markdown(rep, settings.report_title)
    html = render_html(rep, settings.report_title)
    md_path = os.path.join(out_dir, f"report-{stamp}.md")
    html_path = os.path.join(out_dir, f"report-{stamp}.html")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    return md, html, md_path, html_path


def _maybe_email(rep, settings, html):
    cfg = load_email_config()
    subj = subject_line(rep, settings.report_title)
    ok = send_email(cfg, subj, html, text_body=render_markdown(rep, settings.report_title))
    return ok


def cmd_demo(args):
    from .demo import build_demo
    settings = load_settings(args.settings)
    holdings, nav_map, quote_map, index_map, fx_returns, brief = build_demo()
    funds = []
    for h in holdings:
        idx = index_map.get(h.tracking.index, [])
        fx = fx_returns if (h.tracking.index and not h.tracking.currency_hedged) else []
        funds.append(analyze_fund(h, nav_map[h.code], quote_map.get(h.code), idx, fx, settings))
    rep = build_report(funds, settings, market_brief=brief, as_of=datetime(2026, 6, 19, 9, 0))
    md, html, md_path, html_path = _write_outputs(rep, settings)
    print(md)
    print(f"\n[已写出] {md_path}\n[已写出] {html_path}")
    if args.email:
        _maybe_email(rep, settings, html)
    return 0


def cmd_report(args):
    settings = load_settings(args.settings)
    holdings = load_holdings(args.holdings)
    if not holdings:
        print(f"未找到持仓配置：{args.holdings}\n请复制 config/holdings.example.yaml 为 config/holdings.yaml 并填写。")
        return 1
    rep = Analyzer(settings).run(holdings)
    md, html, md_path, html_path = _write_outputs(rep, settings)
    print(md)
    print(f"\n[已写出] {md_path}\n[已写出] {html_path}")
    if args.email or os.getenv("SEND_EMAIL", "").lower() == "true":
        _maybe_email(rep, settings, html)
    return 0


def cmd_estimate(args):
    settings = load_settings(args.settings)
    az = Analyzer(settings)
    navpoints = az.em.history(args.code, size=300)
    quote = az.em.realtime(args.code)
    if not navpoints and not quote:
        print(f"取不到 {args.code} 的数据（可能是网络受限或代码有误）。")
        return 1
    tracking = Tracking(index=args.index, beta=args.beta, lag_days=args.lag,
                        currency_hedged=args.hedged)
    idx = az._index_returns(args.index)
    fx = az._index_returns("USDCNY") if (args.index and not args.hedged) else []
    from .models import Holding
    h = Holding(code=args.code, name=(quote.name if quote else ""), tracking=tracking,
                annual_fee=args.fee)
    fa = analyze_fund(h, navpoints, quote, idx, fx, settings)
    e = fa.estimate
    print(f"基金 {args.code} {h.name}")
    if e and e.has_estimate:
        for d in e.detail:
            print("  ", d)
        print(f"  累计待体现：{e.cum_return*100:+.2f}% (±{e.band*100:.2f}%)  "
              f"应有净值≈{e.implied_nav:.4f}  [{e.method}]")
    else:
        print("  无法估算（缺少指数行情或未指定 --index）。")
    return 0


def cmd_email_test(args):
    cfg = load_email_config()
    html = ("<h2>基金分析助手 · 邮件配置测试</h2>"
            "<p>如果你收到这封邮件，说明 SMTP 配置正确，每日报告可以正常发送。✅</p>")
    ok = send_email(cfg, "【测试】基金分析助手邮件配置成功", html, "邮件配置测试成功")
    return 0 if ok else 1


def build_parser():
    p = argparse.ArgumentParser(prog="fund_analyzer", description="基金组合智能分析与每日建议")
    p.add_argument("--settings", default="config/settings.yaml")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("demo", help="离线演示（无需网络）")
    d.add_argument("--email", action="store_true", help="顺便测试发邮件")
    d.set_defaults(func=cmd_demo)

    r = sub.add_parser("report", help="分析真实持仓（联网）")
    r.add_argument("--holdings", default="config/holdings.yaml")
    r.add_argument("--email", action="store_true", help="发邮件")
    r.set_defaults(func=cmd_report)

    e = sub.add_parser("estimate", help="单只基金时差估算（联网）")
    e.add_argument("code")
    e.add_argument("--index", default=None, help="跟踪指数，如 ^NDX / ^GSPC")
    e.add_argument("--beta", default="auto")
    e.add_argument("--lag", type=int, default=2)
    e.add_argument("--fee", type=float, default=0.0)
    e.add_argument("--hedged", action="store_true")
    e.set_defaults(func=cmd_estimate)

    t = sub.add_parser("email-test", help="测试 SMTP 邮件配置")
    t.set_defaults(func=cmd_email_test)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
