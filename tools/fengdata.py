#!/usr/bin/env python3
"""fengdata — Pull stock data: price/MA + financials. Dual-backend: Futu (primary), yfinance (fallback).

Usage:
    python fengdata.py 0700.HK               # all data, auto backend
    python fengdata.py 0700.HK --price       # price + MA only
    python fengdata.py 0700.HK --financials  # financials only
    python fengdata.py 0700.HK --backend futu   # force Futu
    python fengdata.py 0700.HK --backend yfinance  # force yfinance
    python fengdata.py 600036.SS --sina-financials            # 新浪A股三大报表（PIT: 自带公告日期+审计状态）
    python fengdata.py 600036.SS --sina-financials --latest 4 # 只保留最近4个报告期
    python fengdata.py zt-pools                       # 东财涨停池（5 池：涨停/强势/炸板/跌停/昨日涨停）
    python fengdata.py zt-pools --date 20260901       # 指定日期
    python fengdata.py zt-pools --pools zt,qs,dt      # 只获取指定池
    python fengdata.py --fund-nav 160137              # 腾讯基金实时估算净值
    python fengdata.py --fund-nav 160137 005827       # 多只基金

Backend policy:
    --backend auto (default): try Futu → fallback yfinance
    --backend futu: Futu OpenD only, fail if not available
    --backend yfinance: yfinance only (original behavior)

Dependencies:
    futu-api (primary), yfinance + pandas (fallback)
"""
import json, os, re, sys, time, traceback
from datetime import datetime

os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)


# ─── Ticker conversion ───────────────────────────────────────────
# FengInvest uses yfinance format internally (e.g. 0700.HK, AAPL).
# Futu uses format: HK.00700, US.AAPL

def _to_futu_code(ticker: str) -> str:
    """Convert yfinance-style ticker to Futu format.
    0700.HK → HK.00700   AAPL → US.AAPL    TSLA → US.TSLA
    9988.HK → HK.09988   0005.HK → HK.00005
    """
    t = ticker.upper().strip()
    # Already in Futu format (US.xxx or HK.xxx)
    if re.match(r'^(US|HK|SH|SZ|SG|MY|JP|CC)\.', t):
        return t
    # yfinance format: 0700.HK or 9988.HK
    m = re.match(r'^(\d+\.)(HK)$', t)
    if m:
        nums = m.group(1).rstrip('.')
        return f"HK.{nums.zfill(5)}"
    m = re.match(r'^([A-Z]+)\.(HK)$', t)
    if m:
        return f"HK.{m.group(1)}"
    # Plain ticker like AAPL → US.AAPL
    if re.match(r'^[A-Z]+$', t):
        return f"US.{t}"
    return t  # pass through


def _to_yahoo_code(ticker: str) -> str:
    """Convert Futu-style ticker to yfinance format.
    HK.00700 → 0700.HK   US.AAPL → AAPL
    """
    t = ticker.upper().strip()
    m = re.match(r'^HK\.0*(\d+)$', t)
    if m:
        return f"{m.group(1)}.HK"
    m = re.match(r'^US\.(.+)$', t)
    if m:
        return m.group(1)
    return t


# ─── Backend detection ──────────────────────────────────────────

_FUTU_AVAILABLE = None

def _check_futu() -> bool:
    """Check if Futu OpenD is running and accessible."""
    global _FUTU_AVAILABLE
    if _FUTU_AVAILABLE is not None:
        return _FUTU_AVAILABLE
    try:
        from futu import OpenQuoteContext, RET_OK
        ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
        ret, data = ctx.get_global_state()
        ctx.close()
        _FUTU_AVAILABLE = (ret == RET_OK)
    except Exception:
        _FUTU_AVAILABLE = False
    return _FUTU_AVAILABLE


# ─── Futu backend ───────────────────────────────────────────────

def _futu_get_price(ticker: str) -> dict:
    """Get price + MA via Futu OpenD. Returns same shape as yfinance version."""
    from futu import OpenQuoteContext, RET_OK, KLType, AuType
    code = _to_futu_code(ticker)
    ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
    try:
        # 1) Snapshot for current price, high, low, volume
        ret_snap, snap_data = ctx.get_market_snapshot([code])
        if ret_snap != RET_OK or snap_data is None or (hasattr(snap_data, 'empty') and snap_data.empty):
            return {"error": f"Futu: no snapshot for {code}"}
        row = snap_data.iloc[0] if hasattr(snap_data, 'iloc') else snap_data[0]

        def _g(k, d=0):
            if hasattr(row, 'get'):
                v = row.get(k, d)
                return float(v) if v is not None and v == v else d  # nan check
            v = getattr(row, k, d)
            return float(v) if v is not None and v == v else d

        price = _g('last_price')
        open_p = _g('open_price')
        high = _g('high_price')
        low = _g('low_price')
        prev_close = _g('prev_close_price')
        volume = _g('volume')
        turnover = _g('turnover')

        # 2) K-line for MA & returns
        ret_k, klines, _page_key = ctx.request_history_kline(
            code, ktype=KLType.K_DAY, autype=AuType.QFQ, max_count=260)
        ma50 = ma120 = ma200 = None
        high52 = low52 = None
        m1 = m3 = m6 = ytd = None
        avg_vol = None

        if ret_k == RET_OK and klines is not None and not klines.empty:
            c = klines['close']
            v = klines['volume']
            # Futu klines has time_key column (string) instead of DatetimeIndex
            tk = klines.get('time_key') if 'time_key' in klines.columns else None

            ma50 = float(c.iloc[-50:].mean()) if len(c) >= 50 else None
            ma120 = float(c.iloc[-120:].mean()) if len(c) >= 120 else None
            ma200 = float(c.iloc[-200:].mean()) if len(c) >= 200 else None
            high52 = float(c.max())
            low52 = float(c.min())
            m1 = float((c.iloc[-1] / c.iloc[-22] - 1) * 100) if len(c) >= 22 else None
            m3 = float((c.iloc[-1] / c.iloc[-66] - 1) * 100) if len(c) >= 66 else None
            m6 = float((c.iloc[-1] / c.iloc[-126] - 1) * 100) if len(c) >= 126 else None
            # YTD: filter by time_key string >= "2026-01-01"
            if tk is not None:
                ytd_mask = tk >= "2026-01-01"
                ytd_idx_c = c[ytd_mask]
                if len(ytd_idx_c) > 0:
                    ytd = float((ytd_idx_c.iloc[-1] / ytd_idx_c.iloc[0] - 1) * 100)
            avg_vol = float(v.iloc[-30:].mean()) if len(v) >= 30 else None

        return {
            "ticker": ticker,
            "price": price,
            "open": open_p,
            "high_24h": high,
            "low_24h": low,
            "prev_close": prev_close,
            "change_pct": round((price / prev_close - 1) * 100, 2) if prev_close else None,
            "ma50": ma50,
            "ma120": ma120,
            "ma200": ma200,
            "high_52w": high52,
            "low_52w": low52,
            "price_above_ma50": price > ma50 if ma50 else None,
            "ma50_above_ma120": ma50 > ma120 if ma50 and ma120 else None,
            "ma120_above_ma200": ma120 > ma200 if ma120 and ma200 else None,
            "return_1m_pct": round(m1, 1) if m1 else None,
            "return_3m_pct": round(m3, 1) if m3 else None,
            "return_6m_pct": round(m6, 1) if m6 else None,
            "return_ytd_pct": round(ytd, 1) if ytd else None,
            "volume": volume,
            "turnover": turnover,
            "avg_volume_30d": avg_vol,
        }
    finally:
        ctx.close()


def _futu_get_financials(ticker: str) -> dict:
    """Get financial fundamentals via Futu snapshot. Limited vs yfinance but real-time.
    Uses snapshot data (market cap, PE, PB) — detailed financials fallback to yfinance."""
    from futu import OpenQuoteContext, RET_OK
    code = _to_futu_code(ticker)
    ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
    try:
        result = {"ticker": ticker}
        ret_snap, snap_data = ctx.get_market_snapshot([code])
        if ret_snap == RET_OK and snap_data is not None and not (hasattr(snap_data, 'empty') and snap_data.empty):
            row = snap_data.iloc[0] if hasattr(snap_data, 'iloc') else snap_data[0]
            def _g2(k):
                if hasattr(row, 'get'):
                    v = row.get(k)
                    if v is not None and v == v:  # not nan
                        return float(v)
                else:
                    v = getattr(row, k, None)
                    if v is not None and v == v:
                        return float(v)
                return None
            result["market_cap"] = _g2('total_market_val')
            result["trailing_pe"] = _g2('pe_ttm_ratio')
            result["pb"] = _g2('pb_ratio')
            result["pe"] = _g2('pe_ratio')

        # Quick financial statements (time-boxed, may fail without permissions)
        try:
            ret_inc, inc_data = ctx.get_financials_statements(code, statement_type=1, financial_type=10, num=3)
            if ret_inc == RET_OK and inc_data is not None and not (hasattr(inc_data, 'empty') and inc_data.empty):
                _extract_fs_rows(inc_data, result, 'revenue_annual', ['Total Revenue', 'Revenue', '营业总收入'])
                _extract_fs_rows(inc_data, result, 'net_income_annual', ['Net Income', '净利润', '归属于母公司'])
                _extract_fs_rows(inc_data, result, 'operating_income_annual', ['Operating Income', '营业利润'])
                # Count years
                yrs = result.get('revenue_annual', [])
                if yrs:
                    result['financial_years_covered'] = len(yrs)

            ret_cf, cf_data = ctx.get_financials_statements(code, statement_type=3, financial_type=10, num=3)
            if ret_cf == RET_OK and cf_data is not None and not (hasattr(cf_data, 'empty') and cf_data.empty):
                _extract_fs_rows(cf_data, result, 'fcf_annual', ['Free Cash Flow', 'FCF', '自由现金流'])

            ret_bs, bs_data = ctx.get_financials_statements(code, statement_type=2, financial_type=10, num=3)
            if ret_bs == RET_OK and bs_data is not None and not (hasattr(bs_data, 'empty') and bs_data.empty):
                _extract_fs_rows(bs_data, result, 'equity_annual', ['Total Equity', 'Shareholders', 'Stockholders', '股东权益', '归属于母公司'])
                _extract_fs_rows(bs_data, result, 'debt_annual', ['Total Debt', 'Total Liabilities', '负债合计', '总负债'])
                _extract_fs_rows(bs_data, result, 'cash_annual', ['Cash And Cash', 'Cash and cash', '货币资金', '现金及现金等价物'])
        except Exception:
            pass  # financial statements are bonus; don't fail

        return result
    finally:
        ctx.close()


def _extract_fs_rows(df, result, key, index_keywords):
    """Extract a financial statement row by keyword matching on index."""
    matches = [idx for idx in df.index if any(kw in str(idx) for kw in index_keywords)]
    if not matches:
        return
    vals = [float(df.loc[matches[0], c]) for c in df.columns
            if pd_notna(df.loc[matches[0], c])]
    if vals:
        result[key] = vals


def pd_notna(v):
    """Null-safe pd.notna replacement."""
    import pandas as pd
    return pd.notna(v)


# ─── yfinance backend (unchanged) ───────────────────────────────

_HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"}
_YAHOO_HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]


def _yahoo_chart_http(symbol: str, range_str: str = "1y", _tries: int = 3) -> dict:
    """Fetch OHLCV+meta from Yahoo chart API using stdlib only (no yfinance/Futu).

    Yahoo's hosts intermittently drop the SSL handshake, so we retry across
    query1/query2 with backoff. Returns {'ok': True, 'data': {...}} or {'ok': False}.
    symbol = yfinance/Yahoo style (SPY, 0700.HK, 600036.SS).
    """
    import json as _json
    import random as _random
    import urllib.request as _ur

    last_err = None
    for attempt in range(_tries):
        host = _YAHOO_HOSTS[attempt % len(_YAHOO_HOSTS)]
        url = f"https://{host}/v8/finance/chart/{symbol}?range={range_str}&interval=1d&includePrePost=false"
        req = _ur.Request(url, headers=_HTTP_HEADERS)
        try:
            with _ur.urlopen(req, timeout=15) as r:
                d = _json.loads(r.read().decode("utf-8"))
            break
        except Exception as e:  # noqa: BLE001 - retry on transient SSL/network errors
            last_err = e
            time.sleep(0.7 * (attempt + 1) + _random.random() * 0.4)
    else:
        return {"ok": False, "error": f"Yahoo HTTP error after {_tries} tries: {last_err}"}

    try:
        res = d["chart"]["result"][0]
    except (KeyError, IndexError, TypeError):
        return {"ok": False, "error": f"Yahoo bad response: {str(d)[:200]}"}

    ts = res.get("timestamp") or []
    bc = res.get("indicators", {}).get("quote") or []
    if not bc:
        return {"ok": False, "error": "No quote series"}
    q = bc[0]
    closes = [c for c in q.get("close") if c not in (None,)]
    closes = [float(c) for c in closes]
    if not closes:
        return {"ok": False, "error": "Empty close series"}
    ma = lambda n: (sum(closes[-n:]) / n) if len(closes) >= n else None
    prices = [float(c) for c in q.get("close") if c not in (None,)]
    highs = [float(h) for h in q.get("high") if h not in (None,)]
    lows = [float(l) for l in q.get("low") if l not in (None,)]
    highs = highs[:len(prices)]
    lows = lows[:len(prices)]
    meta = res.get("meta") or {}
    return {
        "ok": True,
        "data": {
            "price": prices[-1],
            "ma50": ma(50), "ma120": ma(120), "ma200": ma(200),
            "high_52w": max(highs) if highs else None,
            "low_52w": min(lows) if lows else None,
            "return_1m_pct": round((prices[-1] / prices[-22] - 1) * 100, 1) if len(prices) >= 22 else None,
            "return_3m_pct": round((prices[-1] / prices[-66] - 1) * 100, 1) if len(prices) >= 66 else None,
            "return_6m_pct": round((prices[-1] / prices[-126] - 1) * 100, 1) if len(prices) >= 126 else None,
            "currency": meta.get("currency"),
            "symbol": symbol,
        },
        "meta": meta,
    }


def _to_tencent_code(ticker: str) -> str | None:
    """Convert a ticker to Tencent (qt.gtimg.cn) symbol, or None if not supported.

    600036.SS → sh600036   002032.SZ → sz002032   000300.SS → sh000300 (指数)
    0700.HK → hk00700      hkHSI/hkHSTECH → 透传   159766.SZ → sz159766 (基金)
    ticker 用 yfinance/Yahoo 风格输入。
    """
    t = (ticker or "").upper().strip()
    if t in ("HKHSI", "HSTECH", "HKHSTECH"):
        return "hkHSI" if t == "HKHSI" else "hkHSTECH"
    # 腾讯直通形式（hk 前缀）直接透传
    if re.match(r"^HK[A-Z]+$", t):
        return t.lower()
    m = re.match(r"^(6|9|0)(\d{5})\.(SS|SH)$", t)
    if m:  # A股 上证
        return f"sh{m.group(1)}{m.group(2)}"
    m = re.match(r"^(\d{6})\.SZ$", t)
    if m:  # A股 深证/创业板/基金 .SZ
        return f"sz{m.group(1)}"
    # 港股代码支持 3-5 位数字（0700.HK → hk00700, 5.HK → hk00005）
    m = re.match(r"^(\d{1,5})\.HK$", t)
    if m:  # 港股
        return f"hk{m.group(1).zfill(5)}"
    return None  # 美股/未知 → 交给 Yahoo


def _tx_get_price(ticker: str) -> dict:
    """Fetch live quote (price + change) via Tencent qt.gtimg.cn using stdlib.

    Covers A股/港股/基金/恒生指数类。只取现价与涨跌；MA 需另由 Yahoo 历史算。
    返回 {'ok': True, 'price': x, 'change_pct': y, 'name': z} 或 {'ok': False, 'error': ...}
    """
    import urllib.request
    code = _to_tencent_code(ticker)
    if not code:
        return {"ok": False, "error": f"Tencent unsupported for {ticker}"}
    url = f"https://qt.gtimg.cn/q={code}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            body = r.read().decode("gbk", "ignore")
        if "pv_none_match" in body or "=" not in body:
            return {"ok": False, "error": f"Tencent no match for {ticker}"}
        f = body.split('="', 1)[1].rstrip('";').split("~")
        # 字段: 1名称, 2代码, 3现价, 4昨收, 31涨跌额, 32涨跌%
        if len(f) <= 32:
            return {"ok": False, "error": f"Tencent bad fields for {ticker}"}
        try:
            price = float(f[3])
        except (ValueError, IndexError):
            return {"ok": False, "error": f"Tencent price parse fail for {ticker}"}
        chg = None
        try:
            chg = float(f[32]) if f[32] not in ("", "-") else None
        except (ValueError, IndexError):
            chg = None
        return {"ok": True, "price": price, "change_pct": chg, "name": f[1], "source": "tencent_qtgimg (stdlib)"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Tencent HTTP error: {e}"}


def _yf_get_price(ticker: str, years: int = 1) -> dict:
    # Prefer stdlib direct-Yahoo fetch (no yfinance dependency needed).
    # Input may be yfinance-style (US.SPY / 0700.HK / 600036.SS) — convert to
    # the bare Yahoo symbol (SPY / 0700.HK / 600036.SS) before hitting the API.
    yahoo_sym = _to_yahoo_code(ticker) or ticker
    # A股/港股/香港指数优先走腾讯行情（快、国产免费、免历史重试）。
    tx = _tx_get_price(_to_yahoo_code(ticker) or ticker)
    if tx["ok"]:
        return {
            "ticker": ticker, "price": tx["price"],
            "ma50": None, "ma120": None, "ma200": None,
            "high_52w": None, "low_52w": None,
            "price_above_ma50": None, "ma50_above_ma120": None, "ma120_above_ma200": None,
            "return_1m_pct": None, "return_3m_pct": None, "return_6m_pct": None,
            "return_ytd_pct": None, "avg_volume_30d": None,
            "change_pct": tx.get("change_pct"),
            "name": tx.get("name"),
            "_source_note": tx.get("source"),
        }
    try:
        http = _yahoo_chart_http(yahoo_sym)
        if http["ok"]:
            d = http["data"]
            price = d["price"]
            # YTD from chart meta (only if same-year range included); approximate skip
            return {
                "ticker": ticker, "price": price, "ma50": d["ma50"], "ma120": d["ma120"],
                "ma200": d["ma200"], "high_52w": d["high_52w"], "low_52w": d["low_52w"],
                "price_above_ma50": d["ma50"] is not None and price > d["ma50"],
                "ma50_above_ma120": d["ma50"] is not None and d["ma120"] is not None and d["ma50"] > d["ma120"],
                "ma120_above_ma200": d["ma120"] is not None and d["ma200"] is not None and d["ma120"] > d["ma200"],
                "return_1m_pct": d["return_1m_pct"], "return_3m_pct": d["return_3m_pct"],
                "return_6m_pct": d["return_6m_pct"], "return_ytd_pct": None,
                "avg_volume_30d": None, "change_pct": None,
                "_source_note": "yahoo_chart_http (stdlib)",
            }
    except Exception as _e:
        pass

    # Legacy fallback: yfinance if installed
    try:
        import yfinance as yf
        import pandas as pd
    except ImportError:
        return {"error": "No market backend: Futu OpenD off, yfinance not installed, Yahoo HTTP failed"}
    t = yf.Ticker(ticker)
    if years > 1:
        hist = t.history(period="max")
    else:
        hist = t.history(period="1y")
    if hist.empty:
        return {"error": f"No price data for {ticker}"}
    c = hist["Close"]
    price = float(c.iloc[-1])
    ma50 = float(c.iloc[-50:].mean()) if len(c) >= 50 else None
    ma120 = float(c.iloc[-120:].mean()) if len(c) >= 120 else None
    ma200 = float(c.iloc[-200:].mean()) if len(c) >= 200 else None
    high52 = float(hist["High"].max())
    low52 = float(hist["Low"].min())
    m1 = float((c.iloc[-1] / c.iloc[-22] - 1) * 100) if len(c) >= 22 else None
    m3 = float((c.iloc[-1] / c.iloc[-66] - 1) * 100) if len(c) >= 66 else None
    m6 = float((c.iloc[-1] / c.iloc[-126] - 1) * 100) if len(c) >= 126 else None
    ytd_start = c[c.index >= "2026-01-01"]
    ytd = float((ytd_start.iloc[-1] / ytd_start.iloc[0] - 1) * 100) if len(ytd_start) > 0 else None
    vol = float(c.iloc[-30:].mean()) if len(c) >= 30 else None
    return {
        "ticker": ticker, "price": price, "ma50": ma50, "ma120": ma120, "ma200": ma200,
        "high_52w": high52, "low_52w": low52,
        "price_above_ma50": price > ma50 if ma50 else None,
        "ma50_above_ma120": ma50 > ma120 if ma50 and ma120 else None,
        "ma120_above_ma200": ma120 > ma200 if ma120 and ma200 else None,
        "return_1m_pct": round(m1, 1) if m1 else None,
        "return_3m_pct": round(m3, 1) if m3 else None,
        "return_6m_pct": round(m6, 1) if m6 else None,
        "return_ytd_pct": round(ytd, 1) if ytd else None,
        "avg_volume_30d": vol,
    }


def _yf_get_financials(ticker: str) -> dict:
    import yfinance as yf
    import pandas as pd
    t = yf.Ticker(ticker)
    info = t.info or {}
    result = {
        "ticker": ticker,
        "market_cap": info.get("marketCap"),
        "trailing_pe": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "pb": info.get("priceToBook"),
        "roe": info.get("returnOnEquity"),
        "roe_pct": round(info.get("returnOnEquity", 0) * 100, 1) if info.get("returnOnEquity") else None,
        "profit_margin_pct": round(info.get("profitMargins", 0) * 100, 1) if info.get("profitMargins") else None,
        "operating_margin_pct": round(info.get("operatingMargins", 0) * 100, 1) if info.get("operatingMargins") else None,
        "gross_margin_pct": round(info.get("grossMargins", 0) * 100, 1) if info.get("grossMargins") else None,
        "revenue_growth_pct": round(info.get("revenueGrowth", 0) * 100, 1) if info.get("revenueGrowth") else None,
        "earnings_growth_pct": round(info.get("earningsGrowth", 0) * 100, 1) if info.get("earningsGrowth") else None,
        "dividend_yield_pct": info.get("dividendYield"),
        "payout_ratio": info.get("payoutRatio"),
        "beta": info.get("beta"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "full_time_employees": info.get("fullTimeEmployees"),
    }
    fs = t.financials
    if fs is not None and not fs.empty:
        n_years = min(5, len(fs.columns))
        rev = [float(fs.loc["Total Revenue", c]) for c in fs.columns[:n_years]
               if "Total Revenue" in fs.index and pd.notna(fs.loc["Total Revenue", c])]
        ni = [float(fs.loc["Net Income", c]) for c in fs.columns[:n_years]
              if "Net Income" in fs.index and pd.notna(fs.loc["Net Income", c])]
        op = [float(fs.loc["Operating Income", c]) for c in fs.columns[:n_years]
              if "Operating Income" in fs.index and pd.notna(fs.loc["Operating Income", c])]
        result["revenue_annual"] = rev
        result["net_income_annual"] = ni
        result["operating_income_annual"] = op
        result["financial_years_covered"] = len(rev)
    cf = t.cashflow
    if cf is not None and not cf.empty:
        n_years = min(5, len(cf.columns))
        fcf = [float(cf.loc["Free Cash Flow", c]) for c in cf.columns[:n_years]
               if "Free Cash Flow" in cf.index and pd.notna(cf.loc["Free Cash Flow", c])]
        ocf = [float(cf.loc["Operating Cash Flow", c]) for c in cf.columns[:n_years]
               if "Operating Cash Flow" in cf.index and pd.notna(cf.loc["Operating Cash Flow", c])]
        capex = [float(cf.loc["Capital Expenditure", c]) for c in cf.columns[:n_years]
                 if "Capital Expenditure" in cf.index and pd.notna(cf.loc["Capital Expenditure", c])]
        result["fcf_annual"] = fcf
        result["operating_cf_annual"] = ocf
        result["capex_annual"] = capex
    bs = t.balance_sheet
    if bs is not None and not bs.empty:
        n_years = min(5, len(bs.columns))
        cash = [float(bs.loc["Cash And Cash Equivalents", c]) for c in bs.columns[:n_years]
                if "Cash And Cash Equivalents" in bs.index and pd.notna(bs.loc["Cash And Cash Equivalents", c])]
        debt = [float(bs.loc["Total Debt", c]) for c in bs.columns[:n_years]
                if "Total Debt" in bs.index and pd.notna(bs.loc["Total Debt", c])]
        equity = [float(bs.loc["Stockholders Equity", c]) for c in bs.columns[:n_years]
                  if "Stockholders Equity" in bs.index and pd.notna(bs.loc["Stockholders Equity", c])]
        result["cash_annual"] = cash
        result["debt_annual"] = debt
        result["equity_annual"] = equity
    result["recommendation"] = info.get("recommendationKey")
    result["analyst_count"] = info.get("numberOfAnalystOpinions")
    result["target_mean"] = info.get("targetMeanPrice")
    result["target_high"] = info.get("targetHighPrice")
    result["target_low"] = info.get("targetLowPrice")
    shares = info.get("sharesOutstanding")
    if not shares:
        price = info.get("currentPrice") or info.get("regularMarketPrice")
        mcap = info.get("marketCap")
        if price and mcap and price > 0:
            shares = mcap / price
    result["shares_outstanding"] = shares
    return result


# ─── New Futu data modes: valuation, shareholders, analysts, etc ──

_WARNINGS = {
    "valuation": ['⚠️ 估值分位基于 Futu 数据，复权处理可能不精确，建议交叉验证'],
    "shareholders": ['⚠️ 内部人交易仅支持美股', '⚠️ 持股变动数据可能有T-2延迟'],
    "analysts": ['⚠️ 美股分析师数据更完整，港股覆盖可能不全'],
    "revenue": ['⚠️ 主营构成需年报权限，可能无数据'],
}


def _mode_ctx(ticker):
    """Create a Futu quote context for a single mode call."""
    from futu import OpenQuoteContext
    code = _to_futu_code(ticker)
    ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
    return code, ctx


def _futu_get_valuation(ticker: str) -> dict:
    """PE/PB/PS 历史估值分位+趋势."""
    from futu import RET_OK
    code, ctx = _mode_ctx(ticker)
    try:
        result = {"ticker": ticker, "_warnings": _WARNINGS["valuation"]}
        for vtype, vname in [(1, 'pe'), (2, 'pb'), (3, 'ps')]:
            try:
                ret, data = ctx.get_valuation_detail(code, valuation_type=vtype, interval_type=5)
                if ret == RET_OK and data is not None and not (hasattr(data, 'empty') and data.empty):
                    row = data.iloc[0] if hasattr(data, 'iloc') else data
                    g = row.get if hasattr(row, 'get') else (lambda k, d=None: getattr(row, k, d))
                    trend = g('trend', {})
                    if isinstance(trend, dict):
                        result[f"{vname}_current"] = trend.get('current_value')
                        result[f"{vname}_avg"] = trend.get('average_value')
                        result[f"{vname}_percentile"] = trend.get('valuation_percentile')
                        result[f"{vname}_forward"] = trend.get('forward_value')
            except Exception:
                pass
        return result
    finally:
        ctx.close()


def _futu_get_shareholders(ticker: str) -> dict:
    """机构+内部人+股东增减持. 部分数据可能因权限不可用。"""
    code, ctx = _mode_ctx(ticker)
    try:
        result = {"ticker": ticker, "_warnings": _WARNINGS["shareholders"]}
        _try_futu_api(ctx, 'get_shareholders_overview', result, code,
                      rename={'institution_hold_ratio': 'institution_ratio'})
        _try_futu_api(ctx, 'get_shareholders_holding_changes', result, code,
                      params={'num': 5}, list_key='recent_changes')
        _try_futu_api(ctx, 'get_insider_trade_list', result, code,
                      params={'num': 5}, list_key='insider_trades')
        return result
    finally:
        ctx.close()


def _futu_get_analysts(ticker: str) -> dict:
    """分析师评级+目标价+晨星."""
    code, ctx = _mode_ctx(ticker)
    try:
        result = {"ticker": ticker, "_warnings": _WARNINGS["analysts"]}
        _try_futu_api(ctx, 'get_research_analyst_consensus', result, code,
                      rename={'buy': 'buy_ratio', 'hold': 'hold_ratio', 'sell': 'sell_ratio',
                              'highest': 'target_high', 'average': 'target_mean', 'lowest': 'target_low',
                              'total': 'analyst_count'})
        _try_futu_api(ctx, 'get_research_morningstar_report', result, code,
                      rename={'star_rating': 'morningstar_rating', 'fair_value': 'fair_value', 'moat': 'moat'})
        return result
    finally:
        ctx.close()


def _futu_get_corp_actions(ticker: str) -> dict:
    """分红+回购+拆股."""
    code, ctx = _mode_ctx(ticker)
    try:
        result = {"ticker": ticker}
        _try_futu_api(ctx, 'get_corporate_actions_dividends', result, code,
                      list_key='dividends')
        _try_futu_api(ctx, 'get_corporate_actions_buybacks', result, code,
                      params={'num': 5}, list_key='buybacks')
        _try_futu_api(ctx, 'get_corporate_actions_stock_splits', result, code,
                      params={'num': 5}, list_key='stock_splits')
        return result
    finally:
        ctx.close()


def _futu_get_profile(ticker: str) -> dict:
    """公司详情+高管+经营效率."""
    code, ctx = _mode_ctx(ticker)
    try:
        result = {"ticker": ticker}
        _try_futu_api(ctx, 'get_market_snapshot', result, code,
                      params={'code_list': [code]},
                      rename={'name': 'name', 'listing_date': 'listing_date',
                              'lot_size': 'lot_size', 'total_market_val': 'market_cap',
                              'issued_shares': 'issued_shares'},
                      single_row=True)
        _try_futu_api(ctx, 'get_company_profile', result, code,
                      raw_key='profile')
        _try_futu_api(ctx, 'get_company_executives', result, code,
                      list_key='executives')
        return result
    finally:
        ctx.close()


def _futu_get_revenue(ticker: str) -> dict:
    """主营构成."""
    code, ctx = _mode_ctx(ticker)
    try:
        result = {"ticker": ticker, "_warnings": _WARNINGS["revenue"]}
        _try_futu_api(ctx, 'get_financials_revenue_breakdown', result, code,
                      rename={'period': 'period'}, raw_key='breakdown_data')
        return result
    finally:
        ctx.close()


def _try_futu_api(ctx, api_name, result, code,
                  params=None, rename=None, list_key=None, raw_key=None, single_row=False):
    """Generic Futu API caller. Tries the API, extracts fields into result.

    Handles both DataFrame and dict returns. Silently fails on error.
    """
    from futu import RET_OK
    try:
        api_fn = getattr(ctx, api_name)
        args = [code]
        if params:
            args += [params] if api_name == 'get_market_snapshot' else []
            fn_params = {k: v for k, v in params.items()}
        else:
            fn_params = {}

        ret, data = api_fn(code, **{k: v for k, v in (params or {}).items()
                                      if k != 'code_list'})

        # Handle get_market_snapshot specially (takes code_list)
        if api_name == 'get_market_snapshot':
            ret, data = api_fn([code])

        if ret != RET_OK or data is None:
            return

        # Dict return (analyst consensus, etc.) — flat merge
        if isinstance(data, dict):
            if rename:
                for old_k, new_k in rename.items():
                    if old_k in data and data[old_k] is not None:
                        result[new_k] = data[old_k]
            elif raw_key:
                result[raw_key] = data
            else:
                result.update(data)
            return

        # DataFrame return
        if hasattr(data, 'empty') and not data.empty:
            if single_row:
                row = data.iloc[0]
                if rename and hasattr(row, 'get'):
                    for old_k, new_k in rename.items():
                        v = row.get(old_k)
                        if v is not None and (not hasattr(v, '__float__') or v == v):
                            result[new_k] = v
                return

            if list_key:
                items = []
                for _, r in data.iterrows() if hasattr(data, 'iterrows') else []:
                    items.append({k: v for k, v in r.items() if v is not None and (not hasattr(v, '__float__') or v == v)})
                if items:
                    result[list_key] = items
                return

            if rename:
                row = data.iloc[0]
                if hasattr(row, 'get'):
                    for old_k, new_k in rename.items():
                        v = row.get(old_k)
                        if v is not None and (not hasattr(v, '__float__') or v == v):
                            result[new_k] = v
                return

    except Exception:
        pass


def _sf(row_or_getter, key, cast=float):
    """Safe field extraction: handle dict.get and attr access, nan-safe."""
    import math
    if callable(row_or_getter):
        v = row_or_getter(key) if isinstance(key, str) else row_or_getter(key[0])
    else:
        m = row_or_getter
        v = m.get(key, None) if hasattr(m, 'get') else getattr(m, key, None)
    if v is None:
        return None
    try:
        fv = cast(v)
        if isinstance(fv, float) and (math.isnan(fv) or math.isinf(fv)):
            return None
        return fv
    except (ValueError, TypeError):
        return None


# ─── Holdings batch update ──────────────────────────────────────

def _quote_free(ticker: str):
    """零依赖实时价回退：A股/港股走腾讯 qt.gtimg.cn，美股走 Yahoo chart。拿不到返回 None。"""
    import urllib.request
    t = ticker.upper()
    try:
        if t.endswith((".SS", ".SZ")):
            sym = ("sh" if t.endswith(".SS") else "sz") + t[:6]
            req = urllib.request.Request(f"https://qt.gtimg.cn/q={sym}", headers={"User-Agent": "Mozilla/5.0"})
            txt = urllib.request.urlopen(req, timeout=10).read().decode("gbk", "ignore")
            parts = txt.split("~")
            return float(parts[3]) if len(parts) > 3 and parts[3] else None
        if t.endswith(".HK"):
            sym = "r_hk" + t.split(".")[0].zfill(5)
            req = urllib.request.Request(f"https://qt.gtimg.cn/q={sym}", headers={"User-Agent": "Mozilla/5.0"})
            txt = urllib.request.urlopen(req, timeout=10).read().decode("gbk", "ignore")
            parts = txt.split("~")
            return float(parts[3]) if len(parts) > 3 and parts[3] else None
        # 美股：东财 push2 实时（105=纳斯达克/106=纽交所/107=美交所），Yahoo 403 时的主回退
        import urllib.request, json as _json
        for mkt in ("105", "106", "107"):
            try:
                url = (f"https://push2.eastmoney.com/api/qt/stock/get?secid={mkt}.{t}"
                       "&fltt=2&invt=2&fields=f43")
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                j = _json.loads(urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "ignore"))
                v = ((j.get("data") or {}).get("f43"))
                if v:
                    return float(v)
            except Exception:
                continue
        r = _yahoo_chart_http(t, range_str="5d", _tries=2)
        if r.get("ok"):
            d = r.get("data") or {}
            closes = [c for c in (d.get("close") or []) if c]
            return float(closes[-1]) if closes else None
    except Exception:
        return None
    return None


def _update_holdings_prices():
    """Batch-update current_price for all holdings/ via Futu snapshots."""
    holdings_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "holdings")
    if not os.path.isdir(holdings_dir):
        print(json.dumps({"error": "holdings/ directory not found"}, indent=2))
        return

    updated = []
    failed = []
    for fname in sorted(os.listdir(holdings_dir)):
        m = re.match(r"^hold_([A-Za-z0-9.]+)\.json$", fname)
        if not m:
            continue
        ticker = m.group(1)
        code = _to_futu_code(ticker)
        try:
            price = None
            src = "futu"
            try:
                from futu import OpenQuoteContext, RET_OK
                ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
                ret, snap = ctx.get_market_snapshot([code])
                ctx.close()
                if ret == RET_OK:
                    row = snap.iloc[0] if hasattr(snap, 'iloc') else snap[0]
                    price = float(row.get('last_price', 0) if hasattr(row, 'get') else getattr(row, 'last_price', 0))
            except Exception:
                price = None
            if not price or price <= 0:
                # 回退：腾讯/Yahoo 免依赖源（2026-09-06 一键更新真跑要求）
                src = "free"
                price = _quote_free(ticker)
            if not price or price <= 0:
                failed.append({"ticker": ticker, "error": "futu 与免费源均无价"})
                continue
            # Update the holding file
            fpath = os.path.join(holdings_dir, fname)
            with open(fpath, "r", encoding="utf-8") as fh:
                h = json.load(fh)
            old_price = h.get("position", {}).get("current_price", 0)
            h.setdefault("position", {})["current_price"] = price
            h.setdefault("position", {})["market_value"] = price * (h["position"].get("shares") or h["position"].get("units") or 0)
            h.setdefault("meta", {})["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            with open(fpath, "w", encoding="utf-8") as fh:
                json.dump(h, fh, indent=2, ensure_ascii=False)
            updated.append({"ticker": ticker, "source": src, "old_price": old_price, "new_price": price,
                           "change_pct": round((price / old_price - 1) * 100, 2) if old_price else None})
        except Exception as e:
            failed.append({"ticker": ticker, "error": str(e)[:100]})

    result = {"updated_count": len(updated), "failed_count": len(failed)}
    if updated:
        result["updated"] = updated
    if failed:
        result["failed"] = failed
    print(json.dumps(result, indent=2, default=str))


# ─── Real-time FX (人民币统一口径) ──────────────────────────────

def _fx_rates():
    """Fetch live cross rates via Yahoo chart API (zero-dependency stdlib).

    Returns {"USDCNY":.., "HKDCNY":.., "USDHKD":.., "date":.., "live":bool}.
    实时失败或关键币种缺失时，回退持仓 JSON meta.fx_rates 快照（live=False），保证总拿得到值。
    """
    symbols = ["USDCNY=X", "HKDCNY=X", "USDHKD=X"]
    rates = {}
    for sym in symbols:
        try:
            r = _yahoo_chart_http(sym, range_str="5d", _tries=4)
            if not r.get("ok"):
                continue
            price = (r.get("data") or {}).get("price")
            if price is None:
                price = (r.get("meta") or {}).get("regularMarketPrice")
            if price:
                key = sym.replace("=X", "")
                rates[key] = round(float(price), 6)
        except Exception:
            continue
    # 缺某币种时用交叉换算补全（简化恒等式，避免单源失败拖垮整体）
    if "USDCNY" in rates and "USDHKD" in rates and "HKDCNY" not in rates:
        rates["HKDCNY"] = round(rates["USDCNY"] / rates["USDHKD"], 6)
    elif "USDCNY" in rates and "HKDCNY" in rates and "USDHKD" not in rates:
        rates["USDHKD"] = round(rates["USDCNY"] / rates["HKDCNY"], 6)
    elif "USDCNY" not in rates and "HKDCNY" in rates and "USDHKD" in rates:
        rates["USDCNY"] = round(rates["HKDCNY"] * rates["USDHKD"], 6)

    # 关键币种(USDCNY+HKDCNY)齐全且非零 → 视为实时成功
    if rates.get("USDCNY") and rates.get("HKDCNY"):
        rates.setdefault("USDHKD", round(rates["USDCNY"] / rates["HKDCNY"], 6))
        rates["date"] = datetime.now().strftime("%Y-%m-%d")
        rates["source"] = "Yahoo Finance chart (USDCNY=X/HKDCNY=X/USDHKD=X)"
        rates["live"] = True
        return rates

    # 否则回退持仓快照（holdings/hold_cash_cny.json · meta.fx_rates）
    try:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(base, "holdings", "hold_cash_cny.json"), encoding="utf-8") as fh:
            h = json.load(fh)
        fxr = h.get("meta", {}).get("fx_rates", {})
        usdcny = fxr.get("USD_CNY")
        hkdcny = fxr.get("HKD_CNY")
        if usdcny and hkdcny:
            return {
                "USDCNY": float(usdcny),
                "HKDCNY": float(hkdcny),
                "USDHKD": round(float(usdcny) / float(hkdcny), 6),
                "date": fxr.get("date", "snapshot"),
                "source": "holdings meta.fx_rates snapshot (fallback)",
                "live": False,
            }
    except Exception:
        pass
    return None


def _cmd_fx():
    """--mode fx 入口：输出实时汇率 JSON。"""
    rates = _fx_rates()
    if not rates:
        print(json.dumps({"error": "实时汇率获取失败（网络/源不可达）"}, indent=2))
        sys.exit(1)
    print(json.dumps(rates, indent=2, ensure_ascii=False))


# ─── Sina A股三大报表（PIT：自带公告日期+审计状态）──────────────
# 移植自 akshare stock_financial_report_sina（仓库外参考：
#   ~/_research/akshare\akshare\stock_fundamental\stock_finance_sina.py）
# 原实现关键点（逐一保留）：
#   - URL: https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022
#   - params: paperCode=sh600036 / source=fzb|lrb|llb / type=0 / page=1 / num=1000
#   - 报告期取自 result.data.report_date[].date_value；科目取自
#     result.data.report_list[<报告期>].data[].{item_title,item_value}
#   - 每期附带元信息行（原 akshare 宽表尾部追加）：data_source / is_audit /
#     publish_date / rCurrency / rType / update_time(时间戳)
#   - 重复科目（'国内票证结算'/'内部应收款'）保留首个（同 akshare keep='first'）

_PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SINA_FIN_URL = "https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022"
_SINA_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36")
# (输出键, 中文名, 新浪 source 参数)
_SINA_STATEMENTS = [
    ("balance", "资产负债表", "fzb"),
    ("income", "利润表", "lrb"),
    ("cashflow", "现金流量表", "llb"),
]
_SINA_CACHE_TTL = 86400  # 本地缓存 TTL：1 天


def _to_sina_code(ticker: str):
    """A 股 ticker → 新浪代码：600036.SS/600036.SH → sh600036；000001.SZ → sz000001。
    裸 6 位数字按首位推断（6/9 → 沪，0/3 → 深）。非 A 股返回 None。"""
    t = (ticker or "").upper().strip()
    m = re.match(r"^(SH|SZ)\.0*(\d{6})$", t)  # Futu 风格 SH.600036
    if m:
        return f"{m.group(1).lower()}{m.group(2)}"
    m = re.match(r"^(\d{6})\.(SS|SH)$", t)
    if m:
        return f"sh{m.group(1)}"
    m = re.match(r"^(\d{6})\.SZ$", t)
    if m:
        return f"sz{m.group(1)}"
    m = re.match(r"^(\d{6})$", t)
    if m:
        d = m.group(1)
        return f"sh{d}" if d[0] in "69" else f"sz{d}"
    return None


def _sina_num(v):
    """新浪科目值转 float；'--'/'-'/'None'/空/非数值 → None。"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v == v else None  # NaN 过滤
    s = str(v).strip().replace(",", "")
    if not s or s in ("--", "-", "None", "null", "nan", "N/A"):
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return f if f == f else None


def _sina_ts_iso(v):
    """update_time（unix 秒）→ ISO 字符串；解析失败原样返回。"""
    if v is None:
        return None
    try:
        ts = float(v)
        if ts > 0:
            return datetime.fromtimestamp(ts).isoformat()
    except (TypeError, ValueError, OverflowError):
        pass
    return v


def _sina_statement(sina_code: str, source: str, latest=None):
    """拉取新浪单张报表。返回 (data{报告期:{科目:值}}, meta{报告期:{publish_date,is_audit,...}}, warnings, cache_src)。

    请求走 fengthrottle.cached_get（限流 + TTL 缓存，1 天）。网络失败由 fengthrottle
    回退陈旧缓存或上抛异常，本函数不做吞错。
    """
    if source not in ("fzb", "lrb", "llb"):
        raise ValueError(f"未知新浪报表 source: {source}")
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    # fengthrottle 在导入时读取 FENG_HTTP_UA，须先设置再导入
    os.environ.setdefault("FENG_HTTP_UA", _SINA_UA)
    from fengthrottle import cached_get

    params = {"paperCode": sina_code, "source": source, "type": "0", "page": "1", "num": "1000"}
    data, src = cached_get(_SINA_FIN_URL, params=params, ttl=_SINA_CACHE_TTL, timeout=30)

    try:
        result = data["result"]["data"]
    except (KeyError, TypeError):
        raise ValueError(f"新浪接口返回异常（可能被反爬/限流），前 200 字符: {str(data)[:200]}")

    warnings = []
    # 报告期列表（按接口顺序去重）
    periods_raw = [str(x["date_value"]) for x in result.get("report_date", []) if x.get("date_value")]
    seen = set()
    periods = [p for p in periods_raw if not (p in seen or seen.add(p))]
    # 报告期按日期降序（最新在前）；解析不出日期的排末尾
    def _period_key(p):
        d = re.sub(r"\D", "", p)
        if len(d) >= 8:
            try:
                return (int(d[:4]), int(d[4:6]), int(d[6:8]))
            except ValueError:
                return (9999, 12, 31)
        return (0, 0, 0)
    periods.sort(key=_period_key, reverse=True)
    if latest:
        periods = periods[:latest]

    report_list = result.get("report_list", {})
    out, meta = {}, {}
    dup_names, skip_nonnum = [], 0
    for p in periods:
        rl = report_list.get(p) or {}
        row = {}
        for it in rl.get("data") or []:
            title = str(it.get("item_title") or "").strip()
            if not title:
                continue
            if title in row:  # 重复科目保留首个（同 akshare keep='first'）
                if title not in dup_names:
                    dup_names.append(title)
                continue
            fv = _sina_num(it.get("item_value"))
            if fv is None:
                skip_nonnum += 1
                continue
            row[title] = fv
        out[p] = row
        meta[p] = {  # PIT 关键：公告日期 + 审计状态
            "publish_date": rl.get("publish_date"),
            "is_audit": rl.get("is_audit"),
            "data_source": rl.get("data_source"),
            "currency": rl.get("rCurrency"),
            "rType": rl.get("rType"),
            "update_time": _sina_ts_iso(rl.get("update_time")),
        }
    if dup_names:
        warnings.append(f"重复科目已保留首个: {', '.join(dup_names[:5])}{'…' if len(dup_names) > 5 else ''}")
    if skip_nonnum:
        warnings.append(f"跳过非数值科目 {skip_nonnum} 项")
    if not out:
        raise ValueError("该报表无数据（新浪无此报表或代码有误）")
    return out, meta, warnings, src


def _apply_latest(payload: dict, latest):
    """对已生成的 payload 按 --latest 截断各报表期（缓存命中/回退路径同样生效）。
    报表期在拉取时已按日期降序排列，dict 保序，直接取前 N 个即可。"""
    if not latest:
        return payload
    for stmt in ("balance", "income", "cashflow"):
        d = payload.get(stmt) or {}
        if not d:
            continue
        keep = list(d.keys())[:latest]
        payload[stmt] = {k: d[k] for k in keep}
        m = (payload.get("meta") or {}).get(stmt) or {}
        if m:
            payload.setdefault("meta", {})[stmt] = {k: m[k] for k in keep if k in m}
    return payload


def _cmd_sina_financials(ticker: str, latest=None):
    """--sina-financials 入口：新浪 A 股三大报表 JSON（PIT：公告日期/审计状态）。

    缓存：data/cache/sina_fin_<TICKER>.json（TTL 1 天，gitignored）。
    网络失败 → {"error": ...} + 提示，不崩溃；有陈旧本地缓存则回退并标注。
    """
    sina_code = _to_sina_code(ticker)
    if not sina_code:
        print(json.dumps({
            "error": f"无法把 {ticker} 转换为新浪代码（仅 A 股支持：600036.SS / 000001.SZ / 600036）",
            "hint": "--sina-financials 仅适用于 A 股；美股/港股请用默认模式",
        }, indent=2, ensure_ascii=False))
        sys.exit(1)

    cache_path = os.path.join(_PROJ_ROOT, "data", "cache", f"sina_fin_{ticker}.json")

    # 1) 本地缓存命中（TTL 1 天）
    if os.path.exists(cache_path):
        try:
            with open(cache_path, encoding="utf-8") as fh:
                cached = json.load(fh)
            if time.time() - cached.get("fetched_ts", 0) < _SINA_CACHE_TTL:
                print(json.dumps(_apply_latest(cached["data"], latest), indent=2, ensure_ascii=False))
                return
        except Exception:
            pass

    # 2) 网络拉取（fengthrottle 限流 + TTL 缓存）
    statements, metas, warnings, failed = {}, {}, [], []
    for key, label, src_key in _SINA_STATEMENTS:
        try:
            data, meta, warns, _src = _sina_statement(sina_code, src_key, latest=latest)
            statements[key] = data
            metas[key] = meta
            warnings.extend(warns)
        except Exception as e:
            failed.append(label)
            warnings.append(f"{label} 获取失败: {str(e)[:200]}")

    if failed:
        # 3) 网络失败 → 回退陈旧本地缓存；无缓存则明确报错
        if os.path.exists(cache_path):
            try:
                with open(cache_path, encoding="utf-8") as fh:
                    stale = json.load(fh)
                stale["data"]["warnings"] = warnings + ["已回退本地陈旧缓存（注意数据时效，非本次实时拉取）"]
                print(json.dumps(_apply_latest(stale["data"], latest), indent=2, ensure_ascii=False))
                return
            except Exception:
                pass
        print(json.dumps({
            "error": f"新浪财务数据获取失败（{'、'.join(failed)}）",
            "hint": "网络不可达或被新浪反爬。请求已走 fengthrottle 限流+缓存，可稍后重试；"
                    "亦可用 FENG_HTTP_UA 环境变量自定义 UA 规避风控",
            "warnings": warnings,
        }, indent=2, ensure_ascii=False))
        sys.exit(1)

    payload = {
        "ticker": ticker,
        "sina_code": sina_code,
        "balance": statements.get("balance", {}),
        "income": statements.get("income", {}),
        "cashflow": statements.get("cashflow", {}),
        "meta": {
            "balance": metas.get("balance", {}),
            "income": metas.get("income", {}),
            "cashflow": metas.get("cashflow", {}),
        },
        "data_source": "sina_finance — quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022",
        "currency": "以各报告期 meta.<报表>.<报告期>.currency(rCurrency) 为准",
        "fetched_at": datetime.now().isoformat(),
        "warnings": list(dict.fromkeys(warnings)),
    }
    # 写本地缓存
    try:
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump({"fetched_ts": time.time(), "ttl": _SINA_CACHE_TTL, "data": payload},
                      fh, ensure_ascii=False, indent=2)
    except Exception as e:
        payload["warnings"].append(f"缓存写入失败: {e}")
    print(json.dumps(payload, indent=2, ensure_ascii=False))


# ─── 东财涨停池 API（5 池：涨停/强势/炸板/跌停/昨日涨停）────────────
# 源码参考: RockyZSU-Stock/datahub/dfcf_hot_block.py
# API 全部走 push2ex.eastmoney.com，ut 参数需从东财 JS 动态获取

import urllib.request as _urllib_req

_ZT_HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "zh,en;q=0.9,en-US;q=0.8,zh-CN;q=0.7",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "Pragma": "no-cache",
    "Referer": "https://quote.eastmoney.com/ztb/detail",
    "Sec-Fetch-Dest": "script",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "same-site",
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/138.0.0.0 Safari/537.36"),
    "sec-ch-ua": '"Chromium";v="138", "Google Chrome";v="138", "Not=A?Brand";v="8"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}

# 东财 ut token 缓存（进程内有效，避免重复请求）
_zt_ut_cache = None
_zt_ut_last_fetch = 0


def _zt_get_ut():
    """获取东财涨停板页面的 ut 参数（动态 JS 里的 token）。
    缓存 5 分钟避免频繁请求。"""
    global _zt_ut_cache, _zt_ut_last_fetch
    now = time.time()
    if _zt_ut_cache and (now - _zt_ut_last_fetch) < 300:
        return _zt_ut_cache
    url = "https://quote.eastmoney.com/ztb/newstatic/build/detail.js"
    try:
        req = _urllib_req.Request(url, headers=_ZT_HEADERS)
        with _urllib_req.urlopen(req, timeout=10) as r:
            text = r.read().decode("utf-8", errors="ignore")
        m = re.search(r'\{ut:"(\w+)",', text)
        if m:
            _zt_ut_cache = m.group(1)
            _zt_ut_last_fetch = now
            return _zt_ut_cache
    except Exception:
        pass
    # 回退：返回 None，API 可能不需要 ut（但数据可能不全）
    return _zt_ut_cache


def _zt_http_get(url, params, timeout=15):
    """东财涨停池统一 HTTP GET，带限流（每次请求间隔 0.5s）。"""
    time.sleep(0.5)  # 简易限流：东财 API 有频率限制
    query = "&".join(f"{k}={v}" for k, v in params.items())
    full_url = f"{url}?{query}"
    req = _urllib_req.Request(full_url, headers=_ZT_HEADERS)
    with _urllib_req.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _zt_format_time(t):
    """将封板时间整数（如 93012）格式化为 HH:MM:SS 字符串。"""
    s = str(int(t)).zfill(6)
    return f"{s[:2]}:{s[2:4]}:{s[4:6]}"


def _zt_parse_ztstats(x):
    """解析涨停统计字段：{days: N, ct: M} → 'N/M' 格式。"""
    if not x or not isinstance(x, dict):
        return "0/0"
    days = x.get("days", 0)
    ct = x.get("ct", 0)
    return f"{days}/{ct}"


def _zt_pool_fetch(pool_type, date):
    """东财涨停池统一获取逻辑。
    pool_type: zt(涨停) / qs(强势) / zb(炸板) / dt(跌停) / yz(昨日涨停)
    返回 (pool_list, error_msg)"""
    ut = _zt_get_ut()
    # API URL 映射
    url_map = {
        "zt": "https://push2ex.eastmoney.com/getTopicZTPool",
        "qs": "https://push2ex.eastmoney.com/getTopicQSPool",
        "zb": "https://push2ex.eastmoney.com/getTopicZBPool",
        "dt": "https://push2ex.eastmoney.com/getTopicDTPool",
        "yz": "https://push2ex.eastmoney.com/getYesterdayZTPool",
    }
    # 参数映射（各池略有差异）
    params_map = {
        "zt": {"ut": ut, "dpt": "wz.ztzt", "Pageindex": "0",
               "pagesize": "10000", "sort": "fbt:asc", "date": date},
        "qs": {"ut": ut, "dpt": "wz.ztzt", "Pageindex": "0",
               "pagesize": "5000", "sort": "zdp:desc", "date": date},
        "zb": {"ut": ut, "dpt": "wz.ztzt", "Pageindex": "0",
               "pagesize": "5000", "sort": "fbt:asc", "date": date},
        "dt": {"ut": ut, "dpt": "wz.ztzt", "Pageindex": "0",
               "pagesize": "10000", "sort": "fund:asc", "date": date},
        "yz": {"ut": ut, "dpt": "wz.ztzt", "Pageindex": "0",
               "pagesize": "5000", "sort": "zs:desc", "date": date},
    }
    url = url_map.get(pool_type)
    params = params_map.get(pool_type)
    if not url or not params:
        return [], f"未知池类型: {pool_type}"
    try:
        data = _zt_http_get(url, params)
    except Exception as e:
        return [], f"东财 API 请求失败: {e}"
    pool = (data.get("data") or {}).get("pool") or []
    return pool, None


def _cmd_zt_pools(date=None, pools=None, output_json=True):
    """--zt-pools 入口：获取东财涨停池数据。

    参数:
        date: 交易日 YYYYMMDD，默认今天
        pools: 要获取的池类型列表，默认全部 [zt,qs,zb,dt,yz]
        output_json: 是否输出 JSON
    """
    if not date:
        date = datetime.now().strftime("%Y%m%d")
    if not pools:
        pools = ["zt", "qs", "zb", "dt", "yz"]
    pool_names = {
        "zt": "涨停股池", "qs": "强势股池", "zb": "炸板股池",
        "dt": "跌停股池", "yz": "昨日涨停股池",
    }
    result = {
        "date": date,
        "fetched_at": datetime.now().isoformat(),
        "data_source": "eastmoney push2ex API (via RockyZSU-Stock)",
        "pools": {},
    }
    for p in pools:
        name = pool_names.get(p, p)
        pool_data, err = _zt_pool_fetch(p, date)
        if err:
            result["pools"][p] = {"name": name, "error": err, "count": 0}
            continue
        # 格式化每条记录为可读 dict
        items = []
        for item in pool_data:
            row = {}
            # 通用字段
            code = str(item.get("c", "")).zfill(6)  # 代码
            row["代码"] = code
            row["名称"] = item.get("n", "")  # 名称
            price = item.get("p", 0) / 1000  # 最新价（API 返回值除以 1000）
            row["最新价"] = round(price, 2) if price else None
            row["涨跌幅"] = round(item.get("zdp", 0) / 100, 2) if item.get("zdp") else None
            row["成交额"] = item.get("amount", 0)  # 成交额（元）
            row["流通市值"] = item.get("ltsz", 0)  # 流通市值
            row["总市值"] = item.get("tshare", 0)  # 总市值
            row["换手率"] = round(item.get("hs", 0) / 100, 2) if item.get("hs") else None
            row["所属行业"] = item.get("hybk", "")  # 行业板块
            row["涨停统计"] = _zt_parse_ztstats(item.get("zttj"))
            # 涨停股池特有
            if p == "zt":
                row["连板数"] = item.get("lbc", 0)
                fbt = item.get("fbt", 0)
                row["首次封板时间"] = _zt_format_time(fbt) if fbt else None
                lbt = item.get("lbt", 0)
                row["最后封板时间"] = _zt_format_time(lbt) if lbt else None
                row["封板资金"] = item.get("fund", 0)
                row["炸板次数"] = item.get("zbc", 0)
            # 强势股池特有
            elif p == "qs":
                row["涨停价"] = round(item.get("lsp", 0) / 1000, 2) if item.get("lsp") else None
                row["涨速"] = round(item.get("zspeed", 0) / 100, 2) if item.get("zspeed") else None
                is_new_high = item.get("sinh", 0)
                row["是否新高"] = "是" if is_new_high == 1 else "否"
                row["量比"] = round(item.get("lg", 0) / 100, 2) if item.get("lg") else None
                reason_map = {1: "60日新高", 2: "近期多次涨停", 3: "60日新高且近期多次涨停"}
                row["入选理由"] = reason_map.get(item.get("sinh"), "未知")
            # 炸板股池特有
            elif p == "zb":
                row["涨停价"] = round(item.get("lsp", 0) / 1000, 2) if item.get("lsp") else None
                fbt = item.get("fbt", 0)
                row["首次封板时间"] = _zt_format_time(fbt) if fbt else None
                row["炸板次数"] = item.get("zbc", 0)
                row["振幅"] = round(item.get("amp", 0) / 100, 2) if item.get("amp") else None
                row["涨速"] = round(item.get("zspeed", 0) / 100, 2) if item.get("zspeed") else None
            # 跌停股池特有
            elif p == "dt":
                row["动态市盈率"] = round(item.get("pe", 0) / 100, 2) if item.get("pe") else None
                row["封单资金"] = item.get("fund", 0)
                lbt = item.get("lbt", 0)
                row["最后封板时间"] = _zt_format_time(lbt) if lbt else None
                row["板上成交额"] = item.get("hsbz", 0)
                row["连续跌停"] = item.get("lbc", 0)
                row["开板次数"] = item.get("zbc", 0)
            # 昨日涨停股池特有
            elif p == "yz":
                row["涨停价"] = round(item.get("lsp", 0) / 1000, 2) if item.get("lsp") else None
                row["涨速"] = round(item.get("zspeed", 0) / 100, 2) if item.get("zspeed") else None
                row["振幅"] = round(item.get("amp", 0) / 100, 2) if item.get("amp") else None
                fbt = item.get("fbt", 0)
                row["昨日封板时间"] = _zt_format_time(fbt) if fbt else None
                row["昨日连板数"] = item.get("lbc", 0)
            items.append(row)
        result["pools"][p] = {"name": name, "count": len(items), "stocks": items}
    print(json.dumps(result, indent=2, ensure_ascii=False))


# ─── 腾讯基金 NAV 估算 API ───────────────────────────────────────
# 源码参考: RockyZSU-Stock/fund/fund_info_spider.py
# 主源: qt.gtimg.cn/q=jj{code}（稳定，返回基金名称/净值/涨跌幅）
# 备源: web.ifzq.gtimg.cn getSsgz（历史净值序列，当前可能离线）

_FUND_NAV_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/138.0.0.0 Safari/537.36")


def _fund_nav_fetch_qt(fund_code):
    """通过 qt.gtimg.cn 获取基金净值（主源）。
    返回格式: v_jj{code}="code~name~?~?~?~nav~acc_nav~chg%~date~"
    字段（~分隔）: 0=代码 1=名称 2-4=占位 5=单位净值 6=累计净值 7=涨跌幅 8=日期
    """
    url = f"http://qt.gtimg.cn/q=jj{fund_code}"
    try:
        req = _urllib_req.Request(url, headers={"User-Agent": _FUND_NAV_UA})
        with _urllib_req.urlopen(req, timeout=12) as r:
            body = r.read().decode("gbk", "ignore")
    except Exception as e:
        return {"fund_code": fund_code, "error": f"腾讯 qt.gtimg.cn 请求失败: {e}"}
    # 解析: v_jj160137="160137~南方中证互联网...~0.0~0.0~~1.79~1.79~-0.4~2026-09-03~";
    m = re.search(r'="(.+)"', body)
    if not m:
        return {"fund_code": fund_code, "error": f"腾讯 qt.gtimg.cn 无匹配数据"}
    fields = m.group(1).split("~")
    if len(fields) < 9:
        return {"fund_code": fund_code, "error": f"腾讯 qt.gtimg.cn 字段不足（{len(fields)}个）"}
    def _safe_float(v):
        try:
            f = float(v)
            return f if f == f else None  # 过滤 NaN
        except (ValueError, TypeError):
            return None
    return {
        "fund_code": fields[0],
        "name": fields[1],
        "nav_estimate": _safe_float(fields[5]),
        "nav_accumulated": _safe_float(fields[6]),
        "change_pct": _safe_float(fields[7]),
        "nav_date": fields[8] if fields[8] else None,
        "source": "qt.gtimg.cn (腾讯基金)",
    }


def _fund_nav_fetch_ssgz(fund_code):
    """通过 getSsgz 获取基金历史净值序列（备源，当前可能离线）。
    返回格式: data.data 是 [[日期, 净值], ...] 列表。
    """
    url = f"http://web.ifzq.gtimg.cn/fund/newfund/fundSsgz/getSsgz?app=web&symbol=jj{fund_code}"
    try:
        req = _urllib_req.Request(url, headers={"User-Agent": _FUND_NAV_UA})
        with _urllib_req.urlopen(req, timeout=12) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"fund_code": fund_code, "error": f"腾讯 getSsgz 请求失败: {e}"}
    if data.get("code") != 0 or not data.get("data"):
        return {"fund_code": fund_code, "error": f"getSsgz 接口离线或无数据（code={data.get('code')}）"}
    fund_data = data["data"]
    # 历史净值: fund_data.data 是 [[日期str, 净值float], ...]
    history = None
    if isinstance(fund_data, list):
        history = fund_data
    elif isinstance(fund_data, dict):
        inner = fund_data.get("data")
        history = inner if isinstance(inner, list) else None
    if not history:
        return {"fund_code": fund_code, "error": "getSsgz 无法解析净值历史"}
    last = history[-1]
    return {
        "fund_code": fund_code,
        "nav_estimate": float(last[1]) if len(last) > 1 and last[1] else None,
        "nav_date": last[0] if len(last) > 0 else None,
        "history_count": len(history),
        "recent_nav": [{"date": h[0], "nav": float(h[1]) if h[1] else None}
                       for h in (history[-5:] if len(history) >= 5 else history)
                       if len(h) > 1],
        "source": "web.ifzq.gtimg.cn getSsgz (备源)",
    }


def _fund_nav_fetch(fund_code):
    """获取单只基金的实时估算净值。主源 qt.gtimg.cn，备源 getSsgz。

    返回 dict: {fund_code, name, nav_estimate, nav_date, ...}
    """
    if not fund_code or not fund_code.isdigit():
        return {"fund_code": fund_code, "error": f"基金代码格式错误: {fund_code}"}
    # 主源: qt.gtimg.cn
    result = _fund_nav_fetch_qt(fund_code)
    if "error" not in result:
        result["updated_at"] = datetime.now().isoformat()
        return result
    # 备源: getSsgz
    fallback = _fund_nav_fetch_ssgz(fund_code)
    fallback["updated_at"] = datetime.now().isoformat()
    if "error" not in fallback:
        fallback["_fallback"] = True
        return fallback
    # 两个源都失败
    return {
        "fund_code": fund_code,
        "error": f"主源和备源均失败: {result.get('error')} / {fallback.get('error')}",
        "updated_at": datetime.now().isoformat(),
    }


def _cmd_fund_nav(fund_codes, output_json=True):
    """--fund-nav 入口：获取腾讯基金实时估算净值。

    参数:
        fund_codes: 基金代码列表（如 160137 005827）
    """
    if not fund_codes:
        print(json.dumps({"error": "用法: fengdata.py --fund-nav CODE1 [CODE2 ...]"}, indent=2))
        sys.exit(1)
    results = []
    for code in fund_codes:
        # 去除可能的前缀（如 jj160137）
        clean = re.sub(r"^(jj|JJ)", "", code.strip())
        info = _fund_nav_fetch(clean)
        results.append(info)
        time.sleep(0.3)  # 简易限流
    payload = {
        "count": len(results),
        "fetched_at": datetime.now().isoformat(),
        "funds": results,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


# ─── Mode dispatch & main ───────────────────────────────────────

# All available modes
MODE_FUNCS = {
    "price": ("price", _futu_get_price, _yf_get_price),
    "financials": ("financials", _futu_get_financials, _yf_get_financials),
    "valuation": ("valuation", _futu_get_valuation, None),
    "shareholders": ("shareholders", _futu_get_shareholders, None),
    "analysts": ("analysts", _futu_get_analysts, None),
    "corp-actions": ("corp_actions", _futu_get_corp_actions, None),
    "profile": ("profile", _futu_get_profile, None),
    "revenue": ("revenue", _futu_get_revenue, None),
}
_ALL_MODES = list(MODE_FUNCS.keys())


def main():
    # Special mode: batch-update holdings prices
    if len(sys.argv) >= 2 and sys.argv[1] == "--holdings-update":
        return _update_holdings_prices()

    # Special mode: real-time FX (no ticker needed)
    if len(sys.argv) >= 2 and (sys.argv[1].lower() in ("fx", "FX") or
                               ("--mode" in sys.argv and "fx" in [a.lower() for a in sys.argv])):
        return _cmd_fx()

    # Sina A股三大报表（PIT：公告日期+审计状态）—— 独立入口，不影响既有模式
    if "--sina-financials" in sys.argv:
        if len(sys.argv) < 2 or sys.argv[1].startswith("-"):
            print(json.dumps({"error": "用法: fengdata.py <TICKER> --sina-financials [--latest N]"
                                      "（TICKER 如 600036.SS / 000001.SZ）"}, indent=2, ensure_ascii=False))
            sys.exit(1)
        ticker = sys.argv[1].upper()
        latest = None
        rest = sys.argv[2:]
        for i, a in enumerate(rest):
            if a == "--latest":
                if i + 1 < len(rest):
                    try:
                        latest = int(rest[i + 1])
                    except ValueError:
                        print(json.dumps({"error": f"--latest 需要整数，收到: {rest[i+1]}"},
                                          indent=2, ensure_ascii=False))
                        sys.exit(1)
            elif a.startswith("--latest="):
                try:
                    latest = int(a.split("=", 1)[1])
                except ValueError:
                    print(json.dumps({"error": f"--latest 需要整数，收到: {a}"},
                                      indent=2, ensure_ascii=False))
                    sys.exit(1)
        if latest is not None and latest <= 0:
            print(json.dumps({"error": f"--latest 需为正整数: {latest}"}, indent=2, ensure_ascii=False))
            sys.exit(1)
        return _cmd_sina_financials(ticker, latest)

    # 东财涨停池（5 池：涨停/强势/炸板/跌停/昨日涨停）
    if "--zt-pools" in sys.argv or (len(sys.argv) > 1 and sys.argv[1].lower() == "zt-pools"):
        zt_date = None
        zt_pools = None
        rest = sys.argv[2:] if sys.argv[1].lower() == "zt-pools" else sys.argv[1:]
        # 过滤掉 --zt-pools 本身
        rest = [a for a in rest if a != "--zt-pools"]
        i = 0
        while i < len(rest):
            a = rest[i]
            if a == "--date" and i + 1 < len(rest):
                zt_date = rest[i + 1]
                i += 2
            elif a.startswith("--date="):
                zt_date = a.split("=", 1)[1]
                i += 1
            elif a == "--pools" and i + 1 < len(rest):
                zt_pools = rest[i + 1].split(",")
                i += 2
            elif a.startswith("--pools="):
                zt_pools = a.split("=", 1)[1].split(",")
                i += 1
            else:
                i += 1
        return _cmd_zt_pools(date=zt_date, pools=zt_pools)

    # 腾讯基金实时估算净值
    if "--fund-nav" in sys.argv:
        nav_codes = []
        rest = sys.argv[1:]
        i = 0
        while i < len(rest):
            a = rest[i]
            if a == "--fund-nav":
                i += 1
                # 收集后面所有非参数值作为基金代码
                while i < len(rest) and not rest[i].startswith("-"):
                    nav_codes.append(rest[i])
                    i += 1
            else:
                i += 1
        return _cmd_fund_nav(nav_codes)

    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: fengdata.py TICKER [--mode MODE] [--backend auto|futu|yfinance]; OR fengdata.py fx; OR fengdata.py zt-pools [--date YYYYMMDD] [--pools zt,qs,zb,dt,yz]; OR fengdata.py --fund-nav CODE1 [CODE2 ...]"}, indent=2))
        sys.exit(1)

    ticker = sys.argv[1].upper()
    selected_modes = _ALL_MODES   # default: all
    backend = "auto"
    i = 2
    while i < len(sys.argv):
        a = sys.argv[i]
        if a == "--mode":
            i += 1
            if i < len(sys.argv):
                m = sys.argv[i].lower()
                if m == "all":
                    selected_modes = _ALL_MODES
                elif m in MODE_FUNCS:
                    selected_modes = [m]
                else:
                    print(json.dumps({"error": f"Unknown mode: {m}. Available: {', '.join(_ALL_MODES)}"}, indent=2))
                    sys.exit(1)
        elif a == "--backend":
            i += 1
            if i < len(sys.argv):
                backend = sys.argv[i]
        elif a.startswith("--backend="):
            backend = a.split("=", 1)[1]
        i += 1

    result = {"ticker": ticker, "fetched_at": datetime.now().isoformat(), "backend": backend}
    futu_ok = False

    try_futu = (backend in ("auto", "futu"))
    if try_futu:
        try:
            futu_ok = _check_futu()
        except Exception:
            futu_ok = False

    sources = []
    if futu_ok:
        sources.append({
            "source": "futu_opend",
            "type": "multi-mode",
            "fetched_at": datetime.now().isoformat(),
            "host": "127.0.0.1:11111",
            "notes": "Futu OpenD primary backend",
        })

    # Collect all warnings across modes
    all_warnings = []

    for mode_key in selected_modes:
        key_name, futu_fn, yf_fn = MODE_FUNCS[mode_key]
        mode_result = None

        if futu_ok and futu_fn:
            try:
                mode_result = futu_fn(ticker)
            except Exception as e:
                mode_result = {"error": f"Futu {mode_key} failed: {str(e)[:100]}"}

        # Fallback
        if (not mode_result or "error" in mode_result) and yf_fn and backend != "futu":
            try:
                mode_result = yf_fn(ticker)
                if mode_result and "error" not in mode_result:
                    mode_result["_fallback"] = True
                    sources.append({
                        "source": "yfinance",
                        "type": mode_key,
                        "fetched_at": datetime.now().isoformat(),
                        "url": f"https://finance.yahoo.com/quote/{_to_yahoo_code(ticker)}",
                        "notes": f"BACKUP for {mode_key}",
                    })
            except Exception as e:
                mode_result = {"error": f"yfinance {mode_key} also failed: {str(e)[:100]}"}

        if mode_result and "error" not in mode_result:
            # Collect warnings
            w = mode_result.pop("_warnings", None)
            if w:
                all_warnings.extend(w)
            result[key_name] = mode_result

    if all_warnings:
        result["_warnings"] = list(dict.fromkeys(all_warnings))  # dedup, preserve order
    if sources:
        # Dedup sources
        seen = set()
        unique_sources = []
        for s in sources:
            tag = s.get("source", "") + s.get("type", "")
            if tag not in seen:
                seen.add(tag)
                unique_sources.append(s)
        result["data_sources"] = unique_sources

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
