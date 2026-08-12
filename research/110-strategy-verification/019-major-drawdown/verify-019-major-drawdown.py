#!/usr/bin/env python3
"""verify-019-major-drawdown.py — 论断 #19: MA50<MA120+基本面恶化 → 避免>70%亏损

核心逻辑：
  当股价 50 日线跌破 120 日线（死叉），同时最新财报显示基本面恶化（FCF下降等），
  持有这只股票大概率亏损（>70% 概率）。所以应该在死叉+基本面恶化时及时卖出/避免买入。

用法:
    python research/110-strategy-verification/019-major-drawdown/verify-019-major-drawdown.py
"""
import sys, os, json, sqlite3
from datetime import datetime, timedelta
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, BASE)

DB_PATH = os.path.join(BASE, "data", "market_data.db")
TODAY = "2026-07-23"

# ── 辅助函数 ──────────────────────────────────────────

def cn_stocks(conn):
    """返回(CN)有每日数据的股票列表 [(index_id, stkcd), ...]"""
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
    """加载一只股票的日线数据 (date, close)"""
    rows = conn.execute("""
        SELECT date, close FROM daily_data
        WHERE index_id=? AND close>0
        ORDER BY date
    """, (index_id,)).fetchall()
    return rows  # list of (date_str, close)


def sma(prices, window):
    """计算简单移动平均线，返回 {索引: 平均值} 的字典"""
    result = {}
    for i in range(len(prices)):
        if i < window - 1:
            continue
        s = sum(prices[i - window + 1:i + 1]) / window
        result[i] = s
    return result


def load_financials(conn, stkcd, as_of_date):
    """加载某只股票在给定日期之前的最新合并报表财务数据"""
    row = conn.execute("""
        SELECT accper, operating_cf_net, capital_expenditure,
               total_revenue, parent_net_profit, roe_A
        FROM cn_financials
        WHERE stkcd=? AND typrep='A' AND if_correct=0
          AND accper <= ?
        ORDER BY accper DESC
        LIMIT 1
    """, (stkcd, as_of_date)).fetchone()
    if row is None:
        return None

    accper, ocf, capex, rev, np, roe = row
    fcf = (ocf or 0) - (capex or 0)

    # 取 4 个季度前的同一数据（同比）
    row_4q = conn.execute("""
        SELECT operating_cf_net, capital_expenditure, total_revenue, parent_net_profit, roe_A
        FROM cn_financials
        WHERE stkcd=? AND typrep='A' AND if_correct=0
          AND accper < ?
        ORDER BY accper DESC
        LIMIT 1
    """, (stkcd, accper)).fetchone()

    if row_4q:
        ocf_4q, capex_4q, rev_4q, np_4q, roe_4q = row_4q
        fcf_4q = (ocf_4q or 0) - (capex_4q or 0)
    else:
        fcf_4q = None

    return {
        "accper": accper,
        "fcf": fcf,
        "fcf_4q_ago": fcf_4q,
        "revenue": rev,
        "net_profit": np,
        "roe": roe,
    }


def is_fundamentals_deteriorating(fin):
    """判断基本面是否恶化（至少满足一项）"""
    if fin is None:
        return None
    signals = []
    if fin["fcf_4q_ago"] is not None and fin["fcf_4q_ago"] != 0:
        fcf_decline = (fin["fcf"] - fin["fcf_4q_ago"]) / abs(fin["fcf_4q_ago"])
        signals.append(fcf_decline < -0.2)  # FCF同比下降>20%
    if fin["roe"] is not None:
        signals.append(fin["roe"] < 0.03)  # ROE<3%视为恶化
    if fin["revenue"] is not None and fin["revenue"] < 0:
        signals.append(True)  # 营收为负
    if fin["fcf"] < 0 and fin["fcf_4q_ago"] is not None and fin["fcf_4q_ago"] < 0:
        signals.append(True)  # 连续亏损现金流
    if not signals:
        return False
    return any(signals)


def get_forward_return(daily_prices, current_idx, hold_days=126):
    """计算 forward return，从 current_idx 到 current_idx+hold_days"""
    target = current_idx + hold_days
    if target >= len(daily_prices):
        return None
    cp = daily_prices[current_idx][1]
    fp = daily_prices[target][1]
    if cp == 0 or cp is None:
        return None
    return (fp - cp) / cp


# ── 主回测 ────────────────────────────────────────────

def run_backtest():
    conn = sqlite3.connect(DB_PATH)
    stocks = cn_stocks(conn)
    print(f"CN 股票池: {len(stocks)} 只有价格数据")

    # 回测参数
    HOLD_DAYS = 126  # ~6个月
    HOLD_LABEL = {63: "3个月", 126: "6个月", 252: "12个月"}
    DRAWDOWN_THRESHOLD = 0.70  # 70%亏损

    results_by_hold = {}

    for hold_days, hold_label in HOLD_LABEL.items():
        print(f"\n=== {hold_label}持有期 ===")
        bad_group = []      # MA50<MA120 + 基本面恶化
        technical_group = []  # 仅 MA50<MA120
        normal_group = []     # 其他

        for idx, (index_id, stkcd) in enumerate(stocks):
            if (idx + 1) % 50 == 0:
                print(f"  进度: {idx + 1}/{len(stocks)}")

            prices = load_prices(conn, index_id)
            if len(prices) < 252:
                continue

            closes = [p[1] for p in prices]

            # 只有最后 5 年的数据做回测（避免太久远）
            start_idx = max(0, len(prices) - 5 * 252)

            # 计算 MA50 和 MA120
            ma50 = sma(closes, 50)
            ma120 = sma(closes, 120)

            # 按季度检查（每个 quarter-end 附近）
            # 我们检查每个月末
            check_dates = set()
            for i in range(start_idx, len(prices) - hold_days, 21):  # 约每月
                date_str = prices[i][0]
                month = date_str[5:7]
                if month in {"03", "06", "09", "12"} and date_str[8:10] >= "25":
                    check_dates.add(i)

            for i in sorted(check_dates):
                date_str = prices[i][0]

                if i not in ma50 or i not in ma120:
                    continue

                technical_bad = ma50[i] < ma120[i]  # 死叉

                # 加载基本面
                fin = load_financials(conn, stkcd, date_str)

                if technical_bad:
                    # 检查基本面是否恶化
                    if fin and is_fundamentals_deteriorating(fin):
                        fwd = get_forward_return(prices, i, hold_days)
                        if fwd is not None:
                            bad_group.append(fwd)
                    else:
                        fwd = get_forward_return(prices, i, hold_days)
                        if fwd is not None:
                            technical_group.append(fwd)
                else:
                    fwd = get_forward_return(prices, i, hold_days)
                    if fwd is not None:
                        normal_group.append(fwd)

        # 计算统计
        results = {}
        for label, group in [("MA50<MA120+基本面恶化", bad_group),
                             ("仅MA50<MA120", technical_group),
                             ("正常", normal_group)]:
            if not group:
                continue
            losses = sum(1 for r in group if r < 0)
            gain = sum(1 for r in group if r > 0)
            loss_rate = len(group) and losses / len(group) or 0
            gain_rate = len(group) and gain / len(group) or 0
            avg_return = sum(group) / len(group)

            results[label] = {
                "样本数": len(group),
                "亏损次数": losses,
                "盈利次数": gain,
                "亏损率": round(loss_rate, 4),
                "盈利率": round(gain_rate, 4),
                "平均收益": round(avg_return, 4),
            }
            print(f"  {label}:")
            for k, v in results[label].items():
                print(f"    {k}: {v}")

        # 关键验证: 坏组的亏损率是否 > 70%
        if "MA50<MA120+基本面恶化" in results:
            bad_loss_rate = results["MA50<MA120+基本面恶化"]["亏损率"]
            support = bad_loss_rate >= DRAWDOWN_THRESHOLD
            print(f"\n  >>> 关键验证: 坏组亏损率={bad_loss_rate:.1%}, 阈值={DRAWDOWN_THRESHOLD:.0%}")
            print(f"  >>> 结果: {'✅ 支持' if support else '❌ 拒绝'}")

            if "仅MA50<MA120" in results:
                tech_loss_rate = results["仅MA50<MA120"]["亏损率"]
                print(f"  >>> 仅技术面恶化组亏损率={tech_loss_rate:.1%}")
                improvement = (tech_loss_rate - bad_loss_rate) / tech_loss_rate if tech_loss_rate > 0 else 0
                print(f"  >>> 基本面检查减少亏损: {improvement:.1%}")

        results_by_hold[hold_label] = results

    conn.close()

    # 汇总结论
    summary = {}
    for hold_label, res in results_by_hold.items():
        if "MA50<MA120+基本面恶化" in res:
            bad = res["MA50<MA120+基本面恶化"]
            tech = res.get("仅MA50<MA120", None)

            support = bad["亏损率"] >= DRAWDOWN_THRESHOLD
            improvement = None
            if tech and tech["样本数"] > 0:
                improvement = (tech["亏损率"] - bad["亏损率"]) / tech["亏损率"] if tech["亏损率"] > 0 else 0

            summary[hold_label] = {
                "支持论断": support,
                "坏组亏损率": bad["亏损率"],
                "仅技术面亏损率": tech and tech["亏损率"] or None,
                "基本面减少亏损比": improvement,
                "坏组样本数": bad["样本数"],
            }

    return {
        "test_date": TODAY,
        "claim_id": 19,
        "claim": "MA50<MA120+基本面恶化→避免>70%亏损",
        "parameter": {"ma50_vs_ma120": True, "fundamental_checks": "FCF decline>20% or ROE<3% or negative revenue or consecutive FCF loss"},
        "results": summary,
        "details_by_hold": results_by_hold,
    }


if __name__ == "__main__":
    t0 = time.time()
    results = run_backtest()
    elapsed = time.time() - t0

    # 输出 JSON
    out_path = os.path.join(os.path.dirname(__file__), "results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n结果已保存到: {out_path}")
    print(f"耗时: {elapsed:.0f}s")
    print(json.dumps(results, indent=2, ensure_ascii=False))
