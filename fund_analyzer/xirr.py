"""交易流水 + XIRR 真实年化收益计算。

XIRR: 基于现金流的时间加权内部收益率，比净值口径的持仓收益准确得多。
"""
from __future__ import annotations

import json
import os
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple


@dataclass
class Transaction:
    """一笔交易记录。"""
    date: date
    code: str
    fund_name: str = ""
    tx_type: str = "buy"    # buy | sell | dca | dividend
    amount: float = 0.0     # 金额（买入为正，卖出为负，分红为正）
    shares: float = 0.0     # 份额（可选）
    nav: float = 0.0        # 成交净值（可选）
    note: str = ""


@dataclass
class XirrResult:
    """XIRR 计算结果。"""
    xirr: float = 0.0           # 年化内部收益率（小数）
    total_invested: float = 0.0  # 总投入
    total_return: float = 0.0    # 总收益（绝对值）
    return_pct: float = 0.0      # 总收益率
    annualized_return: float = 0.0  # 简单年化
    years: float = 0.0           # 投资年限


# ---------------------------------------------------------------------------
# XIRR 计算
# ---------------------------------------------------------------------------

def _xirr_cashflows(transactions: List[Transaction],
                    current_value: float,
                    current_date: date) -> List[Tuple[date, float]]:
    """转换交易记录为现金流序列（负=投入，正=当前价值）。"""
    flows = []
    for tx in sorted(transactions, key=lambda t: t.date):
        if tx.tx_type in ("buy", "dca"):
            flows.append((tx.date, -abs(tx.amount)))
        elif tx.tx_type == "sell":
            flows.append((tx.date, abs(tx.amount)))
        elif tx.tx_type == "dividend":
            flows.append((tx.date, abs(tx.amount)))
    # 最后一笔：当前市值作为回笼
    if current_value > 0 and flows:
        flows.append((current_date, current_value))
    return flows


def _xirr_npv(rate: float, flows: List[Tuple[date, float]]) -> float:
    """计算给定折现率下的 NPV。"""
    if not flows:
        return 0.0
    d0 = flows[0][0]
    npv = 0.0
    for d, amt in flows:
        years = (d - d0).days / 365.25
        npv += amt / ((1.0 + rate) ** years)
    return npv


def compute_xirr(transactions: List[Transaction],
                 current_value: float,
                 current_date: date = None) -> XirrResult:
    """计算 XIRR 年化内部收益率。"""
    if current_date is None:
        current_date = date.today()

    result = XirrResult()

    # 汇总
    total_in = sum(tx.amount for tx in transactions if tx.tx_type in ("buy", "dca"))
    total_out = sum(tx.amount for tx in transactions if tx.tx_type == "sell")
    result.total_invested = total_in - total_out
    result.total_return = current_value - result.total_invested
    result.return_pct = result.total_return / max(result.total_invested, 0.01)

    flows = _xirr_cashflows(transactions, current_value, current_date)
    if len(flows) < 2:
        result.xirr = result.return_pct
        result.years = 0
        return result

    years = (current_date - flows[0][0]).days / 365.25
    result.years = years
    result.annualized_return = (current_value / max(total_in, 0.01)) ** (1.0 / max(years, 0.01)) - 1

    # Newton-Raphson 求解 IRR
    guess = 0.1
    for _ in range(100):
        npv = _xirr_npv(guess, flows)
        if abs(npv) < 0.01:
            break
        # 数值导数
        deriv = (_xirr_npv(guess + 0.0001, flows) - npv) / 0.0001
        if abs(deriv) < 1e-9:
            break
        guess = guess - npv / deriv
        guess = max(-0.99, min(10.0, guess))  # 限幅

    result.xirr = guess
    return result


# ---------------------------------------------------------------------------
# 交易流水存储
# ---------------------------------------------------------------------------

TX_FILE = "config/transactions.json"


def load_transactions(code: str = None) -> List[Transaction]:
    """加载交易记录。code=None 返回全部。"""
    if not os.path.exists(TX_FILE):
        return []
    try:
        with open(TX_FILE, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return []
    txs = []
    for item in data:
        try:
            tx = Transaction(
                date=date.fromisoformat(item["date"]),
                code=item["code"],
                fund_name=item.get("fund_name", ""),
                tx_type=item.get("tx_type", "buy"),
                amount=float(item.get("amount", 0)),
                shares=float(item.get("shares", 0)),
                nav=float(item.get("nav", 0)),
                note=item.get("note", ""),
            )
            if code is None or tx.code == code:
                txs.append(tx)
        except (KeyError, ValueError):
            continue
    return txs


def save_transactions(transactions: List[Transaction]):
    """保存交易记录。"""
    os.makedirs(os.path.dirname(TX_FILE), exist_ok=True)
    data = []
    for tx in transactions:
        data.append({
            "date": tx.date.isoformat(),
            "code": tx.code,
            "fund_name": tx.fund_name,
            "tx_type": tx.tx_type,
            "amount": tx.amount,
            "shares": tx.shares,
            "nav": tx.nav,
            "note": tx.note,
        })
    with open(TX_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def auto_dca_transactions(holdings: list, days_back: int = 90) -> List[Transaction]:
    """从持仓的定投计划自动生成历史 DCA 交易记录。"""
    today = date.today()
    txs = []
    for h in holdings:
        dp = h.get("dca_plan") or {}
        if not dp.get("amount"):
            continue
        freq = dp.get("frequency", "daily")
        amt = float(dp["amount"])
        code = str(h.get("code", ""))
        name = h.get("name", "")

        if freq == "daily":
            interval = 1
        elif freq == "weekly":
            interval = 7
        else:
            interval = 30

        d = today - timedelta(days=days_back)
        while d <= today:
            if d.weekday() < 5:  # 工作日
                txs.append(Transaction(
                    date=d, code=code, fund_name=name,
                    tx_type="dca", amount=amt,
                ))
            d += timedelta(days=interval)

    return sorted(txs, key=lambda t: t.date)
