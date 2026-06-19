"""每日组合快照 + 收益曲线。

每天自动保存一次组合总估值，前端画累计收益曲线。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional

SNAPSHOT_FILE = "data/snapshots.json"


@dataclass
class Snapshot:
    date: str          # "2026-06-19"
    total_value: float
    total_cost: float
    total_invested: float   # 累计投入（含定投）
    fund_count: int
    notes: str = ""


def load_snapshots(days: int = 365) -> List[dict]:
    """加载历史快照。"""
    if not os.path.exists(SNAPSHOT_FILE):
        return []
    try:
        with open(SNAPSHOT_FILE, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return []
    cutoff = date.today()
    results = []
    for item in data:
        try:
            d = date.fromisoformat(item["date"])
            if (cutoff - d).days <= days:
                results.append(item)
        except (KeyError, ValueError):
            continue
    return sorted(results, key=lambda x: x["date"])


def save_snapshot(total_value: float, total_cost: float, total_invested: float,
                  fund_count: int, notes: str = ""):
    """保存当日快照（同一天只保留最新）。"""
    os.makedirs(os.path.dirname(SNAPSHOT_FILE), exist_ok=True)
    snapshots = load_snapshots(days=9999) if os.path.exists(SNAPSHOT_FILE) else []

    today_str = date.today().isoformat()
    # 替换或追加
    replaced = False
    for s in snapshots:
        if s["date"] == today_str:
            s["total_value"] = total_value
            s["total_cost"] = total_cost
            s["total_invested"] = total_invested
            s["fund_count"] = fund_count
            s["notes"] = notes
            replaced = True
            break
    if not replaced:
        snapshots.append({
            "date": today_str,
            "total_value": round(total_value, 2),
            "total_cost": round(total_cost, 2),
            "total_invested": round(total_invested, 2),
            "fund_count": fund_count,
            "notes": notes,
        })

    # 只保留最近 2 年
    cutoff = date.today().replace(year=date.today().year - 2)
    snapshots = [s for s in snapshots if date.fromisoformat(s["date"]) >= cutoff]

    with open(SNAPSHOT_FILE, "w") as f:
        json.dump(snapshots, f, ensure_ascii=False, indent=2)
