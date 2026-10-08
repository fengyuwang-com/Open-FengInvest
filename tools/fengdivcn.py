#!/usr/bin/env python3
"""CN 全市场分红增量回填（akshare 东财 stock_fhps_em 报告期一览，免代理）。

数据源：ak.stock_fhps_em(date=报告期) —— 全市场分红送配一览，含除权除息日与
现金分红比例（10派X 元 → 每股 X/10）。逐报告期拉取，与 DB 中 CN 股票匹配后
增量写入 dividends（UNIQUE(index_id, ex_date) 幂等）。

用法：
  python tools/fengdivcn.py                # dry-run：只打印将写入的行
  python tools/fengdivcn.py --write        # 真写（fengdb.safe_batch 可回滚）
  python tools/fengdivcn.py --periods 20260630,20251231   # 自选报告期
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "data", "market_data.db")

# 默认拉近 4 个报告期，覆盖近一年实施分红
DEFAULT_PERIODS = ["20260630", "20251231", "20250930", "20250630"]


def log(msg):
    print("[%s] %s" % (__import__("datetime").datetime.now().strftime("%H:%M:%S"), msg))


def cn_suffix(code):
    if code.startswith("6"):
        return code + ".SH"
    if code.startswith(("8", "4", "9")):
        return code + ".BJ"
    return code + ".SZ"


def fetch_rows(periods):
    import akshare as ak
    rows = []  # (code, name, ex_date, per_share, period)
    for p in periods:
        df = ak.stock_fhps_em(date=p)
        impl = df[(df["方案进度"] == "实施分配") & df["除权除息日"].notna()]
        n = 0
        for _, r in impl.iterrows():
            ratio = r.get("现金分红-现金分红比例")
            if not ratio or ratio <= 0:
                continue
            ex = str(r["除权除息日"])[:10]
            if len(ex) != 10:
                continue
            rows.append((str(r["代码"]).zfill(6), str(r["名称"]), ex, round(float(ratio) / 10.0, 6), p))
            n += 1
        log("报告期 %s: 实施 %d 条(全市场 %d 行)" % (p, n, len(df)))
    return rows


def main():
    write = "--write" in sys.argv
    periods = DEFAULT_PERIODS
    for i, a in enumerate(sys.argv):
        if a == "--periods" and i + 1 < len(sys.argv):
            periods = [p.strip() for p in sys.argv[i + 1].split(",") if p.strip()]

    rows = fetch_rows(periods)

    con = sqlite3.connect(DB_PATH)
    stocks = dict(con.execute(
        "SELECT ticker, id FROM indices WHERE market='CN' AND category='stock'"))
    con.close()

    pending = {}  # (idx_id, ex_date) -> amt
    skipped_no_idx = 0
    for code, name, ex, amt, _p in rows:
        t = cn_suffix(code)
        idx_id = stocks.get(t)
        if idx_id is None:
            skipped_no_idx += 1
            continue
        pending.setdefault((idx_id, ex), amt)

    # 已在库中的跳过（幂等）
    existing = con2 = sqlite3.connect(DB_PATH)
    fresh = []
    for (idx_id, ex), amt in pending.items():
        hit = con2.execute(
            "SELECT 1 FROM dividends WHERE index_id=? AND ex_date=?", (idx_id, ex)).fetchone()
        if not hit:
            fresh.append((idx_id, ex, amt))
    con2.close()

    tick = {v: k for k, v in stocks.items()}
    log("匹配: 拟写 %d 条 | 已在库跳过 %d 条 | 库外代码 %d 条"
        % (len(fresh), len(pending) - len(fresh), skipped_no_idx))
    for idx_id, ex, amt in sorted(fresh, key=lambda x: x[1])[:40]:
        log("  %s %s 每股 %.4f" % (tick.get(idx_id, idx_id), ex, amt))
    if len(fresh) > 40:
        log("  ... 共 %d 条" % len(fresh))

    if not write:
        log("dry-run 结束（加 --write 真写）")
        return
    if not fresh:
        log("无新行可写")
        return

    from fengdb import safe_batch
    with safe_batch(["dividends"], "cn-dividends-akshare-%s" % "-".join(periods)) as cur:
        for idx_id, ex, amt in fresh:
            cur.execute(
                "INSERT OR IGNORE INTO dividends (index_id, ex_date, dividend) VALUES (?,?,?)",
                (idx_id, ex, amt))
        mx = cur.execute(
            "SELECT MAX(ex_date) FROM dividends d JOIN indices i ON i.id=d.index_id "
            "WHERE i.market='CN'").fetchone()[0]
    log("写入完成，CN MAX(ex_date) = %s" % mx)


if __name__ == "__main__":
    main()
