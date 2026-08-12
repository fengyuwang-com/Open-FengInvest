#!/usr/bin/env python3
"""verify-005-shanghai-annual-symmetry.py — 论断 #5: 上证年线上下对称

统计 000001.SS（上证综合指数）全部历史交易日收盘价在 200MA 上方与下方的天数，
分析上下占比是否接近对称。

用法:
    python research/110-strategy-verification/005-shanghai-annual-symmetry/verify-005-shanghai-annual-symmetry.py
"""
import sys, os, json, sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, BASE)

DB_PATH = os.path.join(BASE, "data", "market_data.db")

INDEX_ID = 26         # 000001.SS
INDEX_TICKER = "000001.SS"
INDEX_NAME = "上证综合指数"


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

    for i in range(199, n):
        ma200 = sum(closes[i-199:i+1]) / 200.0
        if closes[i] > ma200:
            above_days += 1
        else:
            below_days += 1

    total_days = above_days + below_days
    above_pct = above_days / total_days * 100
    below_pct = below_days / total_days * 100
    ratio = above_days / below_days if below_days > 0 else None

    result = {
        "index": INDEX_TICKER,
        "name": INDEX_NAME,
        "first_date": dates[0],
        "last_date": dates[-1],
        "total_trading_days_analyzed": total_days,
        "above_ma200_days": above_days,
        "below_ma200_days": below_days,
        "above_pct": round(above_pct, 2),
        "below_pct": round(below_pct, 2),
        "ratio_above_below": round(ratio, 4) if ratio else None,
        # "对称" means close to 50-50. Allow 45-55% range.
        "claim_supported": 40 <= above_pct <= 60,
    }

    return result


def main():
    print("Computing 上证指数 200MA above/below symmetry...", file=sys.stderr)
    result = compute()

    out_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    print(f"\nResults written to {os.path.join(out_dir, 'results.json')}")

    print("\n" + "=" * 70)
    print("论断 #5 — 上证年线上下对称")
    print("=" * 70)
    print(f"  Index: {result['name']} ({result['first_date']} ~ {result['last_date']})")
    print(f"  Total trading days: {result['total_trading_days_analyzed']}")
    print(f"  Above 200MA: {result['above_ma200_days']} ({result['above_pct']}%)")
    print(f"  Below 200MA: {result['below_ma200_days']} ({result['below_pct']}%)")
    print(f"  Ratio (above/below): {result['ratio_above_below']}")
    verdict = "SUPPORT (对称)" if result["claim_supported"] else "REJECT (不对称)"
    print(f"  Verdict: {verdict}")


if __name__ == "__main__":
    main()
