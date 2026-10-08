#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/backtest_core.py — FengInvest 通用共享回测引擎库（纯库）

零第三方回测框架：仅 stdlib + numpy；scipy 为可选懒加载（本库默认不用）。
数据源：本地 data/market_data.db（daily_data.index_id -> indices(id,ticker,name,market,category)），
        close = 前复权收盘价；无数据时返回缺失标记，不联网。

对照参考：
- tools/fengbacktest.py 的成本口径：FEE_RATE=0.0015 + SLIPPAGE=0.001 = 单边 0.25%（25 bps）；
  一次"买入->持有->卖出"为双向，round-trip = 50 bps。
- research/110-strategy-verification/001-above-annual-line/audit.md 铁律一（判据错位教训）：
  主判据必须是论断承诺的量（如"平均收益"），胜率仅作辅助。

设计要点：
- signal_split / forward_returns 均向量化（K x N 面板），防前视：
  信号在 t 日收盘判定（close[t] vs 均线[t]，均线只用 t 及之前数据），
  持有自次一交易日（entry_lag=1）起，收益 = close[t+lag+h] / close[t+lag] - 1。
- to_results_json 输出的"事实包" JSON schema 是
  research/110-strategy-verification/000-FORMAT-SAMPLE-白话卡.md（白话卡）填数的【唯一来源】：
  白话卡里的"关键数字/协议红绿灯"一律从这里取数，不得临时另算。

主要公开 API：
  load_bars / signal_split / forward_returns / group_diff / bootstrap_significance /
  cost_apply / sample_out_split / protocol_flags / to_results_json   （见各函数 docstring）

用法示例：
  from tools.backtest_core import load_bars, signal_split, forward_returns, to_results_json
  bars = load_bars(markets=["US"], categories=("stock",))
  sig  = signal_split(bars.close, window=200)
  res  = forward_returns(bars.close, sig, holds=[20, 60, 120])
  pack = to_results_json(bars, window=200, holds=[20, 60, 120], bootstrap=True)

冒烟自测（真跑本地 DB，非占位）：
  python tools/backtest_core.py              # 默认：US/stock，window=200，holds=[20,60,120]
"""
import json
import math
import os
import sqlite3
from datetime import datetime, timezone

import numpy as np

__all__ = [
    "load_bars", "signal_split", "forward_returns", "group_diff",
    "bootstrap_significance", "cost_apply", "sample_out_split",
    "protocol_flags", "to_results_json", "Bars",
]

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "data", "market_data.db")

# ---- 成本口径（与 tools/fengbacktest.py 一致）----
FEE_RATE = 0.0015     # 单边佣金+规费比例
SLIPPAGE = 0.001       # 单边滑点比例
SINGLE_SIDE_BPS = int(round((FEE_RATE + SLIPPAGE) * 10000))   # 25 bps = 单边 0.25%

# ---- 显著性自助法 ----
BOOT_CAP = 200_000     # 单组样本数超过该阈值 -> bootstrap 退化为解析正态近似
SCHEMA_VERSION = "1.0"
SCHEMA_DESC = ("该 schema 是'白话卡'(research/110-strategy-verification/"
               "000-FORMAT-SAMPLE-白话卡.md)填数的唯一来源")


# =====================================================================
# 数据加载
# =====================================================================
class Bars(object):
    """前复权收盘价面板。

    - tickers : list[str]          按行排序的标的代码（与 close 行一一对应）
    - dates   : list[str]          并集交易日（按日期升序，与 close 列一一对应）
    - close   : np.ndarray (K,N)   float64；缺失/停牌一律 nan
    - meta    : {ticker: {name, market, category}}
    - markets/categories : 实际加载的范围
    - as_long(tickers=None, pandas=False, limit=None) -> 长表
      （pandas=False 返回 list[dict]，纯 stdlib；pandas=True 且已安装则返回 DataFrame）
    """
    __slots__ = ("tickers", "dates", "close", "meta", "markets", "categories")

    def __init__(self, tickers, dates, close, meta, markets, categories):
        self.tickers = list(tickers)
        self.dates = list(dates)
        self.close = np.asarray(close, dtype=np.float64)
        self.meta = meta
        self.markets = sorted(markets) if markets else []
        self.categories = sorted(categories) if categories else []

    @property
    def shape(self):
        return self.close.shape

    def market_rows(self, market):
        """返回该市场对应的行下标（int list）。"""
        return [k for k, t in enumerate(self.tickers) if self.meta.get(t, {}).get("market") == market]

    def as_long(self, tickers=None, pandas=False, limit=None):
        """导出长表：{ticker, date, close} 逐行（nan 剔除）。"""
        rows = []
        sel = range(len(self.tickers)) if tickers is None else \
            [self.tickers.index(t) for t in tickers]
        emitted = 0
        for k in sel:
            tk = self.tickers[k]
            row_close = self.close[k]
            for j, d in enumerate(self.dates):
                v = row_close[j]
                if v == v and v is not None and not np.isnan(v):
                    rows.append({"ticker": tk, "date": d, "close": float(v)})
                    emitted += 1
                    if limit and emitted >= limit:
                        break
            if limit and emitted >= limit:
                break
        if pandas:
            try:
                import pandas as pd
                return pd.DataFrame(rows, columns=["ticker", "date", "close"])
            except ImportError:
                return rows
        return rows


def load_bars(markets=None, categories=("stock", "etf", "index"),
              min_rows=360, db_path=None):
    """从本地 DB 加载前复权收盘面板（K x N numpy 矩阵，缺失为 nan）。

    - markets : None=全部市场；或 ['US','CN',...]（按 indices.market 过滤）
    - categories : 过滤 category（默认股票/ETF/指数，排除 macro 等不可投资项）
    - min_rows : 仅保留日线 > 该阈值的标的（默认 360，确保 window+最长持有期 有有效样本）
    - db_path : 默认 data/market_data.db；DB 不存在返回 None

    注：默认 markets=None 会加载全部市场，内存偏大（约 50M 格）；建议按市场传参。
    """
    if db_path is None:
        db_path = DB
    if not os.path.exists(db_path):
        return None
    con = sqlite3.connect(db_path)
    try:
        q = "SELECT id, ticker, name, market, category FROM indices WHERE category IN (%s)" % \
            ",".join("?" * len(categories))
        params = list(categories)
        if markets:
            q += " AND market IN (%s)" % ",".join("?" * len(markets))
            params += list(markets)
        rows = con.execute(q, params).fetchall()
        # 各 index 的日线条数
        cnt = dict(con.execute(
            "SELECT index_id, COUNT(*) FROM daily_data GROUP BY index_id").fetchall())
        keep = [(i, t, n, m, c) for (i, t, n, m, c) in rows if cnt.get(i, 0) >= min_rows]

        # 排序：稳定行序（按 ticker）
        keep.sort(key=lambda r: r[1])
        tickers = [r[1] for r in keep]
        meta = {r[1]: {"name": r[2], "market": r[3], "category": r[4]} for r in keep}
        ids = [r[0] for r in keep]

        # 日期列=仅这些保留标的的并集交易日（不能用全市场并集：会把 CN/JP 及美股指数
        # 早至 1927 的交易日算进来，导致美股行过度稀疏、年线几乎无法定义）
        ph = ",".join("?" * len(ids))
        dates = sorted(d for (d,) in con.execute(
            "SELECT DISTINCT date FROM daily_data WHERE index_id IN (%s)" % ph, ids))
        n_days = len(dates)
        col = {d: j for j, d in enumerate(dates)}
        panel = np.full((len(keep), n_days), np.nan, dtype=np.float64)

        # 分批读每个标的的 close（避免一次性全表）
        for k, iid in enumerate(ids):
            sub = con.execute(
                "SELECT date, close FROM daily_data WHERE index_id=? AND close IS NOT NULL",
                (iid,)).fetchall()
            for d, c in sub:
                j = col.get(d)
                if j is not None:
                    panel[k, j] = c
        markets_used = sorted({meta[t]["market"] for t in tickers})
    finally:
        con.close()
    return Bars(tickers, dates, panel, meta, markets_used, list(categories))


# =====================================================================
# 信号与收益
# =====================================================================
def _panel_ma(close, window):
    """滑动均线（按行、逐列 i 用 close[i-window+1..i]，缺失值按有效个数降权）。"""
    K, N = close.shape
    valid = ~np.isnan(close)
    ma = np.full_like(close, np.nan)
    if N < window:
        return ma
    c = np.where(valid, close, 0.0)
    cumc = np.cumsum(c, axis=1)
    cumv = np.cumsum(valid.astype(np.float64), axis=1)
    # 列 i (window-1..N-1)：和 = cumc[i] - cumc[i-window]
    seg_end = cumc[:, window - 1:] - np.concatenate(
        [np.zeros((K, 1)), cumc[:, :N - window]], axis=1)
    cnt = cumv[:, window - 1:] - np.concatenate(
        [np.zeros((K, 1)), cumv[:, :N - window]], axis=1)
    ok = cnt >= window
    ma[:, window - 1:] = np.where(ok, seg_end / np.where(ok, cnt, 1.0), np.nan)
    return np.where(valid, ma, np.nan)


def signal_split(close, window=200, entry_lag=1):
    """计算年线(滑动均线)上下信号。返回 dict：
        {"above": bool, "ma": float, "defined": bool, "window": int, "entry_lag": int}
    - above[t] = close[t] >= ma[t]（True=站上均线）
    - defined[t]：均线可用（warmup 后且 close 有效）——只有 defined 的日期才进入分组
    - 防前视：均线只用 t 及以前数据；持有自次一交易日（entry_lag）起。
    close 支持 1D（单标的）或 2D (K,N)。
    """
    c = np.asarray(close, dtype=np.float64)
    squeezed = (c.ndim == 1)
    if squeezed:
        c = c[None, :]
    ma = _panel_ma(c, window)
    valid = ~np.isnan(c)
    defined = valid & ~np.isnan(ma)
    above = np.zeros(c.shape, dtype=bool)
    above[defined] = (c >= ma)[defined]
    if squeezed:
        return {"above": above[0], "ma": ma[0], "defined": defined[0],
                "window": int(window), "entry_lag": int(entry_lag)}
    return {"above": above, "ma": ma, "defined": defined,
            "window": int(window), "entry_lag": int(entry_lag)}


def _aggregate(rets):
    """单组收益聚合（rets 为十进制小数数组）。返回 {n, mean%, median%, win_rate%}。"""
    r = rets[~np.isnan(rets)]
    n = int(r.size)
    if n == 0:
        return {"n": 0, "mean": None, "median": None, "win_rate": None}
    return {
        "n": n,
        "mean": round(float(np.mean(r)) * 100, 4),        # %
        "median": round(float(np.median(r)) * 100, 4),    # %
        "win_rate": round(float(np.mean(r > 0)) * 100, 4) # %
    }


def forward_returns(close, signal, holds=(20, 60, 120), entry_lag=None,
                    cost_bps=0, cost_sides=2, return_arrays=False):
    """按年线上/下分组计算前视收益（防前视：起始=信号日次一交易日）。

    - close : (K,N) 或 (N,) 前复权收盘面板
    - signal : signal_split 的返回 dict（或直接 bool 数组：True=站上）
    - holds : 持有交易日数列表
    - entry_lag : 信号日 -> 建仓日延迟（默认取 signal 的 entry_lag=1）
    - cost_bps / cost_sides : >0 时对每个收益扣成本（round-trip=单边bps*边数）
    - return_arrays : True 时额外给出十进制原始收益数组（bootstrap 用）

    返回：list[dict]，每个持有期一项：
      {hold, above:{n,mean,median,win_rate}, below:{...}, diff:{...},
       cost_bps_total, _arrays?:{above,below}（十进制）}
    收益聚合均为 %；diff 为百分点(pp)。
    """
    c = np.asarray(close, dtype=np.float64)
    squeezed = (c.ndim == 1)
    if squeezed:
        c = c[None, :]
    K, N = c.shape

    if isinstance(signal, dict):
        above = np.asarray(signal["above"], dtype=bool)
        defined = np.asarray(signal["defined"], dtype=bool)
        if squeezed:
            above, defined = above[None, :], defined[None, :]
        lag = int(entry_lag if entry_lag is not None else signal.get("entry_lag", 1))
    else:
        above = np.asarray(signal, dtype=bool)
        if squeezed:
            above = above[None, :]
        defined = ~np.isnan(c)
        lag = int(entry_lag if entry_lag is not None else 1)

    cost = (float(cost_bps) * int(cost_sides)) / 10000.0   # 十进制
    cost_total = int(cost_bps) * int(cost_sides)
    out = []
    for h in holds:
        L = N - h - lag            # 可用样本的列数（signal 日 0..L-1）
        if L <= 0:
            out.append({"hold": int(h), "above": _aggregate(np.array([])),
                        "below": _aggregate(np.array([])),
                        "diff": {"mean_diff_pp": None, "median_diff_pp": None,
                                 "win_rate_diff_pp": None},
                        "cost_bps_total": cost_total})
            continue
        base = c[:, lag:N - h]                 # 建仓收盘（信号日+lag）
        exit_ = c[:, lag + h:N]                # 平仓收盘
        sig = above[:, :L] & defined[:, :L]    # 有效信号日
        valid = (base == base) & (base > 0) & (exit_ == exit_)
        fwd = np.full_like(base, np.nan)
        fwd[valid] = exit_[valid] / base[valid] - 1.0
        if cost > 0:
            fwd[valid] = fwd[valid] - cost
        a = fwd[sig & valid]                      # above 组（defined 且站上）
        bel = defined[:, :L] & ~above[:, :L]      # below 组（defined 且未站上）
        b = fwd[bel & valid]
        agg = {
            "hold": int(h),
            "above": _aggregate(a),
            "below": _aggregate(b),
            "diff": {
                "mean_diff_pp": _pp(a.mean() - b.mean()) if a.size and b.size else None,
                "median_diff_pp": _pp(np.median(a) - np.median(b)) if a.size and b.size else None,
                "win_rate_diff_pp": _pp(np.mean(a > 0) - np.mean(b > 0)) if a.size and b.size else None,
            },
            "cost_bps_total": cost_total,
        }
        if return_arrays:
            agg["_arrays"] = {"above": a, "below": b}
        out.append(agg)
    return out


def _pp(x):
    """十进制差 -> 百分点，保留 4 位。"""
    return round(float(x) * 100, 4)


def group_diff(above, below):
    """收益差（上-下）。支持两种输入：
    - 两个 1D 十进制收益数组（均值/中位/胜率差，返回 pp）
    - 两个 forward_returns 的聚合 dict（直接取 % 字段相减）
    返回 {"n_above","n_below","mean_diff_pp","median_diff_pp","win_rate_diff_pp"}。
    """
    if isinstance(above, dict) and "mean" in above:
        ga, gb = above, below
        return {
            "n_above": int(ga.get("n") or 0),
            "n_below": int(gb.get("n") or 0),
            "mean_diff_pp": round(float(ga["mean"] - gb["mean"]), 4) if ga["mean"] is not None and gb["mean"] is not None else None,
            "median_diff_pp": round(float(ga["median"] - gb["median"]), 4) if ga["median"] is not None and gb["median"] is not None else None,
            "win_rate_diff_pp": round(float(ga["win_rate"] - gb["win_rate"]), 4) if ga["win_rate"] is not None and gb["win_rate"] is not None else None,
        }
    a = np.asarray(above, dtype=np.float64).ravel()
    b = np.asarray(below, dtype=np.float64).ravel()
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    if a.size == 0 or b.size == 0:
        return {"n_above": int(a.size), "n_below": int(b.size),
                "mean_diff_pp": None, "median_diff_pp": None, "win_rate_diff_pp": None}
    return {
        "n_above": int(a.size), "n_below": int(b.size),
        "mean_diff_pp": _pp(a.mean() - b.mean()),
        "median_diff_pp": _pp(np.median(a) - np.median(b)),
        "win_rate_diff_pp": _pp(np.mean(a > 0) - np.mean(b > 0)),
    }


# =====================================================================
# 统计推断
# =====================================================================
def bootstrap_significance(above, below, n_iter=2000, seed=42, stride=None):
    """对「上-下」平均收益差做显著性（95%CI + p 值）。

    - above/below : 1D 十进制收益数组（来自 forward_returns 的 _arrays）
    - n_iter : 自助法迭代数（仅在样本量小到足以重抽样时使用）
    - seed : 随机种子（可复现）
    - stride : 非重叠/降采样选项——对逐日高度重叠的样本，传入 >1 的步长
              （每隔 stride 取一个样本），输出时会注明该方法降低了样本重叠。

    抽样路径：单组样本总数 ≤ BOOT_CAP(200k) 时用真实重抽样，CI=2.5/97.5 分位数，
              双侧 p=2*min(P(diff<=0), P(diff>=0))，并注明重叠会低估 p；
              样本量过大时退化为解析正态近似（其标准误恰等于 bootstrap SE，
              大样本两者一致），note 中如实标注。
    返回：{method, mean_diff_pp, ci95_low_pp, ci95_high_pp, p_value, significant,
          n_above, n_below, note}
    """
    a = np.asarray(above, dtype=np.float64).ravel()
    b = np.asarray(below, dtype=np.float64).ravel()
    a = a[~np.isnan(a)]
    b = b[~np.isnan(b)]
    if a.size < 2 or b.size < 2:
        return {"method": "n<2", "mean_diff_pp": None, "ci95_low_pp": None,
                "ci95_high_pp": None, "p_value": None, "significant": None,
                "n_above": int(a.size), "n_below": int(b.size),
                "note": "任一组样本 <2，无法做推断"}
    if stride and stride > 1:
        a = a[::int(stride)]
        b = b[::int(stride)]
    mean_diff = float(a.mean() - b.mean())

    # 自举（小样本路径）
    if a.size + b.size <= BOOT_CAP:
        rng = np.random.default_rng(seed)
        diffs = np.empty(n_iter)
        for i in range(n_iter):
            diffs[i] = rng.choice(a, size=a.size, replace=True).mean() \
                     - rng.choice(b, size=b.size, replace=True).mean()
        lo, hi = np.percentile(diffs, [2.5, 97.5])
        p = 2 * min(np.mean(diffs <= 0), np.mean(diffs >= 0))
        method = "bootstrap（重抽样 %d 次）" % n_iter
        note = ("样本为逐日滚动信号、持仓期高度重叠 → CI 偏窄、p 被低估；"
                "键入 stride>1 降采样或改用非重叠抽样可缓解")
    else:
        # 大样本解析近似：bootstrap SE = sqrt(var_a/na + var_b/nb)（CLT）
        se = math.sqrt(np.var(a) / a.size + np.var(b) / b.size)
        z = abs(mean_diff) / se if se > 0 else float("inf")
        p = min(1.0, math.erfc(z / math.sqrt(2.0))) if math.isfinite(z) else 0.0
        lo, hi = mean_diff - 1.96 * se, mean_diff + 1.96 * se
        method = "bootstrap 解析近似（n 过大=%d，SE=样本标准误，与重抽样一致）" \
                 % (a.size + b.size)
        note = ("样本量过大改用解析近似（bootstrap SE）；重叠样本可能低估真实不确定性，"
                "如需更严可降采样后重跑")
    significant = (hi < 0) or (lo > 0)   # 95%CI 不跨 0
    return {
        "method": method, "mean_diff_pp": round(mean_diff * 100, 4),
        "ci95_low_pp": round(float(lo) * 100, 4),
        "ci95_high_pp": round(float(hi) * 100, 4),
        "p_value": round(float(p), 4), "significant": bool(significant),
        "n_above": int(a.size), "n_below": int(b.size), "note": note,
    }


def cost_apply(rets, cost_bps=25, sides=2):
    """给收益数组扣交易成本（cost_apply(收益, 单边bps, 边数)）。

    默认 cost_bps=25（=FEE_RATE 0.15% + SLIPPAGE 0.1%，单边，与 fengbacktest 一致），
    sides=2 表示 round-trip（买入一次+卖出一次），每个收益扣 0.50%。
    返回扣减后的十进制收益数组。
    """
    r = np.asarray(rets, dtype=np.float64)
    cost = (float(cost_bps) * int(sides)) / 10000.0
    return r - cost


def sample_out_split(dates, frac=0.2):
    """训练/样本外切分说明：样本外=时间上最后 frac（默认 20%）。

    返回：{method, frac, cut_index, train:{start,end,days}, oos:{start,end,days},
          note}。样本外数据在训练期不参与任何参数/筛选，用于独立验证。
    """
    ds = sorted(set(dates))
    n = len(ds)
    cut = int(round(n * (1.0 - frac)))
    cut = max(1, min(n - 1, cut))
    return {
        "method": "chronological-last-%.0f%%" % (frac * 100),
        "frac": round(frac, 4), "cut_index": cut,
        "train": {"start": ds[0], "end": ds[cut - 1], "days": cut},
        "oos": {"start": ds[cut], "end": ds[-1], "days": n - cut},
        "note": "样本外=按时间序列最后的 %.0f%% 个交易日；训练段不得使用样本外信息" % (frac * 100),
    }


# =====================================================================
# 协议红绿灯与统一事实包
# =====================================================================
def protocol_flags(pack=None, *, criterion="mean_return", cost_bps=None,
                   bootstrap_done=False, significance_ok=None,
                   oos_frac=None, oos_done=False, survivor_done=False):
    """回测标准协议逐项红绿灯（✅/⚠️/❌），对照 backtest-methodology.md 铁律一~三。

    - pack : 可传入 to_results_json 的产物，自动从 meta 推断 cost_bps/criterion等
    - criterion : 主判据（默认 mean_return=以平均收益为判据，胜率仅辅助）
    - cost_bps : 0=未计成本
    - bootstrap_done / significance_ok : 是否做了显著性、结果是否显著(方向符合)
    - oos_frac / oos_done : 样本外切分比例 / 是否实际在样本外重跑
    - survivor_done : 幸存者审计（默认 False，如实标"未做"）
    返回 list[{"item","flag","detail"}]。
    """
    if pack is not None:
        meta = pack.get("meta", {})
        if cost_bps is None:
            cost_bps = meta.get("cost_bps", 0)
        if "criterion" in meta:
            criterion = meta["criterion"]
        if "oos_frac" in pack.get("sample_out", {}):
            oos_frac = pack["sample_out"].get("frac")
    flags = []

    if criterion == "mean_return":
        flags.append({"item": "判据对齐（主判据=论断承诺的量）", "flag": "✅",
                      "detail": "以平均收益为唯一主判据，胜率仅作辅助（铁律一，audit #1 教训）"})
    elif criterion == "win_rate":
        flags.append({"item": "判据对齐（主判据=论断承诺的量）", "flag": "⚠️",
                      "detail": "主判据=胜率；仅当论断本就承诺'胜率'时才可采信"})
    else:
        flags.append({"item": "判据对齐（主判据=论断承诺的量）", "flag": "❌",
                      "detail": "未知判据 %r；必须与论断声称的量一致" % criterion})

    if cost_bps and cost_bps > 0:
        flags.append({"item": "数据口径：复权 / 交易成本", "flag": "✅",
                      "detail": "前复权 close + 计入交易成本（单边 %d bps）" % cost_bps})
    else:
        flags.append({"item": "数据口径：复权 / 交易成本", "flag": "⚠️",
                      "detail": "成本未计入（cost_bps=0）或未知——换手策略未计成本会夸大超额"})

    if bootstrap_done:
        if significance_ok is True:
            flags.append({"item": "显著性：效果量 + 统计检验", "flag": "✅",
                          "detail": "Bootstrap 给出 95%CI 与 p，p<0.05 且方向符合论断"})
        elif significance_ok is False:
            flags.append({"item": "显著性：效果量 + 统计检验", "flag": "⚠️",
                          "detail": "已做 Bootstrap 但 p≥0.05 或 CI 跨 0 / 幅度低于噪音地板"})
        else:
            flags.append({"item": "显著性：效果量 + 统计检验", "flag": "⚠️",
                          "detail": "已做 Bootstrap，方向与幅度需人工核对"})
    else:
        flags.append({"item": "显著性：效果量 + 统计检验", "flag": "❌",
                      "detail": "未做显著性检验（无 p / 无 CI）——差异不足以排除运气"})

    if oos_done:
        flags.append({"item": "样本外验证（回测期后 %s）" % (("%.0f%%" % (oos_frac * 100)) if oos_frac else "?"),
                      "flag": "✅", "detail": "已在独立样本外段重跑验证"})
    elif oos_frac:
        flags.append({"item": "样本外验证（回测期后 %.0f%%）" % (oos_frac * 100),
                      "flag": "⚠️", "detail": "已给出切分说明，但尚未在样本外重跑（调用方负责）"})
    else:
        flags.append({"item": "样本外验证", "flag": "❌", "detail": "未提供/未做样本外验证"})

    if survivor_done:
        flags.append({"item": "幸存者审计（含已退市股票）", "flag": "✅",
                      "detail": "已说明股票池是否含退市股并评估影响"})
    else:
        flags.append({"item": "幸存者审计（含已退市股票）", "flag": "❌",
                      "detail": "未做：股票池是否含退市股未标明——可能高估收益"})
    return flags


def _flags_summary(flags):
    if any(f["flag"] == "❌" for f in flags):
        return "❌"
    if any(f["flag"] == "⚠️" for f in flags):
        return "⚠️"
    return "✅"


def _hold_block(close, signal, h, entry_lag, cost_bps, cost_sides, bootstrap, n_iter, seed):
    """单个持有期的完整结果块（含聚合、差、显著性）。"""
    fr = forward_returns(close, signal, holds=[h], entry_lag=entry_lag,
                         cost_bps=cost_bps, cost_sides=cost_sides, return_arrays=True)[0]
    diff = fr["diff"]
    bs = None
    if bootstrap and fr["_arrays"]["above"].size and fr["_arrays"]["below"].size:
        bs = bootstrap_significance(fr["_arrays"]["above"], fr["_arrays"]["below"],
                                    n_iter=n_iter, seed=seed)
    block = {
        "hold": int(h), "window": int(signal["window"]), "entry_lag": int(entry_lag),
        "above": fr["above"], "below": fr["below"],
        "diff": diff,
        "bootstrap": bs,
        "cost_bps_total": fr["cost_bps_total"],
    }
    return block


def to_results_json(bars, *, window=200, holds=(20, 60, 120), entry_lag=1,
                    cost_bps=25, cost_sides=2, bootstrap=True, n_iter=2000, seed=42,
                    oos_frac=0.2, survivor_done=False, markets=None, note=""):
    """生成统一「事实包」JSON（per-market + 汇总 + 协议区）。

    ⚠️ 该 schema 是"白话卡"(research/110-strategy-verification/000-FORMAT-SAMPLE-白话卡.md)
       填数的【唯一来源】：白话卡的"关键数字 / 协议红绿灯"一律从这里取，不得临时另算。

    结构：
      {schema, schema_version, description, generated_utc,
       meta: {window, holds, entry_lag, cost_bps, cost_sides, criterion, cost_note},
       universe: {markets, categories, n_tickers, dates:{first,last,days}},
       sample_out: {...}(oos_frac 时给出),
       per_market: {市场: {n_tickers, by_hold: {hold: block}}},
       summary: {by_hold: {hold: block}},          # 所处理市场的 pooled 汇总
       protocol: {flags, summary, notes},
       note}
    收益字段单位均为 %（mean/median/win_rate），diff 为 pp；
    bootstrap.mean_diff/ci/p 亦为 %/pp 口径；significant = CI 不跨 0。
    """
    if bars is None:
        return {"error": "bars 为空（DB 不存在或无数据）"}
    c = bars.close
    K, N = c.shape
    mkts = sorted(bars.markets if markets is None else
                  [m for m in markets if m in bars.markets])

    meta = {
        "engine": "backtest_core", "schema_version": SCHEMA_VERSION,
        "window": int(window), "holds": [int(h) for h in holds],
        "entry_lag": int(entry_lag), "cost_bps": int(cost_bps),
        "cost_sides": int(cost_sides),
        "criterion": "mean_return",   # 主判据=平均收益（铁律一）
        "adjusted": "close=前复权", "cost_bps_total": int(cost_bps) * int(cost_sides),
        "cost_note": "成本口径= fengbacktest: FEE_RATE 0.0015 + SLIPPAGE 0.001 = 单边 %.0f%%；"
                     "round-trip = 双边 %.0f%%" % (
                         (FEE_RATE + SLIPPAGE) * 100, (FEE_RATE + SLIPPAGE) * 200),
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    universe = {
        "markets": mkts, "categories": bars.categories, "n_tickers": K,
        "dates": {"first": bars.dates[0], "last": bars.dates[-1], "days": N},
    }

    sample_out = sample_out_split(bars.dates, frac=oos_frac) if oos_frac else None

    per_market = {}
    for m in mkts:
        rows = bars.market_rows(m)
        if not rows:
            continue
        sub = c[rows]
        smx = signal_split(sub, window=window, entry_lag=entry_lag)
        by_hold = {str(h): _hold_block(sub, smx, h, entry_lag, cost_bps, cost_sides,
                                       bootstrap, n_iter, seed)
                   for h in holds}
        per_market[m] = {"n_tickers": len(rows),
                         "by_hold": {str(h): {k: v for k, v in blk.items()}
                                     for h, blk in by_hold.items()}}
    # 汇总（跨处理市场 pooled）
    sm_all = signal_split(c, window=window, entry_lag=entry_lag)
    summary_by_hold = {str(h): _hold_block(c, sm_all, h, entry_lag, cost_bps, cost_sides,
                                           bootstrap, n_iter, seed) for h in holds}

    flags = protocol_flags(criterion="mean_return", cost_bps=cost_bps,
                           bootstrap_done=bootstrap,
                           significance_ok=bootstrap,   # 是否显著由各 hold 的 significant 判定见下
                           oos_frac=oos_frac, oos_done=False,
                           survivor_done=survivor_done)
    # 显著性红绿灯按汇总首个持有期实际推断结果修正
    first = summary_by_hold.get(str(holds[0]))
    if bootstrap and first and first.get("bootstrap"):
        sig = first["bootstrap"].get("significant")
        for f in flags:
            if f["item"].startswith("显著性"):
                f["flag"] = "✅" if sig else "⚠️"
                f["detail"] += " | 汇总 %d 日持有效应显著=%s" % (holds[0], sig)
    protocol = {
        "flags": flags,
        "summary": _flags_summary(flags),
        "notes": [
            "无来源=不存在：每个数字都来自本地 data/market_data.db（前复权 close），不凭训练知识。",
            "收益单位为 %，diff 为 pp；bootstrap.CI 不跨 0 → significant=true。",
            "幸存者审计默认未做：股票池是否含退市股未标明。",
            "重叠样本：逐日滚动信号持仓高度重叠，显著性方向需结合降采样复核。",
        ],
    }
    return {
        "schema": "fenginvest/backtest_core/fact-pack",
        "schema_version": SCHEMA_VERSION,
        "description": SCHEMA_DESC,
        "generated_utc": meta["generated_utc"],
        "meta": meta,
        "universe": universe,
        "sample_out": sample_out,
        "per_market": per_market,
        "summary": {"by_hold": summary_by_hold},
        "protocol": protocol,
        "note": note,
    }


# =====================================================================
# 冒烟自测（真跑本地 DB）
# =====================================================================
def _smoke(verbose=True):
    import time
    t_all = time.time()
    t0 = time.time()
    bars = load_bars(markets=["US"], categories=("stock",))
    if bars is None:
        print("[smoke] ERROR: data/market_data.db 缺失")
        return
    load_t = time.time() - t0
    print("[smoke] load_bars: %.1fs | US/stock n=%d tickers, %d 交易日"
          % (load_t, bars.close.shape[0], bars.close.shape[1]))

    # 内部数值正确性：MA vs 朴素循环
    rng = np.random.default_rng(7)
    tiny = rng.normal(100, 2, 40).cumsum() + 100
    ref = np.array([np.mean(tiny[i - 3 + 1:i + 1]) if i >= 3 - 1 else np.nan
                    for i in range(40)])
    sim = signal_split(tiny, window=3, entry_lag=1)
    r0, s0 = ref[~np.isnan(ref)], sim["ma"][~np.isnan(sim["ma"])]
    ok = r0.size == s0.size and np.allclose(r0, s0)
    print("[smoke] MA 校验(窗口3 vs 朴素循环): %s" % ("OK" if ok else "FAIL"))

    t0 = time.time()
    sig = signal_split(bars.close, window=200, entry_lag=1)
    sig_t = time.time() - t0
    print("[smoke] signal_split(window=200): %.2fs, 有效信号日占比 %.1f%%"
          % (sig_t, 100 * sig["defined"].mean()))

    t0 = time.time()
    res = forward_returns(bars.close, sig, holds=[20, 60, 120], return_arrays=True)
    fr_t = time.time() - t0
    print("\n[smoke] forward_returns(holds=[20,60,120]): %.2fs" % fr_t)
    print("%-8s %-22s %-22s %-14s %-10s" % ("持有期", "年线上 平均收益", "年线下 平均收益", "平均收益差", "n(上/下)"))
    for it in res:
        a, b = it["above"], it["below"]
        print("%-8d %-22s %-22s %+11.3fpp  %d/%d" % (
            it["hold"],
            ("%+.3f%% (n=%d)" % (a["mean"], a["n"])),
            ("%+.3f%% (n=%d)" % (b["mean"], b["n"])),
            (it["diff"]["mean_diff_pp"] if it["diff"]["mean_diff_pp"] is not None else float("nan")),
            a["n"], b["n"]))

    # bootstrap 示例（取 60 日持有）
    it60 = res[1]
    t0 = time.time()
    bs = bootstrap_significance(it60["_arrays"]["above"], it60["_arrays"]["below"],
                                n_iter=2000, seed=42)
    bs_t = time.time() - t0
    print("\n[smoke] bootstrap(hold=60): %.2fs %s" % (bs_t, bs["method"]))
    print("  mean_diff=%+.3fpp  CI95=[%+.3f, %+3.3f]  p=%.4f  significant=%s"
          % (bs["mean_diff_pp"], bs["ci95_low_pp"], bs["ci95_high_pp"],
             bs["p_value"], bs["significant"]))

    # cost 方向 sanity
    net = cost_apply(np.array([0.01, 0.02]), cost_bps=SINGLE_SIDE_BPS, sides=2)
    assert abs(net[0] - (0.01 - 0.005)) < 1e-9
    print("[smoke] cost_apply round-trip 25bps*2 扣减 OK:", net.tolist())

    # 协议红绿灯
    flg = protocol_flags(criterion="mean_return", cost_bps=25, bootstrap_done=True,
                         significance_ok=bs["significant"], oos_frac=0.2, oos_done=False)
    print("\n[smoke] protocol_flags:")
    for f in flg:
        print("  %s %s — %s" % (f["flag"], f["item"], f["detail"]))

    # 统一事实包
    t0 = time.time()
    pack = to_results_json(bars, window=200, holds=[20, 60, 120],
                           cost_bps=SINGLE_SIDE_BPS, cost_sides=2, bootstrap=True, seed=42)
    pack_t = time.time() - t0
    print("\n[smoke] to_results_json: %.2fs | schema=%s v%s\n  summary 首个持有期: %s"
          % (pack_t, pack["schema"], pack["schema_version"],
             json.dumps(pack["summary"]["by_hold"]["20"], ensure_ascii=False)))
    print("  samples: per_market=%s protocol.summary=%s"
          % (sorted(pack["per_market"].keys()), pack["protocol"]["summary"]))
    print("\n[smoke] 总计 %.1fs" % (time.time() - t_all))


def main():
    """入口：不带参数跑完整冒烟（US/stock）；带 --market 只打印上/下收益表。"""
    import argparse
    ap = argparse.ArgumentParser(description="backtest_core 冒烟自测（真跑本地 DB）")
    ap.add_argument("--market", default=None, help="指定市场（如 HK/CN）则只打印收益表；缺省跑完整冒烟")
    ap.add_argument("--category", default="stock")
    ap.add_argument("--window", type=int, default=200)
    ap.add_argument("--holds", default="20,60,120")
    args = ap.parse_args()
    if args.market is None:
        _smoke()
        return 0
    b = load_bars(markets=[args.market], categories=(args.category,))
    if b is None:
        print("no data"); return 1
    import time
    t0 = time.time()
    sig = signal_split(b.close, window=args.window, entry_lag=1)
    res = forward_returns(b.close, sig, holds=[int(x) for x in args.holds.split(",")],
                          return_arrays=True)
    print("%s/%s | window=%d | 耗时 %.2fs" % (args.market, args.category, args.window,
                                              time.time() - t0))
    print("%-8s %-18s %-18s %-14s" % ("持有期", "年线上平均收益", "年线下平均收益", "平均收益差"))
    for it in res:
        print("%-8d %+13.3f%%  %+13.3f%%  %+10.3fpp" % (
            it["hold"], it["above"]["mean"], it["below"]["mean"],
            it["diff"]["mean_diff_pp"] if it["diff"]["mean_diff_pp"] is not None else float("nan")))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
