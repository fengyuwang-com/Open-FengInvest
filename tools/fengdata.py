#!/usr/bin/env python3
"""fengdata — Pull stock data: price/MA + financials. Dual-backend: Futu (primary), yfinance (fallback).

Usage:
    python fengdata.py 0700.HK               # all data, auto backend
    python fengdata.py 0700.HK --price       # price + MA only
    python fengdata.py 0700.HK --financials  # financials only
    python fengdata.py 0700.HK --backend futu   # force Futu
    python fengdata.py 0700.HK --backend yfinance  # force yfinance

Backend policy:
    --backend auto (default): try Futu → fallback yfinance
    --backend futu: Futu OpenD only, fail if not available
    --backend yfinance: yfinance only (original behavior)

Dependencies:
    futu-api (primary), yfinance + pandas (fallback)
"""
import json, os, re, sys, traceback
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


def _norm_yf_code(ticker: str) -> str:
    """yfinance 港股代码去前导零：09988.HK → 9988.HK（4 位如 0700.HK 不动）。

    Yahoo 对 5 位港股代码（09988/01024 风格）返回 404，只认 4 位风格。
    """
    t = ticker.upper().strip()
    m = re.match(r'^0(\d{4})\.HK$', t)
    if m:
        return f"{m.group(1)}.HK"
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

def _yf_get_price(ticker: str, years: int = 1) -> dict:
    import yfinance as yf
    import pandas as pd
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
            # ── 主源：Futu OpenD 快照 ──
            price = None
            err = None
            try:
                from futu import OpenQuoteContext, RET_OK
                ctx = OpenQuoteContext(host='127.0.0.1', port=11111)
                ret, snap = ctx.get_market_snapshot([code])
                ctx.close()
                if ret == RET_OK:
                    row = snap.iloc[0] if hasattr(snap, 'iloc') else snap[0]
                    p0 = float(row.get('last_price', 0) if hasattr(row, 'get') else getattr(row, 'last_price', 0))
                    if p0 > 0:
                        price = p0
                    else:
                        err = "Futu zero price"
                else:
                    err = "Futu snapshot failed"
            except Exception as e:
                err = f"Futu: {str(e)[:60]}"
            # ── 回退：yfinance（无 Futu OpenD 环境也能跑，开源版必需）──
            if price is None:
                try:
                    import yfinance as yf
                    hist = yf.Ticker(_norm_yf_code(ticker)).history(period="5d")
                    c = hist["Close"].dropna() if not hist.empty else []
                    if len(c) > 0:
                        price = float(c.iloc[-1])
                    else:
                        err = (err + "; " if err else "") + "yfinance empty"
                except Exception as e:
                    err = (err + "; " if err else "") + f"yf: {str(e)[:60]}"
            if price is None:
                failed.append({"ticker": ticker, "error": err or "no price source"})
                continue
            # Update the holding file
            fpath = os.path.join(holdings_dir, fname)
            with open(fpath, "r", encoding="utf-8") as fh:
                h = json.load(fh)
            old_price = h.get("position", {}).get("current_price", 0)
            pos = h.setdefault("position", {})
            shares = pos.get("shares", 0)
            avg_cost = pos.get("avg_cost", 0)
            pos["current_price"] = price
            pos["market_value"] = price * shares
            pos["unrealized_pl"] = round((price - avg_cost) * shares, 2)
            # 派生字段一并重算（人民币等值，按 meta.fx_rates 快照口径）
            cur = (h.get("currency") or "CNY").upper()
            fx = (h.get("meta") or {}).get("fx_rates") or {}
            rate = 1.0 if cur == "CNY" else fx.get(f"{cur}_CNY")
            if h.get("capital") and rate:
                h["capital"]["market_value_equiv_cny"] = round(pos["market_value"] * rate, 2)
            h.setdefault("meta", {})["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            with open(fpath, "w", encoding="utf-8") as fh:
                json.dump(h, fh, indent=2, ensure_ascii=False)
            updated.append({"ticker": ticker, "old_price": old_price, "new_price": price,
                           "change_pct": round((price / old_price - 1) * 100, 2) if old_price else None})
        except Exception as e:
            failed.append({"ticker": ticker, "error": str(e)[:100]})

    result = {"updated_count": len(updated), "failed_count": len(failed)}
    if updated:
        result["updated"] = updated
    if failed:
        result["failed"] = failed
    print(json.dumps(result, indent=2, default=str))


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

    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: fengdata.py TICKER [--mode MODE] [--backend auto|futu|yfinance]"}, indent=2))
        sys.exit(1)

    ticker = sys.argv[1].upper()
    yf_ticker = _norm_yf_code(ticker)  # yfinance 后端用归一化代码（09988.HK→9988.HK）
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
                mode_result = yf_fn(yf_ticker)
                if mode_result and "error" not in mode_result:
                    mode_result["_fallback"] = True
                    sources.append({
                        "source": "yfinance",
                        "type": mode_key,
                        "fetched_at": datetime.now().isoformat(),
                        "url": f"https://finance.yahoo.com/quote/{_to_yahoo_code(yf_ticker)}",
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
