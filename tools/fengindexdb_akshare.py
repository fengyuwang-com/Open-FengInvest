#!/usr/bin/env python3
"""fengindexdb_akshare — A 股指数补充（填补 yfinance 缺失）

用法：
    python fengindexdb_akshare.py build    # 下载缺失的 A 股指数
    python fengindexdb_akshare.py update   # 增量更新
    python fengindexdb_akshare.py list     # 列出补充的指数
    python fengindexdb_akshare.py info <code>  # 查看某个指数
"""
import os, sqlite3, sys, time
from datetime import datetime, timedelta

import akshare as ak

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "market_data.db")

# A 股指数注册表 — yfinance 缺失的部分
# code: (name, market, category, akshare_symbol)
INDICES_AK = {
    "399006.SZ": ("创业板指", "CN", "index", "sz399006"),
    "000688.SS": ("科创板50", "CN", "index", "sh000688"),
    "399673.SZ": ("创业板50", "CN", "index", "sz399673"),
    "000016.SS": ("上证50", "CN", "index", "sh000016"),
    "000905.SS": ("中证500", "CN", "index", "sh000905"),
}

def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def seed_indices(conn):
    """写入 indices 表（如已存在则跳过）"""
    cur = conn.execute("SELECT ticker FROM indices")
    existing = {row[0] for row in cur.fetchall()}
    inserted = 0
    for ticker, (name, market, cat, _) in INDICES_AK.items():
        if ticker not in existing:
            conn.execute(
                "INSERT OR IGNORE INTO indices (ticker, name, market, category) VALUES (?, ?, ?, ?)",
                (ticker, name, market, cat),
            )
            inserted += 1
    if inserted:
        conn.commit()
        print(f"  新增 {inserted} 个 A 股指数到注册表")
    return len(INDICES_AK)

def download_index(conn, ticker, force_all=False):
    """下载一个 A 股指数的历史日线数据"""
    if ticker not in INDICES_AK:
        print(f"  [WARN] {ticker}: 未在 AKShare 注册表中")
        return 0
    name, market, cat, ak_symbol = INDICES_AK[ticker]

    # 获取 index_id
    cur = conn.execute("SELECT id FROM indices WHERE ticker = ?", (ticker,))
    row = cur.fetchone()
    if not row:
        print(f"  [WARN] {ticker}: 未在 indices 表中（请先 build）")
        return 0
    idx_id = row[0]

    # 确定起始日期
    if not force_all:
        cur = conn.execute("SELECT MAX(date) FROM daily_data WHERE index_id = ?", (idx_id,))
        max_date = cur.fetchone()[0]
        if max_date:
            # 已有数据，从最后日期往前推 5 天（防遗漏）
            start_dt = datetime.strptime(max_date, "%Y-%m-%d") - timedelta(days=5)
            start_str = start_dt.strftime("%Y%m%d")
        else:
            start_str = "20000101"  # 全量
    else:
        start_str = "20000101"

    end_str = datetime.now().strftime("%Y%m%d")

    try:
        df = ak.stock_zh_index_daily(symbol=ak_symbol)
    except Exception as e:
        print(f"  [ERR] {ticker} ({name}): 下载失败 - {str(e)[:80]}")
        return 0

    if df is None or df.empty:
        print(f"  [WARN] {ticker}: 无数据")
        return 0

    # 过滤出需要的新数据
    existing_dates = set()
    for d_row in conn.execute("SELECT date FROM daily_data WHERE index_id = ?", (idx_id,)).fetchall():
        existing_dates.add(d_row[0])

    new_rows = []
    for _, r in df.iterrows():
        date_str = str(r["date"])[:10]
        if date_str not in existing_dates:
            new_rows.append((
                idx_id, date_str,
                float(r["open"]) if r["open"] else None,
                float(r["high"]) if r["high"] else None,
                float(r["low"]) if r["low"] else None,
                float(r["close"]) if r["close"] else None,
                int(r["volume"]) if r["volume"] else None,
            ))

    if not new_rows:
        return 0

    conn.executemany(
        "INSERT OR IGNORE INTO daily_data (index_id, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
        new_rows,
    )
    conn.commit()

    last = new_rows[-1][1]
    print(f"  [OK] {ticker}: +{len(new_rows)} rows -> {last} ({name})")
    return len(new_rows)

# ─── CLI Commands ────────────────────────────────────────────

def cmd_build():
    conn = get_db()
    total = seed_indices(conn)
    print(f"\nAKShare 补充注册表: {total} 个指数\n开始下载...\n")
    total_rows = 0
    for ticker in INDICES_AK:
        rows = download_index(conn, ticker, force_all=True)
        total_rows += rows
        time.sleep(1)  # 礼貌间隔
    conn.close()
    print(f"\n完成: 新增 {total_rows} 条日线数据")

def cmd_update():
    conn = get_db()
    total = seed_indices(conn)
    print(f"增量更新 {total} 个 A 股指数...\n")
    total_rows = 0
    for ticker in INDICES_AK:
        rows = download_index(conn, ticker, force_all=False)
        total_rows += rows
        if rows:
            time.sleep(1)
    conn.close()
    if total_rows == 0:
        print("  所有指数已是最新")
    else:
        print(f"\n新增 {total_rows} 条数据")

def cmd_list():
    conn = get_db()
    placeholders = ",".join("?" for _ in INDICES_AK)
    cur = conn.execute(f"""
        SELECT i.ticker, i.name, COUNT(d.id) as rows,
               MIN(d.date) as first, MAX(d.date) as last
        FROM indices i
        LEFT JOIN daily_data d ON d.index_id = i.id
        WHERE i.ticker IN ({placeholders})
        GROUP BY i.id
        ORDER BY i.ticker
    """, list(INDICES_AK.keys()))
    rows = cur.fetchall()
    conn.close()
    if not rows:
        print("暂无 AKShare 补充数据")
        return
    print(f"{'Ticker':<14} {'名称':<16} {'行数':<8} {'起始':<12} {'最新':<12}")
    print("-" * 62)
    total = 0
    for r in rows:
        cnt = r["rows"] or 0
        total += cnt
        print(f"{r['ticker']:<14} {r['name']:<16} {cnt:<8} {r['first'] or '-':<12} {r['last'] or '-':<12}")
    print(f"\n总计: {len(rows)} 个指数, {total} 条数据")

def cmd_info(ticker):
    conn = get_db()
    cur = conn.execute("SELECT id, name, market FROM indices WHERE ticker = ?", (ticker.upper(),))
    row = cur.fetchone()
    if not row:
        print(f"[ERR] {ticker}: 未在注册表中")
        conn.close()
        return
    idx_id, name, market = row
    cur = conn.execute("""
        SELECT COUNT(*), MIN(date), MAX(date), MIN(close), MAX(close), AVG(close)
        FROM daily_data WHERE index_id = ?
    """, (idx_id,))
    cnt, first, last, min_c, max_c, avg_c = cur.fetchone()
    conn.close()
    if cnt and cnt > 0:
        print(f"{ticker} — {name} ({market})")
        print(f"  数据: {cnt} 行, {first} ~ {last}")
        print(f"  收盘: {min_c:.2f} ~ {max_c:.2f} (均值 {avg_c:.2f})")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "build":
        cmd_build()
    elif cmd == "update":
        cmd_update()
    elif cmd == "list":
        cmd_list()
    elif cmd == "info" and len(sys.argv) >= 3:
        cmd_info(sys.argv[2])
    else:
        print(f"未知命令: {cmd}")
        print(__doc__)
