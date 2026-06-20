"""SQLite 持久化：基金元数据 + 历史净值缓存。"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime
from typing import Dict, List, Optional

DB_PATH = "data/fund_cache.db"


def _conn() -> sqlite3.Connection:
    os.makedirs("data", exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db():
    """初始化表结构。"""
    with _conn() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS fund_meta (
                code TEXT PRIMARY KEY,
                name TEXT,
                inception_date TEXT,
                fund_type TEXT,
                annual_fee REAL,
                fund_size REAL,
                updated_at TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS nav_history (
                code TEXT,
                date TEXT,
                nav REAL,
                cum_nav REAL,
                change_pct REAL,
                PRIMARY KEY (code, date)
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS benchmark_returns (
                benchmark_code TEXT,
                date TEXT,
                return_pct REAL,
                PRIMARY KEY (benchmark_code, date)
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_nav_code ON nav_history(code)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_nav_date ON nav_history(date)")
        db.commit()


def upsert_meta(code: str, meta: dict):
    """写入或更新基金元数据。"""
    with _conn() as db:
        db.execute("""
            INSERT OR REPLACE INTO fund_meta (code, name, inception_date, fund_type, annual_fee, fund_size, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            code,
            meta.get("name", ""),
            meta.get("inception_date"),
            meta.get("fund_type"),
            meta.get("annual_fee"),
            meta.get("fund_size"),
            date.today().isoformat(),
        ))
        db.commit()


def get_meta(code: str) -> Optional[dict]:
    """读取基金元数据。"""
    with _conn() as db:
        row = db.execute(
            "SELECT name, inception_date, fund_type, annual_fee, fund_size FROM fund_meta WHERE code=?",
            (code,)
        ).fetchone()
        if not row:
            return None
        return {
            "name": row[0], "inception_date": row[1], "fund_type": row[2],
            "annual_fee": row[3], "fund_size": row[4],
        }


def insert_nav_batch(code: str, navs: List[dict]):
    """批量写入净值。navs: [{date, nav, cum_nav, change_pct}]"""
    with _conn() as db:
        db.executemany(
            "INSERT OR IGNORE INTO nav_history (code, date, nav, cum_nav, change_pct) VALUES (?,?,?,?,?)",
            [(code, n["date"], n["nav"], n.get("cum_nav"), n.get("change_pct")) for n in navs]
        )
        db.commit()


def get_nav_history(code: str, start_date: str = None, limit: int = 300) -> List[dict]:
    """读取净值历史。"""
    with _conn() as db:
        if start_date:
            rows = db.execute(
                "SELECT date, nav, cum_nav, change_pct FROM nav_history WHERE code=? AND date>=? ORDER BY date ASC LIMIT ?",
                (code, start_date, limit)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT date, nav, cum_nav, change_pct FROM nav_history WHERE code=? ORDER BY date DESC LIMIT ?",
                (code, limit)
            ).fetchall()
            rows = list(reversed(rows))
        return [
            {"date": r[0], "nav": r[1], "cum_nav": r[2], "change_pct": r[3]}
            for r in rows
        ]


def get_nav_count(code: str) -> int:
    with _conn() as db:
        row = db.execute("SELECT COUNT(*) FROM nav_history WHERE code=?", (code,)).fetchone()
        return row[0] if row else 0


def get_all_codes() -> List[str]:
    with _conn() as db:
        rows = db.execute("SELECT DISTINCT code FROM nav_history").fetchall()
        return [r[0] for r in rows]


def sync_nav_for_codes(http, codes: List[str], progress_callback=None):
    """为指定代码同步净值到 SQLite。

    http: HttpClient 实例
    codes: 基金代码列表
    progress_callback: 可选，每同步一只回调 (code, index, total)
    """
    from .datasource.eastmoney import EastMoney
    em = EastMoney(http)

    total = len(codes)
    synced = 0
    for i, code in enumerate(codes):
        try:
            # Check if we already have enough data
            existing = get_nav_count(code)
            if existing >= 200:
                continue  # Already synced

            navpoints = em.history(code, size=300)
            if navpoints:
                batch = [
                    {
                        "date": p.d.isoformat(),
                        "nav": p.nav,
                        "cum_nav": p.cum_nav,
                        "change_pct": p.change,
                    }
                    for p in navpoints
                ]
                insert_nav_batch(code, batch)
                synced += 1
        except Exception as e:
            print(f"[sync] {code} failed: {e}")

        if progress_callback:
            progress_callback(code, i + 1, total)

    return synced


def get_sync_status(codes: List[str]) -> dict:
    """获取同步状态。"""
    total = len(codes)
    complete = sum(1 for c in codes if get_nav_count(c) >= 200)
    return {
        "total": total,
        "complete": complete,
        "pct": round(complete / max(total, 1) * 100, 1),
    }
