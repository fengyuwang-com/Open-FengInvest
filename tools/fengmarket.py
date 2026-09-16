#!/usr/bin/env python3
"""fengmarket — 跨市场"人性温度计"仪表盘。

每天自动采集 SPY/HSI/CSI300/VIX 数据,
并爬取公开网站的真实第三方数据（Buffett 指标、Fear & Greed Index）,
保存快照。能爬的真实数据不自算。

Usage:
    python fengmarket.py collect          # 采集+爬取+计算+保存
    python fengmarket.py dashboard        # 人类可读报告
    python fengmarket.py history          # 滚动趋势 (N天)

Dependencies: yfinance, numpy, scipy, pandas, requests
"""

import json, os, sys, glob, math
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any
import statistics

os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

import yfinance as yf
import numpy as np
from scipy import stats as sp_stats
import requests
import re

# ── paths ────────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MARKET_DIR = PROJECT_ROOT / "research" / "market"
DAILY_DIR = MARKET_DIR / "daily"
LATEST_PATH = MARKET_DIR / "latest.json"
HISTORY_PATH = MARKET_DIR / "history.jsonl"

MARKET_DIR.mkdir(parents=True, exist_ok=True)
DAILY_DIR.mkdir(parents=True, exist_ok=True)

# ── helpers ──────────────────────────────────────────────────────────

def _clean(obj):
    """Recursively replace NaN/Infinity with None for JSON-safe output."""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj

def _save_json(path, data):
    """Save JSON with NaN→null handling. Always UTF-8."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_clean(data), f, indent=2, default=str, ensure_ascii=False)

def _percentile(val: float, series: list) -> float:
    """What percentile is val within series? 0-100."""
    if not series:
        return 50.0
    return float(round(sp_stats.percentileofscore(series, val), 1))

def _pct_pos(val, high, low):
    """Position in range as percentage."""
    return round((val - low) / (high - low) * 100, 1) if high > low else 50.0

def _zscore(val: float, series: list) -> float:
    """Z-score of val within series."""
    if len(series) < 2:
        return 0.0
    arr = np.array(series)
    return float(round((val - arr.mean()) / (arr.std() + 1e-8), 2))


# ── data fetchers ────────────────────────────────────────────────────

def _get_hist(ticker: str, period="max") -> dict:
    """Fetch price history and compute stats."""
    t = yf.Ticker(ticker)
    hist = t.history(period=period)
    if hist.empty:
        return {"error": f"No data for {ticker}"}
    c = hist["Close"]
    price_raw = float(c.iloc[-1])
    price = None if math.isnan(price_raw) else price_raw
    if price is None:
        # Try last non-NaN close
        valid = c.dropna()
        if not valid.empty:
            price = float(valid.iloc[-1])
    hi = float(hist["High"].max())
    lo = float(hist["Low"].min())
    # 10-year price percentile
    c10 = c.tail(2520)  # ~10 years of trading days
    if len(c10) < 2:
        c10 = c
    c10_clean = c10.dropna()
    pct_10y = _percentile(price, list(c10_clean)) if price is not None and len(c10_clean) > 2 else None
    # MAs
    ma50 = float(c.iloc[-50:].mean()) if len(c) >= 50 else None
    ma200 = float(c.iloc[-200:].mean()) if len(c) >= 200 else None
    # Volume
    v = hist["Volume"]
    vol5 = float(v.iloc[-5:].mean()) if len(v) >= 5 else None
    vol20 = float(v.iloc[-20:].mean()) if len(v) >= 20 else None
    vol_ratio = round(vol5 / vol20, 2) if vol5 and vol20 else None
    return {
        "ticker": ticker,
        "price": price,
        "ma50": ma50,
        "ma200": ma200,
        "high_all": hi,
        "low_all": lo,
        "pct_10y": pct_10y,
        "ma50_above_ma200": ma50 > ma200 if ma50 and ma200 else None,
        "vol_5d": vol5,
        "vol_20d": vol20,
        "vol_ratio_5_20": vol_ratio,
        "data_points": len(c),
    }


def _get_hist_with_pe(ticker: str) -> dict:
    """Price history + PE from info."""
    t = yf.Ticker(ticker)
    info = t.info or {}
    hist = t.history(period="max")
    if hist.empty:
        return {"error": f"No data for {ticker}"}
    c = hist["Close"]
    price_raw = float(c.iloc[-1])
    price = None if math.isnan(price_raw) else price_raw
    if price is None:
        valid = c.dropna()
        if not valid.empty:
            price = float(valid.iloc[-1])
    pe = info.get("trailingPE")
    if isinstance(pe, float) and math.isnan(pe):
        pe = None
    # 10-yr price percentile
    c10 = c.tail(2520)
    c10_clean = c10.dropna()
    pct_10y = _percentile(price, list(c10_clean)) if price is not None and len(c10_clean) > 2 else None
    # Collect historical PE (approximate via price changes if no historical PE available)
    return {
        "ticker": ticker,
        "name": info.get("shortName", ticker),
        "price": price,
        "pe": pe,
        "pct_10y": pct_10y,
        "ma50": float(c.iloc[-50:].mean()) if len(c) >= 50 else None,
        "ma200": float(c.iloc[-200:].mean()) if len(c) >= 200 else None,
        "data_points": len(c),
    }


def _get_vix() -> dict:
    """VIX data."""
    t = yf.Ticker("^VIX")
    info = t.info or {}
    hist = t.history(period="max")
    if hist.empty:
        return {"error": "No VIX data"}
    c = hist["Close"]
    price_raw = float(c.iloc[-1])
    price = None if math.isnan(price_raw) else price_raw
    if price is None:
        valid = c.dropna()
        if not valid.empty:
            price = float(valid.iloc[-1])
    # 10-yr percentile
    c10 = c.tail(2520)
    c10_clean = c10.dropna()
    pct_10y = _percentile(price, list(c10_clean)) if price is not None and len(c10_clean) > 2 else None
    # VIX zones
    if price is None:
        zone = "unknown"
    else:
        zone = "extreme_fear" if price > 30 else ("fear" if price > 20 else
               ("neutral" if price > 15 else "complacent"))
    return {
        "vix": price,
        "pct_10y": pct_10y,
        "zone": zone,
        "ma50": float(c.iloc[-50:].mean()) if len(c) >= 50 else None,
    }


def _scrape_shiller_pe() -> dict:
    """Scrape Shiller CAPE from multpl.com."""
    try:
        r = requests.get("https://www.multpl.com/shiller-pe", timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        if r.status_code != 200:
            raise IOError(f"HTTP {r.status_code}")
        # Current value is in meta description: "Current Shiller PE Ratio is 42.18"
        m = re.search(r'Current Shiller PE Ratio is ([\d.]+)', r.text)
        if not m:
            # Fallback: search for any big number near Shiller PE
            m = re.search(r'Shiller PE[^<>]*?([\d.]+)', r.text)
        if not m:
            raise ValueError("Could not find Shiller PE value")
        cape = float(m.group(1))
        # Extract stats from #stats table (min/max/mean/median)
        mean = None; median = None; lo = None; hi = None
        m_mean = re.search(r'Mean:\s*</td>[^<]*<td[^>]*>\s*([\d.]+)', r.text, re.DOTALL)
        m_med = re.search(r'Median:\s*</td>[^<]*<td[^>]*>\s*([\d.]+)', r.text, re.DOTALL)
        m_min = re.search(r'Min:\s*</td>[^<]*<td[^>]*>\s*([\d.]+)', r.text, re.DOTALL)
        m_max = re.search(r'Max:\s*</td>[^<]*<td[^>]*>\s*([\d.]+)', r.text, re.DOTALL)
        if m_mean: mean = float(m_mean.group(1))
        if m_med: median = float(m_med.group(1))
        if m_min: lo = float(m_min.group(1))
        if m_max: hi = float(m_max.group(1))
        return {
            "available": True,
            "cape": cape,
            "mean": mean,
            "median": median,
            "min": lo,
            "max": hi,
            "source": "multpl.com",
            "note": f"Shiller CAPE={cape}, mean={mean}, median={median}",
        }
    except Exception as e:
        return {"available": False, "note": f"Scrape failed: {e}"}


def _get_index_pe(ticker: str) -> dict:
    """Get current PE ratio for an index via yfinance info."""
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        pe = info.get("trailingPE")
        fpe = info.get("forwardPE")
        name = info.get("shortName", ticker)
        return {
            "available": pe is not None or fpe is not None,
            "trailing_pe": pe,
            "forward_pe": fpe,
            "name": name,
        }
    except Exception as e:
        return {"available": False, "note": str(e)}


# ── scrapers (real data from public websites — no calculation) ────────

def _scrape_buffett() -> dict:
    """Scrape real Buffett Indicator from thebuffettindicator.com."""
    try:
        r = requests.get("https://thebuffettindicator.com/", timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        if r.status_code != 200:
            raise IOError(f"HTTP {r.status_code}")

        # Extract: "Buffett Indicator: 214.08%"
        m = re.search(r'Buffett Indicator:\s*([\d.]+)%', r.text)
        if not m:
            raise ValueError("Could not find Buffett Indicator value in page")

        ratio = float(m.group(1))
        market_cap_t = None
        gdp_t = None

        # Also try to extract market cap and GDP
        m2 = re.search(r'total.*?market.*?(?:cap|value).*?\$?([\d,.]+)\s*(?:trillion|billion)', r.text, re.I)
        m3 = re.search(r'GDP.*?\$?([\d,.]+)\s*(?:trillion|billion)', r.text, re.I)

        zone = "extreme_overvalued" if ratio > 120 else (
                "overvalued" if ratio > 100 else (
                "fair" if ratio > 80 else "undervalued"))

        return {
            "available": True,
            "ratio_pct": round(ratio, 1),
            "estimated_market_cap_t": market_cap_t,
            "gdp_t": gdp_t,
            "zone": zone,
            "source": "thebuffettindicator.com",
            "note": "Scraped from thebuffettindicator.com",
        }
    except Exception as e:
        return {"available": False, "note": f"Scrape failed: {e}"}


def _scrape_fear_greed() -> dict:
    """Scrape Fear & Greed Index from cfgi.io as external benchmark."""
    try:
        r = requests.get("https://cfgi.io/stock-fear-and-greed-index/", timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
        if r.status_code != 200:
            raise IOError(f"HTTP {r.status_code}")

        # Extract score: "63 / 100" in title or body
        m = re.search(r'(?:Index\s*Today:?\s*|score["\':\s]*)(\d+)\s*/?\s*100', r.text)
        if not m:
            # Try any "NN / 100" near Greed/Fear text
            m = re.search(r'(\d+)\s*/\s*100[^<]*', r.text)
        if not m:
            raise ValueError("Could not find Fear & Greed score")

        score = int(m.group(1))

        # Determine label
        if score >= 75: label = "extreme_greed"
        elif score >= 55: label = "greed"
        elif score >= 45: label = "neutral"
        elif score >= 25: label = "fear"
        else: label = "extreme_fear"

        return {
            "available": True,
            "score": score,
            "label": label,
            "source": "cfgi.io",
            "note": f"CFGI Fear & Greed Index: {score}/100 ({label})",
        }
    except Exception as e:
        return {"available": False, "note": f"Scrape failed: {e}"}


def _get_momentum(ticker: str) -> dict:
    """Short-term momentum (1m return)."""
    t = yf.Ticker(ticker)
    hist = t.history(period="2mo")
    if hist.empty:
        return {"error": "No data"}
    c = hist["Close"]
    m1 = float((c.iloc[-1] / c.iloc[-22] - 1) * 100) if len(c) >= 22 else None
    return {"return_1m_pct": m1}


# ── temperature calculation ──────────────────────────────────────────

def _norm(val: float, lo: float, hi: float) -> float:
    """Normalize val between lo-hi to 0-1, clamped."""
    if hi <= lo: return 0.5
    return max(0.0, min(1.0, (val - lo) / (hi - lo)))


def compute_temperature(data: dict) -> dict:
    """6-component greed-fear thermometer (0=extreme fear, 100=extreme greed)."""
    spy = data.get("spy", {})
    vix_d = data.get("vix", {})
    buffett = data.get("buffett", {})
    hsi = data.get("hsi", {})
    csi300 = data.get("csi300", {})
    spy_hist = data.get("spy_hist", {})

    components = {}
    total_weight = 0

    # 1. VIX reverse (25%): low VIX = greed
    vix_v = vix_d.get("vix", 20)
    vi = 1.0 - _norm(vix_v, 10, 40)  # VIX 10→greed, 40→fear
    components["vix_reverse"] = {
        "score": round(vi * 100, 1),
        "weight_pct": 25,
        "value": vix_v,
        "note": f"VIX={vix_v}: low=greed",
    }
    total_weight += 25

    # 2. SPY vs MA200 (15%): how far price is above/below 200-day MA
    # Measures short-to-medium-term extension. Above MA200 = normal in bull,
    # but extreme distances indicate euphoria. More responsive than 10yr %ile.
    spy_price = spy_hist.get("price", 0)
    spy_ma200 = spy_hist.get("ma200")
    if spy_price and spy_ma200 and spy_ma200 > 0:
        spy_ma200_dist = round((spy_price / spy_ma200 - 1) * 100, 1)
        # -20% → score 0 (fear), +20% → score 100 (greed), 0% → score 50
        sv = _norm(spy_ma200_dist, -20, 20)
    else:
        spy_ma200_dist = None
        sv = 0.5
    components["spy_vs_ma200"] = {
        "score": round(sv * 100, 1),
        "weight_pct": 15,
        "value": spy_ma200_dist,
        "note": f"SPY vs MA200: {spy_ma200_dist}%",
    }
    total_weight += 15

    # 3. Buffett indicator (10%): high = greed
    # Scraped from thebuffettindicator.com — real data, not computed.
    # Normalized against modern range (60-250) where 250+ is extreme.
    if buffett.get("available"):
        br = buffett.get("ratio_pct", 100)
        bv = _norm(br, 60, 250)
        components["buffett_indicator"] = {
            "score": round(bv * 100, 1),
            "weight_pct": 10,
            "value": br,
            "note": f"TOTALSA/GDP={br}% (src: thebuffettindicator.com)",
        }
        total_weight += 10
    else:
        # Redistribute to SPY valuation + VIX
        components["buffett_indicator"] = {
            "score": None, "weight_pct": 0,
            "note": buffett.get("note", "unavailable"),
        }

    # 4. Cross-market divergence (15%): SPY outperforming HSI = US greed
    spy_pct_val = spy.get("pct_10y", 50)
    hsi_pct = hsi.get("pct_10y", 50)
    divergence = spy_pct_val - hsi_pct  # positive = US much stronger
    cd = 0.5 + divergence / 200  # ±100% divergence → 0.0 or 1.0
    cd = max(0.0, min(1.0, cd))
    components["cross_market_divergence"] = {
        "score": round(cd * 100, 1),
        "weight_pct": 15,
        "value": round(divergence, 1),
        "note": f"SPY({spy_pct_val}%) - HSI({hsi_pct}%) divergence",
    }
    total_weight += 15

    # 5. Volume anomaly (10%): extreme volume (either direction) = emotional
    # Vol ratio near 1.0 = normal. Low volume = apathy/consolidation, not greed.
    vol_ratio = spy_hist.get("vol_ratio_5_20", 1.0)
    vol_dev = min(abs(vol_ratio - 1.0), 0.5) / 0.5  # 0-1, distance from 1.0
    # Map: near 1.0 → 50 (neutral), far → 100 (emotional but ambiguous)
    vr = 50 + vol_dev * 50
    components["volume_anomaly"] = {
        "score": round(vr, 1),
        "weight_pct": 10,
        "value": vol_ratio,
        "note": f"Volume ratio (5d/20d)={vol_ratio}: near 1=neutral",
    }
    total_weight += 10

    # 6. Short-term momentum (25%): strong up = greed
    mom = data.get("momentum", {}).get("return_1m_pct", 0)
    stm = _norm(mom, -10, 10) if mom is not None else 0.5
    components["short_term_momentum"] = {
        "score": round(stm * 100, 1),
        "weight_pct": 25,
        "value": mom,
        "note": f"SPY 1m return={mom}%",
    }
    total_weight += 25

    # Weighted composite
    weighted = 0
    actual_weight = 0
    for k, c in components.items():
        w = c["weight_pct"]
        s = c["score"]
        if s is not None:
            weighted += s * w
            actual_weight += w
    composite = round(weighted / (actual_weight or 1), 1)
    # Ensure 0-100
    composite = max(0.0, min(100.0, composite))

    # Label
    if composite >= 80: label = "extreme_greed"
    elif composite >= 65: label = "greed"
    elif composite >= 35: label = "neutral"
    elif composite >= 20: label = "fear"
    else: label = "extreme_fear"

    return {
        "composite": composite,
        "label": label,
        "components": components,
    }


def compute_temperatures_by_country(data: dict) -> dict:
    """Per-country temperature composites (US/HK/CN)."""

    def _safe(val, default=50):
        """Convert NaN/None to default."""
        if val is None: return default
        if isinstance(val, float) and math.isnan(val): return default
        return val

    spy = data.get("spy", {})
    spy_hist = data.get("spy_hist", {})
    vix_d = data.get("vix", {})
    buffett = data.get("buffett", {})
    hsi = data.get("hsi", {})
    csi300 = data.get("csi300", {})
    shiller = data.get("shiller", {})
    fg = data.get("fear_greed", {})

    def _composite(name: str, comps: list) -> dict:
        """Build weighted composite from component dicts."""
        weighted = 0.0
        total_w = 0.0
        for c in comps:
            if c["score"] is not None:
                weighted += c["score"] * c["weight"]
                total_w += c["weight"]
        score = round(weighted / (total_w or 1), 1)
        score = max(0.0, min(100.0, score))
        if score >= 80: label = "extreme_greed"
        elif score >= 65: label = "greed"
        elif score >= 35: label = "neutral"
        elif score >= 20: label = "fear"
        else: label = "extreme_fear"
        comp_map = {c["id"]: {"score": c["score"], "weight_pct": c["weight"],
                              "value": c.get("value"), "note": c.get("note", "")}
                     for c in comps}
        return {"composite": score, "label": label, "components": comp_map}

    vix_v = vix_d.get("vix", 20)

    # ── US Temperature ──
    # Components: VIX reverse, SPY vs MA200, Buffett, SPY momentum, Shiller CAPE
    vi = 1.0 - _norm(_safe(vix_d.get("vix"), 20), 10, 40)
    spy_price = _safe(spy_hist.get("price"), 0)
    spy_ma200 = spy_hist.get("ma200")
    if spy_price and spy_ma200 and spy_ma200 > 0:
        spy_ma200_dist = round((spy_price / spy_ma200 - 1) * 100, 1)
        spy_ma200_score = _norm(spy_ma200_dist, -20, 20) * 100
    else:
        spy_ma200_dist, spy_ma200_score = None, 50
    # Buffett (high ratio = greed)
    if buffett.get("available"):
        buffett_score = _norm(buffett["ratio_pct"], 60, 250) * 100
    else:
        buffett_score = 50
    # SPY 1m momentum
    mom = data.get("momentum", {}).get("return_1m_pct", 0)
    mom_score = _norm(mom, -10, 10) * 100 if mom is not None else 50
    # Shiller CAPE
    if shiller.get("available"):
        shiller_score = _norm(shiller["cape"], 10, 45) * 100
    else:
        shiller_score = None

    us_comps = [
        {"id": "vix_reverse", "score": round(vi * 100, 1), "weight": 20,
         "value": vix_v, "note": f"VIX={vix_v}"},
        {"id": "spy_vs_ma200", "score": round(spy_ma200_score, 1), "weight": 15,
         "value": spy_ma200_dist, "note": f"SPY vs MA200={spy_ma200_dist}%"},
        {"id": "buffett_indicator", "score": round(buffett_score, 1), "weight": 20,
         "value": buffett.get("ratio_pct"), "note": f"Buffett={buffett.get('ratio_pct')}%"},
        {"id": "short_term_momentum", "score": round(mom_score, 1), "weight": 15,
         "value": mom, "note": f"SPY 1m={mom}%"},
        {"id": "shiller_cape", "score": round(shiller_score, 1) if shiller_score is not None else None,
         "weight": 15, "value": shiller.get("cape"), "note": f"Shiller CAPE={shiller.get('cape')}"},
    ]

    # ── HK Temperature ──
    # Components: HSI pct_10y reverse, HSI vs MA200, HSI momentum, cross-market
    hsi_pct = _safe(hsi.get("pct_10y"), 50)
    hsi_price = _safe(hsi.get("price"), 0)
    hsi_ma200 = hsi.get("ma200")
    if hsi_price and hsi_ma200 and hsi_ma200 > 0:
        hsi_ma200_dist = round((hsi_price / hsi_ma200 - 1) * 100, 1)
        hsi_ma200_score = _norm(hsi_ma200_dist, -20, 20) * 100
    else:
        hsi_ma200_dist, hsi_ma200_score = None, 50
    # HSI percentile (low percentile = fear territory, high = greed)
    # Price percentile: low means cheap → fear, high means expensive → greed
    hsi_pct_score = hsi_pct  # already 0-100, higher = more expensive
    # Cross-market (SPY vs HSI divergence)
    spy_pct = _safe(spy.get("pct_10y"), 50)
    divergence = spy_pct - hsi_pct
    div_score = (0.5 + divergence / 200) * 100

    hk_comps = [
        {"id": "hsi_percentile", "score": round(hsi_pct_score, 1), "weight": 30,
         "value": hsi_pct, "note": f"HSI 10yr={hsi_pct}%"},
        {"id": "hsi_vs_ma200", "score": round(hsi_ma200_score, 1), "weight": 20,
         "value": hsi_ma200_dist, "note": f"HSI vs MA200={hsi_ma200_dist}%"},
        {"id": "cross_market_divergence", "score": round(div_score, 1), "weight": 20,
         "value": round(divergence, 1), "note": f"SPY({spy_pct}%) - HSI({hsi_pct}%)"},
        {"id": "vix_spillover", "score": round(vi * 100, 1), "weight": 15,
         "value": vix_v, "note": f"VIX={vix_v} spillover"},
        {"id": "short_term_momentum", "score": round(mom_score, 1), "weight": 15,
         "value": mom, "note": f"SPY 1m={mom}% (proxy)"},
    ]

    # ── CN Temperature ──
    # Components: CSI300 pct_10y reverse, CSI300 vs MA200, CSI300 momentum, cross-market
    cn_pct = _safe(csi300.get("pct_10y"), 50)
    cn_price = _safe(csi300.get("price"), 0)
    cn_ma200 = csi300.get("ma200")
    if cn_price and cn_ma200 and cn_ma200 > 0:
        cn_ma200_dist = round((cn_price / cn_ma200 - 1) * 100, 1)
        cn_ma200_score = _norm(cn_ma200_dist, -20, 20) * 100
    else:
        cn_ma200_dist, cn_ma200_score = None, 50
    cn_pct_score = cn_pct

    cn_comps = [
        {"id": "csi300_percentile", "score": round(cn_pct_score, 1), "weight": 30,
         "value": cn_pct, "note": f"CSI300 10yr={cn_pct}%"},
        {"id": "csi300_vs_ma200", "score": round(cn_ma200_score, 1), "weight": 20,
         "value": cn_ma200_dist, "note": f"CSI300 vs MA200={cn_ma200_dist}%"},
        {"id": "cross_market_divergence", "score": round(div_score, 1), "weight": 20,
         "value": round(divergence, 1), "note": f"SPY({spy_pct}%) - CSI300({cn_pct}%)"},
        {"id": "vix_spillover", "score": round(vi * 100, 1), "weight": 15,
         "value": vix_v, "note": f"VIX={vix_v} spillover"},
        {"id": "short_term_momentum", "score": round(mom_score, 1), "weight": 15,
         "value": mom, "note": f"SPY 1m={mom}% (proxy)"},
    ]

    us_temp = _composite("us", us_comps)
    hk_temp = _composite("hk", hk_comps)
    cn_temp = _composite("cn", cn_comps)

    # Global = simple average of 3
    global_composite = round((us_temp["composite"] + hk_temp["composite"] + cn_temp["composite"]) / 3, 1)
    if global_composite >= 80: global_label = "extreme_greed"
    elif global_composite >= 65: global_label = "greed"
    elif global_composite >= 35: global_label = "neutral"
    elif global_composite >= 20: global_label = "fear"
    else: global_label = "extreme_fear"

    return {
        "global": {"composite": global_composite, "label": global_label},
        "us": us_temp,
        "hk": hk_temp,
        "cn": cn_temp,
    }


# ── behavior rules ───────────────────────────────────────────────────

def generate_behavior_insights(data: dict, temp: dict) -> list:
    """Rule-based behavior analysis. No LLM, pure if-then."""
    insights = []
    score = temp["composite"]
    label = temp["label"]
    spy_pct = data.get("spy", {}).get("pct_10y", 50)
    vix_v = data.get("vix", {}).get("vix", 20)
    vix_pct = data.get("vix", {}).get("pct_10y", 50)
    buffett = data.get("buffett", {})
    div = temp["components"].get("cross_market_divergence", {}).get("value", 0)
    spy_pe = data.get("spy", {}).get("pe")
    hsi_pct = data.get("hsi", {}).get("pct_10y", 50)
    spy_ma = data.get("spy_hist", {})
    ma_ok = spy_ma.get("ma50_above_ma200")

    rules = [
        # Extreme greed
        (score >= 80 and buffett.get("available") and (buffett.get("ratio_pct", 0) or 0) > 100,
         "greed",
         "估值泡沫化驱动 — Buffett指标>100%, 市场在price in完美的未来"),

        (score >= 80 and vix_v < 15 and spy_pct > 70,
         "greed",
         "过度自满 — VIX<15 + 估值高位, 市场无视风险"),

        # Divergence
        (div > 40 and hsi_pct < 30,
         "divergence",
         f"本土偏好极端化 — SPY在{spy_pct}%分位 vs 港股在{hsi_pct}%分位, 资金集中于美股"),

        (div < -30 and hsi_pct > 50,
         "divergence",
         "价值洼地信号 — 港股强于美股, 资金可能在轮动"),

        # Extreme fear
        (score <= 20 and vix_v > 30,
         "fear",
         "恐慌驱动 — VIX>30, 市场在情绪性抛售"),

        (score <= 20 and spy_pct < 20,
         "fear",
         "超卖区域 — SPY处于10年低位, 可能是逆向买入机会"),

        # Trend health
        (ma_ok is False and score > 50,
         "conflict",
         "价格趋势↓但情绪偏贪 — 价格和情绪背离, 可能需要时间消化"),

        (ma_ok is True and score < 30,
         "conflict",
         "价格趋势↑但情绪偏恐 — 可能是短期调整, 不是趋势反转"),

        # VIX specific
        (vix_pct < 20 and spy_pct > 70,
         "warning",
         f"VIX处于{vix_pct}%分位(极低) + SPY高位 — 经典的'暴风雨前的平静'"),

        # Valuation specific
        (spy_pe and spy_pe > 25 and score > 65,
         "valuation",
         f"SPY PE={spy_pe}x — 估值偏高, 未来预期回报率降低"),

        (spy_pe and spy_pe < 16 and score < 40,
         "valuation",
         f"SPY PE={spy_pe}x — 估值偏低, 长期配置价值显现"),
    ]

    for condition, category, message in rules:
        if condition:
            insights.append({
                "category": category,
                "message": message,
            })

    # Always add the baseline reading
    baseline = {
        "reading": label,
        "score": score,
        "summary": {
            "extreme_greed": "全市场情绪极度贪婪。谨慎，减少买入。",
            "greed": "市场偏贪婪。新仓位需更严格的安全边际。",
            "neutral": "市场情绪中性。按框架正常分析。",
            "fear": "市场偏恐惧。关注是否错杀好公司。",
            "extreme_fear": "市场极度恐惧。可能是最佳买入窗口。",
        }.get(label, "市场情绪中性。"),
    }

    return {
        "baseline": baseline,
        "alerts": insights,
    }


# ── collect ──────────────────────────────────────────────────────────

def collect() -> dict:
    """Full collect + scrape + compute + save."""
    today_str = date.today().isoformat()

    # 1. yfinance market data (real, not computed)
    spy_pe = _get_hist_with_pe("SPY")
    spy_ma = _get_hist("SPY")
    hsi = _get_hist("^HSI")
    csi300 = _get_hist("000300.SS")
    vix = _get_vix()
    momentum = _get_momentum("SPY")

    # 2. Scrape real third-party data (not computed)
    buffett = _scrape_buffett()
    fear_greed = _scrape_fear_greed()
    shiller = _scrape_shiller_pe()

    # 3. Index PE ratios
    hsi_pe = _get_index_pe("^HSI")
    csi300_pe = _get_index_pe("000300.SS")

    raw = {
        "spy": spy_pe,
        "spy_hist": spy_ma,
        "hsi": hsi,
        "csi300": csi300,
        "vix": vix,
        "buffett": buffett,
        "shiller": shiller,
        "fear_greed": fear_greed,
        "momentum": momentum,
        "index_pe": {"hsi": hsi_pe, "csi300": csi300_pe},
    }

    # 有声失败（2026-09-13）：记录每个数据组件是否真拿到了。compute_temperature 对缺数
    # 成分会取中性值（VIX 缺=20、SPY 缺=0.5），温度照样出——但快照必须带上"哪些成分是
    # 造出来的默认值"的真相，供 web 页/体检探针/人工判断温度可信度。
    def _comp_ok(v):
        if isinstance(v, dict):
            if "error" in v:
                return False
            if "available" in v:
                return bool(v["available"])
        return bool(v)
    data_health = {k: ("ok" if _comp_ok(v) else "FAILED")
                   for k, v in raw.items() if k != "index_pe"}
    data_health["index_pe_hsi"] = "ok" if _comp_ok(hsi_pe) else "FAILED"
    data_health["index_pe_csi300"] = "ok" if _comp_ok(csi300_pe) else "FAILED"

    # 4. Temperature (now per-country)
    temp_global = compute_temperature(raw)
    temp_country = compute_temperatures_by_country(raw)

    # 5. Behavior insights (uses global temp)
    insights = generate_behavior_insights(raw, temp_global)

    snapshot = {
        "date": today_str,
        "collected_at": datetime.now().isoformat(),
        "raw": raw,
        "external_benchmarks": {
            "fear_greed_index": fear_greed,
            "buffett_indicator": buffett,
            "shiller_pe": shiller,
        },
        "temperature": temp_global,
        "temperatures": temp_country,
        "behavior": insights,
        "data_health": data_health,
    }

    # Save daily
    daily_path = DAILY_DIR / f"{today_str}.json"
    _save_json(str(daily_path), snapshot)

    # Save latest
    _save_json(str(LATEST_PATH), snapshot)

    # Append to history
    hist_line = json.dumps({
        "date": today_str,
        "composite": temp_global["composite"],
        "label": temp_global["label"],
        "us_composite": temp_country["us"]["composite"],
        "hk_composite": temp_country["hk"]["composite"],
        "cn_composite": temp_country["cn"]["composite"],
        "vix": vix.get("vix"),
        "spy_pct": spy_pe.get("pct_10y"),
        "spy_pe": spy_pe.get("pe"),
        "hsi_pct": hsi.get("pct_10y"),
        "vix_pct": vix.get("pct_10y"),
        "buffett_pct": buffett.get("ratio_pct") if buffett.get("available") else None,
        "shiller_cape": shiller.get("cape") if shiller.get("available") else None,
    })
    with open(HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(hist_line + "\n")

    return snapshot


# ── dashboard ────────────────────────────────────────────────────────

def _color(val, thresholds: list) -> str:
    """Color-code a value based on threshold list [(min,color),...]."""
    for hi, c in thresholds:
        if val <= hi:
            return c
    return thresholds[-1][1] if thresholds else "?"


def print_dashboard(snapshot: dict = None) -> None:
    """Human-readable dashboard."""
    if snapshot is None:
        if not LATEST_PATH.exists():
            print("[ERROR] No market data. Run 'collect' first.")
            return
        with open(LATEST_PATH) as f:
            snapshot = json.load(f)

    t = snapshot["temperature"]
    b = snapshot["behavior"]
    raw = snapshot["raw"]
    ext = snapshot.get("external_benchmarks", {})
    fg = ext.get("fear_greed_index", {})
    spy = raw.get("spy", {})
    spy_h = raw.get("spy_hist", {})
    hsi = raw.get("hsi", {})
    vix_d = raw.get("vix", {})
    buffett = raw.get("buffett", {})

    def p(key, val, suf=""):
        if val is None:
            print(f"  {key}: --")
        elif isinstance(val, float):
            print(f"  {key}: {val:.1f}{suf}")
        else:
            print(f"  {key}: {val}{suf}")

    # ── External sentiment (headline) ──
    print()
    print("=" * 62)
    print(f"  {snapshot['date']}  |  {snapshot['collected_at'][:19]}")
    print()

    if fg.get("available"):
        fg_s = fg["score"]
        fg_lbl = fg["label"].upper()
        fg_short = {"extreme_greed": "EG", "greed": "GD",
                     "neutral": "NT", "fear": "FR",
                     "extreme_fear": "EF"}.get(fg["label"], "??")
        print(f"  FEAR & GREED INDEX (CFGI): {fg_s}/100 [{fg_short}]")
        print(f"  → {fg['note']}")
    else:
        print(f"  [External sentiment unavailable]")

    print()
    print(f"  -- Markets --")
    spy_pct = spy.get("pct_10y", 50)
    hsi_pct = hsi.get("pct_10y", 50)
    spy_pe = spy.get("pe")
    spy_price = spy.get("price")
    hsi_price = hsi.get("price")
    vix_val = vix_d.get("vix")

    p(f"SPY", spy_price)
    p(f"  PE", spy_pe, "x")
    p(f"  10yr %ile", spy_pct, "%")
    p(f"  MA50>MA200", spy_h.get("ma50_above_ma200"))
    print()
    p(f"HSI", hsi_price)
    p(f"  10yr %ile", hsi_pct, "%")
    print()
    p(f"CSI300", raw.get("csi300", {}).get("price"))
    p(f"  10yr %ile", raw.get("csi300", {}).get("pct_10y"), "%")
    print()
    p(f"VIX", vix_val)
    p(f"  10yr %ile", vix_d.get("pct_10y"), "%")
    p(f"  Zone", vix_d.get("zone", ""))
    print()

    if buffett.get("available"):
        p(f"Buffett Indicator", buffett.get("ratio_pct"), "%")
        p(f"  Zone", buffett.get("zone", ""))
        p(f"  Source", buffett.get("source", buffett.get("note", "?")))
        print()

    # ── My composite decomposition (analytical context) ──
    score = t["composite"]
    label = t["label"]
    label_short = {"extreme_greed": "EG", "greed": "GD",
                   "neutral": "NT", "fear": "FR",
                   "extreme_fear": "EF"}.get(label, "??")
    print(f"  -- Decomposition: FengInvest Composite ({score:.0f}/100 [{label_short}]) --")
    COMP_ORDER = ["vix_reverse", "spy_vs_ma200", "buffett_indicator",
                  "cross_market_divergence", "volume_anomaly", "short_term_momentum"]
    COMP_NAMES = {"vix_reverse": "VIX(reverse)", "spy_vs_ma200": "SPY vs MA200",
                  "buffett_indicator": "Buffett", "cross_market_divergence": "X-Market",
                  "volume_anomaly": "Volume", "short_term_momentum": "Momentum"}
    for k in COMP_ORDER:
        c = t["components"].get(k, {})
        s = c.get("score")
        w = c.get("weight_pct", 0)
        n = c.get("note", "")
        nm = COMP_NAMES.get(k, k)
        if s is not None:
            print(f"    {nm:>18s}: {s:5.1f} (w={w}%) | {n}")
        else:
            print(f"    {nm:>18s}:  --   (w=0%) | {c.get('note','')}")
    print(f"    {'Composite':>18s}: {score:.1f}  (external CFGI={fg.get('score','?')}/100)")
    print()

    # ── Behavior signals ──
    if b.get("alerts"):
        print(f"  -- Behavior Signals --")
        for a in b["alerts"]:
            cat_e = {"greed": "[GD]", "divergence": "[DV]",
                     "fear": "[FR]", "conflict": "[CF]",
                     "warning": "[WN]", "valuation": "[VL]"}.get(
                a["category"], f"[{a['category'][:2].upper()}]")
            print(f"    {cat_e} {a['message']}")
        print()
    history_lines = []
    if HISTORY_PATH.exists():
        with open(HISTORY_PATH) as f:
            history_lines = [json.loads(l) for l in f.readlines() if l.strip()]
    for h in history_lines[-10:]:
        print(f"    {h['date']}  |  {h['composite']:.0f}/100  [{h.get('label','?')}]  "
              f"VIX={h.get('vix','?')}  SPY%={h.get('spy_pct','?')}")
    print()


# ── history ──────────────────────────────────────────────────────────

def print_history(n: int = 30) -> None:
    """Print rolling trend of last N days."""
    if not HISTORY_PATH.exists():
        print("[ERROR] No history. Run 'collect' first.")
        return
    with open(HISTORY_PATH) as f:
        lines = [json.loads(l) for l in f.readlines() if l.strip()]

    if not lines:
        print("[ERROR] Empty history.")
        return

    print(f"\n  Market History (last {min(n, len(lines))} of {len(lines)} snapshots)")
    print(f"  {'Date':<14s} {'Temp':>6s} {'Label':<14s} {'VIX':>6s} {'SPY%':>6s} {'HSI%':>6s} {'PE':>5s}")
    print(f"  " + "-" * 60)
    for h in lines[-n:]:
        label_s = {"extreme_greed": "EG", "greed": "GD", "neutral": "NT",
                   "fear": "FR", "extreme_fear": "EF"}.get(h.get("label", ""), "??")
        v = f"{h.get('vix','?'):.1f}" if h.get("vix") else "?"
        sp = f"{h.get('spy_pct','?'):.0f}" if h.get("spy_pct") else "?"
        hp = f"{h.get('hsi_pct','?'):.0f}" if h.get("hsi_pct") else "?"
        pe = f"{h.get('spy_pe','?'):.0f}" if h.get("spy_pe") else "?"
        print(f"  {h['date']:<14s} {h['composite']:6.0f} {label_s:<14s} {v:>6s} {sp:>6s} {hp:>6s} {pe:>5s}")
    print()


# ── main ─────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "collect":
        result = collect()
        _failed = [k for k, s in result.get("data_health", {}).items() if s == "FAILED"]
        if _failed:
            print(f"[WARN] {len(_failed)} 个数据组件取数失败，温度含中性默认值成分: {', '.join(_failed)}",
                  file=sys.stderr)
        print(json.dumps({"status": "ok" if not _failed else "partial",
                          "failed_components": _failed,
                          "date": result["date"],
                          "temperature": result["temperature"]["composite"],
                          "label": result["temperature"]["label"]}, indent=2))

    elif cmd == "dashboard":
        print_dashboard()

    elif cmd == "history":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 30
        print_history(n)

    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
