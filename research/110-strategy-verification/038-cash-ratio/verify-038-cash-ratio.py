#!/usr/bin/env python3
"""verify-038-cash-ratio.py — 论断 #38: 现金比例<10%在股灾中失去抄底能力

论断原文:
  "Cash ratio <10% in a portfolio loses ability to buy the dip in market
   crashes, underperforming a portfolio that keeps 15% cash"

测试方法:
  取 SP500 四次重大危机，向前看 3 年，比较三种组合：

  组合 A — 0% 现金，100% 持仓，买持有不动           （<10%现金的代表）
  组合 B — 15% 现金，85% 持仓，每月再平衡到 85/15    （15%现金的代表）
  组合 C — 5% 现金，95% 持仓，当SP500从峰值回撤>20%
           时全仓杀入，反弹后重建 5% 现金             （动态现金管理）

用法:
  python research/110-strategy-verification/038-cash-ratio/verify-038-cash-ratio.py
"""
import sys
import os
import json
import sqlite3
import time
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, BASE)

DB_PATH = os.path.join(BASE, "data", "market_data.db")
TODAY = "2026-07-23"

SP500_ID = 1
TRADING_DAYS_YEAR = 252
FORWARD_YEARS = 3

CRASHES = [
    {"name": "2008 GFC",                "start": "2008-01-02"},
    {"name": "2015 China Crash",        "start": "2015-07-01"},
    {"name": "2020 COVID",              "start": "2020-02-01"},
    {"name": "2022 Bear Market",        "start": "2022-01-03"},
]

A_LABEL = "0%现金(100%买持有)"
B_LABEL = "15%现金(85/15月再平衡)"
C_LABEL = "5%现金(动态抄底)"


# ── 数据加载 ──

def load_sp500_prices(conn):
    """Return list of (date_str, close) for SP500 index."""
    rows = conn.execute(
        "SELECT date, close FROM daily_data "
        "WHERE index_id=? AND close>0 ORDER BY date",
        (SP500_ID,)
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def find_idx(prices, target_date):
    """First index with date >= target_date (clamped to last)."""
    for i, (d, _) in enumerate(prices):
        if d >= target_date:
            return i
    return len(prices) - 1


def end_date_3yr(start_str):
    dt = datetime.strptime(start_str, "%Y-%m-%d")
    return dt.replace(year=dt.year + FORWARD_YEARS).strftime("%Y-%m-%d")


# ── 组合模拟 ──

def simulate_a(prices):
    """组合 A: 100% 持仓, 0% 现金, 买持有不动."""
    start_price = prices[0][1]
    return [p / start_price for _, p in prices]


def simulate_b(prices):
    """组合 B: 85% 股票 + 15% 现金, 每月末再平衡回 85/15.

    现金部分不产生收益(0%)，再平衡时卖出上涨部分、买入下跌部分。
    在股灾中这种机械再平衡天然等于"抄底"。
    """
    shares = 0.85 / prices[0][1]
    cash = 0.15
    values = []

    for i, (date_str, price) in enumerate(prices):
        stock_val = shares * price
        total = stock_val + cash
        values.append(total)

        # 月再平衡（当下一交易日的月份不同时，在当前日执行）
        if i < len(prices) - 1:
            next_month = prices[i + 1][0][:7]
            if next_month != date_str[:7]:
                shares = (total * 0.85) / price
                cash = total * 0.15

    return values


def simulate_c(prices):
    """组合 C: 95% 股票 + 5% 现金, 急跌(-20%+)时全仓杀入.

    正常时期维持 95/5（月再平衡）。
    当 SP500 从近期峰值回撤 >20% 时：卖出现金，全部买入股票(→100%)。
    当 SP500 回升至距峰值 <5% 时：卖出股票，重建 5% 现金储备(→95/5)。
    核心思想：平时少留现金减少拖累，只在极端行情时动用储备。
    """
    target_stock = 0.95
    target_cash = 0.05

    shares = target_stock / prices[0][1]
    cash = target_cash

    sp500_peak = prices[0][1]
    deployed = False          # 是否已触发抄底
    values = []

    for i, (date_str, price) in enumerate(prices):
        # 追踪 SP500 峰值
        if price > sp500_peak:
            sp500_peak = price

        sp500_dd = (sp500_peak - price) / sp500_peak

        stock_val = shares * price
        total = stock_val + cash
        values.append(total)

        # ── 抄底触发：SP500 从峰值下跌 >20% ──
        if sp500_dd > 0.20 and not deployed:
            shares += cash / price   # 全部现金买入
            cash = 0.0
            deployed = True
            target_stock = 1.0
            target_cash = 0.0

        # ── 反弹恢复：SP500 回到峰值的 5% 以内 ──
        if deployed and sp500_dd < 0.05:
            deployed = False
            target_stock = 0.95
            target_cash = 0.05
            sp500_peak = price           # 重置峰值基线
            total = stock_val + cash
            shares = (total * target_stock) / price
            cash = total * target_cash

        # ── 月再平衡（使用当前目标配比）──
        if i < len(prices) - 1:
            next_month = prices[i + 1][0][:7]
            if next_month != date_str[:7]:
                total = stock_val + cash
                shares = (total * target_stock) / price
                cash = total * target_cash

    return values


# ── 计算指标 ──

def compute_metrics(values, n_days):
    """Return final_value, CAGR, and max_drawdown from a value series."""
    if n_days < 2 or values[0] <= 0:
        return {"final_value": 0, "cagr": 0, "mdd": 0}

    years = n_days / TRADING_DAYS_YEAR
    final_val = values[-1]
    cagr = (final_val) ** (1.0 / years) - 1 if years > 0 else 0

    peak = values[0]
    mdd = 0.0
    for v in values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        mdd = max(mdd, dd)

    return {
        "final_value": round(final_val, 4),
        "cagr": round(cagr, 4),
        "mdd": round(mdd, 4),
    }


def sp500_drawdown_info(prices, si, ei):
    """Return dict of SP500 peak/trough/drawdown within [si, ei]."""
    peak = running_peak = prices[si][1]
    trough = prices[si][1]
    running_peak_date = peak_date = prices[si][0]
    trough_date = prices[si][0]
    max_dd = 0.0

    for i in range(si, ei + 1):
        d, p = prices[i]
        if p > running_peak:
            running_peak = p
            running_peak_date = d
        dd = (running_peak - p) / running_peak
        if dd > max_dd:
            max_dd = dd
            peak = running_peak
            peak_date = running_peak_date
            trough = p
            trough_date = d

    return {
        "sp500_start":       round(prices[si][1], 2),
        "sp500_end":         round(prices[ei][1], 2),
        "sp500_peak":        round(peak, 2),
        "sp500_peak_date":   peak_date,
        "sp500_trough":      round(trough, 2),
        "sp500_trough_date": trough_date,
        "sp500_max_drawdown":  round(max_dd, 4),
        "sp500_period_return": round((prices[ei][1] - prices[si][1]) / prices[si][1], 4),
    }


# ── 主回测 ──

def run_backtest():
    conn = sqlite3.connect(DB_PATH)
    all_prices = load_sp500_prices(conn)
    conn.close()

    print(f"SP500 数据: {len(all_prices)} 日线, "
          f"{all_prices[0][0]} ~ {all_prices[-1][0]}")

    results = {}

    for crash in CRASHES:
        name = crash["name"]
        start_str = crash["start"]
        end_str = end_date_3yr(start_str)

        si = find_idx(all_prices, start_str)
        ei = find_idx(all_prices, end_str)
        if ei >= len(all_prices):
            ei = len(all_prices) - 1

        period = all_prices[si:ei + 1]
        n_days = len(period)
        years = n_days / TRADING_DAYS_YEAR

        print(f"\n{'=' * 60}")
        print(f"  {name}")
        print(f"  期间: {period[0][0]} ~ {period[-1][0]}  "
              f"({n_days} 交易日, {years:.1f} 年)")

        # SP500 背景
        dd_info = sp500_drawdown_info(all_prices, si, ei)
        print(f"  SP500: 最大回撤 {dd_info['sp500_max_drawdown']:.1%} "
              f"({dd_info['sp500_peak_date']}→{dd_info['sp500_trough_date']})")

        # 三种组合
        pa_vals = simulate_a(period)
        pb_vals = simulate_b(period)
        pc_vals = simulate_c(period)

        pa_m = compute_metrics(pa_vals, n_days)
        pb_m = compute_metrics(pb_vals, n_days)
        pc_m = compute_metrics(pc_vals, n_days)

        diff_ba = pb_m["cagr"] - pa_m["cagr"]
        diff_cb = pc_m["cagr"] - pb_m["cagr"]

        print(f"  {A_LABEL}: 终值={pa_m['final_value']:.4f}, "
              f"CAGR={pa_m['cagr']:.2%}, MDD={pa_m['mdd']:.1%}")
        print(f"  {B_LABEL}: 终值={pb_m['final_value']:.4f}, "
              f"CAGR={pb_m['cagr']:.2%}, MDD={pb_m['mdd']:.1%}")
        print(f"  {C_LABEL}: 终值={pc_m['final_value']:.4f}, "
              f"CAGR={pc_m['cagr']:.2%}, MDD={pc_m['mdd']:.1%}")
        print(f"  增量: B-A={diff_ba:+.2%}, C-B={diff_cb:+.2%}")

        results[name] = {
            "start_date": period[0][0],
            "end_date": period[-1][0],
            "trading_days": n_days,
            "years": round(years, 2),
            "sp500": dd_info,
            "portfolio_A": {"label": A_LABEL, **pa_m},
            "portfolio_B": {"label": B_LABEL, **pb_m},
            "portfolio_C": {"label": C_LABEL, **pc_m},
            "analysis": {
                "B优于A": diff_ba > 0,
                "C优于B": diff_cb > 0,
                "B_vs_A_CAGR_diff": round(diff_ba, 4),
                "C_vs_B_CAGR_diff": round(diff_cb, 4),
                "B_vs_A_MDD_diff": round(pa_m["mdd"] - pb_m["mdd"], 4),
                "C_vs_B_MDD_diff": round(pb_m["mdd"] - pc_m["mdd"], 4),
            },
        }

    return results


def build_conclusion(results):
    n = len(results)

    b_beats_a = sum(1 for r in results.values() if r["analysis"]["B优于A"])
    c_beats_b = sum(1 for r in results.values() if r["analysis"]["C优于B"])

    avg_ba = sum(r["analysis"]["B_vs_A_CAGR_diff"] for r in results.values()) / n
    avg_cb = sum(r["analysis"]["C_vs_B_CAGR_diff"] for r in results.values()) / n

    avg_a_cagr = sum(r["portfolio_A"]["cagr"] for r in results.values()) / n
    avg_b_cagr = sum(r["portfolio_B"]["cagr"] for r in results.values()) / n
    avg_c_cagr = sum(r["portfolio_C"]["cagr"] for r in results.values()) / n

    # 谁的均值最高
    best_map = {0: "A (0%现金买持有)", 1: "B (15%现金再平衡)", 2: "C (5%动态抄底)"}
    best_idx = max(range(3), key=lambda i: [avg_a_cagr, avg_b_cagr, avg_c_cagr][i])

    summary = (
        f"15%现金组合(B)在 {b_beats_a}/{n} 次危机中 CAGR 跑赢纯持仓(A)，"
        f"平均超额 {avg_ba:+.2%}；"
        f"动态现金组合(C)在 {c_beats_b}/{n} 次危机中 CAGR 跑赢固定现金组合(B)，"
        f"平均超额 {avg_cb:+.2%}。"
        f"三组合平均 CAGR: A={avg_a_cagr:.2%}, B={avg_b_cagr:.2%}, C={avg_c_cagr:.2%}。"
        f"整体最优: {best_map[best_idx]}。"
    )

    return {
        "summary": summary,
        "B优于A次数": f"{b_beats_a}/{n}",
        "C优于B次数": f"{c_beats_b}/{n}",
        "平均BvsA超额CAGR": round(avg_ba, 4),
        "平均CvsB超额CAGR": round(avg_cb, 4),
        "平均A_CAGR": round(avg_a_cagr, 4),
        "平均B_CAGR": round(avg_b_cagr, 4),
        "平均C_CAGR": round(avg_c_cagr, 4),
        "整体最佳策略": best_map[best_idx],
        "论断支持(15%现金优于0%现金)": b_beats_a > n / 2,
    }


# ── 入口 ──

if __name__ == "__main__":
    t0 = time.time()
    crash_results = run_backtest()
    conclusion = build_conclusion(crash_results)

    output = {
        "test_date": TODAY,
        "claim_id": 38,
        "claim": "现金比例<10%在股灾中失去抄底能力，跑输保持15%现金的组合",
        "claim_en": "Cash ratio <10% loses ability to buy the dip in market crashes, "
                    "underperforming a portfolio that keeps 15% cash",
        "methodology": {
            "description": "取 SP500 四次重大危机，向前看3年，比较三种组合的 CAGR 和最大回撤",
            "portfolio_A": "0%现金，100%持仓，买持有不动",
            "portfolio_B": "15%现金，85%持仓，每月末再平衡回 85/15",
            "portfolio_C": "5%现金，95%持仓，SP500从峰值回撤>20%时全仓杀入，"
                           "反弹至峰值5%以内时重建5%现金",
            "cash_assumption": "现金部分不产生收益(年化0%)",
        },
        "crash_periods": crash_results,
        "conclusion": conclusion,
    }

    elapsed = time.time() - t0
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n{'=' * 60}")
    print(conclusion["summary"])
    print(f"\n结果已保存: {out_path}")
    print(f"耗时: {elapsed:.0f}s")
