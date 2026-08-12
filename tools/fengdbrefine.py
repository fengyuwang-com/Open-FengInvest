#!/usr/bin/env python3
"""fengdbrefine.py — 回填 US/CN/HK 核心市场: unadj_close + dividends

策略: 逐个下载 auto_adjust=False，提取 Close→unadj_close, Dividends→dividends 表。
使用全局 session+UA 轮换防限流，串行处理+延迟。

用法:
    python tools/fengdbrefine.py              # 全量回填
    python tools/fengdbrefine.py --status     # 查看进度
    python tools/fengdbrefine.py --verify     # 随机抽检一致性
    python tools/fengdbrefine.py --retry      # 只重试失败的
"""
import json, os, random, sqlite3, sys, time
from datetime import datetime

random.seed(20260722)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "data", "market_data.db")
CHECKPOINT = os.path.join(BASE, "data", ".refine_checkpoint.json")
CORE_MARKETS = ["US", "CN", "HK"]
REQ_DELAY = 5.0
FAIL_DELAY = 30.0
RETRY_MAX = 5

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ── 全局 session（可选 Clash 代理） ──
_YF_SESSION = None
_CLASH_PROXY = None

def _try_clash_proxy():
    """检测 Clash 是否运行，返回代理 dict 或 None"""
    import urllib.request, json as j
    try:
        req = urllib.request.Request("http://127.0.0.1:9097/proxies")
        req.add_header("Authorization", "Bearer set-your-secret")
        with urllib.request.urlopen(req, timeout=1.5) as r:
            r.read()
        log("🔌 Clash 代理已检测到 (127.0.0.1:7897)")
        return {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}
    except Exception:
        return None

def _get_session(use_proxy=False):
    global _YF_SESSION, _CLASH_PROXY
    import requests
    if _YF_SESSION is None:
        _YF_SESSION = requests.Session()
        if use_proxy:
            _CLASH_PROXY = _try_clash_proxy()
            if _CLASH_PROXY:
                _YF_SESSION.proxies.update(_CLASH_PROXY)
                log("  → yfinance 通过 Clash 代理")
            else:
                log("  → Clash 未运行，直连")
    uas = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    ]
    _YF_SESSION.headers["User-Agent"] = random.choice(uas)
    return _YF_SESSION

# ── 获取股票列表 ──
def get_stocks(conn):
    return conn.execute(
        "SELECT id, ticker, name, market FROM indices "
        "WHERE category='stock' AND market IN (?,?,?) "
        "ORDER BY CASE market WHEN 'US' THEN 0 WHEN 'HK' THEN 1 ELSE 2 END, id",
        CORE_MARKETS
    ).fetchall()

def stock_row_count(conn, idx_id):
    return conn.execute("SELECT COUNT(*) FROM daily_data WHERE index_id=?", (idx_id,)).fetchone()[0]

# ── 进度统计 ──
def show_status():
    conn = sqlite3.connect(DB_PATH)
    log("  市场  总数  有数据  有unadj  有dividends")
    for mkt in CORE_MARKETS:
        total = conn.execute("SELECT COUNT(*) FROM indices WHERE category='stock' AND market=?", (mkt,)).fetchone()[0]
        has_data = conn.execute("SELECT COUNT(DISTINCT index_id) FROM daily_data dd JOIN indices i ON dd.index_id=i.id WHERE i.market=?", (mkt,)).fetchone()[0]
        unadj = conn.execute("SELECT COUNT(DISTINCT dd.index_id) FROM daily_data dd JOIN indices i ON dd.index_id=i.id WHERE i.market=? AND dd.unadj_close IS NOT NULL", (mkt,)).fetchone()[0]
        divs = conn.execute("SELECT COUNT(DISTINCT d.index_id) FROM dividends d JOIN indices i ON d.index_id=i.id WHERE i.market=?", (mkt,)).fetchone()[0]
        log(f"  {mkt:4s}  {total:4d}   {has_data:4d}     {unadj:4d}        {divs:4d}")
    conn.close()
    if os.path.exists(CHECKPOINT):
        with open(CHECKPOINT, encoding="utf-8") as f:
            cp = json.load(f)
        log(f"检查点: 已完成 {len(cp.get('done',[]))} 只, unadj更新 {cp.get('progress',{}).get('updated',0)} 行, div新增 {cp.get('progress',{}).get('divs_added',0)} 条")

# ── 核心下载 ──
_PROXY_MODE = False  # 全局代理开关

def download_one(ticker):
    import yfinance as yf
    import pandas as pd
    try:
        s = _get_session(use_proxy=_PROXY_MODE)
        t = yf.Ticker(ticker, session=s)
        hist = t.history(period="max", auto_adjust=False)
    except Exception:
        return None
    if hist.empty:
        return None
    unadj, divs = [], []
    for dt_idx, r in hist.iterrows():
        d = dt_idx.strftime("%Y-%m-%d") if hasattr(dt_idx, "strftime") else str(dt_idx)[:10]
        close_raw = r["Close"]
        if not pd.isna(close_raw):
            unadj.append((d, float(close_raw)))
        if "Dividends" in r:
            div_amt = r["Dividends"]
            if not pd.isna(div_amt) and float(div_amt) > 0:
                divs.append((d, float(div_amt)))
    return unadj, divs

# ── 处理一只股票 ──
def process_one(conn, idx_id, ticker, name, market, progress):
    row_count = stock_row_count(conn, idx_id)
    if row_count == 0:
        progress["no_data"] += 1
        return "no_data"

    already = conn.execute(
        "SELECT COUNT(*) FROM daily_data WHERE index_id=? AND unadj_close IS NOT NULL",
        (idx_id,)
    ).fetchone()[0] > 0
    has_divs = conn.execute(
        "SELECT COUNT(*) FROM dividends WHERE index_id=?", (idx_id,)
    ).fetchone()[0] > 0
    if already and has_divs:
        progress["skipped"] += 1
        return "skipped"

    result = None
    for attempt in range(RETRY_MAX):
        try:
            result = download_one(ticker)
            if result is not None:
                break
        except Exception:
            pass
        if attempt < RETRY_MAX - 1:
            time.sleep(FAIL_DELAY)

    if result is None:
        progress["failed"] += 1
        return False

    unadj, divs = result
    if not unadj and not divs:
        progress["failed"] += 1
        return False

    updated = 0
    for d, val in unadj:
        cur = conn.execute(
            "UPDATE daily_data SET unadj_close=? WHERE index_id=? AND date=?",
            (val, idx_id, d)
        )
        updated += cur.rowcount
    progress["updated"] += updated

    for d, amt in divs:
        conn.execute(
            "INSERT OR IGNORE INTO dividends (index_id, ex_date, dividend) VALUES (?, ?, ?)",
            (idx_id, d, amt)
        )
    progress["divs_added"] += len(divs)
    conn.commit()
    progress["done"] += 1
    return True

# ── 主循环 ──
def main():
    conn = sqlite3.connect(DB_PATH)
    stocks = get_stocks(conn)
    total = len(stocks)
    us_c = sum(1 for s in stocks if s[3] == "US")
    cn_c = sum(1 for s in stocks if s[3] == "CN")
    hk_c = sum(1 for s in stocks if s[3] == "HK")
    log(f"需处理 {total} 只 (US={us_c}, HK={hk_c}, CN={cn_c})")

    progress = {"done": 0, "updated": 0, "divs_added": 0,
                "skipped": 0, "failed": 0, "no_data": 0}
    done_set = set()
    failed_set = set()
    nodata_set = set()

    if os.path.exists(CHECKPOINT):
        with open(CHECKPOINT, encoding="utf-8") as f:
            cp = json.load(f)
        done_set = set(cp.get("done", []))
        failed_set = set(cp.get("failed", []))
        nodata_set = set(cp.get("nodata", []))
        progress = cp.get("progress", progress)
        log(f"从检查点恢复: 完成={len(done_set)} 失败={len(failed_set)} 无数据={len(nodata_set)}")

    all_done = done_set | failed_set | nodata_set
    pending = [s for s in stocks if s[1] not in all_done]
    retry_failed = [s for s in stocks if s[1] in failed_set]
    if retry_failed and "--retry" in sys.argv:
        pending = retry_failed + pending
        failed_set.clear()
        log(f"重试模式: {len(retry_failed)} 只失败的股票")
    elif retry_failed:
        log(f"跳过 {len(retry_failed)} 只失败股票 (用 --retry 重试)")

    log(f"本次需处理 {len(pending)} 只")

    # 自适应限流
    consecutive_fails = 0
    current_delay = REQ_DELAY

    for i, (idx_id, ticker, name, market) in enumerate(pending):
        result = process_one(conn, idx_id, ticker, name, market, progress)

        if result == "no_data":
            nodata_set.add(ticker)
            status = "nodata"
            consecutive_fails = 0
        elif result == "skipped":
            done_set.add(ticker)
            status = "skipped"
            consecutive_fails = 0
        elif result:
            done_set.add(ticker)
            status = "ok"
            consecutive_fails = 0
            # 连续成功后逐渐降低延迟
            if current_delay > REQ_DELAY and consecutive_fails == 0:
                current_delay = max(REQ_DELAY, current_delay * 0.8)
        else:
            failed_set.add(ticker)
            status = "FAIL"
            consecutive_fails += 1
            # 连续失败 → 增加延迟
            if consecutive_fails >= 3:
                current_delay = min(current_delay * 1.5, 30.0)
                log(f"  ⚠️  连续 {consecutive_fails} 次失败, 延迟提高到 {current_delay:.0f}s")

        # 每 5 只写 checkpoint 并打印进度
        if (i + 1) % 5 == 0 or i == len(pending) - 1 or status == "FAIL":
            cp = {"done": list(done_set), "failed": list(failed_set),
                  "nodata": list(nodata_set), "progress": progress}
            with open(CHECKPOINT, "w", encoding="utf-8") as f:
                json.dump(cp, f)
            processed = len(done_set) + len(failed_set) + len(nodata_set)
            pct = processed / total * 100 if total else 0
            log(f"[{processed}/{total} {pct:.0f}%] {ticker:16s} | {name[:20]:20s} | {market:2s} | {status:7s} | "
                f"unadj={progress['updated']} | divs={progress['divs_added']} | fail={progress['failed']} | nodata={progress['no_data']}")

        # 限流延迟（自适应）
        time.sleep(current_delay + random.uniform(0, 1.0))

    with open(CHECKPOINT, "w", encoding="utf-8") as f:
        json.dump({"done": list(done_set), "failed": list(failed_set),
                   "nodata": list(nodata_set), "progress": progress}, f)

    log(f"\n完成!")
    log(f"  成功: {len(done_set)} / 失败: {len(failed_set)} / 无数据: {len(nodata_set)} / 跳过: {progress['skipped']}")
    log(f"  unadj_close: {progress['updated']} 行 | dividends: {progress['divs_added']} 条")
    show_status()
    conn.close()

# ── 抽检 ──
def verify_random():
    import yfinance as yf, pandas as pd
    conn = sqlite3.connect(DB_PATH)
    stocks = get_stocks(conn)
    sample = random.sample(stocks, min(5, len(stocks)))
    log(f"抽检 {len(sample)} 只 (adj_close vs DB close 一致性)...")
    for idx_id, ticker, name, market in sample:
        try:
            s = _get_session()
            t = yf.Ticker(ticker, session=s)
            hist = t.history(period="1y", auto_adjust=False)
            if hist.empty:
                log(f"  {ticker}: 无数据")
                continue
            db_rows = {r[0]: r[1] for r in conn.execute(
                "SELECT date, close FROM daily_data WHERE index_id=? ORDER BY date DESC LIMIT 252", (idx_id,)).fetchall()}
            mismatches = 0
            for dt_idx, r in hist.iterrows():
                d = dt_idx.strftime("%Y-%m-%d")
                adj_close = r.get("Adj Close")
                if adj_close is not None and not pd.isna(adj_close):
                    adj_close = float(adj_close)
                    if d in db_rows and db_rows[d] is not None and db_rows[d] > 0:
                        if abs(adj_close - db_rows[d]) / db_rows[d] > 0.001:
                            mismatches += 1
            log(f"  {ticker:16s} | adj_close OK, mismatch={mismatches}/{len(hist)}")
            time.sleep(REQ_DELAY)
        except Exception as e:
            log(f"  {ticker}: {e}")
    conn.close()

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding='utf-8')
    if "--proxy" in sys.argv:
        _PROXY_MODE = True
    if "--status" in sys.argv:
        show_status()
    elif "--verify" in sys.argv:
        verify_random()
    else:
        main()
