"""AI 分析：调 DeepSeek API，结合行情+新闻+网络搜索，对持仓和组合给判断。

性能：结果缓存 2 小时，请求并发，总超时 30s。
"""
from __future__ import annotations

import concurrent.futures
import os
import re
import time
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from openai import OpenAI


# ---------------------------------------------------------------------------
# 简单缓存
# ---------------------------------------------------------------------------

_cache: dict = {}
_CACHE_TTL = 7200  # 2 小时


def _cached(key: str, factory, ttl: int = _CACHE_TTL):
    now = time.time()
    entry = _cache.get(key)
    if entry and now - entry["ts"] < ttl:
        return entry["val"]
    val = factory()
    _cache[key] = {"ts": now, "val": val}
    return val


# 总超时预算
_SEARCH_TIMEOUT = 5  # 单个搜索超时
_TOTAL_BUDGET = 30   # 总预算秒


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
                      institutional_views: List[str] = None,
                      market_indicators: List[dict] = None) -> str:
    """构建逐只分析 prompt，包含机构观点、宏观事件、市场情绪指标。"""
    news = news or {}
    fund_texts = []
    for fa in funds:
        t = _fund_snapshot(fa)
        code_news = news.get(fa.holding.code, [])
        if code_news:
            t += f"\n相关新闻: {'; '.join(code_news[:5])}"
        fund_texts.append(t)

    # 市场情绪指标摘要
    market_block = ""
    if market_indicators:
        lines = []
        for ind in market_indicators:
            emoji = "🟢" if ind["level"] == "low" else ("🔴" if ind["level"] == "high" else "🟡")
            lines.append(f"{emoji} {ind['label']}: {ind['value']}（{ind['level']}）")
        market_block = "\n## 当前市场情绪指标\n" + "\n".join(lines) + "\n（这些指标反映市场整体风险偏好，请结合判断）"

    # 宏观事件摘要
    macro_block = ""
    if macro_events:
        macro_block = "\n## 近期宏观事件/催化剂\n" + "\n".join(f"- {e}" for e in macro_events[:10])

    # 网络搜索参考（非正式研报）
    inst_block = ""
    if institutional_views:
        inst_block = "\n## 网络搜索参考（非正式研报，仅供参考）\n" + "\n".join(f"- {v}" for v in institutional_views[:6])

    header = f"""你是华尔街顶级基金分析师。今天是{datetime.now().strftime('%Y年%m月%d日')}。

{market_block}

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
                         total_value: float = 0,
                         market_indicators: List[dict] = None) -> AiPortfolioAnalysis:
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
    fund_prompt = build_fund_prompt(funds, news, macro_events, inst_views, market_indicators)
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
# 新闻搜索（缓存 + 并发 + 超时；标注为网络搜索结果，非正式研报）
# ---------------------------------------------------------------------------

def _bing_search(query: str) -> List[str]:
    """Bing News RSS，返回标题列表。5s 超时。"""
    try:
        encoded = urllib.parse.quote(query)
        url = f"https://www.bing.com/news/search?q={encoded}&format=rss"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; FundAnalyzer/1.0)",
        })
        with urllib.request.urlopen(req, timeout=_SEARCH_TIMEOUT) as resp:
            data = resp.read().decode("utf-8", errors="replace")
            titles = re.findall(r'<title>(.+?)</title>', data)
            return [t for t in titles if t and "Bing" not in t and "必应" not in t and "Microsoft" not in t]
    except Exception:
        return []


def search_news_for_fund(name: str, keywords: List[str] = None) -> List[str]:
    """搜索基金相关网络新闻。"""
    query = name
    if keywords:
        query += " " + " ".join(keywords[:3])
    key = f"fund_news:{query}"
    return _cached(key, lambda: _bing_search(query)[:5], 1800)


def search_institutional_views(funds: List) -> List[str]:
    """搜索机构相关网络新闻（标注来源，非正式研报）。"""
    def _fetch():
        topics = _extract_topics(funds)
        queries = []
        for topic in topics[:2]:
            for src in ["摩根大通", "高盛", "花旗", "贝莱德"]:
                queries.append(f"{src} {topic}")
        views = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            futures = {ex.submit(_bing_search, q): q for q in queries[:8]}
            for fut in concurrent.futures.as_completed(futures, timeout=min(15, _TOTAL_BUDGET)):
                try:
                    for t in fut.result() or []:
                        if len(t) > 10:
                            views.append(f"[网络搜索] {t}")
                except Exception:
                    continue
        return views[:6]
    return _cached("inst_views", _fetch, 3600)


def search_macro_events() -> List[str]:
    """搜索近期宏观事件（动态日期）。"""
    def _fetch():
        now = datetime.now()
        m = now.strftime("%Y年%-m月")
        queries = [f"美联储 利率 {m}", f"美股 经济数据 CPI {m}"]
        events = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            futures = [ex.submit(_bing_search, q) for q in queries]
            for fut in concurrent.futures.as_completed(futures, timeout=min(10, _TOTAL_BUDGET)):
                try:
                    for t in fut.result() or []:
                        if len(t) > 15:
                            events.append(f"📅 {t}")
                except Exception:
                    continue
        return events[:6]
    return _cached("macro_events", _fetch, 3600)


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
    return list(dict.fromkeys(topics))


def build_news_feed(news: Dict[str, List[str]], macro_events: List[str],
                    inst_views: List[str]) -> List[dict]:
    """构建前端新闻 feed。"""
    feed = []
    for e in macro_events[:3]:
        feed.append({"type": "macro", "text": e})
    for v in inst_views[:3]:
        feed.append({"type": "institution", "text": v})
    for code, items in (news or {}).items():
        for item in items[:2]:
            feed.append({"type": "fund", "code": code, "text": item})
    return feed[:12]
