#!/usr/bin/env python3
"""verify-029-pe-percentile-cut.py -- 论断 #29: PE高于历史80%分位时减仓减少回撤

策略:
  每季度末检查持仓股票的PE_TTM历史分位。
  如果PE高于历史80%分位，将仓位降至50%；
  否则满仓持有。
  对比纯持有策略的最大回撤、CAGR、夏普比率。

用法:
    python research/110-strategy-verification/029-pe-percentile-cut/verify-029-pe-percentile-cut.py
"""
import sys, os, json, sqlite3
from datetime import datetime, timedelta
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, BASE)

DB_PATH = os.path.join(BASE, "data", "market_data.db")
TODAY = "2026-07-23"


# -- 数据加载 -------------------------------------------------------

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
    """加载一只股票全部合并报表财务记录(含PE_TTM)。"""
    rows = conn.execute("""
        SELECT accper, pe_ttm
        FROM cn_financials
        WHERE stkcd = ? AND typrep = 'A' AND if_correct = 0
          AND pe_ttm IS NOT NULL AND pe_ttm > 0
        ORDER BY accper
    """, (stkcd,)).fetchall()
    return rows


def get_quarter_end_indices(prices, start_date="2005-01-01"):
    """找出所有季度末附近的索引 (3/6/9/12月 25日之后)。"""
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
    """返回 as_of_date 之前的最新一条财务记录。"""
    for fr in reversed(fin_records):
        if fr[0] <= as_of_date:
            return fr
    return None


def calc_pe_percentile(current_pe, all_pe_list):
    """计算 current_pe 在历史序列中的百分位(0~1)。"""
    if len(all_pe_list) < 4:
        return None
    cnt = sum(1 for pe in all_pe_list if pe <= current_pe)
    return cnt / len(all_pe_list)


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


def sharpe_ratio(returns, rf_annual=0.02, periods_per_year=4):
    if len(returns) < 2:
        return 0.0
    avg = sum(returns) / len(returns)
    var = sum((r - avg) ** 2 for r in returns) / (len(returns) - 1)
    std = var ** 0.5
    if std == 0:
        return 0.0
    rf_prd = rf_annual / periods_per_year
    ann = periods_per_year ** 0.5
    return (avg - rf_prd) / std * ann


# -- 主回测 -------------------------------------------------------

def run_backtest():
    conn = sqlite3.connect(DB_PATH)
    stocks = cn_stocks(conn)
    print(f"CN 股票池: {len(stocks)} 只")
    conn.close()

    HOLD_PERIODS = [(63, "3个月"), (126, "6个月"), (252, "12个月")]
    results_by_hold = {}

    for hold_days, hold_label in HOLD_PERIODS:
        print(f"\n=== {hold_label}持有期 ===")

        # 收集所有信号的策略收益/持有收益
        # 分组: 高PE(>80%分位) vs 正常PE
        high_pe_hold = []   # 高PE区间的持有收益
        high_pe_strat = []  # 高PE区间的策略收益(减仓50%)
        normal_hold = []    # 正常PE区间的持有收益

        signal_cnt = 0
        high_cnt = 0

        for sidx, (index_id, stkcd) in enumerate(stocks):
            if (sidx + 1) % 50 == 0:
                print(f"  进度: {sidx + 1}/{len(stocks)}")

            # 重新建立连接
            conn2 = sqlite3.connect(DB_PATH)
            prices = load_prices(conn2, index_id)
            conn2.close()

            if len(prices) < 252:
                continue

            conn3 = sqlite3.connect(DB_PATH)
            fins = load_financials(conn3, stkcd)
            conn3.close()

            if len(fins) < 4:
                continue

            # 提取所有历史PE(整个序列)
            all_pe = [r[1] for r in fins]

            qis = get_quarter_end_indices(prices)
            for qi in qis:
                if qi + hold_days >= len(prices):
                    continue
                ds = prices[qi][0]
                cp = prices[qi][1]
                if not cp or cp <= 0:
                    continue

                latest = latest_financial(fins, ds)
                if latest is None:
                    continue

                current_pe = latest[1]
                if current_pe is None or current_pe <= 0:
                    continue

                # 计算截止到当期的历史PE分位
                hist_pe = [r[1] for r in fins if r[0] <= latest[0] and r[1] is not None and r[1] > 0]
                pct = calc_pe_percentile(current_pe, hist_pe)
                if pct is None:
                    continue

                fwd = forward_return(prices, qi, hold_days)
                if fwd is None:
                    continue

                signal_cnt += 1
                if pct > 0.80:
                    high_cnt += 1
                    high_pe_hold.append(fwd)
                    high_pe_strat.append(fwd * 0.5)  # 减仓至50%
                else:
                    normal_hold.append(fwd)

        if not high_pe_hold:
            print(f"  无高PE信号，跳过。")
            continue

        # 计算各项指标
        def stats(label, returns_list):
            if not returns_list:
                return {}
            avg_r = sum(returns_list) / len(returns_list)
            cagr = (1 + avg_r) ** (252 / hold_days) - 1 if hold_days > 0 else 0
            mdd = max_drawdown(returns_list)
            sr = sharpe_ratio(returns_list, periods_per_year=max(1, 252 // hold_days))
            wr = sum(1 for r in returns_list if r > 0) / len(returns_list)
            return {
                f"{label}_{k}": v for k, v in {
                    "样本数": len(returns_list),
                    "平均收益": round(avg_r, 4),
                    "年化收益": round(cagr, 4),
                    "最大回撤": round(mdd, 4),
                    "夏普比": round(sr, 4),
                    "胜率": round(wr, 4),
                }.items()
            }

        s = {}
        s.update(stats("高PE持有", high_pe_hold))
        s.update(stats("高PE策略", high_pe_strat))
        s.update(stats("正常PE持有", normal_hold))
        s["高PE信号占比"] = round(high_cnt / signal_cnt, 4) if signal_cnt else 0

        # 关键比较: 高PE区间回撤是否减少
        if high_pe_hold:
            hold_mdd = max_drawdown(high_pe_hold)
            strat_mdd = max_drawdown(high_pe_strat)
            s["回撤减少(绝对值)"] = round(hold_mdd - strat_mdd, 4)
            s["回撤减少(比例)"] = round((hold_mdd - strat_mdd) / hold_mdd, 4) if hold_mdd > 0 else 0
            s["支持论断"] = (hold_mdd - strat_mdd) > 0.01  # 回撤减少超过1个百分点

        results_by_hold[hold_label] = s

        print(f"  高PE信号: {high_cnt}/{signal_cnt} ({high_cnt / signal_cnt:.1%})")
        print(f"  高PE持有收益: {s.get('高PE持有_平均收益', 'N/A')}")
        print(f"  高PE策略收益: {s.get('高PE策略_平均收益', 'N/A')}")
        print(f"  高PE持有最大回撤: {s.get('高PE持有_最大回撤', 'N/A')}")
        print(f"  高PE策略最大回撤: {s.get('高PE策略_最大回撤', 'N/A')}")
        print(f"  回撤减少: {s.get('回撤减少(比例)', 'N/A')}")

    return {
        "test_date": TODAY,
        "claim_id": 29,
        "claim": "PE高于历史80%分位时减仓能减少回撤",
        "parameter": {
            "universe": "CN A股(含沪深300等)",
            "pe_field": "pe_ttm",
            "threshold": "80th_percentile",
            "position_reduction": "50% (when signal active)",
            "rebalance": "quarter-end",
            "hold_periods": ["3个月", "6个月", "12个月"],
            "note": "分位计算基于CSMAR历史PE_TTM(扩展窗口,不固定窗宽)",
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
