#!/usr/bin/env python3
"""verify-024-cash-roll-bull.py — 论断 #24: 钱仓滚存牛市跑输持有

测试方法:
  1. 获取所有 US 股票的日线数据, 转换为月末收盘价
  2. 获取 SPY 的月线数据, 计算各月的 6 个月收益
  3. 筛选"牛市"月份 (SPY 6个月收益 > 10%)
  4. 钱仓滚存策略:
     - 每月末, 对所有 US 股票计算当月 (1个月) 动量
     - 按动量排序, 选前 20%
     - 等权重持有 1 个月
  5. 对比钱仓滚存策略 vs SPY 持有人在牛市的收益率

用法:
    python research/110-strategy-verification/024-cash-roll-bull/verify-024-cash-roll-bull.py
"""
import sys, os, json, sqlite3
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, BASE)

DB_PATH = os.path.join(BASE, "data", "market_data.db")

SPY_INDEX_ID = 5
GSPC_INDEX_ID = 1

BULL_THRESHOLD = 0.10  # 6-month SPY return > 10%

MOMENTUM_FRACTION = 0.20  # top 20% by momentum


def get_us_stocks():
    """Get list of US stocks from the indices table."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT id, ticker, name FROM indices WHERE market='US' AND category='stock' ORDER BY ticker"
    ).fetchall()
    conn.close()
    return rows


def get_monthly_closes(index_id):
    """Get {YYYY-MM: close} for a single index/stock.

    Uses the last available close price for each calendar month.
    """
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT date, close FROM daily_data WHERE index_id=? AND close IS NOT NULL ORDER BY date",
        (index_id,)
    ).fetchall()
    conn.close()

    monthly = {}
    for date_str, close in rows:
        monthly[date_str[:7]] = float(close)
    return monthly


def load_all_us_stock_monthly(min_months=24):
    """Load monthly close data for all US stocks.

    Returns:
        dict: {index_id: {"ticker": str, "name": str, "monthly": {YYYY-MM: close}}}
    """
    stocks = get_us_stocks()
    stock_data = {}

    for idx_id, ticker, name in stocks:
        monthly = get_monthly_closes(idx_id)
        if len(monthly) >= min_months:
            stock_data[idx_id] = {
                "ticker": ticker,
                "name": name,
                "monthly": monthly,
            }

    return stock_data


def run_backtest():
    """主回测逻辑 — 钱仓滚存在牛市 vs SPY 持有"""
    print("Loading US stock data...")
    stocks = load_all_us_stock_monthly()
    print(f"Loaded {len(stocks)} US stocks with sufficient data")

    print("Loading SPY data...")
    spy_monthly = get_monthly_closes(SPY_INDEX_ID)
    print(f"SPY has {len(spy_monthly)} monthly data points ({min(spy_monthly.keys())} to {max(spy_monthly.keys())})")

    # Also load ^GSPC monthly as alternative benchmark
    gspc_monthly = get_monthly_closes(GSPC_INDEX_ID)

    # Sort all months that have both SPY data and stock data
    all_months = sorted(spy_monthly.keys())
    if len(all_months) < 7:
        print("ERROR: Not enough SPY monthly data")
        return {"error": "insufficient data"}

    # For each month (index i), compute:
    #   SPY_6m_ret = (close[i] - close[i-6]) / close[i-6]  -- regime classification
    #   If bull (SPY_6m_ret > 10%):
    #     Stock_1m_ret = (close[M_i] - close[M_{i-1}]) / close[M_{i-1}]  -- momentum signal
    #     Cash-roll holding period: all_months[i] -> all_months[i+1]

    bull_results = []
    all_regime_counts = defaultdict(int)

    for i in range(6, len(all_months) - 1):
        month_current = all_months[i]
        month_prev = all_months[i - 1]
        month_next = all_months[i + 1]
        month_6ago = all_months[i - 6]

        # SPY trailing 6-month return
        spy_6m_ret = (spy_monthly[month_current] - spy_monthly[month_6ago]) / spy_monthly[month_6ago]

        # Classify regime
        if spy_6m_ret > BULL_THRESHOLD:
            regime = "bull"
        elif spy_6m_ret < -BULL_THRESHOLD:
            regime = "bear"
        else:
            regime = "neutral"
        all_regime_counts[regime] += 1

        # Only process bull months
        if regime != "bull":
            continue

        # Compute 1-month momentum for each stock
        stock_momentum = []
        for idx_id, info in stocks.items():
            m = info["monthly"]
            if month_prev in m and month_current in m:
                ret_1m = (m[month_current] - m[month_prev]) / m[month_prev]
                stock_momentum.append((idx_id, ret_1m))

        if len(stock_momentum) < 10:
            continue  # not enough stocks to form a meaningful portfolio

        # Rank by momentum (descending), select top 20%
        stock_momentum.sort(key=lambda x: -x[1])
        top_count = max(1, int(len(stock_momentum) * MOMENTUM_FRACTION))
        top_stocks = stock_momentum[:top_count]

        # Compute cash-roll return for next month
        cash_roll_rets = []
        for idx_id, _ in top_stocks:
            m = stocks[idx_id]["monthly"]
            if month_current in m and month_next in m:
                r = (m[month_next] - m[month_current]) / m[month_current]
                cash_roll_rets.append(r)

        if not cash_roll_rets:
            continue

        cash_roll_ret = sum(cash_roll_rets) / len(cash_roll_rets)

        # SPY buy-and-hold return for same period
        spy_ret = (spy_monthly[month_next] - spy_monthly[month_current]) / spy_monthly[month_current]

        # ^GSPC return for same period (if available)
        gspc_ret = None
        if month_current in gspc_monthly and month_next in gspc_monthly:
            gspc_ret = (gspc_monthly[month_next] - gspc_monthly[month_current]) / gspc_monthly[month_current]

        bull_results.append({
            "month": month_current,
            "next_month": month_next,
            "cash_roll_return": round(cash_roll_ret, 6),
            "spy_return": round(spy_ret, 6),
            "gspc_return": round(gspc_ret, 6) if gspc_ret is not None else None,
            "spy_6m_return": round(spy_6m_ret, 6),
            "num_stocks_in_portfolio": len(cash_roll_rets),
            "top_pct_selected": round(len(cash_roll_rets) / len(stock_momentum) * 100, 1) if stock_momentum else 0,
        })

    if not bull_results:
        print("WARNING: No bull months found")
        return {"error": "no bull months found", "total_spy_months": len(all_months)}

    # Aggregate results
    cash_roll_rets = [r["cash_roll_return"] for r in bull_results]
    spy_rets = [r["spy_return"] for r in bull_results]

    avg_cash_roll = sum(cash_roll_rets) / len(cash_roll_rets)
    avg_spy = sum(spy_rets) / len(spy_rets)

    cash_roll_wins = sum(1 for i in range(len(bull_results))
                         if bull_results[i]["cash_roll_return"] > bull_results[i]["spy_return"])
    spy_wins = len(bull_results) - cash_roll_wins

    # Annualized metrics
    ann_cash_roll = (1 + avg_cash_roll) ** 12 - 1
    ann_spy = (1 + avg_spy) ** 12 - 1

    # Standard deviation
    if len(cash_roll_rets) > 1:
        var_cr = sum((r - avg_cash_roll) ** 2 for r in cash_roll_rets) / len(cash_roll_rets)
        std_cr = var_cr ** 0.5
        var_spy = sum((r - avg_spy) ** 2 for r in spy_rets) / len(spy_rets)
        std_spy = var_spy ** 0.5
    else:
        std_cr = 0
        std_spy = 0

    # Cumulative returns
    cum_cash_roll = 1.0
    cum_spy = 1.0
    cum_cash_roll_series = [1.0]
    cum_spy_series = [1.0]
    for entry in bull_results:
        cum_cash_roll *= (1 + entry["cash_roll_return"])
        cum_spy *= (1 + entry["spy_return"])
        cum_cash_roll_series.append(cum_cash_roll)
        cum_spy_series.append(cum_spy)

    # Max drawdown
    def max_dd(series):
        peak = series[0]
        mdd = 0.0
        for v in series[1:]:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0
            if dd > mdd:
                mdd = dd
        return mdd

    cr_max_dd = max_dd(cum_cash_roll_series)
    spy_max_dd = max_dd(cum_spy_series)

    # The claim: "cash-rolling UNDERPERFORMS buy-and-hold in bull markets"
    # So claim_supported = (avg_spy > avg_cash_roll) i.e., SPY beats cash-roll
    claim_supported = avg_spy > avg_cash_roll

    results = {
        "claim": "#24 - 钱仓滚存牛市跑输持有",
        "regime_definition": {
            "bull": f"SPY 6-month return > {BULL_THRESHOLD:.0%}",
            "momentum_fraction": MOMENTUM_FRACTION,
        },
        "data_range": {
            "spy": f"{min(spy_monthly.keys())} to {max(spy_monthly.keys())}",
            "stocks_used": len(stocks),
        },
        "regime_counts": dict(all_regime_counts),
        "bull_month_count": len(bull_results),
        "summary_metrics": {
            "cash_roll": {
                "avg_monthly_return": round(avg_cash_roll, 6),
                "ann_return": round(ann_cash_roll, 6),
                "monthly_std": round(std_cr, 6),
                "max_drawdown": round(cr_max_dd, 6),
                "win_count": cash_roll_wins,
            },
            "spy_buy_and_hold": {
                "avg_monthly_return": round(avg_spy, 6),
                "ann_return": round(ann_spy, 6),
                "monthly_std": round(std_spy, 6),
                "max_drawdown": round(spy_max_dd, 6),
                "win_count": spy_wins,
            },
            "cash_roll_underperformance": {
                "avg_monthly_underperformance": round(avg_spy - avg_cash_roll, 6),
                "ann_underperformance": round(ann_spy - ann_cash_roll, 6),
                "spy_win_rate": round(spy_wins / len(bull_results), 4),
                "total_periods": len(bull_results),
            },
        },
        "claim_supported": claim_supported,
        "monthly_details": bull_results[:120],
        "summary": (
            "如果 SPY 持有人在牛市的平均月收益 > 钱仓滚存, "
            "则论断成立: 牛市中钱仓滚存跑输持有."
        ),
    }

    return results


if __name__ == "__main__":
    results = run_backtest()

    # Write results
    out_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(out_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # Print readable summary
    print()
    print("=" * 65)
    print(f"论断 #24: 钱仓滚存牛市跑输持有")
    if "error" in results:
        print(f"ERROR: {results['error']}")
        print(json.dumps(results, indent=2, ensure_ascii=False))
        sys.exit(0)

    print(f"数据范围: {results['data_range']['spy']}")
    print(f"US 股票数: {results['data_range']['stocks_used']}")
    print()
    print(f"市场状态分布: {json.dumps(results['regime_counts'], ensure_ascii=False)}")
    print(f"牛市月数: {results['bull_month_count']}")
    print()

    sm = results["summary_metrics"]
    print(f"{'策略':>20} | {'月均收益':>10} | {'年化收益':>10} | {'月波动':>8} | {'最大回撤':>10} | {'胜次数':>6}")
    print("-" * 75)
    print(f"{'钱仓滚存':>20} | {sm['cash_roll']['avg_monthly_return']:+>9.4%} | "
          f"{sm['cash_roll']['ann_return']:+>9.4%} | {sm['cash_roll']['monthly_std']:>7.4f} | "
          f"{sm['cash_roll']['max_drawdown']:>9.4%} | {sm['cash_roll']['win_count']:>6}")
    print(f"{'SPY 持有':>20} | {sm['spy_buy_and_hold']['avg_monthly_return']:+>9.4%} | "
          f"{sm['spy_buy_and_hold']['ann_return']:+>9.4%} | {sm['spy_buy_and_hold']['monthly_std']:>7.4f} | "
          f"{sm['spy_buy_and_hold']['max_drawdown']:>9.4%} | {sm['spy_buy_and_hold']['win_count']:>6}")
    print()

    underperform = sm["cash_roll_underperformance"]
    print(f"SPY 月均跑赢钱仓滚存: {underperform['avg_monthly_underperformance']:+>+9.4%}")
    print(f"SPY 年化跑赢钱仓滚存: {underperform['ann_underperformance']:+>+9.4%}")
    print(f"SPY 跑赢概率: {underperform['spy_win_rate']:.1%} ({underperform['total_periods']} 个月)")

    verdict = "✅ SUPPORT" if results["claim_supported"] else "❌ REJECT"
    print(f"\n结论: {verdict}")

    print()
    print(json.dumps({k: v for k, v in results.items() if k != "monthly_details"}, indent=2, ensure_ascii=False))
