#!/usr/bin/env python3
"""fengstockdb.py — 全球个股日线数据库

将主要市场大盘股日线数据（OHLCV）下载到 market_data.db。
与指数数据同库，通过 category='stock' 区分。

用法：
    python fengstockdb.py build [market]   # 全量构建（所有市场或指定市场）
    python fengstockdb.py update [market]  # 增量更新
    python fengstockdb.py status           # 数据统计
    python fengstockdb.py list [market]    # 列出股票
    python fengstockdb.py info <ticker>    # 查看某只股票
    python fengstockdb.py verify           # 随机验证数据

市场: us, cn, hk, jp, uk, de, fr, kr, in, tw, au, sg
"""
import json, os, random, sqlite3, sys, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from io import StringIO

import pandas as pd
import requests

random.seed(20260721)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "market_data.db")
WIKI_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
_EARLIEST = (datetime.now() - timedelta(days=100 * 365.25)).strftime("%Y-%m-%d")

# yfinance session 池 — 轮换 UA 防限流
_YF_SESSION = None
def _get_yf_session():
    global _YF_SESSION
    if _YF_SESSION is None:
        s = requests.Session()
        uas = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
        ]
        s.headers["User-Agent"] = random.choice(uas)
        _YF_SESSION = s
    return _YF_SESSION

# ═══════════════════════════════════════════════════════════════════════════════
# 成分股获取函数
# ═══════════════════════════════════════════════════════════════════════════════

def get_sp500():
    """S&P 500 ~503 stocks (Wikipedia)"""
    resp = requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
                         headers=WIKI_HEADERS, timeout=15)
    df = pd.read_html(StringIO(resp.text))[0]
    out = []
    for t in df["Symbol"].astype(str).str.strip():
        t = t.replace(".", "-")  # BRK.B -> BRK-B for yfinance
        if t.lower() not in ("nan", "") and t:
            out.append((t, t))
    return out

def get_csi300():
    """沪深300 ~300 stocks (baostock)"""
    import baostock as bs
    _ensure_bs()
    rs = bs.query_hs300_stocks()
    result = []
    while rs.next():
        row = rs.get_row_data()
        code = row[1].replace("sh.", "").replace("sz.", "")
        db_t = f"{code}.SS" if code.startswith(("6", "9")) else f"{code}.SZ"
        result.append((db_t, code))
    return result

def get_hsi():
    """恒生指数成分股 ~85 stocks (Wikipedia)"""
    resp = requests.get("https://en.wikipedia.org/wiki/Hang_Seng_Index",
                         headers=WIKI_HEADERS, timeout=15)
    df = pd.read_html(StringIO(resp.text))[6]
    result = []
    for t in df["Ticker"]:
        raw = str(t).strip()
        num = raw.split(":")[-1].strip() if ":" in raw else raw
        if num.isdigit():
            db_t = f"{int(num):04d}.HK"
            result.append((db_t, db_t))
    return result

def get_nikkei225():
    """日经225 ~225 stocks (topforeignstocks list)"""
    codes = [
        "6857","8267","5201","2802","6770","6113","9202","8304","2502","3407",
        "4503","7832","5108","7751","6952","9022","9502","4519","7762","1721",
        "7186","8253","4751","7912","8750","4568","6367","1925","8601","2432",
        "4061","6902","4324","4631","5714","9020","6361","4523","5020","6954",
        "9983","6504","4901","5803","6702","8354","5801","6674","1808","7205",
        "6305","7004","6501","7267","7741","5019","7013","1605","3099","7202",
        "8001","3086","9201","8697","6178","2914","5411","1963","6473","1812",
        "4452","7012","9107","9433","9008","9009","6861","2801","2503","5406",
        "6301","9766","4902","6326","3405","6971","4151","6920","4689","2413",
        "8002","8252","7261","2269","4385","6479","4188","8058","6503","8802",
        "7011","9301","5711","7211","8306","8031","4183","8801","5706","9104",
        "8411","8725","6981","6701","3659","5333","2282","2871","6594","7731",
        "7974","5214","9147","3863","5401","9432","9101","4021","7201","2002",
        "1332","9843","6988","8604","6471","6472","9613","1802","9007","3861",
        "6103","7733","6645","4661","8591","9532","4578","5541","6752","4755",
        "6098","6723","8308","4004","7752","2501","7735","9735","6724","1928",
        "3382","6753","1803","4063","4507","4911","5831","6273","9434","9984",
        "2768","8630","6758","7270","3436","4005","8053","5802","6302","5713",
        "8316","8309","5232","4506","8830","7269","8795","5233","1801","6976",
        "2531","8233","4502","6762","3401","4543","8331","5631","9503","5101",
        "9001","9602","5301","8766","4043","9501","8035","9531","8804","9005",
        "3289","7911","3402","4042","5332","7203","8015","4704","4208","9021",
        "7951","7272","9064","6506","6841",
    ]
    return [(f"{c}.T", f"{c}.T") for c in codes]

def get_ftse100():
    """富时100 ~100 stocks (Wikipedia tickers need .L suffix)"""
    resp = requests.get("https://en.wikipedia.org/wiki/FTSE_100_Index",
                         headers=WIKI_HEADERS, timeout=15)
    df = pd.read_html(StringIO(resp.text))[6]
    out = []
    for t in df["Ticker"].astype(str).str.strip():
        if t not in ("-", "nan", "") and t:
            if "." not in t:
                out.append((t, f"{t}.L"))
            else:
                # Yahoo needs -.L e.g. BT.A → BT-A.L
                out.append((t, t.replace(".", "-") + ".L"))
    return out

def get_dax():
    """德国DAX40 ~40 stocks (Wikipedia)"""
    resp = requests.get("https://en.wikipedia.org/wiki/DAX", headers=WIKI_HEADERS, timeout=15)
    df = pd.read_html(StringIO(resp.text))[4]
    out = []
    for t in df["Ticker"]:
        s = str(t).strip()
        if s and s != "-":
            out.append((s, s))
    return out

def get_cac40():
    """法国CAC40 ~40 stocks (Wikipedia)"""
    resp = requests.get("https://en.wikipedia.org/wiki/CAC_40", headers=WIKI_HEADERS, timeout=15)
    df = pd.read_html(StringIO(resp.text))[4]
    out = []
    for t in df["Ticker"]:
        s = str(t).strip()
        if s and s != "-":
            out.append((s, s))
    return out

def get_kospi200():
    """KOSPI200 ~200 stocks (Wikipedia)"""
    resp = requests.get("https://en.wikipedia.org/wiki/KOSPI_200", headers=WIKI_HEADERS, timeout=15)
    df = pd.read_html(StringIO(resp.text))[2]
    out = []
    for s in df["Symbol"].astype(str).str.strip():
        s = s.replace(" ", "")
        if s.lower() not in ("nan", "") and len(s) > 0:
            out.append((f"{s}.KS", f"{s}.KS"))
    return out

def get_nifty50():
    """印度Nifty50 ~50 stocks (Wikipedia)"""
    resp = requests.get("https://en.wikipedia.org/wiki/NIFTY_50", headers=WIKI_HEADERS, timeout=15)
    df = pd.read_html(StringIO(resp.text))[1]
    out = []
    for s in df["Symbol"].astype(str).str.strip():
        s = s.replace(" ", "")
        if s.lower() not in ("nan", "") and len(s) > 0:
            out.append((f"{s}.NS", f"{s}.NS"))
    return out

def get_taiwan50():
    """台湾50 ~50 stocks (nstock.tw list)"""
    codes = [
        "1216","1303","2059","2301","2303","2308","2317","2327","2330","2344",
        "2345","2357","2360","2368","2382","2383","2395","2408","2412","2449",
        "2454","2603","2880","2881","2882","2883","2884","2885","2886","2887",
        "2890","2891","2892","3008","3017","3037","3045","3231","3443","3653",
        "3661","3665","3711","4904","4958","5880","6505","6669","7769","8046",
    ]
    return [(f"{c}.TW", f"{c}.TW") for c in codes]

def get_asx200():
    """澳洲ASX200 ~200 stocks (Wikipedia)"""
    resp = requests.get("https://en.wikipedia.org/wiki/S%26P/ASX_200",
                         headers=WIKI_HEADERS, timeout=15)
    df = pd.read_html(StringIO(resp.text))[2]
    out = []
    for c in df["Code"].astype(str).str.strip():
        if c.lower() not in ("nan", ""):
            out.append((f"{c}.AX", f"{c}.AX"))
    return out

def get_sti():
    """新加坡STI ~30 stocks (Wikipedia)"""
    resp = requests.get("https://en.wikipedia.org/wiki/Straits_Times_Index",
                         headers=WIKI_HEADERS, timeout=15)
    df = pd.read_html(StringIO(resp.text))[3]
    out = []
    for s in df["Stock symbol"].astype(str).str.strip():
        sym = s.split(":")[-1].strip() if ":" in s else s
        if sym:
            out.append((f"{sym}.SI", f"{sym}.SI"))
    return out

def get_smi():
    """瑞士SMI ~20 stocks (Wikipedia)"""
    resp = requests.get("https://en.wikipedia.org/wiki/Swiss_Market_Index",
                         headers=WIKI_HEADERS, timeout=15)
    df = pd.read_html(StringIO(resp.text))[2]
    out = []
    for t in df["Ticker"].astype(str).str.strip():
        if t and t != "nan":
            out.append((f"{t}.SW", f"{t}.SW"))
    return out

def get_aex():
    """荷兰AEX ~25 stocks (Wikipedia) — 已含.AS后缀"""
    resp = requests.get("https://en.wikipedia.org/wiki/AEX_index",
                         headers=WIKI_HEADERS, timeout=15)
    df = pd.read_html(StringIO(resp.text))[3]
    out = []
    for t in df["Ticker"].astype(str).str.strip():
        if t and t != "nan":
            out.append((t, t))
    return out

def get_ibex35():
    """西班牙IBEX 35 ~35 stocks (Wikipedia) — 已含.MC后缀"""
    resp = requests.get("https://en.wikipedia.org/wiki/IBEX_35",
                         headers=WIKI_HEADERS, timeout=15)
    df = pd.read_html(StringIO(resp.text))[2]
    out = []
    for t in df["Ticker"].astype(str).str.strip():
        if t and t != "nan":
            out.append((t, t))
    return out

def get_ftsemib():
    """意大利FTSE MIB ~40 stocks (Wikipedia) — 已含.MI后缀"""
    resp = requests.get("https://en.wikipedia.org/wiki/FTSE_MIB",
                         headers=WIKI_HEADERS, timeout=15)
    df = pd.read_html(StringIO(resp.text))[1]
    out = []
    for t in df["Ticker"].astype(str).str.strip():
        if t and t != "nan":
            out.append((t, t))
    return out

def get_omxs30():
    """瑞典OMXS30 ~30 stocks (Wikipedia) — 已含.ST后缀"""
    resp = requests.get("https://en.wikipedia.org/wiki/OMX_Stockholm_30",
                         headers=WIKI_HEADERS, timeout=15)
    df = pd.read_html(StringIO(resp.text))[1]
    out = []
    for t in df["Ticker"].astype(str).str.strip():
        if t and t != "nan":
            out.append((t, t))
    return out

def get_nzx50():
    """新西兰NZX 50 ~50 stocks (Wikipedia)"""
    resp = requests.get("https://en.wikipedia.org/wiki/NZX_50_Index",
                         headers=WIKI_HEADERS, timeout=15)
    df = pd.read_html(StringIO(resp.text))[1]
    out = []
    for t in df["Ticker symbol"].astype(str).str.strip():
        if t and t != "nan":
            out.append((f"{t}.NZ", f"{t}.NZ"))
    return out

def get_tsx60():
    """加拿大TSX 60 ~60 stocks (Wikipedia)"""
    resp = requests.get("https://en.wikipedia.org/wiki/S%26P/TSX_60",
                         headers=WIKI_HEADERS, timeout=15)
    df = pd.read_html(StringIO(resp.text))[1]
    out = []
    for t in df["Symbol"].astype(str).str.strip():
        if t and t != "nan":
            out.append((f"{t}.TO", f"{t}.TO"))
    return out

# ═══════════════════════════════════════════════════════════════════════════════
# 市场注册表
# ═══════════════════════════════════════════════════════════════════════════════

MARKETS = {
    "us": {"name": "美国 S&P 500",  "market": "US", "fn": get_sp500,     "src": "yfinance"},
    "cn": {"name": "A股 沪深300",   "market": "CN", "fn": get_csi300,    "src": "baostock"},
    "hk": {"name": "香港 恒生",     "market": "HK", "fn": get_hsi,       "src": "yfinance"},
    "jp": {"name": "日本 日经225",  "market": "JP", "fn": get_nikkei225, "src": "yfinance"},
    "uk": {"name": "英国 富时100",  "market": "UK", "fn": get_ftse100,   "src": "yfinance"},
    "de": {"name": "德国 DAX40",    "market": "DE", "fn": get_dax,       "src": "yfinance"},
    "fr": {"name": "法国 CAC40",    "market": "FR", "fn": get_cac40,     "src": "yfinance"},
    "kr": {"name": "韩国 KOSPI200", "market": "KR", "fn": get_kospi200,  "src": "yfinance"},
    "in": {"name": "印度 Nifty50",  "market": "IN", "fn": get_nifty50,   "src": "yfinance"},
    "tw": {"name": "台湾50",        "market": "TW", "fn": get_taiwan50,  "src": "yfinance"},
    "au": {"name": "澳洲 ASX200",   "market": "AU", "fn": get_asx200,    "src": "yfinance"},
    "sg": {"name": "新加坡 STI",    "market": "SG", "fn": get_sti,       "src": "yfinance"},
    "ch": {"name": "瑞士 SMI",      "market": "CH", "fn": get_smi,       "src": "yfinance"},
    "nl": {"name": "荷兰 AEX",      "market": "NL", "fn": get_aex,       "src": "yfinance"},
    "es": {"name": "西班牙 IBEX35", "market": "ES", "fn": get_ibex35,    "src": "yfinance"},
    "it": {"name": "意大利 MIB",    "market": "IT", "fn": get_ftsemib,   "src": "yfinance"},
    "se": {"name": "瑞典 OMXS30",   "market": "SE", "fn": get_omxs30,    "src": "yfinance"},
    "nz": {"name": "新西兰 NZX50",  "market": "NZ", "fn": get_nzx50,     "src": "yfinance"},
    "ca": {"name": "加拿大 TSX60",  "market": "CA", "fn": get_tsx60,     "src": "yfinance"},
}

# ═══════════════════════════════════════════════════════════════════════════════
# 数据库操作
# ═══════════════════════════════════════════════════════════════════════════════

def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    return conn

def seed_and_map(conn, stocks, market):
    """写入 indices 表，返回 {(db_ticker): (index_id, yf_ticker)}"""
    cur = conn.execute("SELECT ticker, id FROM indices")
    existing = {r["ticker"]: r["id"] for r in cur.fetchall()}
    for db_t, _ in stocks:
        if db_t not in existing:
            conn.execute("INSERT OR IGNORE INTO indices (ticker, name, market, category) VALUES (?, ?, ?, ?)",
                         (db_t, db_t, market, "stock"))
    conn.commit()
    cur = conn.execute("SELECT ticker, id FROM indices WHERE market=? AND category='stock'", (market,))
    db_ids = {r["ticker"]: r["id"] for r in cur.fetchall()}
    stocks_dict = dict(stocks)
    return {t: (db_ids[t], stocks_dict[t]) for t in stocks_dict if t in db_ids}

# ═══════════════════════════════════════════════════════════════════════════════
# 下载函数
# ═══════════════════════════════════════════════════════════════════════════════

def download_yf(ticker, force_all, skip_dates):
    """用 yfinance 下载，返回 [(date, open, high, low, close, volume), ...]"""
    import yfinance as yf
    try:
        s = _get_yf_session()
        t = yf.Ticker(ticker, session=s)
        hist = t.history(start=_EARLIEST) if force_all else t.history(period="3mo")
        if hist.empty:
            return []
    except Exception:
        return []
    rows = []
    for dt_idx, r in hist.iterrows():
        d = dt_idx.strftime("%Y-%m-%d") if hasattr(dt_idx, "strftime") else str(dt_idx)[:10]
        if d in skip_dates:
            continue
        rows.append((
            d,
            float(r["Open"]) if pd.notna(r["Open"]) else None,
            float(r["High"]) if pd.notna(r["High"]) else None,
            float(r["Low"]) if pd.notna(r["Low"]) else None,
            float(r["Close"]) if pd.notna(r["Close"]) else None,
            int(r["Volume"]) if pd.notna(r["Volume"]) else None,
        ))
    return rows

_bs_login = threading.local()

def _ensure_bs():
    """确保当前线程已登录 baostock"""
    if not getattr(_bs_login, "ok", False):
        import baostock as bs
        bs.login()
        _bs_login.ok = True

def download_baostock(symbol, force_all, skip_dates):
    """用 baostock 下载 A 股，返回 [(date, open, high, low, close, volume), ...]"""
    import baostock as bs
    _ensure_bs()
    try:
        end = datetime.now().strftime("%Y-%m-%d")
        start = "1990-12-01" if force_all else "2020-01-01"
        if symbol.startswith(("6", "9")):
            code = f"sh.{symbol}"
        else:
            code = f"sz.{symbol}"
        rs = bs.query_history_k_data_plus(code,
            "date,open,high,low,close,volume",
            start_date=start, end_date=end,
            frequency="d", adjustflag="3")
        rows = []
        while rs.next():
            d, o, h, l, c, v = rs.get_row_data()
            if d in skip_dates:
                continue
            try:
                rows.append((
                    d,
                    float(o) if o else None,
                    float(h) if h else None,
                    float(l) if l else None,
                    float(c) if c else None,
                    int(float(v)) if v else None,
                ))
            except (ValueError, TypeError):
                continue
    except Exception:
        return []
    return rows

def download_one(idx_id, db_t, yf_t, source, force_all, skip_dates=None):
    """单只股票下载+写入，返回新增行数"""
    if skip_dates is None:
        conn = get_db()
        cur = conn.execute("SELECT date FROM daily_data WHERE index_id=?", (idx_id,))
        skip_dates = {r["date"] for r in cur.fetchall()}
        conn.close()
    if source == "yfinance":
        time.sleep(0.3 + random.random() * 0.4)  # rate limit avoidance
        rows = download_yf(yf_t, force_all, skip_dates)
    elif source == "baostock":
        rows = download_baostock(yf_t, force_all, skip_dates)
    else:
        return None, 0
    if not rows:
        return db_t, 0
    conn = get_db()
    data = [(idx_id, *r) for r in rows]
    conn.executemany("INSERT OR IGNORE INTO daily_data (index_id,date,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?)", data)
    conn.commit()
    conn.close()
    return db_t, len(rows)

# ═══════════════════════════════════════════════════════════════════════════════
# 构建逻辑
# ═══════════════════════════════════════════════════════════════════════════════

def build_market(mk, force_all, workers=6):
    cfg = MARKETS[mk]
    print(f"\n{'='*60}\n {cfg['name']} ({mk.upper()})\n{'='*60}")
    print("  获取成分股...")
    try:
        stocks = cfg["fn"]()
    except Exception as e:
        print(f"  [ERR] 成分股获取失败: {e}")
        return 0, 0
    print(f"  成分股: {len(stocks)} 只")

    conn = get_db()
    mapping = seed_and_map(conn, stocks, cfg["market"])
    conn.close()
    if not mapping:
        return 0, 0

    total = len(mapping)
    done = 0
    new_rows = 0
    pool_args = [(idx, db_t, yf_t, cfg["src"], force_all) for db_t, (idx, yf_t) in mapping.items()]

    with ThreadPoolExecutor(max_workers=workers) as ex:
        fut = {ex.submit(download_one, *a): a[1] for a in pool_args}
        for f in as_completed(fut):
            db_t = fut[f]
            done += 1
            try:
                _, n = f.result()
            except Exception as e:
                n = 0
                print(f"    [ERR] {db_t}: {e}")
            new_rows += n
            if n > 0:
                print(f"    [{done}/{total}] {db_t}: +{n}")
            elif done % 50 == 0 or done == total:
                print(f"    [{done}/{total}] ...{n} new")

    # 更新日志
    conn = get_db()
    for db_t, (idx, _) in mapping.items():
        cur = conn.execute("SELECT MAX(date) as md FROM daily_data WHERE index_id=?", (idx,))
        last = cur.fetchone()["md"]
        conn.execute("INSERT OR REPLACE INTO update_log (ticker, last_date, rows, updated_at) VALUES (?, ?, "
                     "(SELECT COUNT(*) FROM daily_data WHERE index_id=?), datetime('now'))",
                     (db_t, last, idx))
    conn.commit()
    conn.close()
    print(f"\n  [{cfg['name']}] 完成: +{new_rows} 条")
    return total, new_rows

# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def _resolve(target):
    if target:
        if target not in MARKETS:
            print(f"[ERR] 未知市场: {target}\n可选: {', '.join(MARKETS)}")
            sys.exit(1)
        return [target]
    return list(MARKETS)

def cmd_build(target):
    for mk in _resolve(target):
        build_market(mk, force_all=True)
        time.sleep(2)

def cmd_update(target):
    for mk in _resolve(target):
        build_market(mk, force_all=False)
        time.sleep(1)

def cmd_status():
    conn = get_db()
    cur = conn.execute("""
        SELECT i.market, COUNT(DISTINCT i.id) as n_stock, COUNT(d.id) as n_rows,
               COUNT(DISTINCT i.id) FILTER (WHERE d.id IS NOT NULL) as has_data
        FROM indices i LEFT JOIN daily_data d ON d.index_id = i.id
        WHERE i.category='stock' GROUP BY i.market ORDER BY i.market
    """)
    rows = cur.fetchall()
    # 指数统计
    cur2 = conn.execute("""
        SELECT COUNT(DISTINCT i.id) as n_idx, COUNT(d.id) as n_idx_rows
        FROM indices i LEFT JOIN daily_data d ON d.index_id=i.id
        WHERE i.category IN ('index','etf','macro')
    """)
    idx_stat = cur2.fetchone()
    conn.close()
    print(f"{'Market':<7} {'Stocks':<8} {'HasData':<8} {'Rows':<12}")
    print("-" * 35)
    ts, tr, td = 0, 0, 0
    for r in rows:
        print(f"{r['market']:<7} {r['n_stock']:<8} {r['has_data']:<8} {r['n_rows']:<12}")
        ts += r["n_stock"]; tr += r["n_rows"]; td += r["has_data"]
    print("-" * 35)
    print(f"{'TOTAL':<7} {ts:<8} {td:<8} {tr:<12}")
    if idx_stat and idx_stat["n_idx"]:
        print(f"\n指数/ETF/宏观: {idx_stat['n_idx']} 个, {idx_stat['n_idx_rows']} 行")
    size_mb = os.path.getsize(DB_PATH) / 1e6
    print(f"数据库: {size_mb:.1f} MB")

def cmd_list(target):
    conn = get_db()
    if target:
        cur = conn.execute("""
            SELECT i.ticker,i.name,i.market,COUNT(d.id) as cnt,MIN(d.date) as first,MAX(d.date) as last
            FROM indices i LEFT JOIN daily_data d ON d.index_id=i.id
            WHERE i.category='stock' AND i.market=? GROUP BY i.id ORDER BY i.ticker
        """, (target.upper(),))
    else:
        cur = conn.execute("""
            SELECT i.ticker,i.name,i.market,COUNT(d.id) as cnt,MIN(d.date) as first,MAX(d.date) as last
            FROM indices i LEFT JOIN daily_data d ON d.index_id=i.id
            WHERE i.category='stock' GROUP BY i.id ORDER BY i.market,i.ticker
        """)
    rows = cur.fetchall()
    conn.close()
    if not rows:
        print("暂无股票数据"); return
    by_mkt = {}
    for r in rows:
        by_mkt.setdefault(r["market"], []).append(r)
    for m, ss in sorted(by_mkt.items()):
        print(f"\n--- {m} ({len(ss)} stocks) ---")
        for r in ss[:20]:
            print(f"  {r['ticker']:<18} {r['cnt'] or 0:>8} rows  {r['first'] or '-':<12} {r['last'] or '-'}")
        if len(ss) > 20:
            print(f"  ... {len(ss)-20} more")

def cmd_info(ticker):
    conn = get_db()
    cur = conn.execute("SELECT id,ticker,name,market,category FROM indices WHERE ticker=?", (ticker.upper(),))
    r = cur.fetchone()
    if not r:
        print(f"[ERR] {ticker}: not found"); conn.close(); return
    cur = conn.execute("""
        SELECT COUNT(*) as cnt,MIN(date) as first,MAX(date) as last,
               MIN(close) as mn,MAX(close) as mx,AVG(close) as av
        FROM daily_data WHERE index_id=?
    """, (r["id"],))
    s = cur.fetchone(); conn.close()
    if s and s["cnt"]:
        print(f"{r['ticker']} -- {r['name']} ({r['market']}/{r['category']})")
        print(f"  Rows: {s['cnt']}, Range: {s['first']} ~ {s['last']}")
        print(f"  Close: {s['mn']:.2f} ~ {s['mx']:.2f} (avg {s['av']:.2f})")

def cmd_verify():
    import yfinance as yf
    conn = get_db()
    cur = conn.execute("""
        SELECT i.ticker,i.name,i.market,COUNT(d.id) as cnt
        FROM indices i JOIN daily_data d ON d.index_id=i.id
        WHERE i.category='stock' GROUP BY i.id HAVING cnt>50 ORDER BY RANDOM() LIMIT 10
    """)
    samples = cur.fetchall()
    if not samples:
        print("No stock data to verify"); conn.close(); return
    ok = True
    for s in samples:
        ticker = s["ticker"]
        print(f"  {ticker} ({s['cnt']} rows)")
        cur2 = conn.execute("""
            SELECT date,close FROM daily_data
            WHERE index_id=(SELECT id FROM indices WHERE ticker=?) ORDER BY date DESC LIMIT 5
        """, (ticker,))
        db = {r["date"]: r["close"] for r in cur2.fetchall()}
        try:
            hist = yf.Ticker(ticker).history(period="1mo")
            miss = 0
            for dt, r in hist.iterrows():
                d = dt.strftime("%Y-%m-%d") if hasattr(dt,"strftime") else str(dt)[:10]
                if d in db and db[d] and pd.notna(r["Close"]):
                    diff = abs(db[d]-float(r["Close"]))/float(r["Close"])*100
                    if diff > 1:
                        miss += 1
                        print(f"    MISMATCH {d}: DB={db[d]:.4f} YF={float(r['Close']):.4f} diff={diff:.2f}%")
            print(f"    {'[OK]' if not miss else f'[WARN] {miss} mismatches'}")
        except Exception as e:
            print(f"    verify err: {e}")
    conn.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    cmd, target = sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None
    actions = {"build": cmd_build, "update": cmd_update, "status": lambda _: cmd_status(),
               "list": cmd_list, "info": cmd_info, "verify": lambda _: cmd_verify()}
    actions.get(cmd, lambda _: print(f"Unknown: {cmd}\n{__doc__}"))(target)
