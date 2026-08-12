#!/usr/bin/env python3
"""verify-031-safety-margin.py -- 论断 #31: 安全边际>30%时买入胜率>80%

核心逻辑:
  安全边际 = (内在价值 - 当前价格) / 内在价值
  内在价值 = 历史中位数PE * 当前EPS(ttm)
  当安全边际 > 30% 时买入，检查未来1/2/3年收益的正收益概率。

用法:
    python research/110-strategy-verification/031-safety-margin/verify-031-safety-margin.py
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


def load_financials(conn, stkcd):
    """含 PE_TTM 和 EPS (basic_eps_report)。"""
    rows = conn.execute("""
        SELECT accper, pe_ttm, basic_eps_report, parent_net_profit, total_revenue
        FROM cn_financials
        WHERE stkcd = ? AND typrep = 'A' AND if_correct = 0
        ORDER BY accper
    """, (stkcd,)).fetchall()
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


def latest_financial(fin_records, as_of_date):
    for fr in reversed(fin_records):
        if fr[0] <= as_of_date:
            return fr
    return None


def forward_return(prices, i, hold_days):
    j = i + hold_days
    if j >= len(prices):
        return None
    cp = prices[i][1]
    fp = prices[j][1]
    if not cp or not fp or cp <= 0:
        return None
    return (fp - cp) / cp


# -- 主回测 -------------------------------------------------------

def run_backtest():
    conn = sqlite3.connect(DB_PATH)
    stocks = cn_stocks(conn)
    conn.close()
    print(f"CN 股票池: {len(stocks)} 只")

    HOLD_MAP = {252: "1年", 504: "2年", 756: "3年"}
    results_by_hold = {}

    for hold_days, hold_label in HOLD_MAP.items():
        print(f"\n=== {hold_label}持有期 ===")

        # 分组: 有安全边际 vs 无安全边际
        margin_returns = []    # 安全边际>30%时的收益
        no_margin_returns = []  # 安全边际<=30%时的收益
        margin_safety_pct = []  # 记录安全边际的具体值

        total_checks = 0
        margin_count = 0

        for sidx, (index_id, stkcd) in enumerate(stocks):
            if (sidx + 1) % 50 == 0:
                print(f"  进度: {sidx + 1}/{len(stocks)}")

            conn2 = sqlite3.connect(DB_PATH)
            prices = load_prices(conn2, index_id)
            conn2.close()
            if len(prices) < 252 * 3:  # 需要至少3年数据
                continue

            conn3 = sqlite3.connect(DB_PATH)
            fins = load_financials(conn3, stkcd)
            conn3.close()
            if len(fins) < 8:  # 至少2年
                continue

            qis = get_quarter_end_indices(prices)
            for qi in qis:
                if qi + hold_days >= len(prices):
                    continue
                ds = prices[qi][0]
                cp = prices[qi][1]
                if not cp or cp <= 0:
                    continue

                # 检查是否有该日期后的足够价格数据
                # (已通过 hold_days 检查)

                latest = latest_financial(fins, ds)
                if latest is None:
                    continue

                accper, pe_ttm, eps, net_profit, revenue = latest

                # 需要 PE_TTM 和 EPS 都有效
                if pe_ttm is None or pe_ttm <= 0:
                    continue
                if eps is None or eps <= 0:
                    continue

                # 计算历史中位数PE(截至当前)
                hist_pe = [r[1] for r in fins if r[0] <= latest[0] and r[1] is not None and r[1] > 0]
                if len(hist_pe) < 8:
                    continue

                hist_pe_sorted = sorted(hist_pe)
                median_pe = hist_pe_sorted[len(hist_pe_sorted) // 2]

                # 内在价值 = 中位数PE * EPS
                intrinsic_value = median_pe * eps

                # 安全边际
                safety_margin = (intrinsic_value - cp) / intrinsic_value

                fwd = forward_return(prices, qi, hold_days)
                if fwd is None:
                    continue

                total_checks += 1

                if safety_margin > 0.30:
                    margin_count += 1
                    margin_returns.append(fwd)
                    margin_safety_pct.append(safety_margin)
                else:
                    no_margin_returns.append(fwd)

        if not margin_returns:
            print(f"  无安全边际信号，跳过。")
            continue

        # 统计
        margin_wins = sum(1 for r in margin_returns if r > 0)
        margin_win_rate = margin_wins / len(margin_returns) if margin_returns else 0
        margin_avg_ret = sum(margin_returns) / len(margin_returns) if margin_returns else 0

        no_margin_wins = sum(1 for r in no_margin_returns if r > 0)
        no_margin_win_rate = no_margin_wins / len(no_margin_returns) if no_margin_returns else 0
        no_margin_avg_ret = sum(no_margin_returns) / len(no_margin_returns) if no_margin_returns else 0

        s = {
            "检查次数": total_checks,
            "有安全边际次数": margin_count,
            "无安全边际次数": total_checks - margin_count,
            "安全边际触发率": round(margin_count / total_checks, 4) if total_checks else 0,
            "有安全边际_样本数": len(margin_returns),
            "有安全边际_胜率": round(margin_win_rate, 4),
            "有安全边际_平均收益": round(margin_avg_ret, 4),
            "有安全边际_亏损次数": len(margin_returns) - margin_wins,
            "无安全边际_样本数": len(no_margin_returns),
            "无安全边际_胜率": round(no_margin_win_rate, 4),
            "无安全边际_平均收益": round(no_margin_avg_ret, 4),
            "平均安全边际": round(sum(margin_safety_pct) / len(margin_safety_pct), 4) if margin_safety_pct else 0,
            "支持论断(胜率>80%)": margin_win_rate > 0.80,
        }

        results_by_hold[hold_label] = s

        print(f"  有安全边际信号: {margin_count}/{total_checks} ({margin_count / total_checks:.1%})")
        print(f"  有安全边际胜率: {margin_win_rate:.1%} (期望>80%)")
        print(f"  有安全边际平均收益: {margin_avg_ret:.2%}")
        print(f"  无安全边际胜率: {no_margin_win_rate:.1%}")
        print(f"  无安全边际平均收益: {no_margin_avg_ret:.2%}")
        print(f"  >>> 论断支持: {'✅' if margin_win_rate > 0.80 else '❌'} {margin_win_rate:.1%} vs 80%阈值")

    return {
        "test_date": TODAY,
        "claim_id": 31,
        "claim": "安全边际>30%时买入胜率>80%",
        "parameter": {
            "universe": "CN A股",
            "intrinsic_value": "historical_median_PE * current_EPS",
            "safety_margin": "(intrinsic - price) / intrinsic",
            "threshold": "> 30%",
            "success_definition": "forward return > 0",
            "hold_periods": ["1年", "2年", "3年"],
            "note": "EPS用basic_eps_report(ttm); PE历史中位数基于CSMAR所有历史数据",
        },
        "results": results_by_hold,
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
