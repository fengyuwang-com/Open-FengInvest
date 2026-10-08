#!/usr/bin/env python3
"""fengquant — L2b 因子z-score vs 同业. 连续性校正 (rank-0.5)/n. Output JSON.

Usage:
    python fengquant.py 0700.HK              # auto peers by sector
    python fengquant.py 0700.HK --peers BABA NTES PDD  # manual peers
    python fengquant.py 0700.HK --list        # show known stocks by sector
    python fengquant.py 000660.KS             # KR：同行组取自 naver 同行业对照（一手源）
    python fengquant.py 000660.KS --peers 005930.KS 042700.KS

KR 路径（2026-09-16 新增，yfinance 对 KR 全域失效）：
    取数与同行组全部走 naver 一手源（m.stock.naver.com）：
      估值  per(TTM)/cnsPer(券商预期)/pbr/股息率      ← integration
      质量  ROE / 순이익률(净利率) / 매출액 YoY(年报实际) ← finance/annual（已剔除预期列）
      杠杆  부채비율(总负债/股东权益%)                 ← finance/annual
      动量  naver fchart 日K 6 个月收益
    同行组  industryCompareInfo（naver 自家同行业对照名单，含 sosok 市场码）
    ★ 绝不用其他市场公司冒充 KR 同行；同行不足 2 家或科目缺失 → 该因子 abstain 并写明原因。
    ★ 与 yfinance 语义的口径差异逐项写在输出 kr_sources 里（不冒充同义）。

Dependencies: yfinance, scipy（KR 路径不需要 yfinance）
"""

import json, os, re, sys
from datetime import datetime

# 代理策略（2026-09-16 修，依赖修复非填坑）：
# 默认行为保持不变——清空代理环境变量，避免历史上前端 Clash 干扰 yfinance。
# 当显式设了 FENG_HTTP_PROXY（如 clashproxy.py 报出的 http://127.0.0.1:7897）时，
# 改为把该地址写回 HTTP(S)_PROXY，供 Yahoo 直连被 429/网络阻断时使用。
# 与 AGENTS.md「clashproxy.py：yfinance 限流时主动切」的既有设计一致。
_FENG_PROXY = os.environ.get("FENG_HTTP_PROXY")
if _FENG_PROXY:
    os.environ["HTTP_PROXY"] = _FENG_PROXY
    os.environ["HTTPS_PROXY"] = _FENG_PROXY
    os.environ["http_proxy"] = _FENG_PROXY
    os.environ["https_proxy"] = _FENG_PROXY
else:
    os.environ.pop("HTTP_PROXY", None)
    os.environ.pop("HTTPS_PROXY", None)
    os.environ.pop("http_proxy", None)
    os.environ.pop("https_proxy", None)

import yfinance as yf
from scipy import stats


# Known stocks by sector (ticker -> name)
KNOWN_STOCKS = {
    # HK Internet
    "0700.HK": "Tencent",
    "9988.HK": "Alibaba",
    "9999.HK": "NetEase",
    "9618.HK": "JD",
    "3690.HK": "Meituan",
    "1024.HK": "Kuaishou",
    "1810.HK": "Xiaomi",
    # HK Pharma/TCM
    "0874.HK": "白云山",
    "3613.HK": "同仁堂国药",
    "3320.HK": "华润医药",
    "2877.HK": "神威药业",
    "0570.HK": "中国中药",
    "6896.HK": "金嗓子",
    "1681.HK": "康臣药业",
    "2186.HK": "绿叶制药",
    "1093.HK": "石药集团",
    "1177.HK": "中国生物制药",
    # US Internet
    "BABA": "Alibaba(US)",
    "NTES": "NetEase(US)",
    "JD": "JD(US)",
    "PDD": "PDD",
    "BIDU": "Baidu",
    "NIO": "NIO",
    "LI": "LiAuto",
    # US Tech
    "META": "Meta",
    "GOOGL": "Google",
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "AMZN": "Amazon",
    "NFLX": "Netflix",
    # Korea
    "005930.KS": "Samsung",
    "000660.KS": "SK Hynix",
    # China A
    "600519.SS": "茅台",
    "000858.SZ": "五粮液",
}

# Peer groups
PEER_GROUPS = {
    "hk_internet": ["0700.HK", "9988.HK", "9999.HK", "9618.HK"],
    "hk_pharma": ["0874.HK", "3613.HK", "3320.HK", "2877.HK", "0570.HK", "6896.HK", "1681.HK", "2186.HK"],
    "us_internet": ["BABA", "NTES", "PDD", "JD", "BIDU"],
    "all_internet": ["0700.HK", "BABA", "NTES", "PDD", "JD", "BIDU"],
    "us_bigtech": ["META", "GOOGL", "AAPL", "MSFT", "AMZN", "NFLX"],
}


def zscore_small(val: float, arr: list) -> float:
    """Continuity-corrected z-score: (rank-0.5)/n -> norm.ppf.

    Bounds pct to [0.5/n, (n-0.5)/n] so the max absolute z-score
    for n=3 is ~0.97, n=6 is ~1.38, n=10 is ~1.64 — preventing
    inflated z-scores from small peer groups.
    """
    n = len(arr)
    if n < 2:
        return 0.0
    rank = sum(1 for x in arr if x <= val)
    pct = (rank - 0.5) / n
    # Bound to feasible range for continuity correction
    lo = 0.5 / n
    hi = (n - 0.5) / n
    pct = max(lo, min(hi, pct))
    return round(float(stats.norm.ppf(pct)), 2)


def get_ticker_data(ticker: str) -> dict:
    """Fetch essential data for one ticker."""
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}

        # Get price for momentum
        hist = t.history(period="1y")
        # yfinance默认auto_adjust=True → Close为前复权价格
        c = hist["Close"] if not hist.empty else None
        mom_6m = float((c.iloc[-1] / c.iloc[-126] - 1) * 100) if c is not None and len(c) >= 126 else None

        return {
            "ticker": ticker,
            "name": info.get("shortName") or KNOWN_STOCKS.get(ticker, ticker),
            "pe": info.get("trailingPE"),
            "fwd_pe": info.get("forwardPE"),
            "pb": info.get("priceToBook"),
            "roe_pct": round(info.get("returnOnEquity", 0) * 100, 1) if info.get("returnOnEquity") else None,
            "profit_margin_pct": round(info.get("profitMargins", 0) * 100, 1) if info.get("profitMargins") else None,
            "revenue_growth_pct": round(info.get("revenueGrowth", 0) * 100, 1) if info.get("revenueGrowth") else None,
            "debt_to_equity": info.get("debtToEquity"),
            "market_cap": info.get("marketCap"),
            "momentum_6m_pct": mom_6m,
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


# ── KR 路径（2026-09-16）：yfinance 对 KR 全域失效，取数与同行组改走 naver 一手源 ──
KR_RE = re.compile(r"^(\d{6})\.(KS|KQ)$")


def is_kr_ticker(ticker: str) -> bool:
    return bool(KR_RE.match((ticker or "").upper().strip()))


def _kr_intl():
    """惰性 import 同目录 fengstockintl（KR 取数复用适配器，不另写一份取数代码）。"""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import fengstockintl
    return fengstockintl


def _kr_code(ticker: str):
    m = KR_RE.match((ticker or "").upper().strip())
    return m.group(1) if m else None


def kr_industry_peers(ticker: str) -> tuple:
    """KR 同行组：naver industryCompareInfo（一手同行业对照名单）。
    返回 (peers, source, reason)；拿不到 → ([], None, 原因)（绝不用别的市场公司凑数）。"""
    code = _kr_code(ticker)
    if not code:
        return [], None, "not_kr_ticker"
    try:
        q = _kr_intl().naver_quote(code)
    except Exception as e:  # noqa: BLE001
        return [], None, f"naver_quote_fail:{type(e).__name__}"
    if not q.get("ok"):
        return [], None, f"naver_quote_no_data:{q.get('note')}"
    peers, unknown = [], []
    for p in q.get("peers") or []:
        if p.get("code") == code:
            continue
        sfx = p.get("suffix")
        if not sfx:  # sosok 未识别 → 不猜市场，用目标后缀占位并标注
            unknown.append(p.get("code"))
            sfx = KR_RE.match(ticker.upper()).group(2)
        peers.append(f"{p['code']}.{sfx}")
    if not peers:
        return [], "naver industryCompareInfo", "industryCompareInfo 为空（naver 未给该股同业名单）"
    src = (f"naver industryCompareInfo（industry_code={q.get('industry_code')}，"
           f"{len(peers)} 家同业）")
    if unknown:
        src += f"；{len(unknown)} 家 sosok 未识别，市场后缀按目标市场占位: {','.join(unknown)}"
    return peers, src, None


def get_ticker_data_kr(ticker: str) -> dict:
    """KR 单票科目（naver 一手源）。键与 get_ticker_data 对齐；拿不到一律 None（→ abstain，不编数）。"""
    code = _kr_code(ticker)
    out = {"ticker": ticker, "name": KNOWN_STOCKS.get(ticker.upper(), ticker)}
    if not code:
        return {"ticker": ticker, "error": f"not a KR ticker: {ticker}"}
    try:
        fi = _kr_intl()
        q = fi.naver_quote(code)
        ann = fi.naver_finance_annual(code)
        series = fi.naver_fetch("KR", code)
    except Exception as e:  # noqa: BLE001
        return {"ticker": ticker, "error": f"naver fetch failed: {type(e).__name__}: {str(e)[:80]}"}

    rows, years = (ann.get("rows") or {}), (ann.get("years") or [])
    latest = years[-1] if years else None
    prev = years[-2] if len(years) >= 2 else None

    def _row(name, year):
        return (rows.get(name) or {}).get(year) if year else None

    rev_growth = None
    if latest and _row("revenue", prev) not in (None, 0):
        rev_growth = (_row("revenue", latest) / _row("revenue", prev) - 1) * 100

    mom_6m = None
    closes = [x["close"] for x in (series.get("data") or []) if x.get("close") is not None]
    if len(closes) >= 126:
        mom_6m = (closes[-1] / closes[-126] - 1) * 100

    out.update({
        "name": q.get("name_kr") or out["name"],
        "pe": q.get("per"),                      # PER（naver TTM 口径）
        "fwd_pe": q.get("cns_per"),              # 추정PER（券商一致预期）
        "pb": q.get("pbr"),
        "roe_pct": _row("roe_pct", latest),
        "profit_margin_pct": _row("net_margin_pct", latest),
        "revenue_growth_pct": round(rev_growth, 1) if rev_growth is not None else None,
        "debt_to_equity": _row("debt_ratio_pct", latest),
        "market_cap": q.get("market_cap_krw"),
        "momentum_6m_pct": round(mom_6m, 1) if mom_6m is not None else None,
    })
    if all(out.get(k) is None for k in ("pe", "fwd_pe", "pb", "roe_pct",
                                        "profit_margin_pct", "market_cap",
                                        "momentum_6m_pct")):
        return {"ticker": ticker, "error": "naver 取数全空（代码错误/接口变更/无数据）"}
    return out


KR_SOURCE_NOTES = {
    "pe": "naver integration PER（TTM 口径原值）",
    "fwd_pe": "naver integration 추정PER（券商一致预期）",
    "pb": "naver integration PBR",
    "roe_pct": "naver 年报 ROE（最近已披露财年，已剔除券商预期年份）",
    "profit_margin_pct": "naver 年报 순이익률（净利率，%）；注意 ≠ yfinance profitMargins 的同名同义口径",
    "revenue_growth_pct": "naver 年报 매출액 最近两个已披露财年 YoY（年度口径，非 yfinance 的季度/TTM 同比）",
    "debt_to_equity": "naver 年报 부채비율=总负债/股东权益%（口径宽于 yfinance debtToEquity 的有息负债/权益%）",
    "market_cap": "naver integration 시총（KRW）",
    "momentum_6m_pct": "naver fchart 日K 126 根收益（naver 复权口径未声明 → 该因子属趋势口径，"
                       "与 yfinance 的 Close 复权口径不保证可比；KR 内比，不跨市场比）",
    "peers": "naver industryCompareInfo（naver 自家同行业对照，非外部行业分类标准）；"
             "peer 市场后缀由 naver sosok 码推出（0=KOSPI/.KS，1=KOSDAQ/.KQ；"
             "sosok 未识别时按目标市场后缀占位并在 peer_group_source 标注）",
}


def compute_factors(target: dict, peers: list) -> dict:
    """Compute z-scores for target vs peer list."""
    # ── 因子文献追溯（见 knowledge/methodology/papers/02-value-quality.md、01-trend-timing.md）──
    # value_pe        价值(PE)：Liu-Stambaugh-Yuan 2019（A股价值因子首选 EP 而非 BM）+ Fama-French 1993（HML 价值因子）
    # value_fwd_pe    价值(FwdPE)：Campbell-Shiller 1988（估值比率可预测长期收益）
    # quality_roe     质量(ROE)：Novy-Marx 2013（盈利质量因子：毛利率/资产 预测力与 BM 相当）
    # profit_margin   利润率：Novy-Marx 2013（同上，盈利质量维度）
    # growth_revenue  收入增长：成长因子无直接标尺，与动量互补（Jegadeesh-Titman 1993）
    # leverage_de     杠杆(D/E)：杠杆风险（Fama-French 1993 负债因子；银行股注意 Gandhi-Lustig 2015 规模效应）
    # momentum_6m     动量(6m)：Jegadeesh-Titman 1993（3-12 月动量显著）——单独计算（价格数据），见下方
    factor_configs = [
        ("value_pe", "价值(PE)", lambda d: d.get("pe"), True),
        ("value_fwd_pe", "价值(FwdPE)", lambda d: d.get("fwd_pe"), True),
        ("quality_roe", "质量(ROE)", lambda d: d.get("roe_pct"), False),
        ("profit_margin", "利润率", lambda d: d.get("profit_margin_pct"), False),
        ("growth_revenue", "收入增长", lambda d: d.get("revenue_growth_pct"), False),
        ("leverage_de", "杠杆(D/E)", lambda d: d.get("debt_to_equity"), True),
    ]

    factors = []
    abstained = []  # ai-hedge-fund abstain 语义：数据缺失 = "没观点"，不算中性，也不计入共识
    for key, label, extract_fn, invert in factor_configs:
        t_val = extract_fn(target)
        if t_val is None:
            abstained.append({"factor": key, "label": label, "reason": "no_target_data"})
            continue

        p_vals = [extract_fn(p) for p in peers if extract_fn(p) is not None]
        if len(p_vals) < 2:
            abstained.append({"factor": key, "label": label, "reason": "insufficient_peers"})
            continue

        z = zscore_small(t_val, p_vals)
        if invert:
            z = -z

        signal = "BULL" if z > 0.5 else ("BEAR" if z < -0.5 else "NEUT")

        factors.append({
            "factor": key,
            "label": label,
            "target_value": t_val,
            "peer_values": p_vals,
            "peer_min": min(p_vals),
            "peer_max": max(p_vals),
            "peer_median": sorted(p_vals)[len(p_vals)//2],
            "z_score": z,
            "signal": signal,
        })

    # Momentum (separate - from price data, not cross-sectional)
    momentum = target.get("momentum_6m_pct")
    if momentum is not None:
        factors.append({
            "factor": "momentum_6m",
            "label": "动量(6m)",
            "target_value": momentum,
            "peer_values": [],
            "z_score": None,
            "signal": "BULL" if momentum > 10 else ("BEAR" if momentum < -10 else "NEUT"),
        })
    elif not abstained:
        abstained.append({"factor": "momentum_6m", "label": "动量(6m)", "reason": "no_target_data"})

    # 共识统计：abstain 分子分母都排除（"没有观点"不得冒充"观点：中性"）
    consensus = {
        "bull": sum(1 for f in factors if f["signal"] == "BULL"),
        "bear": sum(1 for f in factors if f["signal"] == "BEAR"),
        "neut": sum(1 for f in factors if f["signal"] == "NEUT"),
        "scored": len(factors),
        "abstained": len(abstained),
    }
    if abstained:
        consensus["note"] = (f"{len(abstained)} 个因子数据缺失 abstain，不计入共识"
                             "（ai-hedge-fund 语义：没观点≠中性）")

    return {
        "method": "continuity_corrected_(rank-0.5)/n",
        "target_name": target.get("name", target["ticker"]),
        "peer_count": len(peers),
        "peer_names": [p.get("name", p["ticker"]) for p in peers],
        "factors": factors,
        "abstained": abstained,
        "consensus": consensus,
    }


def main_kr(ticker: str):
    """KR 独立路径（.KS/.KQ）：同行组默认取 naver 同行业对照；非 KR 路径一行未动。"""
    if "--list" in sys.argv:
        kr_known = {k: v for k, v in KNOWN_STOCKS.items() if is_kr_ticker(k)}
        print(json.dumps({"market": "KR", "known_stocks": kr_known,
                          "peer_group_source": "naver industryCompareInfo（运行时自动取）"},
                         ensure_ascii=False, indent=2))
        return

    peers_tickers, peers_source, peers_reason = None, None, None
    if "--peers" in sys.argv:
        idx = sys.argv.index("--peers")
        peers_tickers = [t.upper() for t in sys.argv[idx+1:]]
        peers_source = "用户显式 --peers"
    elif "--group" in sys.argv:
        print(json.dumps({
            "error": "--group 不适用于 KR：既有 PEER_GROUPS 全是港股/美股公司，"
                     "拿它们给韩股当同业 = 用别的市场公司凑数（框架禁止）。",
            "hint": "KR 同行组默认自动取 naver 同行业对照；如需覆盖用 --peers 指定韩股代码",
            "available_groups": list(PEER_GROUPS.keys()),
        }, ensure_ascii=False, indent=2))
        sys.exit(1)
    else:
        peers_tickers, peers_source, peers_reason = kr_industry_peers(ticker)

    target_data = get_ticker_data_kr(ticker)
    if "error" in target_data:
        print(json.dumps({"error": f"Cannot fetch target {ticker}", "detail": target_data["error"],
                          "market": "KR", "source_attempted": "naver (m.stock.naver.com + fchart)"},
                         ensure_ascii=False, indent=2), file=sys.stderr)
        sys.exit(2)

    peer_data, errors = [], []
    for pt in peers_tickers or []:
        d = get_ticker_data_kr(pt) if is_kr_ticker(pt) else {
            "ticker": pt, "error": "非 KR 代码：KR 路径不拿其他市场公司当韩股同业"}
        (errors.append(d) if "error" in d else peer_data.append(d))

    factors = compute_factors(target_data, peer_data)

    result = {
        "ticker": ticker,
        "market": "KR",
        "fetched_at": datetime.now().isoformat(),
        "target": target_data,
        "peer_group": [p["ticker"] for p in peer_data],
        "peer_group_source": peers_source,
        "factor_analysis": factors,
        "kr_sources": KR_SOURCE_NOTES,
    }
    if errors:
        result["fetch_errors"] = errors
    result["data_health"] = {
        "peers_requested": len(peers_tickers or []),
        "peers_fetched": len(peer_data),
        "peers_failed": [e.get("ticker") for e in errors],
    }
    # 有声降级：同行组拿不到 / 同行不足 → 明说原因，不得静默只留一张空因子表
    if peers_reason:
        result["abstain_note"] = (f"KR 同行组不可得（{peers_reason}）→ 横截面因子（价值/质量/成长/杠杆）"
                                  f"全部 abstain，仅动量因子可单独看。可用 --peers 手动指定韩股同业。")
        result["data_health"]["peers_source_reason"] = peers_reason
    elif len(peer_data) < 2:
        result["abstain_note"] = (f"KR 同行仅取到 {len(peer_data)} 家（需 ≥2 家才算 z-score）："
                                  f"横截面因子 abstain，原因见 data_health.peers_failed。")
    n_abstain = len(factors["abstained"])
    if n_abstain:
        result["data_health"]["factors_abstained"] = n_abstain
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: fengquant.py TICKER [--peers P1 P2 ...|--group GROUP]"}, indent=2))
        sys.exit(1)

    ticker = sys.argv[1].upper()

    # KR 独立路径（2026-09-16）：命中 .KS/.KQ 才进，下方非 KR 逻辑逐字节不变
    if is_kr_ticker(ticker):
        return main_kr(ticker)

    # Determine peer list
    peers_tickers = None
    if "--peers" in sys.argv:
        idx = sys.argv.index("--peers")
        peers_tickers = sys.argv[idx+1:]
    elif "--group" in sys.argv:
        idx = sys.argv.index("--group")
        group = sys.argv[idx+1]
        peers_tickers = PEER_GROUPS.get(group)
        if not peers_tickers:
            print(json.dumps({"error": f"Unknown group '{group}'. Available: {list(PEER_GROUPS.keys())}"}, indent=2))
            sys.exit(1)
    elif "--list" in sys.argv:
        print(json.dumps({"known_stocks": KNOWN_STOCKS, "peer_groups": {k: len(v) for k, v in PEER_GROUPS.items()}}, indent=2))
        sys.exit(0)
    else:
        # Auto-detect: search all groups for this ticker
        for group_name, g_tickers in PEER_GROUPS.items():
            if ticker in g_tickers:
                peers_tickers = [t for t in g_tickers if t != ticker]
                break
        if not peers_tickers:
            available = ", ".join(f"{k}({len(v)})" for k, v in PEER_GROUPS.items())
            print(json.dumps({
                "error": f"Ticker {ticker} not found in any peer group. Use --peers or --group.",
                "available_groups": available,
                "hint": f"python fengquant.py {ticker} --peers TICKER1 TICKER2 TICKER3"
            }, indent=2))
            sys.exit(1)

    # Fetch data
    target_data = get_ticker_data(ticker)
    peer_data = []
    errors = []
    for pt in peers_tickers:
        d = get_ticker_data(pt)
        if "error" in d:
            errors.append(d)
        else:
            peer_data.append(d)

    if "error" in target_data:
        print(json.dumps({"error": f"Cannot fetch target {ticker}", "detail": target_data["error"]}, indent=2))
        sys.exit(1)

    # 有声失败（2026-09-13）：yfinance 被限流/退市时不抛异常而是返回空壳（info={}、hist 空）——
    # target 全部关键因子为 null 即数据获取失败，显式报错退出，禁止把空表当好数据输出。
    _core_keys = ("pe", "fwd_pe", "pb", "market_cap", "momentum_6m_pct")
    if all(target_data.get(k) is None for k in _core_keys):
        print(json.dumps({
            "error": f"Target {ticker} 取数全空（yf 限流/退市/代码错误），拒绝输出空因子表",
            "target_raw": target_data,
            "peers_failed": [e.get("ticker") for e in errors],
        }, indent=2), file=sys.stderr)
        sys.exit(2)

    # Compute factors
    factors = compute_factors(target_data, peer_data)

    result = {
        "ticker": ticker,
        "fetched_at": datetime.now().isoformat(),
        "target": target_data,
        "peer_group": [p["ticker"] for p in peer_data],
        "factor_analysis": factors,
    }

    if errors:
        result["fetch_errors"] = errors

    # 数据健康度：z-score 只在幸存 peer 上算，分母与失败名单必须显式（无声降级治理 B 线）
    result["data_health"] = {
        "peers_requested": len(peers_tickers),
        "peers_fetched": len(peer_data),
        "peers_failed": [e.get("ticker") for e in errors],
    }

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
