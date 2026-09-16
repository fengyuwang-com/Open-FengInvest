#!/usr/bin/env python3
"""fengsector.py — FengInvest 全球板块轮动模块（自建）

三层板块宇宙：
  L-US     11 只 SPDR 行业 ETF（XLK/XLY/...），基准 ^GSPC
  L-GLOBAL iShares 全球行业 ETF（IXN/IXJ/...，实测有效者收编），基准 ACWI（无效则 SPY 并标 proxy）
  L-CN     申万一级 31 行业指数（新浪源 akshare index_hist_sw），基准 000300.SS

算法（对齐 MIT 协议 github.com/deeleeramone/RRG-Dashboard 的计算方式，
其核心在 OpenBB openbb_technical.relative_rotation）：
  RS-Ratio   = 标的周收盘 / 基准周收盘；再取 52 点滚动窗口 z-score 归一后 ×100
               （参考实现的 z-score 归一：normalize(method="z")）
  RS-Momentum= RS-Ratio 的 12 周动量 ratio/ratio.shift(12)-1（任务规格指定形式；
               参考实现为 ln(1+r52w)-ln(1+r13w) 类同构），同样 52 点滚动 z-score 归一 ×100
  象限（两轴以 100 为界，本任务规格）：右上 Leading / 右下 Improving(获得动能)
               / 左上 Weakening / 左下 Lagging
  输出最近 26 周轨迹 trail 与上周→本周象限迁移信号；另算 1M/3M/6M/12M 绝对与超额动量排名。

写库通道：一律经 fengdb.safe_batch（apsw Session 变更集，可精确回滚），
每市场一批、label 如 sector_us_20260824；起始日期统一 2010-01-01（申万用 API 全量）。
yfinance 一律 auto_adjust=False，每只间隔 ≥1.2s；A 股申万走新浪源（禁用东财接口）。

用法：
    python tools/fengsector.py universe             # 打印三层数量与清单 JSON
    python tools/fengsector.py update               # 拉数入库（幂等增量）
    python tools/fengsector.py analyze              # stdout 各层象限表 + 轮动信号 JSON
    python tools/fengsector.py analyze --json       # 纯 JSON（三层 x/y/象限/信号/26 周尾迹）
    python tools/fengsector.py longterm             # L-CN 长周期体检人读表（只读库）
    python tools/fengsector.py longterm --json      # 沉寂榜+年度矩阵+CAGR排名+回撤采样 JSON
    python tools/fengsector.py dashboard            # 生成 research/070-reports/SECTOR-DASHBOARD.html（主副关系：/sector 为主，HTML 为 CLI 副产品保留）
"""
import argparse
import contextlib
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(BASE, "tools")
DB_PATH = os.path.join(BASE, "data", "market_data.db")
CONFIG_DIR = os.path.join(BASE, "data", "config")
UNIVERSE_JSON = os.path.join(CONFIG_DIR, "sector_universe.json")
PROGRESS_JSON = os.path.join(BASE, "data", "cache", "sector_progress.json")
ANALYSIS_JSON = os.path.join(BASE, "data", "cache", "sector_analysis.json")
DASHBOARD_HTML = os.path.join(BASE, "research", "070-reports", "SECTOR-DASHBOARD.html")

START_DATE = "2010-01-01"          # 美股系统一起始日
YF_SLEEP = 1.2                     # yfinance 每只最小间隔（秒），防限流
ZSCORE_WINDOW = 52                 # RS-Ratio / Momentum 归一滚动窗口（周）
ZSCORE_MIN_PERIODS = 52            # 严格 52 个点
MOM_WEEKS = 12                     # 动量回看周数
TRAIL_WEEKS = 26                   # 分析输出轨迹长度（周）
TAIL_WEEKS = 10                    # 图上尾迹长度（周，规格 8-12）

QUADRANTS = {
    # (x_side, y_side): 名称 —— 本任务规格：右下 Improving、左上 Weakening
    ("R", "T"): "Leading",
    ("R", "B"): "Improving",
    ("L", "T"): "Weakening",
    ("L", "B"): "Lagging",
}
QUAD_CN = {"Leading": "领涨", "Improving": "改善(获得动能)",
           "Weakening": "走弱", "Lagging": "滞后"}

# ── 宇宙常量 ──────────────────────────────────────────────────────────────────

US_SECTORS = [
    ("XLK", "信息技术"), ("XLY", "可选消费"), ("XLP", "必需消费"),
    ("XLE", "能源"), ("XLF", "金融"), ("XLV", "医疗保健"),
    ("XLI", "工业"), ("XLB", "原材料"), ("XLRE", "房地产"),
    ("XLU", "公用事业"), ("XLC", "通信服务"),
]
US_BENCH = "^GSPC"

# GLOBAL 层候选：实测（yfinance 返回有效 OHLC 且历史>5 年）后才收编
GLOBAL_CANDIDATES = ["IXN", "IXJ", "IXG", "EXI", "KXI", "MXI", "RXI", "JXI"]
GLOBAL_NAMES = {
    "IXN": "全球科技", "IXJ": "全球医疗保健", "IXG": "全球金融",
    "EXI": "全球工业", "KXI": "全球必需消费", "MXI": "全球材料",
    "RXI": "全球可选消费", "JXI": "全球公用事业",
}
GLOBAL_BENCH_PRIMARY = "ACWI"
GLOBAL_BENCH_FALLBACK = "SPY"

CN_SECTORS = [
    ("801010", "农林牧渔"), ("801030", "基础化工"), ("801040", "钢铁"),
    ("801050", "有色金属"), ("801080", "电子"), ("801110", "家用电器"),
    ("801120", "食品饮料"), ("801130", "纺织服饰"), ("801140", "轻工制造"),
    ("801150", "医药生物"), ("801160", "公用事业"), ("801170", "交通运输"),
    ("801180", "房地产"), ("801200", "商贸零售"), ("801210", "社会服务"),
    ("801230", "综合"), ("801710", "建筑材料"), ("801720", "建筑装饰"),
    ("801730", "电力设备"), ("801740", "国防军工"), ("801750", "计算机"),
    ("801760", "传媒"), ("801770", "通信"), ("801780", "银行"),
    ("801790", "非银金融"), ("801880", "汽车"), ("801890", "机械设备"),
    ("801950", "煤炭"), ("801960", "石油石化"), ("801970", "环保"),
    ("801980", "美容护理"),
]
CN_BENCH = "000300.SS"

LAYERS = ["L-US", "L-GLOBAL", "L-CN"]


def _log(msg):
    print(f"[fengsector {datetime.now():%H:%M:%S}] {msg}", flush=True)


def _save_progress(state):
    """进度落盘 data/cache/sector_progress.json（长跑中断不丢进度）。"""
    os.makedirs(os.path.dirname(PROGRESS_JSON), exist_ok=True)
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    with open(PROGRESS_JSON, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ── 写库通道（惰性加载 fengdb，锁等待加长） ────────────────────────────────────

@contextlib.contextmanager
def _safe_batch_retry(tables, label, attempts=3, wait_s=30):
    """fengdb.safe_batch 包装：库锁时等待重试（同 fengstockdb 模式）。"""
    if TOOLS_DIR not in sys.path:
        sys.path.insert(0, TOOLS_DIR)
    import fengdb
    fengdb.BUSY_TIMEOUT_MS = max(getattr(fengdb, "BUSY_TIMEOUT_MS", 0), 30000)
    ctx, con = None, None
    for i in range(attempts):
        try:
            ctx = fengdb.safe_batch(tables, label)
            con = ctx.__enter__()
            break
        except Exception as e:
            msg = str(e).lower()
            if ("lock" not in msg and "busy" not in msg) or i == attempts - 1:
                raise
            _log(f"[LOCK] 写库被占用（{e}），{wait_s}s 后重试 {i + 2}/{attempts}: {label}")
            time.sleep(wait_s)
    try:
        yield con
    except BaseException:
        ctx.__exit__(*sys.exc_info())
        raise
    else:
        ctx.__exit__(None, None, None)


def _ro_con():
    """只读连接（mode=ro，绝不误写）。"""
    import sqlite3
    con = sqlite3.connect(f"file:{DB_PATH.replace(os.sep, '/')}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


# ── 数据下载（只取数不写库） ───────────────────────────────────────────────────

_YF_SESSION = None


def _yf_session():
    global _YF_SESSION
    if _YF_SESSION is None:
        import requests
        s = requests.Session()
        s.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
        _YF_SESSION = s
    return _YF_SESSION


def download_yf(ticker, start=START_DATE, attempts=4):
    """yfinance 日线（auto_adjust=False 强制），指数退避重试瞬时网络错。
    返回 [(date, open, high, low, close, volume), ...]；彻底失败抛异常。"""
    import yfinance as yf
    last_err = None
    for i in range(attempts):
        try:
            h = yf.Ticker(ticker, session=_yf_session()).history(
                start=start, auto_adjust=False)
            time.sleep(YF_SLEEP + random.random() * 0.6)  # 每只间隔 ≥1.2s
            if h is None or h.empty:
                # 空结果也可能是限流假象，退避重试一次以上
                raise RuntimeError("empty history")
            rows = []
            for dt_idx, r in h.iterrows():
                d = dt_idx.strftime("%Y-%m-%d") if hasattr(dt_idx, "strftime") else str(dt_idx)[:10]
                rows.append((
                    d,
                    float(r["Open"]) if pd.notna(r["Open"]) else None,
                    float(r["High"]) if pd.notna(r["High"]) else None,
                    float(r["Low"]) if pd.notna(r["Low"]) else None,
                    float(r["Close"]) if pd.notna(r["Close"]) else None,
                    int(r["Volume"]) if pd.notna(r["Volume"]) else None,
                ))
            return rows
        except Exception as e:
            last_err = e
            wait = 2 ** i + random.random() * 2
            _log(f"    [RETRY {i + 1}/{attempts}] {ticker}: {type(e).__name__}: {str(e)[:90]} → 等 {wait:.0f}s")
            time.sleep(wait)
    raise RuntimeError(f"yfinance {ticker} 最终失败: {type(last_err).__name__}: {str(last_err)[:150]}")


def probe_yf(ticker, period="10y", attempts=3):
    """收编实测：period=10y 拉一次，返回探测 dict（不写任何文件）。
    瞬时限流/网络错会以 'possibly delisted' 假象出现 → 指数退避重试后再下结论。"""
    import yfinance as yf
    last_reason = ""
    for i in range(attempts):
        try:
            h = yf.Ticker(ticker, session=_yf_session()).history(period=period, auto_adjust=False)
            time.sleep(YF_SLEEP + random.random() * 0.6)
            if h is not None and not h.empty:
                years = (h.index[-1] - h.index[0]).days / 365.25
                ok_ohlc = bool(h[["Open", "High", "Low", "Close"]].notna().any(axis=1).all())
                accepted = bool(ok_ohlc and years > 5)
                return {"ticker": ticker, "ok": True, "rows": len(h),
                        "start": str(h.index[0].date()), "end": str(h.index[-1].date()),
                        "years": round(years, 2), "valid_ohlc": ok_ohlc, "accepted": accepted,
                        "reason": "" if accepted else f"历史不足 5 年（{years:.1f}y）或 OHLC 无效"}
            last_reason = "空返回（possibly delisted / 无数据）"
        except Exception as e:
            last_reason = f"{type(e).__name__}: {str(e)[:150]}"
        wait = 3 * (i + 1) + random.random() * 2
        _log(f"    [PROBE RETRY {i + 1}/{attempts}] {ticker}: {last_reason[:90]} → 等 {wait:.0f}s")
        time.sleep(wait)
    return {"ticker": ticker, "ok": False, "reason": last_reason}


def download_sw(code):
    """申万一级行业指数日线 —— 新浪源 akshare index_hist_sw（API 全量，禁东财）。
    返回 [(date, open, high, low, close, volume), ...]。"""
    import akshare as ak
    df = ak.index_hist_sw(symbol=str(code), period="day")
    time.sleep(1.0 + random.random() * 0.5)  # 新浪限流护栏
    if df is None or df.empty:
        return []
    rows = []
    for _, r in df.iterrows():
        d = str(r["日期"])
        try:
            rows.append((
                d,
                float(r["开盘"]) if pd.notna(r["开盘"]) else None,
                float(r["最高"]) if pd.notna(r["最高"]) else None,
                float(r["最低"]) if pd.notna(r["最低"]) else None,
                float(r["收盘"]) if pd.notna(r["收盘"]) else None,
                int(float(r["成交量"])) if pd.notna(r["成交量"]) else None,
            ))
        except (ValueError, TypeError):
            continue
    return rows


# ── 宇宙解析（含 GLOBAL 收编配置持久化） ────────────────────────────────────────

def load_universe_config():
    if os.path.exists(UNIVERSE_JSON):
        with open(UNIVERSE_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def resolve_global_layer(force_retest=False, prev=None):
    """GLOBAL 层成员解析：首跑逐只实测收编并落配置；之后直接用配置。
    重测时合并历史已收编成员（union），避免瞬时网络抖动把老成员误踢出。"""
    cfg = load_universe_config()
    if cfg and "global_test" in cfg and not force_retest:
        return cfg["global_test"]
    _log("GLOBAL 层候选逐只实测（yfinance 10y 探针）...")
    results = [probe_yf(t) for t in GLOBAL_CANDIDATES]
    prev_tickers = {a["ticker"] for a in (prev or {}).get("accepted", [])}
    accepted_map = {t: {"ticker": t, "name": GLOBAL_NAMES.get(t, t)} for t in prev_tickers}
    rejected = []
    for r in results:
        if r.get("accepted") or r["ticker"] in prev_tickers:
            accepted_map[r["ticker"]] = {"ticker": r["ticker"], "name": GLOBAL_NAMES.get(r["ticker"], r["ticker"])}
        else:
            rejected.append({"ticker": r["ticker"], "reason": r.get("reason") or "未通过实测"})
    accepted = [accepted_map[t] for t in GLOBAL_CANDIDATES if t in accepted_map]
    bench = probe_yf(GLOBAL_BENCH_PRIMARY)
    bench_ticker, bench_proxy = GLOBAL_BENCH_PRIMARY, False
    if not bench.get("ok"):
        fb = probe_yf(GLOBAL_BENCH_FALLBACK)
        if not fb.get("ok"):
            raise RuntimeError(f"GLOBAL 基准双双不可用: {bench['reason']} / {fb.get('reason')}")
        bench_ticker, bench_proxy = GLOBAL_BENCH_FALLBACK, True
    elif (prev or {}).get("benchmark_proxy"):
        bench_proxy = False
    gt = {"accepted": accepted, "rejected": rejected,
          "benchmark": bench_ticker, "benchmark_probe": bench, "benchmark_proxy": bench_proxy}
    _log(f"GLOBAL 收编 {len(accepted)}/{len(GLOBAL_CANDIDATES)}，基准 {bench_ticker}"
         + ("（proxy）" if bench_proxy else ""))
    return gt


def get_universe():
    """三层数据结构（universe 命令输出 / update 用）。"""
    gcfg = load_universe_config()
    layers = {
        "L-US": {"market": "US", "benchmark": US_BENCH,
                 "sectors": [{"ticker": t, "name": n} for t, n in US_SECTORS],
                 "source": "yfinance"},
        "L-GLOBAL": {"market": "GLOBAL", "source": "yfinance"},
        "L-CN": {"market": "CN", "benchmark": CN_BENCH,
                 "sectors": [{"ticker": t, "name": n} for t, n in CN_SECTORS],
                 "source": "新浪·申万(akshare index_hist_sw)"},
    }
    if gcfg and "global_test" in gcfg:
        gt = gcfg["global_test"]
    else:
        # 未实测过时给候选视图（universe 命令在 update 前调用即显示候选）
        layers["L-GLOBAL"].update({
            "benchmark": f"{GLOBAL_BENCH_PRIMARY}(待实测)",
            "sectors": [{"ticker": t, "name": GLOBAL_NAMES[t], "status": "candidate"} for t in GLOBAL_CANDIDATES]})
        return layers
    layers["L-GLOBAL"].update({
        "benchmark": gt["benchmark"] + ("(proxy)" if gt.get("benchmark_proxy") else ""),
        "sectors": gt["accepted"]})
    return layers


# ── update：拉数入库 ──────────────────────────────────────────────────────────

def _existing_dates(con, index_id):
    return {r["date"] for r in con.execute(
        "SELECT date FROM daily_data WHERE index_id=?", (index_id,)).fetchall()}


def cmd_update(args):
    state = {"run_started_at": datetime.now().isoformat(timespec="seconds"),
             "layers": {}, "changesets": []}
    _save_progress(state)

    uni = get_universe()
    # GLOBAL 未实测 → 先实测并落盘配置；--retest-global 强制重测（union 合并老成员）
    gcfg = load_universe_config() or {}
    if "global_test" not in gcfg or args.retest_global:
        gcfg["global_test"] = resolve_global_layer(force_retest=args.retest_global,
                                                   prev=gcfg.get("global_test"))
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(UNIVERSE_JSON, "w", encoding="utf-8") as f:
            json.dump(gcfg, f, ensure_ascii=False, indent=2)
        uni = get_universe()

    day_tag = datetime.now().strftime("%Y%m%d")
    summary = {}

    for layer in LAYERS:
        info = uni[layer]
        sectors = info["sectors"]
        bench = info["benchmark"].replace("(proxy)", "")
        tickers = [(s["ticker"], s["name"]) for s in sectors] + \
                  [(bench, "基准")]  # 基准一并增量维护
        _log(f"== {layer} 共 {len(tickers)} 只（含基准），market={info['market']} ==")

        # ① 先把新标的登记进 indices（查重：有 ticker 即跳过插入）
        pending_rows = []      # [(db_ticker, index_id, rows)]
        registered, skipped_reg = [], []
        failed = []

        # 先只读拿现有映射与已有日期集合
        ro = _ro_con()
        id_map = {r["ticker"]: r["id"] for r in ro.execute("SELECT ticker, id FROM indices")}
        have_dates = {}
        need_seed = [(t, n) for t, n in tickers if t not in id_map]
        for t, _ in [(t, n) for t, n in tickers if t in id_map]:
            iid = id_map[t]
            have_dates[t] = {r["date"] for r in ro.execute(
                "SELECT date FROM daily_data WHERE index_id=?", (iid,))}
        ro.close()

        if need_seed:
            label = f"seed_indices_{layer.lower()}_{day_tag}"
            with _safe_batch_retry(["indices"], label) as con:
                for t, n in need_seed:
                    cat = "index" if t == bench else "sector"
                    con.execute(
                        "INSERT OR IGNORE INTO indices (ticker, name, market, category) VALUES (?, ?, ?, ?)",
                        (t, n, info["market"], cat))
                    registered.append(t)
            # 重取映射
            ro = _ro_con()
            id_map = {r["ticker"]: r["id"] for r in ro.execute("SELECT ticker, id FROM indices")}
            ro.close()
            _log(f"  新登记 indices: {len(registered)} 只 ({label})")
        else:
            _log("  indices 无新增（全部已登记）")

        # ② 逐只下载（增量起点 = update_log.last_date 与已有最早缺口的较晚者，简单化：last_date 往前留 7 天缓冲）
        ro = _ro_con()
        log_rows = {r["ticker"]: (r["last_date"], r["rows"]) for r in ro.execute(
            "SELECT ticker, last_date, rows FROM update_log")}
        ro.close()

        for k, (t, name) in enumerate(tickers, 1):
            iid = id_map.get(t)
            if iid is None:
                failed.append({"ticker": t, "stage": "register", "error": "indices 登记缺失"})
                continue
            known = have_dates.setdefault(t, set())
            src_last = log_rows.get(t, (None, None))[0]
            # 按 ticker 形态分流：纯数字 = 申万指数走新浪；其余（含 ^GSPC/000300.SS 基准）走 yfinance
            use_sw = t.isdigit()
            if not use_sw:
                # 增量：从 max(START_DATE, last_date-7d) 起；已有行靠 skip 去重
                start = START_DATE
                if src_last and len(known) > 0 and src_last >= START_DATE:
                    y, m, d = (int(x) for x in src_last.split("-"))
                    start = max((datetime(y, m, d) - timedelta(days=7)).strftime("%Y-%m-%d"),
                                START_DATE)
                try:
                    rows = download_yf(t, start=start)
                except Exception as e:
                    failed.append({"ticker": t, "stage": "download", "error": str(e)[:200]})
                    _log(f"  [{k}/{len(tickers)}] FAIL {t}: {str(e)[:110]}")
                    continue
            else:
                try:
                    rows = download_sw(t)
                except Exception as e:
                    failed.append({"ticker": t, "stage": "download", "error": str(e)[:200]})
                    _log(f"  [{k}/{len(tickers)}] FAIL {t}: {str(e)[:110]}")
                    continue
            new_rows = [r for r in rows if r[0] not in known]
            # 防脏写：跳过「今天」的行 —— 盘中实时价未定型（如周一中午的 A 股），
            # INSERT OR IGNORE 会把盘中价永久留在库里；次日再取即已定型。
            today_str = datetime.now().strftime("%Y-%m-%d")
            new_rows = [r for r in new_rows if r[0] < today_str]
            pending_rows.append((t, iid, new_rows))
            _log(f"  [{k}/{len(tickers)}] {t}: 取得 {len(rows)} 行，新增 {len(new_rows)}"
                 + (f"（{new_rows[0][0]}~{new_rows[-1][0]}）" if new_rows else ""))
            state["layers"].setdefault(layer, {})[t] = {
                "fetched": len(rows), "new": len(new_rows)}
            _save_progress(state)

        # ③ 分批落库：≤50 只一个 changeset（本层一批即可，label 如 sector_cn_20260824）
        inserted_total = 0
        CH = 50
        for bi in range(0, len(pending_rows), CH):
            chunk = pending_rows[bi:bi + CH]
            label = f"sector_{layer.split('-')[1].lower()}_{day_tag}" + ("" if bi == 0 else f"_b{bi // CH + 1}")
            with _safe_batch_retry(["daily_data", "update_log", "indices"], label) as con:
                for t, iid, new_rows in chunk:
                    if not new_rows:
                        continue
                    before = con.total_changes()
                    con.executemany(
                        "INSERT OR IGNORE INTO daily_data "
                        "(index_id,date,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?)",
                        [(iid, *r) for r in new_rows])
                    inserted_total += con.total_changes() - before
                # 刷新 update_log（事务内，同一变更集可整体回滚）
                now = datetime.now().isoformat(timespec="seconds")
                for t, iid, _nr in chunk:
                    row = con.execute(
                        "SELECT MAX(date), COUNT(*) FROM daily_data WHERE index_id=?", (iid,)).fetchone()
                    con.execute(
                        "INSERT OR REPLACE INTO update_log (ticker,last_date,rows,updated_at) VALUES (?,?,?,?)",
                        (t, row[0], row[1], now))
            state["changesets"].append(label)
            _save_progress(state)
            _log(f"  落库批次 {label}: 插入 {inserted_total} 行累计")

        summary[layer] = {"tickers": len(tickers), "registered_new": len(registered),
                          "failed": failed, "inserted_rows": inserted_total}

    print(json.dumps({"summary": {k: {kk: vv for kk, vv in v.items()}
                                  for k, v in summary.items()}},
                     ensure_ascii=False, indent=2))
    return 0


# ── analyze：RRG 计算 ─────────────────────────────────────────────────────────

def _rolling_zscore_x100(s, window=ZSCORE_WINDOW, min_periods=ZSCORE_MIN_PERIODS):
    mu = s.rolling(window, min_periods=min_periods).mean()
    sd = s.rolling(window, min_periods=min_periods).std(ddof=1)
    return (s - mu) / sd * 100.0


def _quadrant(x, y):
    xs = "R" if x >= 100 else "L"
    ys = "T" if y >= 100 else "B"
    return QUADRANTS[(xs, ys)]


def _weekly_closes(tickers):
    """读库（ro）→ 收盘价宽表 → 周线 W-FRI 取每周最后收盘。"""
    ro = _ro_con()
    ph = {}
    for t in tickers:
        r = ro.execute("SELECT id FROM indices WHERE ticker=?", (t,)).fetchone()
        if not r:
            ph[t] = None
            continue
        rows = ro.execute(
            "SELECT date, close FROM daily_data WHERE index_id=? AND close IS NOT NULL ORDER BY date",
            (r["id"],)).fetchall()
        ph[t] = pd.Series({x["date"]: x["close"] for x in rows}, dtype=float)
    ro.close()
    df = pd.DataFrame(ph)
    df.index = pd.to_datetime(df.index)
    w = df.resample("W-FRI").last().dropna(how="all")
    return w


def compute_layer(layer_key, sectors, bench, bench_label=None):
    """单层 RRG 全量计算，返回该层分析 dict。"""
    tickers = [s["ticker"] for s in sectors]
    names = {s["ticker"]: s["name"] for s in sectors}
    w = _weekly_closes(tickers + [bench])
    # 公共周：标的与基准都有价的周
    w = w.dropna(subset=[bench])
    valid = [t for t in tickers if t in w.columns and w[t].notna().sum() >= ZSCORE_WINDOW + MOM_WEEKS + 1]
    excluded = [{"ticker": t, "reason": f"有效周数不足（需 ≥{ZSCORE_WINDOW + MOM_WEEKS + 1}）"}
                for t in tickers if t not in valid]
    # 剪掉尾部「只有基准有价」的周（如基准多一根盘中条），防止末周动量全变 None
    sec_cols = [c for c in w.columns if c != bench]
    if sec_cols:
        w = w[w[sec_cols].notna().any(axis=1)]
    w = w[[bench] + valid].copy()

    result = {"benchmark": bench, "benchmark_label": bench_label or bench,
              "weeks_used": int(len(w)),
              "first_week": str(w.index[0].date()) if len(w) else None,
              "last_week": str(w.index[-1].date()) if len(w) else None,
              "last_date": None, "excluded": excluded, "sectors": []}
    if len(w) < ZSCORE_WINDOW + 1:
        result["excluded"].append({"ticker": "*", "reason": "整层数据不足一年"})
        return result

    bw = w[bench]
    mom_rank_cols = {}
    for sec in sectors:
        t = sec["ticker"]
        if t not in valid:
            continue
        ratio_raw = w[t] / bw                      # RS-Ratio 原始比
        x = _rolling_zscore_x100(ratio_raw) * 1.0  # 已 ×100
        m_raw = ratio_raw / ratio_raw.shift(MOM_WEEKS) - 1.0   # 12 周动量（任务规格）
        y = _rolling_zscore_x100(m_raw)
        pair = pd.concat({"x": x, "y": y}, axis=1).dropna()
        if pair.empty:
            excluded.append({"ticker": t, "reason": "归一后无有效点"})
            continue
        last, prev = pair.iloc[-1], pair.iloc[-2] if len(pair) > 1 else None
        q_now = _quadrant(last.x, last.y)
        q_prev = _quadrant(prev.x, prev.y) if prev is not None else None
        trail = [{"date": str(ix.date()), "x": round(float(r.x), 2), "y": round(float(r.y), 2)}
                 for ix, r in pair.tail(TRAIL_WEEKS).iterrows()]
        # 绝对/超额动量（周频 4/13/26/52 ≈ 1M/3M/6M/12M）
        px, bx = w[t], bw
        abs_m, exc_m = {}, {}
        for lbl, n in (("1M", 4), ("3M", 13), ("6M", 26), ("12M", 52)):
            if len(px) > n and pd.notna(px.iloc[-1]) and pd.notna(px.iloc[-1 - n]) and px.iloc[-1 - n]:
                a = px.iloc[-1] / px.iloc[-1 - n] - 1
                b = bx.iloc[-1] / bx.iloc[-1 - n] - 1
                abs_m[lbl] = round(float(a) * 100, 2)
                exc_m[lbl] = round(float(a - b) * 100, 2)
            else:
                abs_m[lbl] = exc_m[lbl] = None
        mom_rank_cols[t] = exc_m
        result["sectors"].append({
            "ticker": t, "name": names.get(t, t),
            "x": round(float(last.x), 2), "y": round(float(last.y), 2),
            "quadrant": q_now, "prev_quadrant": q_prev,
            "signal": f"{q_prev}→{q_now}" if q_prev and q_prev != q_now else "持续",
            "trail": trail, "abs_mom": abs_m, "excess_mom": exc_m,
            "last_px_date": str(w[t].dropna().index[-1].date()),
        })

    # 排名（按 3M 超额动量降序；并列参考 6M）
    ranked = sorted([s for s in result["sectors"]],
                    key=lambda s: (-(s["excess_mom"]["3M"] if s["excess_mom"]["3M"] is not None else -999),
                                   -(s["excess_mom"]["6M"] if s["excess_mom"]["6M"] is not None else -999)))
    for i, s in enumerate(ranked, 1):
        s["rank_3m_excess"] = i
    result["last_date"] = max((s["last_px_date"] for s in result["sectors"]), default=None)
    return result


def cmd_analyze(args):
    uni = get_universe()
    out = {"generated_at": datetime.now().isoformat(timespec="seconds"), "layers": {}}
    for layer in LAYERS:
        info = uni[layer]
        bench = info["benchmark"].replace("(proxy)", "")
        proxy = "(proxy)" in info["benchmark"]
        res = compute_layer(layer, info["sectors"], bench,
                            bench_label=info["benchmark"] + ("" if not proxy else ""))
        out["layers"][layer] = res

        if getattr(args, "json", False):
            continue  # --json 模式：stdout 只留最终 JSON，表格一律不打印
        # 文本象限表
        print(f"\n===== {layer}  基准={res['benchmark']}  周数={res['weeks_used']}  最后周={res['last_week']} =====")
        print(f"{'板块':<14}{'代码':<9}{'X':>8}{'Y':>8}  {'本周象限':<12}{'上周':<12}{'信号'}")
        print("-" * 88)
        order = {"Leading": 0, "Improving": 1, "Weakening": 2, "Lagging": 3}
        for s in sorted(res["sectors"], key=lambda s: order[s["quadrant"]]):
            nm = f"{s['name']}"
            print(f"{nm:<14}{s['ticker']:<9}{s['x']:>8.1f}{s['y']:>8.1f}  "
                  f"{QUAD_CN[s['quadrant']]:<12}"
                  f"{(QUAD_CN[s['prev_quadrant']] if s['prev_quadrant'] else '-'):<12}{s['signal']}")
        if res["excluded"]:
            print(f"  [排除] {res['excluded']}")

    # 轮动信号汇总
    signals = {ly: [{"ticker": s["ticker"], "name": s["name"], "signal": s["signal"]}
                    for s in out["layers"][ly]["sectors"] if s["signal"] != "持续"]
               for ly in LAYERS}
    out["rotation_signals"] = signals
    os.makedirs(os.path.dirname(ANALYSIS_JSON), exist_ok=True)
    with open(ANALYSIS_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    if getattr(args, "json", False):
        print(json.dumps(out, ensure_ascii=False))
        return 0
    print("\n--- 轮动信号（象限迁移）JSON ---")
    print(json.dumps(signals, ensure_ascii=False, indent=2))
    print(f"\n完整分析已存 {ANALYSIS_JSON}")
    return 0


# ── longterm：CN 申万 31 行业长周期体检（只读库 mode=ro，绝不写库） ─────────────

LT_MA_WEEKS = 200            # 200 周均线（约 4 年）
LT_MATRIX_START_YEAR = 2006  # 年度收益矩阵起始年
STAG_DEEP_DD = -30.0         # 深度沉寂：回撤 >30%
STAG_DEEP_YEARS = 3.0        #   且距前高 ≥3 年
STAG_MID_DD = -20.0          # 沉寂：回撤 >20% 且 ≥2 年
STAG_MID_YEARS = 2.0
STAG_LEVEL_CN = {"deep": "深度沉寂", "mid": "沉寂", "none": "正常"}
CAGR_WINDOWS = (("1Y", 1), ("3Y", 3), ("5Y", 5), ("10Y", 10))
EXCESS_WINDOWS = ("5Y", "10Y")


def _stagnation_level(dd_pct, years_since):
    """回撤>30% 且 ≥3 年 = deep；>20% 且 ≥2 年 = mid；否则正常。"""
    if dd_pct is None or years_since is None:
        return "none"
    if dd_pct < STAG_DEEP_DD and years_since >= STAG_DEEP_YEARS:
        return "deep"
    if dd_pct < STAG_MID_DD and years_since >= STAG_MID_YEARS:
        return "mid"
    return "none"


def _trailing_cagr(s, years):
    """近 N 年 CAGR%（周线序列）；基期=目标日前最后一个有效周，历史不足返回 None。"""
    s = s.dropna()
    if len(s) < 2:
        return None
    last_dt, last_px = s.index[-1], float(s.iloc[-1])
    target = last_dt - pd.DateOffset(years=years)
    hist = s[s.index <= target]
    if hist.empty:
        return None
    base_dt, base_px = hist.index[-1], float(hist.iloc[-1])
    span = (last_dt - base_dt).days / 365.25
    if base_px <= 0 or span < years * 0.95:
        return None
    return round(((last_px / base_px) ** (1.0 / span) - 1.0) * 100, 2)


def _months_below_ma(sec, ma):
    """当前连续低于 200 周均线的月数（按该段连续周覆盖的日历月去重计数）。"""
    below = (sec < ma) & sec.notna() & ma.notna()
    if len(below) == 0 or not bool(below.iloc[-1]):
        return 0
    i = len(below) - 1
    while i >= 0 and bool(below.iloc[i]):
        i -= 1
    streak_idx = below.index[i + 1:]
    return int(streak_idx.to_period("M").nunique())


def _annual_returns_pct(s):
    """年度收益%（自然年最后收盘环比）；首年无基数不输出。"""
    s = s.dropna()
    if s.empty:
        return {}
    yearly_last = s.groupby(s.index.year).last()
    rets = yearly_last / yearly_last.shift(1) - 1.0
    return {int(y): round(float(v) * 100, 2) for y, v in rets.items() if pd.notna(v)}


def _monthly_drawdown_curve(sec):
    """水下曲线：滚动最高点回撤%，每月取一个样本点控制体积。"""
    dd = (sec / sec.cummax() - 1.0) * 100.0
    grp = dd.groupby([dd.index.year, dd.index.month]).last()
    return [[f"{y}-{m:02d}", round(float(v), 2)]
            for (y, m), v in grp.items() if pd.notna(v)]


def cmd_longterm(args):
    as_json = getattr(args, "json", False)
    uni = get_universe()
    cn = uni["L-CN"]
    sectors = cn["sectors"]
    bench = cn["benchmark"].replace("(proxy)", "")
    w = _weekly_closes([s["ticker"] for s in sectors] + [bench])

    bw = w[bench].dropna()
    bench_last_date = str(bw.index[-1].date()) if len(bw) else None

    # 基准指标（超额 CAGR 用）
    bench_cagr = {lbl: _trailing_cagr(bw, n) for lbl, n in CAGR_WINDOWS}
    bench_annual = _annual_returns_pct(bw)

    rows = []
    for sec in sectors:
        t = sec["ticker"]
        if t not in w.columns:
            continue
        s = w[t].dropna()
        if len(s) < 2:
            continue
        cur_px = float(s.iloc[-1])
        last_dt = s.index[-1]
        ath_px = float(s.max())
        ath_dt = s.idxmax()                      # 首次触及历史最高的周
        dd_pct = round((cur_px / ath_px - 1.0) * 100.0, 2)
        yrs_since = round((last_dt - ath_dt).days / 365.25, 2)

        ma = s.rolling(LT_MA_WEEKS, min_periods=LT_MA_WEEKS).mean()
        ma_cur = ma.iloc[-1]
        vs_ma = round((cur_px / float(ma_cur) - 1.0) * 100.0, 2) if pd.notna(ma_cur) else None

        cagr = {lbl: _trailing_cagr(s, n) for lbl, n in CAGR_WINDOWS}
        excess = {}
        for lbl in EXCESS_WINDOWS:
            sc, bc = cagr.get(lbl), bench_cagr.get(lbl)
            excess[lbl] = round(sc - bc, 2) if (sc is not None and bc is not None) else None

        rows.append({
            "ticker": t,
            "name": sec["name"],
            "ath_date": str(ath_dt.date()),
            "ath_price": round(ath_px, 2),
            "cur_price": round(cur_px, 2),
            "last_date": str(last_dt.date()),
            "drawdown_pct": dd_pct,              # 负值=低于前高
            "years_since_ath": yrs_since,
            "vs_ma200w_pct": vs_ma,
            "below_ma200w": bool(vs_ma is not None and vs_ma < 0),
            "months_below_ma200w": _months_below_ma(s, ma),
            "cagr_pct": cagr,
            "excess_cagr_vs_hs300_pct": excess,
            "stagnation": _stagnation_level(dd_pct, yrs_since),
        })

    # 沉寂榜：距前高年数降序
    rows.sort(key=lambda r: -(r["years_since_ath"] if r["years_since_ath"] is not None else -1))

    # 年度收益矩阵（2006 → 今年度；缺史年份为 null）
    this_year = datetime.now().year
    years = list(range(LT_MATRIX_START_YEAR, this_year + 1))
    sector_annual = {r["ticker"]: _annual_returns_pct(w[r["ticker"]]) for r in rows}
    matrix = {
        "years": years,
        "sectors": {r["ticker"]: [sector_annual.get(r["ticker"], {}).get(y) for y in years]
                    for r in rows},
        "benchmark": [bench_annual.get(y) for y in years],
        "note": f"今年度({this_year})为年初至今未完年收益",
    }

    # CAGR 排名（5Y/10Y 绝对值降序；并列参考超额）
    def _rank(lbl):
        items = [(r, r["cagr_pct"].get(lbl)) for r in rows if r["cagr_pct"].get(lbl) is not None]
        items.sort(key=lambda p: -p[1])
        return [{"ticker": r["ticker"], "name": r["name"], "cagr_pct": v,
                 "excess_pct": r["excess_cagr_vs_hs300_pct"].get(lbl)}
                for r, v in items]

    out = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "layer": "L-CN",
        "universe": "申万一级行业指数(新浪源)",
        "benchmark": {"ticker": bench, "name": "沪深300"},
        "last_trading_date": max((r["last_date"] for r in rows), default=None),
        "benchmark_last_date": bench_last_date,
        "stagnation_rules": {
            "deep": f"回撤>{abs(STAG_DEEP_DD):.0f}% 且距前高≥{STAG_DEEP_YEARS:.0f}年",
            "mid": f"回撤>{abs(STAG_MID_DD):.0f}% 且距前高≥{STAG_MID_YEARS:.0f}年",
            "none": "其余",
        },
        "ma200w_weeks": LT_MA_WEEKS,
        "sectors": rows,
        "annual_returns": matrix,
        "cagr_ranking": {"5Y": _rank("5Y"), "10Y": _rank("10Y")},
        "drawdown_curves": {r["ticker"]: _monthly_drawdown_curve(w[r["ticker"]].dropna())
                            for r in rows},
    }

    if as_json:
        print(json.dumps(out, ensure_ascii=False))
        return 0

    # 人读表格
    print(f"\n===== L-CN 申万一级 长周期体检（基准 {bench}，最后交易日 {out['last_trading_date']}）=====")
    print(f"{'排名':<4}{'行业':<12}{'代码':<8}{'ATH日期':<12}{'回撤%':>8}{'距前高年':>9}"
          f"{'vs200周MA%':>11}{'低于月数':>9}  {'分级'}")
    print("-" * 96)
    for i, r in enumerate(rows, 1):
        vm = f"{r['vs_ma200w_pct']:+.1f}" if r["vs_ma200w_pct"] is not None else "-"
        print(f"{i:<4}{r['name']:<12}{r['ticker']:<8}{r['ath_date']:<12}"
              f"{r['drawdown_pct']:>8.1f}{r['years_since_ath']:>9.1f}{vm:>11}"
              f"{r['months_below_ma200w']:>9}  {STAG_LEVEL_CN[r['stagnation']]}")

    print(f"\n--- CAGR%（基准同窗：{bench}）---")
    print(f"{'行业':<12}{'代码':<8}{'1Y':>8}{'3Y':>8}{'5Y':>8}{'10Y':>8}  {'5Y超额':>8}{'10Y超额':>8}")
    print("-" * 80)
    for r in sorted(rows, key=lambda r: (r["cagr_pct"]["5Y"] or -999), reverse=True):
        def fmt(v):
            return f"{v:>+8.1f}" if v is not None else f"{'-':>8}"
        e5 = r["excess_cagr_vs_hs300_pct"]["5Y"]
        e10 = r["excess_cagr_vs_hs300_pct"]["10Y"]
        c = r["cagr_pct"]
        print(f"{r['name']:<12}{r['ticker']:<8}"
              + "".join(fmt(c[k]) for k in ("1Y", "3Y", "5Y", "10Y"))
              + "  " + "".join(fmt(x) for x in (e5, e10)))

    yr_head = "行业      " + "".join(f"{y % 100:>4}" for y in years)
    print(f"\n--- 年度收益矩阵 %（{years[0]}→{this_year}，今年未完年）---")
    print(yr_head)
    print("-" * (10 + 4 * len(years)))
    name_w = 12
    for r in rows:
        vals = matrix["sectors"][r["ticker"]]
        line = f"{r['name']:<{name_w}}"
        for v in vals:
            line += f"{v:>4.0f}" if v is not None else f"{'·':>4}"
        print(line)
    line = f"{'沪深300':<{name_w}}"
    for v in matrix["benchmark"]:
        line += f"{v:>4.0f}" if v is not None else f"{'·':>4}"
    print(line)
    print(f"\n说明：分级规则 {out['stagnation_rules']['deep']}；{out['stagnation_rules']['mid']}。"
          f"10Y 超额需基准满 10 年历史（当前库内 {bench} 自 "
          f"{str(bw.index[0].date()) if len(bw) else '-'} 起）。")
    return 0


# ── dashboard：单文件自包含 plotly HTML ───────────────────────────────────────

_CSS = """
body{font-family:'Microsoft YaHei','PingFang SC',sans-serif;margin:24px auto;max-width:1180px;
     color:#222;background:#fafafa;}
h1{font-size:26px;border-bottom:3px solid #2c5f8a;padding-bottom:8px;}
h2{font-size:20px;color:#2c5f8a;margin-top:36px;}
table.quad{border-collapse:collapse;width:100%;font-size:14px;background:#fff;}
table.quad th{background:#2c5f8a;color:#fff;padding:6px 8px;text-align:left;}
table.quad td{border-bottom:1px solid #ddd;padding:5px 8px;}
tr.Leading td:nth-child(4){color:#c0392b;font-weight:bold;}
tr.Lagging td:nth-child(4){color:#7f8c8d;font-weight:bold;}
footer{margin-top:40px;padding:14px;border-top:2px solid #ccc;font-size:12.5px;color:#555;
       line-height:1.8;background:#fff;}
.badge{display:inline-block;background:#eef;border-radius:4px;padding:1px 7px;margin-right:6px;
       font-size:12px;color:#22508a;}
.sig{color:#b34700;font-weight:bold;}
"""

_QUAD_CN_FULL = {"Leading": "Leading 领涨", "Improving": "Improving 改善",
                 "Weakening": "Weakening 走弱", "Lagging": "Lagging 滞后"}


def _rrg_figure(res, layer_title):
    """单层 RRG 散点图：尾迹 TAIL_WEEKS 周 + 100 分界线 + 四象限标注。"""
    import plotly.graph_objects as go
    fig = go.Figure()
    for s in res["sectors"]:
        tr = s["trail"][-TAIL_WEEKS:]
        if len(tr) < 2:
            continue
        tx = [p["x"] for p in tr]
        ty = [p["y"] for p in tr]
        hover = [f"{s['name']} ({s['ticker']})<br>{p['date']}<br>X={p['x']} Y={p['y']}" for p in tr]
        fig.add_trace(go.Scatter(
            x=tx, y=ty, mode="lines+markers", name=f"{s['name']} {s['ticker']}",
            text=hover, hoverinfo="text", line={"width": 1.4}, marker={"size": 4}))
        fig.add_trace(go.Scatter(
            x=[tx[-1]], y=[ty[-1]], mode="markers+text", name=s["name"],
            text=[f"{s['name']}"], textposition="top center",
            textfont={"size": 11}, marker={"size": 10, "symbol": "diamond",
                                           "color": "#c0392b" if s["quadrant"] == "Leading" else "#2c5f8a"},
            hovertemplate=f"{s['name']} ({s['ticker']})<br>X=%{{x}} Y=%{{y}}"
                          f"<br>{_QUAD_CN_FULL[s['quadrant']]}<extra></extra>"))
    xr = [min([p["x"] for s in res["sectors"] for p in s["trail"]] + [95]),
          max([p["x"] for s in res["sectors"] for p in s["trail"]] + [105])]
    yr = [min([p["y"] for s in res["sectors"] for p in s["trail"]] + [95]),
          max([p["y"] for s in res["sectors"] for p in s["trail"]] + [105])]
    pad_x = (xr[1] - xr[0]) * 0.06
    pad_y = (yr[1] - yr[0]) * 0.06
    fig.add_vline(x=100, line_dash="dash", line_color="#888")
    fig.add_hline(y=100, line_dash="dash", line_color="#888")
    # 四象限角落标签（锚定在图区内角）
    for ax, ay, xa, ya, lab, col in (
            (xr[1], yr[1], "right", "top", "Leading 领涨", "#2e7d32"),
            (xr[1], yr[0], "right", "bottom", "Improving 改善(获得动能)", "#1565c0"),
            (xr[0], yr[1], "left", "top", "Weakening 走弱", "#ef6c00"),
            (xr[0], yr[0], "left", "bottom", "Lagging 滞后", "#616161")):
        fig.add_annotation(x=ax, y=ay, xanchor=xa, yanchor=ya, text=lab,
                           showarrow=False, font={"size": 11, "color": col})
    fig.update_layout(title=f"{layer_title}｜相对轮动图 RRGM（最后周 {res['last_week']}，尾迹 {TAIL_WEEKS} 周）",
                      xaxis_title="RS-Ratio（52 周滚动 z-score×100）",
                      yaxis_title="RS-Momentum（12 周动量 z-score×100）",
                      height=520, showlegend=False, template="plotly_white",
                      margin={"l": 60, "r": 30, "t": 60, "b": 50})
    fig.update_xaxes(range=[xr[0] - pad_x, xr[1] + pad_x])
    fig.update_yaxes(range=[yr[0] - pad_y, yr[1] + pad_y])
    return fig


def _heatmap_figure(all_res):
    """3M（及 1/6/12M）超额动量热力图：行=板块，列=时间窗。"""
    import plotly.graph_objects as go
    rows, ys, zs = [], [], []
    for ly in LAYERS:
        for s in all_res["layers"][ly]["sectors"]:
            rows.append(f"{ly}|{s['name']} {s['ticker']}")
            zs.append([s["excess_mom"][k] for k in ("1M", "3M", "6M", "12M")])
    zs_T = [list(col) for col in zip(*zs)] if zs else [[0] * len(rows)] * 4
    fig = go.Figure(go.Heatmap(
        z=zs_T, y=["1M", "3M", "6M", "12M"], x=rows,
        colorscale="RdYlGn", zmid=0,   # 低=红 高=绿：正超额动量为绿
        hovertemplate="%{x}<br>%{y} 超额动量: %{z}%<extra></extra>"))
    fig.update_layout(title="板块超额动量热力图（相对各层基准，%）— 行=板块，列=回看窗口",
                      height=430, template="plotly_white",
                      margin={"l": 50, "r": 20, "t": 60, "b": 130})
    fig.update_xaxes(tickangle=-60, tickfont={"size": 10})
    return fig


def _quad_table_html(res, layer):
    rows = []
    order = {"Leading": 0, "Improving": 1, "Weakening": 2, "Lagging": 3}
    for s in sorted(res["sectors"], key=lambda s: order[s["quadrant"]]):
        arrow = "→" if s["signal"] != "持续" else "＝"
        sig = f'<span class="sig">{arrow} 轮动</span>' if s["signal"] != "持续" else ""
        rows.append(
            f"<tr class='{s['quadrant']}'><td>{s['name']}</td><td>{s['ticker']}</td>"
            f"<td>{s['x']} / {s['y']}</td>"
            f"<td>{_QUAD_CN_FULL[s['quadrant']]}</td>"
            f"<td>{(_QUAD_CN_FULL[s['prev_quadrant']] if s['prev_quadrant'] else '-')}</td>"
            f"<td>{arrow}</td><td>{sig}</td>"
            f"<td>3M 超额 {s['excess_mom']['3M']}%</td>"
            f"<td>排名 #{s['rank_3m_excess']}</td></tr>")
    return (f"<h2>{layer} 象限归属（本周 X/Y，基准 {res['benchmark_label']}）</h2>"
            "<table class='quad'><tr><th>板块</th><th>代码</th><th>X / Y</th><th>本周象限</th>"
            "<th>上周象限</th><th>迁移</th><th>信号</th><th>3M 超额动量</th><th>3M 排名</th></tr>"
            + "".join(rows) + "</table>")


def cmd_dashboard(args):
    uni = get_universe()
    all_res = {"generated_at": datetime.now().isoformat(timespec="seconds"), "layers": {}}
    for layer in LAYERS:
        info = uni[layer]
        bench = info["benchmark"].replace("(proxy)", "")
        all_res["layers"][layer] = compute_layer(
            layer, info["sectors"], bench, bench_label=info["benchmark"])

    import plotly.graph_objects as go  # noqa: F401 确保可用
    parts = [
        "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>",
        "<title>FengInvest 全球板块轮动仪表盘</title>",
        f"<style>{_CSS}</style></head><body>",
        "<h1>FengInvest 全球板块轮动仪表盘</h1>",
        "<div><span class='badge'>RS-Ratio：板块/基准价格比 · 52 周滚动 z-score×100</span>",
        "<span class='badge'>RS-Momentum：12 周动量 · 52 周滚动 z-score×100</span>",
        "<span class='badge'>象限：右上 Leading｜右下 Improving｜左上 Weakening｜左下 Lagging</span></div>",
    ]
    first = True
    titles = {"L-US": "① L-US 美国 SPDR 行业", "L-GLOBAL": "② L-GLOBAL 全球行业(iShares)",
              "L-CN": "③ L-CN 中国申万一级行业"}
    for ly in LAYERS:
        fig = _rrg_figure(all_res["layers"][ly], titles[ly])
        parts.append(fig.to_html(full_html=False,
                                 include_plotlyjs="inline" if first else False,
                                 config={"displaylogo": False}))
        first = False
    parts.append("<h2>④ 动量热力图与象限归属表</h2>")
    parts.append(_heatmap_figure(all_res).to_html(full_html=False, include_plotlyjs=False,
                                                  config={"displaylogo": False}))
    for ly in LAYERS:
        parts.append(_quad_table_html(all_res["layers"][ly], titles[ly]))

    # 页脚：数据新鲜度 + 来源
    foot = ["<footer><b>数据新鲜度</b>："]
    for ly in LAYERS:
        foot.append(f"<br>· {titles[ly].split(' ')[0]} 最后交易日 "
                    f"<b>{all_res['layers'][ly]['last_date']}</b>"
                    f"（基准 {all_res['layers'][ly]['benchmark_label']}，"
                    f"覆盖 {all_res['layers'][ly]['weeks_used']} 周："
                    f"{all_res['layers'][ly]['first_week']} ~ {all_res['layers'][ly]['last_week']}）")
        if all_res["layers"][ly]["excluded"]:
            ex = "; ".join(f"{e['ticker']}({e['reason']})" for e in all_res["layers"][ly]["excluded"])
            foot.append(f"<br>&nbsp;&nbsp;<span style='color:#b00'>排除：{ex}</span>")
    foot.append("<br><b>数据源</b>：美股/全球 ETF = yfinance（auto_adjust=False）；"
                "A 股申万行业 = 新浪财经·申万一级行业指数（akshare index_hist_sw）。"
                "<br><b>算法</b>：RRG 相对轮动（参考 MIT 协议 deeleeramone/RRG-Dashboard 计算方式，自建实现）。"
                "<br><b>生成时间</b>：" + datetime.now().strftime("%Y-%m-%d %H:%M:%S") +
                " · FengInvest fengsector.py 自动生成，仅供内部研究。</footer></body></html>")
    parts.extend(foot)

    os.makedirs(os.path.dirname(DASHBOARD_HTML), exist_ok=True)
    html = "\n".join(parts)
    with open(DASHBOARD_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    size_kb = os.path.getsize(DASHBOARD_HTML) / 1024
    print(json.dumps({"dashboard": DASHBOARD_HTML, "size_kb": round(size_kb, 1)},
                     ensure_ascii=False, indent=2))
    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────

def cmd_universe(args):
    uni = get_universe()
    print(json.dumps({k: {"market": v["market"], "benchmark": v["benchmark"],
                          "n_sectors": len(v["sectors"]), "sectors": v["sectors"],
                          "source": v["source"]}
                     for k, v in uni.items()}, ensure_ascii=False, indent=2))
    return 0


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="FengInvest 全球板块轮动模块")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("universe", help="打印三层数量与清单 JSON").set_defaults(func=lambda a: cmd_universe(a))
    pu = sub.add_parser("update", help="拉数入库（幂等增量）")
    pu.add_argument("--retest-global", action="store_true", help="强制重测 GLOBAL 候选")
    pu.set_defaults(func=cmd_update)
    pa = sub.add_parser("analyze", help="stdout 打印各层象限表+轮动信号 JSON")
    pa.add_argument("--json", action="store_true",
                    help="stdout 输出纯 JSON（无表格/进度文本，结构稳定供程序解析）")
    pa.set_defaults(func=cmd_analyze)
    pd_ = sub.add_parser("dashboard", help="生成 SECTOR-DASHBOARD.html").set_defaults(func=cmd_dashboard)
    pl = sub.add_parser("longterm", help="L-CN 申万 31 行业长周期体检（只读库）：沉寂榜/CAGR/年度矩阵/水下曲线")
    pl.add_argument("--json", action="store_true",
                    help="stdout 输出纯 JSON（沉寂榜+年度收益矩阵+CAGR排名+回撤月度采样）")
    pl.set_defaults(func=cmd_longterm)
    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
