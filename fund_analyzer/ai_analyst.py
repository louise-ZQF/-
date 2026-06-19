"""AI 分析：调 DeepSeek API，结合行情+新闻+机构研报，对持仓和组合给判断。"""
from __future__ import annotations

import os
import re
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from openai import OpenAI


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class AiSentiment:
    code: str
    sentiment: str           # "强烈看好" | "看好" | "中性偏多" | "中性" | "谨慎" | "规避"
    reason: str              # 一句话理由
    suggestion: str          # "加大定投" | "继续定投" | "维持" | "减少定投" | "暂停观望" | "减仓"


@dataclass
class AiPortfolioAnalysis:
    funds: Dict[str, AiSentiment] = field(default_factory=dict)
    portfolio_analysis: str = ""
    sector_bias: str = ""
    macro_note: str = ""
    dca_adjustments: Dict[str, str] = field(default_factory=dict)
    news_feed: List[dict] = field(default_factory=list)  # 影响持仓的重要新闻


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

ASSET_CN = {
    "us_equity": "美股", "cn_equity": "A股", "hk_equity": "港股",
    "global_equity": "全球股", "commodity": "商品", "bond": "债券",
    "cash": "现金", "other": "其他",
}


def _fund_snapshot(fa) -> str:
    m = fa.metrics
    h = fa.holding
    lines = [
        f"代码: {h.code}, 名称: {h.name or '未知'}, 类别: {ASSET_CN.get(h.asset_class.value, h.asset_class.value)}",
    ]
    if h.current_value > 0:
        lines.append(f"当前仓位: ¥{h.current_value:,.0f}")
    dp_str = "否"
    if h.is_dca:
        dp_str = "是"
        if h.dca_plan:
            freq_cn = {"daily": "每天", "weekly": "每周", "monthly": "每月"}
            dp_str += f"（{freq_cn.get(h.dca_plan.frequency, h.dca_plan.frequency)} ¥{h.dca_plan.amount:.0f}）"
    lines.append(f"定投: {dp_str}")

    if m.last_nav is not None:
        lines.append(f"最新净值: {m.last_nav}")
    if m.holding_return is not None:
        lines.append(f"持仓收益: {m.holding_return*100:+.1f}%")
    if m.rsi14 is not None:
        lines.append(f"RSI(14): {m.rsi14:.0f}")
    if m.price_percentile is not None:
        lines.append(f"估值分位: {m.price_percentile*100:.0f}%")
    if m.ret_1w is not None:
        lines.append(f"近1周: {m.ret_1w*100:+.1f}%")
    if m.ret_1m is not None:
        lines.append(f"近1月: {m.ret_1m*100:+.1f}%")
    if m.ret_3m is not None:
        lines.append(f"近3月: {m.ret_3m*100:+.1f}%")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Prompt 构建（增强版：机构研报 + 宏观事件 + 新闻）
# ---------------------------------------------------------------------------

def build_fund_prompt(funds: List, news: Dict[str, List[str]] = None,
                      macro_events: List[str] = None,
                      institutional_views: List[str] = None) -> str:
    """构建逐只分析 prompt，包含机构观点和宏观事件。"""
    news = news or {}
    fund_texts = []
    for fa in funds:
        t = _fund_snapshot(fa)
        code_news = news.get(fa.holding.code, [])
        if code_news:
            t += f"\n相关新闻: {'; '.join(code_news[:5])}"
        fund_texts.append(t)

    # 宏观事件摘要
    macro_block = ""
    if macro_events:
        macro_block = "\n## 近期宏观事件/催化剂\n" + "\n".join(f"- {e}" for e in macro_events[:10])

    # 机构观点
    inst_block = ""
    if institutional_views:
        inst_block = "\n## 主要机构观点\n" + "\n".join(f"- {v}" for v in institutional_views[:8])

    header = f"""你是华尔街顶级基金分析师。今天是{datetime.now().strftime('%Y年%m月%d日')}。

{macro_block}
{inst_block}

## 你的持仓基金技术面快照

对每只基金输出一行判断。不要保守——如果你看到强烈的信号，就给出强烈判断。

格式：
<代码>: <判断> | <理由> | <操作建议>

判断选项：强烈看好 / 看好 / 中性偏多 / 中性 / 谨慎 / 规避
操作建议：加大定投 / 继续定投 / 维持 / 减少定投 / 暂停观望 / 减仓

核心原则：
1. 趋势 > 估值 —— 牛市中高估值可以继续涨，不要因为估值高就轻易看空
2. 动量很重要 —— RSI高不一定超买，强势行情中RSI可以持续高位
3. 机构观点权重大 —— 大行研报比技术指标更有前瞻性
4. 宏观事件优先 —— Fed决议、CPI、财报季比日常波动重要100倍
5. 不要模棱两可 —— 有判断就给明确方向，不要老说"中性"
6. 只输出结果行，不要任何额外解释
"""
    return header + "\n\n" + "\n\n---\n\n".join(fund_texts)


def build_portfolio_prompt(funds: List, total_value: float,
                           macro_events: List[str] = None) -> str:
    """构建组合层分析 prompt。"""
    by_class: Dict[str, float] = {}
    for fa in funds:
        ac = fa.holding.asset_class.value
        v = fa.holding.current_value or 0
        by_class[ac] = by_class.get(ac, 0) + v

    class_info = []
    for k, v in sorted(by_class.items(), key=lambda x: -x[1]):
        cn = ASSET_CN.get(k, k)
        pct = f"{v/total_value*100:.0f}%" if total_value > 0 else "?"
        class_info.append(f"  - {cn}: {pct}")

    dca_info = []
    for fa in funds:
        if fa.holding.dca_plan:
            dp = fa.holding.dca_plan
            freq_cn = {"daily": "每天", "weekly": "每周", "monthly": "每月"}
            dca_info.append(
                f"  - {fa.holding.name or fa.holding.code}: "
                f"{freq_cn.get(dp.frequency, dp.frequency)} ¥{dp.amount:.0f}"
            )

    macro_block = ""
    if macro_events:
        macro_block = "## 近期关键事件\n" + "\n".join(f"- {e}" for e in macro_events[:8])

    prompt = f"""你是华尔街顶级资产管理顾问。今天是{datetime.now().strftime('%Y年%m月%d日')}。

{macro_block}

## 客户组合概况
总市值: ¥{total_value:,.0f}
资产分布:
{chr(10).join(class_info) if class_info else '  无数据'}
定投计划:
{chr(10).join(dca_info) if dca_info else '  无'}

## 请分析

### 组合诊断（150字以内，一针见血）
- 最大的风险敞口是什么？最大的机会在哪里？
- 集中度是否合理？如果不合理，应该怎么调？
- 给出明确的组合层操作建议

### 定投调整
对每只定投中的基金：维持 / 增加xx% / 减少xx%（必须给具体数字和理由）

格式：
```
### 组合诊断
（分析文字）

### 定投调整
代码: 维持/增加xx%/减少xx% | 理由
```
"""
    return prompt


# ---------------------------------------------------------------------------
# DeepSeek 调用
# ---------------------------------------------------------------------------

def _get_client() -> Optional[OpenAI]:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        return None
    return OpenAI(api_key=api_key, base_url="https://api.deepseek.com")


def call_deepseek(prompt: str, system: str = None) -> Optional[str]:
    """调用 DeepSeek API。"""
    if system is None:
        system = ("你是华尔街顶级基金分析师。你的判断基于数据、机构研报和宏观分析。"
                  "你敢于给出明确判断，不模棱两可。你的建议具体可执行。")
    client = _get_client()
    if not client:
        return None
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            max_tokens=2500,
        )
        return resp.choices[0].message.content
    except Exception as e:
        print(f"[ai_analyst] DeepSeek API 调用失败: {e}")
        return None


# ---------------------------------------------------------------------------
# 响应解析
# ---------------------------------------------------------------------------

def parse_ai_response(text: str) -> dict:
    """解析 AI 回复，提取结构化数据。"""
    result = {
        "funds": {},
        "portfolio_analysis": "",
        "dca_adjustments": {},
    }

    # 匹配所有可能的判断标签
    sentiments = r'(强烈看好|看好|中性偏多|中性|谨慎|规避)'
    fund_pattern = re.compile(
        rf'^(\d{{6}})\s*[:：]\s*{sentiments}\s*[|｜]\s*(.+?)\s*[|｜]\s*(.+)$',
        re.MULTILINE,
    )
    for m in fund_pattern.finditer(text):
        result["funds"][m.group(1)] = {
            "sentiment": m.group(2).strip(),
            "reason": m.group(3).strip(),
            "suggestion": m.group(4).strip(),
        }

    sections = re.split(r'###\s+', text)
    for sec in sections:
        sec = sec.strip()
        if sec.startswith("组合诊断") or sec.startswith("组合分析"):
            result["portfolio_analysis"] = sec.split("\n", 1)[-1].strip()
        elif sec.startswith("定投调整"):
            for line in sec.splitlines()[1:]:
                dm = re.match(r'(\d{6})\s*[:：]\s*(.+)', line)
                if dm:
                    result["dca_adjustments"][dm.group(1)] = dm.group(2).strip()

    return result


# ---------------------------------------------------------------------------
# 高层编排
# ---------------------------------------------------------------------------

def ai_analyze_portfolio(funds: List, news: Dict[str, List[str]] = None,
                         total_value: float = 0) -> AiPortfolioAnalysis:
    """一站式 AI 分析。"""
    result = AiPortfolioAnalysis()

    client = _get_client()
    if not client:
        result.portfolio_analysis = "未配置 DEEPSEEK_API_KEY 环境变量，跳过 AI 分析。"
        return result

    # 获取宏观事件和机构观点
    macro_events = search_macro_events()
    inst_views = search_institutional_views(funds)

    # 1. 逐只分析
    fund_prompt = build_fund_prompt(funds, news, macro_events, inst_views)
    fund_resp = call_deepseek(fund_prompt)
    if fund_resp:
        parsed = parse_ai_response(fund_resp)
        for code, info in parsed["funds"].items():
            result.funds[code] = AiSentiment(
                code=code,
                sentiment=info.get("sentiment", "中性"),
                reason=info.get("reason", ""),
                suggestion=info.get("suggestion", "维持"),
            )

    # 2. 组合分析
    pf_prompt = build_portfolio_prompt(funds, total_value, macro_events)
    pf_resp = call_deepseek(pf_prompt)
    if pf_resp:
        parsed = parse_ai_response(pf_resp)
        result.portfolio_analysis = parsed.get("portfolio_analysis", "")
        result.dca_adjustments = parsed.get("dca_adjustments", {})

    # 3. 汇总新闻 feed
    result.news_feed = build_news_feed(news or {}, macro_events, inst_views)

    return result


# ---------------------------------------------------------------------------
# 新闻搜索（增强版：机构研报 + 宏观事件）
# ---------------------------------------------------------------------------

def search_news_for_fund(name: str, keywords: List[str] = None) -> List[str]:
    """搜索基金相关新闻。"""
    try:
        query = name
        if keywords:
            query += " " + " ".join(keywords[:3])
        encoded = urllib.parse.quote(query)
        url = f"https://www.bing.com/news/search?q={encoded}&format=rss"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; FundAnalyzer/1.0)",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read().decode("utf-8", errors="replace")
            titles = re.findall(r'<title>(.+?)</title>', data)
            return [t for t in titles if t and "Bing" not in t and "必应" not in t and "Microsoft" not in t][:5]
    except Exception as e:
        print(f"[news] 搜索 {name} 新闻失败: {e}")
        return []


def search_institutional_views(funds: List) -> List[str]:
    """搜索摩根大通、花旗、高盛、摩根士丹利等机构最新观点。"""
    sources = ["摩根大通", "花旗", "高盛", "摩根士丹利", "贝莱德", "中金"]
    topics = _extract_topics(funds)

    views = []
    for topic in topics[:3]:
        for source in sources[:3]:
            try:
                query = f"{source} {topic} 最新观点 2026"
                encoded = urllib.parse.quote(query)
                url = f"https://www.bing.com/news/search?q={encoded}&format=rss"
                req = urllib.request.Request(url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; FundAnalyzer/1.0)",
                })
                with urllib.request.urlopen(req, timeout=8) as resp:
                    data = resp.read().decode("utf-8", errors="replace")
                    titles = re.findall(r'<title>(.+?)</title>', data)
                    for t in titles:
                        if t and "Bing" not in t and "必应" not in t and "Microsoft" not in t and len(t) > 10:
                            views.append(f"[{source}] {t}")
            except Exception:
                continue

    return views[:10]


def search_macro_events() -> List[str]:
    """搜索未来1-2周的宏观事件（美联储、CPI、财报等）。"""
    today = datetime.now()
    events = []

    # 搜索宏观事件
    queries = [
        "美联储 利率决议 2026年6月",
        "美股 CPI 非农 经济数据 2026年6月",
        "美股 财报季 科技股 2026",
        "纳斯达克 标普500 市场展望 2026年6月",
    ]
    for q in queries[:2]:
        try:
            encoded = urllib.parse.quote(q)
            url = f"https://www.bing.com/news/search?q={encoded}&format=rss"
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; FundAnalyzer/1.0)",
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = resp.read().decode("utf-8", errors="replace")
                titles = re.findall(r'<title>(.+?)</title>', data)
                for t in titles:
                    if t and "Bing" not in t and "必应" not in t and "Microsoft" not in t and len(t) > 15:
                        events.append(f"📅 {t}")
        except Exception:
            continue

    return events[:8]


def _extract_topics(funds: List) -> List[str]:
    """从持仓中提取关键主题。"""
    topics = []
    for fa in funds:
        name = fa.holding.name.lower()
        ac = fa.holding.asset_class.value
        if ac == "us_equity":
            if "纳斯达克" in name or "纳指" in name:
                topics.append("纳斯达克 科技股")
            elif "标普" in name or "sp500" in name or "s&p" in name:
                topics.append("标普500 美股")
        if "科技" in name:
            topics.append("全球科技股")
        if "互联" in name or "新兴" in name:
            topics.append("新兴市场")
    if not topics:
        topics = ["美股 纳斯达克", "全球科技", "QDII基金"]
    return list(dict.fromkeys(topics))  # 去重保序


def build_news_feed(news: Dict[str, List[str]], macro_events: List[str],
                    inst_views: List[str]) -> List[dict]:
    """构建前端新闻 feed。"""
    feed = []

    # 宏观事件
    for e in macro_events[:4]:
        feed.append({"type": "macro", "text": e})

    # 机构观点
    for v in inst_views[:4]:
        feed.append({"type": "institution", "text": v})

    # 基金相关新闻
    for code, items in (news or {}).items():
        for item in items[:2]:
            feed.append({"type": "fund", "code": code, "text": item})

    return feed[:15]
