#!/usr/bin/env python3
"""verify-002-annual-line-filter.py — 论断 #2: 年线过滤降回撤 > 50%

仅当收盘价在 200MA 上方时买入（仓位 100%），否则空仓（现金 100%），
对比始终持仓的策略，比较最大回撤。

使用 7+ 主要市场。

用法:
    python research/110-strategy-verification/002-annual-line-filter/verify-002-annual-line-filter.py
    python research/110-strategy-verification/002-annual-line-filter/verify-002-annual-line-filter.py --all-markets
"""
import sys, os, json, sqlite3, time
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, BASE)

DB_PATH = os.path.join(BASE, "data", "market_data.db")

# Major markets to test
MAJOR_MARKETS = ["US", "CN", "HK", "JP", "KR", "UK", "AU", "IN", "CA", "DE", "FR", "TW"]

LOOKAHEAD_DAYS = [63, 126, 252]  # ~3mo, ~6mo, ~1yr
SAMPLE_INTERVAL = 21  # Sample 1 entry per ~month to keep runtime manageable


def get_stocks(market):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, ticker, name FROM indices WHERE market=? AND category='stock' ORDER BY ticker",
        (market,)
    ).fetchall()
    conn.close()
    return rows


def load_prices(index_id):
    """加载收盘价序列。返回 (dates, closes) 列表。"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT date, close FROM daily_data WHERE index_id=? AND close IS NOT NULL AND close > 0 ORDER BY date",
        (index_id,)
    ).fetchall()
    conn.close()
    dates = [r[0] for r in rows]
    closes = [float(r[1]) for r in rows]
    return dates, closes


def max_drawdown(values):
    """计算净值序列的最大回撤。values[0] 应为 1.0。"""
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


def run_market(market):
    """对一个市场的全部股票运行回测。"""
    stocks = get_stocks(market)

    # Per-holding-period, collect drawdowns for filtered vs always-in
    all_dds = {days: {"filtered": [], "always": []} for days in LOOKAHEAD_DAYS}

    stocks_processed = 0
    stocks_with_signal = 0

    for idx_id, ticker, name in stocks:
        dates, closes = load_prices(idx_id)
        n = len(closes)
        if n < 200:
            continue
        stocks_processed += 1

        # Pre-compute 200MA
        mas = []
        for i in range(n):
            if i < 199:
                mas.append(None)
            else:
                mas.append(sum(closes[i-199:i+1]) / 200.0)

        has_signal = False
        for days in LOOKAHEAD_DAYS:
            for i in range(199, n - days, SAMPLE_INTERVAL):
                p_signal = closes[i]
                if p_signal == 0 or p_signal is None:
                    continue

                # Strategy A (filtered): only invest if close > MA200, otherwise cash
                # Strategy B (always): always invest
                close_above = closes[i] > mas[i]

                vals_a = [1.0]
                vals_b = [1.0]
                for j in range(1, days + 1):
                    ret = closes[i + j] / p_signal
                    vals_b.append(ret)
                    if close_above:
                        vals_a.append(ret)
                    else:
                        vals_a.append(1.0)  # cash, no return

                dd_a = max_drawdown(vals_a)
                dd_b = max_drawdown(vals_b)
                all_dds[days]["filtered"].append(dd_a)
                all_dds[days]["always"].append(dd_b)
                has_signal = True

        if has_signal:
            stocks_with_signal += 1

    # Aggregate
    result = {
        "market": market,
        "stocks_total": len(stocks),
        "stocks_processed": stocks_processed,
        "stocks_with_signal": stocks_with_signal,
    }

    for days in LOOKAHEAD_DAYS:
        flist = all_dds[days]["filtered"]
        alist = all_dds[days]["always"]
        n_sig = len(flist)
        if n_sig == 0:
            result[f"d{days}"] = {"signal_count": 0}
            continue

        avg_f = sum(flist) / n_sig
        avg_a = sum(alist) / n_sig
        # Reduction in drawdown
        reduction = ((avg_a - avg_f) / avg_a * 100) if avg_a > 0 else 0

        result[f"d{days}"] = {
            "signal_count": n_sig,
            "avg_drawdown_filtered": round(avg_f, 6),
            "avg_drawdown_always": round(avg_a, 6),
            "drawdown_reduction_pct": round(reduction, 2),
            "claim_supported": reduction > 50,  # Claim says > 50%
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

    print("Running backtest for 论断#2: 年线过滤降回撤>50%...", file=sys.stderr)
    results = run_backtest(markets)

    out_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nResults written to {os.path.join(out_dir, 'results.json')}")

    print("\n" + "=" * 70)
    print("论断 #2 — 年线过滤降回撤 > 50%")
    print("=" * 70)
    for m, r in results.items():
        s = f"stocks={r['stocks_with_signal']}/{r['stocks_processed']}/{r['stocks_total']}"
        print(f"\n[{m}] {s}")
        for days in LOOKAHEAD_DAYS:
            d = r.get(f"d{days}")
            if not d or d.get("signal_count", 0) == 0:
                continue
            verdict = "SUPPORT" if d["claim_supported"] else "REJECT"
            print(f"  d{days}: filtered_dd={d['avg_drawdown_filtered']:.4f} always_dd={d['avg_drawdown_always']:.4f} "
                  f"reduction={d['drawdown_reduction_pct']:+.1f}% -> {verdict}")


if __name__ == "__main__":
    main()
