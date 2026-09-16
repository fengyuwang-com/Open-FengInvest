#!/usr/bin/env python3
"""fengquant — L2b 因子z-score vs 同业. 连续性校正 (rank-0.5)/n. Output JSON.

Usage:
    python fengquant.py 0700.HK              # auto peers by sector
    python fengquant.py 0700.HK --peers BABA NTES PDD  # manual peers
    python fengquant.py 0700.HK --list        # show known stocks by sector

Dependencies: yfinance, scipy
"""

import json, os, sys
from datetime import datetime

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


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: fengquant.py TICKER [--peers P1 P2 ...|--group GROUP]"}, indent=2))
        sys.exit(1)

    ticker = sys.argv[1].upper()

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
