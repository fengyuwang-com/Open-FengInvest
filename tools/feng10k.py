#!/usr/bin/env python3
"""fengfundamentals — 标准化10-K财报阅读工具

Usage:
    python fengfundamentals.py AAPL              # 最新10-K完整数据
    python fengfundamentals.py AAPL --period 2025 # 指定年份
    python fengfundamentals.py AAPL --tables      # 仅财务报表（不含文字）
    python fengfundamentals.py AAPL --sections    # 仅文字章节
    python fengfundamentals.py AAPL --compact     # 精简输出（默认）
    python fengfundamentals.py AAPL --full        # 完整输出

依赖: edgar
"""

import json, os, re, sys
from datetime import datetime

# ──────────────────────────── edgartools 初始化 ────────────────────────────
try:
    from edgar import Company, set_identity
    set_identity("FengInvest fengfundamentals@fenginvest.com")
    EDGAR_AVAILABLE = True
except ImportError:
    EDGAR_AVAILABLE = False

# ──────────────────────────── hkfilings 可选 ───────────────────────────────
try:
    from hkfilings import HKFilingsClient
    HKFILINGS_AVAILABLE = True
except ImportError:
    HKFILINGS_AVAILABLE = False

# ──────────────────────────── 常量定义 ────────────────────────────

# 关键财务报表概念（标准 US-GAAP 标签）
# 每个概念可指定多个备选 element_id（按优先级）
INCOME_STATEMENT_CONCEPTS = [
    "Revenue",          "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    "Cost of Revenue",  "us-gaap:CostOfRevenue", "us-gaap:CostOfGoodsAndServicesSold",
    "Gross Profit",     "us-gaap:GrossProfit",
    "R&D Expense",      "us-gaap:ResearchAndDevelopmentExpense",
    "SG&A Expense",     "us-gaap:SellingGeneralAndAdministrativeExpense",
    "Operating Income", "us-gaap:OperatingIncomeLoss", "us-gaap:IncomeLossFromOperations",
    "Interest Expense", "us-gaap:InterestExpense", "us-gaap:InterestExpenseDebt",
    "Other Income/(Exp)", "us-gaap:NonoperatingIncomeExpense", "us-gaap:OtherNonoperatingIncomeExpense",
    "Income Before Tax", "us-gaap:IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
    "Income Tax Exp.",   "us-gaap:IncomeTaxExpenseBenefit",
    "Net Income",       "us-gaap:NetIncomeLoss",
    "Basic EPS",        "us-gaap:EarningsPerShareBasic",
    "Diluted EPS",      "us-gaap:EarningsPerShareDiluted",
    "Basic Shares",     "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic",
    "Diluted Shares",   "us-gaap:WeightedAverageNumberOfDilutedSharesOutstanding",
]

BALANCE_SHEET_CONCEPTS = [
    "Cash & Equivalents",       "us-gaap:CashAndCashEquivalentsAtCarryingValue",
    "Short-Term Investments",   "us-gaap:ShortTermInvestments",
    "Accounts Receivable",      "us-gaap:AccountsReceivableNetCurrent",
    "Inventory",                "us-gaap:InventoryNet",
    "Other Current Assets",     "us-gaap:OtherAssetsCurrent",
    "Total Current Assets",     "us-gaap:AssetsCurrent",
    "PP&E (Net)",               "us-gaap:PropertyPlantAndEquipmentNet",
    "Goodwill",                 "us-gaap:Goodwill",
    "Intangible Assets",        "us-gaap:IntangibleAssetsNetExcludingGoodwill",
    "Other Non-Current Assets", "us-gaap:OtherAssetsNoncurrent",
    "Total Assets",             "us-gaap:Assets",
    "Accounts Payable",         "us-gaap:AccountsPayableCurrent",
    "Short-Term Debt",          "us-gaap:ShortTermDebtCurrent",
    "Other Current Liab.",      "us-gaap:OtherLiabilitiesCurrent",
    "Total Current Liab.",      "us-gaap:LiabilitiesCurrent",
    "Long-Term Debt",           "us-gaap:LongTermDebtNoncurrent",
    "Other Non-Current Liab.",  "us-gaap:OtherLiabilitiesNoncurrent",
    "Total Liabilities",        "us-gaap:Liabilities",
    "Common Stock & APIC",      "us-gaap:CommonStockAdditionalPaidInCapital",
    "Retained Earnings",        "us-gaap:RetainedEarningsAccumulatedDeficit",
    "Accum. Other Inc.",        "us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax",
    "Total Equity",             "us-gaap:StockholdersEquity",
]

CASH_FLOW_CONCEPTS = [
    "Net Income",              "us-gaap:NetIncomeLoss",
    "D&A",                     "us-gaap:DepreciationDepletionAndAmortization",
    "Stock-Based Comp.",       "us-gaap:ShareBasedCompensation",
    "Deferred Income Taxes",   "us-gaap:DeferredIncomeTaxExpenseBenefit",
    "Other Non-Cash Items",    "us-gaap:OtherNoncashIncomeExpense",
    "Change in Working Cap.",  "us-gaap:IncreaseDecreaseInOperatingCapital",
    "Operating Cash Flow",     "us-gaap:NetCashProvidedByUsedInOperatingActivities",
    "CapEx",                   "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
    "Free Cash Flow (Calc)",   "us-gaap:FreeCashFlow",
    "Investing Cash Flow",     "us-gaap:NetCashProvidedByUsedInInvestingActivities",
    "Debt Issuance/(Repay)",   "us-gaap:ProceedsFromRepaymentsOfDebt",
    "Share Repurchases",       "us-gaap:PaymentsForRepurchaseOfCommonStock",
    "Dividends Paid",          "us-gaap:PaymentsOfDividends",
    "Financing Cash Flow",     "us-gaap:NetCashProvidedByUsedInFinancingActivities",
]


def _make_concepts_list(flat_list: list) -> list[tuple]:
    """将扁平列表（label, id1, id2, ...）转换为 [(label, [ids]), ...]"""
    result = []
    i = 0
    while i < len(flat_list):
        label = flat_list[i]
        i += 1
        ids = []
        while i < len(flat_list) and ":" in flat_list[i]:
            ids.append(flat_list[i])
            i += 1
        result.append((label, ids if ids else [label]))
    return result

# 构建最终的带备选的概念列表
INCOME_CONCEPTS = _make_concepts_list(INCOME_STATEMENT_CONCEPTS)
BALANCE_CONCEPTS = _make_concepts_list(BALANCE_SHEET_CONCEPTS)
CASHFLOW_CONCEPTS = _make_concepts_list(CASH_FLOW_CONCEPTS)

NARRATIVE_SECTIONS = [
    ("business",     "Item 1.",   "Item 1A."),
    ("risk_factors", "Item 1A.",  "Item 1B."),
    ("cybersec",     "Item 1C.",  "Item 2."),
    ("mdna",         "Item 7.",   "Item 7A."),
    ("market_risk",  "Item 7A.",  "Item 8."),
]


# ──────────────────────────── 核心提取函数 ────────────────────────────

def _fetch_us_filing(ticker: str) -> tuple:
    """获取指定 ticker 的最新 10-K 申报（美股）"""
    company = Company(ticker)
    filings = company.get_filings(form="10-K")
    if not filings:
        raise ValueError(f"No 10-K filings found for {ticker}")
    filing = filings[0]
    cik = company.cik
    return company, filing, cik

def _is_hk_ticker(ticker: str) -> bool:
    """Detect HK stock ticker."""
    return ticker.upper().endswith(".HK")


def _fetch_hk_filing(ticker: str) -> dict:
    """Fetch HK stock fundamentals via hkfilings (optional, needs API key)."""
    api_key = os.environ.get("HKFILINGS_API_KEY")
    if not api_key:
        return {"note": "HKFILINGS_API_KEY not set. Install hkfilings and set the API key for deeper HK data."}

    if not HKFILINGS_AVAILABLE:
        return {"note": "hkfilings not installed. pip install hkfilings"}

    raw_ticker = ticker.replace(".HK", "")
    client = HKFilingsClient(api_key=api_key)

    # Try current year and recent years
    current_year = datetime.now().year
    result = {"ticker": ticker, "source": "hkfilings", "facts": {}}

    for year in range(current_year, current_year - 3, -1):
        try:
            task = client.analyze(ticker=raw_ticker, year=year)
            task = client.wait(task.id, timeout=120)
            if task and task.facts:
                result["facts"][str(year)] = [
                    {"metric": f.metric_key, "value": f.value, "unit": f.unit}
                    for f in task.facts
                ]
                result["years_available"] = list(result["facts"].keys())
        except Exception as e:
            result.setdefault("warnings", []).append(f"Year {year}: {e}")
            continue

    if not result.get("facts"):
        result["note"] = "No HK filing data available (check API key / free tier limit)"
    return result
    """获取指定 ticker 的最新 10-K 申报"""
    company = Company(ticker)
    filings = company.get_filings(form="10-K")
    if not filings:
        raise ValueError(f"No 10-K filings found for {ticker}")
    filing = filings[0]
    cik = company.cik
    return company, filing, cik


def _clean_html(html_text: str) -> str:
    """去除 HTML 标签和实体，保留纯文本"""
    text = re.sub(r"<[^>]+>", " ", html_text)
    text = re.sub(r"&#\d+;|&#x[0-9a-fA-F]+;", " ", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _extract_narrative_section(html: str, section_name: str,
                               start_marker: str, end_marker: str,
                               search_from: int = 0) -> dict:
    """从 HTML 中提取一个文字章节"""
    start_pos = html.find(start_marker, search_from)
    if start_pos < 0:
        return {"section": section_name, "text": None,
                "note": f"Section marker '{start_marker}' not found after {search_from}"}

    # 寻找下一个章节标记
    candidates = [(end_marker, html.find(end_marker, start_pos + len(start_marker)))]
    for pm in ["PART II", "PART III", "PART IV"]:
        pos = html.find(pm, start_pos + len(start_marker))
        if pos > 0:
            candidates.append((pm, pos))

    valid = [(lbl, pos) for lbl, pos in candidates if pos > 0]
    if not valid:
        end_pos = start_pos + min(500000, len(html) - start_pos)
    else:
        end_pos = min(pos for _, pos in valid)

    raw = html[start_pos:end_pos]
    text = _clean_html(raw)

    return {
        "section": section_name,
        "heading": start_marker.strip(),
        "text": text,
        "word_count": len(text.split()),
        "char_count": len(text),
    }


def _extract_narrative_sections(filing, html: str) -> dict:
    """提取所有文字章节（按 PART I / PART II 定位实际内容）"""
    sections = {}

    # 定位 PART 边界
    part1 = html.find("PART I</span>", 100000)  # 跳过封面/TOC
    part2 = html.find("PART II</span>", part1 + 1) if part1 > 0 else -1

    # Part I 中的章节
    if part1 > 0:
        sections["business"] = _extract_narrative_section(
            html, "business", "Item 1.", "Item 1A.", search_from=part1)
        sections["risk_factors"] = _extract_narrative_section(
            html, "risk_factors", "Item 1A.", "Item 1B.", search_from=part1)
        sections["cybersec"] = _extract_narrative_section(
            html, "cybersec", "Item 1C.", "PART II", search_from=part1)

    # Part II 中的章节
    if part2 > 0:
        sections["mdna"] = _extract_narrative_section(
            html, "mdna", "Item 7.", "Item 7A.", search_from=part2)
        sections["market_risk"] = _extract_narrative_section(
            html, "market_risk", "Item 7A.", "Item 8.", search_from=part2)

    return sections


def _get_xbrl_value(facts, concept_ids: list, end_date: str,
                    period_type: str = "duration") -> int | float | None:
    """从 XBRL fact 表中获取某个概念在指定年度末的合并值。

    period_type:
        duration — 期间数据（income/cash flow），使用 period_start/period_end
        instant  — 时点数据（balance sheet），使用 period_instant
    """
    for element_id in concept_ids:
        rows = facts[facts["element_id"] == element_id]
        if rows.empty:
            continue

        if period_type == "instant":
            rows = rows[rows["period_instant"].notna()]
            date_col = "period_instant"
            date_val = end_date
        else:
            rows = rows[rows["period_start"].notna()]
            date_col = "period_end"
            date_val = end_date

        if rows.empty:
            continue

        # 筛选无维度（合并值）
        dim_cols = [c for c in rows.columns if c.startswith("dim_")]
        no_dim = rows[~rows[dim_cols].notna().any(axis=1)]
        if no_dim.empty:
            continue

        # 指定年份
        for_year = no_dim[no_dim[date_col] == date_val]
        if for_year.empty:
            continue

        # 取第一个值（去重）
        val = for_year.iloc[0]["value"]
        if val is None:
            continue

        # 字符串→数值转换
        if isinstance(val, str):
            val = val.replace(",", "").strip()
            try:
                val = float(val) if "." in val else int(val)
            except (ValueError, TypeError):
                return val

        if isinstance(val, (int, float)):
            # 将 float 整数转为 int
            return int(val) if isinstance(val, float) and val == int(val) else val

    return None


def _get_years_from_filing(filing) -> list:
    """从申报中获取可用的财年末尾日期列表"""
    xbrl = filing.xbrl()
    dfs = xbrl.to_pandas()
    facts = dfs["facts"]
    annual_dates = sorted(facts[facts["period_start"].notna()]["period_end"].unique())
    # 返回最多3个年度的日期（最近3年）
    return [d for d in annual_dates if d is not None and d != "nan"][-3:]


def _extract_financial_statements(filing) -> dict:
    """从 XBRL 提取三大财务报表"""
    xbrl = filing.xbrl()
    dfs = xbrl.to_pandas()
    facts = dfs["facts"]

    years = _get_years_from_filing(filing)
    if not years:
        return {"error": "No annual period data found in XBRL"}

    result = {"years": years}

    for stmt_name, concepts_list, period_type in [
        ("income_statement", INCOME_CONCEPTS, "duration"),
        ("balance_sheet", BALANCE_CONCEPTS, "instant"),
        ("cash_flow", CASHFLOW_CONCEPTS, "duration"),
    ]:
        stmt_data = []
        for label, concept_ids in concepts_list:
            row = {"concept": label, "concept_id": concept_ids[0].split(":")[-1]}
            for y in years:
                val = _get_xbrl_value(facts, concept_ids, y, period_type)
                if val is not None:
                    row[f"fy_{y[:4]}"] = val
            stmt_data.append(row)
        result[stmt_name] = stmt_data

    return result


def _compute_ratios(financials: dict) -> dict:
    """从财务报表数据计算关键估值/质量比率"""
    years = financials.get("years", [])

    def _get(stmt: str, concept: str, year_idx: int) -> int | float | None:
        """获取某个数据行的值"""
        for row in financials.get(stmt, []):
            if row["concept"] == concept:
                return row.get(year_idx)
        return None

    ratios = {}
    for y in years:
        year_key = f"fy_{y[:4]}"

        def val(stmt, concept):
            for r in financials.get(stmt, []):
                if r["concept"] == concept:
                    return r.get(year_key)
            return None

        rev = val("income_statement", "Revenue")
        cogs = val("income_statement", "Cost of Revenue")
        gp = val("income_statement", "Gross Profit")
        op_inc = val("income_statement", "Operating Income")
        ni = val("income_statement", "Net Income")
        total_assets = val("balance_sheet", "Total Assets")
        total_equity = val("balance_sheet", "Total Equity")
        total_liab = val("balance_sheet", "Total Liabilities")
        ocf = val("cash_flow", "Operating Cash Flow")
        capex = val("cash_flow", "CapEx")
        shares = val("income_statement", "Basic Shares")
        eps = val("income_statement", "Basic EPS")

        ratios[year_key] = {}

        # 利润率
        if rev and rev != 0:
            ratios[year_key]["gross_margin_pct"] = round((gp / rev) * 100, 2) if gp else None
            ratios[year_key]["operating_margin_pct"] = round((op_inc / rev) * 100, 2) if op_inc else None
            ratios[year_key]["net_margin_pct"] = round((ni / rev) * 100, 2) if ni else None

        # ROE / ROA
        if total_equity and total_equity != 0 and ni is not None:
            ratios[year_key]["roe_pct"] = round((ni / total_equity) * 100, 2)
        if total_assets and total_assets != 0 and ni is not None:
            ratios[year_key]["roa_pct"] = round((ni / total_assets) * 100, 2)

        # 负债率
        if total_assets and total_assets != 0:
            if total_liab is not None:
                ratios[year_key]["debt_ratio_pct"] = round((total_liab / total_assets) * 100, 2)
            if total_equity and total_equity != 0:
                ratios[year_key]["debt_to_equity"] = round(total_liab / total_equity, 2) if total_liab else None

        # 自由现金流
        if ocf is not None and capex is not None:
            fcf = ocf + capex if capex < 0 else ocf - capex
            ratios[year_key]["free_cash_flow"] = fcf

    return ratios


def _to_num(v):
    """将 XBRL 字符串值转为数字"""
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        v = v.replace(",", "").strip()
        try:
            return int(v) if v.isdigit() else float(v)
        except (ValueError, TypeError):
            return v
    return v


def _extract_revenue_breakdown(filing, facts, years: list) -> dict:
    """提取营收细分（按产品/服务 + 按区域）"""
    breakdown = {}
    rev_id = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"

    def _gather(dim_col: str) -> dict:
        data = {}
        rows = facts[(facts["element_id"] == rev_id) & (facts[dim_col].notna())]
        for _, r in rows.iterrows():
            dim_val = r[dim_col].split(":")[-1]
            end = r["period_end"] or r["period_instant"]
            if end and str(end) != "nan":
                v = _to_num(r["value"])
                if isinstance(v, (int, float)):
                    data.setdefault(dim_val, {})[str(end)] = v
        return data

    psv = _gather("dim_srt_ProductOrServiceAxis")
    if psv:
        breakdown["by_product_service"] = psv
    geo = _gather("dim_srt_StatementGeographicalAxis")
    if geo:
        breakdown["by_geography"] = geo
    seg = _gather("dim_us-gaap_StatementBusinessSegmentsAxis")
    if seg:
        breakdown["by_business_segment"] = seg
    return breakdown


def _extract_company_info(company, filing, cik: str) -> dict:
    """提取公司基本信息"""
    xbrl = filing.xbrl()
    info = xbrl.entity_info or {}
    return {
        "ticker": company.tickers[0] if hasattr(company, "tickers") and company.tickers else ticker,
        "company_name": company.name if hasattr(company, "name") else info.get("entity_name"),
        "cik": cik,
        "filing_date": str(filing.filing_date) if filing.filing_date else info.get("reporting_end_date"),
        "fiscal_year_end": str(filing.period_of_report) if filing.period_of_report else info.get("document_period_end_date"),
        "form_type": filing.form,
    }


# ──────────────────────────── 主函数 ────────────────────────────

def extract(ticker: str, mode: str = "compact") -> dict:
    """
    提取指定标的的全面基本面数据。

    mode:
        compact — 仅财务报表+比率+营收细分
        sections — 仅文字章节
        tables   — 仅财务报表
        full     — 全部

    支持 US 和 HK 标的:
        - US: 通过 SEC EDGAR 的 10-K XBRL
        - HK: 通过 hkfilings（可选, 需 HKFILINGS_API_KEY）
    """
    # ── HK branch ──────────────────────────────────────────────────
    if _is_hk_ticker(ticker):
        hk_data = _fetch_hk_filing(ticker)
        hk_data.setdefault("ticker", ticker)
        hk_data.setdefault("fetched_at", datetime.now().isoformat())
        hk_data["data_sources"] = [
            {
                "source": "hkfilings",
                "type": "HKEX annual report NLP",
                "fetched_at": datetime.now().isoformat(),
                "url": f"https://www.hkexnews.hk/listedco/listconews/sehk/{ticker.replace('.HK','')}/",
                "notes": hk_data.get("note", ""),
            }
        ]
        return hk_data

    # ── US branch (EDGAR) ──────────────────────────────────────────
    if not EDGAR_AVAILABLE:
        return {"error": "edgar not installed. pip install edgartools", "ticker": ticker}

    company, filing, cik = _fetch_us_filing(ticker)
    html = filing.html()
    xbrl = filing.xbrl()
    dfs = xbrl.to_pandas()
    facts = dfs["facts"]

    result = {
        "ticker": ticker,
        "company": _extract_company_info(company, filing, cik),
        "fetched_at": datetime.now().isoformat(),
        "data_sources": [
            {
                "source": "SEC EDGAR",
                "type": "10-K XBRL + HTML",
                "url": filing.filing_url if hasattr(filing, "filing_url") else f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
                "fetched_at": datetime.now().isoformat(),
                "notes": f"Latest 10-K for {ticker} via edgartools",
            }
        ],
    }

    if mode in ("full", "sections"):
        sections = _extract_narrative_sections(filing, html)
        result["narrative_sections"] = sections

    if mode in ("full", "compact", "tables"):
        financials = _extract_financial_statements(filing)
        result["financial_statements"] = financials

        ratios = _compute_ratios(financials)
        result["ratios"] = ratios

        years = financials.get("years", [])
        rev_breakdown = _extract_revenue_breakdown(filing, facts, years)
        if rev_breakdown:
            result["revenue_breakdown"] = rev_breakdown

    # 去掉 None 值（用于精简输出）
    if mode != "full":
        result = {k: v for k, v in result.items() if v is not None and v != {}}

    return result


def print_summary(result: dict):
    """打印人类可读的摘要"""
    t = result.get("ticker", "???")
    company = result.get("company", {})
    print(f"\n{'='*60}")
    print(f"  {company.get('company_name', t)} ({t})")
    print(f"  10-K 申报日期: {company.get('filing_date', 'N/A')}")
    print(f"  财年末: {company.get('fiscal_year_end', 'N/A')}")
    print(f"{'='*60}")

    # 财务摘要
    fins = result.get("financial_statements", {})
    if fins:
        years = fins.get("years", [])

        dash30 = "─" * 30
        print(f"\n  ┌─ 损益表（百万美元）{dash30}")
        print(f"  │ {'项目':<30s}", end="")
        for y in years:
            print(f" {y[:7]:>14s}", end="")
        print()

        for row in fins.get("income_statement", []):
            is_eps = "EPS" in row["concept"]
            is_shares = "Shares" in row["concept"]
            vals = []
            for y in years:
                v = row.get(f"fy_{y[:4]}")
                if v is not None and isinstance(v, (int, float)):
                    if is_eps:
                        vals.append(f"{v:>14.2f}")
                    elif is_shares:
                        vals.append(f"{v/1e6:>14,.0f}")
                    else:
                        vals.append(f"{v/1e6:>14,.0f}")
                else:
                    vals.append(f"{'—':>14s}")
            if any(v.strip("—.0 ") != "" for v in vals):
                print(f"  │ {row['concept']:<30s}", "".join(vals))

    # 比率
    ratios = result.get("ratios", {})
    if ratios:
        dash40 = "─" * 40
        print(f"\n  ┌─ 关键比率{dash40}")
        ratio_rows = [
            ("毛利率", "gross_margin_pct"),
            ("营业利润率", "operating_margin_pct"),
            ("净利润率", "net_margin_pct"),
            ("ROE", "roe_pct"),
            ("ROA", "roa_pct"),
            ("负债率", "debt_ratio_pct"),
            ("FCF利润率", "fcf_margin_pct"),
        ]
        for label, key in ratio_rows:
            vals = []
            for yf in sorted(ratios.keys()):
                v = ratios[yf].get(key)
                vals.append(f"{v:>10.1f}%" if v is not None else f"{'—':>10s}")
            if any(v.strip("—% ") for v in vals):
                print(f"  │ {label:<20s}", " | ".join(vals))

    # 营收细分
    rd = result.get("revenue_breakdown", {})
    if rd.get("by_product_service"):
        print(f"\n  ┌─ 营收按产品/服务{dash30}")
        for prod, vals in rd["by_product_service"].items():
            parts = []
            for y in sorted(vals.keys()):
                v = vals[y]
                if isinstance(v, str):
                    v = int(v) if v.isdigit() else float(v.replace(",", ""))
                parts.append(f"{y[:7]}: ${v/1e9:.1f}B")
            print(f"  │ {prod:<30s} {'  '.join(parts)}")

    print()

    print(f"\n  {result['data_sources'][0]['url']}")
    print(f"{'='*60}\n")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    ticker = sys.argv[1].upper()
    mode = "compact"
    for a in sys.argv[2:]:
        if a in ("--full", "--tables", "--sections", "--compact"):
            mode = a.lstrip("--")

    try:
        result = extract(ticker, mode)
        # JSON 到 stdout（机器可读）
        sys.stdout.write(json.dumps(result, indent=2, default=str) + "\n")
        sys.stdout.flush()
        # 摘要到 stderr（人类可读，不干扰管道）
        import io
        buf = io.StringIO()
        _old_stdout = sys.stdout
        sys.stdout = buf
        try:
            print_summary(result)
        finally:
            sys.stdout = _old_stdout
        sys.stderr.write(buf.getvalue())
    except Exception as e:
        sys.stdout.write(json.dumps({"error": str(e), "ticker": ticker}, indent=2) + "\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
