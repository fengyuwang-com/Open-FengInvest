#!/usr/bin/env python3
"""verify-011-vix-panic-buy.py — 论断 #11: VIX>30 恐慌期买入跑赢平静期

测试方法:
  1. 获取 VIX 和 SPX (S&P 500) 的日线数据, 按日期对齐
  2. 定义信号:
     - 恐慌: VIX 收盘价 > 30
     - 平静: VIX 收盘价 < 20
  3. 对每个信号日, 计算 SPX 后续 1/3/6/12 个月的收益率
  4. 对比恐慌期与平静期的平均收益率

用法:
    python research/110-strategy-verification/011-vix-panic-buy/verify-011-vix-panic-buy.py
"""
import sys, os, json, sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, BASE)

DB_PATH = os.path.join(BASE, "data", "market_data.db")

VIX_INDEX_ID = 17
SPX_INDEX_ID = 1

LOOKAHEAD_TRADING_DAYS = [21, 63, 126, 252]
LOOKAHEAD_LABELS = {21: "1M", 63: "3M", 126: "6M", 252: "12M"}

PANIC_THRESHOLD = 30.0
CALM_THRESHOLD = 20.0

# Additional VIX thresholds for robustness checks
HIGH_PANIC_THRESHOLD = 35.0
EXTREME_PANIC_THRESHOLD = 40.0


def load_aligned_data():
    """Load VIX and SPX daily data aligned by date.

    Returns: list of (date_str, vix_close, spx_close)
    """
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT v.date, v.close, s.close
        FROM daily_data v
        JOIN daily_data s ON v.date = s.date
        WHERE v.index_id=? AND s.index_id=?
          AND v.close IS NOT NULL AND s.close IS NOT NULL
        ORDER BY v.date
    """, (VIX_INDEX_ID, SPX_INDEX_ID)).fetchall()
    conn.close()

    # Convert to tuples of (str, float, float)
    return [(r[0], float(r[1]), float(r[2])) for r in rows]


def compute_forward_returns(data):
    """For each signal day, compute SPX forward returns at various horizons.

    Returns:
        panic_ret: dict {days: [list of forward returns]}
        calm_ret:  dict {days: [list of forward returns]}
        panic_info: dict {days: [(date, entry_spx, forward_spx, ret)]}
        calm_info:  dict {days: [(date, entry_spx, forward_spx, ret)]}
    """
    n = len(data)
    panic_ret = {d: [] for d in LOOKAHEAD_TRADING_DAYS}
    calm_ret = {d: [] for d in LOOKAHEAD_TRADING_DAYS}
    panic_info = {d: [] for d in LOOKAHEAD_TRADING_DAYS}
    calm_info = {d: [] for d in LOOKAHEAD_TRADING_DAYS}

    # Also track higher VIX thresholds
    high_panic_ret = {d: [] for d in LOOKAHEAD_TRADING_DAYS}
    extreme_panic_ret = {d: [] for d in LOOKAHEAD_TRADING_DAYS}

    for i in range(n):
        date = data[i][0]
        vix = data[i][1]
        spx = data[i][2]

        is_panic = vix > PANIC_THRESHOLD
        is_calm = vix < CALM_THRESHOLD
        is_high_panic = vix > HIGH_PANIC_THRESHOLD
        is_extreme_panic = vix > EXTREME_PANIC_THRESHOLD

        if not is_panic and not is_calm:
            continue

        for days in LOOKAHEAD_TRADING_DAYS:
            j = i + days
            if j >= n:
                continue
            future_spx = data[j][2]
            if future_spx is None:
                continue
            ret = (future_spx - spx) / spx

            if is_calm:
                calm_ret[days].append(ret)
                calm_info[days].append((date, spx, future_spx, ret))

            if is_panic:
                panic_ret[days].append(ret)
                panic_info[days].append((date, spx, future_spx, ret))

            if is_high_panic:
                high_panic_ret[days].append(ret)

            if is_extreme_panic:
                extreme_panic_ret[days].append(ret)

    return panic_ret, calm_ret, panic_info, calm_info, high_panic_ret, extreme_panic_ret


def summarize_returns(ret_dict, label):
    """Compute summary stats for a return series."""
    if not ret_dict:
        return {
            "label": label,
            "count": 0,
            "avg_return": None,
            "median_return": None,
            "win_rate": None,
            "std_return": None,
            "min_return": None,
            "max_return": None,
        }

    sorted_ret = sorted(ret_dict)
    n = len(sorted_ret)
    mid = n // 2
    median = sorted_ret[mid] if n % 2 else (sorted_ret[mid - 1] + sorted_ret[mid]) / 2
    avg = sum(sorted_ret) / n
    win_rate = sum(1 for r in sorted_ret if r > 0) / n

    variance = sum((r - avg) ** 2 for r in sorted_ret) / n
    std = variance ** 0.5

    return {
        "label": label,
        "count": n,
        "avg_return": round(avg, 6),
        "median_return": round(median, 6),
        "win_rate": round(win_rate, 4),
        "std_return": round(std, 6),
        "min_return": round(sorted_ret[0], 6),
        "max_return": round(sorted_ret[-1], 6),
    }


def run_backtest():
    """主回测逻辑"""
    print("Loading VIX/SPX aligned data...")
    data = load_aligned_data()
    print(f"Loaded {len(data)} trading days ({data[0][0]} to {data[-1][0]})")

    panic_ret, calm_ret, panic_info, calm_info, high_panic_ret, extreme_panic_ret = compute_forward_returns(data)

    # Count signal days
    panic_days = len(panic_ret[21])  # use 1M horizon count as reference
    calm_days = len(calm_ret[21])
    high_panic_days = len(high_panic_ret[21])
    extreme_panic_days = len(extreme_panic_ret[21])
    total_days = len(data)
    vix_values = [d[1] for d in data]

    print(f"VIX>30 (panic) days: {panic_days}")
    print(f"VIX<20 (calm) days: {calm_days}")
    print(f"VIX>35 (high panic) days: {high_panic_days}")
    print(f"VIX>40 (extreme panic) days: {extreme_panic_days}")

    # Build results per horizon
    horizon_results = {}
    for days in LOOKAHEAD_TRADING_DAYS:
        label = LOOKAHEAD_LABELS[days]

        p_summary = summarize_returns(panic_ret[days], "panic")
        c_summary = summarize_returns(calm_ret[days], "calm")
        hp_summary = summarize_returns(high_panic_ret[days], "high_panic")
        ep_summary = summarize_returns(extreme_panic_ret[days], "extreme_panic")

        claim_supported = (
            p_summary["avg_return"] is not None
            and c_summary["avg_return"] is not None
            and p_summary["avg_return"] > c_summary["avg_return"]
        )

        # Additional: what fraction of panic signals beat the average calm return?
        if c_summary["avg_return"] is not None and c_summary["avg_return"] != 0:
            panic_beat_avg_calm = sum(1 for r in panic_ret[days] if r > c_summary["avg_return"])
            panic_beat_avg_calm_pct = panic_beat_avg_calm / len(panic_ret[days]) if panic_ret[days] else 0
        else:
            panic_beat_avg_calm_pct = None

        horizon_results[label] = {
            "lookahead_days": days,
            "panic": p_summary,
            "calm": c_summary,
            "high_panic_vix35": hp_summary,
            "extreme_panic_vix40": ep_summary,
            "panic_outperforms_calm_by": round(
                (p_summary["avg_return"] - c_summary["avg_return"])
                if p_summary["avg_return"] is not None and c_summary["avg_return"] is not None
                else 0, 6
            ),
            "panic_beat_calm_avg_pct": round(panic_beat_avg_calm_pct, 4) if panic_beat_avg_calm_pct is not None else None,
            "claim_supported": claim_supported,
        }

    # VIX percentile summary
    sorted_vix = sorted(vix_values)
    n_vix = len(sorted_vix)
    percentiles = {
        "min": round(min(vix_values), 2),
        "p25": round(sorted_vix[n_vix // 4], 2),
        "p50": round(sorted_vix[n_vix // 2], 2),
        "p75": round(sorted_vix[3 * n_vix // 4], 2),
        "p90": round(sorted_vix[9 * n_vix // 10], 2),
        "p95": round(sorted_vix[19 * n_vix // 20], 2),
        "max": round(max(vix_values), 2),
        "mean": round(sum(sorted_vix) / n_vix, 2),
    }

    results = {
        "claim": "#11 - VIX>30 恐慌期买入跑赢平静期",
        "data_range": {"from": data[0][0], "to": data[-1][0]},
        "total_trading_days": total_days,
        "vix_percentiles": percentiles,
        "signal_counts": {
            "panic_vix_over_30": panic_days,
            "calm_vix_under_20": calm_days,
            "high_panic_vix_over_35": high_panic_days,
            "extreme_panic_vix_over_40": extreme_panic_days,
        },
        "horizon_results": horizon_results,
        "summary": (
            "如果恐慌期(VIX>30)买入的平均收益高于平静期(VIX<20), "
            "则论断成立: VIX>30恐慌时买入确实跑赢平静期买入."
        ),
    }

    # Overall claim: supported in at least 3 out of 4 horizons
    support_count = sum(1 for h in horizon_results.values() if h["claim_supported"])
    results["overall_claim_supported_count"] = support_count
    results["overall_claim_supported"] = support_count >= 3

    return results


if __name__ == "__main__":
    results = run_backtest()

    # Write results
    out_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # Print readable summary
    print()
    print("=" * 60)
    print(f"论断 #11: VIX>30 恐慌期买入跑赢平静期")
    print(f"数据范围: {results['data_range']['from']} ~ {results['data_range']['to']}")
    print(f"总交易日: {results['total_trading_days']}")
    print(f"VIX 分布: P50={results['vix_percentiles']['p50']}, P75={results['vix_percentiles']['p75']}, P90={results['vix_percentiles']['p90']}")
    print()
    print(f"信号天数: 恐慌(VIX>30)={results['signal_counts']['panic_vix_over_30']}, "
          f"平静(VIX<20)={results['signal_counts']['calm_vix_under_20']}")
    print()
    print(f"{'持有期':>6} | {'恐慌均收益':>10} | {'平静均收益':>10} | {'差值':>10} | {'恐慌胜率':>8} | {'平静胜率':>8} | {'支持?':>4}")
    print("-" * 70)
    for label, h in results["horizon_results"].items():
        p = h["panic"]
        c = h["calm"]
        check = "YES" if h["claim_supported"] else "NO"
        print(f"{label:>6} | {p['avg_return']:>+9.4%} | {c['avg_return']:>+9.4%} | "
              f"{h['panic_outperforms_calm_by']:>+9.4%} | {p['win_rate']:>7.1%} | {c['win_rate']:>7.1%} | {check:>4}")
    print()
    print(f"VIX>35 高恐慌 vs VIX<20 平静:")
    for label, h in results["horizon_results"].items():
        hp = h["high_panic_vix35"]
        c = h["calm"]
        if hp["avg_return"] is not None:
            print(f"  {label}: VIX>35 avg={hp['avg_return']:+>9.4%} vs calm avg={c['avg_return']:+>9.4%}")

    sup_count = results["overall_claim_supported_count"]
    verdict = "✅ SUPPORT" if results["overall_claim_supported"] else "❌ REJECT"
    print()
    print(f"结论: {verdict}")
    print(f"(四个持有期中 {sup_count}/4 个恐慌收益 > 平静收益)")

    print()
    print(json.dumps(results, indent=2, ensure_ascii=False))
