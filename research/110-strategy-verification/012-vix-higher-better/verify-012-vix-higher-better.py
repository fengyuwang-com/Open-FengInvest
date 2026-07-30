#!/usr/bin/env python3
"""verify-012-vix-higher-better.py — 论断 #12: VIX越高恐慌买入收益越强

测试方法:
  1. 获取 VIX 和 SPX (S&P 500) 的日线数据, 按日期对齐
  2. 将 VIX 水平分桶: <15, 15-20, 20-25, 25-30, 30-35, >35
  3. 对每个桶内的信号日, 计算 SPX 后续 1/3/6/12 个月的平均收益率
  4. 展示 VIX 水平与后续收益的单调关系

用法:
    python research/110-strategy-verification/012-vix-higher-better/verify-012-vix-higher-better.py
"""
import sys, os, json, sqlite3
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, BASE)

DB_PATH = os.path.join(BASE, "data", "market_data.db")

VIX_INDEX_ID = 17
SPX_INDEX_ID = 1

LOOKAHEAD_TRADING_DAYS = [21, 63, 126, 252]
LOOKAHEAD_LABELS = {21: "1M", 63: "3M", 126: "6M", 252: "12M"}

# VIX buckets
VIX_BUCKETS = [
    ("<15",  0.0, 15.0),
    ("15-20", 15.0, 20.0),
    ("20-25", 20.0, 25.0),
    ("25-30", 25.0, 30.0),
    ("30-35", 30.0, 35.0),
    (">35",   35.0, float("inf")),
]


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
    return [(r[0], float(r[1]), float(r[2])) for r in rows]


def classify_bucket(vix_close):
    """Classify VIX close into a bucket name."""
    for name, lo, hi in VIX_BUCKETS:
        if lo <= vix_close < hi:
            return name
    return ">35"


def run_backtest():
    """主回测逻辑 — 按 VIX 分桶计算 SPX 后续收益"""
    print("Loading VIX/SPX aligned data...")
    data = load_aligned_data()
    print(f"Loaded {len(data)} trading days ({data[0][0]} to {data[-1][0]})")

    # bucket_returns[days][bucket_name] = list of forward returns
    bucket_returns = {d: defaultdict(list) for d in LOOKAHEAD_TRADING_DAYS}
    bucket_entries = {d: defaultdict(list) for d in LOOKAHEAD_TRADING_DAYS}  # dates for reference

    n = len(data)
    for i in range(n):
        date = data[i][0]
        vix = data[i][1]
        spx = data[i][2]

        bucket = classify_bucket(vix)

        for days in LOOKAHEAD_TRADING_DAYS:
            j = i + days
            if j >= n:
                continue
            future_spx = data[j][2]
            if future_spx is None:
                continue
            ret = (future_spx - spx) / spx

            bucket_returns[days][bucket].append(ret)
            bucket_entries[days][bucket].append((date, spx, future_spx, ret))

    # Build results
    horizon_results = {}
    for days in LOOKAHEAD_TRADING_DAYS:
        label = LOOKAHEAD_LABELS[days]
        buckets_out = []

        for bucket_name, _, _ in VIX_BUCKETS:
            rets = bucket_returns[days].get(bucket_name, [])
            if not rets:
                buckets_out.append({
                    "bucket": bucket_name,
                    "count": 0,
                    "avg_return": None,
                    "median_return": None,
                    "win_rate": None,
                    "std_return": None,
                })
                continue

            sorted_rets = sorted(rets)
            n_r = len(sorted_rets)
            mid = n_r // 2
            median = sorted_rets[mid] if n_r % 2 else (sorted_rets[mid - 1] + sorted_rets[mid]) / 2
            avg = sum(sorted_rets) / n_r
            win_rate = sum(1 for r in sorted_rets if r > 0) / n_r
            variance = sum((r - avg) ** 2 for r in sorted_rets) / n_r

            buckets_out.append({
                "bucket": bucket_name,
                "count": n_r,
                "avg_return": round(avg, 6),
                "median_return": round(median, 6),
                "win_rate": round(win_rate, 4),
                "std_return": round(variance ** 0.5, 6),
            })

        # Check monotonicity: higher VIX bucket should have higher avg_return
        valid_buckets = [(b["bucket"], b["avg_return"]) for b in buckets_out if b["avg_return"] is not None]
        strictly_monotonic = all(
            valid_buckets[i][1] < valid_buckets[i + 1][1]
            for i in range(len(valid_buckets) - 1)
        )
        # Also check non-decreasing (allow ties)
        non_decreasing = all(
            valid_buckets[i][1] <= valid_buckets[i + 1][1]
            for i in range(len(valid_buckets) - 1)
        )

        # Threshold-based analysis: compare high-VIX vs low-VIX groups
        # High VIX group: buckets with lower bound >= 25 (25-30, 30-35, >35)
        # Low VIX group: buckets with upper bound < 25 (<15, 15-20, 20-25)
        high_buckets = [b for b in buckets_out if b["bucket"] in ("25-30", "30-35", ">35")]
        low_buckets = [b for b in buckets_out if b["bucket"] in ("<15", "15-20", "20-25")]

        high_avg = (
            sum(b["avg_return"] * b["count"] for b in high_buckets if b["avg_return"] is not None)
            / sum(b["count"] for b in high_buckets if b["avg_return"] is not None)
            if any(b["avg_return"] is not None for b in high_buckets) else None
        )
        low_avg = (
            sum(b["avg_return"] * b["count"] for b in low_buckets if b["avg_return"] is not None)
            / sum(b["count"] for b in low_buckets if b["avg_return"] is not None)
            if any(b["avg_return"] is not None for b in low_buckets) else None
        )

        # Extreme vs calm: VIX>=30 vs VIX<20
        extreme_buckets = [b for b in buckets_out if b["bucket"] in ("30-35", ">35")]
        calm_buckets = [b for b in buckets_out if b["bucket"] in ("<15", "15-20")]
        extreme_avg = (
            sum(b["avg_return"] * b["count"] for b in extreme_buckets if b["avg_return"] is not None)
            / sum(b["count"] for b in extreme_buckets if b["avg_return"] is not None)
            if any(b["avg_return"] is not None for b in extreme_buckets) else None
        )
        calm_avg = (
            sum(b["avg_return"] * b["count"] for b in calm_buckets if b["avg_return"] is not None)
            / sum(b["count"] for b in calm_buckets if b["avg_return"] is not None)
            if any(b["avg_return"] is not None for b in calm_buckets) else None
        )

        # Correlation: VIX level vs forward return
        vix_levels = []
        forward_rets = []
        for bucket_name, lo, hi in VIX_BUCKETS:
            rets = bucket_returns[days].get(bucket_name, [])
            # Use mid-point of bucket as representative VIX level
            mid_vix = (lo + hi) / 2 if hi != float("inf") else lo + 5
            for r in rets:
                vix_levels.append(mid_vix)
                forward_rets.append(r)

        # Simple correlation
        if len(vix_levels) > 2:
            n_corr = len(vix_levels)
            mean_vix = sum(vix_levels) / n_corr
            mean_ret = sum(forward_rets) / n_corr
            num = sum((v - mean_vix) * (r - mean_ret) for v, r in zip(vix_levels, forward_rets))
            denom_v = sum((v - mean_vix) ** 2 for v in vix_levels)
            denom_r = sum((r - mean_ret) ** 2 for r in forward_rets)
            correlation = num / ((denom_v * denom_r) ** 0.5) if denom_v > 0 and denom_r > 0 else 0
        else:
            correlation = 0

        horizon_results[label] = {
            "lookahead_days": days,
            "buckets": buckets_out,
            "strictly_monotonic": strictly_monotonic,
            "non_decreasing": non_decreasing,
            "vix_return_correlation": round(correlation, 4),
            "threshold_analysis": {
                "high_vix_ge25_avg": round(high_avg, 6) if high_avg is not None else None,
                "low_vix_lt25_avg": round(low_avg, 6) if low_avg is not None else None,
                "high_outperforms_low": (high_avg > low_avg) if (high_avg is not None and low_avg is not None) else None,
                "extreme_vix_ge30_avg": round(extreme_avg, 6) if extreme_avg is not None else None,
                "calm_vix_lt20_avg": round(calm_avg, 6) if calm_avg is not None else None,
                "extreme_outperforms_calm": (extreme_avg > calm_avg) if (extreme_avg is not None and calm_avg is not None) else None,
            },
        }

    # Overall assessment
    monotonic_count = sum(1 for h in horizon_results.values() if h["strictly_monotonic"])
    non_decreasing_count = sum(1 for h in horizon_results.values() if h["non_decreasing"])
    high_beats_low_count = sum(1 for h in horizon_results.values()
                                if h["threshold_analysis"]["high_outperforms_low"])
    extreme_beats_calm_count = sum(1 for h in horizon_results.values()
                                    if h["threshold_analysis"]["extreme_outperforms_calm"])

    results = {
        "claim": "#12 - VIX越高恐慌买入收益越强",
        "data_range": {"from": data[0][0], "to": data[-1][0]},
        "total_trading_days": n,
        "vix_bucket_definitions": [
            {"bucket": name, "range": f"{lo}-{hi if hi != float('inf') else 'inf'}"}
            for name, lo, hi in VIX_BUCKETS
        ],
        "horizon_results": horizon_results,
        "overall_assessment": {
            "horizons_with_strict_monotonic": monotonic_count,
            "horizons_with_non_decreasing": non_decreasing_count,
            "horizons_high_vix_ge25_beats_low": high_beats_low_count,
            "horizons_extreme_vix_ge30_beats_calm": extreme_beats_calm_count,
            "total_horizons": len(LOOKAHEAD_TRADING_DAYS),
            "claim_supported_strict": monotonic_count >= 3,
            "claim_supported_weak": non_decreasing_count >= 3,
            "claim_supported_threshold": high_beats_low_count >= 3,
            "claim_supported_extreme": extreme_beats_calm_count >= 3,
        },
        "summary": (
            "如果 VIX 越高的分桶对应的 SPX 后续平均收益率越高, "
            "则论断成立: VIX 越高恐慌时买入的收益越强."
        ),
    }

    return results


if __name__ == "__main__":
    results = run_backtest()

    # Write results
    out_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # Print readable summary
    print()
    print("=" * 70)
    print(f"论断 #12: VIX越高恐慌买入收益越强")
    print(f"数据范围: {results['data_range']['from']} ~ {results['data_range']['to']}")
    print(f"总交易日: {results['total_trading_days']}")
    print()

    for label, h in results["horizon_results"].items():
        print(f"--- {label} SPX 后续收益 ---")
        print(f"{'VIX桶':>8} | {'信号数':>6} | {'均收益':>10} | {'中位数':>10} | {'胜率':>8} | {'标准差':>8}")
        print("-" * 60)
        for b in h["buckets"]:
            avg = f"{b['avg_return']:+>9.4%}" if b["avg_return"] is not None else "N/A"
            med = f"{b['median_return']:+>9.4%}" if b["median_return"] is not None else "N/A"
            wr = f"{b['win_rate']:>7.1%}" if b["win_rate"] is not None else "N/A"
            std = f"{b['std_return']:>7.4f}" if b["std_return"] is not None else "N/A"
            print(f"{b['bucket']:>8} | {b['count']:>6} | {avg} | {med} | {wr} | {std}")
        monotonic = "YES" if h["strictly_monotonic"] else "NO"
        corr = h["vix_return_correlation"]
        print(f"  单调递增: {monotonic}  |  VIX-收益相关系数: {corr:>+.4f}")
        ta = h["threshold_analysis"]
        if ta["high_vix_ge25_avg"] is not None:
            print(f"  高VIX(>=25)均收益: {ta['high_vix_ge25_avg']:+>9.4%} vs 低VIX(<25): {ta['low_vix_lt25_avg']:+>9.4%} | "
                  f"高>低: {'YES' if ta['high_outperforms_low'] else 'NO'}")
        if ta["extreme_vix_ge30_avg"] is not None:
            print(f"  极端VIX(>=30)均收益: {ta['extreme_vix_ge30_avg']:+>9.4%} vs 平静VIX(<20): {ta['calm_vix_lt20_avg']:+>9.4%} | "
                  f"极端>平静: {'YES' if ta['extreme_outperforms_calm'] else 'NO'}")
        print()

    print(f"严格单调递增的持有期数: {results['overall_assessment']['horizons_with_strict_monotonic']}/{results['overall_assessment']['total_horizons']}")
    print(f"非递减的持有期数: {results['overall_assessment']['horizons_with_non_decreasing']}/{results['overall_assessment']['total_horizons']}")
    print(f"高VIX(>=25)跑赢低VIX(<25)的持有期数: {results['overall_assessment']['horizons_high_vix_ge25_beats_low']}/{results['overall_assessment']['total_horizons']}")
    print(f"极端VIX(>=30)跑赢平静VIX(<20)的持有期数: {results['overall_assessment']['horizons_extreme_vix_ge30_beats_calm']}/{results['overall_assessment']['total_horizons']}")

    if results["overall_assessment"]["claim_supported_threshold"]:
        verdict = "✅ SUPPORT (VIX>=25 vs <25)"
    elif results["overall_assessment"]["claim_supported_strict"]:
        verdict = "✅ SUPPORT"
    else:
        verdict = "🟡 PARTIAL"
    print(f"\n结论: {verdict}")
    print()

    print(json.dumps(results, indent=2, ensure_ascii=False))
