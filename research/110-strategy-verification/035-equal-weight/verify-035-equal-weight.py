#!/usr/bin/env python3
"""verify-035-equal-weight.py — 论断 #35: 等权组合跑赢市值加权

核心逻辑：
  S&P 500 等权重组合（每月再平衡）的长期年化收益和风险调整收益，
  是否优于市值加权组合（即指数本身）。
"""
import sys, os, json, sqlite3, time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, BASE)

DB_PATH = os.path.join(BASE, "data", "market_data.db")
TODAY = "2026-07-23"


def run_backtest():
    conn = sqlite3.connect(DB_PATH)

    # 获取 S&P 500 成分股
    stocks = conn.execute("""
        SELECT i.id, i.ticker, i.id as index_id
        FROM indices i
        WHERE i.market='US' AND i.category='stock'
        ORDER BY i.ticker
    """).fetchall()
    print(f"US 股票池: {len(stocks)} 只")

    if len(stocks) == 0:
        print("⚠️  无数据，可能 indices 表结构不同")
        conn.close()
        return {"error": "no stock data"}

    # 等权重组合：每月初重新平衡，每只股票等权
    # 先从 2010-01 到 2025-12
    import datetime
    months = []
    for y in range(2010, 2026):
        for m in range(1, 13):
            months.append(f"{y}-{m:02d}-01")
    months.append("2025-12-01")

    ew_returns = []  # 等权组合月收益
    mw_returns = []  # 市值加权月收益

    for i in range(len(months) - 1):
        m1, m2 = months[i], months[i + 1]
        m_start = m1[:7]
        m_end = m2[:7]

        stock_returns = []
        market_caps = []

        for sid, ticker, idx_id in stocks:
            # 月初价格
            row1 = conn.execute("""
                SELECT close FROM daily_data
                WHERE index_id=? AND date >= ? AND date < ?
                ORDER BY date LIMIT 1
            """, (idx_id, m1, m1[:8] + "28")).fetchone()

            # 月末价格
            row2 = conn.execute("""
                SELECT close FROM daily_data
                WHERE index_id=? AND date >= ? AND date < ?
                ORDER BY date DESC LIMIT 1
            """, (idx_id, m2, m2[:8] + "28")).fetchone()

            if row1 and row2 and row1[0] > 0 and row2[0] > 0:
                r = (row2[0] - row1[0]) / row1[0]
                stock_returns.append(r)
                # 市值用 index_id 近似 (只用是否有数据来标记)
                market_caps.append(1.0)  # 每月无法拿到准确市值，简化处理

        if len(stock_returns) < 50:
            continue

        # 等权
        ew_r = sum(stock_returns) / len(stock_returns)
        ew_returns.append(ew_r)

        # 市值加权 (近似: 用月初价格 * 1股 ≈ 价格作为权重)
        # 更准确的应该用市值，但我们没有每月的市值数据
        # 这里用价格近似 (高价股=大公司)
        prices_1 = []
        for sid, ticker, idx_id in stocks:
            row1_p = conn.execute("""
                SELECT close FROM daily_data
                WHERE index_id=? AND date >= ? AND date < ?
                ORDER BY date LIMIT 1
            """, (idx_id, m1, m1[:8] + "28")).fetchone()
            if row1_p and row1_p[0] > 0:
                prices_1.append(row1_p[0])

        if len(prices_1) < 50:
            continue

        total_mcap = sum(prices_1)
        weighted_sum = 0
        for j, r in enumerate(stock_returns):
            w = prices_1[j] / total_mcap
            weighted_sum += w * r
        mw_returns.append(weighted_sum)

    if not ew_returns or not mw_returns:
        print("⚠️  没有足够的月度数据")
        conn.close()
        return {"error": "insufficient data"}

    # 年化
    n = len(ew_returns)
    ew_cagr = (1 + sum(ew_returns)) ** (12 / n) - 1 if len(ew_returns) > 0 else 0
    mw_cagr = (1 + sum(mw_returns)) ** (12 / n) - 1 if len(mw_returns) > 0 else 0

    ew_maxdd = max_drawdown(ew_returns)
    mw_maxdd = max_drawdown(mw_returns)

    ew_sharpe = (sum(ew_returns) / len(ew_returns) - 0.02 / 12) / (std(ew_returns) + 1e-10) * (12 ** 0.5)
    mw_sharpe = (sum(mw_returns) / len(mw_returns) - 0.02 / 12) / (std(mw_returns) + 1e-10) * (12 ** 0.5)

    ew_win = sum(1 for r in ew_returns if r > 0) / len(ew_returns)
    mw_win = sum(1 for r in mw_returns if r > 0) / len(mw_returns)

    results = {
        "test_date": TODAY,
        "claim_id": 35,
        "claim": "等权组合跑赢市值加权",
        "period": f"{months[0][:7]} ~ {months[-2][:7]}",
        "monthly_periods": n,
        "stock_count": len(stocks),
        "equal_weight": {
            "年化收益": round(ew_cagr, 4),
            "最大回撤": round(ew_maxdd, 4),
            "夏普比率": round(ew_sharpe, 2),
            "月胜率": round(ew_win, 4),
        },
        "market_weight": {
            "年化收益": round(mw_cagr, 4),
            "最大回撤": round(mw_maxdd, 4),
            "夏普比率": round(mw_sharpe, 2),
            "月胜率": round(mw_win, 4),
        },
        "conclusion": "✅ 支持" if ew_cagr > mw_cagr else "❌ 拒绝",
    }

    print(f"等权组合: CAGR={ew_cagr:.1%}, MaxDD={ew_maxdd:.1%}, Sharpe={ew_sharpe:.2f}")
    print(f"市值加权: CAGR={mw_cagr:.1%}, MaxDD={mw_maxdd:.1%}, Sharpe={mw_sharpe:.2f}")
    print(f"结论: {results['conclusion']}")

    conn.close()
    return results


def max_drawdown(returns):
    if not returns:
        return 0
    cum = 1
    peak = 1
    mdd = 0
    for r in returns:
        cum *= (1 + r)
        peak = max(peak, cum)
        dd = (peak - cum) / peak
        mdd = max(mdd, dd)
    return mdd


def std(values):
    if len(values) < 2:
        return 0
    avg = sum(values) / len(values)
    var = sum((v - avg) ** 2 for v in values) / (len(values) - 1)
    return var ** 0.5


if __name__ == "__main__":
    t0 = time.time()
    results = run_backtest()
    elapsed = time.time() - t0

    out_path = os.path.join(os.path.dirname(__file__), "results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n耗时: {elapsed:.0f}s")
