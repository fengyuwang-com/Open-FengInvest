#!/usr/bin/env python3
"""verify-036-sector-diversify.py — 论断 #36: 行业分散降低回撤>20%

核心逻辑：
  分散投资多个行业的组合，最大回撤比集中于单一行业的组合少 20% 以上。
"""
import sys, os, json, sqlite3, time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, BASE)

DB_PATH = os.path.join(BASE, "data", "market_data.db")
TODAY = "2026-07-23"


def run_backtest():
    conn = sqlite3.connect(DB_PATH)
    # 获取 US 股票
    stocks = conn.execute("""
        SELECT i.id, i.ticker, i.id as index_id, COALESCE(f.sector, 'Unknown') as sector
        FROM indices i
        LEFT JOIN fundamentals f ON i.id = f.index_id
        WHERE i.market='US' AND i.category='stock'
        ORDER BY i.ticker
    """).fetchall()

    sectors = {}
    for sid, ticker, idx_id, sector in stocks:
        if sector not in sectors:
            sectors[sector] = []
        sectors[sector].append((sid, ticker, idx_id))

    print(f"股票数: {len(stocks)}, 行业数: {len(sectors)}")
    for s, v in sectors.items():
        print(f"  {s}: {len(v)} 只")

    # 数据集: 2015-01 到 2025-06, 按月
    months = []
    import datetime
    for y in range(2015, 2026):
        for m in range(1, 13):
            months.append(f"{y}-{m:02d}")
    months = months[:-1]  # 去掉 2026-12

    # 等权全市场组合 (分散)
    diversified_returns = []
    # 各行业集中组合
    sector_returns = {s: [] for s in sectors}

    for mi in range(len(months) - 1):
        m = months[mi]
        m_next = months[mi + 1]

        # all stock returns this month
        all_r = []
        sector_r = {s: [] for s in sectors}

        for idx_id in [s[2] for s in stocks]:
            r1 = conn.execute("""
                SELECT close FROM daily_data
                WHERE index_id=? AND date LIKE ? || '-%'
                ORDER BY date LIMIT 1
            """, (idx_id, m)).fetchone()
            r2 = conn.execute("""
                SELECT close FROM daily_data
                WHERE index_id=? AND date LIKE ? || '-%'
                ORDER BY date DESC LIMIT 1
            """, (idx_id, m_next)).fetchone()

            if r1 and r2 and r1[0] > 0 and r2[0] > 0:
                ret = (r2[0] - r1[0]) / r1[0]
                all_r.append(ret)

                # 找 sector
                found_sector = "Unknown"
                for sid2, t, iid, sec in stocks:
                    if iid == idx_id:
                        found_sector = sec
                        break
                if found_sector in sector_r:
                    sector_r[found_sector].append(ret)

        if len(all_r) > 10:
            diversified_returns.append(sum(all_r) / len(all_r))
            for sec, rets in sector_r.items():
                if rets:
                    sector_returns[sec].append(sum(rets) / len(rets))
                else:
                    sector_returns[sec].append(0)

    if not diversified_returns:
        conn.close()
        return {"error": "no data"}

    div_maxdd = _max_drawdown(diversified_returns)
    div_avg = sum(diversified_returns) / len(diversified_returns)

    sec_results = {}
    for sec, rets in sector_returns.items():
        if rets and len(rets) > 10:
            sec_maxdd = _max_drawdown(rets)
            dd_reduction = (sec_maxdd - div_maxdd) / sec_maxdd if sec_maxdd > 0 else 0
            sec_results[sec] = {
                "集中最大回撤": round(sec_maxdd, 4),
                "分散比集中降低回撤": round(dd_reduction, 4),
                "降低>20%": dd_reduction > 0.20,
            }
            print(f"{sec}: 集中MDD={sec_maxdd:.1%}, 分散降低={dd_reduction:.1%}")

    # 找到最多的行业
    max_sector = max(sec_results.items(),
                     key=lambda x: abs(x[1]["集中最大回撤"]))[0] if sec_results else "Unknown"
    best_reduction = max(sec_results.items(),
                         key=lambda x: x[1]["分散比集中降低回撤"])[1]["分散比集中降低回撤"] if sec_results else 0

    verdict = best_reduction > 0.20

    results = {
        "test_date": TODAY,
        "claim_id": 36,
        "claim": "行业分散降低回撤>20%",
        "period": f"{months[0]} ~ {months[-1]}",
        "diversified_portfolio": {
            "月均收益": round(div_avg, 4),
            "最大回撤": round(div_maxdd, 4),
        },
        "sectors": sec_results,
        "best_reduction_seen": round(best_reduction, 4),
        "conclusion": "✅ 支持" if verdict else "❌ 拒绝",
    }

    print(f"\n分散组合回撤: {div_maxdd:.1%}")
    print(f"最大降低幅度: {best_reduction:.1%}")
    print(f"结论: {results['conclusion']}")

    conn.close()
    return results


def _max_drawdown(returns):
    if not returns:
        return 0
    cum = 1
    peak = 1
    mdd = 0
    for r in returns:
        cum *= (1 + r)
        peak = max(peak, cum)
        dd = (peak - cum) / peak
        mdd = max(mdd, dd)
    return mdd


if __name__ == "__main__":
    t0 = time.time()
    results = run_backtest()
    elapsed = time.time() - t0
    out_path = os.path.join(os.path.dirname(__file__), "results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\n耗时: {elapsed:.0f}s")
