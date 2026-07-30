#!/usr/bin/env python3
"""verify-033-low-pe-high-roe.py -- 论断 #33: 低PE+高ROE组合长期跑赢市场

策略:
  每季度末，在CN A股中筛选：
  1. PE_TTM 最低的20%（价值因子）
  2. ROE_A 最高的20%（质量因子）
  3. 同时满足两个条件的股票组成等权组合
  4. 持有至下季度末，再平衡
  对比基准: 所有CN股票的等权组合

用法:
    python research/110-strategy-verification/033-low-pe-high-roe/verify-033-low-pe-high-roe.py
"""
import sys, os, json, sqlite3
from datetime import datetime, timedelta
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, BASE)

DB_PATH = os.path.join(BASE, "data", "market_data.db")
TODAY = "2026-07-23"


def cn_stocks(conn):
    rows = conn.execute("""
        SELECT s.index_id, s.stkcd
        FROM stkcd_map s
        JOIN daily_data d ON s.index_id = d.index_id
        WHERE s.matched = 1
        GROUP BY s.index_id
        HAVING COUNT(*) > 1000
    """).fetchall()
    return [(r[0], r[1]) for r in rows]


def load_prices(conn, index_id):
    rows = conn.execute("""
        SELECT date, close FROM daily_data
        WHERE index_id = ? AND close > 0
        ORDER BY date
    """, (index_id,)).fetchall()
    return rows


def nearest_price_index(prices, target_date):
    """找 target_date 当天或之后最近的价格索引。"""
    for i, (ds, _) in enumerate(prices):
        if ds >= target_date:
            return i
    return None


def get_price_at(prices, target_date):
    idx = nearest_price_index(prices, target_date)
    if idx is None:
        return None
    return prices[idx][1]


def max_drawdown(returns):
    cum, peak, mdd = 1.0, 1.0, 0.0
    for r in returns:
        cum *= (1 + r)
        peak = max(peak, cum)
        dd = (peak - cum) / peak
        mdd = max(mdd, dd)
    return mdd


def sharpe_ratio(returns, rf_annual=0.02, periods_per_year=4):
    if len(returns) < 2:
        return 0.0
    avg = sum(returns) / len(returns)
    var = sum((r - avg) ** 2 for r in returns) / (len(returns) - 1)
    std = var ** 0.5
    if std == 0:
        return 0.0
    rf_prd = rf_annual / periods_per_year
    return (avg - rf_prd) / std * (periods_per_year ** 0.5)


# -- 主回测 -------------------------------------------------------

def run_backtest():
    conn = sqlite3.connect(DB_PATH)
    stocks = cn_stocks(conn)
    conn.close()
    print(f"CN 股票池: {len(stocks)} 只")

    # 构建 stock_id -> (index_id, stkcd) 映射
    stock_list = [(iid, stkcd) for iid, stkcd in stocks]
    print(f"实际参与回测: {len(stock_list)} 只")

    # 预加载所有价格数据
    print("\n预加载价格数据...")
    all_prices = {}
    for sidx, (iid, stkcd) in enumerate(stock_list):
        if (sidx + 1) % 50 == 0:
            print(f"  进度: {sidx + 1}/{len(stock_list)}")
        conn2 = sqlite3.connect(DB_PATH)
        all_prices[(iid, stkcd)] = load_prices(conn2, iid)
        conn2.close()

    # 预加载所有财务数据
    print("\n预加载财务数据...")
    all_fin = {}
    for sidx, (iid, stkcd) in enumerate(stock_list):
        if (sidx + 1) % 50 == 0:
            print(f"  进度: {sidx + 1}/{len(stock_list)}")
        conn3 = sqlite3.connect(DB_PATH)
        rows = conn3.execute("""
            SELECT accper, pe_ttm, roe_A, basic_eps_report
            FROM cn_financials
            WHERE stkcd=? AND typrep='A' AND if_correct=0
            ORDER BY accper
        """, (stkcd,)).fetchall()
        conn3.close()
        all_fin[stkcd] = rows

    # 生成季度检查日期列表 (年报/半年报/季报截止日)
    # 标准财务截止日: 03-31, 06-30, 09-30, 12-31
    quarter_end_dates = []
    for year in range(2005, 2027):
        for mm, dd in [("03", "31"), ("06", "30"), ("09", "30"), ("12", "31")]:
            d = f"{year}-{mm}-{dd}"
            if d <= TODAY:
                quarter_end_dates.append(d)

    print(f"\n季度检查点: {len(quarter_end_dates)} 个")

    # 回测逐季度滚动
    strategy_q_returns = []  # 策略各季度收益率
    benchmark_q_returns = [] # 基准各季度收益率

    # 记录每期持仓数量
    positions_count = []

    for qi in range(len(quarter_end_dates) - 1):
        qdate = quarter_end_dates[qi]
        next_qdate = quarter_end_dates[qi + 1]

        if (qi + 1) % 10 == 0:
            print(f"\n季度 {qi + 1}/{len(quarter_end_dates) - 1}: {qdate} -> {next_qdate}")

        candidates = []
        for iid, stkcd in stock_list:
            prices = all_prices.get((iid, stkcd))
            if not prices or len(prices) < 252:
                continue

            fins = all_fin.get(stkcd, [])
            if len(fins) < 4:
                continue

            # 找该季度末的最新财务数据
            latest = None
            for fr in reversed(fins):
                if fr[0] <= qdate:
                    latest = fr
                    break
            if latest is None:
                continue

            accper, pe_ttm, roe, eps = latest
            if pe_ttm is None or pe_ttm <= 0:
                continue
            if roe is None or roe <= 0:
                continue

            # 获取该季度末的股价
            cp = get_price_at(prices, qdate)
            if cp is None or cp <= 0:
                continue

            # 获取下季度末的股价
            fp = get_price_at(prices, next_qdate)
            if fp is None or fp <= 0:
                continue

            candidates.append({
                "index_id": iid,
                "stkcd": stkcd,
                "pe_ttm": pe_ttm,
                "roe_A": roe,
                "price_start": cp,
                "price_end": fp,
                "return": (fp - cp) / cp,
            })

        if len(candidates) < 20:
            continue

        # 排序筛选
        pe_sorted = sorted(candidates, key=lambda x: x["pe_ttm"])
        roe_sorted = sorted(candidates, key=lambda x: -x["roe_A"])

        n_pe = max(1, len(candidates) // 5)  # 最低20%
        n_roe = max(1, len(candidates) // 5)  # 最高20%

        low_pe_set = set(s["stkcd"] for s in pe_sorted[:n_pe])
        high_roe_set = set(s["stkcd"] for s in roe_sorted[:n_roe])

        selected = [c for c in candidates if c["stkcd"] in low_pe_set and c["stkcd"] in high_roe_set]

        if len(selected) < 3:
            # 交集太少时只用低PE组
            selected = [c for c in candidates if c["stkcd"] in low_pe_set]
            if len(selected) < 3:
                continue

        # 策略收益: 等权组合
        strategy_ret = sum(c["return"] for c in selected) / len(selected)
        strategy_q_returns.append(strategy_ret)

        # 基准收益: 所有CN股票等权
        benchmark_ret = sum(c["return"] for c in candidates) / len(candidates)
        benchmark_q_returns.append(benchmark_ret)

        positions_count.append(len(selected))

    # -- 结果计算 --
    if not strategy_q_returns:
        print("无有效回测结果!")
        return {"error": "no_data"}

    # 累积收益
    strat_cum = 1.0
    bench_cum = 1.0
    for sr, br in zip(strategy_q_returns, benchmark_q_returns):
        strat_cum *= (1 + sr)
        bench_cum *= (1 + br)

    n_years = len(strategy_q_returns) / 4
    strat_cagr = strat_cum ** (1 / n_years) - 1 if n_years > 0 else 0
    bench_cagr = bench_cum ** (1 / n_years) - 1 if n_years > 0 else 0

    strat_mdd = max_drawdown(strategy_q_returns)
    bench_mdd = max_drawdown(benchmark_q_returns)

    strat_sharpe = sharpe_ratio(strategy_q_returns)
    bench_sharpe = sharpe_ratio(benchmark_q_returns)

    strat_win = sum(1 for r in strategy_q_returns if r > 0) / len(strategy_q_returns)
    bench_win = sum(1 for r in benchmark_q_returns if r > 0) / len(benchmark_q_returns)

    avg_positions = sum(positions_count) / len(positions_count) if positions_count else 0
    min_positions = min(positions_count) if positions_count else 0
    max_positions = max(positions_count) if positions_count else 0

    results = {
        "回测期间": f"{quarter_end_dates[0]} ~ {quarter_end_dates[len(strategy_q_returns)]}",
        "季度数": len(strategy_q_returns),
        "回测年数": round(n_years, 1),
        "策略_累积收益": round(strat_cum, 4),
        "基准_累积收益": round(bench_cum, 4),
        "策略_CAGR": round(strat_cagr, 4),
        "基准_CAGR": round(bench_cagr, 4),
        "超额年化收益": round(strat_cagr - bench_cagr, 4),
        "策略_最大回撤": round(strat_mdd, 4),
        "基准_最大回撤": round(bench_mdd, 4),
        "策略_夏普比": round(strat_sharpe, 4),
        "基准_夏普比": round(bench_sharpe, 4),
        "策略_胜率": round(strat_win, 4),
        "基准_胜率": round(bench_win, 4),
        "持仓_平均": round(avg_positions, 1),
        "持仓_最少": min_positions,
        "持仓_最多": max_positions,
        "支持论断(CAGR跑赢)": strat_cagr > bench_cagr,
    }

    print(f"\n=== 回测结果 ===")
    print(f"回测期间: {results['回测期间']} ({results['季度数']}个季度)")
    print(f"策略累积收益: {strat_cum:.2%}")
    print(f"基准累积收益: {bench_cum:.2%}")
    print(f"策略CAGR: {strat_cagr:.2%}")
    print(f"基准CAGR: {bench_cagr:.2%}")
    print(f"超额收益: {(strat_cagr - bench_cagr):.2%}")
    print(f"策略最大回撤: {strat_mdd:.2%}")
    print(f"基准最大回撤: {bench_mdd:.2%}")
    print(f"策略夏普比: {strat_sharpe:.2f}")
    print(f"基准夏普比: {bench_sharpe:.2f}")
    print(f"策略胜率: {strat_win:.1%}")
    print(f"基准胜率: {bench_win:.1%}")
    print(f"平均持仓数: {avg_positions:.0f}")
    print(f">>> {'✅ 低PE+高ROE组合跑赢' if strat_cagr > bench_cagr else '❌ 组合跑输'}")

    return {
        "test_date": TODAY,
        "claim_id": 33,
        "claim": "低PE+高ROE组合长期跑赢市场",
        "parameter": {
            "universe": "CN A股",
            "selection_criteria": "PE_TTM最低20% ∩ ROE_A最高20% (交集)",
            "weighting": "equal-weight quarterly rebalance",
            "benchmark": "equal-weight all CN A股",
            "data_range": f"{quarter_end_dates[0]} ~ {quarter_end_dates[-1]}",
        },
        "results": results,
    }


if __name__ == "__main__":
    t0 = time.time()
    results = run_backtest()
    elapsed = time.time() - t0

    out_path = os.path.join(os.path.dirname(__file__), "results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存到: {out_path}")
    print(f"耗时: {elapsed:.0f}s")
    print(json.dumps(results, indent=2, ensure_ascii=False))
