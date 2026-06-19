"""A/C类去重 + 同指数去重。"""
from __future__ import annotations

from typing import Dict, List, Optional


def find_share_class_pairs(funds: List[dict]) -> List[tuple]:
    """识别 A/C 类配对。同名基金去掉末尾 A/C 后相同即为配对。"""
    import re
    pairs = []
    seen = {}
    for i, f in enumerate(funds):
        name = f.get("name", "")
        # 去掉末尾 A/C
        base = re.sub(r'[AC]$', '', name.strip())
        if base in seen:
            pairs.append((seen[base], i))
        else:
            seen[base] = i
    return pairs


def resolve_share_class(fund_a: dict, fund_c: dict, hold_years: float = 3) -> dict:
    """在 A/C 类中选一个。预期持有3年以上选A类（无销售服务费），否则选C类。"""
    fee_a = fund_a.get("annual_fee", 0.01)
    fee_c = fund_c.get("annual_fee", 0.01) + 0.004  # C类通常多0.4%销售服务费

    if hold_years >= 3:
        # A类长期更省
        return fund_a
    else:
        return fund_c


def deduplicate_share_classes(funds: List[dict]) -> List[dict]:
    """去重 A/C 类，每对保留一只。"""
    pairs = find_share_class_pairs(funds)
    remove_indices = set()
    for i, j in pairs:
        winner = resolve_share_class(funds[i], funds[j])
        if winner is funds[i]:
            remove_indices.add(j)
        else:
            remove_indices.add(i)

    return [f for idx, f in enumerate(funds) if idx not in remove_indices]


def deduplicate_same_index(funds: List[dict]) -> List[dict]:
    """同一基准指数只保留综合质量最高的一只。"""
    from collections import defaultdict
    by_benchmark = defaultdict(list)
    for f in funds:
        bm = f.get("benchmark_code", "unknown")
        by_benchmark[bm].append(f)

    result = []
    for bm, group in by_benchmark.items():
        if len(group) <= 1:
            result.extend(group)
        else:
            # 保留综合分最高的
            group.sort(key=lambda x: x.get("composite_score", 0), reverse=True)
            winner = group[0]
            winner["dedup_note"] = f"同基准{bm}中排名第1/{len(group)}"
            result.append(winner)

    return result
