"""报告生成：把 PortfolioReport 渲染成中文 Markdown 与 HTML（邮件用）。"""
from __future__ import annotations

from typing import List, Optional

from jinja2 import Template

from .models import Action, FundAnalysis, PortfolioReport

# 操作建议 → 颜色（HTML 用）
_ACTION_COLOR = {
    Action.BUY_MORE: "#0a7d2c",
    Action.DCA_CONTINUE: "#2e7d32",
    Action.HOLD: "#555555",
    Action.DCA_PAUSE: "#b26a00",
    Action.TRIM: "#c25e00",
    Action.SELL: "#c0392b",
}


def pct(x: Optional[float], digits: int = 2, signed: bool = True) -> str:
    if x is None:
        return "—"
    fmt = f"{{:{'+' if signed else ''}.{digits}f}}%"
    return fmt.format(x * 100)


def num(x: Optional[float], digits: int = 4) -> str:
    return "—" if x is None else f"{x:.{digits}f}"


def money(x: Optional[float]) -> str:
    return "—" if x is None else f"¥{x:,.2f}"


# ----------------------------------------------------------------------------
# Markdown
# ----------------------------------------------------------------------------

def render_markdown(rep: PortfolioReport, title: str = "基金组合每日分析报告") -> str:
    L: List[str] = []
    L.append(f"# {title}")
    L.append(f"_生成时间：{rep.as_of.strftime('%Y-%m-%d %H:%M')}_\n")

    # 概览
    L.append("## 一、组合概览")
    if rep.total_value:
        L.append(f"- 已公布净值市值：**{money(rep.total_value)}**")
        L.append(f"- 时差估算「应有」市值：**{money(rep.total_implied_value)}**"
                 f"（估算当日额外涨跌 **{pct(rep.est_today_change)}**，即美股已发生但基金净值尚未体现的部分）")
        if rep.total_cost:
            tot_ret = (rep.total_value / rep.total_cost - 1.0) if rep.total_cost else None
            L.append(f"- 持仓成本：{money(rep.total_cost)}　累计收益：**{pct(tot_ret)}**")
    else:
        L.append("- （未填写持仓份额/成本，本次仅做信号分析）")
    L.append("")

    # 重点提示
    highlights = [fa for fa in rep.funds
                  if fa.action in (Action.SELL, Action.TRIM, Action.DCA_PAUSE, Action.BUY_MORE)]
    if highlights:
        L.append("## 二、今日重点操作提示")
        for fa in highlights:
            L.append(f"- **{fa.holding.name or fa.holding.code}** → **{fa.action.value}**：{fa.rationale}")
        L.append("")

    # 逐只基金
    L.append("## 三、持仓逐只分析")
    for fa in rep.funds:
        h, m, e = fa.holding, fa.metrics, fa.estimate
        L.append(f"### {h.name or h.code}（{h.code}）— {h.asset_class.value}")
        L.append(f"- 操作建议：**{fa.action.value}**（信号分 {fa.score:+.1f}）")
        if m.last_nav is not None:
            L.append(f"- 最新净值：{num(m.last_nav)}　持仓收益：{pct(m.holding_return)}")
        if e and e.has_estimate:
            L.append(f"- ⏱ 时差估算：未体现的美股涨跌累计 **{pct(e.cum_return)}** "
                     f"（±{pct(e.band, signed=False)}），推算应有净值 ≈ **{num(e.implied_nav)}**"
                     f"［{e.method}，跟踪 {h.tracking.index}，滞后 {h.tracking.lag_days} 个指数交易日］")
            for d in e.detail:
                L.append(f"    - {d}")
        L.append(f"- 区间收益：近1周 {pct(m.ret_1w)}｜近1月 {pct(m.ret_1m)}｜近3月 {pct(m.ret_3m)}｜近1年 {pct(m.ret_1y)}")
        L.append(f"- 指标：RSI {num(m.rsi14,0) if m.rsi14 else '—'}｜最大回撤 {pct(m.max_drawdown)}"
                 f"｜年化波动 {pct(m.vol_annual,1)}｜夏普 {num(m.sharpe,2)}｜净值分位 "
                 f"{pct(m.price_percentile,0) if m.price_percentile is not None else '—'}")
        if fa.signals:
            L.append("- 触发信号：")
            for s in fa.signals:
                tag = "🔴" if s.hard else ("🟢" if s.vote > 0 else ("🟠" if s.vote < 0 else "⚪"))
                L.append(f"    - {tag} {s.text}")
        L.append("")

    # 组合建议
    if rep.portfolio_notes:
        L.append("## 四、组合层建议")
        for n in rep.portfolio_notes:
            L.append(f"- {n}")
        L.append("")

    # 市场情报
    if rep.market_brief:
        L.append("## 五、市场情报")
        for b in rep.market_brief:
            L.append(f"- {b}")
        L.append("")

    L.append("---")
    L.append("> **免责声明**：本报告由量化规则自动生成，所有指标、估算与「操作建议」均为基于公开数据与"
             "通用投资规则的参考信息，**不构成任何投资建议或买卖要约**。时差估算为近似模型，存在误差；"
             "市场有风险，决策请独立判断并自负盈亏。")
    return "\n".join(L)


# ----------------------------------------------------------------------------
# HTML（邮件）
# ----------------------------------------------------------------------------

_HTML_TMPL = Template("""\
<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f4f5f7;font-family:-apple-system,'PingFang SC','Microsoft YaHei',Arial,sans-serif;color:#222;">
<div style="max-width:720px;margin:0 auto;padding:16px;">
  <h1 style="font-size:20px;margin:8px 0;">{{ title }}</h1>
  <div style="color:#888;font-size:12px;margin-bottom:14px;">生成时间：{{ rep.as_of.strftime('%Y-%m-%d %H:%M') }}</div>

  {% if rep.total_value %}
  <div style="background:#fff;border-radius:10px;padding:14px 16px;margin-bottom:14px;box-shadow:0 1px 3px rgba(0,0,0,.06);">
    <div style="font-size:13px;color:#666;">组合概览</div>
    <div style="font-size:15px;margin-top:6px;">已公布市值 <b>{{ money(rep.total_value) }}</b>
      ＝估算「应有」市值 <b>{{ money(rep.total_implied_value) }}</b></div>
    <div style="font-size:14px;margin-top:4px;">时差估算当日额外涨跌：
      <b style="color:{{ '#0a7d2c' if (rep.est_today_change or 0)>=0 else '#c0392b' }};">{{ pct(rep.est_today_change) }}</b>
      <span style="color:#999;font-size:12px;">（美股已发生、基金净值尚未体现的部分）</span></div>
    {% if rep.total_cost %}<div style="font-size:13px;color:#666;margin-top:4px;">
      成本 {{ money(rep.total_cost) }}｜累计收益 <b>{{ pct(rep.total_value/rep.total_cost-1) }}</b></div>{% endif %}
  </div>
  {% endif %}

  {% if highlights %}
  <div style="background:#fff;border-radius:10px;padding:14px 16px;margin-bottom:14px;box-shadow:0 1px 3px rgba(0,0,0,.06);">
    <div style="font-size:14px;font-weight:600;margin-bottom:8px;">📌 今日重点操作提示</div>
    {% for fa in highlights %}
    <div style="font-size:13px;margin:6px 0;padding:8px 10px;background:#fafafa;border-left:3px solid {{ color(fa.action) }};border-radius:4px;">
      <b>{{ fa.holding.name or fa.holding.code }}</b> →
      <b style="color:{{ color(fa.action) }};">{{ fa.action.value }}</b><br>
      <span style="color:#666;">{{ fa.rationale }}</span></div>
    {% endfor %}
  </div>
  {% endif %}

  <div style="background:#fff;border-radius:10px;padding:6px 16px 14px;margin-bottom:14px;box-shadow:0 1px 3px rgba(0,0,0,.06);">
    <div style="font-size:14px;font-weight:600;margin:10px 0;">持仓逐只分析</div>
    {% for fa in rep.funds %}
    <div style="border-top:1px solid #eee;padding:10px 0;">
      <div style="font-size:14px;font-weight:600;">{{ fa.holding.name or fa.holding.code }}
        <span style="color:#999;font-weight:400;font-size:12px;">{{ fa.holding.code }} · {{ fa.holding.asset_class.value }}</span></div>
      <div style="font-size:13px;margin:4px 0;">建议
        <b style="color:{{ color(fa.action) }};">{{ fa.action.value }}</b>
        <span style="color:#aaa;">（{{ '%+.1f'|format(fa.score) }} 分）</span>
        {% if fa.metrics.last_nav %}｜净值 {{ num(fa.metrics.last_nav) }}｜持仓收益 {{ pct(fa.metrics.holding_return) }}{% endif %}</div>
      {% if fa.estimate and fa.estimate.has_estimate %}
      <div style="font-size:12px;background:#f0f7ff;border-radius:6px;padding:6px 8px;margin:4px 0;color:#1a4a7a;">
        ⏱ 时差估算：未体现涨跌累计 <b>{{ pct(fa.estimate.cum_return) }}</b> (±{{ pct(fa.estimate.band, 2, false) }})，
        应有净值 ≈ <b>{{ num(fa.estimate.implied_nav) }}</b>
        <span style="color:#789;">[{{ fa.estimate.method }}·{{ fa.holding.tracking.index }}·滞后{{ fa.holding.tracking.lag_days }}日]</span></div>
      {% endif %}
      <div style="font-size:12px;color:#666;">近1周 {{ pct(fa.metrics.ret_1w) }}｜近1月 {{ pct(fa.metrics.ret_1m) }}｜近3月 {{ pct(fa.metrics.ret_3m) }}｜近1年 {{ pct(fa.metrics.ret_1y) }}</div>
      <div style="font-size:12px;color:#666;">RSI {{ num(fa.metrics.rsi14,0) if fa.metrics.rsi14 else '—' }}｜最大回撤 {{ pct(fa.metrics.max_drawdown) }}｜年化波动 {{ pct(fa.metrics.vol_annual,1) }}｜夏普 {{ num(fa.metrics.sharpe,2) }}｜分位 {{ pct(fa.metrics.price_percentile,0) if fa.metrics.price_percentile is not none else '—' }}</div>
      {% for s in fa.signals %}
      <div style="font-size:12px;margin-top:3px;color:#555;">{{ '🔴' if s.hard else ('🟢' if s.vote>0 else ('🟠' if s.vote<0 else '⚪')) }} {{ s.text }}</div>
      {% endfor %}
    </div>
    {% endfor %}
  </div>

  {% if rep.portfolio_notes %}
  <div style="background:#fff;border-radius:10px;padding:14px 16px;margin-bottom:14px;box-shadow:0 1px 3px rgba(0,0,0,.06);">
    <div style="font-size:14px;font-weight:600;margin-bottom:6px;">组合层建议</div>
    {% for n in rep.portfolio_notes %}<div style="font-size:13px;color:#555;margin:4px 0;">• {{ n }}</div>{% endfor %}
  </div>
  {% endif %}

  {% if rep.market_brief %}
  <div style="background:#fff;border-radius:10px;padding:14px 16px;margin-bottom:14px;box-shadow:0 1px 3px rgba(0,0,0,.06);">
    <div style="font-size:14px;font-weight:600;margin-bottom:6px;">市场情报</div>
    {% for b in rep.market_brief %}<span style="display:inline-block;font-size:12px;background:#f2f4f7;border-radius:12px;padding:3px 10px;margin:3px 4px 0 0;color:#444;">{{ b }}</span>{% endfor %}
  </div>
  {% endif %}

  <div style="font-size:11px;color:#999;line-height:1.6;padding:6px 4px 20px;">
    <b>免责声明：</b>本报告由量化规则自动生成，所有指标、估算与「操作建议」均为基于公开数据与通用投资规则的参考信息，
    <b>不构成任何投资建议或买卖要约</b>。时差估算为近似模型，存在误差；市场有风险，决策请独立判断、自负盈亏。
  </div>
</div></body></html>
""")


def render_html(rep: PortfolioReport, title: str = "基金组合每日分析报告") -> str:
    highlights = [fa for fa in rep.funds
                  if fa.action in (Action.SELL, Action.TRIM, Action.DCA_PAUSE, Action.BUY_MORE)]
    return _HTML_TMPL.render(
        rep=rep, title=title, highlights=highlights,
        pct=pct, num=num, money=money,
        color=lambda a: _ACTION_COLOR.get(a, "#555"),
    )


def subject_line(rep: PortfolioReport, title: str = "基金组合每日分析") -> str:
    parts = [title, rep.as_of.strftime("%m-%d")]
    if rep.est_today_change is not None:
        parts.append(f"时差估算{pct(rep.est_today_change)}")
    n_act = sum(1 for fa in rep.funds
                if fa.action in (Action.SELL, Action.TRIM, Action.DCA_PAUSE, Action.BUY_MORE))
    if n_act:
        parts.append(f"{n_act}条操作提示")
    return " ｜ ".join(parts)
