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
# 8c) 论断 #3 引擎：年线穿越 1 日噪音占比（事件计数型）
# --------------------------------------------------------------------------
def _ma200(closes):
    """200 交易日收盘移动平均（与 #1 引擎同口径：滚动均值，前 199 日为 NaN）。"""
    n = len(closes)
    csum = np.concatenate([[0.0], np.cumsum(closes)])
    vma = np.full(n, np.nan)
    idx = np.arange(199, n)
    vma[199:] = (csum[idx + 1] - csum[idx - 199]) / 200.0
    return vma


def _crossing_events(closes):
    """提取 MA200 穿越事件（事件计数型，无前视：事件在 T 日收盘后确定）。

    返回 (cross_idx, is_up)：
      cross_idx : 事件日 T（close 首次处于新的一侧的数组下标，>=199）
      is_up     : True=上穿，False=下穿
    """
    vma = _ma200(closes)
    above = closes[199:] > vma[199:]          # 从 MA 有效首日起
    if len(above) < 2:
        return np.empty(0, dtype=np.int64), np.empty(0, dtype=bool)
    d = np.diff(above.astype(np.int8))
    k = np.where(d != 0)[0] + 1               # above 切片内的新侧首日
    cross_idx = k + 199
    return cross_idx, above[k]


def run_annual_line_noise(claim, out_dir, oos_frac=OOS_FRAC, seed=RNG_SEED):
    """实现 000-claims-def.md id=3 契约（engine: annual-line-crossing-noise）：
      事件 = 收盘价上穿/下穿 MA200 的穿越日 T；
      1 日噪音 = T 日信号后 T+1 日即被反向穿越还原（above 标志在 T+1 再次翻转）；
      主判据 = 1 日噪音占全部穿越事件的比例，落在 25-33% 区间则支持。
      样本外 = 每标的自有交易日后 20% 内的事件单独报告占比。
      显著性 = 股票级 block Bootstrap（每股坍缩为噪音率，2000 次重抽样）。
    """
    rng = np.random.default_rng(seed)
    markets = claim["data_scope"].get("markets", [])
    category = claim["data_scope"].get("category", "stock")

    agg = {"events": 0, "noise": 0, "unclassifiable": 0, "rates": []}
    oos_agg = {"events": 0, "noise": 0, "unclassifiable": 0, "rates": []}
    per_market = {}

    for m in markets:
        series = load_market_series(m, category)
        if series is None:
            continue
        mstat = {"stocks_total": len(series), "stocks_processed": 0,
                 "events": 0, "noise": 0, "unclassifiable": 0}
        oos_mstat = {"stocks_processed": 0, "events": 0, "noise": 0, "unclassifiable": 0}
        for iid, (ticker, dates, closes) in series.items():
            n = int(len(closes))
            if n < 201:  # 至少需要 MA 有效首日 + 1 个可判定日
                continue
            mstat["stocks_processed"] += 1
            cross_idx, is_up = _crossing_events(closes)
            if len(cross_idx) == 0:
                continue
            # 1 日噪音：T+1 日 above 标志再次翻转（反向穿越还原）
            nxt = cross_idx + 1
            classifiable = nxt <= n - 1
            ev = cross_idx[classifiable]
            up = is_up[classifiable]
            above_next = closes[nxt[classifiable]] > _ma200(closes)[nxt[classifiable]]
            noise = above_next != up   # 上穿后 T+1 在下方（或下穿后在上方）= 噪音
            n_ev, n_noise = int(len(ev)), int(noise.sum())
            mstat["events"] += n_ev; mstat["noise"] += n_noise
            mstat["unclassifiable"] += int(np.sum(~classifiable))
            agg["unclassifiable"] += int(np.sum(~classifiable))
            if n_ev:
                agg["rates"].append(float(n_noise) / n_ev)
                agg["events"] += n_ev; agg["noise"] += n_noise

            # 样本外：事件日 T 落在该标的后 20% 交易日
            oos_start = int(np.floor((1.0 - oos_frac) * n))
            sel = ev >= oos_start
            o_ev, o_noise = int(sel.sum()), int(noise[sel].sum())
            oos_mstat["stocks_processed"] += 1
            oos_mstat["events"] += o_ev; oos_mstat["noise"] += o_noise
            if o_ev:
                oos_agg["rates"].append(float(o_noise) / o_ev)
                oos_agg["events"] += o_ev; oos_agg["noise"] += o_noise

        per_market[m] = {
            "stocks_total": mstat["stocks_total"],
            "stocks_processed": mstat["stocks_processed"],
            "events": mstat["events"], "noise": mstat["noise"],
            "unclassifiable": mstat["unclassifiable"],
            "noise_ratio_pct": round(100.0 * mstat["noise"] / mstat["events"], 2) if mstat["events"] else None,
            "oos": {"events": oos_mstat["events"], "noise": oos_mstat["noise"],
                    "noise_ratio_pct": round(100.0 * oos_mstat["noise"] / oos_mstat["events"], 2)
                                       if oos_mstat["events"] else None},
        }
        print(f"    [{datetime.now():%H:%M:%S}] {m} done "
              f"({mstat['stocks_processed']}/{mstat['stocks_total']})", file=sys.stderr, flush=True)

    # 股票级 block bootstrap：每股噪音率 EW 均值的 95% CI
    def rate_boot(rates):
        if len(rates) < 2:
            return None
        arr = np.asarray(rates, dtype=np.float64)
        boots = np.empty(BOOT_ITERS)
        for k in range(BOOT_ITERS):
            idx = rng.integers(0, len(arr), size=len(arr))
            boots[k] = np.mean(arr[idx])
        return {"mean_pct": round(float(np.mean(arr)) * 100, 2),
                "ci95_low_pct": round(float(np.percentile(boots, 2.5)) * 100, 2),
                "ci95_high_pct": round(float(np.percentile(boots, 97.5)) * 100, 2)}

    pooled_ratio = round(100.0 * agg["noise"] / agg["events"], 2) if agg["events"] else None
    oos_ratio = round(100.0 * oos_agg["noise"] / oos_agg["events"], 2) if oos_agg["events"] else None
    boot = rate_boot(agg["rates"])
    oos_boot = rate_boot(oos_agg["rates"])

    # 判据（契约：占比 25-33%）
    band = (25.0, 33.0)
    verdict = {
        "band_pct": list(band),
        "noise_ratio_pooled_pct": pooled_ratio,
        "n_events": agg["events"], "n_noise": agg["noise"],
        "n_unclassifiable": agg["unclassifiable"],
        "n_stocks": len(agg["rates"]),
        "stock_ew_boot": boot,
        "in_band_pooled": bool(pooled_ratio is not None and band[0] <= pooled_ratio <= band[1]),
        "in_band_ew_point": bool(boot and band[0] <= boot["mean_pct"] <= band[1]),
        "oos_noise_ratio_pooled_pct": oos_ratio,
        "oos_events": oos_agg["events"], "oos_noise": oos_agg["noise"],
        "oos_stock_ew_boot": oos_boot,
        "oos_in_band_pooled": bool(oos_ratio is not None and band[0] <= oos_ratio <= band[1]),
    }
    verdict["supported"] = verdict["in_band_pooled"]

    payload = {
        "claim": {k: claim[k] for k in ("id", "title", "statement", "h0", "price_basis",
                                        "cost_bps", "signal_def", "verdict_metric",
                                        "data_scope") if k in claim},
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "engine": "annual-line-crossing-noise",
        "config": {"bootstrap_iters": BOOT_ITERS, "rng_seed": RNG_SEED, "oos_frac": OOS_FRAC,
                   "vma_window": 200, "noise_def": "T 日穿越后 T+1 日即反向穿越还原（1 个交易日内翻转）",
                   "markets": list(per_market.keys())},
        "pools": {"markets": list(per_market.keys()),
                  "stocks_total_by_market": {m: per_market[m]["stocks_total"] for m in per_market},
                  "stocks_processed_by_market": {m: per_market[m]["stocks_processed"] for m in per_market}},
        "survivorship_note": "本地库 indices 仅当前成分股快照，不含退市/被剔除股；穿越事件统计的幸存者偏差方向已知（缺退市前下跌段的噪音），如实记录",
        "protocol_lights": _event_count_lights("1 日噪音占比 vs 25-33% 区间"),
        "per_market": per_market,
        "aggregate": {"events": agg["events"], "noise": agg["noise"],
                      "noise_ratio_pct": pooled_ratio},
        "aggregate_oos": {"events": oos_agg["events"], "noise": oos_agg["noise"],
                          "noise_ratio_pct": oos_ratio},
        "verdict": verdict,
    }
    return _emit_results(claim, out_dir, payload,
                         lambda: print(f"\n==== 论断 #%s 复测摘要 ====\n" % claim["id"],
                                       f"  1日噪音占比(pooled)={pooled_ratio}% 事件数={agg['events']} "
                                       f"股级EW CI={boot} 判据区间25-33% → supported={verdict['supported']}",
                                       f"  OOS占比={oos_ratio}% (事件 {oos_agg['events']})"))


def _event_count_lights(metric_desc):
    """事件计数型引擎（#3/#5/#6）共用协议红绿灯。"""
    return [
        {"item": f"判据对齐（论断={metric_desc}）", "status": "✅",
         "note": "事件计数型论断，主判据就是论断声称的那个量本身，不用收益/胜率替代（铁律一）"},
        {"item": "价格口径（前复权 close）", "status": "✅",
         "note": "daily_data.close 为前复权（000-data-biases.md A.1），避免除权假跳空制造假穿越"},
        {"item": "时机（无前视）", "status": "✅",
         "note": "穿越事件在 T 日收盘后即可确定；噪音/持续期判定只用 T 及其之后的交易日，MA 用全历史滚动不含未来窗口"},
        {"item": "交易成本", "status": "⚠️",
         "note": "事件统计不涉及交易，成本不参与计算；保留 cost_bps 字段与 schema 一致"},
        {"item": "显著性/区间（Bootstrap 2000 次）", "status": "✅",
         "note": f"股票级 block bootstrap（每股坍缩为统计量，种子 {RNG_SEED} 可复现）"},
        {"item": "重叠样本处理", "status": "⚠️",
         "note": "穿越事件间至少隔 1 个交易日但相邻事件相关 → 每股坍缩为统计量后做股票级 bootstrap；跨股同日历相关未建模"},
        {"item": "样本外验证（后 20%）", "status": "✅",
         "note": "每标的自有交易日后 20% 内的事件/区间单独跑同口径"},
        {"item": "幸存者偏差（含退市股）", "status": "⚠️",
         "note": "本地库 indices 仅当前成分股快照，不含退市/被剔除股 → 穿越事件样本缺退市前下跌段，方向已知、现有数据无法修复"},
    ]


def _emit_results(claim, out_dir, payload, summary_printer):
    """落盘 results.json + 打印摘要（#3/#5/#6 共用出口，与 #1/#8 输出同构）。"""
    res_path = os.path.join(out_dir, "results.json")
    os.makedirs(out_dir, exist_ok=True)
    with open(res_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print("\n==== 论断 #%s 复测摘要 ====" % claim["id"])
    print("输出:", res_path)
    summary_printer()
    return 0


# --------------------------------------------------------------------------
# 8d) 论断 #5 引擎：上证年线上下持续期对称（engine: annual-line-duration-ratio）
# --------------------------------------------------------------------------
def run_shanghai_symmetry(claim, out_dir, oos_frac=OOS_FRAC, seed=RNG_SEED,
                          block_days=250):
    """实现 000-claims-def.md id=5 契约（engine: annual-line-duration-ratio）：
      对象 = 上证指数（000001.SS）；
      持续期 = 收盘价连续处于 MA200 同一侧的交易日数；
      主判据 = 上方持续期总和 / 下方持续期总和 ≈ 1.0（95% CI 说明容差）；
      CI = 对日度 above 指示序列做 250 交易日块循环 block bootstrap（2000 次，
      保留年线 regime 的自相关结构），重抽样比例的 2.5/97.5 分位；
      样本外 = 后 20% 交易日单独报告比例。
    """
    rng = np.random.default_rng(seed)
    con = sqlite3.connect(DB)
    row = con.execute("SELECT id, ticker, name FROM indices WHERE ticker='000001.SS'").fetchone()
    con.close()
    if row is None:
        print("错误：库里找不到 000001.SS（上证指数）")
        return 1
    iid, ticker, name = row
    rows = sqlite3.connect(DB).execute(
        "SELECT date, close FROM daily_data WHERE index_id=? AND close IS NOT NULL AND close > 0 "
        "ORDER BY date", (iid,)).fetchall()
    dates = [r[0] for r in rows]
    closes = np.asarray([r[1] for r in rows], dtype=np.float64)
    n = len(closes)
    if n < 201:
        print(f"错误：上证指数数据不足（{n} 行 < 201）")
        return 1

    vma = _ma200(closes)
    above = closes[199:] > vma[199:]   # 从 MA 有效首日起的日度 above 指示
    m_valid = len(above)
    date_span = (dates[199], dates[-1])

    def duration_ratio(ind):
        """上方持续期总和 / 下方持续期总和 = 天数比（同一段窗口内的天数占比之比）。"""
        a = int(np.sum(ind))
        b = int(len(ind) - a)
        return (a / b) if b > 0 else None

    def ratio_boot_ci(ind, iters=BOOT_ITERS):
        m = len(ind)
        nb = int(np.ceil(m / block_days))
        boots = np.empty(iters)
        for k in range(iters):
            starts = rng.integers(0, m, size=nb)
            idxs = (starts[:, None] + np.arange(block_days)[None, :]) % m
            sample = ind[idxs.reshape(-1)][:m]
            r = duration_ratio(sample)
            boots[k] = r if r is not None else np.inf
        return {"point": round(duration_ratio(ind), 4),
                "ci95_low": round(float(np.percentile(boots, 2.5)), 4),
                "ci95_high": round(float(np.percentile(boots, 97.5)), 4),
                "n_blocks_per_draw": nb, "block_days": block_days}

    full = ratio_boot_ci(above)
    # 样本外：后 20% 交易日
    oos_start = int(np.floor((1.0 - oos_frac) * m_valid))
    oos = ratio_boot_ci(above[oos_start:])

    def verdict_for(blk):
        r, lo, hi = blk["point"], blk["ci95_low"], blk["ci95_high"]
        return {"ratio": r, "ci95": [lo, hi],
                "ci_contains_1": bool(lo <= 1.0 <= hi),
                "within_20pct_band": bool(0.8 <= r <= 1.25)}

    v_full, v_oos = verdict_for(full), verdict_for(oos)
    verdict = {
        "primary": "上方持续期总和 / 下方持续期总和 ≈ 1.0",
        "full": v_full, "oos": v_oos,
        "n_days_above": int(np.sum(above)), "n_days_below": int(m_valid - np.sum(above)),
        "n_days_valid": m_valid, "date_span": list(date_span),
        "oos_n_days": int(m_valid - oos_start),
    }
    verdict["supported"] = v_full["ci_contains_1"] and v_full["within_20pct_band"]

    payload = {
        "claim": {k: claim[k] for k in ("id", "title", "statement", "h0", "price_basis",
                                        "cost_bps", "signal_def", "verdict_metric",
                                        "data_scope") if k in claim},
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "engine": "annual-line-duration-ratio",
        "config": {"bootstrap_iters": BOOT_ITERS, "rng_seed": RNG_SEED, "oos_frac": OOS_FRAC,
                   "vma_window": 200, "block_days": block_days,
                   "index": {"id": iid, "ticker": ticker, "name": name}},
        "survivorship_note": "指数为全历史连续序列，无退市问题（claims-def data_scope）",
        "protocol_lights": _event_count_lights("上/下持续期总和之比 ≈ 1.0"),
        "result": verdict,
    }
    return _emit_results(claim, out_dir, payload,
                         lambda: print(f"  上/下持续期比={full['point']} CI95=[{full['ci95_low']},{full['ci95_high']}] "
                                       f"→ supported={verdict['supported']} | OOS={oos['point']} "
                                       f"CI=[{oos['ci95_low']},{oos['ci95_high']}]"))


# --------------------------------------------------------------------------
# 8e) 论断 #6 引擎：年线上停留条件期望（engine: annual-line-hold-expectation）
# --------------------------------------------------------------------------
def run_annual_line_hold(claim, out_dir, oos_frac=OOS_FRAC, seed=RNG_SEED,
                         checkpoint_day=10):
    """实现 000-claims-def.md id=6 契约（engine: annual-line-hold-expectation）：
      事件 = 一次连续站上 MA200 的 above 段（episode），段长 d = 连续交易日数；
      无条件期望 = 全部 above 段的 d 均值；
      条件期望 = d >= 10 的段的额外停留（d − 10）均值；
      主判据 = 条件额外期望 / 无条件期望 ≥ 2；
      右删失段（序列末仍在年线上方、段未结束）不计入均值（两头口径一致），
      数量单独记录；样本外 = 段起点落在该标的后 20% 交易日的段单独统计；
      显著性 = 段级 bootstrap（段之间天然不重叠）2000 次重抽样给比率 CI。
    """
    rng = np.random.default_rng(seed)
    markets = claim["data_scope"].get("markets", [])
    category = claim["data_scope"].get("category", "stock")

    agg = {"durations": [], "censored": 0, "stocks": 0,
           "pairs": []}   # pairs: 每股 (mean_additional, mean_all)
    oos_agg = {"durations": [], "censored": 0, "stocks": 0, "pairs": []}
    per_market = {}

    def episodes_of(closes, oos_start):
        """返回 (durations, censored_n, oos_durations, oos_censored_n)。"""
        vma = _ma200(closes)
        above = closes[199:] > vma[199:]
        m = len(above)
        if m < 1:
            return [], 0, [], 0
        d = np.diff(above.astype(np.int8))
        starts = list(np.where(d == 1)[0] + 1)
        ends = list(np.where(d == -1)[0] + 1)     # end = 首个离开日（排他）
        if above[0]:
            starts.insert(0, 0)
        if above[-1]:
            ends.append(m)                        # 右删失段
        censored, o_censored = 0, 0
        durs, o_durs = [], []
        for s, e in zip(starts, ends):
            censored_ep = (e == m and above[-1])
            g_start = s + 199                     # 全局下标
            if censored_ep:
                if g_start >= oos_start:
                    o_censored += 1
                else:
                    censored += 1
                continue
            durs.append(e - s)
            if g_start >= oos_start:
                o_durs.append(e - s)
        return durs, censored, o_durs, o_censored

    for m_ in markets:
        series = load_market_series(m_, category)
        if series is None:
            continue
        mstat = {"stocks_total": len(series), "stocks_processed": 0,
                 "episodes": 0, "censored": 0}
        oos_mstat = {"episodes": 0, "censored": 0}
        for iid, (ticker, dates, closes) in series.items():
            n = int(len(closes))
            if n < 201:
                continue
            mstat["stocks_processed"] += 1
            oos_start = int(np.floor((1.0 - oos_frac) * n))
            durs, cen, o_durs, o_cen = episodes_of(closes, oos_start)
            if durs:
                arr = np.asarray(durs, dtype=np.float64)
                agg["durations"].append(arr)
                mstat["episodes"] += len(durs)
                mean_all = float(np.mean(arr))
                sel = arr[arr >= checkpoint_day]
                if len(sel):
                    mean_add = float(np.mean(sel - checkpoint_day))
                    agg["pairs"].append((mean_add, mean_all))
            mstat["censored"] += cen
            agg["censored"] += cen; agg["stocks"] += 1
            if o_durs:
                oarr = np.asarray(o_durs, dtype=np.float64)
                oos_agg["durations"].append(oarr)
                oos_mstat["episodes"] += len(o_durs)
                o_mean_all = float(np.mean(oarr))
                osel = oarr[oarr >= checkpoint_day]
                if len(osel):
                    oos_agg["pairs"].append((float(np.mean(osel - checkpoint_day)), o_mean_all))
            oos_mstat["censored"] += o_cen
            oos_agg["censored"] += o_cen; oos_agg["stocks"] += 1

        per_market[m_] = {
            "stocks_total": mstat["stocks_total"],
            "stocks_processed": mstat["stocks_processed"],
            "episodes": mstat["episodes"], "censored_excluded": mstat["censored"],
            "oos_episodes": oos_mstat["episodes"],
        }
        print(f"    [{datetime.now():%H:%M:%S}] {m_} done "
              f"({mstat['stocks_processed']}/{mstat['stocks_total']})", file=sys.stderr, flush=True)

    def pooled_stats(a):
        if not a["durations"]:
            return None
        all_d = np.concatenate(a["durations"])
        sel = all_d[all_d >= checkpoint_day]
        mean_all = float(np.mean(all_d))
        mean_add = float(np.mean(sel - checkpoint_day)) if len(sel) else None
        ratio = mean_add / mean_all if mean_add is not None else None
        # 段级 bootstrap：段之间天然不重叠，直接重抽样段
        boot = None
        if len(all_d) >= 2 and len(sel) >= 1:
            boots = np.empty(BOOT_ITERS)
            nd = len(all_d)
            for k in range(BOOT_ITERS):
                s = all_d[rng.integers(0, nd, size=nd)]
                ssel = s[s >= checkpoint_day]
                boots[k] = (np.mean(ssel - checkpoint_day) / np.mean(s)
                            if len(ssel) else np.nan)
            boots = boots[~np.isnan(boots)]
            if len(boots):
                boot = {"point": round(ratio, 4) if ratio is not None else None,
                        "ci95_low": round(float(np.percentile(boots, 2.5)), 4),
                        "ci95_high": round(float(np.percentile(boots, 97.5)), 4)}
        # 股票级配对（EW 比率）block bootstrap
        ew = None
        if len(a["pairs"]) >= 2:
            arr = np.asarray(a["pairs"], dtype=np.float64)
            boots = np.empty(BOOT_ITERS)
            for k in range(BOOT_ITERS):
                idx = rng.integers(0, len(arr), size=len(arr))
                boots[k] = np.mean(arr[idx][:, 0]) / np.mean(arr[idx][:, 1])
            ew = {"point": round(float(np.mean(arr[:, 0]) / np.mean(arr[:, 1])), 4),
                  "ci95_low": round(float(np.percentile(boots, 2.5)), 4),
                  "ci95_high": round(float(np.percentile(boots, 97.5)), 4),
                  "n_stocks": int(len(arr))}
        return {"episodes": int(len(all_d)), "episodes_ge_10": int(len(sel)),
                "mean_hold_all": round(mean_all, 2),
                "median_hold_all": float(np.median(all_d)),
                "mean_additional_after_10": round(mean_add, 2) if mean_add is not None else None,
                "ratio": round(ratio, 4) if ratio is not None else None,
                "bootstrap": boot, "stock_ew": ew,
                "censored_excluded": a["censored"], "stocks": a["stocks"]}

    full = pooled_stats(agg)
    oos_full = pooled_stats(oos_agg)
    ratio = full["ratio"] if full else None
    oos_ratio = oos_full["ratio"] if oos_full else None

    verdict = {
        "threshold": 2.0,
        "checkpoint_day": checkpoint_day,
        "ratio_pooled": round(ratio, 4) if ratio is not None else None,
        "mean_hold_all": full["mean_hold_all"] if full else None,
        "mean_additional_after_10": full["mean_additional_after_10"] if full else None,
        "bootstrap": full["bootstrap"] if full else None,
        "stock_ew": full["stock_ew"] if full else None,
        "supported_pooled": bool(ratio is not None and ratio >= 2.0),
        "oos_ratio_pooled": round(oos_ratio, 4) if oos_ratio is not None else None,
        "oos_bootstrap": oos_full["bootstrap"] if oos_full else None,
        "oos_supported": bool(oos_ratio is not None and oos_ratio >= 2.0),
        "n_episodes": full["episodes"] if full else 0,
        "n_censored_excluded": agg["censored"],
    }
    verdict["supported"] = verdict["supported_pooled"]

    payload = {
        "claim": {k: claim[k] for k in ("id", "title", "statement", "h0", "price_basis",
                                        "cost_bps", "signal_def", "verdict_metric",
                                        "data_scope") if k in claim},
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "engine": "annual-line-hold-expectation",
        "config": {"bootstrap_iters": BOOT_ITERS, "rng_seed": RNG_SEED, "oos_frac": OOS_FRAC,
                   "vma_window": 200, "checkpoint_day": checkpoint_day,
                   "censoring": "序列末仍未跌破年线的段（右删失）不计入均值，数量单列",
                   "markets": list(per_market.keys())},
        "pools": {"markets": list(per_market.keys()),
                  "stocks_total_by_market": {m: per_market[m]["stocks_total"] for m in per_market},
                  "stocks_processed_by_market": {m: per_market[m]["stocks_processed"] for m in per_market}},
        "survivorship_note": "本地库 indices 仅当前成分股快照，不含退市/被剔除股；缺退市前下跌段会截短长段，方向已知、如实记录",
        "protocol_lights": _event_count_lights("条件额外停留期望 / 无条件停留期望 ≥ 2"),
        "per_market": per_market,
        "aggregate": full, "aggregate_oos": oos_full,
        "verdict": verdict,
    }
    return _emit_results(claim, out_dir, payload,
                         lambda: print(f"  条件额外期望/无条件期望={verdict['ratio_pooled']} "
                                       f"(均停留={verdict['mean_hold_all']}天, >=10天段额外="
                                       f"{verdict['mean_additional_after_10']}天) "
                                       f"CI={verdict['bootstrap']} → supported={verdict['supported']} "
                                       f"| OOS={verdict['oos_ratio_pooled']}"))


# --------------------------------------------------------------------------
# 8e) 论断 #9 引擎：缩量回踩支撑反弹（engine: volume-pullback-rebound）
# --------------------------------------------------------------------------
def run_volume_pullback(claim, out_dir, oos_frac=OOS_FRAC, seed=RNG_SEED):
    """实现 000-claims-def.md id=9 契约（engine: volume-pullback-rebound）：
      信号日 T：收盘价贴近 MA50（|close-MA50|/MA50<=1%）且此前 5 日内曾在 MA50 上方 1%+（回踩），
                且 volume_T < 0.7 × 前 20 日均量（缩量）；
      支撑确认：T+1..T+5 每日收盘 >= 当日 MA50（不跌破支撑），确认在 T+5 收盘后成立；
      入场 = T+6 收盘（信号完全确定后的第一个可交易收盘，无前视）；
      结局 = 入场后 20 个交易日收盘 vs 入场价，上涨即胜；
      主判据 = 胜率 >60%（论断口径本身，铁律一）。
      样本外 = 每标的后 20% 样本单独报告胜率；显著性 = 股票级 bootstrap（每股坍缩为胜率）。
    """
    rng = np.random.default_rng(seed)
    markets = claim["data_scope"].get("markets", [])
    category = claim["data_scope"].get("category", "stock")

    PULL_TOL = 0.01      # 贴近 MA50 容差 ±1%
    ABOVE_TOL = 0.01     # 此前曾站上 MA50 1%+
    VOL_RATIO = 0.7      # 缩量阈值：信号日量 < 70% 前20日均量
    VOL_WIN = 20         # 量均线窗口
    CONF_DAYS = 5        # 支撑确认观察窗
    HOLD = 20            # 入场后持有交易日数
    MIN_ROWS = 110       # MA50(50)+VOL(20)+确认(6)+持有(20)+缓冲

    con = sqlite3.connect(DB)
    qmarks = ",".join("?" * len(markets))
    rows = con.execute(
        "SELECT i.market, d.index_id, i.ticker, d.date, d.close, d.volume "
        "FROM daily_data d JOIN indices i ON d.index_id = i.id "
        f"WHERE i.market IN ({qmarks}) AND i.category = ? AND d.close IS NOT NULL AND d.close > 0 "
        "ORDER BY d.date", (*markets, category)
    ).fetchall()
    con.close()
    by_market = {}
    for m, iid, tk, dt, c, v in rows:
        by_market.setdefault(m, []).append((iid, tk, dt, c, v))

    agg = {"events": 0, "wins": 0, "rates": []}
    oos_agg = {"events": 0, "wins": 0, "rates": []}
    per_market = {}

    for m in markets:
        recs = by_market.get(m, [])
        buckets = {}
        for iid, tk, dt, c, v in recs:
            buckets.setdefault(iid, []).append((dt, c, v))
        mstat = {"stocks_total": len(buckets), "stocks_processed": 0,
                 "events": 0, "wins": 0, "no_volume_skips": 0}
        oos_mstat = {"events": 0, "wins": 0}
        for iid, series in buckets.items():
            n = len(series)
            if n < MIN_ROWS:
                continue
            dates = [s[0] for s in series]
            closes = np.asarray([s[1] for s in series], dtype=np.float64)
            vols = np.asarray([(s[2] if s[2] is not None else np.nan) for s in series],
                              dtype=np.float64)
            if np.isnan(vols).all():
                mstat["no_volume_skips"] += 1
                continue
            ma50 = np.full(n, np.nan)
            for t in range(49, n):
                ma50[t] = closes[t - 49:t + 1].mean()
            vma20 = np.full(n, np.nan)
            vv = np.where(np.isnan(vols), np.nan, vols)
            for t in range(VOL_WIN, n):
                w = vv[t - VOL_WIN:t]          # 前 20 日（不含 T）
                if not np.isnan(w).any():
                    vma20[t] = w.mean()
            mstat["stocks_processed"] += 1

            ev_idx, win_flags = [], []
            for t in range(54, n - CONF_DAYS - 1 - HOLD):
                if np.isnan(ma50[t]) or np.isnan(vma20[t]):
                    continue
                c, ma = closes[t], ma50[t]
                if abs(c - ma) / ma > PULL_TOL:
                    continue
                if not np.any(closes[t - 5:t] > ma50[t - 5:t] * (1 + ABOVE_TOL)):
                    continue
                v = vols[t]
                if np.isnan(v) or v <= 0 or not (v < VOL_RATIO * vma20[t]):
                    continue
                # 支撑确认：T+1..T+5 每日收盘 >= 当日 MA50
                conf = all(closes[t + k] >= ma50[t + k] for k in range(1, CONF_DAYS + 1))
                if not conf:
                    continue
                entry_t = t + CONF_DAYS + 1      # T+6 收盘入场
                exit_t = entry_t + HOLD
                if exit_t >= n:
                    continue
                ev_idx.append(entry_t)
                win_flags.append(closes[exit_t] > closes[entry_t])
            n_ev = len(ev_idx)
            if n_ev:
                n_win = int(np.sum(win_flags))
                mstat["events"] += n_ev; mstat["wins"] += n_win
                agg["events"] += n_ev; agg["wins"] += n_win
                agg["rates"].append(n_win / n_ev)
                oos_start = int(np.floor((1.0 - oos_frac) * n))
                sel = [i for i, e in enumerate(ev_idx) if e >= oos_start]
                o_ev, o_win = len(sel), int(sum(win_flags[i] for i in sel))
                oos_mstat["events"] += o_ev; oos_mstat["wins"] += o_win
                oos_agg["events"] += o_ev; oos_agg["wins"] += o_win
                if o_ev:
                    oos_agg["rates"].append(o_win / o_ev)

        per_market[m] = {
            "stocks_total": mstat["stocks_total"],
            "stocks_processed": mstat["stocks_processed"],
            "no_volume_skips": mstat["no_volume_skips"],
            "events": mstat["events"], "wins": mstat["wins"],
            "win_rate_pct": round(100.0 * mstat["wins"] / mstat["events"], 2)
                            if mstat["events"] else None,
            "oos": {"events": oos_mstat["events"], "wins": oos_mstat["wins"],
                    "win_rate_pct": round(100.0 * oos_mstat["wins"] / oos_mstat["events"], 2)
                                    if oos_mstat["events"] else None},
        }
        print(f"    [{datetime.now():%H:%M:%S}] {m} done "
              f"({mstat['stocks_processed']}/{mstat['stocks_total']})", file=sys.stderr, flush=True)

    def rate_boot(rates):
        if len(rates) < 2:
            return None
        arr = np.asarray(rates, dtype=np.float64)
        boots = np.empty(BOOT_ITERS)
        for k in range(BOOT_ITERS):
            idx = rng.integers(0, len(arr), size=len(arr))
            boots[k] = np.mean(arr[idx])
        return {"mean_pct": round(float(np.mean(arr)) * 100, 2),
                "ci95_low_pct": round(float(np.percentile(boots, 2.5)) * 100, 2),
                "ci95_high_pct": round(float(np.percentile(boots, 97.5)) * 100, 2)}

    pooled = round(100.0 * agg["wins"] / agg["events"], 2) if agg["events"] else None
    oos_pooled = round(100.0 * oos_agg["wins"] / oos_agg["events"], 2) if oos_agg["events"] else None
    boot = rate_boot(agg["rates"])
    oos_boot = rate_boot(oos_agg["rates"])
    threshold = 60.0
    verdict = {
        "threshold_pct": threshold,
        "win_rate_pooled_pct": pooled,
        "n_events": agg["events"], "n_wins": agg["wins"], "n_stocks": len(agg["rates"]),
        "stock_ew_boot": boot,
        "above_threshold_pooled": bool(pooled is not None and pooled > threshold),
        "oos_win_rate_pooled_pct": oos_pooled, "oos_events": oos_agg["events"],
        "oos_wins": oos_agg["wins"], "oos_stock_ew_boot": oos_boot,
        "oos_above_threshold_pooled": bool(oos_pooled is not None and oos_pooled > threshold),
    }
    verdict["supported"] = verdict["above_threshold_pooled"]

    lights = [
        {"item": "判据对齐（论断=反弹概率>60%）", "status": "✅",
         "note": "主判据就是论断声称的胜率本身（>60%），不用收益差替代（铁律一）"},
        {"item": "价格口径（前复权 close）", "status": "✅",
         "note": "daily_data.close 为前复权（000-data-biases.md A.1）"},
        {"item": "时机（无前视）", "status": "✅",
         "note": "信号三要素（贴近MA50/曾站上/缩量）在 T 日收盘可得；支撑确认只用 T+1..T+5；"
                 "入场取确认后第一个收盘 T+6，结局在 T+26——无同bar双用"},
        {"item": "交易成本", "status": "⚠️",
         "note": "主判据是涨跌方向概率，成本不改变方向；25bps 口径保留字段一致"},
        {"item": "显著性/区间（Bootstrap 2000 次）", "status": "✅",
         "note": f"股票级 bootstrap（每股坍缩为胜率，种子 {RNG_SEED} 可复现）"},
        {"item": "重叠样本处理", "status": "⚠️",
         "note": "相邻事件的 26 日窗口重叠 → 每股坍缩后股票级 bootstrap；跨股同日历相关未建模"},
        {"item": "样本外验证（后 20%）", "status": "✅",
         "note": "每标的自有交易日后 20% 的入场事件单独跑同口径"},
        {"item": "幸存者偏差（含退市股）", "status": "⚠️",
         "note": "本地库仅当前成分快照，缺退市前下跌段；回踩反弹类信号缺退市样本，方向已知无法修复"},
        {"item": "成交量数据质量", "status": "⚠️",
         "note": "volume 缺失/为0 的标的整只跳过（no_volume_skips 计数）；19 市场 volume 覆盖率约 95%+，"
                 "个别市场来源口径差异未逐源核对"},
    ]

    payload = {
        "claim": {k: claim[k] for k in ("id", "title", "statement", "h0", "price_basis",
                                        "cost_bps", "signal_def", "verdict_metric",
                                        "data_scope") if k in claim},
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "engine": "volume-pullback-rebound",
        "config": {"bootstrap_iters": BOOT_ITERS, "rng_seed": RNG_SEED, "oos_frac": OOS_FRAC,
                   "pull_tol": PULL_TOL, "above_tol": ABOVE_TOL, "vol_ratio": VOL_RATIO,
                   "vol_window": VOL_WIN, "confirm_days": CONF_DAYS, "hold_days": HOLD,
                   "markets": list(per_market.keys())},
        "pools": {"markets": list(per_market.keys()),
                  "stocks_processed_by_market": {m: per_market[m]["stocks_processed"] for m in per_market}},
        "survivorship_note": "本地库 indices 仅当前成分股快照，不含退市/被剔除股；结果存在幸存者偏差，方向为高估反弹概率",
        "protocol_lights": lights,
        "per_market": per_market,
        "aggregate": {"events": agg["events"], "wins": agg["wins"], "win_rate_pct": pooled},
        "aggregate_oos": {"events": oos_agg["events"], "wins": oos_agg["wins"],
                          "win_rate_pct": oos_pooled},
        "verdict": verdict,
    }
    return _emit_results(claim, out_dir, payload,
                         lambda: print(f"  反弹胜率(pooled)={pooled}% 事件={agg['events']} "
                                       f"股级EW CI={boot} 判据>60% → supported={verdict['supported']}",
                                       f"  OOS胜率={oos_pooled}% (事件 {oos_agg['events']})"))


# --------------------------------------------------------------------------
# 8c-3) 论断 #10 引擎：放量突破在技术信号中排名最高（engine: volume-breakout-ranking）
# --------------------------------------------------------------------------
def run_breakout_volume(claim, out_dir, oos_frac=OOS_FRAC, seed=RNG_SEED):
    """实现 000-claims-def.md id=10 契约（engine: volume-breakout-ranking）：
      排名型论断——四信号同台对比，各信号 20 交易日胜率：
        S1 放量突破：close_T 创 50 日新高（> 前 50 日最高收盘，且 T-1 未创新高=新鲜突破）
                    且 vol_T > 1.5×前 20 日均量（不含 T）；
        S2 无量突破：同 S1 去掉量条件（S1 ⊂ S2）；
        S3 缩量回踩：#9 口径原样（含 5 日确认窗，T+6 入场）；
        S4 金叉：MA50 上穿 MA120。
      S1/S2/S4 入场 = T+1 收盘；S3 入场 = T+6 收盘（确认后）。持 20 交易日，收盘涨为胜。
      主判据 = S1 pooled 胜率在四信号中最高（pooled 与分市场双口径）；
      次判据 = S1−S2 每股胜率差的股票级 bootstrap CI（"放量"是否真加分）。
      样本外 = 每标的后 20% 入场事件单独报告。
    """
    rng = np.random.default_rng(seed)
    markets = claim["data_scope"].get("markets", [])
    category = claim["data_scope"].get("category", "stock")

    VOL_RATIO = 1.5
    HOLD = 20
    MIN_ROWS = 150   # MA120(120)+入场1+持有20+缓冲

    SIGS = ["S1_volume_breakout", "S2_breakout", "S3_volume_pullback", "S4_golden_cross"]

    con = sqlite3.connect(DB)
    qmarks = ",".join("?" * len(markets))
    rows = con.execute(
        "SELECT i.market, d.index_id, i.ticker, d.date, d.close, d.volume "
        "FROM daily_data d JOIN indices i ON d.index_id = i.id "
        f"WHERE i.market IN ({qmarks}) AND i.category = ? AND d.close IS NOT NULL AND d.close > 0 "
        "ORDER BY d.date", (*markets, category)
    ).fetchall()
    con.close()
    by_market = {}
    for m, iid, tk, dt, c, v in rows:
        by_market.setdefault(m, []).append((iid, tk, dt, c, v))

    from numpy.lib.stride_tricks import sliding_window_view

    def _rolling_mean(x, w):
        """滚动均值，窗口内有 nan 则该位 nan。x[0..n-1]，输出同长。"""
        out = np.full(len(x), np.nan)
        if len(x) < w:
            return out
        sw = sliding_window_view(x, w)          # [t-w+1 .. t]
        ok = ~np.isnan(sw).any(axis=1)
        out[w - 1:] = np.where(ok, sw.mean(axis=1), np.nan)
        return out

    # agg[sig] = dict(events, wins, rates, oos_events, oos_wins, oos_rates)
    agg = {s: {"events": 0, "wins": 0, "rates": [],
               "oos_events": 0, "oos_wins": 0, "oos_rates": []} for s in SIGS}
    per_market = {m: {s: {"events": 0, "wins": 0, "oos_events": 0, "oos_wins": 0}
                      for s in SIGS} for m in markets}
    per_market_stocks = {m: 0 for m in markets}
    stocks_total = 0
    no_volume_skips = 0
    diff_rates = []          # 每股 S1胜率 − S2胜率（配对差）

    for m in markets:
        recs = by_market.get(m, [])
        buckets = {}
        for iid, tk, dt, c, v in recs:
            buckets.setdefault(iid, []).append((dt, c, v))
        stocks_total += len(buckets)
        for iid, series in buckets.items():
            n = len(series)
            if n < MIN_ROWS:
                continue
            closes = np.asarray([s[1] for s in series], dtype=np.float64)
            vols = np.asarray([(s[2] if s[2] is not None else np.nan) for s in series],
                              dtype=np.float64)
            if np.isnan(vols).all():
                no_volume_skips += 1
                continue
            ma50 = _rolling_mean(closes, 50)
            ma120 = _rolling_mean(closes, 120)
            vma20 = _rolling_mean(np.where(np.isnan(vols), np.nan, vols), 20)
            prior_max = np.full(n, np.nan)
            if n >= 51:
                sw = sliding_window_view(closes, 50)   # sw[i] = closes[i..i+49]
                prior_max[50:] = sw[:-1].max(axis=1)   # prior_max[t] = max(closes[t-50:t])，不含 T

            # 事件索引（入场日）与胜负
            evs = {s: ([], []) for s in SIGS}   # sig -> (entry_idx list, win list)

            def add(sig, entry_t):
                exit_t = entry_t + HOLD
                if exit_t < n:
                    evs[sig][0].append(entry_t)
                    evs[sig][1].append(bool(closes[exit_t] > closes[entry_t]))

            for t in range(120, n - 1):
                # S2 无量突破：新鲜突破 50 日新高（T 日新高且 T-1 未新高）
                if not (np.isnan(prior_max[t]) or np.isnan(prior_max[t - 1])) \
                        and closes[t] > prior_max[t] and closes[t - 1] <= prior_max[t - 1]:
                    add("S2_breakout", t + 1)
                    v = vols[t]
                    if not np.isnan(v) and not np.isnan(vma20[t]) and v > VOL_RATIO * vma20[t]:
                        add("S1_volume_breakout", t + 1)
                # S4 金叉：MA50 上穿 MA120
                if not np.isnan(ma50[t]) and not np.isnan(ma120[t]) \
                        and not np.isnan(ma50[t - 1]) and not np.isnan(ma120[t - 1]) \
                        and ma50[t] > ma120[t] and ma50[t - 1] <= ma120[t - 1]:
                    add("S4_golden_cross", t + 1)
                # S3 缩量回踩（#9 口径，含 5 日确认，T+6 入场）
                if t + 6 + HOLD < n and not np.isnan(ma50[t]) and not np.isnan(vma20[t]):
                    c0, ma = closes[t], ma50[t]
                    if abs(c0 - ma) / ma <= 0.01 \
                            and np.any(closes[t - 5:t] > ma50[t - 5:t] * 1.01):
                        v = vols[t]
                        if not np.isnan(v) and v > 0 and v < 0.7 * vma20[t] \
                                and all(closes[t + k] >= ma50[t + k] for k in range(1, 6)):
                            add("S3_volume_pullback", t + 6)

            if not any(evs[s][0] for s in SIGS):
                continue
            per_market_stocks[m] += 1
            oos_start = int(np.floor((1.0 - oos_frac) * n))
            r1 = r2 = None
            for sig in SIGS:
                idxs, wins = evs[sig]
                if not idxs:
                    continue
                n_ev, n_win = len(idxs), int(np.sum(wins))
                a = agg[sig]
                a["events"] += n_ev; a["wins"] += n_win; a["rates"].append(n_win / n_ev)
                pm = per_market[m][sig]
                pm["events"] += n_ev; pm["wins"] += n_win
                sel = [i for i, e in enumerate(idxs) if e >= oos_start]
                if sel:
                    o_ev, o_win = len(sel), int(sum(wins[i] for i in sel))
                    a["oos_events"] += o_ev; a["oos_wins"] += o_win
                    a["oos_rates"].append(o_win / o_ev)
                    pm["oos_events"] += o_ev; pm["oos_wins"] += o_win
                if sig == "S1_volume_breakout":
                    r1 = n_win / n_ev
                elif sig == "S2_breakout":
                    r2 = n_win / n_ev
            if r1 is not None and r2 is not None:
                diff_rates.append(r1 - r2)
        print(f"    [{datetime.now():%H:%M:%S}] {m} done "
              f"({per_market_stocks[m]}/{len(buckets)})", file=sys.stderr, flush=True)

    def rate_boot(rates):
        if len(rates) < 2:
            return None
        arr = np.asarray(rates, dtype=np.float64)
        boots = np.empty(BOOT_ITERS)
        for k in range(BOOT_ITERS):
            idx = rng.integers(0, len(arr), size=len(arr))
            boots[k] = np.mean(arr[idx])
        return {"mean_pct": round(float(np.mean(arr)) * 100, 2),
                "ci95_low_pct": round(float(np.percentile(boots, 2.5)) * 100, 2),
                "ci95_high_pct": round(float(np.percentile(boots, 97.5)) * 100, 2)}

    def sig_summary(sig):
        a = agg[sig]
        pooled = round(100.0 * a["wins"] / a["events"], 2) if a["events"] else None
        oos = round(100.0 * a["oos_wins"] / a["oos_events"], 2) if a["oos_events"] else None
        return {"events": a["events"], "wins": a["wins"], "win_rate_pct": pooled,
                "stock_ew_boot": rate_boot(a["rates"]),
                "oos": {"events": a["oos_events"], "wins": a["oos_wins"],
                        "win_rate_pct": oos, "stock_ew_boot": rate_boot(a["oos_rates"])}}

    summaries = {s: sig_summary(s) for s in SIGS}
    p1 = summaries["S1_volume_breakout"]["win_rate_pct"]
    others = {s: summaries[s]["win_rate_pct"] for s in SIGS if s != "S1_volume_breakout"}
    is_highest_pooled = bool(p1 is not None and all(
        v is not None and p1 > v for v in others.values()))
    # 分市场口径：S1 在多少个市场排第一（只统计四信号在该市场均有事件者）
    mk_highest, mk_comparable = 0, 0
    mk_detail = {}
    for m in markets:
        pts = {}
        for s in SIGS:
            pm = per_market[m][s]
            pts[s] = round(100.0 * pm["wins"] / pm["events"], 2) if pm["events"] else None
        if all(pts[s] is not None for s in SIGS):
            mk_comparable += 1
            top = max(pts, key=lambda s: pts[s])
            if top == "S1_volume_breakout":
                mk_highest += 1
        mk_detail[m] = pts
    diff_boot = None
    if len(diff_rates) >= 2:
        arr = np.asarray(diff_rates, dtype=np.float64)
        boots = np.empty(BOOT_ITERS)
        for k in range(BOOT_ITERS):
            idx = rng.integers(0, len(arr), size=len(arr))
            boots[k] = np.mean(arr[idx])
        diff_boot = {"mean_pct": round(float(np.mean(arr)) * 100, 2),
                     "ci95_low_pct": round(float(np.percentile(boots, 2.5)) * 100, 2),
                     "ci95_high_pct": round(float(np.percentile(boots, 97.5)) * 100, 2)}

    verdict = {
        "claim_type": "ranking（相对排名，非绝对阈值）",
        "s1_win_rate_pct": p1, "other_signals_pct": others,
        "s1_highest_pooled": is_highest_pooled,
        "s1_highest_markets": mk_highest,
        "markets_comparable": mk_comparable,
        "s1_minus_s2_diff_stock_ew_boot": diff_boot,
        "supported": is_highest_pooled,
    }

    lights = [
        {"item": "判据对齐（论断=排名最高）", "status": "✅",
         "note": "排名型论断，主判据就是相对排名本身（S1 vs S2/S3/S4 同台 20 日胜率），不用绝对阈值替代（铁律一）"},
        {"item": "价格口径（前复权 close）", "status": "✅",
         "note": "daily_data.close 为前复权（000-data-biases.md A.1）"},
        {"item": "时机（无前视）", "status": "✅",
         "note": "各信号在 T 日收盘确定；S1/S2/S4 入场=T+1 收盘，S3 入场=T+6（确认后）；"
                 "50 日新高=前 50 日窗口不含 T；量均线=前 20 日不含 T"},
        {"item": "交易成本", "status": "⚠️",
         "note": "主判据是方向概率排名，成本不改变方向；25bps 口径保留字段一致"},
        {"item": "显著性/区间（Bootstrap 2000 次）", "status": "✅",
         "note": f"股票级 bootstrap（每股坍缩为胜率；S1−S2 配对差同法，种子 {RNG_SEED}）"},
        {"item": "重叠样本处理", "status": "⚠️",
         "note": "相邻突破/金叉事件 20 日窗口重叠 → 每股坍缩后股票级 bootstrap；跨股同日历相关未建模"},
        {"item": "样本外验证（后 20%）", "status": "✅",
         "note": "每标的自有交易日后 20% 的入场事件单独跑同口径"},
        {"item": "幸存者偏差（含退市股）", "status": "⚠️",
         "note": "本地库仅当前成分快照；突破/动量类信号缺退市前下跌段，方向为高估胜率"},
        {"item": "成交量数据质量", "status": "⚠️",
         "note": "volume 全缺失标的整只跳过（no_volume_skips 计数）；S3 另要求缩量有效"},
        {"item": "口径对齐（S3 沿用 #9 契约）", "status": "✅",
         "note": "S3 与论断 #9 引擎完全同口径（含 5 日确认/T+6 入场），保证跨论断可比"},
    ]

    payload = {
        "claim": {k: claim[k] for k in ("id", "title", "statement", "h0", "price_basis",
                                        "cost_bps", "signal_def", "verdict_metric",
                                        "data_scope") if k in claim},
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "engine": "volume-breakout-ranking",
        "config": {"bootstrap_iters": BOOT_ITERS, "rng_seed": RNG_SEED, "oos_frac": OOS_FRAC,
                   "vol_ratio": VOL_RATIO, "breakout_window": 50, "hold_days": HOLD,
                   "golden_cross": "MA50 上穿 MA120", "min_rows": MIN_ROWS,
                   "markets": list(per_market.keys())},
        "pools": {"stocks_total": stocks_total,
                  "stocks_processed_by_market": per_market_stocks,
                  "no_volume_skips": no_volume_skips},
        "survivorship_note": "本地库 indices 仅当前成分股快照，不含退市/被剔除股；结果存在幸存者偏差，方向为高估突破类胜率",
        "protocol_lights": lights,
        "signals": summaries,
        "per_market": mk_detail,
        "verdict": verdict,
    }
    return _emit_results(claim, out_dir, payload,
                         lambda: print(f"  四信号20日胜率: " +
                                       "  ".join(f"{s}={summaries[s]['win_rate_pct']}%" for s in SIGS),
                                       f"  S1最高(pooled)={is_highest_pooled} 分市场S1第一 {mk_highest}/{mk_comparable}",
                                       f"  S1−S2 差 CI={diff_boot} → supported={verdict['supported']}"))


# --------------------------------------------------------------------------
# 8c-4) 论断 #2 引擎：年线过滤降回撤>50%（engine: annual-line-filter-mdd）
# --------------------------------------------------------------------------
def run_annual_line_filter_mdd(claim, out_dir, oos_frac=OOS_FRAC, seed=RNG_SEED):
    """实现 000-claims-def.md id=2 契约（engine: annual-line-filter-mdd）：
      策略A（过滤）：T 日收益 = r_T 若 close_{T-1} ≥ MA200_{T-1}，否则 0（现金不计息，保守）；
                    每次仓位切换扣 25bps。策略B（买入持有）：始终 r_T。
      两策略均自 MA200 有效首日累计 NAV；MDD = max(1 − NAV/历史峰值)；
      每股降幅 = 1 − MDD_A / MDD_B；主判据 = 每股降幅 EW 均值 >50%。
      样本外 = 后 20% 交易日子区间内两策略 MDD 重算降幅。
      显著性 = 股票级 bootstrap（每股坍缩为降幅，2000 次）。
    """
    rng = np.random.default_rng(seed)
    markets = claim["data_scope"].get("markets", [])
    category = claim["data_scope"].get("category", "stock")
    COST_BPS = 25
    MIN_ROWS = 260

    con = sqlite3.connect(DB)
    qmarks = ",".join("?" * len(markets))
    rows = con.execute(
        "SELECT i.market, d.index_id, i.ticker, d.date, d.close "
        "FROM daily_data d JOIN indices i ON d.index_id = i.id "
        f"WHERE i.market IN ({qmarks}) AND i.category = ? AND d.close IS NOT NULL AND d.close > 0 "
        "ORDER BY d.date", (*markets, category)
    ).fetchall()
    con.close()
    by_market = {}
    for m, iid, tk, dt, c in rows:
        by_market.setdefault(m, []).append((iid, tk, dt, c))

    from numpy.lib.stride_tricks import sliding_window_view

    reductions, oos_reductions = [], []
    per_market = {}
    stocks_total = 0

    def mdd_of(nav):
        peak = np.maximum.accumulate(nav)
        return float(np.max(1.0 - nav / peak)) if len(nav) else np.nan

    for m in markets:
        recs = by_market.get(m, [])
        buckets = {}
        for iid, tk, dt, c in recs:
            buckets.setdefault(iid, []).append((dt, c))
        stocks_total += len(buckets)
        m_red, m_oos_red = [], []
        for iid, series in buckets.items():
            n = len(series)
            if n < MIN_ROWS:
                continue
            closes = np.asarray([s[1] for s in series], dtype=np.float64)
            ma200 = np.full(n, np.nan)
            if n >= 200:
                ma200[199:] = sliding_window_view(closes, 200).mean(axis=1)
            r = np.full(n, np.nan)
            r[1:] = closes[1:] / closes[:-1] - 1.0
            valid = ~np.isnan(ma200)
            start = int(np.argmax(valid))          # MA200 有效首日
            if start + 2 >= n:
                continue
            hold_above = np.zeros(n, dtype=bool)    # 信号用 T-1，无前视
            hold_above[1:] = closes[:-1] >= ma200[:-1]
            ra = np.where(hold_above, r, 0.0)
            # 仓位切换成本：持仓状态相邻两日不同 → 扣 25bps
            pos = hold_above.astype(np.int8)
            switches = np.zeros(n, dtype=np.float64)
            switches[1:] = (pos[1:] != pos[:-1]).astype(np.float64)
            ra = ra - switches * COST_BPS / 10000.0
            rb = r.copy()
            ra[:start + 1] = np.nan
            rb[:start + 1] = np.nan
            va = np.cumprod(1.0 + np.nan_to_num(ra))
            vb = np.cumprod(1.0 + np.nan_to_num(rb))
            da, db = mdd_of(va[start:]), mdd_of(vb[start:])
            if not (np.isfinite(da) and np.isfinite(db)) or db <= 0:
                continue
            red = 1.0 - da / db
            if not np.isfinite(red):
                continue
            reductions.append(red)
            m_red.append(red)
            # 样本外：后 20% 交易日子区间，两策略从区间起点重新累计
            oos_start = int(np.floor((1.0 - oos_frac) * n))
            if oos_start > start:
                va_o = vb_o = None
                ra_o = np.where(hold_above, r, 0.0) - switches * COST_BPS / 10000.0
                va_o = np.cumprod(1.0 + np.nan_to_num(ra_o[oos_start:]))
                vb_o = np.cumprod(1.0 + np.nan_to_num(rb[oos_start:]))
                da_o, db_o = mdd_of(va_o), mdd_of(vb_o)
                if np.isfinite(da_o) and np.isfinite(db_o) and db_o > 0 \
                        and np.isfinite(1.0 - da_o / db_o):
                    oos_reductions.append(1.0 - da_o / db_o)
                    m_oos_red.append(1.0 - da_o / db_o)
        per_market[m] = {
            "stocks_total": len(buckets), "stocks_processed": len(m_red),
            "mean_reduction_pct": round(float(np.mean(m_red)) * 100, 2) if m_red else None,
            "median_reduction_pct": round(float(np.median(m_red)) * 100, 2) if m_red else None,
            "oos_mean_reduction_pct": round(float(np.mean(m_oos_red)) * 100, 2) if m_oos_red else None,
        }
        print(f"    [{datetime.now():%H:%M:%S}] {m} done ({len(m_red)}/{len(buckets)})",
              file=sys.stderr, flush=True)

    # ---- 指数层面参照：同算法跑全部指数（论断的实战语境是指数择时）----
    idx_rows = con = None
    con = sqlite3.connect(DB)
    idx_rows = con.execute(
        "SELECT i.market, i.id, i.ticker, i.name, d.date, d.close "
        "FROM daily_data d JOIN indices i ON d.index_id = i.id "
        "WHERE i.category = 'index' AND d.close IS NOT NULL AND d.close > 0 "
        "ORDER BY d.date").fetchall()
    con.close()
    idx_buckets = {}
    for m, iid, tk, nm, dt, c in idx_rows:
        if tk == "^VIX":          # 波动率指数不是可持有资产
            continue
        idx_buckets.setdefault((m, tk, nm), []).append((dt, c))
    index_results = {}
    for (m, tk, nm), series in idx_buckets.items():
        n = len(series)
        if n < MIN_ROWS:
            continue
        closes = np.asarray([s[1] for s in series], dtype=np.float64)
        ma200 = np.full(n, np.nan)
        if n >= 200:
            ma200[199:] = sliding_window_view(closes, 200).mean(axis=1)
        r = np.full(n, np.nan)
        r[1:] = closes[1:] / closes[:-1] - 1.0
        hold = np.zeros(n, dtype=bool)
        hold[1:] = closes[:-1] >= ma200[:-1]
        pos = hold.astype(np.int8)
        switches = np.zeros(n, dtype=np.float64)
        switches[1:] = (pos[1:] != pos[:-1]).astype(np.float64)
        ra = np.where(hold, r, 0.0) - switches * COST_BPS / 10000.0
        rb = r.copy()
        va = np.cumprod(1.0 + np.nan_to_num(ra))
        vb = np.cumprod(1.0 + np.nan_to_num(rb))
        da, db = mdd_of(va[199:]), mdd_of(vb[199:])
        if not (np.isfinite(da) and np.isfinite(db)) or db <= 0:
            continue
        oos_start = int(np.floor((1.0 - oos_frac) * n))
        da_o = mdd_of(va[oos_start:]) if oos_start > 199 else np.nan
        db_o = mdd_of(vb[oos_start:]) if oos_start > 199 else np.nan
        index_results[f"{m}:{tk}"] = {
            "name": nm, "n_days": n,
            "mdd_filter_pct": round(da * 100, 2), "mdd_hold_pct": round(db * 100, 2),
            "reduction_pct": round((1.0 - da / db) * 100, 2),
            "oos_reduction_pct": round((1.0 - da_o / db_o) * 100, 2)
                                 if np.isfinite(da_o) and np.isfinite(db_o) and db_o > 0 else None,
            "switches": int(switches.sum()),
        }

    def red_boot(vals):
        if len(vals) < 2:
            return None
        arr = np.asarray(vals, dtype=np.float64)
        boots = np.empty(BOOT_ITERS)
        for k in range(BOOT_ITERS):
            idx = rng.integers(0, len(arr), size=len(arr))
            boots[k] = np.mean(arr[idx])
        return {"mean_pct": round(float(np.mean(arr)) * 100, 2),
                "ci95_low_pct": round(float(np.percentile(boots, 2.5)) * 100, 2),
                "ci95_high_pct": round(float(np.percentile(boots, 97.5)) * 100, 2)}

    boot = red_boot(reductions)
    oos_boot = red_boot(oos_reductions)
    mean_red = round(float(np.mean(reductions)) * 100, 2) if reductions else None
    median_red = round(float(np.median(reductions)) * 100, 2) if reductions else None
    threshold = 50.0
    verdict = {
        "threshold_pct": threshold,
        "mean_reduction_pct": mean_red, "median_reduction_pct": median_red,
        "n_stocks": len(reductions),
        "stock_ew_boot": boot,
        "above_threshold_pooled": bool(mean_red is not None and mean_red > threshold),
        "ci_low_above_threshold": bool(boot and boot["ci95_low_pct"] > threshold),
        "oos_mean_reduction_pct": round(float(np.mean(oos_reductions)) * 100, 2)
                                  if oos_reductions else None,
        "oos_n_stocks": len(oos_reductions), "oos_stock_ew_boot": oos_boot,
        "oos_above_threshold_pooled": bool(oos_reductions
                                           and float(np.mean(oos_reductions)) * 100 > threshold),
    }
    verdict["supported"] = verdict["above_threshold_pooled"]

    lights = [
        {"item": "判据对齐（论断=回撤降幅>50%）", "status": "✅",
         "note": "主判据就是论断声称的回撤降幅本身（1−MDD_A/MDD_B），不用收益替代（铁律一）"},
        {"item": "价格口径（前复权 close）", "status": "✅",
         "note": "daily_data.close 为前复权（000-data-biases.md A.1）"},
        {"item": "时机（无前视）", "status": "✅",
         "note": "信号用 T-1 收盘（close 与 MA200 均为 T-1），收益落在 T 日——无同bar双用"},
        {"item": "交易成本", "status": "✅",
         "note": "策略A每次仓位切换扣 25bps；策略B一次性建仓不扣（对降幅判据偏保守）"},
        {"item": "显著性/区间（Bootstrap 2000 次）", "status": "✅",
         "note": f"股票级 bootstrap（每股坍缩为降幅，种子 {RNG_SEED} 可复现）"},
        {"item": "重叠样本处理", "status": "⚠️",
         "note": "全程 NAV MDD 天然强自相关 → 每股坍缩后股票级 bootstrap；跨股同日历相关未建模"},
        {"item": "样本外验证（后 20%）", "status": "✅",
         "note": "每标的自有交易日后 20% 子区间两策略 MDD 重算降幅"},
        {"item": "幸存者偏差（含退市股）", "status": "⚠️",
         "note": "本地库仅当前成分快照；对两策略同向影响，降幅判据受污染方向不确定，如实记录"},
        {"item": "现金收益假设", "status": "⚠️",
         "note": "空仓期现金计 0%（不计利息，保守）；计息会进一步抬高策略A降幅"},
    ]

    payload = {
        "claim": {k: claim[k] for k in ("id", "title", "statement", "h0", "price_basis",
                                        "cost_bps", "signal_def", "verdict_metric",
                                        "data_scope") if k in claim},
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "engine": "annual-line-filter-mdd",
        "config": {"bootstrap_iters": BOOT_ITERS, "rng_seed": RNG_SEED, "oos_frac": OOS_FRAC,
                   "ma_window": 200, "cost_bps_per_switch": COST_BPS,
                   "cash_yield": 0.0, "markets": list(per_market.keys())},
        "pools": {"stocks_total": stocks_total},
        "survivorship_note": "本地库 indices 仅当前成分股快照；幸存者偏差对两策略同向影响，如实记录",
        "protocol_lights": lights,
        "per_market": per_market,
        "index_reference": index_results,
        "index_reference_note": "指数层面参照（同算法同成本）：论断实战语境为指数择时；主判据仍为个股层面股票级统计",
        "aggregate": {"n_stocks": len(reductions), "mean_reduction_pct": mean_red,
                      "median_reduction_pct": median_red},
        "aggregate_oos": {"n_stocks": len(oos_reductions),
                          "mean_reduction_pct": verdict["oos_mean_reduction_pct"]},
        "verdict": verdict,
    }
    return _emit_results(claim, out_dir, payload,
                         lambda: print(f"  回撤降幅(pooled EW)={mean_red}% 中位={median_red}% "
                                       f"股级CI={boot} 判据>50% → supported={verdict['supported']}",
                                       f"  OOS降幅={verdict['oos_mean_reduction_pct']}% "
                                       f"(股票 {len(oos_reductions)})"))


# --------------------------------------------------------------------------
# 8c-5) 论断 #21 引擎：上证2638仓位法则（engine: rule-2638-position-cap）
# --------------------------------------------------------------------------
def run_rule2638(claim, out_dir, oos_frac=OOS_FRAC, seed=RNG_SEED):
    """实现 000-claims-def.md id=21 契约（engine: rule-2638-position-cap）：
      规则：T 日仓位 = 30% 若 close_{T-1} < 2638，否则 100%；日收益=仓位×r_T，
            调仓日对交易部分扣 25bps。对照 = 始终满仓。
      每 126 日窗口（每 21 日滚动一窗）内从窗口起点累计 NAV 取 MDD；
      每窗降幅 = 1 − MDD_rule/MDD_hold；主判据 = 窗口降幅均值 >30%。
      显著性 = 窗口序列圆形块 bootstrap（块长 22，2000 次，保窗口重叠结构）。
      样本外 = 后 20% 交易日的窗口单独报告。
    """
    rng = np.random.default_rng(seed)
    THRESH_PRICE = 2638.0
    LOW_POS = 0.30
    WIN = 126
    STEP = 21
    BLOCK = 22
    COST_BPS = 25

    con = sqlite3.connect(DB)
    row = con.execute("SELECT id, ticker, name FROM indices WHERE ticker='000001.SS'").fetchone()
    rows = con.execute(
        "SELECT date, close FROM daily_data WHERE index_id=? AND close IS NOT NULL AND close > 0 "
        "ORDER BY date", (row[0],)).fetchall()
    con.close()
    n = len(rows)
    if n < 200 + WIN:
        print(f"错误：上证数据不足（{n} 行）")
        return 1
    dates = [r[0] for r in rows]
    closes = np.asarray([r[1] for r in rows], dtype=np.float64)
    r = np.full(n, np.nan)
    r[1:] = closes[1:] / closes[:-1] - 1.0
    low = np.zeros(n, dtype=bool)
    low[1:] = closes[:-1] < THRESH_PRICE          # 仓位由 T-1 收盘决定，无前视
    pos = np.where(low, LOW_POS, 1.0)
    trade = np.abs(np.diff(pos, prepend=pos[0]))
    rr = pos * r - trade * COST_BPS / 10000.0
    rb = r.copy()
    start = 200
    va = np.cumprod(1.0 + np.nan_to_num(rr))
    vb = np.cumprod(1.0 + np.nan_to_num(rb))

    def window_mdds(nav):
        out = []
        for w0 in range(start, n - WIN, STEP):
            seg = nav[w0:w0 + WIN + 1] / nav[w0]
            peak = np.maximum.accumulate(seg)
            out.append(float(np.max(1.0 - seg / peak)))
        return np.asarray(out)

    da, db = window_mdds(va), window_mdds(vb)
    ok = (db > 1e-9) & np.isfinite(da) & np.isfinite(db)
    da, db = da[ok], db[ok]
    reds = 1.0 - da / db
    reds_pct = reds * 100.0

    # 圆形块 bootstrap（窗口强重叠 → 块保结构）
    boots = np.empty(BOOT_ITERS)
    nw = len(reds_pct)
    for k in range(BOOT_ITERS):
        idx = np.concatenate([ (np.arange(rng.integers(0, nw), rng.integers(0, nw) + BLOCK) % nw)
                               for _ in range(max(1, nw // BLOCK)) ])[:nw]
        boots[k] = reds_pct[idx].mean()
    mean_red = round(float(reds_pct.mean()), 2)
    ci = {"mean_pct": mean_red,
          "ci95_low_pct": round(float(np.percentile(boots, 2.5)), 2),
          "ci95_high_pct": round(float(np.percentile(boots, 97.5)), 2)}
    threshold = 30.0

    # 样本外：后 20% 交易日内的窗口
    oos_start = int(np.floor((1.0 - oos_frac) * n))
    oos_mask = np.asarray([(w0 >= oos_start) for w0 in range(start, n - WIN, STEP)])[ok]
    oos_mean = round(float(reds_pct[oos_mask].mean()), 2) if oos_mask.any() else None
    n_below = int(low[start:].sum())
    below_dates = [dates[start + i] for i in range(n - start) if low[start + i]]

    # 全程 NAV MDD（参考列）
    def mdd(nav):
        peak = np.maximum.accumulate(nav)
        return float(np.max(1.0 - nav / peak))
    full_red = round((1.0 - mdd(va[start:]) / mdd(vb[start:])) * 100, 2)

    verdict = {
        "threshold_pct": threshold,
        "mean_window_reduction_pct": mean_red,
        "n_windows": int(nw),
        "window_boot_ci": ci,
        "above_threshold_pooled": bool(mean_red > threshold),
        "ci_low_above_threshold": bool(ci["ci95_low_pct"] > threshold),
        "full_nav_mdd_reduction_pct": full_red,
        "days_below_2638": n_below,
        "first_below": below_dates[0] if below_dates else None,
        "last_below": below_dates[-1] if below_dates else None,
        "oos_mean_window_reduction_pct": oos_mean,
        "oos_n_windows": int(oos_mask.sum()) if oos_mask.any() else 0,
        "oos_above_threshold": bool(oos_mean is not None and oos_mean > threshold),
    }
    verdict["supported"] = verdict["above_threshold_pooled"]

    lights = [
        {"item": "判据对齐（6个月窗口回撤降幅>30%）", "status": "✅",
         "note": "主判据 = 论断声称的窗口回撤降幅本身，不换量（铁律一）"},
        {"item": "价格口径（前复权 close）", "status": "✅", "note": "000-data-biases.md A.1"},
        {"item": "时机（无前视）", "status": "✅",
         "note": "仓位由 T-1 收盘 vs 2638 决定，作用于 T 日收益；2638 为规则原文固定价位，无参数拟合"},
        {"item": "交易成本", "status": "✅",
         "note": "只对仓位变动部分扣 25bps；现金不计息（保守）"},
        {"item": "显著性/区间（Bootstrap 2000 次）", "status": "✅",
         "note": f"窗口序列圆形块 bootstrap 块长 {BLOCK}（保 21 日步长造成的强重叠），种子 {RNG_SEED}"},
        {"item": "重叠样本处理", "status": "⚠️",
         "note": "126 日窗 + 21 日步长 → 相邻窗共享 ~83% 数据；块 bootstrap 缓解，非完全消除；单指数无股票级坍缩可用"},
        {"item": "样本外验证（后 20%）", "status": "✅", "note": "后 20% 交易日的窗口单独报告"},
        {"item": "幸存者偏差", "status": "✅", "note": "指数层面，不适用"},
        {"item": "固定价位规则拟合风险", "status": "⚠️",
         "note": "2638 取自 2016 熔断低点（规则原文非事后拟合）；但规则在 2016 后才可能被提出，存在轻微事后选择风险，如实记录"},
        {"item": "可复现", "status": "✅", "note": "种子固定重跑同数"},
    ]

    payload = {
        "claim": {k: claim[k] for k in ("id", "title", "statement", "h0", "price_basis",
                                        "cost_bps", "signal_def", "verdict_metric",
                                        "data_scope") if k in claim},
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "engine": "rule-2638-position-cap",
        "config": {"bootstrap_iters": BOOT_ITERS, "rng_seed": RNG_SEED, "oos_frac": OOS_FRAC,
                   "threshold_price": THRESH_PRICE, "low_position": LOW_POS,
                   "window_days": WIN, "step_days": STEP, "block": BLOCK,
                   "cost_bps_on_traded": COST_BPS},
        "index": {"ticker": "000001.SS", "name": row[2], "n_days": n,
                  "date_span": [dates[0], dates[-1]]},
        "survivorship_note": "指数层面不适用幸存者偏差；2638 固定价位存在轻微事后选择风险（规则原文引用）",
        "protocol_lights": lights,
        "aggregate": {"n_windows": int(nw), "mean_window_reduction_pct": mean_red,
                      "median_window_reduction_pct": round(float(np.median(reds_pct)), 2),
                      "full_nav_mdd_reduction_pct": full_red},
        "aggregate_oos": {"n_windows": int(oos_mask.sum()) if oos_mask.any() else 0,
                          "mean_window_reduction_pct": oos_mean},
        "verdict": verdict,
    }
    return _emit_results(claim, out_dir, payload,
                         lambda: print(f"  窗口回撤降幅均值={mean_red}% CI={ci} "
                                       f"判据>30% → supported={verdict['supported']}",
                                       f"  全程NAV MDD降幅={full_red}% OOS={oos_mean}% "
                                       f"破2638天数={n_below}"))


# --------------------------------------------------------------------------
# 8c-6) 论断 #22 引擎：年线下降仓30%（engine: annual-line-reduce-mdd）
# --------------------------------------------------------------------------
def run_annual_line_reduce(claim, out_dir, oos_frac=OOS_FRAC, seed=RNG_SEED):
    '''"""实现 000-claims-def.md id=22 契约（engine: annual-line-reduce-mdd）：
      全部库内指数（剔 VIX）：T 日仓位 = 30% 若 close_{T-1} < MA200_{T-1}，否则 100%；
      调仓差价扣 25bps；对照 = 满仓。每 126 日窗口（21 日步长）MDD 降幅，
      全指数窗口混合同池；定性论断 → 主判据 = 池均值 >0 且 CI 下限 >0。
      显著性 = 圆形块 bootstrap（块长 22）；样本外 = 每指数后 20% 窗口。
    """'''
    rng = np.random.default_rng(seed)
    LOW_POS = 0.30
    WIN = 126
    STEP = 21
    BLOCK = 22
    COST_BPS = 25

    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT i.market, i.ticker, i.name, d.date, d.close "
        "FROM daily_data d JOIN indices i ON d.index_id = i.id "
        "WHERE i.category = 'index' AND d.close IS NOT NULL AND d.close > 0 "
        "ORDER BY d.date").fetchall()
    con.close()
    from numpy.lib.stride_tricks import sliding_window_view
    buckets = {}
    for m, tk, nm, dt, c in rows:
        if tk == "^VIX":
            continue
        buckets.setdefault((m, tk, nm), []).append((dt, c))

    all_reds, all_oos = [], []
    per_index = {}
    for (m, tk, nm), series in buckets.items():
        n = len(series)
        if n < 200 + WIN:
            continue
        closes = np.asarray([s[1] for s in series], dtype=np.float64)
        ma200 = np.full(n, np.nan)
        ma200[199:] = sliding_window_view(closes, 200).mean(axis=1)
        r = np.full(n, np.nan)
        r[1:] = closes[1:] / closes[:-1] - 1.0
        low = np.zeros(n, dtype=bool)
        low[1:] = closes[:-1] < ma200[:-1]           # 仓位由 T-1 收盘决定，无前视
        pos = np.where(low, LOW_POS, 1.0)
        trade = np.abs(np.diff(pos, prepend=pos[0]))
        ra = pos * r - trade * COST_BPS / 10000.0
        va = np.cumprod(1.0 + np.nan_to_num(ra))
        vb = np.cumprod(1.0 + np.nan_to_num(r))
        start = 199

        def win_mdds(nav):
            out = []
            for w0 in range(start, n - WIN, STEP):
                seg = nav[w0:w0 + WIN + 1] / nav[w0]
                peak = np.maximum.accumulate(seg)
                out.append(float(np.max(1.0 - seg / peak)))
            return np.asarray(out)

        da, db = win_mdds(va), win_mdds(vb)
        ok = (db > 1e-9) & np.isfinite(da) & np.isfinite(db)
        da, db = da[ok], db[ok]
        reds = (1.0 - da / db) * 100.0
        all_reds.append(reds)
        oos_start = int(np.floor((1.0 - oos_frac) * n))
        oos_mask = np.asarray([w0 >= oos_start for w0 in range(start, n - WIN, STEP)])[ok]
        all_oos.append(reds[oos_mask])

        def mdd(nav):
            peak = np.maximum.accumulate(nav)
            return float(np.max(1.0 - nav / peak))
        per_index[f"{m}:{tk}"] = {
            "name": nm, "n_days": n,
            "full_mdd_reduce_pct": round((1.0 - mdd(va[start:]) / mdd(vb[start:])) * 100, 2),
            "window_mean_reduction_pct": round(float(reds.mean()), 2) if len(reds) else None,
            "window_median_reduction_pct": round(float(np.median(reds)), 2) if len(reds) else None,
            "oos_window_mean_reduction_pct": round(float(reds[oos_mask].mean()), 2)
                                             if oos_mask.any() else None,
            "pct_days_below_ma200": round(float(low[start:].mean()) * 100, 1),
        }
        print(f"    [{datetime.now():%H:%M:%S}] {m}:{tk} done", file=sys.stderr, flush=True)

    pool = np.concatenate(all_reds)
    oos_pool = (np.concatenate([a for a in all_oos if len(a)])
                if any(len(a) for a in all_oos) else np.asarray([]))
    boots = np.empty(BOOT_ITERS)
    nw = len(pool)
    for k in range(BOOT_ITERS):
        idx = np.concatenate([(np.arange(rng.integers(0, nw), rng.integers(0, nw) + BLOCK) % nw)
                              for _ in range(max(1, nw // BLOCK))])[:nw]
        boots[k] = pool[idx].mean()
    mean_red = round(float(pool.mean()), 2)
    ci = {"mean_pct": mean_red,
          "ci95_low_pct": round(float(np.percentile(boots, 2.5)), 2),
          "ci95_high_pct": round(float(np.percentile(boots, 97.5)), 2)}
    oos_mean = round(float(oos_pool.mean()), 2) if len(oos_pool) else None

    verdict = {
        "claim_type": "qualitative（方向性：降幅>0 即支持）",
        "mean_window_reduction_pct": mean_red,
        "median_window_reduction_pct": round(float(np.median(pool)), 2),
        "n_windows": int(nw),
        "n_indices": len(per_index),
        "window_boot_ci": ci,
        "above_zero_pooled": bool(mean_red > 0),
        "ci_low_above_zero": bool(ci["ci95_low_pct"] > 0),
        "oos_mean_window_reduction_pct": oos_mean,
        "oos_n_windows": int(len(oos_pool)),
        "oos_above_zero": bool(oos_mean is not None and oos_mean > 0),
    }
    verdict["supported"] = verdict["above_zero_pooled"] and verdict["ci_low_above_zero"]

    lights = [
        {"item": "判据对齐（定性方向论断）", "status": "✅",
         "note": "论断只声称回撤更低，主判据 = 降幅>0 且 CI 下限>0，不硬安阈值（铁律一；#2 教训）"},
        {"item": "价格口径（前复权 close）", "status": "✅", "note": "000-data-biases.md A.1"},
        {"item": "时机（无前视）", "status": "✅",
         "note": "仓位由 T-1 收盘（含 MA200_{T-1}）决定，作用 T 日收益"},
        {"item": "交易成本", "status": "✅",
         "note": "只对仓位变动部分扣 25bps；现金不计息（保守）"},
        {"item": "显著性/区间（Bootstrap 2000 次）", "status": "✅",
         "note": f"窗口池圆形块 bootstrap 块长 {BLOCK}，种子 {RNG_SEED}"},
        {"item": "重叠样本处理", "status": "⚠️",
         "note": "相邻窗共享约 83% 数据且跨指数同日历相关；块 bootstrap 缓解，非完全消除"},
        {"item": "样本外验证（后 20%）", "status": "✅", "note": "每指数后 20% 窗口混池报告"},
        {"item": "幸存者偏差", "status": "✅", "note": "指数层面不适用"},
        {"item": "口径对照旧结论", "status": "⚠️",
         "note": "旧 ✅约69% 为 US/CN/HK 三指数旧窗口法；本次全指数混池，数字不可直接比，方向结论可比"},
        {"item": "可复现", "status": "✅", "note": "种子固定重跑同数"},
    ]

    payload = {
        "claim": {k: claim[k] for k in ("id", "title", "statement", "h0", "price_basis",
                                        "cost_bps", "signal_def", "verdict_metric",
                                        "data_scope") if k in claim},
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "engine": "annual-line-reduce-mdd",
        "config": {"bootstrap_iters": BOOT_ITERS, "rng_seed": RNG_SEED, "oos_frac": OOS_FRAC,
                   "low_position": LOW_POS, "ma_window": 200, "window_days": WIN,
                   "step_days": STEP, "block": BLOCK, "cost_bps_on_traded": COST_BPS},
        "survivorship_note": "指数层面不适用幸存者偏差",
        "protocol_lights": lights,
        "per_index": per_index,
        "aggregate": {"n_windows": int(nw), "n_indices": len(per_index),
                      "mean_window_reduction_pct": mean_red,
                      "median_window_reduction_pct": verdict["median_window_reduction_pct"]},
        "aggregate_oos": {"n_windows": int(len(oos_pool)),
                          "mean_window_reduction_pct": oos_mean},
        "verdict": verdict,
    }
    return _emit_results(claim, out_dir, payload,
                         lambda: print(f"  窗口回撤降幅均值={mean_red}% 中位={verdict['median_window_reduction_pct']}% "
                                       f"CI={ci} 判据>0且CI下限>0 → supported={verdict['supported']}",
                                       f"  指数数={len(per_index)} 窗口数={nw} OOS={oos_mean}%"))


# --------------------------------------------------------------------------
# 8c-7) 论断 #23 引擎：钱仓滚存（engine: qiancang-rollover）
# --------------------------------------------------------------------------
def run_qiancang_rollover(claim, out_dir, oos_frac=OOS_FRAC, seed=RNG_SEED):
    '''"""实现 000-claims-def.md id=23 契约（engine: qiancang-rollover）：
      股票级 504 日窗口（步长 126）：滚存 = 浮盈>=30% 时卖出收回本金（留利润仓），
      终值差 = 滚存终值 − 买入持有终值；震荡域 = 窗口末 ±20% 持平（含未触发差值 0，保守）。
      主判据 = 震荡域均值 >0 且股票级 bootstrap CI 下限 >0（定性方向，铁律一）。
      触发卖出按当日收盘判定并当日收盘成交（与实盘可同步执行一致，红灯披露）。
    """'''
    rng = np.random.default_rng(seed)
    markets = claim["data_scope"].get("markets", [])
    category = claim["data_scope"].get("category", "stock")
    WIN, STEP, TRIG, FLAT, COST = 504, 126, 1.30, 0.20, 25

    con = sqlite3.connect(DB)
    qmarks = ",".join("?" * len(markets))
    rows = con.execute(
        "SELECT i.market, d.index_id, d.date, d.close "
        "FROM daily_data d JOIN indices i ON d.index_id = i.id "
        f"WHERE i.market IN ({qmarks}) AND i.category = ? AND d.close IS NOT NULL AND d.close > 0 "
        "ORDER BY d.date", (*markets, category)).fetchall()
    con.close()
    from numpy.lib.stride_tricks import sliding_window_view
    buckets = {}
    for m, iid, dt, c in rows:
        buckets.setdefault((m, iid), []).append(c)

    per_market = {}
    stock_stats = []   # (market, domain_mean_diff, n_domain)
    dom_all, trig_all, mdd_all, dom_oos_all = [], [], [], []
    for m in markets:
        m_items = [(k, v) for k, v in buckets.items() if k[0] == m]
        st = {"stocks_total": len(m_items), "stocks_processed": 0,
              "dom_windows": 0, "trig_windows": 0}
        m_dom, m_trig, m_mdd, m_oos = [], [], [], []
        for (mk, iid), closes_l in m_items:
            n = len(closes_l)
            if n < WIN + 60:
                continue
            closes = np.asarray(closes_l, dtype=np.float64)
            w0s = np.arange(0, n - WIN, STEP)
            sw = sliding_window_view(closes, WIN + 1)   # sw[i] = closes[i..i+WIN]
            seg = sw[w0s]                                # (W, WIN+1)
            base = seg[:, 0]
            final = seg[:, WIN]
            wmax = seg.max(axis=1)
            trig = wmax >= TRIG * base
            flat = np.abs(final / base - 1.0) <= FLAT
            dom = trig & flat
            oos_start = int(np.floor((1.0 - oos_frac) * n))
            oos_mask = w0s >= oos_start
            bh = final / base
            diff = np.zeros(len(w0s))
            mdd_red = np.full(len(w0s), np.nan)
            for wi in np.nonzero(trig)[0]:
                w0 = int(w0s[wi])
                path = seg[wi]
                hit = np.nonzero(path >= TRIG * base[wi])[0][0]   # 窗口内首个触发日
                vstar = path[hit] / base[wi]
                kept = 1.0 - 1.0 / vstar
                end_nav = 1.0 + kept * (final[wi] / base[wi]) - COST / 10000.0
                diff[wi] = end_nav - bh[wi]
                nav = np.where(np.arange(WIN + 1) >= hit,
                               1.0 + kept * path / base[wi], path / base[wi])
                nav[hit] -= COST / 10000.0
                pk = np.maximum.accumulate(nav)
                md_a = float(np.max(1.0 - nav / pk))
                pkb = np.maximum.accumulate(path / base[wi])
                md_b = float(np.max(1.0 - path / base[wi] / pkb))
                if md_b > 1e-9:
                    mdd_red[wi] = (1.0 - md_a / md_b) * 100.0
            st["stocks_processed"] += 1
            d_dom = diff[dom]
            if len(d_dom):
                stock_stats.append((m, float(d_dom.mean()), len(d_dom)))
                dom_all.append(d_dom)
                m_dom.append(d_dom)
                if (dom & oos_mask).any():
                    m_oos.append(diff[dom & oos_mask])
                st["dom_windows"] += len(d_dom)
            d_tr = diff[trig]
            if len(d_tr):
                trig_all.append(d_tr)
                m_trig.append(d_tr)
                st["trig_windows"] += len(d_tr)
            mr = mdd_red[trig & np.isfinite(mdd_red)]
            if len(mr):
                m_mdd.append(mr)
                mdd_all.append(mr)
        per_market[m] = {**st,
                         "domain_mean_diff_pct": round(float(np.mean(np.concatenate(m_dom))) * 100, 2) if m_dom else None,
                         "oos_domain_mean_diff_pct": round(float(np.mean(np.concatenate(m_oos))) * 100, 2) if m_oos else None}
        dom_oos_all.extend(m_oos)
        print(f"    [{datetime.now():%H:%M:%S}] {m} done "
              f"({st['stocks_processed']}/{st['stocks_total']})", file=sys.stderr, flush=True)
        m_dom.clear(); m_trig.clear(); m_mdd.clear(); m_oos.clear()

    pool_dom = np.concatenate(dom_all) if dom_all else np.asarray([])
    pool_trig = np.concatenate(trig_all) if trig_all else np.asarray([])
    pool_mdd = np.concatenate(mdd_all) if mdd_all else np.asarray([])
    pool_oos = np.concatenate(dom_oos_all) if dom_oos_all else np.asarray([])
    dom_mean = round(float(pool_dom.mean()) * 100, 2) if len(pool_dom) else None
    # 股票级 bootstrap：每股坍缩为震荡域平均差
    by_stock = {}
    for mk, mv, cnt in stock_stats:
        by_stock.setdefault(mk, []).append(mv)
    rates = np.asarray([v for lst in by_stock.values() for v in lst], dtype=np.float64)
    boots = np.empty(BOOT_ITERS)
    for k in range(BOOT_ITERS):
        idx = rng.integers(0, len(rates), size=len(rates))
        boots[k] = rates[idx].mean()
    ci = {"mean_pct": round(float(rates.mean()) * 100, 2),
          "ci95_low_pct": round(float(np.percentile(boots, 2.5)) * 100, 2),
          "ci95_high_pct": round(float(np.percentile(boots, 97.5)) * 100, 2)}
    pos_stocks = int(np.sum(rates > 0))
    verdict = {
        "claim_type": "qualitative（方向性：震荡域终值差>0 即支持）",
        "domain_mean_diff_pct": dom_mean,
        "domain_median_diff_pct": round(float(np.median(pool_dom)) * 100, 2) if len(pool_dom) else None,
        "domain_n_windows": int(len(pool_dom)),
        "stock_ew_boot": ci,
        "stocks_positive_pct": round(100.0 * pos_stocks / len(rates), 1) if len(rates) else None,
        "triggered_mean_diff_pct": round(float(pool_trig.mean()) * 100, 2) if len(pool_trig) else None,
        "triggered_n_windows": int(len(pool_trig)),
        "mdd_reduction_mean_pct": round(float(pool_mdd.mean()), 2) if len(pool_mdd) else None,
        "ci_low_above_zero": bool(ci["ci95_low_pct"] > 0),
        "oos_domain_mean_diff_pct": round(float(pool_oos.mean()) * 100, 2) if len(pool_oos) else None,
        "oos_n_windows": int(len(pool_oos)),
    }
    verdict["supported"] = bool(dom_mean is not None and dom_mean > 0 and verdict["ci_low_above_zero"])

    lights = [
        {"item": "判据对齐（定性方向论断）", "status": "✅",
         "note": "论断只说震荡市终值更优，主判据 = 震荡域终值差>0 且股级 CI 下限>0（铁律一）"},
        {"item": "价格口径（前复权 close）", "status": "✅", "note": "000-data-biases.md A.1"},
        {"item": "时机（无前视）", "status": "⚠️",
         "note": "触发日 T* 由当日收盘判定并按当日收盘成交——实盘收盘价确认后按收盘价卖出需收盘竞价/尾盘单，口径已披露；无未来信息"},
        {"item": "交易成本", "status": "✅", "note": "触发卖出对收回本金 1.0 扣 25bps；现金不计息（保守）"},
        {"item": "显著性/区间（Bootstrap 2000 次）", "status": "✅",
         "note": f"股票级 bootstrap（每股坍缩为震荡域平均差，种子 {RNG_SEED}）"},
        {"item": "重叠样本处理", "status": "⚠️",
         "note": "相邻窗共享 ~75% 数据；股级坍缩+窗口步长 126 缓解，跨股同日历相关未建模"},
        {"item": "样本外验证（后 20%）", "status": "✅", "note": "每股后 20% 窗口震荡域单独报告"},
        {"item": "幸存者偏差", "status": "⚠️",
         "note": "仅当前成分快照；滚存与 BH 同框架对比，对差值影响中性偏保守（崩退市股缺失使 BH 更差被剔除）"},
        {"item": "条件域披露（震荡市定义）", "status": "⚠️",
         "note": "震荡域=窗口末±20% 持平，为 outcome-based 条件域，无法事前定义；含未触发差值 0 窗口（保守）；无条件触发域对照并列"},
        {"item": "可复现", "status": "✅", "note": "种子固定重跑同数"},
    ]

    payload = {
        "claim": {k: claim[k] for k in ("id", "title", "statement", "h0", "price_basis",
                                        "cost_bps", "signal_def", "verdict_metric",
                                        "data_scope") if k in claim},
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "engine": "qiancang-rollover",
        "config": {"bootstrap_iters": BOOT_ITERS, "rng_seed": RNG_SEED, "oos_frac": OOS_FRAC,
                   "window_days": WIN, "step_days": STEP, "trigger": TRIG, "flat_band": FLAT,
                   "cost_bps_on_principal": COST, "cash_yield": 0.0},
        "survivorship_note": "仅当前成分快照；差值口径下影响中性偏保守",
        "protocol_lights": lights,
        "per_market": per_market,
        "aggregate": {"domain_n_windows": int(len(pool_dom)),
                      "domain_mean_diff_pct": dom_mean,
                      "triggered_n_windows": int(len(pool_trig)),
                      "mdd_reduction_mean_pct": verdict["mdd_reduction_mean_pct"]},
        "verdict": verdict,
    }
    def _sum():
        print(f"  震荡域终值差均值={dom_mean}% 股级CI={ci} "
              f"正差股票={verdict['stocks_positive_pct']}% MDD降幅={verdict['mdd_reduction_mean_pct']}% "
              f"→ supported={verdict['supported']}")
    return _emit_results(claim, out_dir, payload, _sum)
# --------------------------------------------------------------------------
# 8c-8) 论断 #27 引擎：时间止损（engine: time-stop-6m）
# --------------------------------------------------------------------------
def run_time_stop(claim, out_dir, oos_frac=OOS_FRAC, seed=RNG_SEED):
    '''"""实现 000-claims-def.md id=27 契约（engine: time-stop-6m）：
      每股 252 日窗口（步长 126）：前半 126 日收益 r1<=0（论文未兑现）时，
      比较退出（净 0）与继续持有后半 126 日收益 r2。
      主判据 = 域内 r2 均值 <0 且股级 bootstrap CI 上限 <0（铁律一）。
    """'''
    rng = np.random.default_rng(seed)
    markets = claim["data_scope"].get("markets", [])
    category = claim["data_scope"].get("category", "stock")
    HALF, COST = 126, 25

    con = sqlite3.connect(DB)
    qmarks = ",".join("?" * len(markets))
    rows = con.execute(
        "SELECT i.market, d.index_id, d.date, d.close "
        "FROM daily_data d JOIN indices i ON d.index_id = i.id "
        f"WHERE i.market IN ({qmarks}) AND i.category = ? AND d.close IS NOT NULL AND d.close > 0 "
        "ORDER BY d.date", (*markets, category)).fetchall()
    con.close()
    buckets = {}
    for m, iid, dt, c in rows:
        buckets.setdefault((m, iid), []).append((dt, c))

    per_market = {}
    stock_stats = []
    pool_r2, pool_mdd, pool_oos = [], [], []
    for m in markets:
        m_items = [(k, v) for k, v in buckets.items() if k[0] == m]
        st = {"stocks_total": len(m_items), "stocks_processed": 0, "domain_windows": 0}
        m_r2, m_oos = [], []
        for (mk, iid), series in m_items:
            n = len(series)
            if n < 2 * HALF + 10:
                continue
            closes = np.asarray([x[1] for x in series], dtype=np.float64)
            w0s = np.arange(0, n - 2 * HALF, HALF)
            base = closes[w0s]
            mid = closes[w0s + HALF]
            end = closes[w0s + 2 * HALF]
            r1 = mid / base - 1.0
            r2 = end / mid - 1.0
            dom = r1 <= 0
            oos_start = int(np.floor((1.0 - oos_frac) * n))
            oos_mask = w0s >= oos_start
            d_r2 = r2[dom]
            if len(d_r2):
                stock_stats.append((m, float(d_r2.mean())))
                pool_r2.append(d_r2)
                m_r2.append(d_r2)
                if (dom & oos_mask).any():
                    m_oos.append(r2[dom & oos_mask])
                    pool_oos.append(r2[dom & oos_mask])
                st["domain_windows"] += len(d_r2)
                # 域内继续持有半段 MDD（信息参考）
                for wi in np.nonzero(dom)[0][:5]:   # 每股抽 5 窗控制算量，MDD 为次要参考
                    seg = closes[w0s[wi] + HALF:w0s[wi] + 2 * HALF + 1] / mid[wi]
                    pk = np.maximum.accumulate(seg)
                    pool_mdd.append(float(np.max(1.0 - seg / pk)))
            st["stocks_processed"] += 1
        per_market[m] = {**st,
                         "r2_mean_pct": round(float(np.mean(np.concatenate(m_r2))) * 100, 2) if m_r2 else None,
                         "r2_winrate_lt0_pct": round(float(np.mean(np.concatenate(m_r2) < 0)) * 100, 2) if m_r2 else None,
                         "oos_r2_mean_pct": round(float(np.mean(np.concatenate(m_oos))) * 100, 2) if m_oos else None}
        print(f"    [{datetime.now():%H:%M:%S}] {m} done "
              f"({st['stocks_processed']}/{st['stocks_total']})", file=sys.stderr, flush=True)
        m_r2.clear(); m_oos.clear()

    pool = np.concatenate(pool_r2) if pool_r2 else np.asarray([])
    by_stock = {}
    for mk, mv in stock_stats:
        by_stock.setdefault(mk, []).append(mv)
    rates = np.asarray([v for lst in by_stock.values() for v in lst], dtype=np.float64)
    boots = np.empty(BOOT_ITERS)
    for k in range(BOOT_ITERS):
        idx = rng.integers(0, len(rates), size=len(rates))
        boots[k] = rates[idx].mean()
    mean_r2 = round(float(pool.mean()) * 100, 2) if len(pool) else None
    ci = {"mean_pct": round(float(rates.mean()) * 100, 2),
          "ci95_low_pct": round(float(np.percentile(boots, 2.5)) * 100, 2),
          "ci95_high_pct": round(float(np.percentile(boots, 97.5)) * 100, 2)}
    verdict = {
        "claim_type": "qualitative（方向性：继续持有后半段均值为负 → 时间止损胜）",
        "domain_r2_mean_pct": mean_r2,
        "domain_r2_median_pct": round(float(np.median(pool)) * 100, 2) if len(pool) else None,
        "domain_n_windows": int(len(pool)),
        "stock_ew_boot": ci,
        "r2_negative_share_pct": round(float(np.mean(pool < 0)) * 100, 2) if len(pool) else None,
        "continuation_mdd_mean_pct": round(float(np.mean(pool_mdd)) * 100, 2) if pool_mdd else None,
        "oos_r2_mean_pct": round(float(np.concatenate(pool_oos).mean()) * 100, 2) if pool_oos else None,
        "oos_n_windows": int(sum(len(x) for x in pool_oos)),
        "mean_below_zero": bool(mean_r2 is not None and mean_r2 < 0),
        "ci_high_below_zero": bool(ci["ci95_high_pct"] < 0),
    }
    verdict["supported"] = verdict["mean_below_zero"] and verdict["ci_high_below_zero"]

    lights = [
        {"item": "判据对齐（定性方向论断）", "status": "✅",
         "note": "论断=机会成本<下行风险 → 主判据=继续持有后半段 r2 均值<0 且 CI 上限<0（铁律一）"},
        {"item": "价格口径（前复权 close）", "status": "✅", "note": "000-data-biases.md A.1"},
        {"item": "时机（无前视）", "status": "✅", "note": "r1 前半段/r2 后半段不重叠；退出在第 126 日收盘"},
        {"item": "交易成本", "status": "✅", "note": "退出 25bps 作为机会成本基准单列（不改变主判据方向）"},
        {"item": "显著性/区间（Bootstrap 2000 次）", "status": "✅",
         "note": f"股票级 bootstrap（每股坍缩为域内平均 r2，种子 {RNG_SEED}）"},
        {"item": "重叠样本处理", "status": "⚠️",
         "note": "相邻窗不重叠（步长=126）但跨股同日历相关；股级坍缩缓解"},
        {"item": "样本外验证（后 20%）", "status": "✅", "note": "每股后 20% 窗口单独报告"},
        {"item": "幸存者偏差", "status": "⚠️",
         "note": "仅当前成分快照，崩退市股缺失使 r2 偏乐观；判据要求 r2<0，偏差方向对结论保守"},
        {"item": "条件域披露", "status": "⚠️",
         "note": "论断域 r1<=0 为路径条件域（论文未兑现的事后判定），与 #23 同理披露"},
        {"item": "可复现", "status": "✅", "note": "种子固定重跑同数"},
    ]

    payload = {
        "claim": {k: claim[k] for k in ("id", "title", "statement", "h0", "price_basis",
                                        "cost_bps", "signal_def", "verdict_metric",
                                        "data_scope") if k in claim},
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "engine": "time-stop-6m",
        "config": {"bootstrap_iters": BOOT_ITERS, "rng_seed": RNG_SEED, "oos_frac": OOS_FRAC,
                   "half_days": HALF, "domain": "r1<=0", "exit_cost_bps": COST},
        "survivorship_note": "仅当前成分快照；偏差方向使 r2 偏乐观，对'继续持有为负'判据保守",
        "protocol_lights": lights,
        "per_market": per_market,
        "aggregate": {"domain_n_windows": int(len(pool)), "r2_mean_pct": mean_r2},
        "verdict": verdict,
    }
    def _sum():
        print(f"  域内继续持有 r2 均值={mean_r2}% 股级CI={ci} 负占比={verdict['r2_negative_share_pct']}% "
              f"MDD={verdict['continuation_mdd_mean_pct']}% OOS={verdict['oos_r2_mean_pct']}% "
              f"→ supported={verdict['supported']}")
    return _emit_results(claim, out_dir, payload, _sum)
# --------------------------------------------------------------------------
# 8c-9) 论断 #24 引擎：滚存牛市必跑输（engine: rollover-bull-mark）
# --------------------------------------------------------------------------
def run_rollover_bull(claim, out_dir, oos_frac=OOS_FRAC, seed=RNG_SEED):
    '''"""实现 000-claims-def.md id=24 契约（engine: rollover-bull-mark）：
      与 #23 同构模拟，论断域换成牛市域（窗口末涨幅 > +30%）。
      主判据 = 域内终值差均值 <0 且股级 bootstrap CI 上限 <0；幅度报告作"大幅"证据。
    """'''
    rng = np.random.default_rng(seed)
    markets = claim["data_scope"].get("markets", [])
    category = claim["data_scope"].get("category", "stock")
    WIN, STEP, TRIG, COST = 504, 126, 1.30, 25

    con = sqlite3.connect(DB)
    qmarks = ",".join("?" * len(markets))
    rows = con.execute(
        "SELECT i.market, d.index_id, d.date, d.close "
        "FROM daily_data d JOIN indices i ON d.index_id = i.id "
        f"WHERE i.market IN ({qmarks}) AND i.category = ? AND d.close IS NOT NULL AND d.close > 0 "
        "ORDER BY d.date", (*markets, category)).fetchall()
    con.close()
    from numpy.lib.stride_tricks import sliding_window_view
    buckets = {}
    for m, iid, dt, c in rows:
        buckets.setdefault((m, iid), []).append(c)

    per_market = {}
    stock_stats = []
    pool_diff, pool_oos, gain_bins = [], [], {"30-60": [], "60-100": [], ">100": []}
    for m in markets:
        m_items = [(k, v) for k, v in buckets.items() if k[0] == m]
        st = {"stocks_total": len(m_items), "stocks_processed": 0, "bull_windows": 0}
        m_diff, m_oos = [], []
        for (mk, iid), closes_l in m_items:
            n = len(closes_l)
            if n < WIN + 60:
                continue
            closes = np.asarray(closes_l, dtype=np.float64)
            w0s = np.arange(0, n - WIN, STEP)
            sw = sliding_window_view(closes, WIN + 1)
            seg = sw[w0s]
            base, final = seg[:, 0], seg[:, WIN]
            bull = (final / base - 1.0) > 0.30
            oos_start = int(np.floor((1.0 - oos_frac) * n))
            oos_mask = w0s >= oos_start
            diff = np.full(len(w0s), np.nan)
            for wi in np.nonzero(bull)[0]:
                w0 = int(w0s[wi])
                path = seg[wi]
                hit = np.nonzero(path >= TRIG * base[wi])[0][0]
                vstar = path[hit] / base[wi]
                kept = 1.0 - 1.0 / vstar
                diff[wi] = (1.0 + kept * (final[wi] / base[wi]) - COST / 10000.0) - (final[wi] / base[wi])
                g = final[wi] / base[wi] - 1.0
                bkey = "30-60" if g <= 0.6 else ("60-100" if g <= 1.0 else ">100")
                gain_bins[bkey].append(diff[wi] * 100.0)
            d = diff[bull]
            if len(d):
                stock_stats.append((m, float(d.mean())))
                pool_diff.append(d)
                m_diff.append(d)
                if (bull & oos_mask).any():
                    m_oos.append(diff[bull & oos_mask])
                    pool_oos.append(diff[bull & oos_mask])
                st["bull_windows"] += len(d)
            st["stocks_processed"] += 1
        per_market[m] = {**st,
                         "diff_mean_pct": round(float(np.mean(np.concatenate(m_diff))) * 100, 2) if m_diff else None,
                         "diff_median_pct": round(float(np.median(np.concatenate(m_diff))) * 100, 2) if m_diff else None,
                         "oos_diff_mean_pct": round(float(np.mean(np.concatenate(m_oos))) * 100, 2) if m_oos else None}
        print(f"    [{datetime.now():%H:%M:%S}] {m} done "
              f"({st['stocks_processed']}/{st['stocks_total']})", file=sys.stderr, flush=True)
        m_diff.clear(); m_oos.clear()

    pool = np.concatenate(pool_diff) if pool_diff else np.asarray([])
    by_stock = {}
    for mk, mv in stock_stats:
        by_stock.setdefault(mk, []).append(mv)
    rates = np.asarray([v for lst in by_stock.values() for v in lst], dtype=np.float64)
    boots = np.empty(BOOT_ITERS)
    for k in range(BOOT_ITERS):
        idx = rng.integers(0, len(rates), size=len(rates))
        boots[k] = rates[idx].mean()
    mean_d = round(float(pool.mean()) * 100, 2) if len(pool) else None
    ci = {"mean_pct": round(float(rates.mean()) * 100, 2),
          "ci95_low_pct": round(float(np.percentile(boots, 2.5)) * 100, 2),
          "ci95_high_pct": round(float(np.percentile(boots, 97.5)) * 100, 2)}
    bins = {k: {"n": len(v), "mean_pct": round(float(np.mean(v)), 2) if v else None}
            for k, v in gain_bins.items()}
    verdict = {
        "claim_type": "qualitative+幅度（牛市域终值差<0；幅度报告）",
        "bull_diff_mean_pct": mean_d,
        "bull_diff_median_pct": round(float(np.median(pool)) * 100, 2) if len(pool) else None,
        "bull_n_windows": int(len(pool)),
        "stock_ew_boot": ci,
        "diff_negative_share_pct": round(float(np.mean(pool < 0)) * 100, 2) if len(pool) else None,
        "gain_bins": bins,
        "oos_diff_mean_pct": round(float(np.concatenate(pool_oos).mean()) * 100, 2) if pool_oos else None,
        "mean_below_zero": bool(mean_d is not None and mean_d < 0),
        "ci_high_below_zero": bool(ci["ci95_high_pct"] < 0),
    }
    verdict["supported"] = verdict["mean_below_zero"] and verdict["ci_high_below_zero"]

    lights = [
        {"item": "判据对齐（方向+幅度）", "status": "✅",
         "note": "主判据=牛市域终值差<0 且 CI 上限<0；'大幅'以均值/中位/涨幅分箱报告（铁律一）"},
        {"item": "价格口径（前复权 close）", "status": "✅", "note": "000-data-biases.md A.1"},
        {"item": "时机（无前视）", "status": "⚠️",
         "note": "同 #23：触发日收盘判定+当日收盘成交（实盘需尾盘单，已披露）"},
        {"item": "交易成本", "status": "✅", "note": "同 #23：收回本金 1.0 扣 25bps，现金不计息"},
        {"item": "显著性/区间（Bootstrap 2000 次）", "status": "✅",
         "note": f"股票级 bootstrap（每股坍缩为牛市域平均差，种子 {RNG_SEED}）"},
        {"item": "重叠样本处理", "status": "⚠️", "note": "相邻窗共享 ~75% 数据；股级坍缩缓解"},
        {"item": "样本外验证（后 20%）", "status": "✅", "note": "每股后 20% 牛市域窗口单独报告"},
        {"item": "幸存者偏差", "status": "⚠️", "note": "仅当前成分；差值口径中性；牛市域缺退市股影响有限"},
        {"item": "条件域披露", "status": "⚠️",
         "note": "牛市域=窗口末涨幅>30%，outcome-based；'必然'部分为结构性质（v*=1.3 时 diff 随涨幅单调变负），实证给幅度"},
        {"item": "可复现", "status": "✅", "note": "种子固定重跑同数"},
    ]

    payload = {
        "claim": {k: claim[k] for k in ("id", "title", "statement", "h0", "price_basis",
                                        "cost_bps", "signal_def", "verdict_metric",
                                        "data_scope") if k in claim},
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "engine": "rollover-bull-mark",
        "config": {"bootstrap_iters": BOOT_ITERS, "rng_seed": RNG_SEED, "oos_frac": OOS_FRAC,
                   "window_days": WIN, "step_days": STEP, "trigger": TRIG,
                   "bull_domain": "final/base-1 > 0.30", "cost_bps_on_principal": COST},
        "survivorship_note": "仅当前成分快照；差值口径中性",
        "protocol_lights": lights,
        "per_market": per_market,
        "aggregate": {"bull_n_windows": int(len(pool)), "diff_mean_pct": mean_d,
                      "gain_bins": bins},
        "verdict": verdict,
    }
    def _sum():
        print(f"  牛市域终值差均值={mean_d}% 中位={verdict['bull_diff_median_pct']}% 股级CI={ci} "
              f"负占比={verdict['diff_negative_share_pct']}% 窗数={len(pool)} "
              f"OOS={verdict['oos_diff_mean_pct']}% → supported={verdict['supported']}")
    return _emit_results(claim, out_dir, payload, _sum)
# --------------------------------------------------------------------------
# 8c-10) 论断 #35 引擎：分散化曲线（engine: diversification-curve）
# --------------------------------------------------------------------------
def run_diversification_curve(claim, out_dir, oos_frac=OOS_FRAC, seed=RNG_SEED):
    '''"""实现 000-claims-def.md id=35 契约（engine: diversification-curve）：
      每市场最近 750 日收益矩阵，N 只随机等权组合 200 次抽样，
      elim(N)=1-var_p/mean(var_i)；主判据 elim(12)>=75% 且 elim(30)-elim(15)<=5pp。
    """'''
    rng = np.random.default_rng(seed)
    markets = claim["data_scope"].get("markets", [])
    category = claim["data_scope"].get("category", "stock")
    TWIN, NDRAW = 750, 200
    NS = [1, 2, 3, 5, 8, 10, 12, 15, 20, 25, 30]
    MOST, DIMIN = 75.0, 5.0

    con = sqlite3.connect(DB)
    qmarks = ",".join("?" * len(markets))
    rows = con.execute(
        "SELECT i.market, i.id, d.date, d.close "
        "FROM daily_data d JOIN indices i ON d.index_id = i.id "
        f"WHERE i.market IN ({qmarks}) AND i.category = ? AND d.close IS NOT NULL AND d.close > 0 "
        "ORDER BY d.date", (*markets, category)).fetchall()
    con.close()
    # by_market[m][iid][date] = close —— 按 index_id 键控，避免同日多股票位置漂移
    by_market = {}
    for m, iid, dt, c in rows:
        by_market.setdefault(m, {}).setdefault(iid, {})[dt] = c

    curve_pooled = {n: [] for n in NS}
    oos_pooled = {n: [] for n in NS}
    per_market = {}
    for m in markets:
        dates_map = by_market.get(m, {})
        if not dates_map:
            continue
        all_dates = set()
        for sd in dates_map.values():
            all_dates.update(sd)
        dates = sorted(all_dates)
        dates = dates[-(TWIN + 1):]
        # 每只股票独立取序列，只保留覆盖>=99%日期的列（缺失填 NaN，后续按行剔除）
        usable = []
        for iid, sd in dates_map.items():
            if len(sd) >= len(dates) * 0.99:
                usable.append(np.asarray([sd.get(dt, np.nan) for dt in dates], dtype=np.float64))
        if len(usable) < max(NS):
            per_market[m] = {"error": f"usable stocks {len(usable)} < {max(NS)}"}
            continue
        P = np.vstack(usable)
        R = P[:, 1:] / P[:, :-1] - 1.0
        R = R[~np.isnan(R).any(axis=1)]
        oos_start = int(np.floor((1.0 - oos_frac) * R.shape[0]))
        var_i = np.nanvar(R, axis=1, ddof=1)
        var_i_oos = np.nanvar(R[oos_start:], axis=1, ddof=1)
        S = R.shape[0]
        curve, curve_oos = {}, {}
        for N in NS:
            if N > S:
                continue
            elims, elims_oos = [], []
            for _ in range(NDRAW):
                idx = rng.choice(S, size=N, replace=False)
                pr = R[idx].mean(axis=0)
                elims.append((1.0 - pr.var(ddof=1) / var_i.mean()) * 100.0)
                pro = R[idx][:, oos_start:].mean(axis=0)
                elims_oos.append((1.0 - pro.var(ddof=1) / var_i_oos.mean()) * 100.0)
            curve[N] = (float(np.mean(elims)), float(np.std(elims)))
            curve_oos[N] = float(np.mean(elims_oos))
            curve_pooled[N].append(curve[N][0])
            oos_pooled[N].append(curve_oos[N])
        per_market[m] = {"n_stocks": int(S),
                         "elim_pct": {str(n): round(v[0], 2) for n, v in curve.items()},
                         "elim_std": {str(n): round(v[1], 2) for n, v in curve.items()},
                         "elim_oos_pct": {str(n): round(v, 2) for n, v in curve_oos.items()}}
        print(f"    [{datetime.now():%H:%M:%S}] {m} done (S={S})", file=sys.stderr, flush=True)

    pooled = {n: round(float(np.mean(v)), 2) for n, v in curve_pooled.items() if v}
    pooled_oos = {n: round(float(np.mean(v)), 2) for n, v in oos_pooled.items() if v}
    e12 = pooled.get(12)
    e15, e30 = pooled.get(15), pooled.get(30)
    verdict = {
        "claim_type": "quantitative+qualitative（解释阈值已在契约披露）",
        "pooled_elim_curve": pooled,
        "pooled_elim_oos": pooled_oos,
        "elim_at_12": e12, "elim_at_15": e15, "elim_at_30": e30,
        "most_risk_threshold_pct": MOST,
        "diminishing_pp": round(e30 - e15, 2) if (e30 is not None and e15 is not None) else None,
        "diminishing_threshold_pp": DIMIN,
        "most_risk_ok": bool(e12 is not None and e12 >= MOST),
        "diminishing_ok": bool(e30 is not None and e15 is not None and (e30 - e15) <= DIMIN),
        "marginal_gains": {f"{a_}->{b_}": round(pooled[b_] - pooled[a_], 2)
                           for a_, b_ in zip(list(pooled)[:-1], list(pooled)[1:])},
    }
    verdict["supported"] = verdict["most_risk_ok"] and verdict["diminishing_ok"]

    lights = [
        {"item": "判据对齐（论断自己的量）", "status": "⚠️",
         "note": "'大部分/急剧递减'为定性词；本复测解释为 elim(12)>=75% 且 elim(30)-elim(15)<=5pp，契约+此处双披露"},
        {"item": "价格口径（前复权 close）", "status": "✅", "note": "000-data-biases.md A.1"},
        {"item": "时机（无前视）", "status": "✅", "note": "纯波动结构统计，无信号无交易"},
        {"item": "交易成本", "status": "✅", "note": "不适用（波动统计）"},
        {"item": "显著性/区间", "status": "✅",
         "note": f"每 N 抽 200 组合报 std；固定种子 {RNG_SEED} 可复现"},
        {"item": "重叠样本处理", "status": "✅", "note": "单一 750 日窗，无窗口重叠问题"},
        {"item": "样本外验证（后 20%）", "status": "✅", "note": "后 20% 交易日单独算曲线"},
        {"item": "幸存者偏差", "status": "⚠️",
         "note": "仅当前成分+全窗完整列，剔除了退市/停牌股；高波动股缺失使基数略偏保守"},
        {"item": "等权+随机抽样口径", "status": "⚠️",
         "note": "论断未指定加权方式，采用等权随机组合（最常见口径）；市值加权结果可能不同"},
        {"item": "可复现", "status": "✅", "note": "种子固定重跑同数"},
    ]

    payload = {
        "claim": {k: claim[k] for k in ("id", "title", "statement", "h0", "price_basis",
                                        "cost_bps", "signal_def", "verdict_metric",
                                        "data_scope") if k in claim},
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "engine": "diversification-curve",
        "config": {"rng_seed": RNG_SEED, "oos_frac": OOS_FRAC, "window_days": TWIN,
                   "n_draws": NDRAW, "n_values": NS, "weighting": "equal",
                   "most_threshold_pct": MOST, "diminishing_threshold_pp": DIMIN},
        "survivorship_note": "仅当前成分+全窗完整列；波动口径下影响有限",
        "protocol_lights": lights,
        "per_market": per_market,
        "aggregate": {"pooled_elim_curve": pooled, "pooled_elim_oos": pooled_oos},
        "verdict": verdict,
    }
    def _sum():
        print(f"  pooled elim曲线={pooled} "
              f"elim(12)={e12}% (判>={MOST}) elim(30)-elim(15)={verdict['diminishing_pp']}pp (判<={DIMIN}) "
              f"→ supported={verdict['supported']}")
    return _emit_results(claim, out_dir, payload, _sum)
# --------------------------------------------------------------------------
def run_kelly_fraction(claim, out_dir, oos_frac=OOS_FRAC, seed=RNG_SEED):
    """#37 Fractional Kelly (1/4)：复合增长率接近全 Kelly，最大回撤降低约一半。
    每只股票按日收益估 f* = mu/sigma^2（连续时间 Kelly），模拟 f* vs c*f*（c=0.25/0.5）
    的对数财富路径 V += log(1 + f*r)，窗口 504 步 126。
    解释阈值（契约披露）："接近" = cagr(c*f*)/cagr(f*) 中位数 >= 0.9；
    "约一半" = MDD 降幅中位数在 [40%, 60%]。理论参照：g(f*/4) = 0.4375*g(f*)。"""
    rng = np.random.default_rng(seed)
    markets = claim["data_scope"].get("markets", [])
    category = claim["data_scope"].get("category", "stock")
    WIN, STEP = 504, 126
    FRACS = {"half": 0.5, "quarter": 0.25}
    FSTAR_CAP = None  # 主口径不封顶；稳健性变体单独跑 2.0

    con = sqlite3.connect(DB)
    qmarks = ",".join("?" * len(markets))
    rows = con.execute(
        "SELECT i.market, i.ticker, d.date, d.close "
        "FROM daily_data d JOIN indices i ON d.index_id = i.id "
        f"WHERE i.market IN ({qmarks}) AND i.category = ? AND d.close IS NOT NULL AND d.close > 0 "
        "ORDER BY i.ticker, d.date", (*markets, category)).fetchall()
    con.close()
    series = {}
    for m, sym, dt, c in rows:
        series.setdefault((m, sym), {})[dt] = c

    def sim(closes, f):
        """返回 (cagr 年化, log-MDD, 天数, 可行)"""
        r = closes[1:] / closes[:-1] - 1.0
        if np.any(f * r <= -1.0):
            return None, None, len(r), False
        lv = np.log1p(f * r)
        v = np.cumsum(lv)
        n = len(v)
        cagr = v[-1] / n * 252.0
        peak = np.maximum.accumulate(v)
        mdd = float(np.max(peak - v))
        return cagr, mdd, n, True

    def run_variant(fstar_cap):
        """返回 (stock_stats dict, skipped_feasible 计数)"""
        stock_stats = {}
        skipped = 0
        for (m, sym), sd in series.items():
            dates = sorted(sd)
            closes = np.asarray([sd[d] for d in dates], dtype=np.float64)
            if len(closes) < WIN + 1:
                continue
            r = closes[1:] / closes[:-1] - 1.0
            mu, sg = float(np.mean(r)), float(np.std(r, ddof=1))
            if sg <= 0:
                continue
            fstar = mu / (sg * sg)
            if fstar_cap is not None:
                fstar = max(min(fstar, fstar_cap), 0.0)
            if fstar <= 0:
                continue
            n_hist = len(closes) - WIN - 1
            if n_hist < 1:
                continue
            oos_cut = int(np.floor((1.0 - oos_frac) * n_hist))
            recs = []
            for i in range(0, n_hist, STEP):
                path = closes[i:i + WIN + 1]
                cf, mf, n, ok = sim(path, fstar)
                if not ok or mf is None or mf <= 0:
                    skipped += 1
                    continue
                is_oos = i >= oos_cut
                for k, c in FRACS.items():
                    cq, mq, _, ok2 = sim(path, c * fstar)
                    if not ok2 or mq is None or mq <= 0:
                        skipped += 1
                        continue
                    recs.append({
                        "k": k,
                        "cagr_ratio": cq / cf if cf > 0 else np.nan,
                        "mdd_red": 1.0 - mq / mf,
                        "oos": is_oos,
                        "mdd_full": mf, "mdd_frac": mq,
                        "cagr_full": cf, "cagr_frac": cq})
            if recs:
                for k in FRACS:
                    rr = [x for x in recs if x["k"] == k]
                    if rr:
                        stock_stats.setdefault(m, []).append({
                            "k": k,
                            "market": m, "cagr_ratio": float(np.nanmedian([x["cagr_ratio"] for x in rr])),
                            "mdd_red": float(np.nanmedian([x["mdd_red"] for x in rr])),
                            "oos_cagr_ratio": float(np.nanmedian([x["cagr_ratio"] for x in rr if x["oos"]])) if any(x["oos"] for x in rr) else None,
                            "oos_mdd_red": float(np.nanmedian([x["mdd_red"] for x in rr if x["oos"]])) if any(x["oos"] for x in rr) else None,
                            "n_windows": len(rr)})
        return stock_stats, skipped

    stock_stats, skipped = run_variant(FSTAR_CAP)
    stock_stats_cap2, skipped_cap2 = run_variant(2.0)

    def pooled(st):
        out = {}
        for k in FRACS:
            vals = [v for lst in st.values() for v in lst if v["k"] == k]
            cr = [v["cagr_ratio"] for v in vals if v["cagr_ratio"] is not None and not np.isnan(v["cagr_ratio"])]
            mr = [v["mdd_red"] for v in vals]
            ocr = [v["oos_cagr_ratio"] for v in vals if v["oos_cagr_ratio"] is not None and not np.isnan(v["oos_cagr_ratio"])]
            omr = [v["oos_mdd_red"] for v in vals if v["oos_mdd_red"] is not None and not np.isnan(v["oos_mdd_red"])]
            out[k] = {
                "n_stocks": len(cr),
                "cagr_ratio_med": float(np.median(cr)) if cr else None,
                "mdd_red_med": float(np.median(mr)) if mr else None,
                "oos_cagr_ratio_med": float(np.median(ocr)) if ocr else None,
                "oos_mdd_red_med": float(np.median(omr)) if omr else None}
        return out, None

    pooled_main, vals_main = pooled(stock_stats)
    pooled_cap2, _ = pooled(stock_stats_cap2)

    # bootstrap（股票级重抽 2000 次，对 quarter 口径给 CI）
    boot_cr, boot_mr = [], []
    allv = [v for lst in stock_stats.values() for v in lst if v["k"] == "quarter"]
    B = BOOT_ITERS
    arr_cr = np.asarray([v["cagr_ratio"] for v in allv if v["cagr_ratio"] is not None and not np.isnan(v["cagr_ratio"])])
    arr_mr = np.asarray([v["mdd_red"] for v in allv if not np.isnan(v["mdd_red"])])
    for _ in range(B):
        idx = rng.integers(0, len(arr_cr), len(arr_cr))
        boot_cr.append(float(np.median(arr_cr[idx])))
        boot_mr.append(float(np.median(arr_mr[idx])))
    ci = lambda b: [float(np.percentile(b, 2.5)), float(np.percentile(b, 97.5))]

    # 分市场汇总（quarter 口径）
    per_market = {}
    for m, lst in stock_stats.items():
        qv = [v for v in lst if v["k"] == "quarter"]
        cr_m = [v["cagr_ratio"] for v in qv if v["cagr_ratio"] is not None and not np.isnan(v["cagr_ratio"])]
        per_market[m] = {
            "n_stocks": len(qv),
            "cagr_ratio_med": float(np.median(cr_m)) if cr_m else None,
            "mdd_red_med": float(np.median([v["mdd_red"] for v in qv]))}

    q = pooled_main["quarter"]
    CAGR_OK = 0.9
    MDD_LO, MDD_HI = 0.40, 0.60
    cagr_ok = q["cagr_ratio_med"] is not None and q["cagr_ratio_med"] >= CAGR_OK
    mdd_ok = q["mdd_red_med"] is not None and MDD_LO <= q["mdd_red_med"] <= MDD_HI
    verdict = {
        "claim_type": "quantitative（解释阈值已在契约披露：接近>=0.9 / 约一半=40-60%）",
        "quarter": q, "half": pooled_main["half"],
        "robustness_fstar_cap2": pooled_cap2["quarter"],
        "ci_cagr_ratio": ci(boot_cr), "ci_mdd_red": ci(boot_mr),
        "fstar_theory_ratio": 0.4375,
        "per_market": per_market,
        "skipped_infeasible_windows": skipped,
        "thresholds": {"cagr_ratio_min": CAGR_OK, "mdd_red_lo": MDD_LO, "mdd_red_hi": MDD_HI},
        "cagr_ok": cagr_ok, "mdd_ok": mdd_ok,
        "supported": bool(cagr_ok and mdd_ok)}

    payload = {"verdict": verdict, "per_market": per_market,
               "protocol_lights": {"primary_metric_is_claim_quantity": True,
                                   "all_in_scope_markets": True,
                                   "oos": True, "no_lookahead": True,
                                   "survivorship_note": "DB 仅存当前存在标的，退市股缺失，结果偏乐观"}}
    _emit_results(claim, out_dir, payload, lambda: _print_kelly(payload))
    return verdict


def _print_kelly(payload):
    v = payload["verdict"]
    q = v["quarter"]
    print("  quarter: cagr_ratio=%.3f (判>=%.1f) mdd_red=%.3f (判%.0f-%.0f%%) n=%s -> supported=%s" % (
        q["cagr_ratio_med"], v["thresholds"]["cagr_ratio_min"], q["mdd_red_med"],
        v["thresholds"]["mdd_red_lo"] * 100, v["thresholds"]["mdd_red_hi"] * 100, q["n_stocks"], v["supported"]))

def run_core_satellite(claim, out_dir, oos_frac=OOS_FRAC, seed=RNG_SEED):
    """#36 核心-卫星（核心50-80% ETF + 卫星20-50% 个股）夏普比优于纯 ETF 或纯个股。
    每市场：主指数（日期覆盖最长）+ 随机 12 只个股等权（#35 甜点位），窗口 504 步 126，
    每日再平衡：ret = c*index + (1-c)*stocks。每市场抽 50 组随机个股取均值降噪。
    判据：core_sat(0.65) 夏普 − 纯ETF 与 − 纯个股 的窗口配对差中位数 >0 且 block bootstrap CI low >0。"""
    rng = np.random.default_rng(seed)
    markets = claim["data_scope"].get("markets", [])
    WIN, STEP, NDRAW = 504, 126, 50
    CS_FRAC = 0.65
    BLOCK = 22

    con = sqlite3.connect(DB)
    # 主指数：category='index'，每市场取日期数最多的
    idx_rows = con.execute(
        "SELECT i.market, i.id, COUNT(*) AS n FROM daily_data d JOIN indices i ON d.index_id = i.id "
        "WHERE i.category = 'index' AND d.close IS NOT NULL AND d.close > 0 GROUP BY i.market, i.id").fetchall()
    best_idx = {}
    for m, iid, n in idx_rows:
        if m not in best_idx or n > best_idx[m][1]:
            best_idx[m] = (iid, n)
    # 个股
    qmarks = ",".join("?" * len(markets))
    st_rows = con.execute(
        "SELECT i.market, i.id, d.date, d.close "
        "FROM daily_data d JOIN indices i ON d.index_id = i.id "
        f"WHERE i.market IN ({qmarks}) AND i.category = 'stock' AND d.close IS NOT NULL AND d.close > 0 "
        "ORDER BY d.date", (*markets,)).fetchall()
    con.close()
    st = {}
    for m, iid, dt, c in st_rows:
        st.setdefault(m, {}).setdefault(iid, {})[dt] = c
    # 指数序列
    con = sqlite3.connect(DB)
    idx_series = {}
    for m, (iid, _) in best_idx.items():
        rows = con.execute("SELECT d.date, d.close FROM daily_data d WHERE d.index_id = ? AND d.close IS NOT NULL AND d.close > 0 ORDER BY d.date", (iid,)).fetchall()
        idx_series[m] = dict(rows)
    con.close()

    per_market = {}
    diff_etf, diff_stk = [], []   # 窗口配对差（跨市场汇合池）
    oos_diff_etf, oos_diff_stk = [], []
    stock_stats = []
    for m in markets:
        if m not in idx_series or len(idx_series[m]) < WIN + 1:
            per_market[m] = {"error": "no usable index"}
        else:
            sd_all = st.get(m, {})
            # 可用个股：覆盖 >=99% 指数日期
            idx_dates = sorted(idx_series[m])
            idx_dates = idx_dates[-(WIN + STEP * 7):]  # 8 个滚动窗口
            usable_ids = [iid for iid, sd in sd_all.items() if len(sd) >= len(idx_dates) * 0.99 and min(sd) <= idx_dates[0]]
            if len(usable_ids) < 12:
                per_market[m] = {"error": f"usable stocks {len(usable_ids)} < 12"}
            else:
                P_idx = np.asarray([idx_series[m][d] for d in idx_dates], dtype=np.float64)
                r_idx = P_idx[1:] / P_idx[:-1] - 1.0
                n_win = (len(r_idx) - 1) // STEP
                sharpe_cs, sharpe_etf, sharpe_stk = [], [], []
                for w in range(n_win):
                    i0 = w * STEP
                    ri = r_idx[i0:i0 + WIN]
                    if len(ri) < WIN:
                        continue
                    rng.shuffle(usable_ids)
                    grp_cs, grp_etf, grp_stk = [], [], []
                    for draw in range(NDRAW):
                        pick = usable_ids[:12] if draw == 0 else list(rng.choice(usable_ids, 12, replace=False))
                        R = []
                        ok = True
                        for iid in pick:
                            sd = sd_all[iid]
                            closes = np.asarray([sd.get(d, np.nan) for d in idx_dates[i0:i0 + WIN + 1]], dtype=np.float64)
                            if np.isnan(closes).any():
                                ok = False
                                break
                            R.append(closes[1:] / closes[:-1] - 1.0)
                        if not ok:
                            continue
                        r_stk = np.mean(R, axis=0)
                        r_cs = CS_FRAC * ri + (1.0 - CS_FRAC) * r_stk
                        def shp(r):
                            s = np.std(r, ddof=1)
                            return float(np.mean(r) / s * np.sqrt(252.0)) if s > 0 else np.nan
                        grp_cs.append(shp(r_cs)); grp_etf.append(shp(ri)); grp_stk.append(shp(r_stk))
                    if grp_cs:
                        sharpe_cs.append(float(np.nanmean(grp_cs)))
                        sharpe_etf.append(float(np.nanmean(grp_etf)))
                        sharpe_stk.append(float(np.nanmean(grp_stk)))
                if len(sharpe_cs) >= 5:
                    de = np.asarray(sharpe_cs) - np.asarray(sharpe_etf)
                    ds = np.asarray(sharpe_cs) - np.asarray(sharpe_stk)
                    per_market[m] = {
                        "n_windows": len(de),
                        "sharpe_cs_med": float(np.median(sharpe_cs)),
                        "sharpe_etf_med": float(np.median(sharpe_etf)),
                        "sharpe_stk_med": float(np.median(sharpe_stk)),
                        "diff_etf_med": float(np.median(de)),
                        "diff_stk_med": float(np.median(ds))}
                    n_oos = int(np.floor((1.0 - oos_frac) * len(de)))
                    diff_etf.extend(de); diff_stk.extend(ds)
                    oos_diff_etf.extend(de[n_oos:]); oos_diff_stk.extend(ds[n_oos:])
                    stock_stats.append({"market": m, "diff_etf": float(np.median(de)), "diff_stk": float(np.median(ds))})
                else:
                    per_market[m] = {"error": f"only {len(sharpe_cs)} windows"}

    def circ_boot(diffs):
        diffs = np.asarray(diffs)
        n = len(diffs)
        stats = []
        nb = max(1, n // BLOCK)
        for _ in range(BOOT_ITERS):
            starts = rng.integers(0, n, nb)
            sample = np.concatenate([np.arange(int(st_), int(st_) + BLOCK) % n for st_ in starts])
            sample = sample[:n]
            stats.append(float(np.median(diffs[sample])))
        return float(np.median(diffs)), float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))

    med_e, lo_e, hi_e = circ_boot(diff_etf)
    med_s, lo_s, hi_s = circ_boot(diff_stk)
    oos_e = float(np.median(oos_diff_etf)) if oos_diff_etf else None
    oos_s = float(np.median(oos_diff_stk)) if oos_diff_stk else None
    supported = bool(lo_e > 0 and lo_s > 0)
    verdict = {
        "claim_type": "quantitative",
        "cs_frac": CS_FRAC, "satellite_n": 12, "ndraw": NDRAW,
        "n_windows_pooled": len(diff_etf),
        "diff_vs_etf": {"median": med_e, "ci": [lo_e, hi_e], "oos_median": oos_e},
        "diff_vs_stock": {"median": med_s, "ci": [lo_s, hi_s], "oos_median": oos_s},
        "per_market": per_market,
        "supported": supported}

    payload = {"verdict": verdict, "per_market": per_market,
               "protocol_lights": {"primary_metric_is_claim_quantity": True,
                                   "all_in_scope_markets": True,
                                   "oos": True, "no_lookahead": True,
                                   "survivorship_note": "DB 仅存当前存在标的，退市股缺失，对核心-卫星略偏乐观"}}
    _emit_results(claim, out_dir, payload, lambda: _print_core_sat(payload))
    return verdict


def _print_core_sat(payload):
    v = payload["verdict"]
    print("  核心-卫星(65/35): vs纯ETF 差中位=%.3f CI[%.3f,%.3f]  vs纯个股 差中位=%.3f CI[%.3f,%.3f] -> supported=%s" % (
        v["diff_vs_etf"]["median"], *v["diff_vs_etf"]["ci"],
        v["diff_vs_stock"]["median"], *v["diff_vs_stock"]["ci"], v["supported"]))

def run_cash_buffer(claim, out_dir, oos_frac=OOS_FRAC, seed=RNG_SEED):
    """#38 现金<10% 的组合在暴跌时失去加仓能力，3 年收益跑赢 15% 现金的概率 <60%。
    每市场主指数，窗口 756 步 126（3 年）。A=满仓指数；B=85% 指数+15% 现金（现金 0 收益，
    每日再平衡），指数从窗口内滚动高点回撤 >=20% 时现金一次入市。
    主指标 = 满仓跑赢 B 的窗口频率。判据：P < 0.60（原话量化），block bootstrap CI。"""
    rng = np.random.default_rng(seed)
    markets = claim["data_scope"].get("markets", [])
    WIN, STEP = 756, 126
    CASH = 0.15
    TRIG = 0.20
    BLOCK = 22

    con = sqlite3.connect(DB)
    idx_rows = con.execute(
        "SELECT i.market, i.id, COUNT(*) AS n FROM daily_data d JOIN indices i ON d.index_id = i.id "
        "WHERE i.category = 'index' AND d.close IS NOT NULL AND d.close > 0 GROUP BY i.market, i.id").fetchall()
    best_idx = {}
    for m, iid, n in idx_rows:
        if m not in best_idx or n > best_idx[m][1]:
            best_idx[m] = (iid, n)
    idx_series = {}
    for m, (iid, _) in best_idx.items():
        rows = con.execute("SELECT d.date, d.close FROM daily_data d WHERE d.index_id = ? AND d.close IS NOT NULL AND d.close > 0 ORDER BY d.date", (iid,)).fetchall()
        idx_series[m] = dict(rows)
    con.close()

    per_market = {}
    win_a = []          # 满仓是否跑赢（1/0）
    diff = []           # cagr_a - cagr_b
    oos_win, oos_diff = [], []
    trig_rate = []
    for m in markets:
        if m not in idx_series:
            per_market[m] = {"error": "no usable index"}
            continue
        sd = idx_series[m]
        dates = sorted(sd)
        closes_all = np.asarray([sd[d] for d in dates], dtype=np.float64)
        r_all = closes_all[1:] / closes_all[:-1] - 1.0
        n_win = (len(r_all) - 1) // STEP
        if n_win < 3:
            per_market[m] = {"error": f"only {n_win} windows"}
            continue
        mw, md, mt = [], [], []
        for w in range(n_win):
            i0 = w * STEP
            r = r_all[i0:i0 + WIN]
            if len(r) < WIN:
                continue
            path = np.cumprod(1.0 + r)
            peak = np.maximum.accumulate(path)
            dd = path / peak - 1.0
            hits = np.nonzero(dd <= -TRIG)[0]
            triggered = len(hits) > 0
            trig_i = int(hits[0]) if triggered else None
            cagr_a = float(np.log(path[-1]) / WIN * 252.0)
            # B：85/15 每日再平衡，触发后全额入市
            rb = np.where(triggered and trig_i is not None, 0, None)
            r_b = np.empty(WIN)
            if triggered:
                r_b[:trig_i] = (1.0 - CASH) * r[:trig_i]
                r_b[trig_i] = (1.0 - CASH) * r[trig_i] + 0.0  # 当日仍 85/15，次日入市
                r_b[trig_i + 1:] = r[trig_i + 1:]
            else:
                r_b[:] = (1.0 - CASH) * r
            path_b = np.cumprod(1.0 + r_b)
            cagr_b = float(np.log(path_b[-1]) / WIN * 252.0)
            is_oos = w >= int(np.floor((1.0 - oos_frac) * n_win))
            rec = (1 if cagr_a > cagr_b else 0, cagr_a - cagr_b, is_oos)
            mw.append(rec[0]); md.append(rec[1])
            win_a.append(rec[0]); diff.append(rec[1])
            if is_oos:
                oos_win.append(rec[0]); oos_diff.append(rec[1])
            mt.append(1 if triggered else 0)
        if mw:
            per_market[m] = {
                "n_windows": len(mw),
                "a_beats_b_pct": float(np.mean(mw)) * 100,
                "diff_cagr_med": float(np.median(md)),
                "trigger_pct": float(np.mean(mt)) * 100}

    p_a = float(np.mean(win_a))
    # block bootstrap：比例 CI
    win_a_arr = np.asarray(win_a, dtype=np.float64)
    n = len(win_a_arr)
    nb = max(1, n // BLOCK)
    stats = []
    for _ in range(BOOT_ITERS):
        starts = rng.integers(0, n, nb)
        sample = np.concatenate([np.arange(int(st_), int(st_) + BLOCK) % n for st_ in starts])[:n]
        stats.append(float(np.mean(win_a_arr[sample])))
    lo_p, hi_p = float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))
    supported = bool(hi_p < 0.60)
    verdict = {
        "claim_type": "quantitative",
        "window_days": WIN, "cash": CASH, "trigger_dd": TRIG,
        "n_windows": n,
        "p_full_beats_cash": p_a, "p_ci": [lo_p, hi_p],
        "threshold": 0.60,
        "oos_p": float(np.mean(oos_win)) if oos_win else None,
        "mean_diff_cagr": float(np.mean(diff)),
        "oos_mean_diff": float(np.mean(oos_diff)) if oos_diff else None,
        "per_market": per_market,
        "supported": supported}

    payload = {"verdict": verdict, "per_market": per_market,
               "protocol_lights": {"primary_metric_is_claim_quantity": True,
                                   "all_in_scope_markets": True,
                                   "oos": True, "no_lookahead": True,
                                   "survivorship_note": "指数口径无幸存者问题；现金收益按 0 计，未计利息"}}
    _emit_results(claim, out_dir, payload, lambda: _print_cash(payload))
    return verdict


def _print_cash(payload):
    v = payload["verdict"]
    print("  满仓跑赢15%%现金频率=%.1f%% CI[%.1f%%,%.1f%%] (判<60%%) 窗口=%d -> supported=%s" % (
        v["p_full_beats_cash"] * 100, v["p_ci"][0] * 100, v["p_ci"][1] * 100, v["n_windows"], v["supported"]))

def run_sector_concentration(claim, out_dir, oos_frac=OOS_FRAC, seed=RNG_SEED):
    """#41 组合行业集中度 >40% 时，发生 -30% 回撤的概率 >50%。
    US 有行业+足够历史的个股；3 年窗口 756/126；每窗口抽 100 个集中组合（10 只等权中
    同一行业 >=4 只即 >=40%）与 100 个分散组合（每行业 <=2 只）对比 MDD<=-30% 频率。
    主指标 = 集中组合 MDD<=-30% 的窗口级频率；判据：均值 >0.50 且 block bootstrap CI low >0.50。"""
    rng = np.random.default_rng(seed)
    markets = claim["data_scope"].get("markets", [])
    WIN, STEP, NDRAW, NSTOCK = 756, 126, 100, 10
    CONC_MIN, DIV_MAX, DD_TH = 4, 2, 0.30
    BLOCK = 22

    con = sqlite3.connect(DB)
    qmarks = ",".join("?" * len(markets))
    rows = con.execute(
        "SELECT i.market, i.id, d.date, d.close "
        "FROM daily_data d JOIN indices i ON d.index_id = i.id "
        f"WHERE i.market IN ({qmarks}) AND i.category = 'stock' AND d.close IS NOT NULL AND d.close > 0 "
        "ORDER BY d.date", (*markets,)).fetchall()
    sec_rows = con.execute(
        "SELECT i.market, f.index_id, f.sector FROM fundamentals f JOIN indices i ON f.index_id = i.id "
        "WHERE f.sector IS NOT NULL AND f.sector != ''").fetchall()
    con.close()
    st = {}
    for m, iid, dt, c in rows:
        st.setdefault(m, {}).setdefault(iid, {})[dt] = c
    sector = {}
    for m, iid, sec in sec_rows:
        sector[(m, iid)] = sec

    per_market = {}
    conc_flags, div_flags = [], []   # 窗口级：该窗口集中/分散组合 MDD<=-30% 的频率
    oos_conc, oos_div = [], []
    for m in markets:
        sd_all = st.get(m, {})
        cand = {iid: sd for iid, sd in sd_all.items() if (m, iid) in sector}
        if not cand:
            per_market[m] = {"error": "no sector data"}
            continue
        all_dates = sorted(set().union(*[set(sd) for sd in cand.values()]))
        all_dates = all_dates[-(WIN + STEP * 29):]
        pc, pd_ = [], []
        for w in range((len(all_dates) - 1) // STEP):
            i0 = w * STEP
            wdates = all_dates[i0:i0 + WIN + 1]
            if len(wdates) < WIN + 1:
                break
            pool = []
            for iid, sd in cand.items():
                if all(d in sd for d in wdates):
                    pool.append(iid)
            by_sec = {}
            for iid in pool:
                by_sec.setdefault(sector[(m, iid)], []).append(iid)
            multi_secs = [sec for sec, lst in by_sec.items() if len(lst) >= CONC_MIN]
            if len(pool) < NSTOCK or len(multi_secs) < 1:
                continue
            rets = {iid: np.diff(np.asarray([sd[d] for d in wdates], dtype=np.float64)) / np.asarray([sd[d] for d in wdates], dtype=np.float64)[:-1] for iid, sd in cand.items() if all(d in sd for d in wdates)}
            n_w_total = min((len(all_dates) - 1) // STEP, (len(all_dates) - WIN) // STEP + 1)
            is_oos = w >= int(np.floor((1.0 - oos_frac) * n_w_total))

            def mdd_of(pick):
                r = np.mean([rets[iid] for iid in pick], axis=0)
                nav = np.cumprod(1.0 + r)
                peak = np.maximum.accumulate(nav)
                return float(np.max(peak / nav - 1.0))

            cw, dw = [], []
            for _ in range(NDRAW):
                sec0 = multi_secs[int(rng.integers(0, len(multi_secs)))]
                others = [i for i in pool if sector[(m, i)] != sec0]
                pick0 = list(rng.choice(by_sec[sec0], CONC_MIN, replace=False))
                pick0 += list(rng.choice(others, NSTOCK - CONC_MIN, replace=False))
                cw.append(1 if mdd_of(pick0) >= DD_TH else 0)
                # 分散：每行业 <=2 只
                for _try in range(20):
                    pick1 = list(rng.choice(pool, NSTOCK, replace=False))
                    cnt = {}
                    for i in pick1:
                        cnt[sector[(m, i)]] = cnt.get(sector[(m, i)], 0) + 1
                    if max(cnt.values()) <= DIV_MAX:
                        break
                if max(cnt.values()) <= DIV_MAX:
                    dw.append(1 if mdd_of(pick1) >= DD_TH else 0)
            if cw:
                pc.append(float(np.mean(cw)))
                conc_flags.append(float(np.mean(cw)))
                if is_oos:
                    oos_conc.append(float(np.mean(cw)))
            if dw:
                pd_.append(float(np.mean(dw)))
                div_flags.append(float(np.mean(dw)))
                if is_oos:
                    oos_div.append(float(np.mean(dw)))
        if pc:
            per_market[m] = {
                "n_windows": len(pc),
                "p_conc_med": float(np.median(pc)),
                "p_div_med": float(np.median(pd_)) if pd_ else None}
        else:
            per_market[m] = {"error": "no windows"}

    conc_arr = np.asarray(conc_flags)
    n = len(conc_arr)
    nb = max(1, n // BLOCK)
    stats = []
    for _ in range(BOOT_ITERS):
        starts = rng.integers(0, n, nb)
        sample = np.concatenate([np.arange(int(st_), int(st_) + BLOCK) % n for st_ in starts])[:n]
        stats.append(float(np.mean(conc_arr[sample])))
    mean_c = float(np.mean(conc_arr))
    lo_c, hi_c = float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))
    supported = bool(lo_c > 0.50)
    verdict = {
        "claim_type": "quantitative",
        "n_windows": n, "ndraw": NDRAW, "nstock": NSTOCK,
        "conc_rule": f">= {CONC_MIN}/{NSTOCK} 同行业 (>=40%)",
        "p_conc_mean": mean_c, "p_conc_ci": [lo_c, hi_c],
        "p_div_mean": float(np.mean(div_flags)) if div_flags else None,
        "threshold": 0.50,
        "oos_p_conc": float(np.mean(oos_conc)) if oos_conc else None,
        "oos_p_div": float(np.mean(oos_div)) if oos_div else None,
        "per_market": per_market,
        "supported": supported}

    payload = {"verdict": verdict, "per_market": per_market,
               "protocol_lights": {"primary_metric_is_claim_quantity": True,
                                   "all_in_scope_markets": True,
                                   "oos": True, "no_lookahead": True,
                                   "survivorship_note": "DB 仅存当前存在标的，退市股缺失 → -30% 回撤概率被低估；若仍 >50% 则结论更稳"}}
    _emit_results(claim, out_dir, payload, lambda: _print_sector(payload))
    return verdict


def _print_sector(payload):
    v = payload["verdict"]
    print("  集中组合 P(MDD>=30%%)=%.1f%% CI[%.1f%%,%.1f%%] (判>50%%)  分散=%.1f%%  窗口=%d -> supported=%s" % (
        v["p_conc_mean"] * 100, v["p_conc_ci"][0] * 100, v["p_conc_ci"][1] * 100,
        (v["p_div_mean"] or 0) * 100, v["n_windows"], v["supported"]))

# --------------------------------------------------------------------------
# 8j) 论断 #11 引擎：VIX 恐慌买入（engine: vix-panic-buy）
# --------------------------------------------------------------------------
def run_vix_panic_buy(claim, out_dir, oos_frac=OOS_FRAC, seed=RNG_SEED):
    """实现 000-claims-def.md id=11 契约（engine: vix-panic-buy）：
      事件 = VIX 收盘自 <=30 上穿 >30 的首日（episode 起点，避免重叠窗口堆叠）；
      事件收益 = 标普500 126 交易日（约6个月）前瞻收益；
      基线 = VIX<=15 平静期逐日 126 日前瞻收益均值（登记口径），无条件均值作参考；
      主判据 = 事件均值 − 平静期基线 > 0 且 episode 层 iid bootstrap（2000 次）
      95% CI 下界 > 0；样本外 = 事件起始日在后 20% 时段单独报告。
    """
    rng = np.random.default_rng(seed)
    ts = claim.get("test_spec", {})
    vix_t = ts.get("vix_ticker", "^VIX")
    idx_t = ts.get("index_ticker", "^GSPC")
    thr = float(ts.get("vix_threshold", 30.0))
    H = int(ts.get("horizon_days", 126))

    con = sqlite3.connect(DB)
    vix = dict(con.execute(
        "SELECT d.date, d.close FROM daily_data d JOIN indices i ON d.index_id=i.id "
        "WHERE i.ticker=? AND d.close IS NOT NULL AND d.close > 0", (vix_t,)).fetchall())
    spx = dict(con.execute(
        "SELECT d.date, d.close FROM daily_data d JOIN indices i ON d.index_id=i.id "
        "WHERE i.ticker=? AND d.close IS NOT NULL AND d.close > 0", (idx_t,)).fetchall())
    con.close()

    dates = sorted(set(vix) & set(spx))
    if len(dates) < H * 5:
        payload = {"claim_id": claim["id"], "error": "VIX/SPX overlap insufficient",
                   "verdict": "NO_DATA"}
        return _emit_results(claim, out_dir, payload,
                             lambda: print("VIX/SPX 重叠样本不足"))

    vi = np.asarray([vix[dt] for dt in dates], dtype=np.float64)
    px = np.asarray([spx[dt] for dt in dates], dtype=np.float64)
    n = len(dates)
    fwd = np.full(n, np.nan)
    fwd[:n - H] = px[H:] / px[:n - H] - 1.0

    trig = np.zeros(n, dtype=bool)
    trig[1:] = (vi[1:] > thr) & (vi[:-1] <= thr)
    ev_all = np.where(trig & ~np.isnan(fwd))[0]
    calm_thr = float(ts.get("calm_threshold", 15.0))
    calm_mask = (vi <= calm_thr) & ~np.isnan(fwd)
    baseline = float(np.nanmean(fwd[calm_mask]))
    uncond = float(np.nanmean(fwd))

    def boot_ci(vals):
        vals = np.asarray(vals, dtype=np.float64)
        if len(vals) < 5:
            return [None, None]
        idx = rng.integers(0, len(vals), (BOOT_ITERS, len(vals)))
        lo, hi = np.percentile(vals[idx].mean(axis=1), [2.5, 97.5])
        return [float(lo), float(hi)]

    def report(idx_ev):
        if len(idx_ev) == 0:
            return {"n_episodes": 0}
        ev = fwd[idx_ev]
        diffs = ev - baseline
        return {
            "n_episodes": int(len(idx_ev)),
            "event_mean": float(np.nanmean(ev)),
            "event_median": float(np.nanmedian(ev)),
            "event_win_rate": float(np.mean(ev > 0)),
            "baseline_mean": baseline,
            "unconditional_mean": uncond,
            "diff_mean": float(np.nanmean(diffs)),
            "diff_ci": boot_ci(diffs),
            "episode_years": sorted({dates[int(i)][:4] for i in idx_ev}),
        }

    oos_start = int(np.floor((1.0 - oos_frac) * n))
    full = report(ev_all)
    ins = report(ev_all[ev_all < oos_start])
    oos = report(ev_all[ev_all >= oos_start])

    ci = full.get("diff_ci", [None, None])
    supported = bool(ci[0] is not None and ci[0] > 0.0)
    payload = {
        "claim_id": claim["id"],
        "vix_threshold": thr,
        "horizon_days": H,
        "window": {"start": dates[0], "end": dates[-1], "n_days": n},
        "full_window": full,
        "in_sample": ins,
        "out_of_sample": oos,
        "supported": supported,
        "verdict": "SUPPORTED" if supported else "REJECTED",
        "notes": ["episode 层 iid bootstrap（事件为抽样单位，非逐日块 bootstrap），已在卡中披露",
                  "事件=VIX 收盘上穿 30 首日，持有 126 交易日",
                  "主基线=VIX<=15 平静期同持有期收益（登记口径）；unconditional_mean=全样本无条件均值仅作参考"],
    }

    def _print_vix():
        f = payload["full_window"]
        if f.get("n_episodes", 0) == 0:
            print("无事件触发")
            return
        w = payload["window"]
        print(f"窗口: {w['start']} ~ {w['end']}  事件数: {f['n_episodes']}")
        print(f"事件6个月均值: {f['event_mean']:.2%}  平静期基线: {f['baseline_mean']:.2%}  "
              f"差: {f['diff_mean']:.2%}  无条件均值: {f['unconditional_mean']:.2%}")
        print(f"差值95%CI: {f['diff_ci']}  事件胜率: {f['event_win_rate']:.1%}")
        o = payload["out_of_sample"]
        print(f"样本外: n={o.get('n_episodes')}  diff={o.get('diff_mean')}  "
              f"CI={o.get('diff_ci')}")
        print("判定:", payload["verdict"])

    return _emit_results(claim, out_dir, payload, _print_vix)


# --------------------------------------------------------------------------
# 8k) 论断 #32 引擎：股息率>无风险利率跑赢不派息（engine: dividend-vs-rf）
# --------------------------------------------------------------------------
def run_dividend_vs_rf(claim, out_dir, oos_frac=OOS_FRAC, seed=RNG_SEED):
    """实现 000-claims-def.md id=32 契约（engine: dividend-vs-rf）：
      年度队列（2012 起，每年首个交易日建仓，持有 252 交易日）；
      A 组 = 股息率（过去 365 天派息/现价）> 无风险利率（^TNX，即期）且
             过去 5 个日历年中 ≥3 年有派息（"可持续派息"的量化解释，卡中披露）；
      B 组 = 截至 t 从未派息（"不派息公司"）；
      主判据 = A−B 前瞻收益差的股票层 two-sample bootstrap（2000 次）95% CI 下界 > 0；
      样本外 = 后 20% 队列单独报告。
    """
    rng = np.random.default_rng(seed)
    ts = claim.get("test_spec", {})
    rf_ticker = ts.get("rf_ticker", "^TNX")
    hold = int(ts.get("hold_days", 252))
    first_year = int(ts.get("first_year", 2012))
    calm_years = int(ts.get("sustain_years", 3))

    con = sqlite3.connect(DB)
    gspc_dates = [r[0] for r in con.execute(
        "SELECT d.date FROM daily_data d JOIN indices i ON d.index_id=i.id "
        "WHERE i.ticker='^GSPC' ORDER BY d.date")]
    rf = dict(con.execute(
        "SELECT d.date, d.close FROM daily_data d JOIN indices i ON d.index_id=i.id "
        "WHERE i.ticker=? AND d.close IS NOT NULL", (rf_ticker,)).fetchall())
    us_ids = [r[0] for r in con.execute(
        "SELECT id FROM indices WHERE market='US' AND category='stock'")]

    # 队列日：每年首个交易日
    cohort_starts = {}
    for dt in gspc_dates:
        y = int(dt[:4])
        if y >= first_year and y not in cohort_starts:
            cohort_starts[y] = dt
    years = sorted(cohort_starts)
    idx_of = {d: k for k, d in enumerate(gspc_dates)}
    cohorts = []
    for y in years:
        s = cohort_starts[y]
        k = idx_of[s]
        if k + hold >= len(gspc_dates):
            continue
        cohorts.append((y, s, gspc_dates[k + hold]))
    n_oos = max(1, int(round(len(cohorts) * oos_frac)))
    oos_cut = len(cohorts) - n_oos

    need_dates = sorted({d for _, s, e in cohorts for d in (s, e)})
    ph = ",".join("?" * len(need_dates))
    px = {}
    for iid, dt, c in con.execute(
            f"SELECT d.index_id, d.date, d.close FROM daily_data d JOIN indices i ON d.index_id=i.id "
            f"WHERE i.market='US' AND i.category='stock' AND d.date IN ({ph}) AND d.close > 0",
            need_dates):
        px[(iid, dt)] = float(c)
    divs = {}
    for iid, ex, amt in con.execute(
            "SELECT d.index_id, d.ex_date, d.dividend FROM dividends d JOIN indices i ON d.index_id=i.id "
            "WHERE i.market='US' AND d.dividend > 0"):
        divs.setdefault(iid, []).append((ex, float(amt)))
    con.close()

    def dt_key(s):
        return "".join(s[:10].split("-"))

    per_cohort = []
    for y, s, e in cohorts:
        rf_y = rf.get(s)
        if rf_y is None:
            near = [d for d in rf if abs(_ord(d) - _ord(s)) <= 7]
            if not near:
                continue
            rf_y = rf[min(near, key=lambda d: abs(_ord(d) - _ord(s)))]
        rfv = rf_y / 1000.0  # ^TNX 报价=收益率%×10 → 小数需 /1000
        gA, gB = [], []
        for iid in us_ids:
            p0, p1 = px.get((iid, s)), px.get((iid, e))
            if not p0 or not p1:
                continue
            r = p1 / p0 - 1.0
            hist = divs.get(iid, [])
            prior = [(ex, a) for ex, a in hist if ex < dt_key(s)]
            trailing = sum(a for ex, a in prior if ex >= dt_key(_shift_year(s, -1)))
            dy = trailing / p0
            yrs_paid = len({ex[:4] for ex, _ in prior if ex >= dt_key(_shift_year(s, -5))})
            if dy > rfv and yrs_paid >= calm_years:
                gA.append(r)
            elif not prior:
                gB.append(r)
        if len(gA) >= 10 and len(gB) >= 10:
            per_cohort.append({"year": y, "rf": rfv, "n_a": len(gA), "n_b": len(gB),
                               "mean_a": float(np.mean(gA)), "mean_b": float(np.mean(gB)),
                               "gA": gA, "gB": gB})

    if len(per_cohort) < 4:
        payload = {"claim_id": claim["id"], "verdict": "NO_DATA",
                   "error": f"usable cohorts {len(per_cohort)} < 4",
                   "cohorts": [{k: v for k, v in c.items() if not k.startswith('g')} for c in per_cohort]}
        return _emit_results(claim, out_dir, payload, lambda: print("可用队列不足"))

    diffs = np.asarray([c["mean_a"] - c["mean_b"] for c in per_cohort], dtype=np.float64)
    # 股票层 two-sample bootstrap：重抽 A、B 股票后重算队列差
    boot = np.empty(BOOT_ITERS)
    for b in range(BOOT_ITERS):
        d_b = []
        for c in per_cohort:
            a = c["gA"]; bb = c["gB"]
            sa = np.mean(a if not len(a) else [a[i] for i in rng.integers(0, len(a), len(a))])
            sb = np.mean(bb if not len(bb) else [bb[i] for i in rng.integers(0, len(bb), len(bb))])
            d_b.append(sa - sb)
        boot[b] = np.mean(d_b)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    ins, oos = diffs[:oos_cut], diffs[oos_cut:]
    supported = bool(lo > 0.0)
    slim = [{k: v for k, v in c.items() if not k.startswith("g")} for c in per_cohort]
    payload = {
        "claim_id": claim["id"],
        "hold_days": hold,
        "rf_ticker": rf_ticker,
        "sustain_rule": f"过去5个日历年中>={calm_years}年有派息（可持续派息的量化解释）",
        "cohorts": slim,
        "full_window": {"n_cohorts": len(per_cohort),
                        "mean_diff": float(np.mean(diffs)),
                        "diff_ci": [float(lo), float(hi)],
                        "win_rate": float(np.mean(diffs > 0))},
        "out_of_sample": {"n_cohorts": len(oos), "mean_diff": float(np.mean(oos)) if len(oos) else None},
        "supported": supported,
        "verdict": "SUPPORTED" if supported else "REJECTED",
        "notes": ["股票层 two-sample bootstrap（组内重抽后重算各队列差）",
                  "可持续派息=过去5个日历年>=3年派息（解释性阈值，已在契约与卡中披露）",
                  "B 组=截至建仓日从未派息的 US 股票；本地库仅当前成分快照，幸存者偏差使两组都偏乐观"],
    }

    def _print_div():
        f = payload["full_window"]
        print(f"队列数: {f['n_cohorts']}  年均差(A-B): {f['mean_diff']:.2%}  "
              f"95%CI: {[round(x, 4) for x in f['diff_ci']]}  胜率: {f['win_rate']:.0%}")
        for c in payload["cohorts"]:
            print(f"  {c['year']} rf={c['rf']:.2%} nA={c['n_a']} nB={c['n_b']} "
                  f"A={c['mean_a']:.2%} B={c['mean_b']:.2%} diff={c['mean_a'] - c['mean_b']:.2%}")
        print(f"样本外: {payload['out_of_sample']}")
        print("判定:", payload["verdict"])

    return _emit_results(claim, out_dir, payload, _print_div)


def _ord(d):
    import datetime as _dt
    return _dt.date(int(d[:4]), int(d[5:7]), int(d[8:10])).toordinal()


def _shift_year(s, dy):
    import datetime as _dt
    d = _dt.date(int(s[:4]), int(s[5:7]), int(s[8:10]))
    try:
        d = d.replace(year=d.year + dy)
    except ValueError:
        d = d.replace(year=d.year + dy, day=28)
    return d.isoformat()


def dts_ord(d):
    return _ord(d)


# --------------------------------------------------------------------------
# 8l) 论断 #12 引擎：VIX 深度分层（engine: vix-depth）
# --------------------------------------------------------------------------
def run_vix_depth(claim, out_dir, oos_frac=OOS_FRAC, seed=RNG_SEED):
    """实现 000-claims-def.md id=12 契约（engine: vix-depth）：
      逐日按 VIX 收盘分桶（<15/15-20/20-25/25-30/30-35/>35，另报 >40），
      每日 126 交易日（约6个月）前瞻收益；
      主判据（阈值序）= mean(VIX>=25) − mean(VIX<25) > 0，组内 22 日循环块
      bootstrap（2000 次）95% CI 下界 > 0；
      次判据（严格序）= 登记口径 VIX>40 > 30-35桶 > 25-30桶（桶均值逐级递增）；
      两者皆过=✅，仅过阈值序=🟡（登记的严格三层序不成立）；
      样本外 = 后 20% 日期。
    """
    rng = np.random.default_rng(seed)
    ts = claim.get("test_spec", {})
    H = int(ts.get("horizon_days", 126))

    con = sqlite3.connect(DB)
    vix = dict(con.execute(
        "SELECT d.date, d.close FROM daily_data d JOIN indices i ON d.index_id=i.id "
        "WHERE i.ticker='^VIX' AND d.close IS NOT NULL AND d.close > 0").fetchall())
    spx = dict(con.execute(
        "SELECT d.date, d.close FROM daily_data d JOIN indices i ON d.index_id=i.id "
        "WHERE i.ticker='^GSPC' AND d.close IS NOT NULL AND d.close > 0").fetchall())
    con.close()

    dates = sorted(set(vix) & set(spx))
    if len(dates) < H * 5:
        payload = {"claim_id": claim["id"], "verdict": "NO_DATA",
                   "error": "VIX/SPX overlap insufficient"}
        return _emit_results(claim, out_dir, payload, lambda: print("样本不足"))

    vi = np.asarray([vix[dt] for dt in dates], dtype=np.float64)
    px = np.asarray([spx[dt] for dt in dates], dtype=np.float64)
    n = len(dates)
    fwd = np.full(n, np.nan)
    fwd[:n - H] = px[H:] / px[:n - H] - 1.0

    buckets = [("<15", 0.0, 15.0), ("15-20", 15.0, 20.0), ("20-25", 20.0, 25.0),
               ("25-30", 25.0, 30.0), ("30-35", 30.0, 35.0), (">35", 35.0, 1e9)]

    def bucket_of(v):
        for name, lo, hi in buckets:
            if lo <= v < hi:
                return name
        return None

    def block_boot_ci(hi_idx, lo_idx, nb=BOOT_ITERS, block=22):
        """组内 22 日循环块 bootstrap 求两组均值差 CI。"""
        def circ_means(idx, nb):
            idx = np.asarray(idx, dtype=int)
            m = len(idx)
            if m == 0:
                return None
            k = max(1, int(np.ceil(m / block)))
            out = np.empty(nb)
            for j in range(nb):
                starts = rng.integers(0, m, k)
                sample = np.concatenate([np.arange(int(st_), int(st_) + block) % m for st_ in starts])[:m]
                out[j] = np.nanmean(fwd[idx[sample]])
            return out
        a = circ_means(hi_idx, nb)
        b = circ_means(lo_idx, nb)
        if a is None or b is None or len(a) < 5 or len(b) < 5:
            return [None, None]
        d = a - b
        return [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))]

    def report(idx_slice):
        day_idx = {d: k for k, d in enumerate(dates)}
        ks = [day_idx[dt] for dt in idx_slice]
        rows = {}
        for name, lo, hi in buckets:
            sel = [k for k in ks if lo <= vi[k] < hi and not np.isnan(fwd[k])]
            rows[name] = {"n_days": len(sel),
                          "mean_fwd": float(np.mean(fwd[sel])) if sel else None}
        sel40 = [k for k in ks if vi[k] >= 40 and not np.isnan(fwd[k])]
        rows[">40"] = {"n_days": len(sel40),
                       "mean_fwd": float(np.mean(fwd[sel40])) if sel40 else None}
        hi = [k for k in ks if vi[k] >= 25 and not np.isnan(fwd[k])]
        lo = [k for k in ks if vi[k] < 25 and not np.isnan(fwd[k])]
        diff = float(np.mean(fwd[hi]) - np.mean(fwd[lo])) if hi and lo else None
        return {"buckets": rows, "n_hi": len(hi), "n_lo": len(lo),
                "hi_minus_lo": diff, "hi_minus_lo_ci": block_boot_ci(hi, lo)}

    oos_start = int(np.floor((1.0 - oos_frac) * n))
    full = report(dates)
    oos = report(dates[oos_start:])

    ci = full["hi_minus_lo_ci"]
    threshold_ok = bool(ci[0] is not None and ci[0] > 0.0)
    b = full["buckets"]
    strict_ok = (b[">40"]["mean_fwd"] is not None and b["30-35"]["mean_fwd"] is not None
                 and b["25-30"]["mean_fwd"] is not None
                 and b[">40"]["mean_fwd"] > b["30-35"]["mean_fwd"] > b["25-30"]["mean_fwd"])
    if threshold_ok and strict_ok:
        verdict = "SUPPORTED"
    elif threshold_ok:
        verdict = "THRESHOLD_ONLY"
    else:
        verdict = "REJECTED"

    payload = {
        "claim_id": claim["id"],
        "horizon_days": H,
        "window": {"start": dates[0], "end": dates[-1], "n_days": n},
        "full_window": full,
        "out_of_sample": oos,
        "threshold_ok": threshold_ok,
        "strict_ok": strict_ok,
        "verdict": verdict,
        "notes": ["组内 22 日循环块 bootstrap（保留 VIX regime 自相关）",
                  "主判据=阈值序(VIX>=25 vs <25)；严格序=登记口径 >40>30-35>25-30 逐级递增",
                  "逐日信号口径（非 #11 的 episode 去重口径），重叠窗口已如实披露"],
    }

    def _print_depth():
        f = payload["full_window"]
        print(f"窗口: {payload['window']['start']} ~ {payload['window']['end']}")
        for name, r in f["buckets"].items():
            m = r["mean_fwd"]
            print(f"  VIX {name:>5}: n={r['n_days']:>5}  6个月均值={m:.2%}" if m is not None
                  else f"  VIX {name:>5}: n={r['n_days']}")
        print(f"阈值序(>=25 vs <25): diff={f['hi_minus_lo']:.2%}  "
              f"CI={f['hi_minus_lo_ci']}")
        o = payload["out_of_sample"]
        print(f"样本外: diff={o['hi_minus_lo']}  CI={o['hi_minus_lo_ci']}")
        print(f"严格序(>40>30-35>25-30): {payload['strict_ok']}  判定: {payload['verdict']}")

    return _emit_results(claim, out_dir, payload, _print_depth)


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

    # 事件计数型引擎（#3/#5/#6，契约见 000-claims-def.md，engine 名见各 run_ 函数 docstring）
    event_engines = {3: run_annual_line_noise,
                     5: run_shanghai_symmetry,
                     6: run_annual_line_hold,
                     9: run_volume_pullback,
                     10: run_breakout_volume,
                     2: run_annual_line_filter_mdd,
                     21: run_rule2638,
                     22: run_annual_line_reduce,
                     23: run_qiancang_rollover,
                     27: run_time_stop,
                     24: run_rollover_bull,
                     35: run_diversification_curve,
                     37: run_kelly_fraction,
                     36: run_core_satellite,
                     38: run_cash_buffer,
                     41: run_sector_concentration,
                     11: run_vix_panic_buy,
                     32: run_dividend_vs_rf,
                     12: run_vix_depth}
    eid = int(claim["id"])
    if eid in event_engines:
        out_dir = args.out or os.path.join(BASE, "research", "110-strategy-verification",
                                           claim.get("folder", f"claim-{eid}"),
                                           f"RETEST-{datetime.now().strftime('%Y-%m-%d')}")
        return event_engines[eid](claim, out_dir)

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
