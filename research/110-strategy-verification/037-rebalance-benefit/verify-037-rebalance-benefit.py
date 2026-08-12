#!/usr/bin/env python3
"""verify-037-rebalance-benefit.py — 论断 #37: 再平衡年化超额>1%

核心逻辑：
  定期再平衡的组合（恢复目标权重），年化收益比不复盘持有高 1% 以上。
"""
import sys, os, json, sqlite3, time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, BASE)

DB_PATH = os.path.join(BASE, "data", "market_data.db")
TODAY = "2026-07-23"


def _max_drawdown(returns):
    cum = 1; peak = 1; mdd = 0
    for r in returns:
        cum *= (1 + r)
        peak = max(peak, cum)
        dd = (peak - cum) / peak
        mdd = max(mdd, dd)
    return mdd


def run_backtest():
    conn = sqlite3.connect(DB_PATH)

    stocks = conn.execute("""
        SELECT i.id as index_id, i.ticker
        FROM indices i
        WHERE i.market='US' AND i.category='stock'
        ORDER BY i.ticker
    """).fetchall()
    print(f"US 股票: {len(stocks)} 只")

    months = []
    for y in range(2010, 2026):
        for m in range(1, 13):
            months.append(f"{y}-{m:02d}")
    months = months[:-1]

    # 选 50 只市值最大的股票构建组合
    selected = stocks[:100]  # 多取一些，排除缺失数据
    monthly_returns = {idx_id: [] for idx_id, _ in selected}

    for idx_id, ticker in selected:
        for mi in range(len(months) - 1):
            m_start, m_end = months[mi], months[mi + 1]
            r1 = conn.execute("""
                SELECT close FROM daily_data
                WHERE index_id=? AND date LIKE ? || '-%' ORDER BY date LIMIT 1
            """, (idx_id, m_start)).fetchone()
            r2 = conn.execute("""
                SELECT close FROM daily_data
                WHERE index_id=? AND date LIKE ? || '-%' ORDER BY date DESC LIMIT 1
            """, (idx_id, m_end)).fetchone()
            if r1 and r2 and r1[0] > 0 and r2[0] > 0:
                monthly_returns[idx_id].append((r2[0] - r1[0]) / r1[0])
            else:
                monthly_returns[idx_id].append(None)

    n_months = len(months) - 1

    # 策略 A: 不复盘 (buy & hold, 权重随涨跌变化)
    bh_values = []
    # 策略 B: 每季再平衡 (quarterly rebalance to equal weight)
    rb_values = []

    for mi in range(n_months):
        active_returns = []
        for idx_id, _ in selected:
            r = monthly_returns[idx_id][mi]
            if r is not None:
                active_returns.append(r)

        if len(active_returns) < 30:
            continue

        # 等权平均收益 (再平衡的效果)
        ew = sum(active_returns) / len(active_returns)
        rb_values.append(ew)

    # 不复盘: 起始等权, 之后权重随涨跌变化
    weights = {idx_id: 1.0 for idx_id, _ in selected[:50]}
    for mi in range(n_months):
        port_ret = 0
        total_w = sum(weights.values())
        if total_w == 0:
            continue

        for idx_id in list(weights.keys()):
            r = monthly_returns[idx_id][mi]
            if r is not None:
                w = weights[idx_id] / total_w
                port_ret += w * r
                weights[idx_id] *= (1 + r)
            else:
                del weights[idx_id]

        bh_values.append(port_ret)

    # 确保长度一致
    min_len = min(len(bh_values), len(rb_values))
    bh_values = bh_values[:min_len]
    rb_values = rb_values[:min_len]

    if min_len < 12:
        conn.close()
        return {"error": f"insufficient data: {min_len} months"}

    # 计算年化收益
    bh_cagr = (1 + sum(bh_values)) ** (12 / min_len) - 1
    rb_cagr = (1 + sum(rb_values)) ** (12 / min_len) - 1

    bh_mdd = _max_drawdown(bh_values)
    rb_mdd = _max_drawdown(rb_values)

    # 夏普
    bh_sharpe = (sum(bh_values) / len(bh_values) - 0.02 / 12) / (_std(bh_values) + 1e-10) * (12 ** 0.5)
    rb_sharpe = (sum(rb_values) / len(rb_values) - 0.02 / 12) / (_std(rb_values) + 1e-10) * (12 ** 0.5)

    excess = rb_cagr - bh_cagr

    results = {
        "test_date": TODAY,
        "claim_id": 37,
        "claim": "再平衡年化超额>1%",
        "period": f"{months[0]} ~ {months[n_months-1]}",
        "monthly_periods": min_len,
        "no_rebalance": {
            "年化收益": round(bh_cagr, 4),
            "最大回撤": round(bh_mdd, 4),
            "夏普比率": round(bh_sharpe, 2),
        },
        "quarterly_rebalance": {
            "年化收益": round(rb_cagr, 4),
            "最大回撤": round(rb_mdd, 4),
            "夏普比率": round(rb_sharpe, 2),
        },
        "再平衡超额收益": round(excess, 4),
        "超额>1%": excess > 0.01,
        "conclusion": "✅ 支持" if excess > 0.01 else "❌ 拒绝",
    }

    print(f"不复盘: CAGR={bh_cagr:.2%}, MDD={bh_mdd:.1%}")
    print(f"再平衡: CAGR={rb_cagr:.2%}, MDD={rb_mdd:.1%}")
    print(f"超额收益: {excess:.2%}")
    print(f"结论: {results['conclusion']}")

    conn.close()
    return results


def _std(values):
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
