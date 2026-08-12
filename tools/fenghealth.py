#!/usr/bin/env python3
"""fenghealth — 公司体检报告。自动化: 盈利能力趋势/成长性/估值位置/会计质量/关键风险。

Usage:
    python fenghealth.py 0700.HK              # 完整体检报告
    python fenghealth.py 0700.HK --summary    # 精简版(仅结论+灯色)
    python fenghealth.py --list-checks        # 列出会计质量检查项

Dependencies: yfinance, pandas, numpy
"""

import json, os, sys
from datetime import datetime
from typing import Any

os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

import yfinance as yf
import pandas as pd
import numpy as np


# ── helpers ──────────────────────────────────────────────────────────

def _light_g(bad: bool, warn: bool = False) -> str:
    """GREEN / YELLOW / RED from boolean flags."""
    if bad: return "RED"
    if warn: return "YELLOW"
    return "GREEN"

def _pct(v: float | None) -> float | None:
    """Format ratio as percentage."""
    return round(v * 100, 1) if v is not None else None

def _trend(arr: list[float]) -> str:
    """Assess trend direction. yfinance returns newest-first, so reverse for chronology."""
    if len(arr) < 3:
        return "insufficient_data"
    rev = list(reversed(arr))  # chronological: oldest → newest
    x = np.arange(len(rev))
    slope = np.polyfit(x, rev, 1)[0]
    rel = slope / (abs(rev[0]) + 1e-8)
    if rel > 0.05: return "improving"
    if rel < -0.05: return "declining"
    return "stable"

def _cagr(values: list[float]) -> float | None:
    """CAGR from annual values. yfinance returns newest-first; oldest is values[-1]."""
    if len(values) < 2 or values[-1] <= 0:
        return None
    years = len(values) - 1
    if years < 1:
        return None
    # values[0]=newest, values[-1]=oldest
    return round((values[0] / values[-1]) ** (1 / years) - 1, 4)


# ── data fetcher ─────────────────────────────────────────────────────

def _fetch(ticker: str) -> dict:
    """Fetch all data needed for health report."""
    t = yf.Ticker(ticker)
    info = t.info or {}

    # Price history (5 years for historical percentile)
    hist = t.history(period="max")
    if hist.empty:
        return {"error": f"No price data for {ticker}"}

    c = hist["Close"]  # auto_adjust=True (default), 前复权价格
    price = float(c.iloc[-1])
    high_52w = float(hist["High"].tail(252).max())
    low_52w = float(hist["Low"].tail(252).min())

    # Financial statements (annual, ~5 years)
    fs = t.financials
    cf = t.cashflow
    bs = t.balance_sheet

    def _series(df, key, n=5):
        if df is None or df.empty or key not in df.index:
            return []
        vals = []
        for c in df.columns[:n]:
            v = df.loc[key, c]
            if pd.notna(v):
                vals.append(float(v))
        return vals

    rev = _series(fs, "Total Revenue")
    ni = _series(fs, "Net Income")
    op = _series(fs, "Operating Income")
    gp = _series(fs, "Gross Profit")
    rd = _series(fs, "Research And Development")
    da = _series(fs, "Depreciation And Amortization")
    interest = _series(fs, "Interest Expense")
    tax = _series(fs, "Income Tax")

    fcf = _series(cf, "Free Cash Flow")
    ocf = _series(cf, "Operating Cash Flow")
    capex = _series(cf, "Capital Expenditure")
    sbc = _series(cf, "Stock Based Compensation")
    # Receivables change (Cash From Operating Activities 内的项目)
    ar_change = _series(cf, "Change In Accounts Receivable")
    inv_change = _series(cf, "Change In Inventory")

    cash = _series(bs, "Cash And Cash Equivalents")
    debt = _series(bs, "Total Debt")
    equity = _series(bs, "Stockholders Equity")
    goodwill = _series(bs, "Goodwill")
    intangibles = _series(bs, "Intangible Assets")
    receivables = _series(bs, "Accounts Receivable")
    inventory = _series(bs, "Inventory")
    ppe = _series(bs, "Property Plant And Equipment")

    # Margins (computed)
    gross_margins = []
    op_margins = []
    ni_margins = []
    for i in range(max(len(gp), len(rev))):
        r = rev[i] if i < len(rev) else None
        g = gp[i] if i < len(gp) else None
        o = op[i] if i < len(op) else None
        n = ni[i] if i < len(ni) else None
        if r and r > 0:
            if g: gross_margins.append(round(g / r * 100, 1))
            if o: op_margins.append(round(o / r * 100, 1))
            if n: ni_margins.append(round(n / r * 100, 1))

    return {
        "ticker": ticker.upper(),
        "name": info.get("shortName") or info.get("longName") or ticker,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "price": price,
        "high_52w": high_52w,
        "low_52w": low_52w,
        "info": info,
        "raw": {
            "rev": rev, "ni": ni, "op": op, "gp": gp,
            "rd": rd, "da": da, "interest": interest, "tax": tax,
            "fcf": fcf, "ocf": ocf, "capex": capex, "sbc": sbc,
            "ar_change": ar_change, "inv_change": inv_change,
            "cash": cash, "debt": debt, "equity": equity,
            "goodwill": goodwill, "intangibles": intangibles,
            "receivables": receivables, "inventory": inventory, "ppe": ppe,
        },
        "gross_margins": gross_margins,
        "op_margins": op_margins,
        "ni_margins": ni_margins,
        "roe": _series(fs, "Net Income")[:len(equity)] if equity else [],
    }

def _roe_series(ni_list: list, eq_list: list) -> list:
    return [round(n / e * 100, 1) for n, e in zip(ni_list, eq_list) if e > 0] if len(ni_list) == len(eq_list) else []


# ── analysis modules ─────────────────────────────────────────────────

def analyze_profitability(d: dict) -> dict:
    """盈利能力分析: ROE趋势, 毛利率, 净利率."""
    raw = d["raw"]
    eq_vs = raw.get("equity", [])
    ni_vs = raw.get("ni", [])
    n = min(len(eq_vs), len(ni_vs))
    roe_series = [round(ni_vs[i] / eq_vs[i] * 100, 1) for i in range(n) if eq_vs[i] > 0] if n > 0 else []

    gm = d.get("gross_margins", [])
    om = d.get("op_margins", [])
    nm = d.get("ni_margins", [])
    roe_current = roe_series[-1] if roe_series else None
    roe_trend = _trend(roe_series) if len(roe_series) >= 3 else "insufficient_data"

    issues = []
    if roe_current is not None and roe_current < 8:
        issues.append(f"ROE({roe_current}%) < 8%, 资本回报效率偏低")
    if roe_trend == "declining":
        issues.append("ROE趋势持续下降")
    if gm and gm[-1] < 20:
        issues.append(f"毛利率({gm[-1]}%) < 20%, 定价能力弱")

    findings = {
        "roe_current_pct": roe_current,
        "roe_series": roe_series,
        "roe_trend": roe_trend,
        "gross_margin_current_pct": gm[-1] if gm else None,
        "gross_margin_trend": _trend(gm) if len(gm) >= 3 else "insufficient_data",
        "op_margin_current_pct": om[-1] if om else None,
        "net_margin_current_pct": nm[-1] if nm else None,
        "issues": issues,
        "light": _light_g(len(issues) >= 2, len(issues) >= 1),
    }
    return findings


def analyze_growth(d: dict) -> dict:
    """成长性分析: 营收CAGR, FCF趋势, 经营现金流趋势."""
    raw = d["raw"]
    rev = raw.get("rev", [])
    fcf = raw.get("fcf", [])
    ocf = raw.get("ocf", [])
    op = raw.get("op", [])

    rev_cagr = _cagr(rev) if len(rev) >= 2 else None
    rev_trend = _trend(rev) if len(rev) >= 3 else "insufficient_data"
    ocf_trend = _trend(ocf) if len(ocf) >= 3 else "insufficient_data"
    fcf_positive = all(v > 0 for v in fcf) if len(fcf) >= 2 else None

    issues = []
    if rev_cagr is not None and rev_cagr < 0.02:
        issues.append(f"营收5年CAGR仅{rev_cagr*100:.1f}%, 基本停滞")
    if rev_trend == "declining":
        issues.append("营收趋势持续下降")
    if fcf_positive is False:
        issues.append("自由现金流在部分年份为负")
    if len(rev) >= 2 and rev[-1] > rev[0]:
        issues.append("5年营收未增长(末 < 首)")

    findings = {
        "revenue_cagr_5y_pct": round(rev_cagr * 100, 1) if rev_cagr else None,
        "revenue_trend": rev_trend,
        "ocf_trend": ocf_trend,
        "ocf_positive": all(v > 0 for v in ocf) if len(ocf) >= 2 else None,
        "fcf_positive_all": fcf_positive,
        "fcf_latest": fcf[-1] if fcf else None,
        "issues": issues,
        "light": _light_g(len(issues) >= 2, len(issues) >= 1),
    }
    return findings


def analyze_valuation(d: dict) -> dict:
    """估值位置: 价格在52周范围的位置, PE/PB current."""
    info = d["info"]
    price = d["price"]
    low = d["low_52w"]
    high = d["high_52w"]

    pct_position = round((price - low) / (high - low) * 100, 1) if high > low else 50.0

    pe = info.get("trailingPE")
    pb = info.get("priceToBook")
    ps = info.get("priceToSalesTrailing12Months")
    fwd_pe = info.get("forwardPE")
    peg = info.get("pegRatio")
    ev_ebitda = info.get("enterpriseToEbitda")
    ps_ttm = info.get("priceToSalesTrailing12Months")

    issues = []
    signals = []

    # PE
    if pe is not None:
        if pe < 10: signals.append(f"PE({pe}) < 10, 可能是价值陷阱或真正便宜")
        elif pe > 40: signals.append(f"PE({pe}) > 40, 估值偏高")
        else: signals.append(f"PE({pe}) 正常范围")

    if pb is not None and pb < 1:
        signals.append(f"PB({pb}) < 1, 破净")
    if fwd_pe and pe and fwd_pe < pe:
        signals.append(f"远期PE({fwd_pe}) < 当前PE({pe}), 市场预期利润增长")

    # 52周位置
    if pct_position < 20:
        signals.append(f"价格在52周低位({pct_position}%)")
    elif pct_position > 80:
        signals.append(f"价格在52周高位({pct_position}%), 追高风险")

    findings = {
        "price_52w_position_pct": pct_position,
        "current_pe": pe,
        "forward_pe": fwd_pe,
        "pb": pb,
        "ps": ps,
        "peg": peg,
        "ev_ebitda": ev_ebitda,
        "signals": signals,
        "issues": issues,
        "light": _light_g(False, pct_position > 90 or (pe or 99) > 50),
    }
    return findings


ACCOUNTING_CHECKS = [
    ("ar_vs_revenue", "应收增速 vs 营收增速", "WARN_IF_RECEIVABLE_FASTER"),
    ("inv_vs_revenue", "存货增速 vs 营收增速", "WARN_IF_INVENTORY_FASTER"),
    ("goodwill_ratio", "商誉/净资产占比", "WARN_IF_OVER_50PCT"),
    ("ocf_vs_ni", "经营现金流 vs 净利润", "WARN_IF_DIVERGING"),
    ("capex_vs_da", "资本开支 vs 折旧摊销", "WARN_IF_CAPEX_ALWAYS_LOWER"),
    ("fcf_consistency", "自由现金流一致性", "WARN_IF_INCONSISTENT"),
    ("debt_ratio", "资产负债率", "WARN_IF_OVER_70PCT"),
]


def analyze_accounting(d: dict) -> dict:
    """会计质量: 7项自动化检查."""
    raw = d["raw"]
    flags = []
    score = 7  # start perfect, deduct

    rev = raw.get("rev", [])
    receivables = raw.get("receivables", [])
    inventory = raw.get("inventory", [])
    equity = raw.get("equity", [])
    goodwill = raw.get("goodwill", [])
    intangibles = raw.get("intangibles", [])
    ni = raw.get("ni", [])
    ocf = raw.get("ocf", [])
    fcf = raw.get("fcf", [])
    capex = raw.get("capex", [])
    da = raw.get("da", [])
    debt = raw.get("debt", [])
    ar_change = raw.get("ar_change", [])

    details = []

    # 1. AR vs Revenue growth alignment (yfinance: newest-first, so [0]/[1] for latest YoY)
    if len(rev) >= 2 and len(receivables) >= 2:
        r_growth = rev[0] / rev[1] - 1 if rev[1] > 0 else 0
        ar_growth = receivables[0] / receivables[1] - 1 if receivables[1] > 0 else 0
        if ar_growth > r_growth * 2 and ar_growth > 0.1:
            flags.append("应收增速远超营收增速, 收入质量存疑")
            score -= 1
            details.append({"check": "ar_vs_revenue", "light": "RED", "detail": f"应收+{ar_growth*100:.0f}% vs 营收+{r_growth*100:.0f}%"})
        else:
            details.append({"check": "ar_vs_revenue", "light": "GREEN", "detail": "正常"})
    else:
        details.append({"check": "ar_vs_revenue", "light": "YELLOW", "detail": "数据不足"})

    # 2. Inventory vs Revenue
    if len(rev) >= 2 and len(inventory) >= 2:
        r_growth = rev[0] / rev[1] - 1 if rev[1] > 0 else 0
        inv_growth = inventory[0] / inventory[1] - 1 if inventory[1] > 0 else 0
        if inv_growth > r_growth * 2 and inv_growth > 0.1:
            flags.append("存货增速远超营收增速, 可能滞销")
            score -= 1
            details.append({"check": "inv_vs_revenue", "light": "RED", "detail": f"存货+{inv_growth*100:.0f}% vs 营收+{r_growth*100:.0f}%"})
        else:
            details.append({"check": "inv_vs_revenue", "light": "GREEN", "detail": "正常"})
    else:
        details.append({"check": "inv_vs_revenue", "light": "YELLOW", "detail": "数据不足"})

    # 3. Goodwill + Intangibles vs Equity
    if equity and (goodwill or intangibles):
        g = (goodwill[-1] if goodwill else 0) + (intangibles[-1] if intangibles else 0)
        e = equity[-1]
        if e > 0 and g / e > 0.5:
            flags.append(f"商誉+无形资产占净资产{g/e*100:.0f}% > 50%")
            score -= 1
            details.append({"check": "goodwill_ratio", "light": "RED", "detail": f"{g/e*100:.0f}% > 50%"})
        elif e > 0 and g / e > 0.3:
            score -= 0
            details.append({"check": "goodwill_ratio", "light": "YELLOW", "detail": f"{g/e*100:.0f}%, 接近警戒线"})
        else:
            details.append({"check": "goodwill_ratio", "light": "GREEN", "detail": f"{(g/e*100 if e>0 else 0):.0f}%, 正常"})
    else:
        details.append({"check": "goodwill_ratio", "light": "GREEN", "detail": "无形/商誉数据不足或无"})

    # 4. OCF vs Net Income divergence
    if len(ocf) >= 2 and len(ni) >= 2:
        ok = True
        for i in range(min(len(ocf), len(ni))):
            if ocf[i] < 0 and ni[i] > 0:
                flags.append(f"经营现金流为负但净利润为正: 利润质量差")
                score -= 1
                details.append({"check": "ocf_vs_ni", "light": "RED", "detail": "OCF为负但NI为正"})
                ok = False
                break
        if ok:
            # Check trend: OCF/NI ratio
            ratios = [ocf[i]/ni[i] if ni[i] != 0 else 0 for i in range(min(len(ocf), len(ni)))]
            avg_ratio = sum(ratios) / len(ratios) if ratios else 0
            if avg_ratio < 0.5:
                flags.append(f"OCF/NI平均仅{avg_ratio:.1f}x, 利润含金量低")
                score -= 1
                details.append({"check": "ocf_vs_ni", "light": "RED", "detail": f"OCF/NI={avg_ratio:.1f}x < 0.5x"})
            else:
                details.append({"check": "ocf_vs_ni", "light": "GREEN", "detail": f"OCF/NI={avg_ratio:.1f}x, 正常"})
    else:
        details.append({"check": "ocf_vs_ni", "light": "YELLOW", "detail": "数据不足"})

    # 5. Capex vs Depreciation
    if len(capex) >= 2 and len(da) >= 2:
        capex_pos = [abs(v) for v in capex]
        ok = True
        for i in range(len(da)):
            c = capex_pos[i] if i < len(capex_pos) else 0
            d = da[i] if i < len(da) else 0
            if d > 0 and c / d < 0.5:
                flags.append("资本开支远低于折旧, 可能维护不足")
                score -= 1
                details.append({"check": "capex_vs_da", "light": "RED", "detail": f"Capex/DA={c/d:.1f}x < 0.5x"})
                ok = False
                break
        if ok:
            details.append({"check": "capex_vs_da", "light": "GREEN", "detail": "正常"})
    else:
        details.append({"check": "capex_vs_da", "light": "YELLOW", "detail": "数据不足"})

    # 6. FCF consistency
    if len(fcf) >= 3:
        neg_years = sum(1 for v in fcf if v < 0)
        if neg_years > len(fcf) / 2:
            flags.append(f"{len(fcf)}年中有{neg_years}年FCF为负")
            score -= 1
            details.append({"check": "fcf_consistency", "light": "RED", "detail": f"{neg_years}/{len(fcf)}年FCF<0"})
        elif neg_years > 0:
            details.append({"check": "fcf_consistency", "light": "YELLOW", "detail": f"{neg_years}/{len(fcf)}年FCF<0"})
        else:
            details.append({"check": "fcf_consistency", "light": "GREEN", "detail": "全部为正"})
    else:
        details.append({"check": "fcf_consistency", "light": "YELLOW", "detail": "数据不足"})

    # 7. Debt ratio
    if debt and equity:
        d = debt[-1] if debt else 0
        e = equity[-1] if equity else 1
        if e > 0 and d / e > 1.5:
            flags.append(f"负债率(D/E={d/e:.1f}x) > 1.5x")
            score -= 1
            details.append({"check": "debt_ratio", "light": "RED", "detail": f"D/E={d/e:.1f}x"})
        elif e > 0 and d / e > 1.0:
            details.append({"check": "debt_ratio", "light": "YELLOW", "detail": f"D/E={d/e:.1f}x"})
        else:
            details.append({"check": "debt_ratio", "light": "GREEN", "detail": f"D/E={d/e:.1f}x"})
    else:
        details.append({"check": "debt_ratio", "light": "YELLOW", "detail": "数据不足"})

    return {
        "score": max(0, score),
        "max_score": 7,
        "flags": flags,
        "details": details,
        "light": _light_g(score <= 3, score <= 5),
    }


def analyze_risks(d: dict, profitability: dict, growth: dict,
                  valuation: dict, accounting: dict) -> list:
    """汇总关键风险."""
    risks = []

    # From profitability
    for i in profitability.get("issues", []):
        risks.append({"category": "profitability", "risk": i})

    # From growth
    for i in growth.get("issues", []):
        risks.append({"category": "growth", "risk": i})

    # From valuation
    for i in valuation.get("issues", []):
        risks.append({"category": "valuation", "risk": i})

    # From accounting
    for f in accounting.get("flags", []):
        risks.append({"category": "accounting", "risk": f})

    # Sector-based
    sector = d.get("sector", "")
    if sector in ("Technology", "科技"):
        raw = d["raw"]
        rd_spend = raw.get("rd", [])
        if rd_spend and len(rd_spend) >= 1:
            rev = raw.get("rev", [])
            if rev and rev[-1] > 0:
                rd_pct = abs(rd_spend[-1]) / rev[-1] * 100
                if rd_pct > 30:
                    risks.append({"category": "tech_risk", "risk": f"研发占营收{rd_pct:.0f}%, 技术迭代风险高"})

    return risks


# ── main ─────────────────────────────────────────────────────────────

def health_report(ticker: str) -> dict:
    """Generate full health report."""
    data = _fetch(ticker)
    if "error" in data:
        return data

    profitability = analyze_profitability(data)
    growth = analyze_growth(data)
    valuation = analyze_valuation(data)
    accounting = analyze_accounting(data)
    risks = analyze_risks(data, profitability, growth, valuation, accounting)

    # Overall light
    lights = [profitability["light"], growth["light"],
              valuation["light"], accounting["light"]]
    light_order = {"GREEN": 0, "YELLOW": 1, "RED": 2}
    overall = max(lights, key=lambda x: light_order.get(x, 0))

    report = {
        "ticker": data["ticker"],
        "company_name": data["name"],
        "sector": data["sector"],
        "industry": data["industry"],
        "report_date": datetime.now().strftime("%Y-%m-%d"),
        "current_price": data["price"],
        "price_52w_high": data["high_52w"],
        "price_52w_low": data["low_52w"],
        "profitability": profitability,
        "growth": growth,
        "valuation": valuation,
        "accounting_quality": accounting,
        "key_risks": risks,
        "overall_light": overall,
    }

    return report


def _safe_print(text: str) -> None:
    """Print with terminal-safe encoding (handles GBK vs UTF-8 mismatch).

    Strips non-ASCII characters for non-UTF-8 terminals to avoid mojibake.
    """
    out = sys.stdout
    enc = out.encoding or "utf-8"
    if enc.lower() in ("utf-8", "utf8"):
        out.write(text + "\n")
    else:
        # Strip or transliterate non-ASCII for GBK/etc terminals
        safe = text.encode(enc, errors="replace").decode(enc)
        out.write(safe + "\n")


def print_summary(report: dict) -> None:
    """Print human-readable summary (ASCII-safe)."""
    t = report.get("ticker", "?")
    name = report.get("company_name", "?")
    light = report.get("overall_light", "?")
    le = {"GREEN": "[G]", "YELLOW": "[Y]", "RED": "[R]"}.get(light, "[?]")

    _safe_print("")
    _safe_print("=" * 60)
    _safe_print(f"  {le} {t} - {name}")
    _safe_print("  " + "=" * 58)
    _safe_print(f"  Price: {report.get('current_price', '?'):.2f}  "
          f"52w: {report.get('price_52w_low', '?'):.0f}-{report.get('price_52w_high', '?'):.0f}")
    _safe_print(f"  Report: {report.get('report_date', '?')}")
    _safe_print(f"  Sector: {report.get('sector', '?')} / {report.get('industry', '?')}")
    _safe_print(f"  Overall: {light}")
    _safe_print("")

    def _le(v):
        return {"GREEN": "[G]", "YELLOW": "[Y]", "RED": "[R]"}.get(v, "[?]")
    def _dl(v):
        return {"GREEN": "[PASS]", "YELLOW": "[WARN]", "RED": "[FAIL]"}.get(v, "[--]")

    def sec(title, fields, lk="light"):
        lv = fields.get(lk, "?")
        _safe_print(f"  {_le(lv)} {title}")
        for k, v in fields.items():
            if k == lk or v is None or isinstance(v, list):
                continue
            if isinstance(v, float):
                _safe_print(f"    {k}: {v:.2f}")
            elif isinstance(v, str):
                _safe_print(f"    {k}: {v}")
        for i in fields.get("issues", []):
            _safe_print(f"    [!] {i}")
        _safe_print("")

    sec("Profitability", report.get("profitability", {}))
    sec("Growth", report.get("growth", {}))
    sec("Valuation", report.get("valuation", {}))

    acct = report.get("accounting_quality", {})
    acct_lv = acct.get("light", "?")
    _safe_print(f"  {_le(acct_lv)} Accounting Quality ({acct.get('score', '?')}/{acct.get('max_score', '?')})")
    for detail in acct.get("details", []):
        _safe_print(f"    {_dl(detail.get('light', ''))} {detail.get('check', '?')}: {detail.get('detail', '')}")
    for f in acct.get("flags", []):
        _safe_print(f"    [FAIL] {f}")
    _safe_print("")

    risks = report.get("key_risks", [])
    if risks:
        _safe_print(f"  [R] Key Risks ({len(risks)})")
        for r in risks:
            _safe_print(f"    - [{r.get('category', '?')}] {r.get('risk', '?')}")
        _safe_print("")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    if "--list-checks" in sys.argv:
        print("Accounting Quality Checks:")
        for key, name, rule in ACCOUNTING_CHECKS:
            print(f"  {key}: {name} ({rule})")
        sys.exit(0)

    ticker = sys.argv[1].upper()
    report = health_report(ticker)

    if "error" in report:
        print(json.dumps(report, indent=2))
        sys.exit(1)

    if "--summary" in sys.argv:
        print_summary(report)
    else:
        print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
