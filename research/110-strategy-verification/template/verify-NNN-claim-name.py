#!/usr/bin/env python3
"""test.py — 论断 #[ID] [论断名称]

用法:
    python research/110-strategy-verification/NNN-claim-name/test.py
"""
import sys, os, json, sqlite3
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, BASE)

DB_PATH = os.path.join(BASE, "data", "market_data.db")


def get_stocks(market="US", category="stock"):
    """获取指定市场的股票列表"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, ticker, name FROM indices WHERE market=? AND category=? ORDER BY ticker",
        (market, category)
    ).fetchall()
    conn.close()
    return rows


def run_backtest():
    """主回测逻辑"""
    stocks = get_stocks("US")
    print(f"共 {len(stocks)} 只股票")

    # TODO: 实现回测逻辑
    results = {"signal_count": 0, "win_rate": 0}
    return results


if __name__ == "__main__":
    results = run_backtest()
    print(json.dumps(results, indent=2, ensure_ascii=False))
