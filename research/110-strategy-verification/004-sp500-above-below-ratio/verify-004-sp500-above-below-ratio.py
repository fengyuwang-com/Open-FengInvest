#!/usr/bin/env python3
"""verify-004-sp500-above-below-ratio.py — 论断 #4: SP500 年线上/下比例 = 2.8

统计 ^GSPC (S&P 500) 全部历史交易日收盘价在 200MA 上方与下方的天数比。

用法:
    python research/110-strategy-verification/004-sp500-above-below-ratio/verify-004-sp500-above-below-ratio.py
"""
import sys, os, json, sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, BASE)

DB_PATH = os.path.join(BASE, "data", "market_data.db")

INDEX_ID = 1          # ^GSPC
INDEX_TICKER = "^GSPC"
INDEX_NAME = "S&P 500"
CLAIM_RATIO = 2.8     # 论断声称的比例约为 2.8


def load_prices():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT date, close FROM daily_data WHERE index_id=? AND close IS NOT NULL ORDER BY date",
        (INDEX_ID,)
    ).fetchall()
    conn.close()
    return [(r[0], float(r[1])) for r in rows]


def compute():
    data = load_prices()
    closes = [d[1] for d in data]
    dates = [d[0] for d in data]
    n = len(closes)

    if n < 200:
        return {"error": "Not enough data"}

    above_days = 0
    below_days = 0
    above_list = []
    below_list = []

    for i in range(199, n):
        ma200 = sum(closes[i-199:i+1]) / 200.0
        if closes[i] > ma200:
            above_days += 1
            above_list.append({"date": dates[i], "close": closes[i], "ma200": ma200})
        else:
            below_days += 1
            below_list.append({"date": dates[i], "close": closes[i], "ma200": ma200})

    ratio = above_days / below_days if below_days > 0 else None
    total_days = above_days + below_days
    above_pct = above_days / total_days * 100

    # Breakdown by decade
    yearly_above = {}
    yearly_below = {}
    for i in range(199, n):
        year = dates[i][:4]
        ma200 = sum(closes[i-199:i+1]) / 200.0
        if closes[i] > ma200:
            yearly_above[year] = yearly_above.get(year, 0) + 1
        else:
            yearly_below[year] = yearly_below.get(year, 0) + 1

    yearly_ratios = {}
    for y in sorted(set(list(yearly_above.keys()) + list(yearly_below.keys()))):
        a = yearly_above.get(y, 0)
        b = yearly_below.get(y, 0)
        yearly_ratios[y] = {
            "above": a, "below": b,
            "ratio": round(a / b, 4) if b > 0 else None,
        }

    # Decade aggregation
    decades = {}
    decade_labels = {}
    for y, v in yearly_ratios.items():
        dec = y[:3] + "0s"
        if dec not in decades:
            decades[dec] = {"above": 0, "below": 0}
            decade_labels[dec] = dec
        decades[dec]["above"] += v["above"]
        decades[dec]["below"] += v["below"]

    for dec, v in decades.items():
        decades[dec] = {
            "above": v["above"], "below": v["below"],
            "ratio": round(v["above"] / v["below"], 4) if v["below"] > 0 else None,
        }

    result = {
        "index": INDEX_TICKER,
        "name": INDEX_NAME,
        "first_date": dates[0],
        "last_date": dates[-1],
        "total_trading_days": total_days,
        "above_ma200_days": above_days,
        "below_ma200_days": below_days,
        "above_pct": round(above_pct, 2),
        "below_pct": round(100 - above_pct, 2),
        "ratio_above_below": round(ratio, 4) if ratio else None,
        "claim_ratio": CLAIM_RATIO,
        "claim_supported": ratio is not None and abs(ratio - CLAIM_RATIO) < 0.5,  # within 0.5 tolerance
    }

    return result


def main():
    print("Computing S&P 500 200MA above/below ratio...", file=sys.stderr)
    result = compute()

    out_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\nResults written to {os.path.join(out_dir, 'results.json')}")

    print("\n" + "=" * 70)
    print("论断 #4 — SP500 年线上/下比例 = 2.8")
    print("=" * 70)
    print(f"  Index: {result['name']} ({result['first_date']} ~ {result['last_date']})")
    print(f"  Total trading days: {result['total_trading_days']}")
    print(f"  Above 200MA: {result['above_ma200_days']} ({result['above_pct']}%)")
    print(f"  Below 200MA: {result['below_ma200_days']} ({result['below_pct']}%)")
    print(f"  Ratio (above/below): {result['ratio_above_below']}")
    print(f"  Claim ratio: {result['claim_ratio']}")
    verdict = "SUPPORT" if result["claim_supported"] else "REJECT"
    print(f"  Verdict: {verdict}")


if __name__ == "__main__":
    main()
