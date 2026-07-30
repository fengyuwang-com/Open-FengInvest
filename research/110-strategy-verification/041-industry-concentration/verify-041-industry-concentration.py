#!/usr/bin/env python3
"""verify-041-industry-concentration.py — 论断 #41

当组合行业集中度超过 40% 时，发生 -30% 回撤的概率超过 50%。

方法:
  1. 从数据库获取 US 股票及行业分类
  2. 构建行业等权月度收益率序列 (2010-01 ~ 2025-12)
  3. 蒙特卡洛模拟: 每月构建随机多行业组合（不同集中度），跟踪未来 12 个月
  4. 按集中度分桶，统计各桶崩溃概率
  5. 对比条件概率 P(崩溃 | 集中度>40%) vs P(崩溃 | 集中度<20%)

数据库:
  - indices(id, ticker, name, market, category)
  - daily_data(id, index_id, date, close)
  - fundamentals(index_id, sector, industry, ...)
  - 关联: indices.id = daily_data.index_id = fundamentals.index_id
"""
import sys
import os
import json
import sqlite3
import time
import random
import math
from collections import defaultdict

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, BASE)

DB_PATH = os.path.join(BASE, "data", "market_data.db")
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
TODAY = "2026-07-23"

random.seed(42)

# =========================== 参数 ===========================
LOOKBACK_MONTHS = 12          # 主回测展望期
ADDITIONAL_HORIZONS = [6, 24]  # 稳健性检查追加期
SIMULATIONS_PER_MONTH = 200   # 每月模拟组合数
CRASH_THRESHOLD = 0.30        # -30% 回撤阈值
CONCENTRATION_THRESHOLD = 0.40  # 40% 集中度阈值
N_SECTOR_RANGE = (2, 8)       # 每个组合随机选择行业数范围


def get_stock_sector_map(conn):
    """获取 stock_id -> sector, sector -> [stock_id] 映射。

    只保留同时有 sector 分类的股票。
    """
    rows = conn.execute("""
        SELECT i.id, f.sector
        FROM indices i
        JOIN fundamentals f ON i.id = f.index_id
        WHERE i.market='US' AND i.category='stock'
          AND f.sector IS NOT NULL AND f.sector != ''
    """).fetchall()

    stock_to_sector = {}
    sector_to_stocks = defaultdict(list)
    for idx_id, sector in rows:
        stock_to_sector[idx_id] = sector
        sector_to_stocks[sector].append(idx_id)

    return stock_to_sector, dict(sector_to_stocks)


def compute_sector_monthly_returns(conn, stock_to_sector):
    """为每个行业计算等权月度收益率。

    对每个行业，取该行业所有股票月末收盘价的等权平均，
    计算月度收益率序列。

    Returns:
        sector_returns: {sector: {YYYY-MM: 收益率}}
        months: 完整月份列表
    """
    # ---- 收集每只股票月末收盘价 ----
    rows = conn.execute("""
        SELECT d.index_id, d.date, d.close
        FROM daily_data d
        JOIN indices i ON d.index_id = i.id
        WHERE i.market='US' AND i.category='stock'
          AND d.date >= '2009-01-01' AND d.date <= '2025-12-31'
        ORDER BY d.index_id, d.date
    """).fetchall()

    # stock_prices: {index_id: [(YYYY-MM, close), ...]}
    stock_prices = defaultdict(list)
    for idx_id, date_str, close in rows:
        stock_prices[idx_id].append((date_str[:7], close))

    # stock_monthly: {index_id: {YYYY-MM: last_close}}
    stock_monthly = {}
    for sid, prices in stock_prices.items():
        monthly = {}
        for ym, close in prices:
            monthly[ym] = close  # 数据已排序，后面的覆盖得月末最后交易日
        stock_monthly[sid] = monthly

    # ---- 完整月份列表 ----
    months = []
    for y in range(2009, 2026):
        for m in range(1, 13):
            months.append(f"{y}-{m:02d}")

    # ---- 按行业分组计算等权收益率 ----
    sector_to_ids = defaultdict(list)
    for sid, sec in stock_to_sector.items():
        sector_to_ids[sec].append(sid)

    sector_returns = {}
    for sec, ids in sector_to_ids.items():
        monthly_rets = {}
        for mi in range(1, len(months)):
            prev_m = months[mi - 1]
            curr_m = months[mi]

            stock_rets = []
            for sid in ids:
                sm = stock_monthly.get(sid, {})
                if prev_m in sm and curr_m in sm:
                    p_prev = sm[prev_m]
                    p_curr = sm[curr_m]
                    if p_prev > 0 and p_curr > 0:
                        r = (p_curr - p_prev) / p_prev
                        stock_rets.append(r)

            if stock_rets:
                monthly_rets[curr_m] = sum(stock_rets) / len(stock_rets)

        sector_returns[sec] = monthly_rets

    return sector_returns, months


def generate_random_weights(n):
    """生成 n 个正权重，和为 1（均匀 Dirichlet 分布）。"""
    xs = [random.random() for _ in range(n)]
    total = sum(xs)
    return [x / total for x in xs]


def max_drawdown(monthly_returns):
    """计算最大回撤。返回正数（如 0.30 = 回撤 30%）。"""
    if not monthly_returns:
        return 0.0
    cum = 1.0
    peak = 1.0
    mdd = 0.0
    for r in monthly_returns:
        if not math.isfinite(r):
            continue
        cum *= (1.0 + r)
        peak = max(peak, cum)
        dd = (peak - cum) / peak
        if dd > mdd:
            mdd = dd
    return mdd


def simulate_portfolios(sector_returns, months):
    """蒙特卡洛模拟：每月构建随机组合，跟踪多期展望。

    对每个起始月份：
      1. 随机选择 2~8 个行业
      2. 随机分配权重（产生不同集中度）
      3. 计算未来 6/12/24 个月的组合收益率
      4. 计算最大回撤

    Returns:
        {horizon: [{concentration, max_drawdown, crash}, ...]}
    """
    sector_names = list(sector_returns.keys())

    # 将 sector_returns 转换为 {sector: {month: ret}} 的简单字典
    sec_data = {sec: sector_returns[sec] for sec in sector_names}

    # 预分配结果容器
    horizons = sorted(set([LOOKBACK_MONTHS] + ADDITIONAL_HORIZONS))
    all_results = {h: [] for h in horizons}

    sim_months_done = 0

    for mi, start_month in enumerate(months):
        # 只模拟 2010-01 到 2024-12
        if start_month < "2010-01" or start_month >= "2025-01":
            continue

        # 检查可用的月份长度
        max_offset = max(horizons)
        if mi + max_offset >= len(months):
            continue

        for _ in range(SIMULATIONS_PER_MONTH):
            # ---- 构建随机组合 ----
            n_secs = random.randint(
                N_SECTOR_RANGE[0],
                min(N_SECTOR_RANGE[1], len(sector_names))
            )
            chosen = random.sample(sector_names, n_secs)
            weights = generate_random_weights(n_secs)
            concentration = max(weights)

            # ---- 预取各行业最近 max_offset 个月的收益率 ----
            # 避免后续重复查字典
            sec_rets = {}
            for sec in chosen:
                sec_rets[sec] = sec_data[sec]

            # ---- 对各展望期分别计算 ----
            for horizon in horizons:
                port_rets = []
                for offset in range(1, horizon + 1):
                    curr_m = months[mi + offset]
                    total_ret = 0.0
                    has_data = False
                    for w, sec in zip(weights, chosen):
                        r = sec_rets[sec].get(curr_m)
                        if r is not None:
                            total_ret += w * r
                            has_data = True
                    if has_data:
                        port_rets.append(total_ret)

                # 至少需要 horizon/2 个月数据才有效
                if len(port_rets) >= max(3, horizon // 2):
                    mdd = max_drawdown(port_rets)
                    all_results[horizon].append({
                        "concentration": round(concentration, 4),
                        "max_drawdown": round(mdd, 4),
                        "crash": mdd > CRASH_THRESHOLD,
                    })

        sim_months_done += 1
        if sim_months_done % 24 == 0:
            print(f"    完成 {sim_months_done} 个起始月 ({start_month})")

    return all_results


def bin_by_concentration(results, buckets):
    """按集中度分桶统计。

    Args:
        results: [{concentration, max_drawdown, crash}, ...]
        buckets: [(lo, hi, label), ...]

    Returns:
        [{concentration_bucket, n_portfolios, n_crashes,
          crash_probability, avg_max_drawdown}, ...]
    """
    bucket_data = []
    for lo, hi, label in buckets:
        subset = [r for r in results if lo <= r["concentration"] < hi]
        if not subset:
            continue
        n_total = len(subset)
        n_crashes = sum(1 for r in subset if r["crash"])
        crash_prob = n_crashes / n_total if n_total > 0 else 0
        avg_mdd = sum(r["max_drawdown"] for r in subset) / n_total

        bucket_data.append({
            "concentration_bucket": label,
            "n_portfolios": n_total,
            "n_crashes": n_crashes,
            "crash_probability": round(crash_prob, 4),
            "avg_max_drawdown": round(avg_mdd, 4),
        })
    return bucket_data


def conditional_probability(results, threshold):
    """计算条件概率 P(崩溃 | 集中度 > threshold)。"""
    high = [r for r in results if r["concentration"] >= threshold]
    low = [r for r in results if r["concentration"] < 0.20]
    mid = [r for r in results if 0.20 <= r["concentration"] < threshold]

    def _p(bin_results):
        if not bin_results:
            return 0
        return sum(1 for r in bin_results if r["crash"]) / len(bin_results)

    return {
        "p_crash_given_concentration_gt_{:.0f}pct".format(threshold * 100): round(_p(high), 4),
        "p_crash_given_concentration_20_{:.0f}pct".format(threshold * 100 - 1): round(_p(mid), 4),
        "p_crash_given_concentration_lt_20pct": round(_p(low), 4),
        "n_high_concentration": len(high),
        "n_mid_concentration": len(mid),
        "n_low_concentration": len(low),
        "high_vs_low_ratio": round(_p(high) / _p(low), 2) if _p(low) > 0 else None,
    }


def analyze_concentration_distribution(results):
    """分析模拟组合的集中度分布。"""
    concs = [r["concentration"] for r in results]
    if not concs:
        return {}
    concs.sort()
    n = len(concs)
    return {
        "min": round(concs[0], 4),
        "p25": round(concs[n // 4], 4),
        "p50": round(concs[n // 2], 4),
        "p75": round(concs[3 * n // 4], 4),
        "max": round(concs[-1], 4),
        "mean": round(sum(concs) / n, 4),
        "n_above_40pct": sum(1 for c in concs if c >= 0.40),
        "n_below_20pct": sum(1 for c in concs if c < 0.20),
    }


def run_backtest():
    """主回测入口。"""
    print("=" * 62)
    print("  FengInvest — 投资论断 #41: 行业集中度与回撤风险")
    print("=" * 62)
    print()
    print(f"  论断：当组合行业集中度超过 40% 时，发生 -30% 回撤的概率超过 50%。")
    print()

    conn = sqlite3.connect(DB_PATH)

    # ===== 步骤 1: 获取行业映射 =====
    print("[1/5] 加载 US 股票行业映射...")
    stock_to_sector, sector_to_stocks = get_stock_sector_map(conn)
    sector_names = sorted(sector_to_stocks.keys())
    print(f"  -> {len(stock_to_sector)} 只股票, {len(sector_names)} 个行业")
    for sec in sector_names:
        print(f"      {sec}: {len(sector_to_stocks[sec])} 只")
    print()

    # ===== 步骤 2: 计算行业月度收益率 =====
    print("[2/5] 计算行业等权月度收益率 (2010-01 ~ 2025-12)...")
    t0 = time.time()
    sector_returns, months = compute_sector_monthly_returns(conn, stock_to_sector)
    for sec in sector_names:
        n_months = len(sector_returns.get(sec, {}))
        print(f"      {sec}: {n_months} 个月")
    print(f"      耗时 {time.time()-t0:.1f}s")
    print()

    conn.close()

    # ===== 步骤 3: 蒙特卡洛模拟 =====
    print(f"[3/5] 蒙特卡洛模拟 ({SIMULATIONS_PER_MONTH} 组合/起始月, "
          f"起始月范围: 2010-01 ~ 2024-12)...")
    t0 = time.time()
    all_results = simulate_portfolios(sector_returns, months)
    for h in sorted(all_results.keys()):
        print(f"      展望 {h:2d} 个月: {len(all_results[h])} 个组合")
    print(f"      模拟耗时 {time.time()-t0:.1f}s")
    print()

    # ===== 步骤 4: 分桶分析 =====
    print("[4/5] 分桶分析...")

    BUCKETS = [
        (0.0, 0.20, "<20%"),
        (0.20, 0.30, "20-30%"),
        (0.30, 0.40, "30-40%"),
        (0.40, 0.50, "40-50%"),
        (0.50, 0.60, "50-60%"),
        (0.60, 0.70, "60-70%"),
        (0.70, 0.80, "70-80%"),
        (0.80, 1.01, ">80%"),
    ]

    horizons = sorted(all_results.keys())
    horizons_output = {}
    primary_verdict = None
    primary_detail = None

    for h in horizons:
        results = all_results[h]
        bucket_data = bin_by_concentration(results, BUCKETS)
        cond_prob = conditional_probability(results, CONCENTRATION_THRESHOLD)
        conc_dist = analyze_concentration_distribution(results)

        # 主论断验证（针对 12 个月展望期）
        p_high = cond_prob[
            "p_crash_given_concentration_gt_{:.0f}pct".format(
                CONCENTRATION_THRESHOLD * 100)]

        is_supported = p_high > 0.50
        if h == LOOKBACK_MONTHS:
            if is_supported:
                primary_verdict = "支持"
                primary_detail = (
                    f"集中度>{CONCENTRATION_THRESHOLD:.0%} 时 "
                    f"崩溃概率 {p_high:.1%} > 50% 阈值 -- 论断成立"
                )
            else:
                primary_verdict = "拒绝"
                primary_detail = (
                    f"集中度>{CONCENTRATION_THRESHOLD:.0%} 时 "
                    f"崩溃概率 {p_high:.1%} <= 50% 阈值 -- 论断不成立"
                )

        # 打印分桶表
        print(f"\n  --- 展望 {h} 个月 ---")
        print(f"  {'集中度桶':>10s}  {'组合数':>7s}  {'崩溃数':>6s}  "
              f"{'崩溃概率':>8s}  {'平均MDD':>8s}")
        print(f"  {'-'*10}  {'-'*7}  {'-'*6}  {'-'*8}  {'-'*8}")
        for bd in bucket_data:
            print(f"  {bd['concentration_bucket']:>10s}  "
                  f"{bd['n_portfolios']:>7d}  "
                  f"{bd['n_crashes']:>6d}  "
                  f"{bd['crash_probability']:>7.1%}  "
                  f"{bd['avg_max_drawdown']:>7.1%}")

        print(f"  P(崩溃 | 集中度>{CONCENTRATION_THRESHOLD:.0%}) = "
              f"{cond_prob['p_crash_given_concentration_gt_{:.0f}pct'.format(CONCENTRATION_THRESHOLD * 100)]:.1%}"
              f"  (n={cond_prob['n_high_concentration']})")
        print(f"  P(崩溃 | 集中度<20%) = "
              f"{cond_prob['p_crash_given_concentration_lt_20pct']:.1%}"
              f"  (n={cond_prob['n_low_concentration']})")
        print(f"  高风险/低风险比值 = "
              f"{cond_prob['high_vs_low_ratio']}x")

        if h == LOOKBACK_MONTHS:
            print(f"  >> 结论: {primary_verdict} ({primary_detail})")

        horizons_output[f"horizon_{h}m"] = {
            "horizon_months": h,
            "n_portfolios": len(results),
            "concentration_distribution": conc_dist,
            "concentration_buckets": bucket_data,
            "conditional_probabilities": cond_prob,
            "verdict": primary_verdict if h == LOOKBACK_MONTHS else None,
            "verdict_detail": primary_detail if h == LOOKBACK_MONTHS else None,
        }

    # ===== 步骤 5: 稳健性检查 — 不同崩溃阈值 =====
    print("\n[5/5] 稳健性检查: 不同崩溃阈值...")

    alt_thresholds = [0.20, 0.30, 0.40]
    robustness = {}
    for alt_t in alt_thresholds:
        results_12m = all_results[LOOKBACK_MONTHS]
        high_conc = [r for r in results_12m if r["concentration"] >= CONCENTRATION_THRESHOLD]
        low_conc = [r for r in results_12m if r["concentration"] < 0.20]
        p_h = (sum(1 for r in high_conc if r["max_drawdown"] > alt_t)
               / len(high_conc)) if high_conc else 0
        p_l = (sum(1 for r in low_conc if r["max_drawdown"] > alt_t)
               / len(low_conc)) if low_conc else 0
        pct_label = int(alt_t * 100)
        robustness[f"crash_{pct_label}pct"] = {
            "threshold": alt_t,
            "p_crash_high_conc": round(p_h, 4),
            "p_crash_low_conc": round(p_l, 4),
        }
        ratio_str = f"比值={p_h/p_l:.1f}x" if p_l > 0 else "比值=N/A"
        print(f"  -{alt_t:.0%} 崩溃阈值: "
              f"P(高集中)={p_h:.1%}, P(低集中)={p_l:.1%}, {ratio_str}")
    print()

    # ===== 构建输出 =====
    final = {
        "test_date": TODAY,
        "claim_id": 41,
        "claim": "当组合行业集中度超过 40% 时，发生 -30% 回撤的概率超过 50%",
        "method": (
            "Sector-level Monte Carlo simulation. "
            "For each month from 2010-01 to 2024-12, generate random portfolios "
            "across 2-8 sectors with random weights (uniform Dirichlet). "
            "Track each portfolio for 6, 12, and 24 months forward. "
            "Record sector concentration (max sector weight) and max drawdown. "
            "Bin by concentration level and compute crash probabilities."
        ),
        "period": "2010-01 ~ 2024-12",
        "simulation_params": {
            "n_simulations_per_month": SIMULATIONS_PER_MONTH,
            "start_months": 180,
            "sectors_used": len(sector_names),
            "stocks_in_pool": len(stock_to_sector),
            "crash_threshold": CRASH_THRESHOLD,
            "concentration_threshold": CONCENTRATION_THRESHOLD,
            "lookback_months": LOOKBACK_MONTHS,
            "robustness_horizons": ADDITIONAL_HORIZONS,
        },
        "results_by_horizon": horizons_output,
        "robustness_by_crash_threshold": robustness,
        "conclusion": primary_verdict,
        "conclusion_detail": primary_detail,
    }

    # ===== 打印总结 =====
    print("=" * 62)
    print(f"  最终结论: {primary_verdict}")
    if primary_detail:
        print(f"  {primary_detail}")
    print("=" * 62)

    return final


if __name__ == "__main__":
    t_start = time.time()
    results = run_backtest()
    elapsed = time.time() - t_start

    out_path = os.path.join(OUT_DIR, "results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\n结果已保存: {out_path}")
    print(f"总耗时: {elapsed:.0f}s")
