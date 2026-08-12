#!/usr/bin/env python3
"""fill_hk_gaps.py — 回填 HK 12只股票缺失的 unadj_close + dividends

这些股票通过 fix_hk_nodata.py（AKShare）拉过 daily_data，
但当时没跑 unadj_close 和 dividends。他们的 close 已经是原始不复权价，
所以 unadj_close = close。分红通过 AKShare 的 stock_hk_dividend_payout_em 拿。

用法:
    python tools/fill_hk_gaps.py            # 全量回填
    python tools/fill_hk_gaps.py --status   # 查看进度
"""
import sqlite3, os, sys, json
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "data", "market_data.db")
# AKShare 装在 venv-numpy2（默认取当前用户 AppData；可用 AK_PYTHON 环境变量覆盖）
AK_PYTHON = os.environ.get(
    "AK_PYTHON",
    os.path.join(os.path.expanduser("~"), "AppData", "Local", "com.fincept.terminal", "venv-numpy2", "Scripts", "python.exe"),
)

HK_TICKERS = ["0700.HK","0388.HK","0941.HK","1299.HK","1810.HK",
              "0981.HK","1876.HK","2269.HK","0285.HK","2319.HK",
              "2331.HK","2359.HK"]

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def update_unadj_from_close(conn):
    """这些股票的 close 已经是原始不复权价，close→unadj_close"""
    updated = 0
    for ticker in HK_TICKERS:
        idx = conn.execute("SELECT id FROM indices WHERE ticker=?", (ticker,)).fetchone()
        if not idx:
            log(f"  {ticker}: 不在 indices 表中")
            continue
        idx_id = idx[0]
        cur = conn.execute("""
            UPDATE daily_data SET unadj_close = close
            WHERE index_id=? AND unadj_close IS NULL AND close IS NOT NULL
        """, (idx_id,))
        updated += cur.rowcount
        log(f"  {ticker}: unadj_close 更新 {cur.rowcount} 行")
    return updated

def fetch_dividends_akshare():
    """通过 AKShare 拉取港股分红数据，返回 {ticker: [(ex_date, dividend), ...]}"""
    import subprocess, tempfile, json
    code_map = {
        "0700.HK":"00700","0388.HK":"00388","0941.HK":"00941",
        "1299.HK":"01299","1810.HK":"01810","0981.HK":"00981",
        "1876.HK":"01876","2269.HK":"02269","0285.HK":"00285",
        "2319.HK":"02319","2331.HK":"02331","2359.HK":"02359"
    }
    result = {}
    for ticker, code in code_map.items():
        script = f"""
import akshare as ak, json, sys
try:
    df = ak.stock_hk_dividend_payout_em(symbol='{code}')
    records = []
    for _, r in df.iterrows():
        ex_date = str(r.get('除净日', ''))[:10]
        plan = str(r.get('分红方案', ''))
        div_amt = 0.0
        import re
        m = re.search(r'相当于每股派.*?([\d.]+)\s*(?:港币|港元|元)', plan)
        if not m:
            m = re.search(r'每股(?:派|分派).*?([\d.]+)\s*(?:港币|港元|元)', plan)
        if m:
            div_amt = float(m.group(1))
        if ex_date and div_amt > 0:
            records.append([ex_date, div_amt])
    print(json.dumps(records))
except Exception as e:
    print(json.dumps({{"error": str(e)}}))
"""
        fp = tempfile.mktemp(suffix=".py")
        with open(fp, "w", encoding="utf-8") as f:
            f.write(script)
        try:
            out = subprocess.check_output([AK_PYTHON, fp], stderr=subprocess.PIPE, text=True, timeout=30)
            data = json.loads(out.strip())
            if isinstance(data, dict) and "error" in data:
                log(f"  {ticker}: AKShare error: {data['error']}")
                result[ticker] = []
            else:
                result[ticker] = data
                log(f"  {ticker}: 获取 {len(data)} 条分红记录")
        except Exception as e:
            log(f"  {ticker}: 失败 {e}")
            result[ticker] = []
        finally:
            os.unlink(fp)
    return result

def insert_dividends(conn, dividend_data):
    total = 0
    for ticker, divs in dividend_data.items():
        idx = conn.execute("SELECT id FROM indices WHERE ticker=?", (ticker,)).fetchone()
        if not idx:
            continue
        idx_id = idx[0]
        count = 0
        for ex_date, amt in divs:
            cur = conn.execute(
                "INSERT OR IGNORE INTO dividends (index_id, ex_date, dividend) VALUES (?,?,?)",
                (idx_id, ex_date, amt)
            )
            count += cur.rowcount
        total += count
        if count:
            log(f"  {ticker}: 新增 {count} 条分红")
    return total

def show_status():
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM indices WHERE market='HK' AND category='stock'").fetchone()[0]
    has_unadj = conn.execute("""
        SELECT COUNT(DISTINCT i.id) FROM indices i
        JOIN daily_data d ON d.index_id=i.id
        WHERE i.market='HK' AND i.category='stock' AND d.unadj_close IS NOT NULL
    """).fetchone()[0]
    has_divs = conn.execute("""
        SELECT COUNT(DISTINCT i.id) FROM indices i
        JOIN dividends d ON d.index_id=i.id
        WHERE i.market='HK' AND i.category='stock'
    """).fetchone()[0]
    log(f"HK 股票: {total} 只 | unadj_close: {has_unadj}/{total} | 分红: {has_divs}/{total}")
    conn.close()

def main():
    conn = sqlite3.connect(DB_PATH)

    # 1. 回填 unadj_close
    log("Step 1: close → unadj_close")
    updated = update_unadj_from_close(conn)
    conn.commit()
    log(f"  unadj_close 共更新 {updated} 行")

    # 2. 拉分红数据
    log("\nStep 2: 拉取 AKShare 港股分红数据")
    div_data = fetch_dividends_akshare()

    # 3. 写入 dividends 表
    log("\nStep 3: 写入 dividends 表")
    added = insert_dividends(conn, div_data)
    conn.commit()
    log(f"  共新增 {added} 条分红记录")

    log("\n完成！")
    show_status()
    conn.close()

if __name__ == "__main__":
    if "--status" in sys.argv:
        show_status()
    else:
        sys.stdout.reconfigure(encoding='utf-8')
        main()
