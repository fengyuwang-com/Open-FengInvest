#!/usr/bin/env python3
"""fengindexdb — 全局指数数据库（SQLite + yfinance）

构建/更新本地数据库，存储所有常用指数的日线 OHLCV 数据。
支持增量更新：已有数据不重复下载，只拉最新数据。

Usage:
    python fengindexdb.py build          # 首次构建全量数据库
    python fengindexdb.py update         # 增量更新（只拉新数据）
    python fengindexdb.py list           # 列出库中所有指数
    python fengindexdb.py info <ticker>  # 查看某个指数的数据摘要
    python fengindexdb.py export <ticker> # 导出为 JSON
"""
import json, os, sqlite3, sys, time
from datetime import datetime, timedelta

import yfinance as yf

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "market_data.db")

# ─── Index Registry ──────────────────────────────────────────────────────────
# 所有常用指数，按市场分类
# ticker: (name, yfinance_ticker, market, category)
INDICES = {
    # === 美国 ===
    "^GSPC":  ("S&P 500", "US", "index"),
    "^DJI":   ("道琼斯工业平均", "US", "index"),
    "^IXIC":  ("纳斯达克综合指数", "US", "index"),
    "^RUT":   ("罗素2000", "US", "index"),
    "SPY":    ("SPDR S&P 500 ETF", "US", "etf"),
    "QQQ":    ("Invesco QQQ ETF (纳指100)", "US", "etf"),
    "IWM":    ("iShares Russell 2000 ETF", "US", "etf"),
    "DIA":    ("SPDR Dow Jones ETF", "US", "etf"),
    "EWJ":    ("iShares MSCI Japan ETF", "US", "etf"),
    "EWY":    ("iShares MSCI South Korea ETF", "US", "etf"),
    "EWH":    ("iShares MSCI Hong Kong ETF", "US", "etf"),
    "EWT":    ("iShares MSCI Taiwan ETF", "US", "etf"),
    "INDA":   ("iShares MSCI India ETF", "US", "etf"),
    "FXI":    ("iShares China Large-Cap ETF", "US", "etf"),
    "MCHI":   ("iShares MSCI China ETF", "US", "etf"),
    "ASHR":   ("Xtrackers Harvest CSI 300 ETF", "US", "etf"),
    "^VIX":   ("CBOE 波动率指数 VIX", "US", "index"),
    # 宏观资产
    "^TNX":   ("美国10年期国债收益率", "US", "macro"),
    "DX-Y.NYB":("美元指数 DXY", "US", "macro"),
    "GLD":    ("SPDR 黄金 ETF", "US", "etf"),
    "TLT":    ("iShares 20+年国债 ETF", "US", "etf"),
    "SHY":    ("iShares 1-3年国债 ETF", "US", "etf"),
    # === 香港 ===
    "^HSI":   ("恒生指数", "HK", "index"),
    "^HSCE":  ("恒生中国企业指数 (H股)", "HK", "index"),
    # 恒生科技指数 ETF 代理
    "3033.HK":("恒生科技ETF (3033)", "HK", "etf"),
    # === 中国内地 ===
    "000001.SS": ("上证综指", "CN", "index"),
    "399001.SZ": ("深证成指", "CN", "index"),
    "000300.SS": ("沪深300", "CN", "index"),
    # A股指数 ETF 代理（覆盖创业板/科创/中证500等 yfinance 不支持的 A 股板块）
    "CNXT":   ("中证500 ETF (深交所)", "CN", "etf"),
    # ^399006.SZ/000688.SS/399673.SZ/000016.SS/000905.SS 在 yfinance 上不可用
    # === 日本 ===
    "^N225":  ("日经225", "JP", "index"),
    # ^TPX (TOPIX) 在 yfinance 上不可用，用 EWJ (US.MSCI Japan ETF) 替代
    # === 韩国 ===
    "^KS11":  ("KOSPI 综合指数", "KR", "index"),
    "^KQ11":  ("KOSDAQ 指数", "KR", "index"),
    # === 台湾 ===
    "^TWII":  ("台湾加权指数", "TW", "index"),
    # === 印度 ===
    "^BSESN": ("印度 SENSEX 30", "IN", "index"),
    "^NSEI":  ("印度 Nifty 50", "IN", "index"),
    # === 欧洲 ===
    "^FTSE":  ("富时100 (英国)", "EU", "index"),
    "^GDAXI": ("德国 DAX", "EU", "index"),
    "^FCHI":  ("法国 CAC 40", "EU", "index"),
    "^STOXX50E": ("欧洲斯托克50", "EU", "index"),
    # === 亚太 ===
    "^AXJO":  ("澳大利亚 ASX 200", "AP", "index"),
    "^STI":   ("新加坡海峡时报指数", "AP", "index"),
    "^KLSE":  ("马来西亚 KLCI", "AP", "index"),
    "^JKSE":  ("印尼雅加达综合", "AP", "index"),
    "VNM":    ("VanEck 越南 ETF", "AP", "etf"),
}


def get_db():
    """Get SQLite connection."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")  # bulk insert perf
    return conn


def init_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS indices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            market TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'index'
        );
        CREATE TABLE IF NOT EXISTS daily_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            index_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            FOREIGN KEY (index_id) REFERENCES indices(id) ON DELETE CASCADE,
            UNIQUE(index_id, date)
        );
        CREATE TABLE IF NOT EXISTS update_log (
            ticker TEXT PRIMARY KEY,
            last_date TEXT,
            rows INTEGER,
            updated_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_daily_index_date ON daily_data(index_id, date);
    """)
    conn.commit()


def seed_indices(conn):
    """Populate the indices table from registry."""
    cur = conn.execute("SELECT ticker FROM indices")
    existing = {row[0] for row in cur.fetchall()}
    inserted = 0
    for ticker, (name, market, cat) in INDICES.items():
        if ticker not in existing:
            conn.execute(
                "INSERT OR IGNORE INTO indices (ticker, name, market, category) VALUES (?, ?, ?, ?)",
                (ticker, name, market, cat),
            )
            inserted += 1
    if inserted:
        conn.commit()
        print(f"  新增 {inserted} 个指数到注册表")
    return len(INDICES)


def download_index(conn, ticker, force_all=False):
    """Download daily data for one index and insert into DB. Incremental."""
    # Find index_id
    cur = conn.execute("SELECT id, name, market FROM indices WHERE ticker = ?", (ticker,))
    row = cur.fetchone()
    if not row:
        print(f"  [WARN] {ticker}: 未在注册表中")
        return 0
    idx_id, name, market = row

    # Determine start date (yfinance 限制最大 100 年)
    _MAX_YEARS_BACK = 100
    _EARLIEST = (datetime.now() - timedelta(days=_MAX_YEARS_BACK * 365.25)).strftime("%Y-%m-%d")

    if force_all:
        start = _EARLIEST
    else:
        cur = conn.execute("SELECT MAX(date) FROM daily_data WHERE index_id = ?", (idx_id,))
        max_date = cur.fetchone()[0]
        if max_date:
            start = (datetime.strptime(max_date, "%Y-%m-%d") - timedelta(days=5)).strftime("%Y-%m-%d")
        else:
            start = _EARLIEST

    # If recent data exists, skip
    if not force_all and start >= (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"):
        return 0  # up to date

    # Download
    try:
        t = yf.Ticker(ticker)
        hist = t.history(start=start)
    except Exception as e:
        print(f"  [ERR] {ticker}: 下载失败 - {str(e)[:80]}")
        return 0

    if hist.empty:
        # Try period="max" as fallback
        try:
            hist = t.history(period="max")
        except Exception:
            pass

    if hist.empty:
        print(f"  [WARN] {ticker}: 无数据 ({name})")
        return 0

    # Filter to new rows only
    existing_dates = set()
    for d_row in conn.execute("SELECT date FROM daily_data WHERE index_id = ?", (idx_id,)).fetchall():
        existing_dates.add(d_row[0])

    new_rows = []
    for dt_idx, row_data in hist.iterrows():
        date_str = dt_idx.strftime("%Y-%m-%d") if hasattr(dt_idx, "strftime") else str(dt_idx)[:10]
        if date_str not in existing_dates:
            new_rows.append((
                idx_id, date_str,
                _v(row_data.get("Open")), _v(row_data.get("High")),
                _v(row_data.get("Low")), _v(row_data.get("Close")),
                _v(row_data.get("Volume")),
            ))

    if not new_rows:
        return 0

    # Batch insert
    conn.executemany(
        "INSERT OR IGNORE INTO daily_data (index_id, date, open, high, low, close, volume) VALUES (?,?,?,?,?,?,?)",
        new_rows,
    )
    conn.commit()

    # Update log
    last = new_rows[-1][1]
    conn.execute(
        "INSERT OR REPLACE INTO update_log (ticker, last_date, rows, updated_at) VALUES (?, ?, ?, ?)",
        (ticker, last, len(new_rows), datetime.now().isoformat()),
    )
    conn.commit()

    print(f"  [OK] {ticker}: +{len(new_rows)} rows -> {last} ({name})")
    return len(new_rows)


def _v(val):
    """Safely extract float, return None if invalid."""
    if val is None:
        return None
    try:
        fv = float(val)
        if fv != fv:  # nan
            return None
        return fv
    except (ValueError, TypeError):
        return None


# ─── CLI Commands ────────────────────────────────────────────────────────────


def cmd_build():
    """Full build: download all indices."""
    conn = get_db()
    init_schema(conn)
    total = seed_indices(conn)
    print(f"\n索引注册表: {total} 个指数\n开始下载...\n")

    total_rows = 0
    for ticker in sorted(INDICES):
        rows = download_index(conn, ticker, force_all=True)
        total_rows += rows
        time.sleep(0.5)  # rate limit

    conn.close()
    print(f"\n完成: 共下载 {total_rows} 条日线数据，{len(INDICES)} 个指数")


def cmd_reset():
    """Delete database and rebuild from scratch."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"已删除旧数据库: {DB_PATH}")
    cmd_build()


def cmd_update():
    """Incremental update: only new data."""
    conn = get_db()
    init_schema(conn)
    total = seed_indices(conn)
    print(f"增量更新 {total} 个指数...\n")

    total_rows = 0
    for ticker in INDICES:
        rows = download_index(conn, ticker, force_all=False)
        total_rows += rows
        if rows:
            time.sleep(0.5)

    conn.close()
    if total_rows == 0:
        print("  所有指数已是最新，无需更新")
    else:
        print(f"\n新增 {total_rows} 条数据")


def cmd_list():
    conn = get_db()
    cur = conn.execute("""
        SELECT i.ticker, i.name, i.market, i.category,
               COUNT(d.id) as rows, MAX(d.date) as last, MIN(d.date) as first
        FROM indices i
        LEFT JOIN daily_data d ON d.index_id = i.id
        GROUP BY i.id
        ORDER BY i.market, i.ticker
    """)
    rows = cur.fetchall()
    conn.close()
    if not rows:
        print("数据库为空。请先运行: python fengindexdb.py build")
        return
    print(f"{'Ticker':<14} {'名称':<24} {'市场':<6} {'类型':<6} {'行数':<8} {'起始':<12} {'最新':<12}")
    print("-" * 82)
    for r in rows:
        ticker, name, market, cat, cnt, last, first = r
        cnt_str = str(cnt) if cnt else "-"
        first_str = first or "-"
        last_str = last or "-"
        print(f"{ticker:<14} {name:<24} {market:<6} {cat:<6} {cnt_str:<8} {first_str:<12} {last_str:<12}")
    total = sum(r[4] for r in rows if r[4])
    print(f"\n总计: {len(rows)} 个指数, {total} 条日线数据")


def cmd_info(ticker):
    conn = get_db()
    # Check in registry
    cur = conn.execute("SELECT id, name, market, category FROM indices WHERE ticker = ?", (ticker.upper(),))
    row = cur.fetchone()
    if not row:
        print(f"[ERR] {ticker}: 未在注册表中")
        conn.close()
        return
    idx_id, name, market, cat = row
    cur = conn.execute("""
        SELECT COUNT(*), MIN(date), MAX(date),
               MIN(close), MAX(close),
               AVG(close)
        FROM daily_data WHERE index_id = ?
    """, (idx_id,))
    cnt, first, last, min_c, max_c, avg_c = cur.fetchone()
    print(f"{ticker} — {name} ({market}/{cat})")
    print(f"  数据: {cnt} 行, {first} ~ {last}")
    if cnt and cnt > 0:
        print(f"  收盘: {min_c:.0f} ~ {max_c:.0f} (均值 {avg_c:.0f})")
    conn.close()


def cmd_export(ticker):
    conn = get_db()
    cur = conn.execute("SELECT id, name FROM indices WHERE ticker = ?", (ticker.upper(),))
    row = cur.fetchone()
    if not row:
        print(f"[ERR] {ticker}: 不存在")
        conn.close()
        return
    idx_id, name = row
    cur = conn.execute(
        "SELECT date, open, high, low, close, volume FROM daily_data WHERE index_id = ? ORDER BY date",
        (idx_id,),
    )
    rows = cur.fetchall()
    conn.close()
    data = [{"date": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]} for r in rows]
    out = {"ticker": ticker.upper(), "name": name, "count": len(data), "data": data}
    print(json.dumps(out, indent=2, default=str))


def cmd_summary():
    """Per-market summary stats."""
    conn = get_db()
    cur = conn.execute("""
        SELECT i.market,
               COUNT(DISTINCT i.id) as indices,
               COUNT(d.id) as rows,
               MIN(d.date) as first,
               MAX(d.date) as last
        FROM indices i
        LEFT JOIN daily_data d ON d.index_id = i.id
        GROUP BY i.market
        ORDER BY i.market
    """)
    rows = cur.fetchall()
    conn.close()
    print(f"{'市场':<6} {'指数数':<8} {'数据行':<10} {'起始':<12} {'最新':<12}")
    print("-" * 48)
    total_indices = total_rows = 0
    for r in rows:
        print(f"{r[0]:<6} {r[1]:<8} {r[2]:<10} {r[3] or '-':<12} {r[4] or '-':<12}")
        total_indices += r[1]
        total_rows += r[2]
    print(f"\n总计 {total_indices} 个指数, {total_rows} 行数据")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "build":
        cmd_build()
    elif cmd == "reset":
        cmd_reset()
    elif cmd == "update":
        cmd_update()
    elif cmd == "list":
        cmd_list()
    elif cmd == "summary":
        cmd_summary()
    elif cmd == "info" and len(sys.argv) >= 3:
        cmd_info(sys.argv[2])
    elif cmd == "export" and len(sys.argv) >= 3:
        cmd_export(sys.argv[2])
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
