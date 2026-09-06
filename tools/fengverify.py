#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FengInvest 论断复测引擎（确定性版）—— v1 最小可用 (MVP)

用途：把 `research/110-strategy-verification/000-claims-def.md` 里登记的论断定义，
     与本地 data/market_data.db 的实际数据逐字对照执行回测，产出机器可读 JSON，
     作为生成「复测版白话卡」的唯一数字来源。

与旧 verify-*.py 的差异（针对 audit 发现的方法缺陷）：
  - 判据：主判据 = **平均收益**（above 组扣成本后均值 − below 组未扣成本均值），
    中位收益辅助，胜率仅参考（原脚本用胜率裁决 = 判据错位）。
  - 复权：直接用 daily_data.close（前复权，见 000-data-biases.md A.1）。
  - 成交：T 日收盘定价信号 → T+1 交易日开始持有（避免当日收盘价又做信号又做成交）。
  - 成本：信号组持有期满卖出扣 25bps 一次；对照组不扣（毛差口径，见 claims-def）。
  - 显著性：市场层面 2000 次股票级 block Bootstrap → 95% CI + p。
  - 样本外：每标的自有交易日后 20% 单独跑同口径。
  - 幸存者口径：如实记录是否含退市（本地库不含 → 已知高估源）。

用法：
  python tools/fengverify.py 1 [--out DIR]
    claim_id: 论断编号（读 000-claims-def.md，当前实现 #1）
    --out:    输出目录（默认 research/110-strategy-verification/RETEST-<id>-<date>）

输出（--out 目录）：
  results.json    机器可读全量结果（per-market + 汇总 + 样本外 + 协议红绿灯）
  （银行卡/audit 由外层按 results.json 撰写）

依赖：numpy（系统已装）；scipy 可选（未使用）。
确定性：bootstrap 固定 RNG 种子 20260820，结果可复现。

铁律（backtest-methodology.md）：
  铁律一 判据=论断指标；铁律二 效应 > 噪音地板 + 显著性；铁律三 数据口径无已知缺陷；
  铁律四 对标权威方法（Brock, Lakonishok & LeBaron 1992：信号 vs 基准 + Bootstrap）。
"""
import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "data", "market_data.db")
DEFS = os.path.join(BASE, "research", "110-strategy-verification", "000-claims-def.md")
RNG_SEED = 20260820
BOOT_ITERS = 2000
OOS_FRAC = 0.20

# 需要支持标准输出中文（Windows 控制台默认 GBK）
sys.stdout.reconfigure(encoding="utf-8")


# --------------------------------------------------------------------------
# 1) 读论断定义（YAML 注册表）
# --------------------------------------------------------------------------
def load_claims_def(path=DEFS):
    """从 000-claims-def.md 提取 ```yaml``` 块并解析为 dict（含 claims 列表）。"""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    try:
        import yaml
    except ImportError:
        print('错误：需要 pyyaml 才能解析 claims 注册表。pip install pyyaml')
        return None
    m = re.search(r"```yaml\s*\n(.*?)\n```", text, re.S)
    if not m:
        print(f"错误：{path} 未找到 ```yaml``` 定义块")
        return None
    return yaml.safe_load(m.group(1))


def find_claim(claims_data, claim_id):
    claims = claims_data.get("claims", []) if claims_data else []
    for c in claims:
        if int(c.get("id")) == int(claim_id):
            return c
    print(f"错误：claims 注册表里没有 id={claim_id} 的定义（{DEFS}）")
    return None


# --------------------------------------------------------------------------
# 2) 数据装载（复用 fengbacktest.load_closes 思路，按 market 批量读）
# --------------------------------------------------------------------------
def load_market_series(market, category="stock"):
    """读某市场全部 category 标的的前复权 close。返回 {index_id: (ticker, dates, closes)}。

    - 按 index_id（FK）装载，天然规避 ticker 形变歧义（ticker.multiple 场景：
      同一代码的 "0700.HK" / "700HK" / "0700" 多种写法在 indices 里可能并存，
      这里只认 id，不需要字符串匹配）。
    - closes 为前复权 close，过滤 NULL / <=0。
    """
    if not os.path.exists(DB):
        print("错误：data/market_data.db 不存在")
        return None
    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT d.index_id, i.ticker, d.date, d.close "
        "FROM daily_data d JOIN indices i ON d.index_id = i.id "
        "WHERE i.market = ? AND i.category = ? AND d.close IS NOT NULL AND d.close > 0 "
        "ORDER BY d.date",
        (market, category),
    ).fetchall()
    con.close()

    out = {}
    meta = {}
    for iid, ticker, date, close in rows:
        meta.setdefault(iid, ticker)
    # 按 index_id 分桶（rows 已按日期排序 → 桶内保持时间序）
    buckets = {}
    for iid, _ticker, date, close in rows:
        buckets.setdefault(iid, []).append((date, close))
    for iid, series in buckets.items():
        dates = [s[0] for s in series]
        closes = np.asarray([s[1] for s in series], dtype=np.float64)
        out[iid] = (meta[iid], dates, closes)
    return out


# --------------------------------------------------------------------------
# 3) 信号 + 前向收益（向量化，每股一次）
# --------------------------------------------------------------------------
def build_forward(closes, vma, h, min_i=199, oos_start=None):
    """在每股收盘序列上定位年线信号日并算前向收益（含持有成本）。

    参数
    ------
    closes    : (n,) 前复权收盘价
    vma       : (n,) 200 交易日移动平均（>=199 有值）
    h         : 持有期（交易日）
    min_i     : 允许作为信号的最早日（默认 199 = MA200 有值日）
    oos_start : 若给，仅把 >= oos_start 的日期当信号日（样本外过滤），MA 用全历史

    返回
    ------
    dict: above_gross / below_gross （持有期毛收益 ndarray）
          above_net  （above 组扣成本后收益）
          above_n / below_n
    信号日定义：closes[i] > vma[i] → above，否则 below。
    成交：次一交易日 close[i+1] 买入，close[i+1+h] 卖出 → 若 i+1+h > n-1 则该信号无前向收益。
    """
    n = len(closes)
    i_max = n - h - 2          # 需要 i+1+h <= n-1
    lo = max(min_i, 0)
    hi = min(i_max, n - 1)
    out = {}
    if oos_start is not None:
        lo = max(lo, oos_start)
    if lo > hi:
        return out
    sig = closes[lo:hi + 1] > vma[lo:hi + 1]
    idx_all = np.arange(lo, hi + 1)
    above = idx_all[sig]
    below = idx_all[~sig]

    def fwd(idx):
        if len(idx) == 0:
            return np.empty(0, dtype=np.float32)
        entry = closes[idx + 1]
        exit_ = closes[idx + 1 + h]
        return (exit_ / entry - 1.0).astype(np.float32)

    r_above = fwd(above)
    r_below = fwd(below)
    out["above_gross"] = r_above
    out["below_gross"] = r_below
    out["above_net"] = r_above - COST  # 信号组持有期满卖出扣一次 25bps
    out["above_n"] = int(len(r_above))
    out["below_n"] = int(len(r_below))
    return out


# --------------------------------------------------------------------------
# 4) 汇总统计（n / 均值 / 中位数 / 胜率）
# --------------------------------------------------------------------------
def bucket_stats(arr):
    n = int(len(arr))
    if n == 0:
        return {"n": 0, "mean": None, "median": None, "win_rate": None}
    return {
        "n": n,
        "mean": float(np.mean(arr)),
        "median": float(np.median(arr)),
        "win_rate": float(np.mean(arr > 0)),
    }


# --------------------------------------------------------------------------
# 5) 显著性：市场层面股票级 block Bootstrap（2000 次）
# --------------------------------------------------------------------------
def bootstrap_ci_diff(pairs, rng, iters=BOOT_ITERS):
    """对配对样本 (above_net_均值, below_gross_均值) 做带放回重抽样。

    D_b = mean(above_net[sample]) - mean(below_gross[sample])，2000 次 →
    95% 百分位 CI 与 p（方向 H1: above > below；另给双侧）。
    把每股看成一个 block（股票级），同一股内部高度重叠的逐日前向收益被坍缩为
    每股均值再入市场统计 → 等价于对重叠持有期降采样，缓解自相关夸大显著性。
    """
    if pairs is None or len(pairs) < 2:
        return None
    a = np.asarray([p[0] for p in pairs], dtype=np.float64)
    b = np.asarray([p[1] for p in pairs], dtype=np.float64)
    n = len(a)
    obs_diff = float(np.mean(a) - np.mean(b))
    boot = np.empty(iters, dtype=np.float64)
    for k in range(iters):
        idx = rng.integers(0, n, size=n)
        boot[k] = np.mean(a[idx]) - np.mean(b[idx])
    ci_low, ci_high = np.percentile(boot, [2.5, 97.5])
    p_pos = float(np.mean(boot <= 0.0))      # H1: above > below 时，落在 0 左侧=犯一类错
    p_neg = float(np.mean(boot >= 0.0))      # 反方向
    return {
        "n_stocks": n,
        "obs_mean_diff": obs_diff,
        "n_boot": iters,
        "ci95_low": float(ci_low),
        "ci95_high": float(ci_high),
        "p_directional_above_gt_below": min(1.0, p_pos),
        "p_two_sided": min(1.0, 2.0 * min(p_pos, p_neg)),
    }


# --------------------------------------------------------------------------
# 6) 单市场 / 全池处理
# --------------------------------------------------------------------------
def process_market(market, claim_cfg, rng, global_buckets, oos_global_buckets,
                   global_pairs, global_oos_pairs, global_sig, global_oos_sig):
    series = load_market_series(market, claim_cfg["data_scope"].get("category", "stock"))
    if series is None:
        return None
    holding_days = claim_cfg["holding_days"]
    total_stocks = len(series)

    # 市场级统计桶：bucket[h][group] 累积收益数组
    buckets = {h: {"above_net": [], "above_gross": [], "below": []} for h in holding_days}
    oos_buckets = {h: {"above_net": [], "above_gross": [], "below": []} for h in holding_days}
    # 每股配对（股级 block）：(above_net_mean, below_gross_mean)
    pairs = {h: [] for h in holding_days}
    oos_pairs = {h: [] for h in holding_days}
    # 每股配对（不扣成本 + 配对）：用于 diff_gross 参考
    pairs_gross = {h: [] for h in holding_days}
    n_stocks_with_signal = {h: {"above": 0, "below": 0} for h in holding_days}
    oos_stocks_with_signal = {h: {"above": 0, "below": 0} for h in holding_days}
    processed = 0
    min_rows = max(holding_days) + 200 + 2

    for iid, (ticker, dates, closes) in series.items():
        n = int(len(closes))
        if n < 200:
            continue
        processed += 1
        # 200 日均线（交易日的滚动均值，与前版/trading-day 惯例一致）
        csum = np.concatenate([[0.0], np.cumsum(closes)])
        vma = np.empty(n)
        vma[:199] = np.nan
        idx = np.arange(199, n)
        vma[199:] = (csum[idx + 1] - csum[idx - 199]) / 200.0

        oos_start = int(min(n, int(np.floor((1.0 - OOS_FRAC) * n))))
        for h in holding_days:
            if n < 200 + h + 2:
                continue
            r = build_forward(closes, vma, h, min_i=199)
            if r.get("above_n", 0) or r.get("below_n", 0):
                if r["above_n"] > 0:
                    buckets[h]["above_net"].append(r["above_net"])
                    buckets[h]["above_gross"].append(r["above_gross"])
                    n_stocks_with_signal[h]["above"] += 1
                if r["below_n"] > 0:
                    buckets[h]["below"].append(r["below_gross"])
                    n_stocks_with_signal[h]["below"] += 1
                if r["above_n"] > 0 and r["below_n"] > 0:
                    pairs[h].append((float(np.mean(r["above_net"])),
                                     float(np.mean(r["below_gross"]))))
                    pairs_gross[h].append((float(np.mean(r["above_gross"])),
                                           float(np.mean(r["below_gross"]))))
            # 样本外（后 20% 交易日）
            ro = build_forward(closes, vma, h, min_i=199, oos_start=oos_start)
            if ro.get("above_n", 0) or ro.get("below_n", 0):
                if ro["above_n"] > 0:
                    oos_buckets[h]["above_net"].append(ro["above_net"])
                    oos_buckets[h]["above_gross"].append(ro["above_gross"])
                    oos_stocks_with_signal[h]["above"] += 1
                if ro["below_n"] > 0:
                    oos_buckets[h]["below"].append(ro["below_gross"])
                    oos_stocks_with_signal[h]["below"] += 1
                if ro["above_n"] > 0 and ro["below_n"] > 0:
                    oos_pairs[h].append((float(np.mean(ro["above_net"])),
                                         float(np.mean(ro["below_gross"]))))

    def make_holding_block(h):
        ab_net = np.concatenate(buckets[h]["above_net"]) if buckets[h]["above_net"] else np.empty(0)
        ab_gross = np.concatenate(buckets[h]["above_gross"]) if buckets[h]["above_gross"] else np.empty(0)
        bel = np.concatenate(buckets[h]["below"]) if buckets[h]["below"] else np.empty(0)
        above_net_s, above_g_s = bucket_stats(ab_net), bucket_stats(ab_gross)
        below_s = bucket_stats(bel)
        boot = bootstrap_ci_diff(pairs[h], rng)
        boot_gross = bootstrap_ci_diff(pairs_gross[h], rng)
        n_paired = len(pairs[h])
        block = {
            "above": {
                **above_net_s,
                "mean_gross": above_g_s["mean"],
                "mean_net": above_net_s["mean"],
                "n": above_net_s["n"],
            },
            "below": {**below_s, "mean": below_s["mean"], "n": below_s["n"]},
            "diff_net_stock_ew": (float(np.mean([p[0] for p in pairs[h]])) -
                                  float(np.mean([p[1] for p in pairs[h]]))
                                  if n_paired else None),
            "diff_gross_stock_ew": (float(np.mean([p[0] for p in pairs_gross[h]])) -
                                    float(np.mean([p[1] for p in pairs_gross[h]]))
                                    if len(pairs_gross[h]) else None),
            "n_paired_stocks": n_paired,
            "diff_net_pooled": (above_net_s["mean"] - below_s["mean"]
                                if above_net_s["mean"] is not None and below_s["mean"] is not None else None),
            "diff_gross_pooled": (above_g_s["mean"] - below_s["mean"]
                                  if above_g_s["mean"] is not None and below_s["mean"] is not None else None),
            "bootstrap": boot,
            "signal_stocks": dict(n_stocks_with_signal[h]),
        }
        return block

    def make_oos_block(h):
        ab_net = np.concatenate(oos_buckets[h]["above_net"]) if oos_buckets[h]["above_net"] else np.empty(0)
        ab_gross = np.concatenate(oos_buckets[h]["above_gross"]) if oos_buckets[h]["above_gross"] else np.empty(0)
        bel = np.concatenate(oos_buckets[h]["below"]) if oos_buckets[h]["below"] else np.empty(0)
        above_net_s, above_g_s = bucket_stats(ab_net), bucket_stats(ab_gross)
        below_s = bucket_stats(bel)
        boot = bootstrap_ci_diff(oos_pairs[h], rng)
        n_paired = len(oos_pairs[h])
        return {
            "above": {**above_net_s, "mean_gross": above_g_s["mean"], "mean_net": above_net_s["mean"], "n": above_net_s["n"]},
            "below": {**below_s, "mean": below_s["mean"], "n": below_s["n"]},
            "diff_net_stock_ew": (float(np.mean([p[0] for p in oos_pairs[h]])) -
                                  float(np.mean([p[1] for p in oos_pairs[h]]))
                                  if n_paired else None),
            "n_paired_stocks": n_paired,
            "diff_net_pooled": (above_net_s["mean"] - below_s["mean"]
                                if above_net_s["mean"] is not None and below_s["mean"] is not None else None),
            "diff_gross_pooled": (above_g_s["mean"] - below_s["mean"]
                                  if above_g_s["mean"] is not None and below_s["mean"] is not None else None),
            "bootstrap": boot,
            "signal_stocks": dict(oos_stocks_with_signal[h]),
        }

    result = {"market": market, "stocks_total": total_stocks, "stocks_processed": processed,
              "holdings": {f"d{h}": make_holding_block(h) for h in holding_days},
              "oos": {f"d{h}": make_oos_block(h) for h in holding_days}}

    # 汇总到全池（pooled 统计 + 全局配对股）
    for h in holding_days:
        if buckets[h]["above_net"]:
            global_buckets[h]["above_net"].extend(buckets[h]["above_net"])
            global_buckets[h]["above_gross"].extend(buckets[h]["above_gross"])
            global_buckets[h]["below"].extend(buckets[h]["below"])
        if oos_buckets[h]["above_net"]:
            oos_global_buckets[h]["above_net"].extend(oos_buckets[h]["above_net"])
            oos_global_buckets[h]["above_gross"].extend(oos_buckets[h]["above_gross"])
            oos_global_buckets[h]["below"].extend(oos_buckets[h]["below"])
        for p in pairs[h]:
            global_pairs[h].append(p)
        for p in oos_pairs[h]:
            global_oos_pairs[h].append(p)
        for grp in ("above", "below"):
            global_sig[h][grp] += n_stocks_with_signal[h][grp]
            global_oos_sig[h][grp] += oos_stocks_with_signal[h][grp]
    return result


# --------------------------------------------------------------------------
# 7) 协议红绿灯（obj 数组）
# --------------------------------------------------------------------------
def protocol_lights():
    return [
        {"item": "判据对齐（论断=收益 → 判据=平均收益）", "status": "✅",
         "note": "主判据=above 组均值(扣成本) − below 组均值；中位数辅助，胜率仅参考（铁律一）"},
        {"item": "价格口径（前复权 close）", "status": "✅",
         "note": "daily_data.close 为前复权（000-data-biases.md A.1），排除未复权假跳空污染"},
        {"item": "成交时机（无前视）", "status": "✅",
         "note": "T 日收盘定价信号，T+1 开始持有；不用当日收盘价当日成交"},
        {"item": "交易成本", "status": "⚠️",
         "note": "信号组持有期满卖出扣 25bps 一次（FEE0.15%+SLIP0.1% 单边口径）；对照组不扣=毛差；未计冲击/印花税，未用 T+1 开盘价成交"},
        {"item": "显著性检验（Bootstrap 95% CI + p）", "status": "✅",
         "note": f"市场层面 2000 次股票级 block bootstrap（种子 {RNG_SEED}，可复现）"},
        {"item": "重叠样本处理", "status": "⚠️",
         "note": "每股坍缩为均值再做股级 bootstrap（等价降采样到每股）；同股跨日重叠被压缩进每股均值，跨股同日历相关未建模"},
        {"item": "样本外验证（后 20%）", "status": "✅",
         "note": "每标的自有交易日后 20% 数据单独跑同口径，报告收益差与 CI"},
        {"item": "幸存者偏差（含退市股）", "status": "⚠️",
         "note": "本地库 indices 仅当前成分股快照，不含退市/被剔除股（survivorship-bias-report.md）→ 收益被系统性高估，现有数据无法修复，如实记录"},
        {"item": "对标权威文献（Brock et al. 1992）", "status": "⚠️",
         "note": "已实现『信号 vs 对照组 + Bootstrap 显著性』；未做『信号 vs 无条件全样本基准』对照；持有期收益未做波动率/风险调整口径"},
    ]


# --------------------------------------------------------------------------
# 8b) 论断 #8 引擎：月度暴涨 → 次月上涨概率（概率阈值判据）
# --------------------------------------------------------------------------
def run_monthly_surge(claim, out_dir, oos_frac=OOS_FRAC, seed=RNG_SEED):
    """实现 000-claims-def.md 中 id=8 的契约：
      信号 = 过去 20 个交易日（≈1 月）涨幅 >30%（T 日收盘确定，无前视）；
      评估 = T+1 起 20 个交易日（次月）内收盘价是否高于 T+1 收盘价（上涨=1）。
      主判据 = 信号组"次月上涨概率"是否 <40%（概率阈值，非收益差）。
      对照组 = 20 日涨幅 ≤30% 的日；两组的上涨概率差 + 股票级 block Bootstrap。
    """
    rng = np.random.default_rng(seed)
    markets = claim["data_scope"].get("markets", [])
    category = claim["data_scope"].get("category", "stock")

    agg = {"sig_n": 0, "sig_up": 0, "ctrl_n": 0, "ctrl_up": 0,
           "sig_stocks": 0, "ctrl_stocks": 0, "sig_rates": [], "ctrl_rates": [], "pairs": []}
    oos_agg = {"sig_n": 0, "sig_up": 0, "ctrl_n": 0, "ctrl_up": 0,
               "sig_stocks": 0, "ctrl_stocks": 0, "sig_rates": [], "ctrl_rates": [], "pairs": []}
    per_market = {}

    for m in markets:
        series = load_market_series(m, category)
        if series is None:
            continue
        mstat = {"stocks_total": len(series), "stocks_processed": 0,
                 "sig_n": 0, "sig_up": 0, "ctrl_n": 0, "ctrl_up": 0,
                 "sig_stocks": 0, "ctrl_stocks": 0}
        oos_mstat = {k: 0 for k in ("sig_n", "sig_up", "ctrl_n", "ctrl_up", "sig_stocks", "ctrl_stocks")}

        for iid, (ticker, dates, closes) in series.items():
            n = int(len(closes))
            if n < 42:  # 需要 i∈[20, n-22] 区间非空
                continue
            mstat["stocks_processed"] += 1
            # 20 日滚动涨幅（T 日收盘可确定）
            r20 = np.empty(n)
            r20[:20] = np.nan
            r20[20:] = closes[20:] / closes[:-20] - 1.0
            sig_day = r20 > 0.30
            # 评估窗口 [i+1, i+21]：i+21 <= n-1 → i <= n-22
            i_arr = np.arange(20, n - 21)
            msig = sig_day[i_arr]
            up = closes[i_arr + 21] > closes[i_arr + 1]
            sig_up = up[msig]
            ctrl_up = up[~msig]
            sig_n, ctrl_n = int(len(sig_up)), int(len(ctrl_up))
            if sig_n:
                srate = float(np.mean(sig_up))
                agg["sig_rates"].append(srate); agg["sig_stocks"] += 1
            if ctrl_n:
                crate = float(np.mean(ctrl_up))
                agg["ctrl_rates"].append(crate); agg["ctrl_stocks"] += 1
            if sig_n and ctrl_n:
                agg["pairs"].append((float(np.mean(sig_up)), float(np.mean(ctrl_up))))
            agg["sig_n"] += sig_n; agg["sig_up"] += int(sig_up.sum())
            agg["ctrl_n"] += ctrl_n; agg["ctrl_up"] += int(ctrl_up.sum())
            mstat["sig_n"] += sig_n; mstat["sig_up"] += int(sig_up.sum())
            mstat["ctrl_n"] += ctrl_n; mstat["ctrl_up"] += int(ctrl_up.sum())
            if sig_n: mstat["sig_stocks"] += 1
            if ctrl_n: mstat["ctrl_stocks"] += 1

            # 样本外：只取该标的后 20% 交易日作为信号日
            oos_start = int(min(n, int(np.floor((1.0 - oos_frac) * n))))
            oi = i_arr[i_arr >= oos_start]
            if len(oi) == 0:
                continue
            o_msig = sig_day[oi]
            o_up = closes[oi + 21] > closes[oi + 1]
            o_sig_up, o_ctrl_up = o_up[o_msig], o_up[~o_msig]
            o_sig_n, o_ctrl_n = int(len(o_sig_up)), int(len(o_ctrl_up))
            if o_sig_n:
                oos_agg["sig_rates"].append(float(np.mean(o_sig_up)))
                oos_agg["sig_stocks"] += 1
            if o_ctrl_n:
                oos_agg["ctrl_rates"].append(float(np.mean(o_ctrl_up)))
                oos_agg["ctrl_stocks"] += 1
            if o_sig_n and o_ctrl_n:
                oos_agg["pairs"].append((float(np.mean(o_sig_up)), float(np.mean(o_ctrl_up))))
            oos_agg["sig_n"] += o_sig_n; oos_agg["sig_up"] += int(o_sig_up.sum())
            oos_agg["ctrl_n"] += o_ctrl_n; oos_agg["ctrl_up"] += int(o_ctrl_up.sum())
            oos_mstat["sig_n"] += o_sig_n; oos_mstat["sig_up"] += int(o_sig_up.sum())
            oos_mstat["ctrl_n"] += o_ctrl_n; oos_mstat["ctrl_up"] += int(o_ctrl_up.sum())
            if o_sig_n: oos_mstat["sig_stocks"] += 1
            if o_ctrl_n: oos_mstat["ctrl_stocks"] += 1

        per_market[m] = {
            "stocks_total": mstat["stocks_total"],
            "stocks_processed": mstat["stocks_processed"],
            "signal": _rate_block(mstat),
            "control": _rate_block(mstat, control=True),
            "oos": {"signal": _rate_block(oos_mstat), "control": _rate_block(oos_mstat, control=True)},
        }
        print(f"    [{datetime.now():%H:%M:%S}] {m} done "
              f"({mstat['stocks_processed']}/{mstat['stocks_total']})", file=sys.stderr, flush=True)

    return _monthly_surge_emit(claim, out_dir, per_market, agg, oos_agg, rng)


def _rate_block(st, control=False):
    """从统计字典抽出上涨率块。control=True 时取对照组字段。"""
    p = "ctrl" if control else "sig"
    n, up = st[p + "_n"], st[p + "_up"]
    return {"n_days": n, "n_up": up,
            "win_rate_pct": round(100.0 * up / n, 2) if n else None,
            "n_stocks": st[p + "_stocks"]}


def _monthly_surge_emit(claim, out_dir, per_market, agg, oos_agg, rng):
    """聚合 + 判据 + 落盘（与 #1 引擎输出同构：results.json）。"""
    def agg_rate(a):
        n, up = a["sig_n"], a["sig_up"]
        return round(100.0 * up / n, 2) if n else None
    def ctrl_rate(a):
        n, up = a["ctrl_n"], a["ctrl_up"]
        return round(100.0 * up / n, 2) if n else None

    sig_rate = agg_rate(agg)          # 信号组 pooled 次月上涨率（%）
    ctrl_rate_pooled = ctrl_rate(agg)
    sig_ew = round(100.0 * float(np.mean(agg["sig_rates"])), 2) if agg["sig_rates"] else None

    # 单组 CI：股票级重抽样信号组上涨率的 EW 均值
    boot_sig = None
    if len(agg["sig_rates"]) >= 2:
        arr = np.asarray(agg["sig_rates"], dtype=np.float64)
        boots = np.empty(BOOT_ITERS)
        for k in range(BOOT_ITERS):
            idx = rng.integers(0, len(arr), size=len(arr))
            boots[k] = np.mean(arr[idx])
        boot_sig = {"mean_pct": round(float(np.mean(arr)) * 100, 2),
                    "ci95_low_pct": round(float(np.percentile(boots, 2.5)) * 100, 2),
                    "ci95_high_pct": round(float(np.percentile(boots, 97.5)) * 100, 2)}

    # 配对差（信号 − 对照，股票等权）Bootstrap
    diff_boot = bootstrap_ci_diff(agg["pairs"], rng) if len(agg["pairs"]) >= 2 else None

    # 样本外同口径
    oos_sig_rate = agg_rate(oos_agg)
    oos_ctrl_rate = ctrl_rate(oos_agg)
    oos_diff_boot = bootstrap_ci_diff(oos_agg["pairs"], rng) if len(oos_agg["pairs"]) >= 2 else None

    # ---- 判据（契约：概率阈值 <40%） ----
    threshold = 40.0
    verdict = {
        "threshold_pct": threshold,
        "signal_win_rate_pooled_pct": sig_rate,
        "signal_win_rate_ew_pct": sig_ew,
        "control_win_rate_pooled_pct": ctrl_rate_pooled,
        "diff_vs_control_pooled_pp": round(sig_rate - ctrl_rate_pooled, 2)
                                     if sig_rate is not None and ctrl_rate_pooled is not None else None,
        "n_signal_days": agg["sig_n"], "n_control_days": agg["ctrl_n"],
        "n_signal_stocks": agg["sig_stocks"], "n_control_stocks": agg["ctrl_stocks"],
        "sig_ci95": boot_sig,
        "diff_bootstrap": diff_boot,
        "oos_signal_win_rate_pooled_pct": oos_sig_rate,
        "oos_control_win_rate_pooled_pct": oos_ctrl_rate,
        "oos_diff_bootstrap": oos_diff_boot,
        "supported_pooled": bool(sig_rate is not None and sig_rate < threshold),
        "supported_ew": bool(sig_ew is not None and sig_ew < threshold),
        "supported_at_95": bool(boot_sig is not None and boot_sig["ci95_high_pct"] < threshold),
    }
    # 汇总判据（池化口径为准，EW/CI 为佐证）
    verdict["supported"] = verdict["supported_pooled"]

    payload = {
        "claim": {k: claim[k] for k in ("id", "title", "statement", "h0", "price_basis",
                                        "cost_bps", "holding_days", "signal_def",
                                        "verdict_metric", "data_scope") if k in claim},
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "config": {"bootstrap_iters": BOOT_ITERS, "rng_seed": RNG_SEED, "oos_frac": OOS_FRAC,
                   "momentum_window_days": 20, "signal_threshold": 0.30, "eval_window_days": 20,
                   "threshold_pct": threshold, "markets": [m for m in per_market]},
        "pools": {"markets": list(per_market.keys()),
                  "stocks_total_by_market": {m: per_market[m]["stocks_total"] for m in per_market},
                  "stocks_processed_by_market": {m: per_market[m]["stocks_processed"] for m in per_market}},
        "survivorship_note": "本地库 indices 仅当前成分股快照，不含退市/被剔除股；结果方向影响已知（高估收益、低估下跌概率）",
        "protocol_lights": _monthly_surge_lights(),
        "per_market": per_market,
        "aggregate": {"signal": _rate_block(agg), "control": _rate_block(agg, control=True)},
        "aggregate_oos": {"signal": _rate_block(oos_agg), "control": _rate_block(oos_agg, control=True)},
        "verdict": verdict,
    }

    res_path = os.path.join(out_dir, "results.json")
    os.makedirs(out_dir, exist_ok=True)
    with open(res_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print("\n==== 论断 #%s 复测摘要 ====" % claim["id"])
    print("输出:", res_path)
    print(f"  信号组次月上涨率(pooled)={sig_rate}% / 对照组={ctrl_rate_pooled}% "
          f"/ EW={sig_ew}% CI95=[{boot_sig['ci95_low_pct']},{boot_sig['ci95_high_pct']}]"
          if boot_sig else f"  信号组次月上涨率(pooled)={sig_rate}% / 对照组={ctrl_rate_pooled}%")
    print(f"  判据(阈值{threshold}%): supported={verdict['supported']} "
          f"supported_95={verdict['supported_at_95']} | OOS={oos_sig_rate}%")
    return 0


def _monthly_surge_lights():
    return [
        {"item": "判据对齐（论断=次月上涨概率 → 判据=信号组上涨概率 vs 40% 阈值）", "status": "✅",
         "note": "主判据=信号组 pooled 次月上涨率；EW 均值与 95%CI 佐证；对照差异仅参考（铁律一）"},
        {"item": "价格口径（前复权 close）", "status": "✅",
         "note": "daily_data.close 为前复权（000-data-biases.md A.1），避免未复权假跳空污染"},
        {"item": "成交时机（无前视）", "status": "✅",
         "note": "信号 T 日收盘确定（20 日涨幅>30%），评估窗口从 T+1 起 20 个交易日；不用当日收盘价又做信号又做评估"},
        {"item": "交易成本", "status": "⚠️",
         "note": "本论断为概率统计、非策略收益，成本不参与上涨率计算；保留 cost_bps 字段与 schema 一致"},
        {"item": "显著性检验（股票级 block Bootstrap 95% CI）", "status": "✅",
         "note": f"信号组 EW 上涨率单组 2000 次重抽样 CI + 配对差 Bootstrap（种子 {RNG_SEED}，可复现）"},
        {"item": "重叠样本处理", "status": "⚠️",
         "note": "逐日滚动 20 日窗口高度重叠 → 每股坍缩为均值再做股票级 bootstrap（等价降采样到每股）；跨股同日历相关未建模"},
        {"item": "样本外验证（后 20%）", "status": "✅",
         "note": "每标的自有交易日后 20% 数据单独跑同口径，报告上涨率与配对差 CI"},
        {"item": "幸存者偏差（含退市股）", "status": "⚠️",
         "note": "本地库 indices 仅当前成分股快照，不含退市/被剔除股 → 上涨率被系统性高估（方向已知，现有数据无法修复）"},
    ]


# --------------------------------------------------------------------------
# 8) 主流程
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="FengInvest 论断复测引擎（确定性版）")
    ap.add_argument("claim_id", help="论断编号（读 000-claims-def.md，当前实现 #1）")
    ap.add_argument("--out", default=None, help="输出目录（默认 RETEST 自动目录）")
    args = ap.parse_args()

    global COST
    claims_data = load_claims_def()
    claim = find_claim(claims_data, args.claim_id)
    if claim is None:
        return 1
    if not claim.get("implemented", True):
        print(f"错误：id={args.claim_id} 已在 000-claims-def.md 登记（implemented:false）但引擎尚未实现"
              f"——定义即契约已就位，待引擎扩展后即可复测（排程见 000-CLASSIFICATION.md）")
        return 1

    if claim.get("engine") == "monthly-surge-prob":
        out_dir = args.out or os.path.join(BASE, "research", "110-strategy-verification",
                                           claim.get("folder", f"claim-{claim['id']}"),
                                           f"RETEST-{datetime.now().strftime('%Y-%m-%d')}")
        return run_monthly_surge(claim, out_dir)
    COST = float(claim.get("cost_bps", 0)) / 10000.0
    holding_days = [int(h) for h in claim.get("holding_days", [20, 60, 120])]
    markets = claim["data_scope"].get("markets", [])
    if not markets:
        print("错误：claims-def 未定义 data_scope.markets")
        return 1

    if args.out:
        out_dir = args.out
    else:
        date_today = datetime.now().strftime("%Y-%m-%d")
        out_dir = os.path.join(BASE, "research", "110-strategy-verification",
                               claim.get("folder", f"claim-{claim['id']}"),
                               f"RETEST-{date_today}")
    os.makedirs(out_dir, exist_ok=True)

    rng = np.random.default_rng(RNG_SEED)
    global_buckets = {h: {"above_net": [], "above_gross": [], "below": []} for h in holding_days}
    oos_global_buckets = {h: {"above_net": [], "above_gross": [], "below": []} for h in holding_days}
    global_pairs = {h: [] for h in holding_days}
    global_oos_pairs = {h: [] for h in holding_days}
    global_sig = {h: {"above": 0, "below": 0} for h in holding_days}
    global_oos_sig = {h: {"above": 0, "below": 0} for h in holding_days}

    per_market = {}
    for m in markets:
        print(f"  [{datetime.now():%H:%M:%S}] {m} ...", file=sys.stderr, flush=True)
        mr = process_market(m, claim, rng, global_buckets, oos_global_buckets,
                            global_pairs, global_oos_pairs, global_sig, global_oos_sig)
        if mr is None:
            continue
        per_market[m] = mr
        print(f"    [{datetime.now():%H:%M:%S}] {m} done "
              f"({mr['stocks_processed']}/{mr['stocks_total']})", file=sys.stderr, flush=True)

    # --- 汇总块 ---
    def make_aggregate_block(h, buckets, pairs, sig):
        ab_net = np.concatenate(buckets[h]["above_net"]) if buckets[h]["above_net"] else np.empty(0)
        ab_gross = np.concatenate(buckets[h]["above_gross"]) if buckets[h]["above_gross"] else np.empty(0)
        bel = np.concatenate(buckets[h]["below"]) if buckets[h]["below"] else np.empty(0)
        above_net_s, above_g_s = bucket_stats(ab_net), bucket_stats(ab_gross)
        below_s = bucket_stats(bel)
        boot = bootstrap_ci_diff(pairs[h], rng)
        n_paired = len(pairs[h])
        return {
            "above": {**above_net_s, "mean_gross": above_g_s["mean"], "mean_net": above_net_s["mean"], "n": above_net_s["n"]},
            "below": {**below_s, "mean": below_s["mean"], "n": below_s["n"]},
            "diff_net_stock_ew": (float(np.mean([p[0] for p in pairs[h]])) -
                                  float(np.mean([p[1] for p in pairs[h]]))
                                  if n_paired else None),
            "n_paired_stocks": n_paired,
            "diff_net_pooled": (above_net_s["mean"] - below_s["mean"]
                                if above_net_s["mean"] is not None and below_s["mean"] is not None else None),
            "diff_gross_pooled": (above_g_s["mean"] - below_s["mean"]
                                  if above_g_s["mean"] is not None and below_s["mean"] is not None else None),
            "bootstrap": boot,
            "signal_stocks": dict(sig[h]),
        }

    aggregate = {f"d{h}": make_aggregate_block(h, global_buckets, global_pairs, global_sig)
                 for h in holding_days}
    aggregate_oos = {f"d{h}": make_aggregate_block(h, oos_global_buckets, global_oos_pairs, global_oos_sig)
                     for h in holding_days}

    # --- 结论建议（从真实数字推导） ---
    verdict = {}
    for h in holding_days:
        blk = aggregate[f"d{h}"]
        oos = aggregate_oos[f"d{h}"]
        diff = blk["diff_net_pooled"]
        boot = blk["bootstrap"]
        supported = (diff is not None and diff > 0 and boot is not None
                     and boot["p_directional_above_gt_below"] < 0.05
                     and boot["ci95_low"] > 0)
        oos_same = (oos["diff_net_pooled"] is not None and oos["diff_net_pooled"] > 0)
        verdict[f"d{h}"] = {
            "diff_net_pooled_pp": round(diff * 100, 4) if diff is not None else None,
            "ci95_low_pp": round(boot["ci95_low"] * 100, 4) if boot else None,
            "ci95_high_pp": round(boot["ci95_high"] * 100, 4) if boot else None,
            "p_directional": boot["p_directional_above_gt_below"] if boot else None,
            "p_two_sided": boot["p_two_sided"] if boot else None,
            "supported_at_95": supported,
            "oos_diff_net_pooled_pp": round(oos["diff_net_pooled"] * 100, 4)
                                      if oos["diff_net_pooled"] is not None else None,
            "oos_same_direction": oos_same,
        }

    payload = {
        "claim": {k: claim[k] for k in ("id", "title", "statement", "h0", "price_basis",
                                        "cost_bps", "holding_days", "signal_def",
                                        "verdict_metric", "data_scope") if k in claim},
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "config": {
            "bootstrap_iters": BOOT_ITERS, "rng_seed": RNG_SEED, "oos_frac": OOS_FRAC,
            "vma_window": 200, "cost_bps": claim.get("cost_bps"), "markets": markets,
        },
        "pools": {
            "markets": list(per_market.keys()),
            "stocks_total_by_market": {m: per_market[m]["stocks_total"] for m in per_market},
            "stocks_processed_by_market": {m: per_market[m]["stocks_processed"] for m in per_market},
        },
        "survivorship_note": "本地库 indices 仅当前成分股快照，不含退市/被剔除股；收益被系统性高估（方向已知，现有数据无法修复）",
        "protocol_lights": protocol_lights(),
        "aggregate": aggregate,
        "aggregate_oos": aggregate_oos,
        "per_market": per_market,
        "verdict": verdict,
    }

    if not args.out:
        out_dir = os.path.join(BASE, "research", "110-strategy-verification",
                               claim.get("folder", f"claim-{claim['id']}"),
                               f"RETEST-{datetime.now().strftime('%Y-%m-%d')}")
        os.makedirs(out_dir, exist_ok=True)
    res_path = os.path.join(out_dir, "results.json")
    with open(res_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    print("\n==== 论断 #%s 复测摘要 ====" % claim["id"])
    print("输出:", res_path)
    for h in holding_days:
        v = verdict[f"d{h}"]
        print(f"  d{h}: 收益差(净,pooled)={v['diff_net_pooled_pp']}pp "
              f"p(one-sided)={v['p_directional']:.4f} CI=[{v['ci95_low_pp']},{v['ci95_high_pp']}] "
              f"OOS差={v['oos_diff_net_pooled_pp']}pp "
              f"→ 95%显著支持={v['supported_at_95']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


# 模块级（build_forward 用）——运行时由 main 赋值
COST = 0.0025
