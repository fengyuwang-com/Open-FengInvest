"""fengquick — 快速股票数据（价格/PE/PB/ROE/市值），输出干净 JSON"""
import json, sys, os, subprocess, re, math

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)

def clean(val):
    """Recursively replace NaN/Infinity with None."""
    if isinstance(val, float):
        return None if (math.isnan(val) or math.isinf(val)) else val
    if isinstance(val, dict):
        return {k: clean(v) for k, v in val.items()}
    if isinstance(val, list):
        return [clean(v) for v in val]
    return val

if len(sys.argv) < 2:
    print(json.dumps({"error": "Usage: fengquick.py <TICKER>"}))
    sys.exit(1)

ticker = sys.argv[1]

# Direct yfinance fetch (reliable, handles NaN cleanly)
script = f"""
import yfinance as yf, json, math
t = yf.Ticker("{ticker}")
info = t.info or {{}}
hist = t.history(period="1y")
price = info.get("regularMarketPrice") or info.get("currentPrice")
prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose")
hist_close = hist["Close"] if not hist.empty else None
if not price and hist_close is not None:
    price = float(hist_close.iloc[-1])
    prev_close = prev_close or (float(hist_close.iloc[-2]) if len(hist_close) > 1 else price)
ma50 = float(hist_close.iloc[-50:].mean()) if hist_close is not None and len(hist_close) >= 50 else None
ma200 = float(hist_close.iloc[-200:].mean()) if hist_close is not None and len(hist_close) >= 200 else None
change_pct = round((price - prev_close) / prev_close * 100, 2) if price and prev_close else None

def c(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)): return None
    return v

roe_val = info.get("returnOnEquity")
if roe_val is not None and isinstance(roe_val, float) and not math.isnan(roe_val):
    roe_pct = round(roe_val * 100, 1)
else:
    roe_pct = None

out = {{
    "ticker": "{ticker}",
    "source": "live",
    "price": c(price),
    "change_pct": change_pct,
    "prev_close": c(prev_close),
    "ma50": c(ma50),
    "ma200": c(ma200),
    "market_cap": c(info.get("marketCap")),
    "trailing_pe": c(info.get("trailingPE")),
    "forward_pe": c(info.get("forwardPE")),
    "pb": c(info.get("priceToBook")),
    "roe_pct": roe_pct,
    "profit_margin_pct": c(info.get("profitMargins")),
    "dividend_yield_pct": c(info.get("dividendYield")),
    "beta": c(info.get("beta")),
    "sector": info.get("sector"),
    "industry": info.get("industry"),
    "short_name": info.get("shortName"),
}}
print(json.dumps(out, ensure_ascii=False))
"""
try:
    r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
    out = r.stdout.strip().split("\n")[-1]
    m = re.search(r'\{[\s\S]*\}', out)
    if m:
        print(m.group(0))
    else:
        print(json.dumps({"error": "No JSON from yfinance", "raw": out[:200]}))
except Exception as e:
    print(json.dumps({"error": str(e)}))
