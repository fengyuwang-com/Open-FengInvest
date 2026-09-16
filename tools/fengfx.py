#!/usr/bin/env python3
"""fengfx.py — 汇率历史入库（R29 创始人定调：汇率本身是价格资产，要总体研究）

把 USDCNY=X（在岸人民币）、CNH=X（离岸人民币）、HKDCNY=X（港币）的日线历史
写入 market_data.db：indices 新增 category='fx' 档案 + daily_data.close 收盘价。
批量写入走 fengdb.safe_batch 可回滚；增量更新（从 MAX(date) 续传）。

用法:
    python tools/fengfx.py fetch            # 增量拉取入库
    python tools/fengfx.py fetch --full     # 从头重建（仍幂等，重复行不落）
    python tools/fengfx.py status           # 覆盖范围统计
"""
import json, os, sqlite3, sys
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "tools"))
DB_PATH = os.path.join(BASE, "data", "market_data.db")

# ticker, 中文名, yahoo symbol（EM: 前缀走东财源）
PAIRS = [
    ("USDCNY", "美元兑在岸人民币", "USDCNY=X"),
    ("USDCNH", "美元兑离岸人民币", "EM:CNH"),
    ("HKDCNY", "港币兑人民币", "HKDCNY=X"),
    ("USDHKD", "美元兑港币(联络汇率)", "USDHKD=X"),
]

PAIR_INFO = json.load(open(os.path.join(BASE, "data", "cache", "fx_latest.json"), encoding="utf-8")) if os.path.exists(os.path.join(BASE, "data", "cache", "fx_latest.json")) else {}


_YAHOO_HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]
_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def yahoo(symbol: str, rng: str) -> list:
    """Yahoo chart API 直连（period 参数才能拿满 FX 历史，range=max 会截断），返回 [(date, close)]"""
    import time, random, urllib.request
    last_err = None
    d = None
    for attempt in range(4):
        host = _YAHOO_HOSTS[attempt % 2]
        url = "https://%s/v8/finance/chart/%s?period1=0&period2=9999999999&interval=1d" % (host, symbol)
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            d = json.loads(urllib.request.urlopen(req, timeout=20).read().decode("utf-8"))
            break
        except Exception as e:  # noqa: BLE001 - Yahoo 间歇性 SSL 握手失败
            last_err = e
            time.sleep(1.0 * (attempt + 1))
    if d is None:
        raise RuntimeError("yahoo %s failed: %s" % (symbol, last_err))
    res = d["chart"]["result"][0]
    ts = res.get("timestamp") or []
    q = (res.get("indicators", {}).get("quote") or [{}])[0]
    out = []
    for t, c in zip(ts, q.get("close") or []):
        if c is None:
            continue
        day = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        out.append((day, float(c)))
    if not out:
        raise RuntimeError("empty series for %s" % symbol)
    return out


def em_cnh() -> list:
    """离岸人民币 CNH：Yahoo 无历史，走东财 kline（secid 133.USDCNH，2010-08 诞生日起）"""
    import time, urllib.request
    url = ("https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=133.USDCNH"
           "&fields1=f1,f2,f3&fields2=f51,f53&klt=101&fqt=0&beg=0&end=20500101")
    last_err = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            d = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
            break
        except Exception as e:  # noqa: BLE001 - 东财偶发瞬断
            last_err = e
            time.sleep(1.0 * (attempt + 1))
    else:
        raise RuntimeError("eastmoney CNH failed: %s" % last_err)
    kl = (d.get("data") or {}).get("klines") or []
    out = []
    for line in kl:
        day, close = line.split(",")[:2]
        out.append((day, float(close)))
    if not out:
        raise RuntimeError("empty CNH series from eastmoney")
    return out


def ensure_indices(cur):
    for tk, nm, _ in PAIRS:
        row = cur.execute("SELECT id FROM indices WHERE ticker=? AND category='fx'", (tk,)).fetchone()
        if not row:
            cur.execute("INSERT INTO indices (ticker, name, market, category) VALUES (?,?,?,?)", (tk, nm, "FX", "fx"))


def cmd_fetch(full=False):
    from fengdb import safe_batch
    rng = "max" if full else "2y"
    with safe_batch(["indices", "daily_data"], "fx_history_%s" % ("full" if full else "incr")) as con:
        cur = con.cursor()
        ensure_indices(cur)
        for tk, nm, sym in PAIRS:
            idx = cur.execute("SELECT id FROM indices WHERE ticker=? AND category='fx'", (tk,)).fetchone()[0]
            last = cur.execute("SELECT MAX(date) FROM daily_data WHERE index_id=?", (idx,)).fetchone()[0]
            if last and not full:
                print("%s: up to date (%s), skip" % (tk, last))
                continue
            if sym == "EM:CNH":
                rows = em_cnh()
            else:
                rows = yahoo(sym, "max" if (full or not last) else "2y")
            if last:
                rows = [r for r in rows if r[0] > last]
            n = 0
            for day, close in rows:
                dup = cur.execute("SELECT 1 FROM daily_data WHERE index_id=? AND date=?", (idx, day)).fetchone()
                if dup:
                    continue
                cur.execute(
                    "INSERT INTO daily_data (index_id, date, open, high, low, close, volume, unadj_close) VALUES (?,?,?,?,?,?,0,?)",
                    (idx, day, close, close, close, close, close),
                )
                n += 1
            print("%s (%s): +%d rows, latest=%s" % (tk, sym, n, rows[-1][0] if rows else last))


def cmd_latest():
    """纯本地输出 JSON：各货币对最新收盘 + 在岸/离岸价差（市场页汇率卡片数据源，零网络）。"""
    con = sqlite3.connect(DB_PATH)
    pairs = []
    for tk, nm, _ in PAIRS:
        r = con.execute(
            """SELECT i.ticker, i.name, d.date, d.close FROM indices i JOIN daily_data d ON d.index_id=i.id
               WHERE i.ticker=? AND i.category='fx' ORDER BY d.date DESC LIMIT 1""", (tk,)
        ).fetchone()
        if r:
            pairs.append({"ticker": r[0], "name": r[1], "date": r[2], "close": r[3]})
    con.close()
    out = {"pairs": pairs, "generated_at": datetime.now(timezone.utc).isoformat()}
    cny = next((p for p in pairs if p["ticker"] == "USDCNY"), None)
    cnh = next((p for p in pairs if p["ticker"] == "USDCNH"), None)
    if cny and cnh:
        spread_pct = (cnh["close"] - cny["close"]) / cny["close"] * 100.0
        out["spread"] = {"spread_pct": spread_pct, "warn": abs(spread_pct) > 0.5,
                         "usdcny_date": cny["date"], "usdcnh_date": cnh["date"]}
    print(json.dumps(out, ensure_ascii=False))


def cmd_status():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    for tk, nm, _ in PAIRS:
        r = cur.execute("""SELECT i.ticker, COUNT(*), MIN(d.date), MAX(d.date) FROM indices i
                           LEFT JOIN daily_data d ON d.index_id=i.id WHERE i.ticker=? AND i.category='fx' GROUP BY i.id""", (tk,)).fetchone()
        print(r)
    con.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "fetch":
        cmd_fetch(full="--full" in sys.argv)
    elif cmd == "status":
        cmd_status()
    elif cmd == "latest":
        cmd_latest()
    else:
        print(__doc__)
