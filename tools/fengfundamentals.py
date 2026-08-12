#!/usr/bin/env python3
"""fengfundamentals.py — 批量拉取 US/CN/HK 基本面数据到 fundamentals 表

通过 yfinance info 获取估值、盈利能力、现金流、财务健康等指标。
使用全局 session + UA 轮换防限流，串行处理 + 自适应延迟。

用法:
    python tools/fengfundamentals.py              # 全量拉取
    python tools/fengfundamentals.py --status     # 查看进度
    python tools/fengfundamentals.py --retry      # 只重试失败的
    python tools/fengfundamentals.py --proxy      # 通过 Clash 代理
    python tools/fengfundamentals.py --market US  # 只拉取指定市场
"""
import json, os, random, socket, sqlite3, sys, time
from datetime import datetime

# ── 确保 yfinance 可用 ──
try:
    import yfinance
except ImportError:
    print("ERROR: yfinance not found. Install with `pip install yfinance` first:", file=sys.stderr)
    sys.exit(1)

random.seed(20260723)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "data", "market_data.db")
CHECKPOINT = os.path.join(BASE, "data", ".fundamentals_checkpoint.json")
TARGET_MARKETS = ["US", "CN", "HK"]
REQ_DELAY = 5.0
FAIL_DELAY = 15.0
RETRY_MAX = 2

_YF_SESSION = None

import urllib.request

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# yfinance info 字段映射
FIELD_MAP = {
    "market_cap": "marketCap",
    "enterprise_value": "enterpriseValue",
    "trailing_pe": "trailingPE",
    "forward_pe": "forwardPE",
    "price_to_book": "priceToBook",
    "price_to_sales": "priceToSalesSales",
    "enterprise_to_ebitda": "enterpriseToEbitda",
    "enterprise_to_revenue": "enterpriseToRevenue",
    "return_on_equity": "returnOnEquity",
    "return_on_assets": "returnOnAssets",
    "profit_margin": "profitMargins",
    "gross_margin": "grossMargins",
    "operating_margin": "operatingMargins",
    "free_cashflow": "freeCashflow",
    "operating_cashflow": "operatingCashflow",
    "capital_expenditure": "capitalExpenditure",
    "debt_to_equity": "debtToEquity",
    "current_ratio": "currentRatio",
    "quick_ratio": "quickRatio",
    "revenue_growth": "revenueGrowth",
    "earnings_growth": "earningsGrowth",
    "dividend_yield": "dividendYield",
    "payout_ratio": "payoutRatio",
    "dividend_rate": "dividendRate",
    "book_value": "bookValue",
    "eps": "trailingEps",
    "sector": "sector",
    "industry": "industry",
    "shares_outstanding": "sharesOutstanding",
}

DB_COLUMNS = [
    "index_id", "updated_at",
    "market_cap", "enterprise_value",
    "trailing_pe", "forward_pe", "price_to_book", "price_to_sales",
    "enterprise_to_ebitda", "enterprise_to_revenue",
    "return_on_equity", "return_on_assets",
    "profit_margin", "gross_margin", "operating_margin",
    "free_cashflow", "operating_cashflow", "capital_expenditure",
    "debt_to_equity", "current_ratio", "quick_ratio",
    "revenue_growth", "earnings_growth",
    "dividend_yield", "payout_ratio", "dividend_rate",
    "book_value", "eps",
    "sector", "industry",
    "shares_outstanding",
]

UPSERT_SQL = (
    "INSERT OR REPLACE INTO fundamentals "
    "(" + ", ".join(DB_COLUMNS) + ") "
    "VALUES (" + ", ".join(["?" for _ in DB_COLUMNS]) + ")"
)

def _get_session(use_proxy=False):
    global _YF_SESSION
    import requests
    if _YF_SESSION is None:
        _YF_SESSION = requests.Session()
        if use_proxy:
            try:
                # Check if Clash proxy port is listening (more reliable than API check)
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1.5)
                s.connect(("127.0.0.1", 7897))
                s.close()
                _YF_SESSION.proxies.update({
                    "http": "http://127.0.0.1:7897",
                    "https": "http://127.0.0.1:7897"
                    })
                log("  -> Clash proxy enabled")
            except Exception:
                log("  -> Clash not running, direct connect")
    uas = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 Version/17.6 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    ]
    _YF_SESSION.headers["User-Agent"] = random.choice(uas)
    return _YF_SESSION

def get_stocks(conn, markets=None):
    if markets is None:
        markets = TARGET_MARKETS
    placeholders = ",".join("?" for _ in markets)
    return conn.execute(
        "SELECT id, ticker, name, market FROM indices "
        "WHERE category='stock' AND market IN (" + placeholders + ") ORDER BY market, id",
        markets
    ).fetchall()

def show_status():
    conn = sqlite3.connect(DB_PATH)
    print(f"  {'Market':4s} {'Total':5s} {'HasFund':7s}")
    for mkt in TARGET_MARKETS:
        total = conn.execute("SELECT COUNT(*) FROM indices WHERE category='stock' AND market=?", (mkt,)).fetchone()[0]
        has_fund = conn.execute(
            "SELECT COUNT(*) FROM fundamentals f JOIN indices i ON f.index_id=i.id WHERE i.market=?", (mkt,)
        ).fetchone()[0]
        print(f"  {mkt:4s} {total:5d} {has_fund:7d}")
    if os.path.exists(CHECKPOINT):
        with open(CHECKPOINT, "r", encoding="utf-8") as f:
            cp = json.load(f)
        log(f"Checkpoint: done={len(cp.get('done',[]))} failed={len(cp.get('failed',[]))} nodata={len(cp.get('nodata',[]))}")
    conn.close()

def extract_info(ticker, use_proxy=False):
    import yfinance as yf
    try:
        s = _get_session(use_proxy=use_proxy)
        s.timeout = (10, 15)  # connect=10s, read=15s
        t = yf.Ticker(ticker, session=s)
        info = t.info
    except Exception:
        return None
    if not info or info.get("regularMarketPrice") is None:
        return None
    return info

def build_row(idx_id, info):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = [idx_id, now]
    for col in DB_COLUMNS[2:]:
        yf_key = FIELD_MAP.get(col)
        if yf_key:
            val = info.get(yf_key)
            if val is None or val == "":
                row.append(None)
            else:
                try:
                    row.append(float(val))
                except (ValueError, TypeError):
                    row.append(str(val) if isinstance(val, str) else None)
        else:
            row.append(None)
    return row

def main():
    use_proxy = "--proxy" in sys.argv
    target_markets = TARGET_MARKETS[:]
    for i, arg in enumerate(sys.argv):
        if arg == "--market" and i + 1 < len(sys.argv):
            target_markets = [sys.argv[i + 1].upper()]
            break

    conn = sqlite3.connect(DB_PATH)
    stocks = get_stocks(conn, target_markets)
    total = len(stocks)
    mkt_counts = {m: sum(1 for s in stocks if s[3] == m) for m in target_markets}
    log(f"Need to process {total} stocks ({', '.join(f'{m}={c}' for m,c in mkt_counts.items())})")

    done_set = set()
    failed_set = set()
    nodata_set = set()
    progress = {"done": 0, "failed": 0, "no_data": 0}

    if os.path.exists(CHECKPOINT):
        with open(CHECKPOINT, "r", encoding="utf-8") as f:
            cp = json.load(f)
        done_set = set(cp.get("done", []))
        failed_set = set(cp.get("failed", []))
        nodata_set = set(cp.get("nodata", []))
        progress = cp.get("progress", progress)
        log(f"Resumed from checkpoint: done={len(done_set)} failed={len(failed_set)} nodata={len(nodata_set)}")

    all_done = done_set | failed_set | nodata_set
    pending = [s for s in stocks if s[1] not in all_done]
    retry_failed = [s for s in stocks if s[1] in failed_set]
    if retry_failed and "--retry" in sys.argv:
        pending = retry_failed + pending
        failed_set.clear()
        log(f"Retry mode: {len(retry_failed)} failed stocks")
    elif retry_failed:
        log(f"Skipping {len(retry_failed)} failed stocks (use --retry to retry)")

    log(f"Processing {len(pending)} stocks this run")
    consecutive_fails = 0
    current_delay = REQ_DELAY

    for i, (idx_id, ticker, name, market) in enumerate(pending):
        log(f"  [{i+1}/{len(pending)}] {ticker} ({market}) ...")
        info = None
        for attempt in range(RETRY_MAX):
            try:
                info = extract_info(ticker, use_proxy=use_proxy)
                if info is not None:
                    break
            except Exception:
                pass
            if attempt < RETRY_MAX - 1:
                time.sleep(FAIL_DELAY)

        if info is None:
            nodata_set.add(ticker)
            progress["no_data"] += 1
            status = "nodata"
            consecutive_fails = 0
            log(f"    -> nodata")
        else:
            try:
                row = build_row(idx_id, info)
                conn.execute(UPSERT_SQL, row)
                conn.commit()
                done_set.add(ticker)
                progress["done"] += 1
                status = "ok"
                consecutive_fails = 0
                pe = info.get("trailingPE", "N/A")
                pb = info.get("priceToBook", "N/A")
                mcap = info.get("marketCap", "N/A")
                if mcap != "N/A":
                    mcap = f"{mcap/1e9:.1f}B"
                log(f"    -> PE={pe} PB={pb} MktCap={mcap}")
            except Exception as e:
                failed_set.add(ticker)
                progress["failed"] += 1
                status = "FAIL"
                consecutive_fails += 1
                log(f"    -> DB ERROR: {e}")
                if consecutive_fails >= 3:
                    current_delay = min(current_delay * 1.5, 30.0)

        if (i + 1) % 10 == 0 or i == len(pending) - 1:
            cp = {"done": list(done_set), "failed": list(failed_set),
                  "nodata": list(nodata_set), "progress": progress}
            with open(CHECKPOINT, "w", encoding="utf-8") as f:
                json.dump(cp, f)
            processed = len(done_set) + len(failed_set) + len(nodata_set)
            log(f"[{processed}/{total}] ok={progress['done']} fail={progress['failed']} nodata={progress['no_data']}")

        time.sleep(current_delay + random.uniform(0, 0.5))

    cp = {"done": list(done_set), "failed": list(failed_set),
          "nodata": list(nodata_set), "progress": progress}
    with open(CHECKPOINT, "w", encoding="utf-8") as f:
        json.dump(cp, f)
    log(f"\nDone! ok={progress['done']} fail={progress['failed']} nodata={progress['no_data']}")
    show_status()
    conn.close()

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if "--status" in sys.argv:
        show_status()
    else:
        main()
