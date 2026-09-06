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
        # 估值口径：PE 属 EP（盈利收益率）口径，Liu-Stambaugh-Yuan 2019 支持 A 股价值因子首选 EP 而非 BM
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

    # ⚠️ A 股估值口径风险：A 股价值因子首选 EP 而非 BM（Liu-Stambaugh-Yuan 2019《Size and Value in China》）；
    # 本筛选支持 --market CN（A 股），价值维度对 PB 反向计分即 BM 口径（与 PE 各占价值分一半），
    # 用于 A 股时需在结果解读中注明此口径风险（仅注释，不改逻辑）。
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


# ═══════════════════════════════════════════════════════════════════
# --hard-rules 模式：7 条硬指标 + 3 条豁免（纯规则，零 LLM）
# 规则定义来自 .agents/skills/fengscreen/SKILL.md，宁可不误杀：
#   数据不足的指标标 N/A 不判 FAIL；数据整体拿不到 → SKIP（不算 FAIL）
# ═══════════════════════════════════════════════════════════════════

HARD_RULES_DEF = [
    ("r1", "10年平均ROE<8%", "roe_avg", 0.08, "lt"),
    ("r2", "5年累计FCF为负", "fcf_sum", 0.0, "lt"),
    ("r3", "利息覆盖<2x", "interest_coverage", 2.0, "lt"),
    ("r4", "长期毛利率<15%", "gross_margin_avg", 0.15, "lt"),
    ("r5", "OCF/净利润5年均值<0.7", "ocf_ni_avg", 0.7, "lt"),
    ("r6", "长期净利率<5%", "net_margin_avg", 0.05, "lt"),
    ("r7", "股本膨胀>20%", "share_dilution", 0.20, "gt"),
]

LISTS_CONFIG_PATH = PROJECT_DIR / "data" / "config" / "batch_lists.json"


def load_lists_config():
    with open(LISTS_CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def _norm_cn_code(code):
    """6 位数字代码 / .SH 后缀 → yfinance 格式（6/9/5 开头→.SS，0/3 开头→.SZ）"""
    code = code.strip()
    if code.isdigit() and len(code) == 6:
        return code + (".SS" if code.startswith(("6", "9", "5")) else ".SZ")
    if code.endswith(".SH"):
        code = code[:-3] + ".SS"
    return code


def fetch_list_tickers(list_name):
    """按 batch_lists.json 配置拉取 list 成分，返回 (tickers, source_desc)。
    拉取失败 raise RuntimeError，由调用方决定降级。"""
    cfg = load_lists_config().get(list_name)
    if not cfg:
        raise RuntimeError(
            f"未知 list: {list_name}。内置 list: {', '.join(load_lists_config().keys())}；"
            f"自定义请用 --file"
        )
    static_file = PROJECT_DIR / cfg.get("static_file", "")
    if static_file.exists():
        tickers = read_tickers_file(static_file)
        if tickers:
            return tickers, f"静态文件 {static_file}"

    source = cfg.get("source", "")
    try:
        if "csindex" in source or list_name == "cn_dividend":
            import akshare as ak
            df = ak.index_stock_cons_csindex(symbol="000922")
            col = "成分券代码" if "成分券代码" in df.columns else df.columns[0]
            tickers = [_norm_cn_code(str(c)) for c in df[col].tolist()]
            return tickers, "akshare 中证指数接口"
        if "nasdaq100" in source or list_name == "us_quality":
            import akshare as ak
            df = ak.index_stock_cons_nasdaq100()
            col = "代码" if "代码" in df.columns else df.columns[0]
            tickers = [str(c).strip().upper() for c in df[col].tolist()]
            return tickers, "akshare 纳指100接口"
    except ImportError:
        raise RuntimeError(
            "akshare 未安装，无法拉取该 list。安装命令（清华镜像）:\n"
            "  pip install akshare -i https://pypi.tuna.tsinghua.edu.cn/simple\n"
            "或手动放静态文件: " + str(static_file) + "（每行一个代码）\n"
            "说明: " + cfg.get("manual_hint", "")
        )
    except Exception as e:
        raise RuntimeError(
            f"list '{list_name}' 接口拉取失败: {e}\n"
            f"降级方案: {cfg.get('manual_hint', '')}\n"
            f"或手动放静态文件（每行一个代码）: {static_file}"
        )
    raise RuntimeError(f"list '{list_name}' 无可用拉取方式。{cfg.get('manual_hint', '')}")


def read_tickers_file(path):
    """读 txt（一行一个代码）或 json（数组）。"""
    p = Path(path)
    with open(p, encoding="utf-8") as f:
        content = f.read().strip()
    if not content:
        return []
    if p.suffix.lower() == ".json" or content.startswith("["):
        arr = json.loads(content)
        return [str(t).strip() for t in arr if str(t).strip()]
    tickers = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 容忍 "600519 贵州茅台" 这种带名字的行，取第一列
        tickers.append(_norm_cn_code(line.split()[0]))
    return [_norm_cn_code(t) for t in tickers]


def _avg(vals):
    vals = [v for v in vals if v is not None and isinstance(v, (int, float)) and math.isfinite(v)]
    return (sum(vals) / len(vals)) if vals else None


def fetch_hard_data(ticker):
    """拉一只股票的多年财务数据供硬指标计算。返回 None = 数据整体失败 → SKIP。"""
    import yfinance as yf

    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        if not info or (info.get("regularMarketPrice") is None and info.get("marketCap") is None):
            return None

        def series(df, key):
            if df is None or df.empty or key not in df.index:
                return {}
            return {str(c)[:4]: df.loc[key, c] for c in df.columns}

        inc = stock.income_stmt
        cf = stock.cashflow
        bs = stock.balance_sheet

        ni = series(inc, "Net Income")
        rev = series(inc, "Total Revenue")
        gp = series(inc, "Gross Profit")
        ebit = series(inc, "Operating Income") or series(inc, "EBIT")
        ie = series(inc, "Interest Expense")
        shares = series(inc, "Diluted Average Shares")
        ocf = series(cf, "Operating Cash Flow")
        fcf = series(cf, "Free Cash Flow")
        if not fcf:
            # FCF 缺失时用 OCF - CapEx 近似
            capex = series(cf, "Capital Expenditure")
            if ocf and capex:
                fcf = {y: ocf[y] + (capex[y] if capex.get(y) else 0) for y in ocf}
        equity = series(bs, "Stockholders Equity") or series(bs, "Common Stockholders Equity")
        bs_shares = series(bs, "Ordinary Shares Number")

        years = sorted(set(ni) | set(rev) | set(ocf) | set(fcf), reverse=True)
        return {
            "name": info.get("shortName") or info.get("longName") or ticker,
            "info_roe": info.get("returnOnEquity"),
            "info_gm": info.get("grossMargins"),
            "info_nm": info.get("profitMargins"),
            "years": years,
            "ni": ni, "rev": rev, "gp": gp, "ebit": ebit, "ie": ie,
            "ocf": ocf, "fcf": fcf, "equity": equity,
            "shares": shares or bs_shares,
            "started_date": info.get("companyStartedDate"),
        }
    except Exception:
        return None


def compute_hard_metrics(d):
    """从多年数据计算硬指标值（部分可能为 None = 数据不足）。"""
    m = {}
    # r1 ROE: 净利润/股东权益 按年，均值（不足 10 年按实际年限，宁可不误杀）
    roes = [d["ni"][y] / d["equity"][y] for y in d["ni"]
            if d["equity"].get(y) and d["equity"][y] != 0 and d["ni"][y] is not None]
    m["roe_avg"] = _avg(roes)
    if m["roe_avg"] is None and d.get("info_roe") is not None:
        m["roe_avg"] = d["info_roe"]  # 兜底: 当期单年 ROE
    # r2 累计 FCF
    fcfv = [v for v in d["fcf"].values() if isinstance(v, (int, float)) and math.isfinite(v)]
    m["fcf_sum"] = sum(fcfv) if fcfv else None
    # r3 利息覆盖: EBIT / |利息费用| 按年均值
    icovs = [d["ebit"][y] / abs(d["ie"][y]) for y in d["ebit"]
             if d["ie"].get(y) not in (None, 0) and d["ebit"][y] is not None]
    m["interest_coverage"] = _avg(icovs)
    # r4 毛利率均值（缺失时用 info 当期兜底）
    gms = [d["gp"][y] / d["rev"][y] for y in d["gp"]
           if d["rev"].get(y) and d["gp"][y] is not None]
    m["gross_margin_avg"] = _avg(gms)
    if m["gross_margin_avg"] is None and d.get("info_gm") is not None:
        m["gross_margin_avg"] = d["info_gm"]
    # r5 OCF/NI 均值
    ratios = [d["ocf"][y] / d["ni"][y] for y in d["ocf"]
              if d["ni"].get(y) and d["ocf"][y] is not None]
    m["ocf_ni_avg"] = _avg(ratios)
    # r6 净利率均值（缺失时用 info 当期兜底）
    nms = [d["ni"][y] / d["rev"][y] for y in d["ni"]
           if d["rev"].get(y) and d["ni"][y] is not None]
    m["net_margin_avg"] = _avg(nms)
    if m["net_margin_avg"] is None and d.get("info_nm") is not None:
        m["net_margin_avg"] = d["info_nm"]
    # r7 股本膨胀：最早 vs 最新
    sh = {y: v for y, v in (d["shares"] or {}).items() if isinstance(v, (int, float)) and v}
    if len(sh) >= 2:
        first, last = sh[min(sh)], sh[max(sh)]
        m["share_dilution"] = (last - first) / abs(first) if first else None
    else:
        m["share_dilution"] = None
    return m


def _fmt_val(v, key=""):
    if not isinstance(v, (int, float)) or not math.isfinite(v):
        return "N/A"
    if any(k in key for k in ("margin", "dilution", "roe")):
        return f"{v*100:.1f}%"
    return f"{v:,.2f}"


def check_hard_rules(ticker, retries=2):
    """对一只股票跑 7 硬指标 + 3 豁免。返回结果 dict。"""
    data = None
    for i in range(retries + 1):
        data = fetch_hard_data(ticker)
        if data:
            break
        time.sleep(1.5 * (i + 1))
    if not data:
        return {"ticker": ticker, "name": "", "verdict": "SKIP",
                "reason": "数据获取失败（重试后仍无数据），不算 FAIL",
                "rules": {}, "exemptions": {}}

    m = compute_hard_metrics(data)
    rules = {}
    hit_any = False
    for rid, desc, key, thr, op in HARD_RULES_DEF:
        v = m.get(key)
        if v is None:
            rules[rid] = {"rule": desc, "value": None, "status": "N/A", "detail": "数据不足"}
        else:
            fail = (v < thr) if op == "lt" else (v > thr)
            hit_any = hit_any or fail
            rules[rid] = {"rule": desc, "value": round(float(v), 4),
                          "status": "FAIL" if fail else "PASS",
                          "detail": f"值={_fmt_val(v, key)} 阈值={thr}"}

    n_years = len(data["years"])
    coverage = f"财务年数={n_years}（10 年口径按实际可得年限算，宁可不误杀）"

    exemptions = {}
    if hit_any:
        gm = m.get("gross_margin_avg")
        ocf_sorted = sorted(data["ocf"])
        ocf_last = [data["ocf"][y] for y in ocf_sorted[-2:]] if ocf_sorted else []
        # A 战略投入期: 上市<10年 + 毛利率>30% + 近2年OCF为正
        started = data.get("started_date")
        listed_years = None
        if started:
            try:
                from datetime import datetime as _dt
                listed_years = (_dt.now() - _dt.fromisoformat(str(started)[:10])).days / 365.25
            except Exception:
                listed_years = None
        cond_a_year = listed_years is None or listed_years < 10
        cond_a_ocf = bool(ocf_last) and all(v > 0 for v in ocf_last)
        exemptions["A"] = {
            "name": "战略投入期",
            "triggered": bool(gm and gm > 0.30 and cond_a_year and cond_a_ocf),
            "reason": f"毛利率={_fmt_val(gm, 'margin')}, 上市年限={'未知' if listed_years is None else f'{listed_years:.0f}年'}, 近2年OCF为正={cond_a_ocf}",
        }
        # B 主动低利润率: 毛利率>30% + 净利率回升
        nms_sorted = sorted(set(data["ni"]) & set(data["rev"]))
        nm_rising = None
        if len(nms_sorted) >= 2:
            nm_first = data["ni"][nms_sorted[0]] / data["rev"][nms_sorted[0]]
            nm_last = data["ni"][nms_sorted[-1]] / data["rev"][nms_sorted[-1]]
            nm_rising = nm_last > nm_first
        exemptions["B"] = {
            "name": "主动低利润率",
            "triggered": bool(gm and gm > 0.30 and nm_rising),
            "reason": f"毛利率={_fmt_val(gm, 'margin')}, 净利率回升={nm_rising}",
        }
        # C 高周转薄利: ROE>20% + OCF/NI>1.0（会员/平台模式不可脚本化，留 AI 判断）
        roe, ocf_ni = m.get("roe_avg"), m.get("ocf_ni_avg")
        exemptions["C"] = {
            "name": "高周转薄利",
            "triggered": bool(roe and roe > 0.20 and ocf_ni and ocf_ni > 1.0),
            "reason": f"ROE={_fmt_val(roe, 'roe')}, OCF/NI={round(ocf_ni, 2) if ocf_ni else 'N/A'}（会员/平台模式需 AI 在 L2a 复核）",
        }
        triggered = [k for k, v in exemptions.items() if v["triggered"]]
        verdict = "EXEMPT" if triggered else "FAIL"
        failed = [rid for rid, info in rules.items() if info["status"] == "FAIL"]
        reason = f"命中规则: {failed}" + (f"；触发豁免: {triggered}" if triggered else "")
    else:
        verdict = "PASS"
        reason = "7 条硬指标全部通过（或数据不足不判负，宁可不误杀）"

    return {"ticker": ticker, "name": data["name"], "verdict": verdict, "reason": reason,
            "coverage": coverage, "rules": rules, "exemptions": exemptions}


def print_hard_rules_table(results):
    marks = {"PASS": "✅", "FAIL": "❌", "EXEMPT": "⚠️", "SKIP": "⏭️"}
    print(f"\n{'=' * 100}")
    print("  硬指标精筛（7 硬指标 + 3 豁免 | 宁可漏网不可误杀 | SKIP=数据拿不到不算 FAIL）")
    print(f"{'=' * 100}")
    for r in results:
        print(f"\n{marks.get(r['verdict'], '?')} {r['ticker']}  {r['name']}  → {r['verdict']}  {r['reason']}")
        if r["verdict"] == "SKIP":
            continue
        for rid, info in r["rules"].items():
            print(f"    [{info['status']:^4}] {info['rule']:<26} {_fmt_val(info['value'], info['rule'])}")
        for k, e in r.get("exemptions", {}).items():
            print(f"    (豁免{k}) {e['name']}: {'触发' if e['triggered'] else '未触发'} — {e['reason']}")
    n = lambda v: sum(1 for r in results if r["verdict"] == v)
    print(f"\n  统计: ✅通过 {n('PASS')} | ❌排除 {n('FAIL')} | ⚠️豁免 {n('EXEMPT')} | ⏭️跳过 {n('SKIP')} / 共 {len(results)}")
    return [r for r in results if r["verdict"] in ("PASS", "EXEMPT")]


def run_hard_rules(tickers=None, file=None, list_name=None, output=None):
    """--hard-rules 主入口，返回结果列表"""
    if file:
        tickers = read_tickers_file(file)
    elif list_name:
        tickers, src = fetch_list_tickers(list_name)
        print(f"[LIST] {list_name}: {len(tickers)} 只，来源: {src}")
    if not tickers:
        print("[ERR] 未指定股票: 用 --file <txt/json> 或 --list-name <内置list>")
        return []
    print(f"[RUN] 硬指标精筛 {len(tickers)} 只: {', '.join(tickers[:10])}{'...' if len(tickers) > 10 else ''}")

    results = []
    for i, t in enumerate(tickers, 1):
        print(f"  [{i}/{len(tickers)}] {t} ...", flush=True)
        results.append(check_hard_rules(t))

    survivors = print_hard_rules_table(results)

    if output:
        out = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "total": len(results),
               "survivors": survivors,
               "results": results}
        with open(output, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"\n[SAVED] 精筛结果已保存: {output}（幸存者 {len(survivors)} 只）")
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
    parser.add_argument("--hard-rules", action="store_true",
                        help="纯规则精筛模式: 7 硬指标 + 3 豁免（需配合 --file 或 --list-name）")
    parser.add_argument("--file", help="精筛输入: ticker 文件（txt 一行一个 / JSON 数组）")
    parser.add_argument("--list-name", help="内置 list (见 data/config/batch_lists.json)")
    args = parser.parse_args()

    if args.hard_rules:
        run_hard_rules(file=args.file, list_name=args.list_name, output=args.output)
    else:
        run_screen(market=args.market, top_n=args.top, output=args.output)
