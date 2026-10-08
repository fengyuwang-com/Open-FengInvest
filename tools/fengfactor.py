#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fengfactor.py — 因子验证三件套（IC / 分位收益 / 换手率）

输入：因子 CSV（列 date,ticker,factor，UTF-8；自动嗅探逗号/tab 分隔）；
价格：data/market_data.db 的 daily_data（index_id 关联，经 indices/stkcd_map
映射 ticker；close 为前复权价，收益不含分红，见 meta 注记）。

流程（Alphalens 语义）：
  1. 周期截面（daily/weekly/monthly，默认 weekly）：因子对齐到每周期最后一个
     交易日（as-of 不未来函数）；
  2. 前向收益 = 下周期末 close / 本周期末 close − 1；
  3. IC：每周期 Spearman(因子, 前向收益)，聚合 mean/std/IR/|IC|>0.02 占比/IC>0 占比；
  4. 分位收益：因子按周期截面分位（rank 分位，不去 demean），Q1..Qq 平均前向收益
     + spread(Qq−Q1)，每分位 N；
  5. 换手率：每期 |S_t ∖ S_{t−period}| / |S_t|（分位成员变化）。

小样本护栏：截面 n<50 → 输出警告（建议周/月频率、2 分位数），仍执行。

用法：
  python tools/fengfactor.py --factor data/test_factor.csv
  python tools/fengfactor.py --factor f.csv --prices-db data/market_data.db \
      --period weekly --quantiles 5 --by-ticker
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sqlite3
import sys
from datetime import datetime

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

try:
    from scipy.stats import spearmanr as _scipy_spearman
except ImportError:
    _scipy_spearman = None

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.path.join(BASE, "data", "market_data.db")

MIN_CROSS_SECTION = 50   # 小样本护栏阈值


# --------------------------------------------------------------------------
# 基础统计（numpy 可选，缺失回退纯 Python）
# --------------------------------------------------------------------------
def _mean(xs):
    if not xs:
        return None
    return sum(xs) / len(xs)


def _std(xs):
    if not xs or len(xs) < 2:
        return None
    m = _mean(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def _rankdata(vals):
    """平均秩（ties 取均值）。"""
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    ranks = [0.0] * len(vals)
    i = 0
    n = len(vals)
    while i < n:
        j = i
        while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(x, y):
    n = len(x)
    mx, my = _mean(x), _mean(y)
    cov = sum((x[i] - mx) * (y[i] - my) for i in range(n))
    sx = (sum((x[i] - mx) ** 2 for i in range(n))) ** 0.5
    sy = (sum((y[i] - my) ** 2 for i in range(n))) ** 0.5
    if sx == 0 or sy == 0:
        return None
    return cov / (sx * sy)


def spearman(x, y):
    """Spearman 秩相关；scipy 可用用 scipy，否则纯 Python 回退。"""
    n = len(x)
    if n < 2:
        return None
    if _scipy_spearman is not None:
        res = _scipy_spearman(x, y)
        r = getattr(res, "statistic", res[0] if isinstance(res, tuple) else None)
        if r is None or (isinstance(r, float) and r != r):
            return None
        return float(r)
    rx, ry = _rankdata(x), _rankdata(y)
    return _pearson(rx, ry)


# --------------------------------------------------------------------------
# 输入加载
# --------------------------------------------------------------------------
def load_factor_csv(path):
    """因子 CSV → (rows, meta)。自动嗅探分隔符（逗号/tab）。"""
    with open(path, encoding="utf-8") as f:
        content = f.read()
    if not content.strip():
        raise ValueError(f"因子文件为空: {path}")
    first_line = content.splitlines()[0]
    delim = None
    if "\t" in first_line and "," not in first_line:
        delim = "\t"
    else:
        try:
            delim = csv.Sniffer().sniff(first_line, delimiters=",;\t").delimiter
        except csv.Error:
            delim = ","
    reader = csv.DictReader(io.StringIO(content), delimiter=delim)
    cols = {c.strip().lower(): c for c in (reader.fieldnames or [])}
    for need in ("date", "ticker", "factor"):
        if need not in cols:
            raise ValueError(
                f"因子文件缺少列 '{need}'（实际列: {list(cols)}；支持逗号/tab 分隔）")
    rows = []
    n_skipped = 0
    for r in reader:
        d = (r.get(cols["date"]) or "").strip()
        t = (r.get(cols["ticker"]) or "").strip()
        try:
            v = float(r.get(cols["factor"]))
        except (TypeError, ValueError):
            n_skipped += 1
            continue
        parsed = _pdate(d)
        if parsed is None:
            n_skipped += 1
            continue
        rows.append({"date": parsed, "ticker": t, "factor": v})
    if not rows:
        raise ValueError("因子文件无有效行（需 date,ticker,factor 三列非空）")
    rows.sort(key=lambda r: (r["ticker"], r["date"]))
    return rows, {"delimiter": repr(delim), "n_rows": len(rows), "n_skipped": n_skipped}


def _pdate(s):
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def load_prices(db_path, tickers):
    """ticker → [(date, close)]（index_id 关联 daily_data）。

    返回 (prices, unmapped, mapping_note)。ticker 解析顺序：
      stkcd_map.stkcd == t → stkcd_map.ticker == t → indices.ticker == t(大写)。
    """
    if not os.path.exists(db_path):
        return {}, list(tickers), f"价格库不存在: {db_path}"
    con = sqlite3.connect(db_path)
    try:
        stkcd_map = con.execute("SELECT stkcd, index_id, ticker FROM stkcd_map").fetchall()
        indices = con.execute("SELECT id, ticker FROM indices").fetchall()
        by_stkcd = {s: (iid, t) for s, iid, t in stkcd_map if iid}
        by_ticker = {t: iid for _, iid, t in stkcd_map if iid}
        by_ticker.update({tk: i for i, tk in indices})   # 方向：ticker → index_id
        by_ticker_upper = {t.upper(): iid for t, iid in by_ticker.items()}
        resolved = {}
        unmapped = []
        for t in tickers:
            iid = None
            if t in by_stkcd:
                iid = by_stkcd[t][0]
            elif t in by_ticker:
                iid = by_ticker[t]
            elif t.upper() in by_ticker_upper:
                iid = by_ticker_upper[t.upper()]
            if iid is None:
                unmapped.append(t)
                continue
            resolved[t] = iid
        prices = {}
        for t, iid in resolved.items():
            cur = con.execute(
                "SELECT date, close FROM daily_data WHERE index_id = ? AND close IS NOT NULL "
                "ORDER BY date", (iid,))
            prices[t] = [(_pdate(d), c) for d, c in cur.fetchall() if _pdate(d) is not None]
        note = f"价格库 {db_path}；ticker→index_id 经 stkcd_map/indices 映射"
        return prices, unmapped, note
    finally:
        con.close()


# --------------------------------------------------------------------------
# 周期面板构建
# --------------------------------------------------------------------------
def _period_key(d, period):
    if period == "daily":
        return d.isoformat()
    if period == "weekly":
        y, w, _ = d.isocalendar()
        return f"{y}-W{w:02d}"
    y, m = d.year, d.month
    return f"{y}-{m:02d}"


def build_panel(factors, prices, period, ic_lag, start, end):
    """构建面板行：[{period_end, ticker, factor, fwd_ret}]。

    - 每 ticker 价格按周期取最后交易日 close；
    - 前向收益 = 下一周期末 close / 本周期末 close − 1（最后一周期无收益，丢弃）；
    - 因子取该 ticker 周期末之前最后一条观测（as-of 对齐）；
    - ic_lag>0：因子取全局周期序列前移 ic_lag 期（IC 用历史因子 vs 当前收益）。
    """
    # ticker → {period_end: close}
    by_period = {}
    for t, px in prices.items():
        pd = {}
        for d, c in sorted(px):
            k = _period_key(d, period)
            if k not in pd or d > pd[k][0]:
                pd[k] = (d, c)
        by_period[t] = pd
    # ticker → 因子 as-of 序列（周期末 → 因子值）
    factor_by = {}
    for t, fl in factors.items():
        fdict = {}
        for d, v in fl:
            fdict.setdefault(d, v)
        fdates = sorted(fdict)
        fvals = [fdict[d] for d in fdates]
        fd_asc = fdates
        factor_by[t] = (fd_asc, fvals)
    # 全局周期序列（按 period_end 排序去重）
    all_ends = set()
    for pd in by_period.values():
        all_ends.update(e for e, _ in pd.values())
    global_ends = sorted(all_ends)
    end_index = {e: i for i, e in enumerate(global_ends)}

    def factor_asof(t, end):
        fd, fv = factor_by.get(t, (None, None))
        if fd is None:
            return None
        # 二分找最后一个 <= end 的因子日
        lo, hi = 0, len(fd)
        while lo < hi:
            mid = (lo + hi) // 2
            if fd[mid] <= end:
                lo = mid + 1
            else:
                hi = mid
        return fv[lo - 1] if lo > 0 else None

    rows = []
    for t, pd in by_period.items():
        seq = sorted(pd.values())          # [(period_end, close), ...] 按结束日升序
        for idx, (end_date, c) in enumerate(seq):
            if idx + 1 >= len(seq):
                continue                   # 无下一周期 → 无前向收益
            fwd = seq[idx + 1][1] / c - 1.0
            i = end_index[end_date]
            lag_idx = i - ic_lag
            lag_end = global_ends[lag_idx] if lag_idx >= 0 else None
            f = factor_asof(t, lag_end if lag_end is not None else end_date)
            if f is None:
                continue
            rows.append({"period_end": end_date, "ticker": t, "factor": f,
                         "fwd_ret": fwd})
    if start:
        rows = [r for r in rows if r["period_end"] >= start]
    if end:
        rows = [r for r in rows if r["period_end"] <= end]
    return rows


# --------------------------------------------------------------------------
# 三件套计算
# --------------------------------------------------------------------------
def _quantile_labels(values, q):
    """rank 分位：值排序后按位置均分为 1..q（不去 demean）。"""
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    labels = [None] * n
    for pos, i in enumerate(order):
        qq = min(q, (pos * q) // n + 1)
        labels[i] = qq
    return labels


def compute_ic(panel, quantiles):
    """a. 周期日频 Spearman IC + 聚合统计。返回 (stats, per_period, warnings)。"""
    warnings = []
    per_period = {}
    for r in panel:
        per_period.setdefault(r["period_end"], []).append(r)
    ic_list = []
    ic_rows = []
    small_n = 0
    for pend in sorted(per_period):
        grp = per_period[pend]
        n = len(grp)
        if n < 2:
            continue
        if n < MIN_CROSS_SECTION:
            small_n += 1
        x = [r["factor"] for r in grp]
        y = [r["fwd_ret"] for r in grp]
        r = spearman(x, y)
        if r is None:
            continue
        ic_list.append(r)
        ic_rows.append({"period_end": pend.isoformat(), "n": n, "ic": round(r, 6)})
    if small_n:
        warnings.append(
            f"{small_n} 个周期截面 n<{MIN_CROSS_SECTION}（小样本，IC 不稳定）；"
            "建议周/月频率、--quantiles 2，并参考每期 n 与 N")
    stats = {
        "mean": round(_mean(ic_list), 6) if ic_list else None,
        "std": round(_std(ic_list), 6) if ic_list else None,
        "ir": None,
        "abs_gt_002_pct": None,
        "positive_pct": None,
        "n_periods": len(ic_list),
    }
    if ic_list:
        stats["ir"] = (round(_mean(ic_list) / _std(ic_list), 4)
                       if _std(ic_list) not in (None, 0) else None)
        stats["abs_gt_002_pct"] = round(
            sum(1 for r in ic_list if abs(r) > 0.02) / len(ic_list) * 100, 2)
        stats["positive_pct"] = round(
            sum(1 for r in ic_list if r > 0) / len(ic_list) * 100, 2)
    return stats, ic_rows, warnings


def compute_quantiles(panel, quantiles):
    """b. 分位收益（不去 demean）+ c. 换手率。返回 (quantile_stats, turnover, warnings)。"""
    warnings = []
    per_period = {}
    for r in panel:
        per_period.setdefault(r["period_end"], []).append(r)
    q_means = {q: [] for q in range(1, quantiles + 1)}
    q_n = {q: 0 for q in range(1, quantiles + 1)}
    q_members = {q: {} for q in range(1, quantiles + 1)}   # q -> period -> set(tickers)
    prev_members = None
    turn_sums = {q: 0.0 for q in range(1, quantiles + 1)}
    turn_counts = {q: 0 for q in range(1, quantiles + 1)}
    n_periods_used = 0
    for pend in sorted(per_period):
        grp = per_period[pend]
        n = len(grp)
        if n < quantiles:
            warnings.append(f"周期 {pend} 截面 n={n} < quantiles={quantiles}，该期跳过分位计算")
            continue
        vals = [r["factor"] for r in grp]
        labels = _quantile_labels(vals, quantiles)
        members = {q: set() for q in range(1, quantiles + 1)}
        for r, qq in zip(grp, labels):
            members[qq].add(r["ticker"])
        for q in range(1, quantiles + 1):
            sel = [r for r, qq in zip(grp, labels) if qq == q]
            q_means[q].append(_mean([r["fwd_ret"] for r in sel]))
            q_n[q] += len(sel)
            q_members[q][pend] = members[q]
            if prev_members is not None:
                s_t = members[q]
                if s_t:
                    new = len(s_t - prev_members[q])
                    turn_sums[q] += new / len(s_t)
                    turn_counts[q] += 1
        prev_members = members
        n_periods_used += 1
    q_out = []
    for q in range(1, quantiles + 1):
        m = _mean(q_means[q])
        turn = (turn_sums[q] / turn_counts[q]) if turn_counts[q] else None
        q_out.append({"quantile": q, "mean_fwd_return": round(m, 6) if m is not None else None,
                      "n": q_n[q], "turnover": round(turn, 4) if turn is not None else None,
                      "n_turnover_periods": turn_counts[q]})
    spread = None
    if q_out and q_out[0]["mean_fwd_return"] is not None and q_out[-1]["mean_fwd_return"] is not None:
        spread = round(q_out[-1]["mean_fwd_return"] - q_out[0]["mean_fwd_return"], 6)
    overall_turn = _mean([q["turnover"] for q in q_out if q["turnover"] is not None])
    return {"quantiles": q_out, "spread": spread, "n_periods_used": n_periods_used,
            "overall_turnover": round(overall_turn, 4) if overall_turn is not None else None}, warnings


def factor_distribution(rows):
    """--no-forward：只用因子分布（无前向收益）。"""
    vals = [r["factor"] for r in rows]
    n = len(vals)
    dist = {
        "n": n,
        "n_tickers": len({r["ticker"] for r in rows}),
        "min": round(min(vals), 6) if vals else None,
        "max": round(max(vals), 6) if vals else None,
        "mean": round(_mean(vals), 6) if vals else None,
        "std": round(_std(vals), 6) if vals else None,
    }
    return dist


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="fengfactor — 因子验证三件套（IC / 分位收益 / 换手率）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--factor", required=True, help="因子 CSV（列 date,ticker,factor，UTF-8，逗号/tab）")
    ap.add_argument("--prices-db", default=DEFAULT_DB, help="价格库（默认 data/market_data.db）")
    ap.add_argument("--period", choices=["daily", "weekly", "monthly"], default="weekly",
                    help="周期频率（默认 weekly）")
    ap.add_argument("--quantiles", type=int, choices=[2, 5], default=5,
                    help="分位数（默认 5；小样本建议 2）")
    ap.add_argument("--ic-lag", type=int, default=0, help="因子滞后周期数（默认 0）")
    ap.add_argument("--start", help="起始周期末 YYYY-MM-DD（含）")
    ap.add_argument("--end", help="截止周期末 YYYY-MM-DD（含）")
    ap.add_argument("--by-ticker", action="store_true", help="输出逐 ticker IC（诊断）")
    ap.add_argument("--no-forward", action="store_true",
                    help="跳过价格/前向收益，只用因子分布")
    args = ap.parse_args()

    warnings = []
    try:
        rows, fmeta = load_factor_csv(args.factor)
    except ValueError as e:
        return _out({"error": str(e)}, exit_code=1)
    warnings.append(f"因子文件: {args.factor}（{fmeta['n_rows']} 行，分隔符 {fmeta['delimiter']}"
                    + (f"，跳过 {fmeta['n_skipped']} 行无效值" if fmeta["n_skipped"] else "") + "）")

    start_d = _pdate(args.start) if args.start else None
    end_d = _pdate(args.end) if args.end else None
    factors = {}
    for r in rows:
        factors.setdefault(r["ticker"], []).append((r["date"], r["factor"]))

    if args.no_forward:
        out = {"meta": {"period": args.period, "quantiles": args.quantiles,
                        "ic_lag": args.ic_lag, "n_periods": None,
                        "n_obs": len(rows), "n_tickers": len(factors),
                        "price_source": None,
                        "forward": None, "note": "--no-forward：仅因子分布"},
               "distribution": factor_distribution(rows),
               "ic": None, "quantile_returns": None, "warnings": warnings}
        return _out(out)

    prices, unmapped, price_note = load_prices(args.prices_db, list(factors))
    if unmapped:
        warnings.append(f"{len(unmapped)} 个 ticker 无法映射到价格库，已排除: {sorted(unmapped)[:10]}")
    if not prices:
        return _out({"error": f"价格库无可用数据（{price_note}）",
                     "hint": "ticker 需可经 stkcd_map/indices 映射，或使用 --no-forward"},
                    exit_code=1)
    used_tickers = [t for t in factors if t in prices]
    if not used_tickers:
        return _out({"error": "所有 ticker 均无价格映射（检查 ticker 格式，或 --no-forward）",
                     "unmapped": unmapped}, exit_code=1)

    panel = build_panel({t: factors[t] for t in used_tickers}, prices,
                        args.period, args.ic_lag, start_d, end_d)
    if len(panel) < 2:
        return _out({"error": "面板行过少（至少需要 2 个周期末才有前向收益）",
                     "hint": "检查日期范围/周期频率/ticker 映射"}, exit_code=1)

    ic_stats, ic_rows, w1 = compute_ic(panel, args.quantiles)
    qret, w2 = compute_quantiles(panel, args.quantiles)
    warnings += w1 + w2

    meta = {
        "period": args.period,
        "quantiles": args.quantiles,
        "ic_lag": args.ic_lag,
        "n_periods": len({r["period_end"] for r in panel}),
        "n_obs": len(panel),
        "n_tickers_used": len(used_tickers),
        "n_tickers_unmapped": len(unmapped),
        "price_source": args.prices_db,
        "forward": "下周期末 close / 本周期末 close − 1（close 前复权，不含分红）",
        "filter": {"start": start_d.isoformat() if start_d else None,
                   "end": end_d.isoformat() if end_d else None},
        "small_sample_guard": f"截面 n<{MIN_CROSS_SECTION} 警告（已触发则见 warnings）",
    }
    out = {"meta": meta, "ic": {"stats": ic_stats, "per_period": ic_rows},
           "quantile_returns": qret, "warnings": warnings}

    if args.by_ticker:
        bt = []
        per_ticker = {}
        for r in panel:
            per_ticker.setdefault(r["ticker"], []).append(r)
        for t in sorted(per_ticker):
            grp = per_ticker[t]
            if len(grp) < 3:
                bt.append({"ticker": t, "n": len(grp), "ic": None, "note": "期数过少"})
                continue
            r = spearman([g["factor"] for g in grp], [g["fwd_ret"] for g in grp])
            bt.append({"ticker": t, "n": len(grp),
                       "ic": round(r, 6) if r is not None else None})
        out["by_ticker_ic"] = bt
    return _out(out)


def _out(obj, exit_code=0):
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
