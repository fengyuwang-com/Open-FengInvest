#!/usr/bin/env python3
"""verify-040-trading-frequency.py — 论断 #40: 交易频率降低一半，每年仅提升 0.5% 收益

论断：交易频率降低一半，年化收益仅提升约 0.5%，说明大多数交易是噪音。

方法：
  1. 用 SP500 指数日线数据模拟市场择时策略
  2. 策略：200日均线择时（价格>均线买入，<均线卖出）
  3. 不同持有期约束：买入后至少持有 N 天才能卖出
  4. 交易成本：假设 0.1%/笔
  5. 统计各持有期约束下的年化收益和交易频率
  6. 检验频率减半对收益的影响

结果保存到 results.json
"""
import json
import math
import os
import sqlite3

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
DB = os.path.join(BASE, "data", "market_data.db")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.json")

TC = 0.001  # 单笔交易成本（买入+卖出）


def get_connection():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def load_sp500(conn):
    """加载 SP500 指数日线"""
    cur = conn.execute("SELECT id FROM indices WHERE ticker='^GSPC' AND category='index'")
    row = cur.fetchone()
    if not row:
        cur = conn.execute("SELECT id FROM indices WHERE ticker='SPY' AND category='etf'")
        row = cur.fetchone()
    if not row:
        return None
    cur = conn.execute(
        "SELECT date, close FROM daily_data WHERE index_id=? AND close>0 ORDER BY date",
        (row["id"],),
    )
    return [dict(r) for r in cur.fetchall()]


def sma(data, window):
    """简单移动平均"""
    if len(data) < window:
        return [None] * len(data)
    result = [None] * (window - 1)
    s = sum(data[:window])
    result.append(s / window)
    for i in range(window, len(data)):
        s += data[i] - data[i - window]
        result.append(s / window)
    return result


def simulate_strategy(prices, min_hold_days, tc=TC):
    """模拟某个持有期约束的择时策略。

    Args:
        prices: [{date, close}]
        min_hold_days: 买入后最短持有天数
        tc: 单边交易成本比例

    Returns: dict with stats
    """
    n = len(prices)
    if n < 500:  # need enough for 200MA
        return None

    closes = [p["close"] for p in prices]
    ma200 = sma(closes, 200)

    cash = 1.0  # 初始资金
    shares = 0.0
    trades = 0
    days_since_buy = 999  # 足够大
    in_market = False

    # 每日净值跟踪
    daily_nav = []
    entry_nav = None

    for i in range(252, n):  # 从有 200MA 开始
        price = closes[i]
        ma = ma200[i]

        if price is None or ma is None or ma == 0:
            if in_market:
                nav = shares * price + cash
            else:
                nav = cash
            daily_nav.append(nav)
            continue

        signal = price > ma
        days_since_buy += 1

        if signal and not in_market and days_since_buy >= min_hold_days:
            # 买入
            buy_cost = cash * tc
            shares = (cash - buy_cost) / price
            cash = 0
            in_market = True
            days_since_buy = 0
            trades += 1
        elif not signal and in_market and days_since_buy >= min_hold_days:
            # 卖出
            sell_value = shares * price
            sell_cost = sell_value * tc
            cash = sell_value - sell_cost
            shares = 0
            in_market = False
            trades += 1

        # 记录 NAV
        nav = shares * price + cash if in_market else cash
        daily_nav.append(nav)
        if in_market and entry_nav is None:
            entry_nav = nav

    # 最终清算
    if in_market and n > 0:
        final_price = closes[-1]
        sell_value = shares * final_price
        sell_cost = sell_value * tc
        cash = sell_value - sell_cost
        shares = 0
        trades += 1

    final_nav = cash
    total_return = final_nav / 1.0 - 1
    years = (len(daily_nav)) / 252
    cagr = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0

    # 最大回撤
    peak = 0
    max_dd = 0
    for nav in daily_nav:
        peak = max(peak, nav)
        dd = (nav - peak) / peak if peak > 0 else 0
        max_dd = min(max_dd, dd)

    # 胜率：统计每笔交易的赢亏
    # 简化：跟踪信号期的收益率
    win_trades = 0
    total_closed = 0

    return {
        "min_hold_days": min_hold_days,
        "type": "hold_constraint",
        "total_return_pct": round(total_return * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "n_trades": trades,
        "trades_per_year": round(trades / years, 1) if years > 0 else 0,
        "years": round(years, 1),
    }


def main():
    conn = get_connection()
    prices = load_sp500(conn)
    conn.close()

    if not prices:
        print("Error: Could not load SP500 data")
        return

    print(f"Loaded {len(prices)} days of SP500 data")
    print(f"Range: {prices[0]['date']} ~ {prices[-1]['date']}")

    # 测试不同持有期约束
    # min_hold = 1 表示无约束（随时可交易）
    # 数值越大 = 交易频率越低
    hold_days = [1, 10, 21, 42, 63, 126, 252]
    labels = {
        1: "无约束 (随时)",
        10: "10天",
        21: "约1个月",
        42: "约2个月",
        63: "约1季度",
        126: "约半年",
        252: "约1年",
    }

    results = []
    for hd in hold_days:
        r = simulate_strategy(prices, hd)
        if r:
            r["label"] = labels[hd]
            results.append(r)
            print(
                f"  {labels[hd]:12s}: CAGR={r['cagr_pct']:+.2f}%  "
                f"MaxDD={r['max_drawdown_pct']:.1f}%  "
                f"Trades/yr={r['trades_per_year']}  "
                f"Total Trades={r['n_trades']}"
            )

    # 频率减半的影响
    impact = []
    for i in range(1, len(results)):
        prev = results[i - 1]
        curr = results[i]
        trades_reduction = (1 - curr["trades_per_year"] / prev["trades_per_year"]) * 100
        cagr_diff = curr["cagr_pct"] - prev["cagr_pct"]
        impact.append({
            "from": f"hold>={prev['min_hold_days']}d ({prev['label']})",
            "to": f"hold>={curr['min_hold_days']}d ({curr['label']})",
            "trades_reduction_pct": round(trades_reduction, 1),
            "cagr_change_pct": round(cagr_diff, 2),
        })

    # 半衰影响: 交易频率腰斩对 CAGR 的影响
    halving_impact = None
    for imp in impact:
        if abs(imp["trades_reduction_pct"] - 50) < 20:  # 接近减半
            halving_impact = imp
            break

    if halving_impact:
        conclusion_text = (
            f"频率腰斩时 CAGR 变化 {halving_impact['cagr_change_pct']:+.2f}%"
        )
    elif impact:
        conclusion_text = (
            f"从 {results[0]['label']} 到 {results[-1]['label']}: "
            f"CAGR 变化 {results[-1]['cagr_pct'] - results[0]['cagr_pct']:+.2f}%"
        )
    else:
        conclusion_text = "无足够数据"

    output = {
        "claim": "#40 交易频率降低一半，每年仅提升 0.5% 收益",
        "claim_en": "Halving trading frequency only improves annual returns by ~0.5%",
        "method": "SP500 200日均线择时 + 不同持有期约束 + 0.1%交易成本",
        "data_period": f"{prices[0]['date']} ~ {prices[-1]['date']}",
        "n_days": len(prices),
        "results": results,
        "frequency_halving_impact": impact,
        "conclusion": conclusion_text,
        "verdict": None,
    }

    # 判定
    if impact:
        changes = [abs(i["cagr_change_pct"]) for i in impact]
        avg_change = sum(changes) / len(changes)
        if avg_change <= 1.0:
            output["verdict"] = "支持 — 频率减半对收益影响很小，接近 0.5% 论断"
        elif avg_change <= 2.0:
            output["verdict"] = "部分支持 — 频率减半有一定影响，但不大"
        else:
            output["verdict"] = "拒绝 — 频率减半对收益影响显著 > 2%"

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n结果已保存至: {OUT}")
    verdict = output.get("verdict", "N/A")
    print(f"结论: {verdict}")
    for imp in impact:
        print(f"  {imp['from']} → {imp['to']}: 交易 {imp['trades_reduction_pct']}% ↓  CAGR {imp['cagr_change_pct']:+.2f}%")


if __name__ == "__main__":
    main()
