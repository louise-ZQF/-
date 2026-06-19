"""滚动时间外回测 + 简单基准对比。"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Dict, List, Optional, Tuple


@dataclass
class BacktestResult:
    """回测结果。"""
    method: str                    # 策略名称
    dates: List[str] = field(default_factory=list)
    forward_3m: List[float] = field(default_factory=list)   # 未来3月超额收益
    forward_6m: List[float] = field(default_factory=list)
    forward_12m: List[float] = field(default_factory=list)
    hit_rate_top10: List[float] = field(default_factory=list)  # Top10%命中率
    turnover: List[float] = field(default_factory=list)        # 换手率
    max_dd: List[float] = field(default_factory=list)

    @property
    def mean_3m(self) -> float:
        return statistics.mean(self.forward_3m) if self.forward_3m else 0

    @property
    def mean_6m(self) -> float:
        return statistics.mean(self.forward_6m) if self.forward_6m else 0

    @property
    def mean_12m(self) -> float:
        return statistics.mean(self.forward_12m) if self.forward_12m else 0

    @property
    def win_rate_3m(self) -> float:
        if not self.forward_3m:
            return 0
        return sum(1 for r in self.forward_3m if r > 0) / len(self.forward_3m)

    def to_dict(self) -> dict:
        return {
            "method": self.method,
            "mean_3m": round(self.mean_3m * 100, 2),
            "mean_6m": round(self.mean_6m * 100, 2),
            "mean_12m": round(self.mean_12m * 100, 2),
            "win_rate_3m": round(self.win_rate_3m * 100, 1),
            "n_periods": len(self.dates),
        }


def run_walk_forward(
    fund_universe_provider: Callable[[date], List[dict]],
    nav_provider: Callable[[str, date, date], List[Tuple[date, float]]],
    scorer: Callable[[List[dict], date], List[dict]],
    start_date: date,
    end_date: date,
    step_months: int = 3,
    top_n: int = 10,
) -> BacktestResult:
    """滚动回测框架。

    fund_universe_provider(as_of_date) → 当时存在的所有基金
    nav_provider(code, start, end) → 净值序列
    scorer(funds, as_of_date) → 评分后的基金列表（已排序）
    """
    result = BacktestResult(method="screener")

    current = start_date
    while current <= end_date:
        result.dates.append(current.isoformat())

        try:
            # 1. 获取当时可用的基金
            funds = fund_universe_provider(current)

            # 2. 评分（只使用 current 之前的数据）
            ranked = scorer(funds, current)
            top = ranked[:top_n]

            # 3. 测量未来表现
            future_start = current
            future_end_3m = current + timedelta(days=90)
            future_end_6m = current + timedelta(days=180)
            future_end_12m = current + timedelta(days=365)

            forward_rets_3m = []
            forward_rets_6m = []
            forward_rets_12m = []

            for f in top:
                code = f.get("code", "")
                navs = nav_provider(code, future_start, future_end_12m)
                if len(navs) >= 2:
                    ret_3m = navs[min(len(navs)-1, 63)][1] / navs[0][1] - 1 if len(navs) > 0 else 0
                    ret_6m = navs[min(len(navs)-1, 126)][1] / navs[0][1] - 1 if len(navs) > 0 else 0
                    ret_12m = navs[-1][1] / navs[0][1] - 1 if navs else 0
                    forward_rets_3m.append(ret_3m)
                    forward_rets_6m.append(ret_6m)
                    forward_rets_12m.append(ret_12m)

            if forward_rets_3m:
                result.forward_3m.append(statistics.mean(forward_rets_3m))
            if forward_rets_6m:
                result.forward_6m.append(statistics.mean(forward_rets_6m))
            if forward_rets_12m:
                result.forward_12m.append(statistics.mean(forward_rets_12m))

        except Exception as e:
            print(f"[backtest] {current} failed: {e}")

        current += timedelta(days=30 * step_months)

    return result


def compare_with_baselines(
    fund_pool: List[dict],
    screener_result: BacktestResult,
) -> Dict[str, BacktestResult]:
    """与简单策略对比。"""
    import random

    results = {"screener": screener_result}

    # 1. 随机选基金
    random_result = BacktestResult(method="random")
    for _ in range(len(screener_result.dates)):
        sample = random.sample(fund_pool, min(10, len(fund_pool)))
        rets = [f.get("ret_12m", 0) for f in sample]
        random_result.forward_12m.append(statistics.mean(rets) if rets else 0)
    results["random"] = random_result

    # 2. 最低费率
    by_fee = sorted(fund_pool, key=lambda f: f.get("annual_fee", 0.01))
    fee_result = BacktestResult(method="lowest_fee")
    fee_rets = [f.get("ret_12m", 0) for f in by_fee[:10]]
    for _ in range(len(screener_result.dates)):
        fee_result.forward_12m.append(statistics.mean(fee_rets) if fee_rets else 0)
    results["lowest_fee"] = fee_result

    # 3. 最高1年收益
    by_ret = sorted(fund_pool, key=lambda f: f.get("ret_1y", 0), reverse=True)
    ret_result = BacktestResult(method="highest_1y_return")
    ret_rets = [f.get("ret_12m", 0) for f in by_ret[:10]]
    for _ in range(len(screener_result.dates)):
        ret_result.forward_12m.append(statistics.mean(ret_rets) if ret_rets else 0)
    results["highest_1y_return"] = ret_result

    # 4. 同类平均
    avg_result = BacktestResult(method="peer_average")
    all_rets = [f.get("ret_12m", 0) for f in fund_pool if f.get("ret_12m")]
    for _ in range(len(screener_result.dates)):
        avg_result.forward_12m.append(statistics.mean(all_rets) if all_rets else 0)
    results["peer_average"] = avg_result

    # 判断是否优于基线
    for name, br in results.items():
        if name == "screener":
            continue
        better_3m = screener_result.mean_3m > br.mean_3m if br.forward_3m else False
        better_12m = screener_result.mean_12m > br.mean_12m if br.forward_12m else False
        br.comparison = {
            "screener_better_3m": better_3m,
            "screener_better_12m": better_12m,
        }

    return results
