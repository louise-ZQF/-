"""AI 分析：调 DeepSeek API，结合行情+新闻，对每只持仓和整体组合给判断。"""
from __future__ import annotations

import os
import re
import urllib.request
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from openai import OpenAI


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class AiSentiment:
    code: str
    sentiment: str           # "看好" | "中性" | "谨慎"
    reason: str = ""         # 一句话理由
    suggestion: str = "维持" # "加仓" | "继续定投" | "维持" | "减少定投" | "暂停定投" | "减仓"


@dataclass
class AiPortfolioAnalysis:
    funds: Dict[str, AiSentiment] = field(default_factory=dict)
    portfolio_analysis: str = ""       # 组合层分析文字
    sector_bias: str = ""              # 行业集中度
    macro_note: str = ""               # 宏观/市场环境提示
    dca_adjustments: Dict[str, str] = field(default_factory=dict)  # 定投调整建议


# ---------------------------------------------------------------------------
# 工具：构建 Prompt
# ---------------------------------------------------------------------------

ASSET_CN = {
    "us_equity": "美股", "cn_equity": "A股", "hk_equity": "港股",
    "global_equity": "全球股", "commodity": "商品", "bond": "债券",
    "cash": "现金", "other": "其他",
}


def _fund_snapshot(fa) -> str:
    """单只基金的文本快照。"""
    m = fa.metrics
    h = fa.holding
    lines = [
        f"代码: {h.code}, 名称: {h.name or '未知'}, 类别: {ASSET_CN.get(h.asset_class.value, h.asset_class.value)}",
    ]
    if h.current_value > 0:
        lines.append(f"当前仓位: ¥{h.current_value:,.0f}")
    lines.append(f"定投: {'是' if h.is_dca else '否'}")
    if h.dca_plan:
        freq_cn = {"daily": "每天", "weekly": "每周", "monthly": "每月"}
        lines[-1] += f"（{freq_cn.get(h.dca_plan.frequency, h.dca_plan.frequency)} ¥{h.dca_plan.amount:.0f}）"

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


def build_fund_prompt(funds: List, news: Dict[str, List[str]] = None) -> str:
    """构建逐只分析 prompt。"""
    news = news or {}
    fund_texts = []
    for fa in funds:
        t = _fund_snapshot(fa)
        code_news = news.get(fa.holding.code, [])
        if code_news:
            t += f"\n相关新闻: {'; '.join(code_news[:5])}"
        fund_texts.append(t)

    header = f"""你是专业基金分析助手。今天是{datetime.now().strftime('%Y年%m月%d日')}。根据以下持仓基金的技术指标和近期新闻，逐只给出你的看法。

对每只基金严格按此格式输出一行：
<代码>: <看好/中性/谨慎> | <一句话理由，结合技术面和消息面> | <操作建议: 加仓/继续定投/维持/减少定投/暂停定投/减仓>

重要规则：
1. 结合技术指标（RSI、估值分位、趋势）和消息面做综合判断
2. "看好"=近期大概率上涨，"谨慎"=近期风险大于机会，"中性"=维持现状
3. 操作建议必须 actionable，给具体方向
4. 如果某基金缺少新闻，仅基于技术面判断
5. 只输出结果，不要额外解释
"""
    return header + "\n\n" + "\n\n---\n\n".join(fund_texts)


def build_portfolio_prompt(funds: List, total_value: float) -> str:
    """构建组合层分析 prompt。"""
    # 汇总行业分布
    by_class: Dict[str, float] = {}
    for fa in funds:
        ac = fa.holding.asset_class.value
        v = fa.holding.current_value or 0
        by_class[ac] = by_class.get(ac, 0) + v

    class_info = []
    for k, v in sorted(by_class.items(), key=lambda x: -x[1]):
        cn = ASSET_CN.get(k, k)
        if total_value > 0:
            class_info.append(f"  - {cn}: {v/total_value*100:.0f}%")
        else:
            class_info.append(f"  - {cn}")

    dca_info = []
    for fa in funds:
        if fa.holding.dca_plan:
            dp = fa.holding.dca_plan
            freq_cn = {"daily": "每天", "weekly": "每周", "monthly": "每月"}
            dca_info.append(
                f"  - {fa.holding.name or fa.holding.code}: "
                f"{freq_cn.get(dp.frequency, dp.frequency)} ¥{dp.amount:.0f}"
            )

    prompt = f"""你正在分析一个基金投资组合的整体状况。今天是{datetime.now().strftime('%Y年%m月%d日')}。

## 组合概况
总市值: ¥{total_value:,.0f}

### 资产分布
{chr(10).join(class_info) if class_info else '  无数据'}

### 当前定投计划
{chr(10).join(dca_info) if dca_info else '  无定投计划'}

## 分析要求

### 合并输出以下内容（一份连贯分析，150-250字）：
1. 当前配置是否合理？集中度如何？有什么风险？
2. 持仓主要暴露在哪些行业/主题（科技、消费、金融…）？
3. 结合当前宏观环境，给一句判断

### 定投调整建议
对每只定投中的基金给出：维持 / 增加xx% / 减少xx%（说明理由）

请严格按此格式回复：
```
### 组合分析
（连贯分析文字）

### 定投调整建议
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


def call_deepseek(prompt: str, system: str = "你是专业的基金投资分析师，回答简洁、具体、可执行。") -> Optional[str]:
    """调用 DeepSeek API，返回响应文本。失败返回 None。"""
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
            temperature=0.3,
            max_tokens=2000,
        )
        return resp.choices[0].message.content
    except Exception as e:
        print(f"[ai_analyst] DeepSeek API 调用失败: {e}")
        return None


# ---------------------------------------------------------------------------
# 响应解析
# ---------------------------------------------------------------------------

def parse_ai_response(text: str) -> dict:
    """解析 AI 回复文本，提取结构化数据。

    返回: {
        "funds": {code: {sentiment, reason, suggestion}},
        "portfolio_analysis": str,
        "dca_adjustments": {code: str},
    }
    """
    result = {
        "funds": {},
        "portfolio_analysis": "",
        "dca_adjustments": {},
    }

    # 解析逐只分析行：代码: 情感 | 理由 | 建议
    fund_pattern = re.compile(
        r'^(\d{6})\s*[:：]\s*(看好|中性|谨慎)\s*[|｜]\s*(.+?)\s*[|｜]\s*(.+)$',
        re.MULTILINE,
    )
    for m in fund_pattern.finditer(text):
        result["funds"][m.group(1)] = {
            "sentiment": m.group(2).strip(),
            "reason": m.group(3).strip(),
            "suggestion": m.group(4).strip(),
        }

    # 解析各段落
    sections = re.split(r'###\s+', text)
    for sec in sections:
        sec = sec.strip()
        if sec.startswith("组合分析"):
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
    """一站式 AI 分析：逐只分析 + 组合分析。"""
    result = AiPortfolioAnalysis()

    client = _get_client()
    if not client:
        result.portfolio_analysis = "未配置 DEEPSEEK_API_KEY 环境变量，跳过 AI 分析。"
        return result

    # 1. 逐只分析
    fund_prompt = build_fund_prompt(funds, news)
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
    pf_prompt = build_portfolio_prompt(funds, total_value)
    pf_resp = call_deepseek(pf_prompt, system="你是专业的基金投资组合分析师，回答简洁、具体、可执行。")
    if pf_resp:
        parsed = parse_ai_response(pf_resp)
        result.portfolio_analysis = parsed.get("portfolio_analysis", "")
        result.dca_adjustments = parsed.get("dca_adjustments", {})

    return result


# ---------------------------------------------------------------------------
# 简易新闻搜索
# ---------------------------------------------------------------------------

def search_news_for_fund(name: str, keywords: List[str] = None) -> List[str]:
    """搜索基金相关新闻（Bing News RSS，免费源）。"""
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
            return [t for t in titles if t and "Bing" not in t][:5]
    except Exception as e:
        print(f"[news] 搜索 {name} 新闻失败: {e}")
        return []
