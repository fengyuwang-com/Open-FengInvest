#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
backtest_param_verify.py — 待验证参数回测验证（2026-08-16）

验证 knowledge/methodology/rule-literature-map.md 第五章注册表两条待验证参数：
  a. 钱仓滚存波动率加权（SOON 触发线 15% → 高波动市况降至 10%/8%）
  b. TRADING 止损阈值 -20% 的学术锚（网格 -10/-15/-20/-25%，按动量/震荡分层）

数据源：本地 data/market_data.db（免联网），close=复权价（与 unadj_close 对照已核）。
方法：
  - 股票级：逐笔（per-entry）仿真，每 21 交易日网格入场，持有 252 日（止损测试）/ 504 日（滚存测试）。
  - 指数级：全路径 NAV 仿真（年化收益/夏普/最大回撤/胜率直接出），含 lag=1（T+1 执行）稳健性。
  - 动量环境：入场日指数 MA50>MA200 为动量（MOM），否则震荡（NOM）；CN=000001.SS / HK=^HSI / US=^GSPC。
  - 滚存高波动：指数 60 日已实现波动率 > 其过去 252 日 80 分位（滚动窗口，无前视）。
  - 成本：单边 0.15% 佣金+规费 + 0.1% 滑点 = 0.25%（与 fengbacktest FEE_RATE+SLIPPAGE 一致）；
    未含 A 股印花税（与 fengbacktest 引擎口径一致，已知限制）。
  - 执行口径：收盘触发、同日收盘执行（lag=0，主口径）；指数级附 lag=1 稳健性。
  - 无前视：MA200/波动率分位/动量状态均只用入场日（含当日）及以前数据。

用法：
  python tools/backtest_param_verify.py             # 全市场
  python tools/backtest_param_verify.py --market CN # 仅 A 股
"""
import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from statistics import NormalDist

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "data", "market_data.db")
OUT_JSON = os.path.join(BASE, "research", "050-strategies",
                        "backtest-param-verify-2026-08-16-results.json")

COST = 0.0025          # 单边 0.15% + 0.1% 滑点（与 fengbacktest 一致）
STOP_LEVELS = (0.10, 0.15, 0.20, 0.25)
INDEX_MAP = {"CN": "000001.SS", "HK": "^HSI", "US": "^GSPC"}
INDEX_LABEL = {"000001.SS": "上证综指", "^HSI": "恒生指数", "^GSPC": "标普500",
               "000300.SS": "沪深300", "SPY": "SPY ETF"}
INDEX_PATH_EXTRA = {"CN": ["000300.SS"], "HK": [], "US": ["SPY"]}


# ─────────────────────────── 数据装载 ───────────────────────────────────────

def movavg(a, w):
    """滑动均值，返回与 a 同长数组（前 w-1 个为 nan）。"""
    out = np.full(len(a), np.nan)
    if len(a) < w:
        return out
    cs = np.cumsum(np.insert(a, 0, 0.0))
    out[w - 1:] = (cs[w:] - cs[:-w]) / w
    return out


def load_series(markets, category):
    """返回 {ticker: (dates, closes_np)}。"""
    con = sqlite3.connect(DB)
    marks = ",".join("?" * len(markets))
    rows = con.execute(
        f"""SELECT i.ticker, d.date, d.close
            FROM daily_data d JOIN indices i ON d.index_id = i.id
            WHERE i.market IN ({marks}) AND i.category = ?
              AND d.close IS NOT NULL AND d.close > 0
            ORDER BY i.ticker, d.date""",
        list(markets) + [category]).fetchall()
    con.close()
    out = {}
    for t, d, c in rows:
        if t not in out:
            out[t] = ([], [])
        out[t][0].append(d)
        out[t][1].append(c)
    return {t: (dates, np.asarray(closes, dtype=float))
            for t, (dates, closes) in out.items() if len(closes) >= 30}


def index_state_maps(index_ticker):
    """返回 (regime_map, volhi_map)：date -> bool。
    regime: 指数 MA50>MA200（动量环境）；volhi: 指数 60 日已实现波动率 > 过去 252 日 80 分位。"""
    con = sqlite3.connect(DB)
    row = con.execute("SELECT id FROM indices WHERE ticker=?", (index_ticker,)).fetchone()
    if not row:
        con.close()
        return {}, {}
    rows = con.execute(
        "SELECT date, close FROM daily_data WHERE index_id=? AND close IS NOT NULL AND close>0 ORDER BY date",
        (row[0],)).fetchall()
    con.close()
    dates = [r[0] for r in rows]
    closes = np.asarray([r[1] for r in rows], dtype=float)
    s = pd.Series(closes, index=dates)
    ma50 = s.rolling(50, min_periods=50).mean()
    ma200 = s.rolling(200, min_periods=200).mean()
    mom = (ma50 > ma200)
    ret = s.pct_change()
    vol60 = ret.rolling(60, min_periods=30).std() * np.sqrt(252)
    p80 = vol60.rolling(252, min_periods=120).quantile(0.8)
    volhi = (vol60 > p80)
    regime_map = {d: bool(v) for d, v in mom.items() if not pd.isna(v)}
    volhi_map = {d: bool(v) for d, v in volhi.items() if not pd.isna(v)}
    return regime_map, volhi_map


# ─────────────────────────── 止损策略（per-entry 路径） ──────────────────────

def _mdd(nav):
    cm = np.maximum.accumulate(nav)
    return float((nav / cm - 1.0).min())


def stop_no_reentry(prof, level):
    """机械止损无再入：收盘跌破 -level 即当日收盘卖出（成本），此后现金 0%。"""
    mask = prof <= -level
    if not mask.any():
        return np.concatenate([[1.0], 1.0 + (1.0 - COST) * prof])
    t = int(np.argmax(mask))                      # prof 索引（第 t+1 日触发）
    nav = np.empty(len(prof) + 1)
    nav[0] = 1.0
    nav[1:t + 2] = 1.0 + (1.0 - COST) * prof[:t + 1]   # 触发日收盘前按持有计
    nav[t + 2:] = nav[t + 1] * (1.0 - COST)            # 当日收盘卖出后现金冻结
    return nav


def stop_reentry(prof, level):
    """Kaminski-Lo 0/1 止损（含再入）：跌破 -level 清仓入现金，回升至 -level 上方再买入。"""
    n = len(prof)
    P = np.empty(n + 1)
    P[0] = 1.0
    P[1:] = 1.0 + prof
    nav = np.ones(n + 1)
    state = 1
    day = 1
    while day <= n:
        if state == 1:
            hits = np.nonzero(P[day:] <= 1.0 - level)[0]
            if len(hits) == 0:
                nav[day:] = nav[day - 1] * (P[day:] / P[day - 1])
                break
            t = day + int(hits[0])
            nav[day:t + 1] = nav[day - 1] * (P[day:t + 1] / P[day - 1])
            nav[t] *= (1.0 - COST)
            day = t + 1
            state = 0
        else:
            hits = np.nonzero(P[day:] >= 1.0 - level)[0]
            if len(hits) == 0:
                nav[day:] = nav[day - 1]
                break
            t = day + int(hits[0])
            nav[day:t + 1] = nav[day - 1]
            nav[t] *= (1.0 - COST)
            day = t + 1
            state = 1
    return nav * (1.0 - COST)                     # 入场成本


def stop_trailing(prof, level):
    """Dai 2020 式追踪止损：止损线 = 历史峰值×(1-level)，收盘跌破即清仓，不再入。"""
    P = np.concatenate([[1.0], 1.0 + prof])
    cm = np.maximum.accumulate(P)
    mask = P[1:] <= cm[1:] * (1.0 - level)
    if not mask.any():
        return np.concatenate([[1.0], 1.0 + (1.0 - COST) * prof])
    t = int(np.argmax(mask))
    nav = np.empty(len(prof) + 1)
    nav[0] = 1.0
    nav[1:t + 2] = 1.0 + (1.0 - COST) * prof[:t + 1]
    nav[t + 2:] = nav[t + 1] * (1.0 - COST)
    return nav


def trend_exit(close_win, ma_win, p0):
    """趋势止损（MA200 代理）：持仓状态 = 收盘≥MA200，跌破清仓、站回再入；
    入场强制首日持仓（隔离"退出规则"本身的效果）。"""
    P = np.concatenate([[1.0], close_win / p0])
    st = (close_win >= ma_win).astype(int)        # 第 1..252 日状态
    full = np.concatenate([[1], st])              # 首日强制持仓
    trans = full[1:] != full[:-1]                 # 第 t 日状态变化 → 当日收盘交易
    rets = P[1:] / P[:-1]
    rets[trans] *= (1.0 - COST)
    nav = np.cumprod(rets)
    return nav * (1.0 - COST)                     # 入场成本


def simulate_stock_stops(C, dates, reg_map, ma200):
    """逐笔止损仿真。返回 {arm: {MOM: [(ret,mdd,win)...], NOM: [...]}}（聚合全部入场）。"""
    n = len(C)
    arms = ["bh"] + ["s%d" % int(L * 100) for L in STOP_LEVELS] + ["kl20", "trail20", "trend"]
    agg = {a: {"MOM": [], "NOM": []} for a in arms}
    n_entries = 0
    for e in range(250, n - 252, 21):
        reg = reg_map.get(dates[e])
        if reg is None:
            continue
        n_entries += 1
        key = "MOM" if reg else "NOM"
        p0 = C[e]
        win = C[e + 1:e + 253]
        prof = win / p0 - 1.0
        bh_nav = (1.0 - COST) * (1.0 + prof)
        bh_ret = bh_nav[-1] - 1.0
        agg["bh"][key].append((bh_ret, _mdd(bh_nav), 1.0 if bh_ret > 0 else 0.0))
        for L in STOP_LEVELS:
            nav = stop_no_reentry(prof, L)
            r = nav[-1] - 1.0
            agg["s%d" % int(L * 100)][key].append((r, _mdd(nav), 1.0 if r > 0 else 0.0))
        nav = stop_reentry(prof, 0.20)
        r = nav[-1] - 1.0
        agg["kl20"][key].append((r, _mdd(nav), 1.0 if r > 0 else 0.0))
        nav = stop_trailing(prof, 0.20)
        r = nav[-1] - 1.0
        agg["trail20"][key].append((r, _mdd(nav), 1.0 if r > 0 else 0.0))
        nav = trend_exit(win, ma200[e + 1:e + 253], p0)
        r = nav[-1] - 1.0
        agg["trend"][key].append((r, _mdd(nav), 1.0 if r > 0 else 0.0))
    return agg, n_entries


# ─────────────────────────── 滚存策略（per-entry 路径） ─────────────────────

def rollover_path(P, volhi_win, variant):
    """滚存单笔路径。P: 504 相对价格（entry=1）；volhi_win: 与 P 对齐的 bool 数组（高波动日）。
    机制：浮盈≥阈值 → 当日收盘卖出足额本金（值=1.0，卖出扣成本），余零成本筹码持有到期。"""
    n = len(P)
    if variant == "BH":
        return (1.0 - COST) * P
    if variant == "FIX15":
        thr = np.full(n, 0.15)
    elif variant == "FIX30":
        thr = np.full(n, 0.30)
    elif variant == "VOLW":
        thr = np.where(volhi_win, 0.10, 0.15)
    elif variant == "VOLW8":
        thr = np.where(volhi_win, 0.08, 0.15)
    else:
        raise ValueError(variant)
    prof = P - 1.0
    mask = prof >= thr
    if not mask.any():
        return (1.0 - COST) * P
    t = int(np.argmax(mask))
    nav = np.empty(n)
    nav[:t + 1] = (1.0 - COST) * P[:t + 1]
    zero_cost_val = nav[t] - 1.0                   # 触发时刻余仓（零成本筹码）价值
    cash = 1.0 - COST                              # 回收本金（扣卖出成本）
    nav[t + 1:] = cash + zero_cost_val * (P[t + 1:] / P[t])
    return nav


def simulate_stock_rollovers(C, volhi_stock, n_horizon=504, step=21, warmup=320):
    """逐笔滚存仿真。volhi_stock: 与 C 同长的 bool 数组（该股交易日的市场高波动标记）。"""
    n = len(C)
    variants = ("BH", "FIX15", "FIX30", "VOLW", "VOLW8")
    agg = {v: {"nav": [], "mdd": [], "tuw": [], "rec": [], "rec_day": [], "trades": []}
           for v in variants}
    n_entries = 0
    for e in range(warmup, n - n_horizon, step):
        n_entries += 1
        P = C[e + 1:e + 1 + n_horizon] / C[e]
        vh = volhi_stock[e + 1:e + 1 + n_horizon]
        for v in variants:
            nav = rollover_path(P, vh, v)
            agg[v]["nav"].append(nav[-1])
            agg[v]["mdd"].append(_mdd(nav))
            agg[v]["tuw"].append(float(np.mean(nav < 1.0)))
            if v == "BH":
                agg[v]["rec"].append(0.0)
                agg[v]["rec_day"].append(None)
                agg[v]["trades"].append(0.0)
                continue
            thr_v = 0.15 if v == "FIX15" else 0.30 if v == "FIX30" else \
                    0.10 if v == "VOLW" else 0.08
            rec = bool((P - 1.0 >= thr_v).any())
            agg[v]["rec"].append(1.0 if rec else 0.0)
            agg[v]["rec_day"].append(None if not rec else int(np.argmax(P - 1.0 >= thr_v)) + 1)
            agg[v]["trades"].append(1.0 if rec else 0.0)
    return agg, n_entries


# ─────────────────────────── 指数级全路径 ──────────────────────────────────

def index_path_strategy(closes, lag):
    """指数级全路径仿真（lag=0 同日收盘执行；lag=1 下一交易日执行）。返回 {arm: nav}。"""
    n = len(closes)
    rel = closes / closes[0]
    out = {"bh": (1.0 - COST) * rel}
    for L in STOP_LEVELS:
        out["s%d" % int(L * 100)] = _index_stop(rel, L, lag, reentry=False)
    out["kl20"] = _index_stop(rel, 0.20, lag, reentry=True)
    out["trail20"] = _index_stop_trail(rel, 0.20, lag)
    out["trend"] = _index_trend(closes, lag)
    return out


def _index_stop(rel, level, lag, reentry):
    """指数级机械止损。rel: 相对价格（首日=1）。触发后入现金；reentry=True 时回升再入。"""
    n = len(rel)
    nav = np.ones(n)
    state = 1
    day = 1
    while day < n:
        if state == 1:
            hits = np.nonzero(rel[day:] <= 1.0 - level)[0]
            if len(hits) == 0:
                nav[day:] = nav[day - 1] * (rel[day:] / rel[day - 1])
                break
            t = day + int(hits[0])
            nav[day:t + 1] = nav[day - 1] * (rel[day:t + 1] / rel[day - 1])
            if lag == 0:
                nav[t] *= (1.0 - COST)
                day = t + 1
            else:
                if t + 1 < n:
                    nav[t + 1] = nav[t] * (1.0 - COST)
                day = t + 2 if t + 1 < n else n
            if not reentry:
                if lag == 0:
                    nav[t + 1:] = nav[t]
                elif t + 1 < n:
                    nav[t + 1:] = nav[t + 1]
                break
            state = 0
        else:
            hits = np.nonzero(rel[day:] >= 1.0 - level)[0]
            if len(hits) == 0:
                nav[day:] = nav[day - 1]
                break
            t = day + int(hits[0])
            nav[day:t + 1] = nav[day - 1]
            if lag == 0:
                nav[t] *= (1.0 - COST)
                day = t + 1
            else:
                if t + 1 < n:
                    nav[t + 1] = nav[t] * (1.0 - COST)
                day = t + 2 if t + 1 < n else n
            state = 1
    return nav * (1.0 - COST)


def _index_stop_trail(rel, level, lag):
    """指数级追踪止损（无再入）。"""
    n = len(rel)
    cm = np.maximum.accumulate(rel)
    mask = rel <= cm * (1.0 - level)
    nav = (1.0 - COST) * rel.copy()
    if not mask.any():
        return nav
    t = int(np.argmax(mask))
    if lag == 0:
        nav[t] *= (1.0 - COST)
        nav[t + 1:] = nav[t]
    elif t + 1 < n:
        nav[t + 1] = nav[t] * (1.0 - COST)
        nav[t + 2:] = nav[t + 1]
    else:
        nav[t] *= (1.0 - COST)
    return nav


def _index_trend(closes, lag):
    """指数级 MA200 趋势（跌破清仓、站回再入）。"""
    n = len(closes)
    ma = movavg(closes, 200)
    st = (closes >= ma).astype(int)
    st[0] = 1
    trans = st[1:] != st[:-1]
    if lag == 1:
        trans = np.concatenate([[False], trans[:-1]])
    rets = closes[1:] / closes[:-1]
    rets[trans] *= (1.0 - COST)
    nav = np.concatenate([[1.0], np.cumprod(rets)])
    return nav * (1.0 - COST)


def metrics_path(nav):
    rets = nav[1:] / nav[:-1] - 1.0
    total = nav[-1] / nav[0] - 1.0
    years = (len(nav) - 1) / 252.0
    ann = (1.0 + total) ** (1.0 / years) - 1.0 if years > 0 else -1.0
    sharpe = (float(np.mean(rets)) / float(np.std(rets, ddof=1)) * np.sqrt(252)) \
        if len(rets) > 2 and np.std(rets, ddof=1) > 0 else 0.0
    return {"total_ret_pct": round(total * 100, 2), "annual_pct": round(ann * 100, 2),
            "sharpe": round(sharpe, 2), "max_dd_pct": round(_mdd(nav) * 100, 2),
            "win_day_pct": round(float(np.mean(rets > 0)) * 100, 2)}


def regime_daily(nav, mom_map, dates):
    """按日环境（指数 MA50>MA200）分解策略日收益均值。"""
    mom_rets, nom_rets = [], []
    for i in range(1, len(nav)):
        m = mom_map.get(dates[i])
        if m is None:
            continue
        r = nav[i] / nav[i - 1] - 1.0
        (mom_rets if m else nom_rets).append(r)
    out = {}
    if mom_rets:
        out["mom_mean_daily_pct"] = round(float(np.mean(mom_rets)) * 100, 3)
        out["mom_days"] = len(mom_rets)
    if nom_rets:
        out["nom_mean_daily_pct"] = round(float(np.mean(nom_rets)) * 100, 3)
        out["nom_days"] = len(nom_rets)
    return out


# ─────────────────────────── 统计与主流程 ──────────────────────────────────

def tstat(deltas):
    d = np.asarray(deltas, dtype=float)
    n = len(d)
    if n < 30:
        return None, None
    mean = float(np.mean(d))
    sd = float(np.std(d, ddof=1))
    if sd == 0:
        return mean, None
    t = mean / (sd / np.sqrt(n))
    p = 2.0 * (1.0 - NormalDist().cdf(abs(t)))
    return mean, p


def stop_stock_stats(agg):
    out = {}
    bh = {k: np.asarray([v[0] for v in agg["bh"][k]]) for k in ("MOM", "NOM")}
    for arm in agg:
        for k in ("MOM", "NOM"):
            vals = agg[arm][k]
            if not vals:
                continue
            rets = np.asarray([v[0] for v in vals])
            wins = np.asarray([v[2] for v in vals])
            mdds = np.asarray([v[1] for v in vals])
            rec = {"n": len(rets),
                   "mean_ret_pct": round(float(np.mean(rets)) * 100, 2),
                   "median_ret_pct": round(float(np.median(rets)) * 100, 2),
                   "win_rate_pct": round(float(np.mean(wins)) * 100, 2),
                   "mean_mdd_pct": round(float(np.mean(mdds)) * 100, 2)}
            if len(rets) > 2 and float(np.std(rets, ddof=1)) > 0:
                rec["sharpe_cross"] = round(float(np.mean(rets)) / float(np.std(rets, ddof=1)), 2)
            if arm != "bh":
                n = min(len(rets), len(bh[k]))
                d_mean, d_p = tstat(rets[:n] - bh[k][:n])
                rec["delta_vs_bh_ret_pct"] = round(d_mean * 100, 2) if d_mean is not None else None
                rec["delta_vs_bh_p"] = round(d_p, 4) if d_p is not None else None
                rec["delta_vs_bh_winrate_pct"] = round(
                    (float(np.mean(wins)) - float(np.mean([v[2] for v in agg["bh"][k]]))) * 100, 2)
                rec["delta_vs_bh_mdd_pct"] = round(
                    (float(np.mean(mdds)) - float(np.mean([v[1] for v in agg["bh"][k]]))) * 100, 2)
            out[f"{arm}|{k}"] = rec
    return out


def rollover_stats(roll):
    out = {}
    for v in roll:
        nav = np.asarray(roll[v]["nav"])
        mdds = np.asarray(roll[v]["mdd"])
        tuw = np.asarray(roll[v]["tuw"])
        rec = np.asarray(roll[v]["rec"])
        rdays = [x for x in roll[v]["rec_day"] if x is not None]
        o = {"n": len(nav),
             "mean_terminal_nav": round(float(np.mean(nav)), 4),
             "median_terminal_nav": round(float(np.median(nav)), 4),
             "terminal_ge1_pct": round(float(np.mean(nav >= 1.0)) * 100, 2),
             "mean_mdd_pct": round(float(np.mean(mdds)) * 100, 2),
             "mean_time_under_water_pct": round(float(np.mean(tuw)) * 100, 2),
             "recovery_rate_pct": round(float(np.mean(rec)) * 100, 2),
             "mean_recovery_day": round(float(np.mean(rdays)), 1) if rdays else None,
             "mean_trades": round(float(np.mean(roll[v]["trades"])), 3)}
        for base in ("BH", "FIX15"):
            if base in roll and len(roll[base]["nav"]) == len(nav):
                d_mean, d_p = tstat(nav - np.asarray(roll[base]["nav"]))
                o[f"delta_vs_{base}_terminal"] = round(d_mean, 4) if d_mean is not None else None
                o[f"delta_vs_{base}_p"] = round(d_p, 4) if d_p is not None else None
        out[v] = o
    return out


def main():
    ap = argparse.ArgumentParser(description="FengInvest 待验证参数回测（2026-08-16）")
    ap.add_argument("--market", choices=["CN", "HK", "US"], default=None)
    args = ap.parse_args()
    markets = [args.market] if args.market else ["CN", "HK", "US"]

    t0 = time.time()
    result = {
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "method": ("per-entry 逐笔仿真（21 交易日网格入场；止损持有 252 日、滚存 504 日）+ 指数级全路径；"
                   "成本 0.25%/单边；close=本地 DB 复权价；动量环境=入场日指数 MA50>MA200；"
                   "滚存高波动=指数 60d 波动率>过去 252 日 80 分位"),
        "markets": {},
    }

    for m in markets:
        stocks = load_series([m], "stock")
        idx = INDEX_MAP[m]
        reg_map, volhi_map = index_state_maps(idx)
        idx_dates, idx_closes = load_series([m], "index").get(idx, ([], np.array([])))
        st_list = stocks
        mr = {"index": {"ticker": idx, "label": INDEX_LABEL[idx],
                        "start": idx_dates[0] if idx_dates else None,
                        "end": idx_dates[-1] if idx_dates else None,
                        "rows": len(idx_dates)}}
        mr["stop"] = {}

        # ── 股票级止损 ──
        stock_agg = None
        usable = 0
        entries = 0
        for t, (dates, C) in st_list.items():
            if len(C) < 502:
                continue
            usable += 1
            agg, ne = simulate_stock_stops(C, dates, reg_map, movavg(C, 200))
            if stock_agg is None:
                stock_agg = {a: {"MOM": [], "NOM": []} for a in agg}
            for a, byreg in agg.items():
                for k in ("MOM", "NOM"):
                    stock_agg[a][k].extend(byreg[k])
            entries += ne
        mr["universe"] = {"stocks_total": len(st_list), "stocks_usable_ge502d": usable,
                          "stop_entries": entries}
        if stock_agg:
            mr["stop"] = {"stock_level": stop_stock_stats(stock_agg)}

        # ── 指数级全路径（含 lag 0/1 与日环境分解）──
        idx_path = {}
        if len(idx_closes) > 250:
            for lag in (0, 1):
                navs = index_path_strategy(idx_closes, lag)
                idx_path[lag] = {}
                for arm, nav in navs.items():
                    met = metrics_path(nav)
                    met.update(regime_daily(nav, reg_map, idx_dates))
                    idx_path[lag][arm] = met
        mr["stop"]["index_level"] = idx_path

        # 附加指数（沪深300 / SPY 等）全路径
        extra_path = {}
        for xt in INDEX_PATH_EXTRA.get(m, []):
            xd, xc = ([], np.array([]))
            for cat in ("index", "etf"):
                got = load_series([m] if m != "US" else ["US"], cat).get(xt)
                if got:
                    xd, xc = got
                    break
            if len(xc) <= 250:
                continue
            extra_path[xt] = {}
            for lag in (0, 1):
                navs = index_path_strategy(xc, lag)
                extra_path[xt][lag] = {}
                for arm, nav in navs.items():
                    met = metrics_path(nav)
                    met.update(regime_daily(nav, reg_map, xd))
                    extra_path[xt][lag][arm] = met
        if extra_path:
            mr["stop"]["index_level_extra"] = extra_path

        # ── 滚存 ──
        roll = {v: {"nav": [], "mdd": [], "tuw": [], "rec": [], "rec_day": [], "trades": []}
                for v in ("BH", "FIX15", "FIX30", "VOLW", "VOLW8")}
        roll_entries = 0
        roll_usable = 0
        for t, (dates, C) in st_list.items():
            if len(C) < 824:
                continue
            roll_usable += 1
            vh_stock = np.asarray([volhi_map.get(d, False) for d in dates])
            agg, ne = simulate_stock_rollovers(C, vh_stock)
            roll_entries += ne
            for v in agg:
                for k in agg[v]:
                    roll[v][k].extend(agg[v][k])
        mr["rollover"] = rollover_stats(roll)
        mr["rollover"]["_entries"] = roll_entries
        mr["rollover"]["_stocks_usable_ge824d"] = roll_usable
        result["markets"][m] = mr

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[OK] 结果已写: {OUT_JSON}  用时 {time.time() - t0:.0f}s")


if __name__ == "__main__":
    sys.exit(main())
