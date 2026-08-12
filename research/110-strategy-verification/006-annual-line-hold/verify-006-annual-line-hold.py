#!/usr/bin/env python3
"""verify-006-annual-line-hold.py — 论断 #6: 站上年线 10 天后额外停留 > 2x

统计收盘价向上穿越 200MA 后，连续停留在年线上方的交易日数。
特别关注穿越后已停留 10 天的情形——这些情形下平均还会多留多少天？
论断声称：站上年线 10 天后，额外停留天数 > 全部穿越的平均停留天数的 2 倍。

用法:
    python research/110-strategy-verification/006-annual-line-hold/verify-006-annual-line-hold.py
    python research/110-strategy-verification/006-annual-line-hold/verify-006-annual-line-hold.py --all-markets
"""
import sys, os, json, sqlite3, time
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, BASE)

DB_PATH = os.path.join(BASE, "data", "market_data.db")

MAJOR_MARKETS = ["US", "CN", "HK", "JP", "KR", "UK", "AU", "IN", "CA", "DE", "FR", "TW"]
CHECKPOINT_DAY = 10  # 论断关注的检查点


def get_stocks(market):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, ticker, name FROM indices WHERE market=? AND category='stock' ORDER BY ticker",
        (market,)
    ).fetchall()
    conn.close()
    return rows


def load_closes(index_id):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT date, close FROM daily_data WHERE index_id=? AND close IS NOT NULL AND close > 0 ORDER BY date",
        (index_id,)
    ).fetchall()
    conn.close()
    return [float(r[1]) for r in rows]


def compute_hold_durations(closes):
    """找到所有向上的 200MA 穿越，计算每次穿越后连续停留在上方的天数。

    返回: list of hold_durations (int, 连续在年线上方的交易日数)
    """
    n = len(closes)
    if n < 200:
        return []

    durations = []
    i = 199
    while i < n:
        ma200 = sum(closes[i-199:i+1]) / 200.0
        if closes[i] > ma200:
            # Found start of above-MA period
            start = i
            j = i + 1
            while j < n:
                ma200_j = sum(closes[j-199:j+1]) / 200.0
                if closes[j] <= ma200_j:
                    break
                j += 1
            hold_days = j - start
            durations.append(hold_days)
            i = j  # Skip ahead to end of this period
        else:
            i += 1

    return durations


def run_market(market):
    stocks = get_stocks(market)

    all_durations = []       # all hold durations
    checkpoint_durations = []  # durations for holds that lasted >= CHECKPOINT_DAY
    stock_count = 0

    for idx_id, ticker, name in stocks:
        closes = load_closes(idx_id)
        if len(closes) < 200:
            continue
        stock_count += 1

        durations = compute_hold_durations(closes)
        all_durations.extend(durations)
        checkpoint_durations.extend([d for d in durations if d >= CHECKPOINT_DAY])

    if len(all_durations) == 0:
        return {"market": market, "stocks_processed": stock_count,
                "error": "No signals found"}

    mean_all = sum(all_durations) / len(all_durations)
    median_all = sorted(all_durations)[len(all_durations) // 2]

    # For episodes lasting >= CHECKPOINT_DAY days, compute "additional" days
    # i.e., total hold - CHECKPOINT_DAY
    if len(checkpoint_durations) > 0:
        additional_days = [d - CHECKPOINT_DAY for d in checkpoint_durations]
        mean_additional = sum(additional_days) / len(additional_days)
        median_additional = sorted(additional_days)[len(additional_days) // 2]
    else:
        additional_days = []
        mean_additional = None
        median_additional = None

    # Ratio: mean_additional / mean_all
    ratio = mean_additional / mean_all if mean_all > 0 and mean_additional is not None else None

    # Percentiles of all durations
    sorted_dur = sorted(all_durations)
    p25 = sorted_dur[len(sorted_dur) // 4] if len(sorted_dur) >= 4 else None
    p50 = sorted_dur[len(sorted_dur) // 2] if len(sorted_dur) >= 2 else None
    p75 = sorted_dur[3 * len(sorted_dur) // 4] if len(sorted_dur) >= 4 else None

    result = {
        "market": market,
        "stocks_processed": stock_count,
        "total_above_ma_episodes": len(all_durations),
        "episodes_ge_10days": len(checkpoint_durations),
        "mean_hold_all": round(mean_all, 2),
        "median_hold_all": median_all,
        "p25_hold": p25,
        "p75_hold": p75,
        "mean_additional_after_10": round(mean_additional, 2) if mean_additional is not None else None,
        "median_additional_after_10": median_additional,
        "ratio_additional_to_mean_all": round(ratio, 4) if ratio is not None else None,
        # Claim: ratio > 2.0
        "claim_supported": ratio is not None and ratio > 2.0,
    }

    return result


def run_backtest(markets=None):
    if markets is None:
        markets = ["US"]
    results = {}
    for m in markets:
        print(f"  Processing {m}...", file=sys.stderr)
        t0 = time.time()
        results[m] = run_market(m)
        print(f"    Done in {time.time() - t0:.1f}s", file=sys.stderr)
    return results


def main():
    if "--all-markets" in sys.argv:
        markets = MAJOR_MARKETS
    else:
        markets = ["US"]

    print("Running backtest for 论断#6: 站上年线10天后额外停留>2x...", file=sys.stderr)
    results = run_backtest(markets)

    out_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nResults written to {os.path.join(out_dir, 'results.json')}")

    print("\n" + "=" * 70)
    print("论断 #6 — 站上年线 10 天后额外停留 > 2x")
    print("=" * 70)
    for m, r in results.items():
        print(f"\n[{m}] stocks={r['stocks_processed']}, episodes={r['total_above_ma_episodes']}")
        print(f"  All holds: mean={r['mean_hold_all']}d, median={r['median_hold_all']}d (p25={r['p25_hold']}, p75={r['p75_hold']})")
        print(f"  Episodes >= 10d: {r['episodes_ge_10days']}")
        if r["mean_additional_after_10"] is not None:
            print(f"  Additional days after 10: mean={r['mean_additional_after_10']}d, median={r['median_additional_after_10']}d")
            print(f"  Ratio (additional/mean_all): {r['ratio_additional_to_mean_all']:.2f}x")
        verdict = "SUPPORT" if r["claim_supported"] else "REJECT"
        print(f"  Verdict: {verdict}")


if __name__ == "__main__":
    main()
