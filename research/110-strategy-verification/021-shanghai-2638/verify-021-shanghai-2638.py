#!/usr/bin/env python3
"""verify-021-shanghai-2638.py — 论断 #21: 上证指数<2638 时仓位≤30%, 比不控制的组合在6个月内回撤低>30%

H0: Position control does not reduce drawdown.

逻辑:
  对每个收盘 <2638 的交易日（信号日）:
    组合 A: 信号日起 30% 仓位（70% 现金），跟踪其后 126 个交易日的回撤
    组合 B: 信号日起 100% 仓位，跟踪其后 126 个交易日的回撤
  比较两者的最大回撤，预期 A 的回撤比 B 低 >30%。

用法:
    python research/110-strategy-verification/021-shanghai-2638/verify-021-shanghai-2638.py
    python research/110-strategy-verification/021-shanghai-2638/verify-021-shanghai-2638.py --all-markets
"""
import sys
import os
import json
import sqlite3
import argparse
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, BASE)

DB_PATH = os.path.join(BASE, "data", "market_data.db")

# 参数常量
FORWARD_DAYS = 126          # 约 6 个交易月
THRESHOLD = 2638.0          # 上证指数阈值
CONTROL_POSITION = 0.30     # 控制组合仓位 30%
FULL_POSITION = 1.00        # 全仓 100%
REDUCTION_THRESHOLD = 0.30  # 论断声称回撤降低 >30%


def get_index_id(market="CN"):
    """查找上证指数在 indices 表中的 id。"""
    conn = sqlite3.connect(DB_PATH)
    candidates = ("000001.SS", "000001.SH", "SH000001", "SSEC")
    row = None
    for ticker in candidates:
        row = conn.execute(
            "SELECT id, ticker, name FROM indices WHERE ticker=? AND category='index'",
            (ticker,)
        ).fetchone()
        if row:
            break
    # 如果 ticker 没找到，按 market + '上证' 特征查
    if not row:
        rows = conn.execute(
            "SELECT id, ticker, name FROM indices WHERE market=? AND category='index'",
            (market,)
        ).fetchall()
        # 第一条通常就是上证指数
        if rows:
            row = rows[0]
    conn.close()
    return row


def load_daily_prices(index_id):
    """加载指定指数全部收盘价，按日期升序。"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT date, close FROM daily_data WHERE index_id=? ORDER BY date",
        (index_id,)
    ).fetchall()
    conn.close()
    return rows  # [(date_str, close), ...]


def max_drawdown(nav_values):
    """计算 NAV 序列的最大回撤，返回正数（百分比小数）。
    例如 0.25 表示从峰值下跌了 25%。"""
    if len(nav_values) < 2:
        return 0.0
    peak = nav_values[0]
    max_dd = 0.0
    for v in nav_values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak
        if dd > max_dd:
            max_dd = dd
    return max_dd


def simulate_window(signal_close, forward_prices):
    """在 forward_prices（信号日后 FORWARD_DAYS 个收盘价）上计算两组合回撤。

    组合 A: 30% 仓位 → NAV(t) = 0.3 * (P_t / P_0) + 0.7
    组合 B: 100% 仓位 → NAV(t) = P_t / P_0

    返回 (dd_A, dd_B)，均为正数小数。
    """
    if len(forward_prices) < FORWARD_DAYS:
        return None, None

    nav_a = []
    nav_b = []
    for price in forward_prices[:FORWARD_DAYS]:
        ret = price / signal_close           # 累积收益比
        nav_b.append(ret)                    # 100% 仓位
        nav_a.append(CONTROL_POSITION * ret + (1.0 - CONTROL_POSITION))  # 30% 仓位

    return max_drawdown(nav_a), max_drawdown(nav_b)


def run_backtest(market="CN"):
    """主回测入口。"""
    index_info = get_index_id(market)
    if not index_info:
        print(f"错误: 未找到市场 {market} 的指数数据")
        return {"error": f"Index not found for market={market}"}

    idx_id, ticker, name = index_info
    print(f"指数: {ticker} (id={idx_id})")

    daily_data = load_daily_prices(idx_id)
    print(f"总记录数: {len(daily_data)}")

    # 第一步：定位信号日（收盘 < 2638）
    signal_indices = []
    for i, (dstr, close) in enumerate(daily_data):
        if close < THRESHOLD:
            signal_indices.append(i)

    total_signals = len(signal_indices)
    print(f"信号日 (close < {THRESHOLD}): {total_signals}")

    if total_signals == 0:
        return {
            "signal_count": 0,
            "avg_drawdown_A": 0,
            "avg_drawdown_B": 0,
            "reduction_pct": 0,
            "claim_supported": False,
            "note": "无信号日",
        }

    # 第二步：逐信号计算
    acc = defaultdict(list)  # dates, dd_A, dd_B, reductions

    for idx in signal_indices:
        # 确保有足够的前向数据
        end_idx = idx + 1 + FORWARD_DAYS
        if end_idx > len(daily_data):
            continue

        date_str = daily_data[idx][0]
        signal_close = daily_data[idx][1]
        forward_prices = [daily_data[j][1] for j in range(idx + 1, end_idx)]

        dd_a, dd_b = simulate_window(signal_close, forward_prices)
        if dd_a is None or dd_b is None:
            continue

        acc["dates"].append(date_str)
        acc["dd_A"].append(dd_a)
        acc["dd_B"].append(dd_b)

        if dd_b > 1e-10:
            reduction = (dd_b - dd_a) / dd_b
        else:
            reduction = 0.0
        acc["reductions"].append(reduction)

    count = len(acc["dates"])
    print(f"有效信号（有足够前向数据）: {count}")

    if count == 0:
        return {
            "signal_count": 0,
            "avg_drawdown_A": 0,
            "avg_drawdown_B": 0,
            "reduction_pct": 0,
            "claim_supported": False,
            "note": "无信号具有足够的前向数据",
        }

    avg_dd_a = sum(acc["dd_A"]) / count
    avg_dd_b = sum(acc["dd_B"]) / count
    avg_reduction = sum(acc["reductions"]) / count

    claim_supported = avg_reduction > REDUCTION_THRESHOLD

    results = {
        "claim_id": 21,
        "claim": "上证指数<2638时仓位≤30%, 比不控制的组合在6个月内回撤低>30%",
        "h0": "Position control does not reduce drawdown",
        "market": market,
        "index_ticker": ticker,
        "threshold": THRESHOLD,
        "forward_days": FORWARD_DAYS,
        "signal_count": count,
        "total_signal_days": total_signals,
        "avg_drawdown_A_pct": round(avg_dd_a * 100, 2),
        "avg_drawdown_B_pct": round(avg_dd_b * 100, 2),
        "reduction_pct": round(avg_reduction * 100, 2),
        "claim_supported": claim_supported,
    }

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="论断 #21: 上证 2638 阈值回测")
    parser.add_argument(
        "--all-markets",
        action="store_true",
        help="接受 --all-markets 参数，但仅测试 CN（上证指数特有）",
    )
    args = parser.parse_args()

    market = "CN"
    if args.all_markets:
        print("--all-markets 已传入，但此论断仅针对上证指数，仅测试 CN 市场。\n")

    results = run_backtest(market=market)

    print("\n" + "=" * 50)
    print(json.dumps(results, indent=2, ensure_ascii=False))
    print("=" * 50)

    # 保存结果
    out_dir = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(out_dir, "results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存: {out_path}")
