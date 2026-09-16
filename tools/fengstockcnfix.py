#!/usr/bin/env python3
"""补爬 CN 沪深300 6只缺失股票的 baostock 数据"""
# 豁免 safe_batch：一次性补丁（6 只缺失票 INSERT OR IGNORE，有数即跳过）。日期 2026-09-09，见 docs/DATA-MANAGEMENT.md §八。
import os, sys, sqlite3, time

sys.stdout.reconfigure(encoding='utf-8')
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "data", "market_data.db")

TICKERS = ["600000.SS", "600009.SS", "600010.SS", "600011.SS", "600015.SS", "600016.SS"]

def ensure_bs():
    import baostock as bs
    bs.login()

def download_baostock(symbol, start="2000-01-01", end=None):
    import baostock as bs
    if end is None:
        from datetime import datetime
        end = datetime.now().strftime("%Y-%m-%d")
    code = f"sh.{symbol}" if symbol.startswith(("6", "9")) else f"sz.{symbol}"
    rs = bs.query_history_k_data_plus(
        code, "date,open,high,low,close,volume",
        start_date=start, end_date=end,
        frequency="d", adjustflag="3"
    )
    rows = []
    while rs.next():
        d, o, h, l, c, v = rs.get_row_data()
        try:
            rows.append((d, float(o), float(h), float(l), float(c), int(float(v))))
        except (ValueError, TypeError):
            continue
    return rows

def main():
    conn = sqlite3.connect(DB_PATH)
    ensure_bs()

    for ticker in TICKERS:
        row = conn.execute(
            "SELECT id FROM indices WHERE ticker=? AND market='CN'", (ticker,)
        ).fetchone()
        if not row:
            print(f"{ticker}: 不在数据库中，跳过")
            continue
        idx_id = row[0]

        # 检查是否已有数据
        cnt = conn.execute("SELECT COUNT(*) FROM daily_data WHERE index_id=?", (idx_id,)).fetchone()[0]
        if cnt > 0:
            print(f"{ticker}: 已有 {cnt} 行数据")
            continue

        # 提取数字代码
        code = ticker.replace(".SS", "").replace(".SZ", "")
        print(f"{ticker} (code={code}): 下载中...", end=" ", flush=True)

        rows = download_baostock(code)
        if not rows:
            print("空数据")
            continue

        data = [(idx_id, *r) for r in rows]
        conn.executemany(
            "INSERT OR IGNORE INTO daily_data (index_id, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
            data
        )
        conn.commit()
        print(f"{len(data)} 行")
        time.sleep(0.5)  # baostock 不频繁

    conn.close()
    print("\n✅ 完成")

if __name__ == "__main__":
    main()
