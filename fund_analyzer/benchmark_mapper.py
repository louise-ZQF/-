"""基准映射器：为每只基金匹配正确的比较基准，处理 QDII 汇率和日期滞后。"""
from __future__ import annotations
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple


# 基准代码 → 中文名称 + 货币
BENCHMARK_INFO: Dict[str, dict] = {
    "^NDX": {"name": "纳斯达克100", "currency": "USD", "region": "us"},
    "^IXIC": {"name": "纳斯达克综合", "currency": "USD", "region": "us"},
    "^GSPC": {"name": "标普500", "currency": "USD", "region": "us"},
    "^DJI": {"name": "道琼斯工业", "currency": "USD", "region": "us"},
    "^SOX": {"name": "费城半导体", "currency": "USD", "region": "us"},
    "^HSTECH": {"name": "恒生科技", "currency": "HKD", "region": "hk"},
    "^HSI": {"name": "恒生指数", "currency": "HKD", "region": "hk"},
    "000300": {"name": "沪深300", "currency": "CNY", "region": "cn"},
    "000905": {"name": "中证500", "currency": "CNY", "region": "cn"},
    "000016": {"name": "上证50", "currency": "CNY", "region": "cn"},
    "399006": {"name": "创业板指", "currency": "CNY", "region": "cn"},
    "000688": {"name": "科创50", "currency": "CNY", "region": "cn"},
    "MSCI_WORLD": {"name": "MSCI全球", "currency": "USD", "region": "global"},
    "CBA001": {"name": "中债综合", "currency": "CNY", "region": "cn"},
    "GC=F": {"name": "黄金期货", "currency": "USD", "region": "us"},
}


# QDII 基金净值滞后天数（指数收盘 → 基金净值公布）
_QDII_LAG: Dict[str, int] = {
    "^NDX": 2, "^IXIC": 2, "^GSPC": 1, "^DJI": 1, "^SOX": 2,
    "^HSTECH": 1, "^HSI": 1, "MSCI_WORLD": 2, "GC=F": 2,
}


# 汇率代码
_FX_MAP: Dict[str, str] = {
    "USD": "USDCNY",
    "HKD": "HKDCNY",
}


def get_benchmark_info(benchmark_code: str) -> dict:
    """获取基准信息。"""
    return BENCHMARK_INFO.get(benchmark_code, {"name": benchmark_code, "currency": "CNY", "region": "cn"})


def get_qdii_lag(benchmark_code: str) -> int:
    """获取 QDII 基金净值滞后天数。"""
    return _QDII_LAG.get(benchmark_code, 1)


def get_fx_code(benchmark_code: str) -> Optional[str]:
    """获取基准货币对应的汇率代码。"""
    info = BENCHMARK_INFO.get(benchmark_code, {})
    currency = info.get("currency", "CNY")
    return _FX_MAP.get(currency)


def align_nav_dates(fund_navs: List[Tuple[date, float]],
                    benchmark_returns: List[Tuple[date, float]],
                    lag_days: int = 2) -> List[Tuple[date, float, float]]:
    """对齐基金净值和基准收益的日期。

    QDII 基金净值公布滞后 lag_days 个交易日，因此：
    基金在 date+lag 公布的净值 对应的是 date 日的基准收益。

    返回: [(基金净值日期, 基金日收益, 同日基准日收益), ...]
    """
    if len(fund_navs) < 2:
        return []

    # 计算基金日收益
    fund_rets = []
    for i in range(1, len(fund_navs)):
        d, nav = fund_navs[i]
        _, prev_nav = fund_navs[i - 1]
        if prev_nav and prev_nav > 0:
            fund_rets.append((d, nav / prev_nav - 1.0))

    # 基准收益索引
    bench_dict = {d: r for d, r in benchmark_returns}

    aligned = []
    for d, fr in fund_rets:
        # 基金净值日期 d 反映的是 d-lag_days 日的基准表现
        bench_date = d - timedelta(days=lag_days)
        # 找最近的交易日
        for offset in range(5):
            bd = bench_date - timedelta(days=offset)
            br = bench_dict.get(bd)
            if br is not None:
                aligned.append((d, fr, br))
                break

    return aligned


def compute_tracking_metrics(aligned_data: List[Tuple[date, float, float]]) -> dict:
    """从对齐数据计算跟踪指标。

    返回: {tracking_diff, tracking_error, beta, alpha, r_squared, info_ratio}
    """
    if len(aligned_data) < 20:
        return {}

    import statistics, math

    fund_rets = [a[1] for a in aligned_data]
    bench_rets = [a[2] for a in aligned_data]
    diffs = [f - b for f, b in zip(fund_rets, bench_rets)]
    n = len(diffs)

    # 跟踪差异（年化）
    td = sum(diffs) / n * 252

    # 跟踪误差（年化）
    te = statistics.stdev(diffs) * math.sqrt(252) if n > 1 else 0

    # Beta 回归
    b_mean = statistics.mean(bench_rets)
    f_mean = statistics.mean(fund_rets)
    cov = sum((bf - b_mean) * (ff - f_mean) for bf, ff in zip(bench_rets, fund_rets)) / (n - 1)
    b_var = statistics.stdev(bench_rets) ** 2 if n > 1 else 1
    beta = cov / max(b_var, 0.0001)
    alpha = (f_mean - beta * b_mean) * 252

    # R²
    residuals = [ff - (beta * bf) for ff, bf in zip(fund_rets, bench_rets)]
    ss_res = sum(r ** 2 for r in residuals)
    ss_tot = sum((ff - f_mean) ** 2 for ff in fund_rets)
    r_squared = 1 - ss_res / max(ss_tot, 0.0001)

    # 信息比率
    ir = (td - 0) / max(te, 0.0001) if te > 0 else 0

    return {
        "tracking_diff": round(td, 4),
        "tracking_error": round(te, 4),
        "beta": round(beta, 4),
        "alpha": round(alpha, 4),
        "r_squared": round(r_squared, 4),
        "info_ratio": round(ir, 2),
    }
