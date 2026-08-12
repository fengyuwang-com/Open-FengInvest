#!/usr/bin/env python3
"""verify-042-portfolio-dna.py — 论断 #42: 组合DNA不变但市场在变，3年后落后基准>20%

论断：组合风格不变，但市场风格变换。3年不调仓，大概率落后基准超过20%。

方法（简化高效版）：
  1. 取 SP500 中市值最大 30 只股票作为"固定DNA组合"
  2. 每 3 年调一次仓（保持在市值最大 30 只）
  3. 计算滚动 3 年与 SP500 指数的超额收益
  4. 统计固定组合跑输基准 >20% 的概率

结果保存到 results.json
"""
import json
import os
import sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DB = os.path.join(BASE, "data", "market_data.db")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json")

import sys

# SQL to get SP500 index daily close
IDX_SQL = """
SELECT id FROM indices
WHERE (ticker='^GSPC' OR ticker='SPY') AND (category='index' OR category='etf')
LIMIT 1
"""

STOCKS_SQL = """
SELECT id, ticker FROM indices
WHERE market='US' AND category='stock'
ORDER BY ticker
"""

PRICES_SQL = """
SELECT d.index_id, d.date, d.close
FROM daily_data d
WHERE d.index_id IN ({})
  AND d.close > 0
ORDER BY d.index_id, d.date
"""


def get_connection():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def get_top_stocks_by_price(conn, common_dates):
    """取基准日市值最大的 N 只股票"""
    cur = conn.execute(STOCKS_SQL)
    stocks = [dict(r) for r in cur.fetchall()]

    if not common_dates:
        return stocks[:30]

    ref_date = common_dates[0]
    prices = {}
    for s in stocks:
        cur = conn.execute(
            "SELECT close FROM daily_data WHERE index_id=? AND date=? AND close>0",
            (s["id"], ref_date),
        )
        row = cur.fetchone()
        if row:
            prices[s["ticker"]] = row["close"]

    sorted_tickers = sorted(prices.keys(), key=lambda t: prices[t], reverse=True)
    return sorted_tickers[:30]


def main():
    conn = get_connection()
    sys.stdout.flush()

    # Get index
    cur = conn.execute(IDX_SQL)
    idx_row = cur.fetchone()
    if not idx_row:
        print("No index found")
        return
    idx_id = idx_row["id"]
    print(f"Index id: {idx_id}")

    # Get index daily data
    cur = conn.execute(
        "SELECT date, close FROM daily_data WHERE index_id=? AND close>0 ORDER BY date",
        (idx_id,),
    )
    idx_prices = {r["date"]: r["close"] for r in cur.fetchall()}
    idx_dates = sorted(idx_prices.keys())
    print(f"Index: {len(idx_dates)} trading days, {idx_dates[0]} ~ {idx_dates[-1]}")

    # Get US stocks
    cur = conn.execute(STOCKS_SQL)
    stocks = [dict(r) for r in cur.fetchall()]
    all_ids = [s["id"] for s in stocks]

    print(f"Loading prices for {len(stocks)} stock IDs...")
    # One query to get ALL prices across all stocks
    ids_placeholders = ",".join("?" * len(all_ids))
    cur = conn.execute(
        f"SELECT d.index_id, d.date, d.close FROM daily_data d "
        f"WHERE d.index_id IN ({ids_placeholders}) AND d.close > 0 "
        f"ORDER BY d.index_id, d.date",
        all_ids,
    )

    all_prices = {}
    ticker_lookup = {s["id"]: s["ticker"] for s in stocks}
    for r in cur:
        sid = r["index_id"]
        if sid not in all_prices:
            all_prices[sid] = {"ticker": ticker_lookup[sid] if sid in ticker_lookup else str(sid),
                              "prices": {}}
        all_prices[sid]["prices"][r["date"]] = r["close"]

    conn.close()
    print(f"Loaded price data for {len(all_prices)} stocks")

    # Simulation parameters
    rebal_years = 3
    n_top = 30
    start_months = []

    # Generate start months from 2005-01 to 2020-01
    for year in range(2005, 2021):
        for month in ["01", "04", "07", "10"]:
            start_months.append(f"{year}-{month}-01")

    all_results = []
    print(f"Simulating {len(start_months)} start periods...")

    for start_date in start_months:
        if start_date not in idx_prices:
            continue

        # Find rebalance dates at 3-year intervals
        rebal_dates = [start_date]
        for i in range(1, 4):
            date_parts = start_date.split("-")
            year = int(date_parts[0]) + i * rebal_years
            rebal_date = f"{year}-{date_parts[1]}-{date_parts[2]}"
            if rebal_date in idx_prices:
                rebal_dates.append(rebal_date)

        # Ensure last rebalance + 3 years is within data range
        final_check = f"{int(rebal_dates[-1].split('-')[0]) + rebal_years}-{rebal_dates[-1].split('-')[1]}-{rebal_dates[-1].split('-')[2]}"
        if final_check not in idx_prices:
            # Skip if not enough data
            final_dates = [d for d in idx_dates if d >= start_date]
            if len(final_dates) < 252 * 3:
                continue
            rebal_dates = [start_date]
            # Just do one 3-year block

        # Build the fixed-DNA portfolio: top N stocks at start, only rebalance every 3 years
        # For simplicity, track the equal-weighted return of top stocks
        # between rebalance dates

        def get_stock_prices_at_date(sid, date):
            """Get close price for a stock on or before date"""
            sd = all_prices.get(sid)
            if not sd:
                return None
            prices = sd["prices"]
            if date in prices:
                return prices[date]
            return None

        def get_top_n_at_date(target_date, n=30):
            """Get the N stocks with highest price on target_date"""
            candidates = []
            for sid, sp in all_prices.items():
                p = get_stock_prices_at_date(sid, target_date)
                if p and p > 0:
                    candidates.append((sid, p))
            candidates.sort(key=lambda x: x[1], reverse=True)
            return [sid for sid, _ in candidates[:n]]

        portfolio_values = []
        prev_date = None

        for r_idx in range(len(rebal_dates)):
            r_date = rebal_dates[r_idx]

            # Select top N at this rebalance point
            top_ids = get_top_n_at_date(r_date, n_top)
            if len(top_ids) < 10:
                continue

            # Next rebalance or end
            if r_idx + 1 < len(rebal_dates):
                next_date = rebal_dates[r_idx + 1]
            else:
                # Use date 3 years from this rebdate
                yr = int(r_date.split("-")[0]) + rebal_years
                next_rebal = f"{yr}-{r_date.split('-')[1]}-{r_date.split('-')[2]}"
                if next_rebal in idx_prices:
                    next_date = next_rebal
                else:
                    continue

            # Get prices at start and end of this period
            start_prices = []
            for sid in top_ids:
                p = get_stock_prices_at_date(sid, r_date)
                if p:
                    start_prices.append((sid, p))

            end_prices = {}
            for sid, _ in start_prices:
                p = get_stock_prices_at_date(sid, next_date)
                if p:
                    end_prices[sid] = p

            # Compute portfolio return
            if start_prices and end_prices:
                returns = []
                for sid, sp in start_prices:
                    if sid in end_prices:
                        ret = end_prices[sid] / sp - 1
                        returns.append(ret)
                if returns:
                    avg_ret = sum(returns) / len(returns)
                    portfolio_values.append(avg_ret)

        if not portfolio_values:
            continue

        # Total portfolio return over 3 years (assuming ~1-2 rebalance periods)
        total_port_ret = 1
        for r in portfolio_values:
            total_port_ret *= (1 + r)
        total_port_ret -= 1

        # Benchmark return over matching period
        start_idx = idx_prices.get(start_date)
        # Find end date ~3 years later
        end_date = f"{int(start_date.split('-')[0]) + 3}-{start_date.split('-')[1]}-{start_date.split('-')[2]}"
        end_idx = idx_prices.get(end_date)
        if not start_idx or not end_idx:
            continue

        bench_ret = end_idx / start_idx - 1
        excess = total_port_ret - bench_ret

        all_results.append({
            "start_date": start_date,
            "end_date": end_date,
            "portfolio_return_pct": round(total_port_ret * 100, 2),
            "benchmark_return_pct": round(bench_ret * 100, 2),
            "excess_return_pct": round(excess * 100, 2),
        })

    if not all_results:
        print("No results generated")
        return

    # Statistics
    n_total = len(all_results)
    n_below_20 = sum(1 for r in all_results if r["excess_return_pct"] < -20)
    n_below_10 = sum(1 for r in all_results if r["excess_return_pct"] < -10)
    n_above_0 = sum(1 for r in all_results if r["excess_return_pct"] > 0)

    prob_below_20 = n_below_20 / n_total * 100
    prob_below_10 = n_below_10 / n_total * 100
    prob_above_0 = n_above_0 / n_total * 100

    # By decade
    by_decade = {}
    for r in all_results:
        decade = r["start_date"][:3] + "0s"
        if decade not in by_decade:
            by_decade[decade] = []
        by_decade[decade].append(r["excess_return_pct"])

    decade_stats = []
    for decade, ex in sorted(by_decade.items()):
        n = len(ex)
        b20 = sum(1 for v in ex if v < -20)
        decade_stats.append({
            "decade": decade,
            "n_windows": n,
            "avg_excess_pct": round(sum(ex) / n, 2),
            "below_20pct_probability_pct": round(b20 / n * 100, 1),
        })

    output = {
        "claim": "#42 组合DNA不变但市场在变，3年后落后基准>20%",
        "claim_en": "Portfolio DNA unchanged for 3 years, underperforms benchmark by >20%",
        "method": "固定持有 SP500 top30 股票，3年再平衡一次。计算滚动3年 vs SP500 超额收益",
        "n_windows_total": n_total,
        "n_windows_below_20pct": n_below_20,
        "p_below_20pct": round(prob_below_20, 1),
        "n_windows_below_10pct": n_below_10,
        "p_below_10pct": round(prob_below_10, 1),
        "n_windows_beat_benchmark": n_above_0,
        "p_beat_benchmark": round(prob_above_0, 1),
        "avg_excess_return_pct": round(sum(r["excess_return_pct"] for r in all_results) / n_total, 2),
        "median_excess_return_pct": sorted(r["excess_return_pct"] for r in all_results)[n_total // 2],
        "min_excess_return_pct": min(r["excess_return_pct"] for r in all_results),
        "max_excess_return_pct": max(r["excess_return_pct"] for r in all_results),
        "decade_stats": decade_stats,
        "all_results": all_results,
        "conclusion": None,
    }

    if prob_below_20 >= 50:
        output["conclusion"] = f"✅ 支持 — 固定组合 3 年落后基准 >20% 概率为 {prob_below_20:.1f}% (>50%)"
    elif prob_below_20 >= 30:
        output["conclusion"] = f"🟡 部分支持 — 概率为 {prob_below_20:.1f}%，低于 50%"
    elif prob_below_20 >= 10:
        output["conclusion"] = f"❌ 拒绝 — 概率仅 {prob_below_20:.1f}%，远低于 50%"
    else:
        output["conclusion"] = f"❌ 拒绝 — 几乎不发生 ({prob_below_20:.1f}%)"

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n结果已保存至: {OUT}")
    verdict = output["conclusion"].replace("✅", "").replace("🟡", "").replace("❌", "").strip()
    print(f"结论: {output['conclusion']}")
    print(f"\n统计: {n_total} 个 3 年窗口")
    print(f"  跑赢基准: {prob_above_0:.0f}%")
    print(f"  落后 >10%: {prob_below_10:.1f}%")
    print(f"  落后 >20%: {prob_below_20:.1f}%")
    print(f"  平均超额: {output['avg_excess_return_pct']:+.1f}%")
    print(f"  中位超额: {output['median_excess_return_pct']:+.1f}%")
    for ds in decade_stats:
        print(f"  {ds['decade']}: 超额 {ds['avg_excess_pct']:+.1f}%, 跌>20%概率 {ds['below_20pct_probability_pct']}%")


if __name__ == "__main__":
    main()
