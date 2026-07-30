#!/usr/bin/env python3
"""verify-001-above-annual-line.py — 论断 #1: 年线上方买入收益优于下方

对每个股票，比较收盘价在 200MA 上方 vs 下方时的未来收益率。
使用全部 19 个有股票数据的市场。

用法:
    python research/110-strategy-verification/001-above-annual-line/verify-001-above-annual-line.py
    python research/110-strategy-verification/001-above-annual-line/verify-001-above-annual-line.py --market US
    python research/110-strategy-verification/001-above-annual-line/verify-001-above-annual-line.py --all-markets
"""
import sys, os, json, argparse, sqlite3, time
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, BASE)

DB_PATH = os.path.join(BASE, "data", "market_data.db")

# All 19 markets with stock data
ALL_MARKETS = ["AU", "CA", "CH", "CN", "DE", "ES", "FR", "HK", "IN", "IT", "JP", "KR", "NL", "NZ", "SE", "SG", "TW", "UK", "US"]
HOLDING_PERIODS = [20, 60, 120]  # ~1 month, ~3 months, ~6 months


def get_stocks(market):
    """获取指定市场的股票列表"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, ticker, name FROM indices WHERE market=? AND category='stock' ORDER BY ticker",
        (market,)
    ).fetchall()
    conn.close()
    return rows


def load_close_prices(index_id):
    """加载某个 index_id 的全部收盘价（升序）。"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT date, close FROM daily_data WHERE index_id=? AND close IS NOT NULL AND close > 0 ORDER BY date",
        (index_id,)
    ).fetchall()
    conn.close()
    return [(r[0], float(r[1])) for r in rows]


def compute_ma200_and_signals(data):
    """计算 200MA 并分类每个交易日为 above 或 below。

    返回:
        above_indices: list of int indices where close > MA200
        below_indices: list of int indices where close <= MA200
    """
    closes = [d[1] for d in data]
    n = len(closes)
    if n < 200:
        return [], []

    above, below = [], []
    for i in range(199, n):
        ma200 = sum(closes[i-199:i+1]) / 200.0
        if closes[i] > ma200:
            above.append(i)
        else:
            below.append(i)
    return above, below


def compute_forward_returns(closes, signal_indices, holding_days):
    """计算信号日的未来持有期收益率。

    返回: list of (return, is_win)
    """
    n = len(closes)
    results = []
    for idx in signal_indices:
        end = idx + holding_days
        if end >= n:
            continue
        if closes[idx] == 0 or closes[idx] is None:
            continue
        ret = (closes[end] - closes[idx]) / closes[idx]
        results.append((ret, ret > 0))
    return results


def run_market(market):
    """对一个市场运行回测，返回结果 dict。"""
    stocks = get_stocks(market)

    # Aggregate results by holding period and group
    by_group = {days: {"above": {"returns": [], "wins": 0, "total": 0},
                       "below": {"returns": [], "wins": 0, "total": 0}}
                for days in HOLDING_PERIODS}

    stocks_processed = 0
    stocks_with_signals = 0

    for idx_id, ticker, name in stocks:
        data = load_close_prices(idx_id)
        if len(data) < 200:
            continue
        stocks_processed += 1

        above_idx, below_idx = compute_ma200_and_signals(data)
        closes = [d[1] for d in data]

        has_signal = False
        for days in HOLDING_PERIODS:
            for group_name, group_indices in [("above", above_idx), ("below", below_idx)]:
                fwd_returns = compute_forward_returns(closes, group_indices, days)
                for ret, is_win in fwd_returns:
                    by_group[days][group_name]["returns"].append(ret)
                    by_group[days][group_name]["total"] += 1
                    if is_win:
                        by_group[days][group_name]["wins"] += 1
                if len(fwd_returns) > 0:
                    has_signal = True

        if has_signal:
            stocks_with_signals += 1

    # Build result
    result = {"market": market, "stocks_total": len(stocks),
              "stocks_processed": stocks_processed,
              "stocks_with_signals": stocks_with_signals}

    for days in HOLDING_PERIODS:
        for group in ["above", "below"]:
            d = by_group[days][group]
            total = d["total"]
            avg_ret = sum(d["returns"]) / total if total > 0 else None
            win_rate = d["wins"] / total if total > 0 else None
            result[f"d{days}_{group}"] = {
                "signal_count": total,
                "win_count": d["wins"],
                "win_rate": round(win_rate, 4) if win_rate is not None else None,
                "avg_return": round(avg_ret, 6) if avg_ret is not None else None,
            }

        # Compare above vs below
        above = by_group[days]["above"]
        below = by_group[days]["below"]
        if above["total"] > 0 and below["total"] > 0:
            above_wr = above["wins"] / above["total"]
            below_wr = below["wins"] / below["total"]
            above_ret = sum(above["returns"]) / above["total"]
            below_ret = sum(below["returns"]) / below["total"]
            result[f"d{days}_comparison"] = {
                "win_rate_diff": round(above_wr - below_wr, 4),
                "win_rate_ratio": round(above_wr / below_wr, 4) if below_wr > 0 else None,
                "avg_return_diff": round(above_ret - below_ret, 6),
                "claim_supported": above_wr > below_wr,
            }
        else:
            result[f"d{days}_comparison"] = None

    return result


def run_backtest(markets=None):
    """主回测。markets: list of market codes, 默认跑 US。"""
    if markets is None:
        markets = ["US"]

    all_results = {}
    for m in markets:
        print(f"  Processing {m}...", file=sys.stderr)
        t0 = time.time()
        all_results[m] = run_market(m)
        elapsed = time.time() - t0
        print(f"    Done in {elapsed:.1f}s", file=sys.stderr)

    return all_results


def main():
    parser = argparse.ArgumentParser(description="论断#1: 年线上方买入收益优于下方")
    parser.add_argument("--market", default="US")
    parser.add_argument("--all-markets", action="store_true")
    args = parser.parse_args()

    if args.all_markets:
        markets = ALL_MARKETS
    else:
        markets = [args.market]

    print("Screening stocks (this may take a while)...", file=sys.stderr)
    results = run_backtest(markets)

    # Write results.json
    out_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nResults written to {os.path.join(out_dir, 'results.json')}")

    # Print summary
    print("\n" + "=" * 70)
    print("论断 #1 — 年线上方买入收益优于下方")
    print("=" * 70)

    for m, r in results.items():
        stocks_info = f"stocks={r['stocks_with_signals']}/{r['stocks_processed']}/{r['stocks_total']}"
        print(f"\n[{m}] {stocks_info}")
        for days in HOLDING_PERIODS:
            comp = r.get(f"d{days}_comparison")
            if comp is None:
                continue
            abv = r[f"d{days}_above"]
            bel = r[f"d{days}_below"]
            verdict = "SUPPORT" if comp["claim_supported"] else "REJECT"
            print(f"  d{days}: above WR={abv['win_rate']:.1%}({abv['signal_count']}) vs below WR={bel['win_rate']:.1%}({bel['signal_count']}) "
                  f"diff={comp['win_rate_diff']:+.1%} ratio={comp['win_rate_ratio']:.2f}x -> {verdict}")


if __name__ == "__main__":
    main()
