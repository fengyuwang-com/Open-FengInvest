#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""fengexpand_hk.py — 港股日线批量回填适配器（数据库永动扩张·阶段2b 直连在线源）

输入: data/expansion/hk_all_list.csv（2,802 只港股全名单，列 代码,中文名称）
输出: data/market_data.db 的 indices(market='HK',category='stock') + daily_data
写库: 一律走 tools/fengdb.safe_batch（可回滚 changeset），铁律不直接 sqlite3 写。
数据源: akshare stock_hk_daily（新浪源，全历史一次抓取，本地按 --from-date/--to-date 过滤；
  腾讯 ifzq 接口实测遇 captcha verify failed 不用）。symbol 为 5 位数字字符串（补前导零）。

用法:
  python tools/fengexpand_hk.py --limit 3          # 小样验证
  python tools/fengexpand_hk.py --limit 100        # 稳定性批次
  python tools/fengexpand_hk.py                    # 全量（断点续传，跳过已有）
  python tools/fengexpand_hk.py --start 00001 --end 01000
  python tools/fengexpand_hk.py --dry-run          # 只盘点缺多少，不写库
  python tools/fengexpand_hk.py --refresh          # 刷新模式：最新日期落后 --stale-days 天的在库票也重抓
                                                   # （周频全量刷新用；新浪源本就全历史一次抓，天然同锚）

代码格式: 库内既有 HK ticker = "0005.HK"（5位代码 + .HK 后缀，88 个先例），本工具对齐。
volume 单位: 新浪港股源单位=股，与库内既有行一致。
进度: data/expansion/hk_progress.json（断点续传）+ progress.jsonl 每轮追加一行。
"""
import argparse
import csv
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, date, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "data", "market_data.db")
LIST_CSV = os.path.join(BASE, "data", "expansion", "hk_all_list.csv")
PROGRESS_JSON = os.path.join(BASE, "data", "expansion", "hk_progress.json")
PROGRESS_JSONL = os.path.join(BASE, "data", "expansion", "progress.jsonl")

# 限流节律：新浪港股接口 1.2s/只；失败退避重试
SLEEP_BETWEEN = 1.2      # 每只之间秒数
RETRY_BACKOFF = 8.0      # 失败重试前等待
MAX_RETRY = 2


def pad5(code: str) -> str:
    """代码补齐 5 位（新浪港股接口要求 5 位数字字符串）。"""
    return code.zfill(5)


def ticker_of(code: str) -> str:
    """5位代码 → 库内格式 0005.HK（与既有 88 个 HK 行对齐）。"""
    return pad5(code) + ".HK"


def load_list() -> list[dict]:
    rows = []
    with open(LIST_CSV, "r", encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            code = (r.get("代码") or "").strip()
            if code:
                rows.append({"code": pad5(code),
                             "name": (r.get("中文名称") or "").strip()})
    return rows


def db_readonly() -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def existing_state() -> dict:
    """返回 {ticker: has_data_bool}，'已在库' = indices 有 ticker 且 daily_data 有行。"""
    with db_readonly() as con:
        known = {r["ticker"]: False for r in
                 con.execute("SELECT ticker FROM indices WHERE market='HK' AND category='stock'")}
        for r in con.execute(
                "SELECT DISTINCT i.ticker AS t FROM daily_data d "
                "JOIN indices i ON d.index_id=i.id WHERE i.market='HK' AND i.category='stock'"):
            known[r["t"]] = True
    return known


def stale_state(stale_days: int) -> dict:
    """刷新模式：返回 {ticker: latest_date}，只含最新日期早于 today-stale_days 的在库票。"""
    cutoff = (date.today() - timedelta(days=stale_days)).isoformat()
    with db_readonly() as con:
        return {r["t"]: r["m"] for r in con.execute(
            "SELECT i.ticker AS t, MAX(d.date) AS m FROM daily_data d "
            "JOIN indices i ON d.index_id=i.id "
            "WHERE i.market='HK' AND i.category='stock' "
            "GROUP BY i.ticker HAVING MAX(d.date) < ?", (cutoff,))}


def fetch_daily(code: str, start: str, end: str):
    """akshare 新浪港股源日线（不复权）。返回 list[dict] 或抛异常（原样上抛不吞）。
    注：stock_hk_daily 无日期参数，一次抓全历史，本地按日期过滤；
    新浪 volume 单位=股，与库内既有行一致。"""
    import akshare as ak
    df = ak.stock_hk_daily(symbol=code, adjust="")
    if df is None or df.empty:
        return []
    out = []
    for _, row in df.iterrows():
        d = str(row["date"])[:10]
        if d < f"{start[:4]}-{start[4:6]}-{start[6:]}" or d > f"{end[:4]}-{end[4:6]}-{end[6:]}":
            continue
        out.append({
            "date": d,
            "open": float(row["open"]), "high": float(row["high"]),
            "low": float(row["low"]), "close": float(row["close"]),
            "volume": float(row["volume"]),   # 新浪单位: 股
            "unadj_close": float(row["close"]),  # 不复权抓取；unadj 与 close 同源（对齐先例）
        })
    return out


def append_jsonl(rec: dict):
    os.makedirs(os.path.dirname(PROGRESS_JSONL), exist_ok=True)
    with open(PROGRESS_JSONL, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def save_progress(state: dict):
    with open(PROGRESS_JSON, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)


def main() -> int:
    ap = argparse.ArgumentParser(description="港股日线批量回填（safe_batch 可回滚）")
    ap.add_argument("--limit", type=int, default=0, help="只回填前 N 只缺号（0=全量）")
    ap.add_argument("--start", type=str, default="", help="起始代码（断点续传）")
    ap.add_argument("--end", type=str, default="", help="结束代码")
    ap.add_argument("--from-date", type=str, default="19800101", help="开始日期 YYYYMMDD")
    ap.add_argument("--to-date", type=str, default=date.today().strftime("%Y%m%d"))
    ap.add_argument("--dry-run", action="store_true", help="只盘点，不写库")
    ap.add_argument("--refresh", action="store_true",
                    help="刷新模式：已入库但最新日期落后 --stale-days 天的票也重抓"
                         "（周频全量刷新用；新浪港股源全历史一次抓，天然同锚）")
    ap.add_argument("--stale-days", type=int, default=4,
                    help="刷新模式判旧阈值（自然日，默认 4）")
    args = ap.parse_args()

    # 熔断检查（PLAN.md 铁律）：C 盘 < 30GB 不写库
    free_gb = __import__("shutil").disk_usage("C:\\").free / 1e9
    if free_gb < 30:
        append_jsonl({"ts": datetime.now().isoformat(timespec="seconds"),
                      "task": "hk-backfill-batch", "result": "disk_fuse_cutoff",
                      "free_gb": round(free_gb, 1), "rows": 0})
        print(f"[cutoff] C盘剩余 {free_gb:.1f}GB < 30GB，熔断退出，不写库")
        return 1

    all_rows = load_list()
    known = None
    if args.refresh:
        # 刷新模式：已入库但最新日期落后的票也重抓（新浪港股源全历史一次抓，天然同锚）
        stale = stale_state(args.stale_days)
        todo = [r for r in all_rows if ticker_of(r["code"]) in stale]
        print(f"[plan] 刷新模式：最新日期落后 {args.stale_days} 天以上的在库票 {len(todo)} 只"
              f"（本次处理 {len(todo)}）")
    else:
        known = existing_state()
        todo = [r for r in all_rows
                if not known.get(ticker_of(r["code"]), False)]
    if args.start:
        todo = [r for r in todo if r["code"] >= pad5(args.start)]
    if args.end:
        todo = [r for r in todo if r["code"] <= pad5(args.end)]
    if args.limit:
        todo = todo[: args.limit]

    if not args.refresh:
        already = sum(1 for r in all_rows if known.get(ticker_of(r["code"]), False))
        print(f"[plan] 全名单 {len(all_rows)}，已在库 {already}，"
              f"待补 {len(all_rows) - already}（本次处理 {len(todo)}）")
    if args.dry_run:
        print(json.dumps({"dry_run": True, "todo": len(todo),
                          "sample": [ticker_of(r["code"]) for r in todo[:10]]},
                         ensure_ascii=False))
        return 0
    if not todo:
        print("[plan] 无待补，退出")
        return 0

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from fengdb import safe_batch  # 铁律：真实写库必经 safe_batch

    written_rows = 0
    ok = fail = 0
    errors = []          # 原样记录失败原因，不吞错
    done_codes = []
    t0 = time.time()

    with safe_batch(["indices", "daily_data"], f"hk_backfill_{datetime.now():%Y%m%d_%H%M}", DB_PATH) as con:
        id_cache = {t: i for i, t in con.execute("SELECT id,ticker FROM indices")}
        for i, r in enumerate(todo):
            code, ticker = r["code"], ticker_of(r["code"])
            attempt = 0
            rows = None
            while attempt <= MAX_RETRY:
                try:
                    rows = fetch_daily(code, args.from_date, args.to_date)
                    break
                except KeyboardInterrupt:
                    raise
                except Exception as e:  # 原样记录，不吞
                    attempt += 1
                    msg = f"{ticker}: attempt{attempt}: {type(e).__name__}: {str(e)[:200]}"
                    errors.append(msg)
                    print(f"[err] {msg}", file=sys.stderr, flush=True)
                    if attempt <= MAX_RETRY:
                        time.sleep(RETRY_BACKOFF * attempt)
                    else:
                        rows = None
            if rows is None:
                fail += 1
                continue
            iid = id_cache.get(ticker)
            if iid is None:
                # 库内可能已有该 ticker：IGNORE 防撞唯一约束，再回查 id
                con.execute(
                    "INSERT OR IGNORE INTO indices(ticker,name,market,category) VALUES(?,?,?,?)",
                    (ticker, r["name"] or ticker, "HK", "stock"))
                iid = con.execute(
                    "SELECT id FROM indices WHERE ticker=?", (ticker,)).fetchone()[0]
                id_cache[ticker] = iid
            for row in rows:
                con.execute(
                    "INSERT OR REPLACE INTO daily_data"
                    "(index_id,date,open,high,low,close,volume,unadj_close) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (iid, row["date"], row["open"], row["high"], row["low"],
                     row["close"], row["volume"], row["unadj_close"]))
            written_rows += len(rows)
            ok += 1
            done_codes.append(code)
            if (i + 1) % 10 == 0 or i + 1 == len(todo):
                rate = (time.time() - t0) / max(ok + fail, 1)
                print(f"[{i+1}/{len(todo)}] ok={ok} fail={fail} rows={written_rows} "
                      f"({rate:.1f}s/只) 最新={ticker} rows_now={len(rows)}", flush=True)
                save_progress({"last_done": done_codes, "ok": ok, "fail": fail,
                               "rows": written_rows,
                               "updated": datetime.now().isoformat(timespec="seconds")})
            time.sleep(SLEEP_BETWEEN)

    result = {"ts": datetime.now().isoformat(timespec="seconds"),
              "task": "hk-backfill-batch",
              "result": f"ok={ok} fail={fail}",
              "rows": written_rows,
              "range": [args.from_date, args.to_date],
              "errors_sample": errors[:10], "errors_total": len(errors)}
    append_jsonl(result)
    save_progress({"last_done": done_codes, "ok": ok, "fail": fail, "rows": written_rows,
                   "updated": result["ts"]})
    print(f"[done] ok={ok} fail={fail} rows={written_rows} errors={len(errors)}")
    if errors:
        print("[errors] 最近10条：")
        for e in errors[-10:]:
            print("  " + e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
