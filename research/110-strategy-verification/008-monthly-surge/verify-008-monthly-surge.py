#!/usr/bin/env python3
"""verify-008-monthly-surge.py — 论断 #8: 月涨幅>30%的标的，次月继续上涨的概率<40%

用法:
    python research/110-strategy-verification/008-monthly-surge/verify-008-monthly-surge.py
    python research/110-strategy-verification/008-monthly-surge/verify-008-monthly-surge.py --market CN
    python research/110-strategy-verification/008-monthly-surge/verify-008-monthly-surge.py --market HK
    python research/110-strategy-verification/008-monthly-surge/verify-008-monthly-surge.py --all-markets
"""
import sys, os, json, argparse
from collections import defaultdict
import sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, BASE)
DB_PATH = os.path.join(BASE, "data", "market_data.db")

MARKETS = {
    "US": {"label": "US_SP500", "market": "US"},
    "CN": {"label": "CN_CSI300", "market": "CN"},
    "HK": {"label": "HK_HSI", "market": "HK"},
}


def get_stocks(market, category="stock"):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, ticker, name FROM indices WHERE market=? AND category=? ORDER BY ticker",
        (market, category)
    ).fetchall()
    conn.close()
    return rows


def calc_monthly_returns(index_id):
    """计算个股的月度收益率序列"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT date, close FROM daily_data WHERE index_id=? AND close IS NOT NULL ORDER BY date",
        (index_id,)
    ).fetchall()
    conn.close()
    if len(rows) < 60:  # 至少5年数据
        return []

    # 按年月分组，取月末收盘价
    monthly = defaultdict(list)
    for date_str, close in rows:
        ym = date_str[:7]  # YYYY-MM
        monthly[ym].append(close)

    # 每月最后一个交易日
    month_last = {}
    for ym, closes in monthly.items():
        month_last[ym] = closes[-1]

    sorted_months = sorted(month_last.keys())
    monthly_returns = []
    for i in range(1, len(sorted_months)):
        prev_ym = sorted_months[i - 1]
        cur_ym = sorted_months[i]
        prev_close = month_last[prev_ym]
        cur_close = month_last[cur_ym]
        ret = (cur_close - prev_close) / prev_close
        monthly_returns.append({
            "month": cur_ym,
            "return": ret,
            "prev_close": prev_close,
            "close": cur_close,
        })
    return monthly_returns


def test_claim(market="US"):
    """回测论断 #8"""
    stocks = get_stocks(market)
    total_signals = 0
    total_wins = 0  # 次月上涨的次数
    stock_results = []

    for idx_id, ticker, name in stocks:
        returns = calc_monthly_returns(idx_id)
        if len(returns) < 12:
            continue

        signals = 0
        wins = 0
        for i in range(len(returns) - 1):
            if returns[i]["return"] > 0.30:  # 当月涨幅>30%
                signals += 1
                next_ret = returns[i + 1]["return"]
                if next_ret > 0:
                    wins += 1

        if signals > 0:
            stock_results.append({
                "ticker": ticker,
                "name": name,
                "signals": signals,
                "wins": wins,
                "win_rate": round(wins / signals, 4),
            })
            total_signals += signals
            total_wins += wins

    overall_win_rate = total_wins / total_signals if total_signals > 0 else 0
    # 论断预测: 次月上涨概率 < 40%
    claim_supported = overall_win_rate < 0.40

    return {
        "market": market,
        "market_label": MARKETS[market]["label"],
        "stock_count": len(stocks),
        "stocks_with_signals": len(stock_results),
        "total_signals": total_signals,
        "total_wins": total_wins,
        "overall_win_rate": round(overall_win_rate, 4),
        "claim_threshold": 0.40,
        "claim_supported": claim_supported,
        "per_stock": sorted(stock_results, key=lambda x: -x["signals"])[:20],
    }


def main():
    parser = argparse.ArgumentParser(description="论断#8: 月涨幅>30%回测")
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

    # 人类可读总结
    print()
    print("=" * 50)
    for m, r in results.items():
        verdict = "SUPPORT" if r["claim_supported"] else "REJECT"
        print(f"{r['market_label']}: win_rate={r['overall_win_rate']:.1%} ({r['total_wins']}/{r['total_signals']}) -> {verdict}")
        print(f"   stocks_with_signals={r['stocks_with_signals']}/{r['stock_count']}, total_signals={r['total_signals']}")


if __name__ == "__main__":
    main()
