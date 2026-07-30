#!/usr/bin/env python3
"""verify-010-breakout-volume.py — Claim #10: Breakout above 50-day high on high volume predicts sustained gains

Signal: Price breaks above rolling 50-day high (max of recent high prices)
        on volume > 1.5x 20-day average volume.
Result: Price stays above breakout level 10/20/60 trading days later at rates
        significantly above 50% (random chance).

Usage:
    python research/110-strategy-verification/010-breakout-volume/verify-010-breakout-volume.py
    python research/110-strategy-verification/010-breakout-volume/verify-010-breakout-volume.py --market CN
    python research/110-strategy-verification/010-breakout-volume/verify-010-breakout-volume.py --market HK
    python research/110-strategy-verification/010-breakout-volume/verify-010-breakout-volume.py --all-markets
"""
import sys, os, json, argparse
import sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, BASE)

DB_PATH = os.path.join(BASE, "data", "market_data.db")

MARKETS = {
    "US": {"label": "US_SP500", "markets": ["US"]},
    "CN": {"label": "CN_CSI300", "markets": ["CN"]},
    "HK": {"label": "HK_HSI", "markets": ["HK"]},
}

# Lookahead windows for measuring sustained breakout
LOOKAHEAD_DAYS = [10, 20, 60]


def get_stocks(market, category="stock"):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, ticker, name FROM indices WHERE market=? AND category=? ORDER BY ticker",
        (market, category)
    ).fetchall()
    conn.close()
    return rows


def load_daily_data(index_id):
    """Load all daily data for a stock sorted by date."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT date, close, high, volume FROM daily_data WHERE index_id=? AND close IS NOT NULL ORDER BY date",
        (index_id,)
    ).fetchall()
    conn.close()
    return rows


def rolling_max(values, window):
    """Calculate rolling max over lookback window. Returns list of (value or None)."""
    result = [None] * len(values)
    for i in range(len(values)):
        if i < window:
            continue
        result[i] = max(values[i - window:i])
    return result


def calc_sma(values, window):
    """Calculate simple moving average. Returns list of (value or None)."""
    result = [None] * len(values)
    for i in range(len(values)):
        if i < window - 1:
            continue
        result[i] = sum(values[i - window + 1:i + 1]) / window
    return result


def find_breakout_signals(dates, closes, highs, volumes):
    """Find high-volume breakout signals above 50-day high.

    Returns list of signal dicts with details for each lookahead window.
    """
    if len(closes) < 80:
        return []

    high_50_max = rolling_max(highs, 50)
    avg_vol_20 = calc_sma(volumes, 20)

    signals = []
    i = 50  # start after we have 50-day high
    while i < len(closes) - max(LOOKAHEAD_DAYS):
        if high_50_max[i] is None or avg_vol_20[i] is None:
            i += 1
            continue
        if closes[i] is None or volumes[i] is None or volumes[i] <= 0:
            i += 1
            continue
        if avg_vol_20[i] <= 0:
            i += 1
            continue

        # Condition: close > previous 50-day high (strict >)
        prev_high_50 = high_50_max[i]
        breakout = closes[i] > prev_high_50

        # Condition: volume > 1.5x 20-day average
        vol_ratio = volumes[i] / avg_vol_20[i]
        high_volume = vol_ratio > 1.5

        if breakout and high_volume:
            entry_price = closes[i]
            b_level = entry_price  # breakout level = close price at signal

            signal = {
                "date": dates[i],
                "entry_price": round(entry_price, 4),
                "prev_50d_high": round(prev_high_50, 4),
                "vol_ratio": round(vol_ratio, 4),
            }

            # Check sustained breakout for each lookahead window
            all_windows_valid = True
            for n_days in LOOKAHEAD_DAYS:
                future_idx = min(i + n_days, len(closes) - 1)
                future_close = closes[future_idx]
                if future_close is None:
                    all_windows_valid = False
                    break

                above_breakout = future_close > b_level
                signal[f"above_{n_days}d"] = above_breakout
                signal[f"close_{n_days}d"] = round(future_close, 4)
                signal[f"ret_{n_days}d"] = round((future_close - b_level) / b_level, 4)

            if all_windows_valid:
                signals.append(signal)

        i += 1

    return signals


def test_claim(market="US"):
    """Backtest Claim #10 for a given market."""
    stocks = get_stocks(market)
    stock_results = []

    # Aggregate by lookahead window
    agg = {n: {"total": 0, "wins": 0} for n in LOOKAHEAD_DAYS}
    total_signals_all = 0

    for idx_id, ticker, name in stocks:
        data = load_daily_data(idx_id)
        if len(data) < 120:
            continue

        dates = [r[0] for r in data]
        closes = [r[1] for r in data]
        highs = [r[2] if r[2] else r[1] for r in data]  # fallback to close if high is None
        volumes = [r[3] if r[3] else 0 for r in data]

        signals = find_breakout_signals(dates, closes, highs, volumes)
        if not signals:
            continue

        total_signals_all += len(signals)

        stock_entry = {
            "ticker": ticker,
            "name": name,
            "signals": len(signals),
        }
        for n in LOOKAHEAD_DAYS:
            wins_n = sum(1 for s in signals if s.get(f"above_{n}d", False))
            wr_n = wins_n / len(signals) if signals else 0
            stock_entry[f"wins_{n}d"] = wins_n
            stock_entry[f"wr_{n}d"] = round(wr_n, 4)
            agg[n]["total"] += len(signals)
            agg[n]["wins"] += wins_n

        stock_results.append(stock_entry)

    # Build per-window results
    window_results = {}
    all_claim_supported = True
    for n in LOOKAHEAD_DAYS:
        wr = agg[n]["wins"] / agg[n]["total"] if agg[n]["total"] > 0 else 0
        # Sustained above-breakout rate > 50% supports the claim
        supported = wr > 0.50
        if not supported:
            all_claim_supported = False
        window_results[f"{n}d"] = {
            "total_signals": agg[n]["total"],
            "wins": agg[n]["wins"],
            "win_rate": round(wr, 4),
            "claim_supported": supported,
        }

    return {
        "market": market,
        "market_label": MARKETS.get(market, {}).get("label", market),
        "stock_count": len(stocks),
        "stocks_with_signals": len(stock_results),
        "total_signals": total_signals_all,
        "windows": window_results,
        "claim_supported": all_claim_supported,
        "per_stock": sorted(stock_results, key=lambda x: -x["signals"])[:30],
    }


def main():
    parser = argparse.ArgumentParser(description="Claim #10: High-volume 50-day breakout")
    parser.add_argument("--market", default="US", choices=["US", "CN", "HK"])
    parser.add_argument("--all-markets", action="store_true")
    args = parser.parse_args()

    if args.all_markets:
        results = {}
        for m in MARKETS:
            results[m] = test_claim(m)
    else:
        results = {args.market: test_claim(args.market)}

    print(json.dumps(results, indent=2, ensure_ascii=False))

    print()
    print("=" * 60)
    for m, r in results.items():
        print(f"{r['market_label']}: total_signals={r['total_signals']}, stocks={r['stocks_with_signals']}/{r['stock_count']}")
        for wn, wr in r["windows"].items():
            vs = "SUPPORT" if wr["claim_supported"] else "REJECT"
            print(f"   {wn}: win_rate={wr['win_rate']:.1%} ({wr['wins']}/{wr['total_signals']}) -> {vs}")
        verdict = "ALL SUPPORT" if r["claim_supported"] else "PARTIAL/REJECT"
        print(f"   overall: {verdict}")

    # Save results
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved: {out_path}")


if __name__ == "__main__":
    main()
