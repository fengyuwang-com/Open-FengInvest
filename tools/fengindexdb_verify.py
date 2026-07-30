#!/usr/bin/env python3
"""验证 market_data.db 的数据准确性。

从数据库中随机抽取数个指数/ETF，与独立数据源（Futu API、yfinance）交叉核对。
"""
import json, os, random, sqlite3, sys, re
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "market_data.db")

random.seed(20260721)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def sample_indices(conn):
    """优先选 Futu 支持的标的，不够则随机补."""
    futu_friendly = ["SPY","QQQ","GLD","FXI","ASHR", "3033.HK","^HSI","000001.SS","399001.SZ"]
    placeholders = ",".join("?" for _ in futu_friendly)
    cur = conn.execute(f"""
        SELECT i.ticker, i.name, i.market, COUNT(d.id) as cnt
        FROM indices i
        JOIN daily_data d ON d.index_id = i.id
        WHERE i.ticker IN ({placeholders})
        GROUP BY i.id HAVING cnt > 100
        ORDER BY RANDOM() LIMIT 5
    """, futu_friendly)
    rows = list(cur.fetchall())

    if len(rows) < 5:
        used = {r["ticker"] for r in rows}
        excl = ",".join(f"'{t}'" for t in used) if used else "'__nonexist__'"
        cur2 = conn.execute(f"""
            SELECT i.ticker, i.name, i.market, COUNT(d.id) as cnt
            FROM indices i JOIN daily_data d ON d.index_id = i.id
            WHERE i.ticker NOT IN ({excl})
            GROUP BY i.id HAVING cnt > 100
            ORDER BY RANDOM() LIMIT {5 - len(rows)}
        """)
        rows.extend(cur2.fetchall())
    return rows


def get_db_latest(conn, ticker, days=10):
    cur = conn.execute("""
        SELECT d.date, d.open, d.high, d.low, d.close, d.volume
        FROM daily_data d JOIN indices i ON d.index_id = i.id
        WHERE i.ticker = ? ORDER BY d.date DESC LIMIT ?
    """, (ticker, days))
    rows = cur.fetchall()
    rows.reverse()
    return rows


def to_futu_code(ticker):
    t = ticker.upper().strip()
    if re.match(r'^(US|HK|SH|SZ)\.', t):
        return t
    m = re.match(r'^(\d+)\.HK$', t)
    if m:
        return f"HK.{m.group(1).zfill(5)}"
    m = re.match(r'^(\d+)\.SS$', t)
    if m:
        return f"SH.{m.group(1)}"
    m = re.match(r'^(\d+)\.SZ$', t)
    if m:
        return f"SZ.{m.group(1)}"
    if re.match(r'^[A-Z]', t):
        return f"US.{t}"
    return t


def fetch_from_futu(ticker, days=10):
    try:
        from futu import OpenQuoteContext, RET_OK, KLType, AuType
    except ImportError:
        return None, "futu not installed"
    code = to_futu_code(ticker)
    ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
    try:
        ret, klines, _ = ctx.request_history_kline(
            code, ktype=KLType.K_DAY, autype=AuType.QFQ, max_count=300)
        ctx.close()
        if ret != RET_OK or klines is None or klines.empty:
            return None, f"Futu empty: {code}"
        rows = []
        for _, r in klines.iterrows():
            rows.append({
                "date": str(r.get("time_key", ""))[:10],
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r.get("volume", 0)),
            })
        return rows[-days:], None
    except Exception as e:
        try: ctx.close()
        except: pass
        return None, f"Futu err: {str(e)[:80]}"


def fetch_from_yfinance(ticker, days=10):
    try:
        import yfinance as yf
    except ImportError:
        return None, "yfinance not installed"
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="1mo")
        if hist.empty:
            return None, "yf empty"
        rows = []
        for dt_idx, r in hist.iterrows():
            date_str = dt_idx.strftime("%Y-%m-%d") if hasattr(dt_idx, "strftime") else str(dt_idx)[:10]
            rows.append({
                "date": date_str,
                "open": float(r.get("Open", 0)),
                "high": float(r.get("High", 0)),
                "low": float(r.get("Low", 0)),
                "close": float(r.get("Close", 0)),
                "volume": float(r.get("Volume", 0)),
            })
        return rows[-days:], None
    except Exception as e:
        return None, f"yf err: {str(e)[:80]}"


def compare(db_rows, src_rows, src_name):
    if not db_rows or not src_rows:
        return None
    db_by_date = {r["date"]: r for r in db_rows}
    src_by_date = {r["date"]: r for r in src_rows}
    common = sorted(set(db_by_date.keys()) & set(src_by_date.keys()))
    if not common:
        return None
    details = []
    for d in common:
        db_r, src_r = db_by_date[d], src_by_date[d]
        close_err = abs(db_r["close"] - src_r["close"]) / max(src_r["close"], 0.001) * 100
        details.append({
            "date": d,
            "db_close": round(db_r["close"], 4),
            f"{src_name}_close": round(src_r["close"], 4),
            "close_diff_pct": round(close_err, 4),
        })
    max_err = max(d["close_diff_pct"] for d in details)
    avg_err = sum(d["close_diff_pct"] for d in details) / len(details)
    return {
        "common_dates": len(common),
        "max_close_diff_pct": max_err,
        "avg_close_diff_pct": round(avg_err, 4),
        "details": details,
    }


def main():
    conn = get_db()
    samples = sample_indices(conn)
    print(f"随机抽取 {len(samples)} 个标的验证（优先 Futu 支持）\n")

    all_ok = True
    for s in samples:
        ticker, name, market, cnt = s["ticker"], s["name"], s["market"], s["cnt"]
        header = f" {ticker} — {name} ({market}, {cnt} rows) "
        print(header)
        print("=" * len(header))

        db_rows_raw = get_db_latest(conn, ticker, days=10)
        if not db_rows_raw:
            print("  DB: 无数据\n")
            continue
        db_rows = [dict(r) for r in db_rows_raw]

        # yfinance cross-check (always available)
        yf_data, yf_err = fetch_from_yfinance(ticker, days=10)
        if yf_data:
            r = compare(db_rows, yf_data, "yf")
            if r:
                status = "OK" if r["max_close_diff_pct"] < 1.0 else "MISMATCH"
                if status == "MISMATCH":
                    all_ok = False
                print(f"  [yfinance] {status}: {r['common_dates']} dates, "
                      f"max close diff={r['max_close_diff_pct']:.4f}%, "
                      f"avg={r['avg_close_diff_pct']:.4f}%")
                for e in r["details"]:
                    if e["close_diff_pct"] > 0.5:
                        print(f"    {e['date']}: DB={e['db_close']} yf={e['yf_close']} "
                              f"diff={e['close_diff_pct']:.4f}% ***")
            else:
                print("  [yfinance] no overlapping dates")
        else:
            print(f"  [yfinance] unavailable: {yf_err}")

        # Futu cross-check
        futu_data, futu_err = fetch_from_futu(ticker, days=10)
        if futu_data:
            r = compare(db_rows, futu_data, "futu")
            if r:
                status = "OK" if r["max_close_diff_pct"] < 1.0 else "MISMATCH"
                if status == "MISMATCH":
                    all_ok = False
                print(f"  [Futu]     {status}: {r['common_dates']} dates, "
                      f"max close diff={r['max_close_diff_pct']:.4f}%, "
                      f"avg={r['avg_close_diff_pct']:.4f}%")
                for e in r["details"]:
                    if e["close_diff_pct"] > 0.5:
                        print(f"    {e['date']}: DB={e['db_close']} futu={e['futu_close']} "
                              f"diff={e['close_diff_pct']:.4f}% ***")
            else:
                print("  [Futu]     no overlapping dates")
        else:
            print(f"  [Futu]     unavailable: {futu_err}")

        print()

    conn.close()
    print("结论: 全部验证通过" if all_ok else "结论: 发现差异，需检查")


if __name__ == "__main__":
    main()
