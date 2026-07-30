#!/usr/bin/env python3
"""verify-030-fcf-exit.py -- 论断 #30: PE>95%分位或市值/FCF>50倍应清仓

策略:
  每季度末检查持仓股票的PE_TTM历史分位和FCF收益率。
  如果PE高于历史95%分位 或 市值/FCF>50，清仓(0%仓位)；
  否则满仓持有。
  对比纯持有策略的最大回撤、CAGR。

用法:
    python research/110-strategy-verification/030-fcf-exit/verify-030-fcf-exit.py
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
    """含 PE_TTM, OCF, CAPEX, 市值。"""
    rows = conn.execute("""
        SELECT accper, pe_ttm, operating_cf_net, capital_expenditure, market_cap_A
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


def calc_pe_percentile(current_pe, all_pe_list):
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
    return (avg - rf_prd) / std * (periods_per_year ** 0.5)


# -- 主回测 -------------------------------------------------------

def run_backtest():
    conn = sqlite3.connect(DB_PATH)
    stocks = cn_stocks(conn)
    conn.close()
    print(f"CN 股票池: {len(stocks)} 只")

    HOLD_PERIODS = [(63, "3个月"), (126, "6个月"), (252, "12个月")]
    results_by_hold = {}

    for hold_days, hold_label in HOLD_PERIODS:
        print(f"\n=== {hold_label}持有期 ===")

        exit_signal_hold = []    # 有退出信号时的持有收益(应该亏)
        exit_signal_strat = []   # 有退出信号时的策略收益(清仓=0)
        no_signal_hold = []      # 无信号的持有收益

        total_sigs = 0
        exit_sigs = 0

        for sidx, (index_id, stkcd) in enumerate(stocks):
            if (sidx + 1) % 50 == 0:
                print(f"  进度: {sidx + 1}/{len(stocks)}")

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

            all_pe = [r[1] for r in fins if r[1] is not None and r[1] > 0]
            if len(all_pe) < 4:
                continue

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

                accper, pe_ttm, ocf, capex, mcap = latest
                fwd = forward_return(prices, qi, hold_days)
                if fwd is None:
                    continue

                # -- 检查两个退出信号 --
                exit_flag = False

                # 信号1: PE > 95% 分位
                if pe_ttm is not None and pe_ttm > 0:
                    hist_pe = [r[1] for r in fins if r[0] <= latest[0] and r[1] is not None and r[1] > 0]
                    pct = calc_pe_percentile(pe_ttm, hist_pe)
                    if pct is not None and pct > 0.95:
                        exit_flag = True

                # 信号2: 市值/FCF > 50 (FCF = OCF - CAPEX)
                if not exit_flag:
                    if ocf is not None and capex is not None and mcap is not None and mcap > 0:
                        fcf = ocf - capex
                        if fcf > 0:  # 只考虑正FCF(负FCF市值/FCF无意义)
                            ratio = mcap / fcf
                            if ratio > 50:
                                exit_flag = True

                total_sigs += 1
                if exit_flag:
                    exit_sigs += 1
                    exit_signal_hold.append(fwd)
                    exit_signal_strat.append(0.0)  # 清仓，后续收益为0
                else:
                    no_signal_hold.append(fwd)

        if not exit_signal_hold:
            print(f"  无退出信号，跳过。")
            continue

        def stats(label, returns_list):
            if not returns_list:
                return {}
            avg_r = sum(returns_list) / len(returns_list)
            cagr = (1 + avg_r) ** (252 / hold_days) - 1
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
        s.update(stats("退出信号持有", exit_signal_hold))
        s.update(stats("退出信号策略", exit_signal_strat))
        s.update(stats("无信号持有", no_signal_hold))
        s["退出信号占比"] = round(exit_sigs / total_sigs, 4) if total_sigs else 0

        # 关键比较: 退出策略是否避免了损失
        if exit_signal_hold:
            hold_loss = sum(1 for r in exit_signal_hold if r < 0)
            s["退出区间持有亏损率"] = round(hold_loss / len(exit_signal_hold), 4)
            s["退出策略避免亏损"] = hold_loss > 0  # 清仓避免了这些亏损
            s["避免亏损绝对值"] = round(abs(sum(r for r in exit_signal_hold if r < 0)), 4) if any(r < 0 for r in exit_signal_hold) else 0

            # 回撤对比
            hold_mdd = max_drawdown(exit_signal_hold)
            strat_mdd = max_drawdown(exit_signal_strat)
            s["持有回撤(退出区间)"] = round(hold_mdd, 4)
            s["策略回撤(退出区间)"] = round(strat_mdd, 4)
            s["回撤减少(绝对值)"] = round(hold_mdd - strat_mdd, 4)

            s["支持论断"] = hold_loss / len(exit_signal_hold) > 0.3  # 退出区间亏损率>30%说明有意义

        results_by_hold[hold_label] = s

        print(f"  退出信号: {exit_sigs}/{total_sigs} ({exit_sigs / total_sigs:.1%})")
        print(f"  退出区间持有平均收益: {s.get('退出信号持有_平均收益', 'N/A')}")
        print(f"  退出区间策略收益: {s.get('退出信号策略_平均收益', 'N/A')} (清仓=0)")
        print(f"  退出区间持有亏损率: {s.get('退出区间持有亏损率', 'N/A')}")

    return {
        "test_date": TODAY,
        "claim_id": 30,
        "claim": "PE高于95%分位或市值/FCF>50倍应清仓",
        "parameter": {
            "universe": "CN A股(含沪深300等)",
            "pe_threshold": "95th_percentile",
            "fcf_threshold": "market_cap / FCF > 50",
            "fcf_definition": "operating_cf_net - capital_expenditure",
            "position_on_signal": "0% (fully exit)",
            "note": "FCF须为正才计算比率; PE分位基于CSMAR历史展开窗口",
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
