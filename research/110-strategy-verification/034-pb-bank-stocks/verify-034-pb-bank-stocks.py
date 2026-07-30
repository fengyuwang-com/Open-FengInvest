#!/usr/bin/env python3
"""verify-034-pb-bank-stocks.py -- 论断 #34: PB<1+股息率>3%的银行股有超额收益

策略:
  每季度末筛选银行股(industry_csrc='J66')。
  选择 PB<1 且 股息率>3% 的银行股组成等权组合。
  对比基准: 所有银行股的等权组合。
  验证超额收益是否显著。

用法:
    python research/110-strategy-verification/034-pb-bank-stocks/verify-034-pb-bank-stocks.py
"""
import sys, os, json, sqlite3
from datetime import datetime, timedelta
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, BASE)

DB_PATH = os.path.join(BASE, "data", "market_data.db")
TODAY = "2026-07-23"


def bank_stocks(conn):
    """返回银行股列表 (industry_csrc='J66' = 货币金融服务)。"""
    rows = conn.execute("""
        SELECT DISTINCT c.stkcd
        FROM cn_financials c
        WHERE c.industry_csrc = 'J66'
    """).fetchall()
    return [r[0] for r in rows]


def load_prices(conn, index_id):
    rows = conn.execute("""
        SELECT date, close FROM daily_data
        WHERE index_id = ? AND close > 0
        ORDER BY date
    """, (index_id,)).fetchall()
    return rows


def load_dividends(conn, index_id):
    rows = conn.execute("""
        SELECT ex_date, dividend FROM dividends
        WHERE index_id = ?
        ORDER BY ex_date
    """, (index_id,)).fetchall()
    return rows


def get_price_at(prices, target_date):
    for ds, close in prices:
        if ds >= target_date:
            return close
    return None


def ttm_dividend_yield(dividends, as_of_date, current_price):
    if not current_price or current_price <= 0:
        return None
    as_of = as_of_date
    one_year_ago = str(int(as_of[:4]) - 1) + as_of[4:]
    total_div = 0.0
    for ex_date, div in dividends:
        if one_year_ago <= ex_date <= as_of and div is not None and div > 0:
            total_div += div
    if total_div <= 0:
        return None
    return total_div / current_price


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
    bank_list = bank_stocks(conn)
    print(f"银行股池: {len(bank_list)} 只 (industry_csrc='J66')")

    # 映射 stkcd -> index_id (取第一个)
    stkcd_to_idx = {}
    for stkcd in bank_list:
        row = conn.execute(
            "SELECT index_id FROM stkcd_map WHERE stkcd=? AND matched=1 LIMIT 1",
            (stkcd,)
        ).fetchone()
        if row:
            stkcd_to_idx[stkcd] = row[0]

    print(f"有价格数据的银行股: {len(stkcd_to_idx)} 只")
    conn.close()

    # 预加载价格和股息数据
    print("\n预加载数据...")
    bank_data = {}
    for stkcd, iid in stkcd_to_idx.items():
        conn2 = sqlite3.connect(DB_PATH)
        prices = load_prices(conn2, iid)
        dividends = load_dividends(conn2, iid)
        conn2.close()

        # 财务数据(PB)
        conn3 = sqlite3.connect(DB_PATH)
        fins = conn3.execute("""
            SELECT accper, pb, pe_ttm, roe_A, market_cap_A, basic_eps_report
            FROM cn_financials
            WHERE stkcd=? AND typrep='A' AND if_correct=0
            ORDER BY accper
        """, (stkcd,)).fetchall()
        conn3.close()

        bank_data[stkcd] = {
            "index_id": iid,
            "prices": prices,
            "dividends": dividends,
            "financials": fins,
        }

    # 季度末日期
    quarter_end_dates = []
    for year in range(2005, 2027):
        for mm, dd in [("03", "31"), ("06", "30"), ("09", "30"), ("12", "31")]:
            d = f"{year}-{mm}-{dd}"
            if d <= TODAY:
                quarter_end_dates.append(d)

    print(f"季度检查点: {len(quarter_end_dates)} 个")

    # 回测
    strategy_q_returns = []  # 选中的银行股等权组合
    benchmark_q_returns = [] # 全部银行股等权组合
    selected_counts = []

    for qi in range(len(quarter_end_dates) - 1):
        qdate = quarter_end_dates[qi]
        next_qdate = quarter_end_dates[qi + 1]

        all_candidates = []
        selected_candidates = []

        for stkcd, data in bank_data.items():
            prices = data["prices"]
            dividends = data["dividends"]
            fins = data["financials"]

            if not prices or len(prices) < 252:
                continue

            # 该季度末最新财务数据
            latest_fin = None
            for fr in reversed(fins):
                if fr[0] <= qdate:
                    latest_fin = fr
                    break
            if latest_fin is None:
                continue

            accper, pb, pe_ttm, roe, mcap, eps = latest_fin

            # 股价
            cp = get_price_at(prices, qdate)
            if cp is None or cp <= 0:
                continue

            fp = get_price_at(prices, next_qdate)
            if fp is None or fp <= 0:
                continue

            ret = (fp - cp) / cp

            # 股息率
            dy = ttm_dividend_yield(dividends, qdate, cp)

            all_candidates.append({
                "stkcd": stkcd,
                "pb": pb,
                "dividend_yield": dy,
                "return": ret,
            })

            # 检查筛选条件: PB<1 AND 股息率>3%
            if pb is not None and pb < 1 and dy is not None and dy > 0.03:
                selected_candidates.append({
                    "stkcd": stkcd,
                    "pb": pb,
                    "dividend_yield": dy,
                    "return": ret,
                })

        if len(all_candidates) < 3:
            continue

        # 基准: 所有银行股等权
        bench_ret = sum(c["return"] for c in all_candidates) / len(all_candidates)
        benchmark_q_returns.append(bench_ret)

        # 策略: 选中银行股等权
        if len(selected_candidates) >= 1:
            strat_ret = sum(c["return"] for c in selected_candidates) / len(selected_candidates)
            strategy_q_returns.append(strat_ret)
            selected_counts.append(len(selected_candidates))
        else:
            # 无选中股票时，策略收益为0
            strategy_q_returns.append(0.0)
            selected_counts.append(0)

    # -- 结果计算 --
    if not strategy_q_returns:
        print("无有效回测结果!")
        return {"error": "no_data"}

    # 累积
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

    avg_sel = sum(selected_counts) / len(selected_counts) if selected_counts else 0

    results = {
        "银行股总数": len(bank_list),
        "有数据银行股数": len(stkcd_to_idx),
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
        "平均每期选中数": round(avg_sel, 1),
        "支持论断(超额>0)": strat_cagr > bench_cagr,
    }

    print(f"\n=== 回测结果 ===")
    print(f"银行股池: {len(bank_list)} 只, 有数据: {len(stkcd_to_idx)} 只")
    print(f"回测期间: {results['回测期间']} ({results['季度数']}个季度)")
    print(f"策略累积收益: {strat_cum:.2%}")
    print(f"基准(全部银行股)累积收益: {bench_cum:.2%}")
    print(f"策略CAGR: {strat_cagr:.2%}")
    print(f"基准CAGR: {bench_cagr:.2%}")
    print(f"超额年化收益: {(strat_cagr - bench_cagr):.2%}")
    print(f"策略最大回撤: {strat_mdd:.2%}")
    print(f"基准最大回撤: {bench_mdd:.2%}")
    print(f"平均每期选中股票数: {avg_sel:.0f}")
    print(f">>> {'✅ PB<1+股息率>3%银行股有超额' if strat_cagr > bench_cagr else '❌ 无显著超额'}")

    return {
        "test_date": TODAY,
        "claim_id": 34,
        "claim": "PB<1且股息率>3%的银行股有超额收益",
        "parameter": {
            "universe": "CN银行股 (industry_csrc='J66')",
            "filter": "PB < 1 AND TTM_dividend_yield > 3%",
            "weighting": "equal-weight quarterly rebalance",
            "benchmark": "equal-weight all bank stocks",
            "data_range": f"{quarter_end_dates[0]} ~ {quarter_end_dates[-1]}",
            "dividend_source": "dividends表(ex_date, dividend), TTM=过去12个月",
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
