#!/usr/bin/env python3
"""fengscreen.py — 多因子全市场筛选工具（四维排名系统）

设计文档: research/050-strategies/100-value-screening-design.md

用法:
  python tools/fengscreen.py --market US --top 30         # 美股 Top 30
  python tools/fengscreen.py --market US --top 50 --sort growth  # 按增长排名
  python tools/fengscreen.py --market HK                      # 港股
  python tools/fengscreen.py --output candidates.json          # 输出 JSON
"""

import argparse, json, math, os, sys, time
from pathlib import Path
from statistics import mean, stdev

TOOLS_DIR = Path(__file__).parent
PROJECT_DIR = TOOLS_DIR.parent

# ── 因子权重 ──
# 设计原则: 质量 > 价值 ≈ 增长 > 动量
# 权重来源于: docs/100-value-screening-design.md
WEIGHTS = {
    "value": 0.25,
    "quality": 0.35,
    "growth": 0.25,
    "momentum": 0.15,
}

# 估值安全边际阈值（FCF 收益率低于此值标记警告）
FCF_YIELD_MIN = 0.02  # 2%


def get_stock_list(market="US", top_n=200):
    """获取待筛选股票列表（当前从 DB 拉取，后续可扩展）"""
    import sqlite3

    db = PROJECT_DIR / "data" / "market_data.db"
    if not db.exists():
        print(f"[ERR] DB not found: {db}")
        sys.exit(1)

    conn = sqlite3.connect(str(db))
    cur = conn.execute(
        "SELECT id, ticker, name FROM indices WHERE market=? AND category='stock' ORDER BY ticker LIMIT ?",
        (market, top_n),
    )
    stocks = [{"id": r[0], "ticker": r[1], "name": r[2]} for r in cur.fetchall()]
    conn.close()
    return stocks


def fetch_fundamentals(ticker):
    """用 yfinance 获取一只股票的基本面数据"""
    import yfinance as yf

    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        if not info or info.get("regularMarketPrice") is None:
            return None

        price = info.get("regularMarketPrice") or info.get("currentPrice") or info.get("previousClose")
        if not price:
            return None

        # 基础数据
        mcap = info.get("marketCap") or 0
        pe = info.get("trailingPE") or info.get("forwardPE") or None
        pb = info.get("priceToBook") or None
        ps = info.get("priceToSalesTrailing12Months") or None
        dy = info.get("dividendYield") or 0
        fcf = info.get("freeCashflow") or 0
        fcf_yield = fcf / mcap if mcap > 0 else 0

        # 质量因子
        roe = info.get("returnOnEquity") or None
        margin = info.get("profitMargins") or None  # 净利润率
        gross_margin = info.get("grossMargins") or None
        de = info.get("debtToEquity") or None
        current_ratio = info.get("currentRatio") or None

        # 增长因子
        rev_growth = info.get("revenueGrowth") or None
        earn_growth = info.get("earningsGrowth") or None

        # 动量因子（6 个月收益率）
        momentum_6m = None
        try:
            hist = stock.history(period="7mo")
            close = hist["Close"].dropna()
            if len(close) >= 2:
                momentum_6m = (close.iloc[-1] / close.iloc[0]) - 1
        except Exception:
            pass

        return {
            "ticker": ticker,
            "name": info.get("shortName") or info.get("longName") or ticker,
            "sector": info.get("sector") or "Unknown",
            "industry": info.get("industry") or "Unknown",
            "price": price,
            "market_cap": mcap,
            # 价值因子
            "pe": pe,
            "pb": pb,
            "ps": ps,
            "dividend_yield": dy,
            "fcf_yield": fcf_yield,
            # 质量因子
            "roe": roe,
            "profit_margin": margin,
            "gross_margin": gross_margin,
            "debt_to_equity": de,
            "current_ratio": current_ratio,
            # 增长因子
            "revenue_growth": rev_growth,
            "earnings_growth": earn_growth,
            # 动量因子
            "momentum_6m": momentum_6m,
        }
    except Exception as e:
        return None


def normalized_zscore(values):
    """将数值列表转为 z-score（均值=0, 标准差=1）"""
    n = len(values)
    if n < 3:
        return [0.0] * n
    m = mean(values)
    s = stdev(values)
    if s == 0:
        return [0.0] * n
    return [(v - m) / s for v in values]


def rank_score(z_scores, higher_better=True):
    """z-score 转为 0-100 百分位分（可选方向）"""
    if not higher_better:
        z_scores = [-z for z in z_scores]
    # 用 CDF 近似: sigmoid(z/2) → 0-100
    return [round(100 / (1 + math.exp(-z / 2)), 1) for z in z_scores]


def compute_scores(stocks_data):
    """计算四维因子分数和综合排名"""
    n = len(stocks_data)
    if n == 0:
        return []

    # 提取各因子原始值（注意处理 None 和异常值）
    def extract(key, transform=None, default=0):
        vals = []
        for s in stocks_data:
            v = s.get(key)
            if v is not None and isinstance(v, (int, float)) and math.isfinite(v):
                vals.append(transform(v) if transform else v)
            else:
                vals.append(None)
        # 中位数填充
        valid = [v for v in vals if v is not None]
        med = sorted(valid)[len(valid) // 2] if valid else default
        return [v if v is not None else med for v in vals]

    # 价值因子（全部反向: 越低越好；负值→不低估）
    pe_vals = extract("pe", lambda x: 100 if x < 0 else min(x, 100))  # 负PE=亏损，不算低估
    pb_vals = extract("pb", lambda x: 20 if x < 0 else min(x, 20))
    dy_vals = extract("dividend_yield")  # 股息率越高越好（正向）
    fcf_vals = extract("fcf_yield")  # FCF 收益率越高越好（正向）

    # 质量因子（全部正向: 越高越好，debt_to_equity 反向）
    roe_vals = extract("roe", lambda x: max(min(x, 5), -5))  # 截断极端 ROE
    margin_vals = extract("profit_margin", lambda x: max(min(x, 1), -1))
    de_vals = extract("debt_to_equity", lambda x: math.log(max(x, 0.1) + 1))  # 对数，反向
    cr_vals = extract("current_ratio", lambda x: min(x, 10))

    # 增长因子（全部正向）
    rev_g_vals = extract("revenue_growth", lambda x: max(min(x, 3), -1))
    earn_g_vals = extract("earnings_growth", lambda x: max(min(x, 3), -1))

    # 动量因子（正向）
    mom_vals = extract("momentum_6m", lambda x: max(min(x, 3), -1))

    # ── 计算 z-score ──
    z_pe = normalized_zscore(pe_vals)  # 低 PE → 高分
    z_pb = normalized_zscore(pb_vals)
    z_dy = normalized_zscore(dy_vals)  # 高股息 → 高分（正向）
    z_fcf = normalized_zscore(fcf_vals)

    z_roe = normalized_zscore(roe_vals)
    z_margin = normalized_zscore(margin_vals)
    z_de = normalized_zscore(de_vals)  # 低负债 → 高分（反向）
    z_cr = normalized_zscore(cr_vals)  # 高流动比 → 高分（正向）

    z_rev = normalized_zscore(rev_g_vals)
    z_earn = normalized_zscore(earn_g_vals)

    z_mom = normalized_zscore(mom_vals)

    # ── 维度聚合 ──
    # 价值维度: PE(反) + PB(反) + 股息(正) + FCF(正)
    value_scores = rank_score(
        [-(z_pe[i] + z_pb[i]) / 2 + (z_dy[i] + z_fcf[i]) / 2 for i in range(n)]
    )

    # 质量维度: ROE(正) + 利润率(正) + 低负债(正) + 流动比(正)
    quality_scores = rank_score(
        [(z_roe[i] + z_margin[i] + (-z_de[i]) + z_cr[i]) / 4 for i in range(n)]
    )

    # 增长维度: 营收增长 + 盈利增长
    growth_scores = rank_score(
        [(z_rev[i] + z_earn[i]) / 2 for i in range(n)]
    )

    # 动量维度: 6m 收益率 + 相对强度（z_mom 本身已考虑全市场）
    momentum_scores = rank_score([z_mom[i] for i in range(n)])

    # 综合分
    total_scores = []
    for i in range(n):
        total = (
            value_scores[i] * WEIGHTS["value"]
            + quality_scores[i] * WEIGHTS["quality"]
            + growth_scores[i] * WEIGHTS["growth"]
            + momentum_scores[i] * WEIGHTS["momentum"]
        )
        total_scores.append(round(total, 1))

    # 组装结果
    results = []
    for i in range(n):
        d = stocks_data[i]
        results.append({
            "rank": 0,  # 排序后更新
            "ticker": d["ticker"],
            "name": d["name"],
            "sector": d["sector"],
            "price": d.get("price"),
            "market_cap": d.get("market_cap"),
            "scores": {
                "total": total_scores[i],
                "value": value_scores[i],
                "quality": quality_scores[i],
                "growth": growth_scores[i],
                "momentum": momentum_scores[i],
            },
            "factors": {
                "pe": d.get("pe"),
                "pb": d.get("pb"),
                "dividend_yield": d.get("dividend_yield"),
                "fcf_yield": d.get("fcf_yield"),
                "roe": d.get("roe"),
                "profit_margin": d.get("profit_margin"),
                "debt_to_equity": d.get("debt_to_equity"),
                "revenue_growth": d.get("revenue_growth"),
                "earnings_growth": d.get("earnings_growth"),
                "momentum_6m": d.get("momentum_6m"),
            },
        })

    # 按综合分排序
    results.sort(key=lambda r: r["scores"]["total"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    return results


def print_table(results, top_n=30):
    """打印排名表格"""
    print(f"\n{'=' * 90}")
    print(f"  多因子排名（综合: 价值×{WEIGHTS['value']} + 质量×{WEIGHTS['quality']}"
          f" + 增长×{WEIGHTS['growth']} + 动量×{WEIGHTS['momentum']}）")
    print(f"{'=' * 90}")
    print(f"{'排名':<6} {'代码':<10} {'名称':<24} {'综合':>6} {'价值':>6} {'质量':>6} {'增长':>6} {'动量':>6} {'PE':>8}")
    print(f"{'-' * 72}")

    for r in results[:top_n]:
        s = r["scores"]
        f = r["factors"]
        name = (r["name"][:23] + "…") if r["name"] and len(r["name"]) > 23 else (r["name"] or "")
        pe_str = f"{f['pe']:.1f}" if f.get("pe") else "N/A"
        print(f"{r['rank']:<6} {r['ticker']:<10} {name:<24} {s['total']:>6.1f} "
              f"{s['value']:>6.1f} {s['quality']:>6.1f} {s['growth']:>6.1f} "
              f"{s['momentum']:>6.1f} {pe_str:>8}")

    print(f"\n  [TOP {min(top_n, len(results))} 显示, 共 {len(results)} 只股票]")

    # 胜出行业分析
    sectors = {}
    for r in results[:20]:
        sec = r.get("sector", "Unknown")
        sectors[sec] = sectors.get(sec, 0) + 1
    print(f"\n  Top 20 行业分布:")
    for sec, cnt in sorted(sectors.items(), key=lambda x: -x[1]):
        bar = "█" * cnt
        print(f"    {bar} {sec} ({cnt})")


def run_screen(market="US", top_n=200, output=None):
    """主筛选流程"""
    t0 = time.time()

    # 获取股票列表
    print(f"[DATA] Loading stock list for {market}...", flush=True)
    stocks = get_stock_list(market, top_n)
    print(f"[DATA] {len(stocks)} stocks to screen", flush=True)

    # 逐个获取基本面
    results_data = []
    fetched = 0
    for stock in stocks:
        data = fetch_fundamentals(stock["ticker"])
        if data:
            results_data.append(data)
        fetched += 1
        if fetched % 50 == 0:
            print(f"  [WAIT] {fetched}/{len(stocks)} processed...", flush=True)

    print(f"[DATA] {len(results_data)} stocks with fundamentals data", flush=True)
    if len(results_data) < 10:
        print(f"[WARN] 样本量不足 ({len(results_data)}), 排名参考价值有限")

    # 计算得分
    results = compute_scores(results_data)

    # 输出
    print_table(results, 30)

    if output:
        with open(output, "w", encoding="utf-8") as f:
            json.dump(results[:50], f, ensure_ascii=False, indent=2)
        print(f"\n[SAVED] Top 50 已保存: {output}")

    elapsed = time.time() - t0
    print(f"\n[DONE] {elapsed:.1f}s ({len(results_data)} stocks × 4 dimensions)")
    return results


if __name__ == "__main__":
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="全市场多因子筛选引擎")
    parser.add_argument("--market", default="US", help="市场代码 (US/HK/CN, 默认 US)")
    parser.add_argument("--top", type=int, default=200, help="从数据库读取最多股票数 (默认 200)")
    parser.add_argument("--display", type=int, default=30, help="显示前 N 名 (默认 30)")
    parser.add_argument("--output", "-o", help="输出 JSON 文件路径")
    args = parser.parse_args()

    run_screen(market=args.market, top_n=args.top, output=args.output)
