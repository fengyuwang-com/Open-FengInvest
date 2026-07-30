#!/usr/bin/env python3
"""verify-028-dip-checking.py — 论断 #28: 下跌>15%时启动基本面检查

买入后继续下跌>15%时启动基本面检查：
- 如果基本面不变 → 持有
- 如果基本面恶化 → 割
此规则比无规则硬扛减少回撤>20%。

H0: 有规则 vs 无规则无差异。

测试方法:
  1. 对每只股票，在每个买入点（随机月份起点）跟踪后续价格
  2. 当回撤 >15% 时：
     - 组合 A: 硬扛不动（继续持有）
     - 组合 B: 止损退出
     - 组合 C（如 fundamentals 可用）: 检查基本面，恶化则割，不变则持有
  3. 比较三组合在 [20, 63, 126] 个交易日后的最大回撤

用法:
    python research/110-strategy-verification/028-dip-checking/verify-028-dip-checking.py
    python research/110-strategy-verification/028-dip-checking/verify-028-dip-checking.py --all-markets
    python research/110-strategy-verification/028-dip-checking/verify-028-dip-checking.py --use-fundamentals  (when data available)
"""
import sys, os, json, sqlite3
from collections import defaultdict
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, BASE)

DB_PATH = os.path.join(BASE, "data", "market_data.db")

DRAWDOWN_THRESHOLD = 0.15
LOOKAHEAD_DAYS = [20, 63, 126]


class TickerDB:
    def __init__(self, db_path=DB_PATH):
        self.conn = sqlite3.connect(db_path)

    def get_stocks(self, market=None):
        q = ("SELECT id, ticker, name, market FROM indices "
             "WHERE category='stock'")
        params = []
        if market:
            q += " AND market=?"
            params.append(market)
        q += " ORDER BY market, id"
        return self.conn.execute(q, params).fetchall()

    def get_prices(self, index_id):
        return self.conn.execute(
            "SELECT date, close FROM daily_data "
            "WHERE index_id=? AND close IS NOT NULL ORDER BY date",
            (index_id,)
        ).fetchall()

    def get_fundamentals(self, index_id):
        """Return the latest fundamentals row for a stock, or None."""
        row = self.conn.execute(
            "SELECT trailing_pe, price_to_book, return_on_equity, "
            "       free_cashflow, debt_to_equity, revenue_growth, "
            "       earnings_growth, profit_margin "
            "FROM fundamentals WHERE index_id=? ORDER BY updated_at DESC LIMIT 1",
            (index_id,)
        ).fetchone()
        return row

    def close(self):
        self.conn.close()


def parse_dates(data):
    """Convert (date_str, close) list to datetime-keyed dict."""
    dates = []
    prices = []
    for dstr, close in data:
        dates.append(datetime.strptime(dstr, "%Y-%m-%d"))
        prices.append(float(close))
    return dates, prices


def max_drawdown(values):
    """Max drawdown from a nav series (values[0] = 1.0)."""
    peak = values[0]
    md = 0.0
    for v in values[1:]:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        md = max(md, dd)
    return md


def simulate(ticker_name, dates, prices, use_fundamentals=False, fund_data=None):
    """Simulate dip scenarios for one stock.

    For every possible entry point (each trading day):
      - Track subsequent prices
      - If price drops >15% from entry, record the trigger
      - Compare: hold (A) vs cut (B) vs fundamentals-checked (C)

    Returns accumulated drawdown lists for each lookahead window.
    """
    # We'll sample entry points every 20 trading days to keep computation bounded
    n = len(prices)
    step = max(1, n // 200)  # ~200 entry points per stock max

    results = {d: {"A_dd": [], "B_dd": [], "C_dd": []} for d in LOOKAHEAD_DAYS}
    if fund_data is not None:
        fund_data = tuple(fund_data)

    for entry_idx in range(0, n, step):
        entry_price = prices[entry_idx]
        if entry_price <= 0:
            continue

        # Find first -15% drawdown point from entry
        dip_idx = None
        for j in range(entry_idx + 1, n):
            ret = (prices[j] - entry_price) / entry_price
            if ret <= -DRAWDOWN_THRESHOLD:
                dip_idx = j
                break

        if dip_idx is None:
            continue  # No -15% dip from this entry point

        for days in LOOKAHEAD_DAYS:
            end = dip_idx + days + 1
            if end > n:
                continue

            # Get post-dip prices
            dip_price = prices[dip_idx]
            post_prices = prices[dip_idx:end]

            # Combination A: Hold (nav stays in market)
            nav_hold = [1.0]
            for p in post_prices[1:]:
                nav_hold.append(p / dip_price)
            dd_hold = max_drawdown(nav_hold)
            results[days]["A_dd"].append(dd_hold)

            # Combination B: Cut (exit at -15%, move to cash)
            # After cutting, nav = 0.85 * (1 + 2% annual cash) ≈ stays flat
            nav_cut = [1.0]
            for _ in post_prices[1:]:
                nav_cut.append(0.85)  # 85% of original, no further loss
            dd_cut = max_drawdown(nav_cut)
            results[days]["B_dd"].append(dd_cut)

            # Combination C: Check fundamentals (only if available)
            if use_fundamentals and fund_data is not None:
                # Simplified: if PE > 50 or ROE < 0 or FCF < 0 → "恶化"
                # Otherwise → "不变" (hold)
                pe, pb, roe, fcf, d_e, rev_g, earn_g, prof_m = fund_data
                deteriorated = False
                if pe is not None and pe > 50:
                    deteriorated = True
                if roe is not None and roe < 0:
                    deteriorated = True
                if fcf is not None and fcf < 0:
                    deteriorated = True

                if deteriorated:
                    nav_ck = nav_cut  # Cut
                else:
                    nav_ck = nav_hold  # Hold
                dd_ck = max_drawdown(nav_ck)
                results[days]["C_dd"].append(dd_ck)

    return results


def run_one_market(market, use_fundamentals=False):
    db = TickerDB()
    stocks = db.get_stocks(market)
    print(f"[{market}] Processing {len(stocks)} stocks...")

    agg = {d: {"A_dd": [], "B_dd": [], "C_dd": []} for d in LOOKAHEAD_DAYS}
    stock_details = []
    total_signals = 0

    for idx_id, ticker, name, mkt in stocks:
        try:
            data = db.get_prices(idx_id)
        except Exception:
            continue
        if len(data) < 252:
            continue

        dates, prices = parse_dates(data)

        fund_row = None
        if use_fundamentals:
            fund_row = db.get_fundamentals(idx_id)

        results = simulate(ticker, dates, prices,
                           use_fundamentals=use_fundamentals,
                           fund_data=fund_row)

        n_signals = 0
        for d in LOOKAHEAD_DAYS:
            agg[d]["A_dd"].extend(results[d]["A_dd"])
            agg[d]["B_dd"].extend(results[d]["B_dd"])
            agg[d]["C_dd"].extend(results[d]["C_dd"])
            n_signals = max(n_signals, len(results[d]["A_dd"]))

        total_signals += n_signals
        if results[LOOKAHEAD_DAYS[0]]["A_dd"]:
            stock_details.append({
                "ticker": ticker,
                "signals": n_signals
            })

    db.close()

    # Build result
    result = {"market": market, "stocks_processed": len(stocks),
              "stocks_with_signals": len(stock_details),
              "total_signal_entries": total_signals}

    for days in LOOKAHEAD_DAYS:
        a_list = agg[days]["A_dd"]
        b_list = agg[days]["B_dd"]
        c_list = agg[days]["C_dd"]

        entry = {"n": len(a_list)}
        if a_list:
            entry["avg_dd_hold_A"] = round(sum(a_list) / len(a_list), 4)
        if b_list:
            entry["avg_dd_cut_B"] = round(sum(b_list) / len(b_list), 4)
        if a_list and b_list:
            avg_a = sum(a_list) / len(a_list)
            avg_b = sum(b_list) / len(b_list)
            if avg_a > 0:
                entry["reduction_cut_vs_hold_pct"] = round((avg_a - avg_b) / avg_a * 100, 2)
            entry["reduction_gt_20pct"] = avg_b <= avg_a * 0.8
        if use_fundamentals and c_list:
            entry["avg_dd_check_C"] = round(sum(c_list) / len(c_list), 4)
            if a_list:
                avg_c = sum(c_list) / len(c_list)
                avg_a = sum(a_list) / len(a_list)
                if avg_a > 0:
                    entry["reduction_check_vs_hold_pct"] = round((avg_a - avg_c) / avg_a * 100, 2)
                entry["check_better_than_hold"] = avg_c < avg_a
                entry["check_better_than_cut"] = avg_c < avg_b if b_list else None

        result[f"lookahead_{days}"] = entry

    return result


def main():
    markets = ["US"]
    use_fundamentals = "--use-fundamentals" in sys.argv or "-f" in sys.argv
    if "--all-markets" in sys.argv:
        markets = ["US", "CN", "HK"]
        # HK often has less data, include it anyway
    elif "-m" in sys.argv:
        idx = sys.argv.index("-m")
        if idx + 1 < len(sys.argv):
            markets = [sys.argv[idx + 1]]

    all_results = {}
    for m in markets:
        res = run_one_market(m, use_fundamentals=use_fundamentals)
        all_results[m] = res
        print(f"\n[{m}] Summary:")
        for days in LOOKAHEAD_DAYS:
            e = res.get(f"lookahead_{days}", {})
            if e.get("n", 0) > 0:
                print(f"  {days}d: hold_dd={e.get('avg_dd_hold_A','?')} "
                      f"cut_dd={e.get('avg_dd_cut_B','?')} "
                      f"reduction={e.get('reduction_cut_vs_hold_pct','?')}%")

    print("\n" + json.dumps(all_results, indent=2, ensure_ascii=False))

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved: {out_path}")


if __name__ == "__main__":
    main()
