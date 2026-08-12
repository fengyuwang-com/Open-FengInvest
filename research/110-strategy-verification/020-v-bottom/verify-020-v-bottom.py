#!/usr/bin/env python3
"""verify-020-v-bottom.py — 论断 #20: MA50<MA120+真价值 → DCA优于一次性买入

核心逻辑：
  当股价处于下跌通道（50日线<120日线），但如果公司真有价值（低PE、高ROE、健康现金流），
  此时分批买入（定投）比一次性买入更好。因为：
  - 一次性买入 → 可能买在下跌半山腰
  - 分批买入 → 摊低成本，享受后续反弹

用法:
    python research/110-strategy-verification/020-v-bottom/verify-020-v-bottom.py
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
    """返回有每日数据的CN股票"""
    rows = conn.execute("""
        SELECT s.index_id, s.stkcd
        FROM stkcd_map s
        JOIN daily_data d ON s.index_id = d.index_id
        WHERE s.matched=1
        GROUP BY s.index_id
        HAVING COUNT(*) > 1000
    """).fetchall()
    return [(r[0], r[1]) for r in rows]


def load_prices(conn, index_id):
    rows = conn.execute("""
        SELECT date, close FROM daily_data
        WHERE index_id=? AND close>0
        ORDER BY date
    """, (index_id,)).fetchall()
    return rows


def sma(prices, window):
    result = {}
    for i in range(len(prices)):
        if i < window - 1:
            continue
        s = sum(prices[i - window + 1:i + 1]) / window
        result[i] = s
    return result


def get_pe_percentile(conn, stkcd, as_of_date):
    """计算某只股票在某个日期的 PE TTM 历史分位"""
    row = conn.execute("""
        SELECT pe_ttm FROM cn_financials
        WHERE stkcd=? AND typrep='A' AND if_correct=0
          AND accper <= ?
        ORDER BY accper DESC LIMIT 1
    """, (stkcd, as_of_date)).fetchone()
    if row is None or row[0] is None:
        return None

    current_pe = row[0]

    # 取全部历史 PE
    rows = conn.execute("""
        SELECT pe_ttm FROM cn_financials
        WHERE stkcd=? AND typrep='A' AND if_correct=0
          AND pe_ttm IS NOT NULL AND pe_ttm > 0
    """, (stkcd,)).fetchall()

    if not rows:
        return None

    pes = sorted([r[0] for r in rows])
    n = len(pes)
    # 找 current_pe 在历史中的位置
    below = sum(1 for p in pes if p < current_pe)
    percentile = below / n
    return percentile


def check_value(conn, stkcd, as_of_date):
    """判断是否为真价值股：PE历史低分位 + 健康基本面"""
    pe_pct = get_pe_percentile(conn, stkcd, as_of_date)
    if pe_pct is None:
        return False

    # PE 处于历史 50% 分位以下才视为价值股
    if pe_pct > 0.5:
        return False

    # 检查 ROE
    row = conn.execute("""
        SELECT roe_A, parent_net_profit, operating_cf_net, capital_expenditure
        FROM cn_financials
        WHERE stkcd=? AND typrep='A' AND if_correct=0
          AND accper <= ?
        ORDER BY accper DESC LIMIT 1
    """, (stkcd, as_of_date)).fetchone()

    if row is None:
        return False

    roe, np, ocf, capex = row

    # ROE > 5% 才算有价值（低 PE + 还不错的盈利能力）
    if roe is None or roe < 0.05:
        return False

    # FCF 为正（经营现金流覆盖资本开支）
    fcf = (ocf or 0) - (capex or 0)
    if fcf < 0:
        return False

    return True


def run_backtest():
    conn = sqlite3.connect(DB_PATH)
    stocks = cn_stocks(conn)
    print(f"CN 股票池: {len(stocks)} 只")

    HOLD_MONTHS = [3, 6, 12, 24]
    DCA_INTERVALS = {3: 21, 6: 42, 12: 84, 24: 168}  # 约每月买入一次

    results = {}

    for hold_m in HOLD_MONTHS:
        hold_days = hold_m * 21
        dca_interval = DCA_INTERVALS[hold_m]
        dca_times = hold_days // dca_interval

        print(f"\n=== {hold_m}个月持有期 ===")
        lump_sum_returns = []  # 一次性买入收益
        dca_returns = []        # 定投收益
        value_signals = 0
        total_signals = 0

        for idx, (index_id, stkcd) in enumerate(stocks):
            if (idx + 1) % 50 == 0:
                print(f"  进度: {idx + 1}/{len(stocks)}, 价值信号: {value_signals}/{total_signals}")

            prices = load_prices(conn, index_id)
            if len(prices) < 252 + hold_days:
                continue

            closes = [p[1] for p in prices]
            ma50 = sma(closes, 50)
            ma120 = sma(closes, 120)

            # 检查过去5年
            start_idx = max(0, len(prices) - 5 * 252 - hold_days)

            for i in range(start_idx, len(prices) - hold_days, 21):
                if i not in ma50 or i not in ma120:
                    continue

                if ma50[i] < ma120[i]:
                    date_str = prices[i][0]
                    total_signals += 1

                    # 检查是否真价值
                    if not check_value(conn, stkcd, date_str):
                        continue

                    value_signals += 1
                    current_price = closes[i]

                    # 一次性买入收益
                    if i + hold_days < len(closes):
                        lump_return = (closes[i + hold_days] - current_price) / current_price
                        lump_sum_returns.append(lump_return)
                    else:
                        continue

                    # 定投收益：分批买入（等额），最终总市值/总成本
                    total_cost = 0
                    total_shares = 0
                    invest_per_time = 1000  # 每次等额投资

                    for t in range(dca_times):
                        buy_idx = i + t * dca_interval
                        if buy_idx >= len(closes):
                            break
                        buy_price = closes[buy_idx]
                        if buy_price <= 0:
                            continue
                        shares = invest_per_time / buy_price
                        total_shares += shares
                        total_cost += invest_per_time

                    # 最终价值
                    if i + hold_days < len(closes):
                        final_price = closes[i + hold_days]
                        final_value = total_shares * final_price
                        dca_return = (final_value - total_cost) / total_cost
                        dca_returns.append(dca_return)

        if not lump_sum_returns:
            print(f"  无有效信号")
            continue

        # 统计
        lump_avg = sum(lump_sum_returns) / len(lump_sum_returns)
        dca_avg = sum(dca_returns) / len(dca_returns)

        lump_win = sum(1 for r in lump_sum_returns if r > 0) / len(lump_sum_returns)
        dca_win = sum(1 for r in dca_returns if r > 0) / len(dca_returns)

        dca_better = sum(1 for i in range(len(lump_sum_returns))
                         if dca_returns[i] > lump_sum_returns[i]) / len(lump_sum_returns)

        print(f"  真价值信号数: {value_signals}/{total_signals}")
        print(f"  一次性买入: 平均收益={lump_avg:.2%}, 胜率={lump_win:.1%}")
        print(f"  定投:      平均收益={dca_avg:.2%}, 胜率={dca_win:.1%}")
        print(f"  定投优于一次性比例: {dca_better:.1%}")

        results[f"{hold_m}个月"] = {
            "价值信号数": value_signals,
            "总技术信号数": total_signals,
            "一次性买入平均收益": round(lump_avg, 4),
            "定投平均收益": round(dca_avg, 4),
            "一次性买入胜率": round(lump_win, 4),
            "定投胜率": round(dca_win, 4),
            "定投优于一次性比例": round(dca_better, 4),
        }

    conn.close()

    # 验证：定投优于一次性买入的比例是否 > 50%
    verdict = {}
    for hold, r in results.items():
        dca_better = r["定投优于一次性比例"]
        verdict[hold] = {
            "定投优于一次性": dca_better,
            "结论": "✅ 支持" if dca_better > 0.5 else "❌ 拒绝",
        }

    return {
        "test_date": TODAY,
        "claim_id": 20,
        "claim": "MA50<MA120+真价值→DCA优于一次性买入",
        "parameter": {
            "value_criteria": "PE历史<50%分位 + ROE>5% + FCF>0",
            "dca_frequency": "约每月一次",
        },
        "verdict": verdict,
        "details": results,
    }


if __name__ == "__main__":
    t0 = time.time()
    results = run_backtest()
    elapsed = time.time() - t0

    out_path = os.path.join(os.path.dirname(__file__), "results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存: {out_path}")
    print(f"耗时: {elapsed:.0f}s")
    print(json.dumps(results, indent=2, ensure_ascii=False))
