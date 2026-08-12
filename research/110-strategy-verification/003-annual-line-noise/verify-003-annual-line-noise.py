#!/usr/bin/env python3
"""verify-003-annual-line-noise.py — 论断 #3: 年线穿越约 25-33% 为噪音

当收盘价穿越 200MA（向上或向下）后，统计在 10/20/30 个交易日内
又穿越回去的比例。这个比例即为"噪音穿越"。

用法:
    python research/110-strategy-verification/003-annual-line-noise/verify-003-annual-line-noise.py
    python research/110-strategy-verification/003-annual-line-noise/verify-003-annual-line-noise.py --all-markets
"""
import sys, os, json, sqlite3, time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, BASE)

DB_PATH = os.path.join(BASE, "data", "market_data.db")

MAJOR_MARKETS = ["US", "CN", "HK", "JP", "KR", "UK", "AU", "IN", "CA", "DE", "FR", "TW"]
LOOKBACK_WINDOWS = [10, 20, 30]


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


def detect_crossings(closes):
    """检测所有 200MA 穿越点。

    返回:
        up_crossings: list of indices where close crosses above 200MA
        down_crossings: list of indices where close crosses below 200MA
    """
    n = len(closes)
    if n < 200:
        return [], []

    up, down = [], []
    prev_above = None

    for i in range(199, n):
        ma200 = sum(closes[i-199:i+1]) / 200.0
        above = closes[i] > ma200

        if prev_above is not None:
            if not prev_above and above:
                up.append(i)       # crossed above
            elif prev_above and not above:
                down.append(i)     # crossed below

        prev_above = above

    return up, down


def count_noise(closes, crossing_indices, lookback):
    """对一组穿越点，统计在 lookback 天内交叉回去的比例。

    up_crossings 的"回去"指回到下方；
    down_crossings 的"回去"指回到上方。
    """
    n = len(closes)
    total = 0
    noise = 0

    for idx in crossing_indices:
        end = idx + lookback
        if end >= n:
            continue
        total += 1

        # See if close moves back to the other side within lookback days
        crossed_back = False
        for j in range(1, lookback + 1):
            ma200_j = sum(closes[idx+j-199:idx+j+1]) / 200.0
            originally_above = closes[idx] > ma200_j  # same as the crossing direction check
            # Actually let's just check relative to the current MA
            # The crossing direction is determined at idx.
            # For up crossings: noise = goes back below
            # For down crossings: noise = goes back above
            pass

        # Simpler approach: compute MA at crossing point, track direction
        # We already know the direction at idx from detect_crossings
        # Let's verify: at idx, the close has just crossed
        ma_cross = sum(closes[idx-199:idx+1]) / 200.0
        is_up = closes[idx] > ma_cross  # True for up crossing

        for j in range(1, lookback + 1):
            check_idx = idx + j
            if check_idx >= n:
                break
            ma_check = sum(closes[check_idx-199:check_idx+1]) / 200.0
            if is_up:
                # Up crossing: noise = goes back below
                if closes[check_idx] < ma_check:
                    crossed_back = True
                    break
            else:
                # Down crossing: noise = goes back above
                if closes[check_idx] > ma_check:
                    crossed_back = True
                    break

        if crossed_back:
            noise += 1

    return total, noise


def run_market(market):
    stocks = get_stocks(market)

    # Aggregate crossing counts and noise counts
    agg = {w: {"total_up": 0, "noise_up": 0, "total_down": 0, "noise_down": 0}
           for w in LOOKBACK_WINDOWS}

    stocks_processed = 0
    stocks_with_crossings = 0

    for idx_id, ticker, name in stocks:
        closes = load_prices(idx_id)
        if len(closes) < 300:  # Need some buffer after crossing
            continue
        stocks_processed += 1

        up_x, down_x = detect_crossings(closes)
        if len(up_x) + len(down_x) == 0:
            continue
        stocks_with_crossings += 1

        for w in LOOKBACK_WINDOWS:
            tu, nu = count_noise(closes, up_x, w)
            td, nd = count_noise(closes, down_x, w)
            agg[w]["total_up"] += tu
            agg[w]["noise_up"] += nu
            agg[w]["total_down"] += td
            agg[w]["noise_down"] += nd

    result = {
        "market": market,
        "stocks_total": len(stocks),
        "stocks_processed": stocks_processed,
        "stocks_with_crossings": stocks_with_crossings,
    }

    for w in LOOKBACK_WINDOWS:
        tu = agg[w]["total_up"]
        nu = agg[w]["noise_up"]
        td = agg[w]["total_down"]
        nd = agg[w]["noise_down"]
        tt = tu + td
        nt = nu + nd
        noise_rate = nt / tt if tt > 0 else None

        result[f"w{w}"] = {
            "up_crossings": tu, "up_noise": nu,
            "up_noise_rate": round(nu / tu, 4) if tu > 0 else None,
            "down_crossings": td, "down_noise": nd,
            "down_noise_rate": round(nd / td, 4) if td > 0 else None,
            "total_crossings": tt,
            "total_noise": nt,
            "noise_rate": round(noise_rate, 4) if noise_rate is not None else None,
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

    print("Running backtest for 论断#3: 年线穿越约25-33%为噪音...", file=sys.stderr)
    results = run_backtest(markets)

    out_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nResults written to {os.path.join(out_dir, 'results.json')}")

    print("\n" + "=" * 70)
    print("论断 #3 — 年线穿越约 25-33% 为噪音")
    print("=" * 70)
    for m, r in results.items():
        s = f"stocks={r['stocks_with_crossings']}/{r['stocks_processed']}/{r['stocks_total']}"
        print(f"\n[{m}] {s}")
        for w in LOOKBACK_WINDOWS:
            d = r.get(f"w{w}")
            if not d or d.get("total_crossings", 0) == 0:
                continue
            print(f"  {w}d: noise={d['noise_rate']:.1%} ({d['total_noise']}/{d['total_crossings']}) "
                  f"up={d['up_noise_rate']:.1%} down={d['down_noise_rate']:.1%}")


if __name__ == "__main__":
    main()
