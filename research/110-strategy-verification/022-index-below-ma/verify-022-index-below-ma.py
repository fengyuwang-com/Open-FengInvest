#!/usr/bin/env python3
"""verify-022-index-below-ma.py — 论断 #22: 大盘低于年线时降仓位至<30%，比不降仓位的组合在短期内回撤低

H0: Not reducing position has no additional risk.

测试方法:
  1. 对每个市场找到主要指数 (US=^GSPC, CN=000001.SS, HK=^HSI)
  2. 计算 200 日均线 (MA)
  3. 对每个收盘价 < 200MA 的信号日:
     - A: 降至 30% 仓位 (70% 现金)
     - B: 保持 100% 仓位
     - 向前追踪 20/63/126 个交易日的最⼤回撤
  4. 比较 A/B 的平均最⼤回撤

用法:
    python research/110-strategy-verification/022-index-below-ma/verify-022-index-below-ma.py
    python research/110-strategy-verification/022-index-below-ma/verify-022-index-below-ma.py --all-markets
"""
import sys
import os
import json
import sqlite3
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, BASE)

DB_PATH = os.path.join(BASE, "data", "market_data.db")

# Major indices for each market — IDs verified from the indices table
MARKET_INDICES = {
    "US": {"index_id": 1, "ticker": "^GSPC", "name": "S&P 500"},
    "CN": {"index_id": 26, "ticker": "000001.SS", "name": "上证指数"},
    "HK": {"index_id": 23, "ticker": "^HSI", "name": "恒生指数"},
}

LOOKAHEAD_DAYS = [20, 63, 126]  # ~1 month, ~3 months, ~6 months

# Portfolio A fraction kept in stocks when below MA
REDUCED_FRACTION = 0.30


def get_close_prices(index_id):
    """获取指定指数的全部收盘价, 按⽇期升序排列。

    Returns: list of (date_str, close_float)
    """
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT date, close FROM daily_data WHERE index_id=? "
        "AND close IS NOT NULL ORDER BY date",
        (index_id,),
    ).fetchall()
    conn.close()
    # Convert to tuple of (str, float) for clarity
    return [(r[0], float(r[1])) for r in rows]


def compute_signals(data):
    """对收盘价序列计算 200MA, 返回信号列表和价格序列。

    data: list of (date_str, close_float)
    Returns:
        closes: list of close prices (float)
        signals: list of int indices into closes where close < MA200

    第⼀个有效 MA200 从第 200 个数据点 (0-indexed index=199) 开始。
    """
    closes = [d[1] for d in data]
    n = len(closes)
    if n < 200:
        return closes, []

    signals = []
    for i in range(199, n):
        # MA200: 当前天及前 199 天, 共 200 个数据点
        ma = sum(closes[i - 199:i + 1]) / 200.0
        if closes[i] < ma:
            signals.append(i)
    return closes, signals


def max_drawdown(values):
    """计算⼀个标准化后的组合价值序列的最⼤回撤。

    values[0] 应 == 1.0 (信号⽇标准化价值).
    Returns: float, 最⼤回撤 (0.0 ~ 1.0)
    """
    peak = values[0]
    max_dd = 0.0
    for v in values[1:]:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd
    return max_dd


def run_single_market(market_key):
    """对⼀个市场执⾏回测, 返回结果 dict."""
    meta = MARKET_INDICES[market_key]
    index_id = meta["index_id"]

    data = get_close_prices(index_id)
    if not data:
        return None
    closes, signals = compute_signals(data)
    n = len(closes)

    # 对每个 lookahead window 收集 A/B 最⼤回撤
    lookahead_dds = {days: {"A": [], "B": []} for days in LOOKAHEAD_DAYS}

    for sig_idx in signals:
        for days in LOOKAHEAD_DAYS:
            end_idx = sig_idx + days + 1  # +1 因为含信号⽇
            if end_idx > n:
                # 信号太靠后, 没有⾜够的 forward 数据
                continue
            # 信号⽇收盘价
            p_signal = closes[sig_idx]

            # Portfolio B: 100% 持股
            b_values = [1.0]  # 信号⽇标准化到 1.0
            for j in range(1, days + 1):
                p_future = closes[sig_idx + j]
                b_values.append(p_future / p_signal)

            # Portfolio A: 30% 持股 + 70% 现⾦
            a_values = [1.0]
            for j in range(1, days + 1):
                p_future = closes[sig_idx + j]
                a_values.append(REDUCED_FRACTION * p_future / p_signal
                                + (1.0 - REDUCED_FRACTION))

            dd_a = max_drawdown(a_values)
            dd_b = max_drawdown(b_values)
            lookahead_dds[days]["A"].append(dd_a)
            lookahead_dds[days]["B"].append(dd_b)

    # 汇总结果
    result = {
        "market": market_key,
        "index": meta["ticker"],
        "name": meta["name"],
        "signal_count": len(signals),
    }
    for days in LOOKAHEAD_DAYS:
        dd_a_list = lookahead_dds[days]["A"]
        dd_b_list = lookahead_dds[days]["B"]
        n_signals = len(dd_a_list)

        if n_signals == 0:
            result[f"lookahead_{days}"] = {
                "signal_count": 0,
                "drawdown_A_avg": None,
                "drawdown_B_avg": None,
                "reduction_pct": None,
                "claim_supported": None,
            }
            continue

        avg_a = sum(dd_a_list) / n_signals
        avg_b = sum(dd_b_list) / n_signals
        reduction_pct = ((avg_b - avg_a) / avg_b * 100.0) if avg_b > 0 else 0.0

        result[f"lookahead_{days}"] = {
            "signal_count": n_signals,
            "drawdown_A_avg": round(avg_a, 6),
            "drawdown_B_avg": round(avg_b, 6),
            "reduction_pct": round(reduction_pct, 2),
            "claim_supported": avg_a < avg_b,
        }

    return result


def run_backtest(markets=None):
    """主回测逻辑。

    Args:
        markets: list of market keys, e.g. ["US", "CN", "HK"].
                 默认只跑 "US".
    Returns: dict {market_key: result_dict}
    """
    if markets is None:
        markets = ["US"]
    results = {}
    for m in markets:
        print(f"Processing {m}...", file=sys.stderr)
        res = run_single_market(m)
        if res is None:
            print(f"  WARNING: No data for {m}, skipping.", file=sys.stderr)
            continue
        results[m] = res
    return results


if __name__ == "__main__":
    if "--all-markets" in sys.argv:
        markets = list(MARKET_INDICES.keys())
    else:
        markets = ["US"]

    results = run_backtest(markets)
    print(json.dumps(results, indent=2, ensure_ascii=False))
