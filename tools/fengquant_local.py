#!/usr/bin/env python3
"""fengquant_local — fengquant 的本地 DB 数据源适配层（yfinance 不可用时）。

背景：fengquant.py 的因子计算逻辑是权威的，但它只有 yfinance 一个取数源。
yfinance 被限流（YFRateLimitError）或网络不可达时，整层 L2b 会因取数失败而瘫痪。

本适配器不复制任何因子逻辑：它把 `yf.Ticker` 替换成一个从 `data/market_data.db`
读数据的替身对象，然后原样调用 `fengquant.main()`。z-score、连续性校正、
abstain 语义全部仍由 fengquant.py 本体计算——**工具仍然是产出者**。

数据来源与口径
  - 估值/质量字段 ← `fundamentals` 表（整组 peer 同一快照，保证可比性）
  - 动量 6M      ← `daily_data` 表前复权 close 序列（126 个交易日）
  快照年份会写进输出的 `data_source` 块，**不回填、不伪装成实时值**。

Usage:
    python fengquant_local.py AAPL                 # 自动 peer 组
    python fengquant_local.py AAPL --group us_bigtech
    python fengquant_local.py AAPL --peers MSFT GOOGL

Exit codes: 0 正常 / 1 用法错误 / 2 本 DB 无该标的或数据不足
"""

import json
import os
import sqlite3
import sys
from datetime import datetime

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "data", "market_data.db")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _conn():
    if not os.path.exists(DB):
        print(json.dumps({"error": f"local DB not found: {DB}"}, indent=2), file=sys.stderr)
        sys.exit(2)
    return sqlite3.connect(DB)


def _lookup(conn, ticker):
    """ticker -> (index_id, name, fundamentals row dict)."""
    row = conn.execute(
        "SELECT id, name FROM indices WHERE UPPER(ticker)=?", (ticker.upper(),)
    ).fetchone()
    if not row:
        return None
    index_id, name = row
    f = conn.execute(
        """SELECT updated_at, market_cap, trailing_pe, forward_pe, price_to_book,
                  return_on_equity, profit_margin, revenue_growth, debt_to_equity
             FROM fundamentals WHERE index_id=?""",
        (index_id,),
    ).fetchone()
    if not f:
        return None
    keys = ("updated_at", "market_cap", "trailing_pe", "forward_pe", "price_to_book",
            "return_on_equity", "profit_margin", "revenue_growth", "debt_to_equity")
    d = dict(zip(keys, f))
    d["index_id"] = index_id
    d["name"] = name
    return d


class _FakeHist:
    """Minimal stand-in for the yfinance DataFrame fengquant touches: hist['Close']."""

    def __init__(self, closes):
        self._closes = closes

    @property
    def empty(self):
        return len(self._closes) == 0

    def __getitem__(self, key):
        if key != "Close":
            raise KeyError(key)
        return _Series(self._closes)


class _Series:
    """pandas 语义替身：iloc 是索引器（c.iloc[-1]），不是方法。"""

    def __init__(self, vals):
        self._vals = vals

    def __len__(self):
        return len(self._vals)

    @property
    def iloc(self):
        return self._vals


class FakeTicker:
    """Serves fengquant's two access patterns from the local DB."""

    def __init__(self, ticker):
        self.ticker = ticker.upper()
        conn = _conn()
        try:
            self._row = _lookup(conn, self.ticker)
            self._closes = []
            if self._row:
                rows = conn.execute(
                    "SELECT close FROM daily_data WHERE index_id=? "
                    "AND close IS NOT NULL ORDER BY date DESC LIMIT 130",
                    (self._row["index_id"],),
                ).fetchall()
                self._closes = [float(r[0]) for r in reversed(rows)]
        finally:
            conn.close()

    @property
    def info(self):
        if not self._row:
            return {}
        r = self._row
        return {
            "shortName": r.get("name") or self.ticker,
            "trailingPE": r.get("trailing_pe"),
            "forwardPE": r.get("forward_pe"),
            "priceToBook": r.get("price_to_book"),
            "returnOnEquity": r.get("return_on_equity"),
            "profitMargins": r.get("profit_margin"),
            "revenueGrowth": r.get("revenue_growth"),
            "debtToEquity": r.get("debt_to_equity"),
            "marketCap": r.get("market_cap"),
        }

    def history(self, period="1y"):
        return _FakeHist(self._closes)


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: fengquant_local.py TICKER [--group G|--peers P1 P2]"}, indent=2))
        sys.exit(1)

    ticker = sys.argv[1].upper()

    # 预检：目标必须在本 DB 里，否则直接有声失败，不进入引擎
    conn = _conn()
    try:
        row = _lookup(conn, ticker)
    finally:
        conn.close()
    if not row:
        print(json.dumps({
            "error": f"{ticker} not in local DB (indices/fundamentals missing)",
            "hint": "本地 DB 无该标的，此适配层无法代偿；请恢复 yfinance 或换数据源",
        }, indent=2), file=sys.stderr)
        sys.exit(2)

    import fengquant
    fengquant.yf = type("_Shim", (), {"Ticker": FakeTicker})

    snapshot = row.get("updated_at")
    fengquant.main()  # 原样调用；上面注入的数据源会写进 stdout 的 JSON

    # fengquant.main() 已经把 JSON 打出来了，这里无法再改它 —— 数据源声明改由
    # stderr 输出，调用方自行拼装（见 04-quantitative.json 的 data_source 块）。
    print(json.dumps({
        "data_source": "local_db",
        "db": "data/market_data.db",
        "fundamentals_snapshot": snapshot,
        "note": "估值/质量字段为全组同一快照，保证 peer 可比；非实时值",
    }, ensure_ascii=False), file=sys.stderr)


if __name__ == "__main__":
    main()
