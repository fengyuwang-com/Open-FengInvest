#!/usr/bin/env python3
"""verify-009-volume-pullback.py — Claim #9: Volume pullback to 50-day MA with support hold predicts >60% win rate

Signal: Price drops to ~50-day MA from above, volume < 70% of 20-day avg volume,
        and price stays above MA for next 5 trading days (support holds).
Result: Price higher 20 trading days later with >60% probability.

Usage:
    python research/110-strategy-verification/009-volume-pullback/verify-009-volume-pullback.py
    python research/110-strategy-verification/009-volume-pullback/verify-009-volume-pullback.py --market CN
    python research/110-strategy-verification/009-volume-pullback/verify-009-volume-pullback.py --market HK
    python research/110-strategy-verification/009-volume-pullback/verify-009-volume-pullback.py --all-markets
"""
import sys, os, json, argparse
from collections import defaultdict
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
        "SELECT date, close, volume FROM daily_data WHERE index_id=? AND close IS NOT NULL ORDER BY date",
        (index_id,)
    ).fetchall()
    conn.close()
    return rows


def calc_sma(values, window):
    """Calculate simple moving average. Returns list of (value or None)."""
    result = [None] * len(values)
    for i in range(len(values)):
        if i < window - 1:
            continue
        result[i] = sum(values[i - window + 1:i + 1]) / window
    return result


def find_pullback_signals(dates, closes, volumes):
    """Find volume-pullback signals.

    Returns list of dicts with signal details.
    """
    if len(closes) < 70:  # need at least 70 days for 50 MA and 20 avg vol
        return []

    sma_50 = calc_sma(closes, 50)

    # Calculate 20-day average volume for each day
    avg_vol_20 = [None] * len(volumes)
    for i in range(len(volumes)):
        if i < 20:
            continue
        valid_vols = [v for v in volumes[i - 20:i] if v and v > 0]
        if len(valid_vols) >= 10:
            avg_vol_20[i] = sum(valid_vols) / len(valid_vols)

    signals = []
    i = 51  # start after we have 50-day MA (need i-1 for prev day check)
    while i < len(closes) - 25:  # need 20 forward + 5 hold
        if sma_50[i] is None or avg_vol_20[i] is None:
            i += 1
            continue
        if closes[i - 1] is None or closes[i] is None:
            i += 1
            continue
        if volumes[i] is None or volumes[i] <= 0:
            i += 1
            continue
        if avg_vol_20[i] <= 0:
            i += 1
            continue

        # Condition (a): Previous day close was above 50-day MA
        prev_above_ma = closes[i - 1] > sma_50[i - 1]

        # Condition (b): Current close is within +/- 1% of 50-day MA (pulls back to it)
        ma_50_val = sma_50[i]
        close_to_ma = abs(closes[i] - ma_50_val) / ma_50_val <= 0.01

        # Condition (c): Volume < 70% of 20-day average volume
        vol_ratio = volumes[i] / avg_vol_20[i]
        low_volume = vol_ratio < 0.70

        if prev_above_ma and close_to_ma and low_volume:
            # Check if support holds: price stays above or at 50MA for next 5 days
            support_held = True
            for j in range(1, 6):  # 5 trading days
                if i + j >= len(closes) or closes[i + j] is None:
                    support_held = False
                    break
                if closes[i + j] < sma_50[i + j]:
                    support_held = False
                    break

            if not support_held:
                i += 1
                continue

            # Measure 20-day forward return
            entry_price = closes[i]
            future_idx = min(i + 20, len(closes) - 1)
            future_price = closes[future_idx]
            if future_price is None or entry_price is None or entry_price == 0:
                i += 1
                continue

            forward_return = (future_price - entry_price) / entry_price
            is_win = forward_return > 0

            signals.append({
                "date": dates[i],
                "entry_price": round(entry_price, 4),
                "fwd_price": round(future_price, 4),
                "fwd_return": round(forward_return, 4),
                "vol_ratio": round(vol_ratio, 4),
                "ma_50": round(ma_50_val, 4),
                "win": is_win,
            })

        i += 1

    return signals


def test_claim(market="US"):
    """Backtest Claim #9 for a given market."""
    stocks = get_stocks(market)
    total_signals = 0
    total_wins = 0
    stock_results = []

    for idx_id, ticker, name in stocks:
        data = load_daily_data(idx_id)
        if len(data) < 100:
            continue

        dates = [r[0] for r in data]
        closes = [r[1] for r in data]
        volumes = [r[2] if r[2] else 0 for r in data]

        signals = find_pullback_signals(dates, closes, volumes)
        if not signals:
            continue

        wins = sum(1 for s in signals if s["win"])
        wr = wins / len(signals) if signals else 0

        stock_results.append({
            "ticker": ticker,
            "name": name,
            "signals": len(signals),
            "wins": wins,
            "win_rate": round(wr, 4),
            "avg_fwd_return": round(sum(s["fwd_return"] for s in signals) / len(signals), 4),
        })
        total_signals += len(signals)
        total_wins += wins

    overall_win_rate = total_wins / total_signals if total_signals > 0 else 0
    # Claim: win rate should be > 60%
    claim_supported = overall_win_rate > 0.60

    return {
        "market": market,
        "market_label": MARKETS.get(market, {}).get("label", market),
        "stock_count": len(stocks),
        "stocks_with_signals": len(stock_results),
        "total_signals": total_signals,
        "total_wins": total_wins,
        "overall_win_rate": round(overall_win_rate, 4),
        "claim_threshold_pct": 60,
        "claim_supported": claim_supported,
        "per_stock": sorted(stock_results, key=lambda x: -x["signals"])[:30],
    }


def main():
    parser = argparse.ArgumentParser(description="Claim #9: Volume pullback to 50MA support")
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
    print("=" * 55)
    for m, r in results.items():
        verdict = "SUPPORT" if r["claim_supported"] else "REJECT"
        print(f"{r['market_label']}: win_rate={r['overall_win_rate']:.1%} ({r['total_wins']}/{r['total_signals']}) -> {verdict}")
        print(f"   stocks_with_signals={r['stocks_with_signals']}/{r['stock_count']}, total_signals={r['total_signals']}")
        print(f"   claim: win rate > 60%")

    # Save results
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved: {out_path}")


if __name__ == "__main__":
    main()
