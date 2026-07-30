#!/usr/bin/env python3
"""verify-027-time-stop-loss.py — Claim #27: Time-stop-loss (6-month thesis unfulfilled) reduces downside risk

Simplified test:
  For each stock with sufficient data, generate periodic entry points.
  At each entry, if 6-month (126 trading day) return < 5% (thesis stalled),
  compare holding another 6 months vs. the exit outcome.
  The claim is that exit opportunity cost < continuing downside risk,
  meaning the exit strategy beats holding for stalled positions.

Usage:
    python research/110-strategy-verification/027-time-stop-loss/verify-027-time-stop-loss.py
    python research/110-strategy-verification/027-time-stop-loss/verify-027-time-stop-loss.py --market CN
    python research/110-strategy-verification/027-time-stop-loss/verify-027-time-stop-loss.py --market HK
    python research/110-strategy-verification/027-time-stop-loss/verify-027-time-stop-loss.py --all-markets
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

HOLD_DAYS = 126              # ~6 months of trading days
NEXT_HOLD_DAYS = 126         # next 6 months for comparison
ENTRY_INTERVAL = 21          # sample every ~1 month to get non-overlapping-ish entries
MIN_DATA_DAYS = 600          # need at least ~2.5 years of data


def get_stocks(market, category="stock"):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, ticker, name FROM indices WHERE market=? AND category=? ORDER BY ticker",
        (market, category)
    ).fetchall()
    conn.close()
    return rows


def load_closes(index_id):
    """Load close prices sorted by date."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT date, close FROM daily_data WHERE index_id=? AND close IS NOT NULL ORDER BY date",
        (index_id,)
    ).fetchall()
    conn.close()
    return rows


def test_claim(market="US"):
    """Backtest Claim #27 for a given market.

    Entry strategy: sample entry at regular intervals (monthly) to get
    a representative set of entry points across market regimes.
    """
    stocks = get_stocks(market)

    total_stalled = 0           # entries where 6m return < 5%
    total_exit_wins = 0         # stalled where exit (selling at 6m) outperforms hold
    total_exit_net_benefit = 0.0  # sum of (exit_return - hold_return) for stalled positions
    total_hold_net_cost = 0.0     # sum of losses from holding when exit was better

    stock_results = []

    for idx_id, ticker, name in stocks:
        data = load_closes(idx_id)
        if len(data) < MIN_DATA_DAYS:
            continue

        dates = [r[0] for r in data]
        prices = [r[1] for r in data]

        stock_stalled = 0
        stock_exit_wins = 0
        stock_entries = []

        # Sample entry points at regular intervals
        # Start with enough data for 6-month lookback (technically we just need
        # enough forward data, so start early) and enough forward data for
        # the full 12-month window
        max_entry = len(prices) - HOLD_DAYS - NEXT_HOLD_DAYS
        for entry_idx in range(0, max_entry, ENTRY_INTERVAL):
            entry_price = prices[entry_idx]
            if entry_price is None or entry_price <= 0:
                continue

            # 6-month (126 trading day) return
            exit_idx = entry_idx + HOLD_DAYS
            if exit_idx >= len(prices):
                continue
            exit_price = prices[exit_idx]
            if exit_price is None or exit_price <= 0:
                continue

            ret_6m = (exit_price - entry_price) / entry_price

            # Check if thesis stalled (6-month return < 5%)
            if ret_6m >= 0.05:
                continue

            # Also check if 6-month return is extremely negative (already severe loss)
            # In that case, the stop-loss already triggered — skip to avoid
            # confounding the thesis-unfulfilled scenario
            if ret_6m < -0.30:
                continue

            stock_stalled += 1

            # Measure next 6 months (what happens if you hold instead of exit)
            next_exit_idx = exit_idx + NEXT_HOLD_DAYS
            if next_exit_idx >= len(prices):
                continue
            next_exit_price = prices[next_exit_idx]
            if next_exit_price is None or next_exit_price <= 0:
                continue

            ret_next_6m = (next_exit_price - exit_price) / exit_price

            # Strategy comparison:
            # EXIT: realize ret_6m at 6-month mark, then sit in cash (0%)
            #       total return = ret_6m
            # HOLD: continue holding to 12-month mark
            #       total return = (1+ret_6m)*(1+ret_next_6m) - 1
            exit_total = ret_6m
            hold_total = (1.0 + ret_6m) * (1.0 + ret_next_6m) - 1.0

            exit_better = exit_total > hold_total

            if exit_better:
                stock_exit_wins += 1

            benefit_of_exit = exit_total - hold_total
            total_exit_net_benefit += benefit_of_exit

            # If hold lost (ret_next_6m < 0), track that loss as cost avoided
            if ret_next_6m < 0:
                total_hold_net_cost += abs(ret_next_6m)

            stock_entries.append({
                "entry_date": dates[entry_idx],
                "entry_price": round(entry_price, 4),
                "exit_date": dates[exit_idx],
                "ret_6m": round(ret_6m, 4),
                "ret_next_6m": round(ret_next_6m, 4),
                "exit_total": round(exit_total, 4),
                "hold_total": round(hold_total, 4),
                "exit_better": exit_better,
            })

        if stock_stalled == 0:
            continue

        wr = stock_exit_wins / stock_stalled if stock_stalled > 0 else 0
        avg_benefit = sum(s["exit_total"] - s["hold_total"] for s in stock_entries) / len(stock_entries) if stock_entries else 0

        # Also compute: for stalled positions, what happens next on average
        avg_next_ret = sum(s["ret_next_6m"] for s in stock_entries) / len(stock_entries) if stock_entries else 0
        avg_ret_6m = sum(s["ret_6m"] for s in stock_entries) / len(stock_entries) if stock_entries else 0
        # Count how many have negative next-6m returns (exit would have helped)
        negative_next = sum(1 for s in stock_entries if s["ret_next_6m"] < 0)

        stock_results.append({
            "ticker": ticker,
            "name": name,
            "total_entries_tested": len([None] * (len(prices) // ENTRY_INTERVAL)),
            "stalled_count": stock_stalled,
            "exit_wins": stock_exit_wins,
            "exit_win_rate": round(wr, 4),
            "avg_ret_6m": round(avg_ret_6m, 4),
            "avg_ret_next_6m": round(avg_next_ret, 4),
            "negative_next_count": negative_next,
            "avg_exit_benefit": round(avg_benefit, 4),
        })

    total_stalled = sum(s["stalled_count"] for s in stock_results)
    total_exit_wins = sum(s["exit_wins"] for s in stock_results)
    overall_exit_wr = total_exit_wins / total_stalled if total_stalled > 0 else 0

    # Average benefit of exit vs hold across all stalled positions
    total_entries_all = sum(s["stalled_count"] for s in stock_results)
    avg_ret_6m_all = sum(s["avg_ret_6m"] * s["stalled_count"] for s in stock_results) / total_entries_all if total_entries_all > 0 else 0
    avg_ret_next_all = sum(s["avg_ret_next_6m"] * s["stalled_count"] for s in stock_results) / total_entries_all if total_entries_all > 0 else 0

    # Claim: exit opportunity cost < continuing downside risk
    # This means for stalled positions:
    #   - exit strategy should win more than 50% of the time (exit_wr > 0.5)
    #   - OR: average next-6m return should be negative (avg_ret_next_6m < 0)
    #         indicating downside risk outweighs opportunity cost
    claim_by_win_rate = overall_exit_wr > 0.50
    claim_by_avg_next = avg_ret_next_all < 0
    claim_supported = claim_by_win_rate or claim_by_avg_next

    return {
        "market": market,
        "market_label": MARKETS.get(market, {}).get("label", market),
        "stock_count": len(stocks),
        "stocks_with_stalled": len(stock_results),
        "total_stalled_positions": total_stalled,
        "exit_wins": total_exit_wins,
        "exit_win_rate": round(overall_exit_wr, 4),
        "avg_ret_6m_stalled": round(avg_ret_6m_all, 4),
        "avg_ret_next_6m": round(avg_ret_next_all, 4),
        "exit_better_when_next_negative_pct": round(
            total_exit_wins / total_stalled * 100, 2
        ) if total_stalled > 0 else 0,
        "claim_by_win_rate": claim_by_win_rate,
        "claim_by_avg_next_negative": claim_by_avg_next,
        "claim_supported": claim_supported,
        "summary": (
            "exit_win_rate>50% means exit beats hold for stalled positions; "
            "avg_ret_next_6m<0 means the average stalled position declines further; "
            "both support the claim that time-stop-loss reduces downside risk."
        ),
        "per_stock": sorted(stock_results, key=lambda x: -x["stalled_count"])[:30],
    }


def main():
    parser = argparse.ArgumentParser(description="Claim #27: Time-stop-loss (6-month thesis unfulfilled)")
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
        verdict = "SUPPORT" if r["claim_supported"] else "REJECT"
        print(f"{r['market_label']}: {verdict}")
        print(f"   total_stalled={r['total_stalled_positions']}, exit_wins={r['exit_wins']}")
        print(f"   exit_win_rate={r['exit_win_rate']:.1%}")
        print(f"   avg_ret_6m_stalled={r['avg_ret_6m_stalled']:.2%}")
        print(f"   avg_ret_next_6m={r['avg_ret_next_6m']:.2%}")
        print(f"   stocks_with_stalled={r['stocks_with_stalled']}/{r['stock_count']}")
        print(f"   claim_by_win_rate={r['claim_by_win_rate']}, claim_by_avg_next_negative={r['claim_by_avg_next_negative']}")


if __name__ == "__main__":
    results = main()
    out_path = os.path.join(os.path.dirname(__file__), "results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
