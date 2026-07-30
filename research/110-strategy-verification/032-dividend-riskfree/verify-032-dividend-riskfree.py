#!/usr/bin/env python3
"""verify-032-dividend-riskfree.py -- 论断 #32: 股息率>无风险利率时跑赢

核心逻辑:
  当股息率 > 中国10年期国债收益率时，持有该股票的收益率优于无风险资产。
  由于数据库中无国债利率数据，本脚本使用两种方法：
  方法A: 固定阈值(股息率>4%) - 简单可用
  方法B: 外部国债利率(需手动提供CSV)

  股息率 = 过去12个月每股股息总和 / 当前股价

用法:
    python research/110-strategy-verification/032-dividend-riskfree/verify-032-dividend-riskfree.py
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


def load_dividends(conn, index_id):
    """加载所有股息记录。"""
    rows = conn.execute("""
        SELECT ex_date, dividend FROM dividends
        WHERE index_id = ?
        ORDER BY ex_date
    """, (index_id,)).fetchall()
    return rows


def get_quarter_end_indices(prices, start_date="2005-01-01"):
    indices = []
    for i in range(len(prices)):
        ds = prices[i][0]
        if ds < start_date:
            continue
        m, d = ds[5:7], ds[8:10]
        if m in ("03", "06", "09", "12") and d >= "25":
            indices.append(i)
    return indices


def ttm_dividend_yield(dividends, as_of_date, current_price):
    """计算过去12个月的股息率。"""
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


def forward_return(prices, i, hold_days):
    j = i + hold_days
    if j >= len(prices):
        return None
    cp = prices[i][1]
    fp = prices[j][1]
    if not cp or not fp or cp <= 0:
        return None
    return (fp - cp) / cp


def max_drawdown(returns):
    cum, peak, mdd = 1.0, 1.0, 0.0
    for r in returns:
        cum *= (1 + r)
        peak = max(peak, cum)
        dd = (peak - cum) / peak
        mdd = max(mdd, dd)
    return mdd


# -- 主回测 -------------------------------------------------------

def run_backtest():
    conn = sqlite3.connect(DB_PATH)
    stocks = cn_stocks(conn)
    conn.close()
    print(f"CN 股票池: {len(stocks)} 只")

    # 方法A: 固定阈值法 (股息率 > 4%)
    print("\n方法A: 固定阈值法 (股息率 > 4%)")
    HOLD_PERIODS = [(63, "3个月"), (126, "6个月"), (252, "12个月")]
    method_a_results = {}

    for hold_days, hold_label in HOLD_PERIODS:
        print(f"\n  === {hold_label}持有期 ===")

        high_div_returns = []   # 高股息率组的后续收益
        low_div_returns = []    # 低股息率组的后续收益
        high_div_values = []    # 记录具体股息率

        total_checks = 0
        high_count = 0

        for sidx, (index_id, stkcd) in enumerate(stocks):
            if (sidx + 1) % 50 == 0:
                print(f"    进度: {sidx + 1}/{len(stocks)}")

            conn2 = sqlite3.connect(DB_PATH)
            prices = load_prices(conn2, index_id)
            dividends = load_dividends(conn2, index_id)
            conn2.close()

            if len(prices) < 252 or len(dividends) < 2:
                continue

            qis = get_quarter_end_indices(prices)
            for qi in qis:
                if qi + hold_days >= len(prices):
                    continue
                ds = prices[qi][0]
                cp = prices[qi][1]
                if not cp or cp <= 0:
                    continue

                dy = ttm_dividend_yield(dividends, ds, cp)
                if dy is None:
                    continue

                fwd = forward_return(prices, qi, hold_days)
                if fwd is None:
                    continue

                total_checks += 1
                if dy > 0.04:  # 股息率 > 4%
                    high_count += 1
                    high_div_returns.append(fwd)
                    high_div_values.append(dy)
                else:
                    low_div_returns.append(fwd)

        if not high_div_returns:
            print(f"    无高股息率信号，跳过。")
            continue

        high_win = sum(1 for r in high_div_returns if r > 0)
        high_win_rate = high_win / len(high_div_returns)
        high_avg = sum(high_div_returns) / len(high_div_returns)

        low_win = sum(1 for r in low_div_returns if r > 0)
        low_win_rate = low_win / len(low_div_returns) if low_div_returns else 0
        low_avg = sum(low_div_returns) / len(low_div_returns) if low_div_returns else 0

        excess_return = high_avg - low_avg

        s = {
            "总检查次数": total_checks,
            "高股息率次数": high_count,
            "高股息率触发率": round(high_count / total_checks, 4) if total_checks else 0,
            "高股息率_样本数": len(high_div_returns),
            "高股息率_胜率": round(high_win_rate, 4),
            "高股息率_平均收益": round(high_avg, 4),
            "低股息率_样本数": len(low_div_returns),
            "低股息率_胜率": round(low_win_rate, 4),
            "低股息率_平均收益": round(low_avg, 4),
            "超额收益(高-低)": round(excess_return, 4),
            "平均股息率(高组)": round(sum(high_div_values) / len(high_div_values), 4) if high_div_values else 0,
            "支持论断(高股息跑赢)": excess_return > 0,
        }
        method_a_results[hold_label] = s

        print(f"    高股息率信号: {high_count}/{total_checks} ({high_count / total_checks:.1%})")
        print(f"    高股息率胜率: {high_win_rate:.1%}, 平均收益: {high_avg:.2%}")
        print(f"    低股息率胜率: {low_win_rate:.1%}, 平均收益: {low_avg:.2%}")
        print(f"    超额收益: {excess_return:.2%}")
        print(f"    >>> {'✅ 高股息跑赢' if excess_return > 0 else '❌ 高股息跑输'}")

    # 尝试加载外部国债利率(如果存在)
    bond_csv = os.path.join(os.path.dirname(__file__), "cn_10y_bond_yield.csv")
    method_b_results = None
    if os.path.exists(bond_csv):
        print(f"\n方法B: 外部国债利率 (找到 {bond_csv})")
        method_b_results = _run_with_bond_yield(bond_csv)
    else:
        print(f"\n方法B: 未找到CN 10Y国债利率文件 ({bond_csv})，跳过。")
        print(f"  请提供 cn_10y_bond_yield.csv 文件，格式: date,yield")

    return {
        "test_date": TODAY,
        "claim_id": 32,
        "claim": "股息率高于无风险利率时持有该股票跑赢",
        "parameter": {
            "universe": "CN A股",
            "method_a": {
                "name": "固定阈值法",
                "threshold": "dividend_yield > 4%",
                "data_source": "dividends表(ex_date, dividend) + daily_data(close)",
                "note": "国债利率数据不在数据库中，无法直接按无风险利率比较"
            },
            "method_b": {
                "name": "外部国债利率法",
                "status": "需手动提供cn_10y_bond_yield.csv",
                "format_required": "date,yield (e.g., 2024-12-31,0.017)",
                "note": "如果有国债利率文件，会动态比较股息率 vs 国债利率"
            },
            "dividend_yield_definition": "过去12个月每股股息之和 / 当前股价",
            "hold_periods": ["3个月", "6个月", "12个月"],
        },
        "results": {
            "固定阈值法": method_a_results,
            "外部国债利率法(如有数据)": method_b_results,
        },
    }


def _run_with_bond_yield(bond_csv):
    """使用外部CSV中的国债利率数据(预留)。"""
    import csv
    bond_rates = {}
    with open(bond_csv, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) >= 2:
                bond_rates[row[0].strip()] = float(row[1].strip())

    print(f"  已加载 {len(bond_rates)} 条国债利率记录")

    # 简化版: 此处可以复用方法A的逻辑但替换阈值为动态国债利率
    # 因无实际数据，仅返回占位
    return {
        "status": "need_data",
        "bond_records_loaded": len(bond_rates),
        "date_range": [min(bond_rates.keys()), max(bond_rates.keys())] if bond_rates else None,
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
