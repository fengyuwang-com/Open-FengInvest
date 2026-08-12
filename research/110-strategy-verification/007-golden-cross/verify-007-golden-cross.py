#!/usr/bin/env python3
"""verify-007-golden-cross.py — 论断 #7: 金叉后 6 个月跑赢随机

当 50MA 上穿 200MA（金叉）时，计算未来 6 个月（约 126 交易日）收益率，
与随机入场点比较。使用 bootstrap 检验显著性。

用法:
    python research/110-strategy-verification/007-golden-cross/verify-007-golden-cross.py
    python research/110-strategy-verification/007-golden-cross/verify-007-golden-cross.py --all-markets
"""
import sys, os, json, sqlite3, time, random
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, BASE)

DB_PATH = os.path.join(BASE, "data", "market_data.db")

MAJOR_MARKETS = ["US", "CN", "HK", "JP", "KR", "UK", "AU", "IN", "CA", "DE", "FR", "TW"]
FORWARD_DAYS = 126  # ~6 months
BOOTSTRAP_SAMPLES = 1000


def get_stocks(market):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, ticker, name FROM indices WHERE market=? AND category='stock' ORDER BY ticker",
        (market,)
    ).fetchall()
    conn.close()
    return rows


def load_prices(index_id):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT date, close FROM daily_data WHERE index_id=? AND close IS NOT NULL AND close > 0 ORDER BY date",
        (index_id,)
    ).fetchall()
    conn.close()
    return [float(r[1]) for r in rows]


def detect_golden_crosses(closes):
    """检测 50MA 上穿 200MA 的点。

    需要至少 200 个数据点（200MA 的第一个有效值在 index 199）。
    50MA 的第一个有效值在 index 49。

    返回: list of indices where golden cross occurs
    """
    n = len(closes)
    if n < 200:
        return []

    # Pre-compute 50MA
    ma50 = []
    for i in range(n):
        if i < 49:
            ma50.append(None)
        else:
            ma50.append(sum(closes[i-49:i+1]) / 50.0)

    # Pre-compute 200MA
    ma200 = []
    for i in range(n):
        if i < 199:
            ma200.append(None)
        else:
            ma200.append(sum(closes[i-199:i+1]) / 200.0)

    # Detect golden cross: 50MA crosses above 200MA
    crossings = []
    # Start from index 199 (first valid 200MA)
    prev_above = None
    for i in range(199, n):
        if ma50[i] is None or ma200[i] is None:
            continue
        curr_above = ma50[i] > ma200[i]

        if prev_above is not None and not prev_above and curr_above:
            crossings.append(i)

        prev_above = curr_above

    return crossings


def compute_forward_return(closes, idx, days):
    """计算从 idx 开始的 days 个交易日后的收益率。"""
    end = idx + days
    if end >= len(closes):
        return None
    if closes[idx] == 0 or closes[idx] is None:
        return None
    return (closes[end] - closes[idx]) / closes[idx]


def generate_random_entries(closes, n_entries, days, seed=None):
    """从收盘价序列中随机选取 n_entries 个入场点，计算 days 天收益。"""
    if seed is not None:
        rng = random.Random(seed)
    else:
        rng = random.Random()

    n = len(closes)
    if n <= days:
        return []

    # Only pick from range where we have enough forward data
    max_start = n - days - 1
    if max_start < 200:
        return []

    returns = []
    for _ in range(n_entries):
        idx = rng.randint(0, max_start)
        ret = compute_forward_return(closes, idx, days)
        if ret is not None:
            returns.append(ret)
    return returns


def run_market(market):
    stocks = get_stocks(market)

    all_cross_returns = []
    all_random_returns = []
    stocks_with_cross = 0
    stock_count = 0

    for idx_id, ticker, name in stocks:
        closes = load_prices(idx_id)
        if len(closes) < 200 + FORWARD_DAYS:
            continue
        stock_count += 1

        # Golden cross returns
        crosses = detect_golden_crosses(closes)
        for x_idx in crosses:
            ret = compute_forward_return(closes, x_idx, FORWARD_DAYS)
            if ret is not None:
                all_cross_returns.append(ret)

        if len(crosses) > 0:
            stocks_with_cross += 1

        # Random entries (same number as crosses for balance)
        n_random = max(len(crosses), 50)  # at least 50 random samples
        random_ret = generate_random_entries(closes, n_random, FORWARD_DAYS, seed=42)
        all_random_returns.extend(random_ret)

    if len(all_cross_returns) == 0:
        return {
            "market": market,
            "stocks_processed": stock_count,
            "stocks_with_cross": 0,
            "error": "No golden cross signals found",
        }

    # Compute means
    mean_cross = sum(all_cross_returns) / len(all_cross_returns)
    mean_random = sum(all_random_returns) / len(all_random_returns)
    win_rate_cross = sum(1 for r in all_cross_returns if r > 0) / len(all_cross_returns)
    win_rate_random = sum(1 for r in all_random_returns if r > 0) / len(all_random_returns)

    # Bootstrap: resample cross returns and compute mean
    rng = random.Random(123)
    boot_means = []
    for _ in range(BOOTSTRAP_SAMPLES):
        sample = rng.choices(all_cross_returns, k=len(all_cross_returns))
        boot_means.append(sum(sample) / len(sample))

    # P-value: what fraction of bootstrap means <= mean_random?
    # If golden cross returns are truly better, we expect few bootstrap means <= mean_random
    boot_means.sort()
    count_le = sum(1 for m in boot_means if m <= mean_random)
    p_value = count_le / BOOTSTRAP_SAMPLES

    # Also compute percentile of mean_random in bootstrap distribution
    # For display
    percentile = count_le / BOOTSTRAP_SAMPLES * 100

    result = {
        "market": market,
        "stocks_processed": stock_count,
        "stocks_with_golden_cross": stocks_with_cross,
        "golden_cross_episodes": len(all_cross_returns),
        "random_samples": len(all_random_returns),
        "golden_cross": {
            "mean_return": round(mean_cross, 6),
            "win_rate": round(win_rate_cross, 4),
            "sample_size": len(all_cross_returns),
        },
        "random_entry": {
            "mean_return": round(mean_random, 6),
            "win_rate": round(win_rate_random, 4),
            "sample_size": len(all_random_returns),
        },
        "comparison": {
            "mean_return_diff": round(mean_cross - mean_random, 6),
            "win_rate_diff": round(win_rate_cross - win_rate_random, 4),
            "bootstrap_p_value": round(p_value, 4),
            "bootstrap_percentile": round(percentile, 2),
            "claim_supported": mean_cross > mean_random and p_value < 0.05,
        },
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

    print("Running backtest for 论断#7: 金叉后6个月跑赢随机...", file=sys.stderr)
    results = run_backtest(markets)

    out_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nResults written to {os.path.join(out_dir, 'results.json')}")

    print("\n" + "=" * 70)
    print("论断 #7 — 金叉后 6 个月跑赢随机")
    print("=" * 70)
    for m, r in results.items():
        print(f"\n[{m}] stocks with cross: {r.get('stocks_with_golden_cross', 0)}/{r['stocks_processed']}")
        gc = r.get("golden_cross", {})
        re = r.get("random_entry", {})
        cmp = r.get("comparison", {})
        if gc.get("sample_size", 0) == 0:
            print("  No golden cross signals found.")
            continue
        print(f"  Golden cross: mean_ret={gc['mean_return']:.4f} WR={gc['win_rate']:.1%} n={gc['sample_size']}")
        print(f"  Random entry: mean_ret={re['mean_return']:.4f} WR={re['win_rate']:.1%} n={re['sample_size']}")
        print(f"  Diff: {cmp['mean_return_diff']:+.4f} WR_diff={cmp['win_rate_diff']:+.1%}")
        print(f"  Bootstrap p-value: {cmp['bootstrap_p_value']:.4f} ({cmp['bootstrap_percentile']:.1f}%ile)")
        verdict = "SUPPORT" if cmp["claim_supported"] else "REJECT"
        print(f"  Verdict: {verdict}")


if __name__ == "__main__":
    main()
