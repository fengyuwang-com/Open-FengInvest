#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fengvaluation.py — 多方法估值（预期法逆向 DCF / 前向两阶段 DCF / 敏感性网格 / 多方法综合）

预期法（expected）：移植 ~/_research/implied-expectations 的
model.py + solver.py 思路（非抄 README）——
  两阶段 FCFF 前向模型：
    revenue_t  = revenue * (1+g)^t
    NOPAT_t    = revenue_t * margin * (1 - tax_rate)
    再投资率   = max(0, g / roic)          （增长-资金恒等式，收缩不造现金流）
    FCFF_t     = NOPAT_t * (1 - 再投资率)
  终值 Gordon：终期 RONIC = 贴现率（价值中性），g_t = terminal_growth
    FCFF_{N+1} = revenue_N * (1+g_t) * margin * (1-tax) * (1 - g_t/ronic)
    TV_N       = FCFF_{N+1} / (wacc - g_t)
  股权价值 = EV - 总债务 + 现金；每股 = 股权价值 / 稀释股数
反解：二分法求隐含增长（区间 [-90%, +60%]，收敛 tol 1e-8）；四模式回退枚举
  SOLVED / DURATION_AT_CAP / BEYOND_HORIZON / BELOW_FLOOR / REJECTED。
「不编造数字」：无解路径必须如实输出 mode + reason，不静默、不伪造。

数据：SEC companyfacts（复用 fengpit 拉取与事件解析）。流量项（营收/营业利润）
取最新完整财年（form ∈ {10-K,20-F,40-F}、fp=FY、期间 340-380 天），营收与营业
利润必须同财年否则 REJECTED；平衡表项（债务/现金/股数）取最新 instant。

用法：
  python tools/fengvaluation.py expected AAPL --price 100
  python tools/fengvaluation.py dcf AAPL --price 100 --wacc 0.10 --growth 0.05
  python tools/fengvaluation.py sensitivity AAPL --price 100
  python tools/fengvaluation.py composite AAPL --price 100 --methods expected,dcf
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fengpit  # noqa: E402

# --------------------------------------------------------------------------
# 常量与参数
# --------------------------------------------------------------------------
GROWTH_FLOOR = -0.90
GROWTH_CAP = 0.60
MAX_YEARS = 50
_TOL = 1e-8
_MAX_ITER = 200

DEFAULT_WACC = 0.095
DEFAULT_TAX = 0.21
DEFAULT_HORIZON = 10
DEFAULT_DURATION_GROWTH = 0.20
DEFAULT_TERMINAL_G_EXPECTED = 0.025   # 长期名义 GDP 量级
DEFAULT_TERMINAL_G_DCF = 0.03         # dcf 子命令默认（CLI 可配）
DEFAULT_GROWTH_DCF = 0.05
FALLBACK_ROIC = 0.20
ROIC_CLAMP = (0.10, 1.00)
TAX_CLAMP = (0.0, 0.45)

# XBRL 概念 → tag 候选（复用 fengpit 的 tag_switch 思路）
TAG_REVENUE = ["RevenueFromContractWithCustomerExcludingAssessedTax",
               "SalesRevenueNet", "Revenues"]
TAG_OPINC = ["OperatingIncomeLoss",
             "OperatingIncomeLossIncludingIncomeFromEquityMethodInvestments"]
TAG_DEBT_NC = ["LongTermDebtNoncurrent",
               "LongTermDebtAndCapitalLeaseObligationsNoncurrent"]
TAG_DEBT_C = ["LongTermDebtCurrent",
              "LongTermDebtAndCapitalLeaseObligationsCurrent"]
TAG_CASH = ["CashAndCashEquivalentsAtCarryingValue"]
TAG_STI = ["ShortTermInvestments"]
TAG_SHARES = ["WeightedAverageNumberOfDilutedSharesOutstanding"]
TAG_ASSETS = ["Assets"]
TAG_EQUITY = ["StockholdersEquity",
              "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]

ANNUAL_FORMS = ("10-K", "20-F", "40-F")
FY_DURATION = (340, 380)   # 完整财年期间（天）


class ValuationError(Exception):
    """数据/参数级拒绝（→ mode=REJECTED 的 reason）。"""


# --------------------------------------------------------------------------
# 基本面提取（companyfacts → CompanyData）
# --------------------------------------------------------------------------
def _latest_annual(facts, tags, concept, unit_contains=None):
    """最新完整财年流量项（form∈年报、fp=FY、期间 340-380 天）。

    返回 (value, event)；同 period 多 tag/多版本取 filed 最新者（tag_switch）。
    """
    events = fengpit.parse_us_events(facts, tags, concept, unit_contains=unit_contains)
    cands = []
    for e in events:
        form = str(e.get("form") or "")
        if not form.startswith(ANNUAL_FORMS):
            continue
        if e.get("fp") != "FY":
            continue
        days = fengpit._lag_days(e["period_end"], e["period_start"])
        if days is None or not (FY_DURATION[0] <= days <= FY_DURATION[1]):
            continue
        cands.append(e)
    if not cands:
        return None, None
    pend = max(e["period_end"] for e in cands)
    by_pend = sorted((e for e in cands if e["period_end"] == pend),
                     key=lambda e: e["filed"] or "")
    return by_pend[-1]["value"], by_pend[-1]


def _latest_instant(facts, tags, concept, unit_contains=None):
    """最新 balance 项：优先纯 instant（start==end）；无纯 instant 的 duration 项
    （如加权平均稀释股数）回退取最新 period_end。同 instant 多版本取 filed 最新者。"""
    events = fengpit.parse_us_events(facts, tags, concept, unit_contains=unit_contains)
    instants = [e for e in events if e["period_start"] == e["period_end"]]
    if not instants:
        instants = events   # duration 项回退（provenance 里 period 即最新报告期）
    if not instants:
        return None, None
    pend = max(e["period_end"] for e in instants)
    by_inst = sorted((e for e in instants if e["period_end"] == pend),
                     key=lambda e: e["filed"] or "")
    return by_inst[-1]["value"], by_inst[-1]


def _sum_instant(facts, tags, concept, unit_contains=None):
    """多个 instant 概念求和（如 长期债务 + 短期债务）；缺失项按 0 计并记入 provenance。"""
    total = 0.0
    used = []
    for tag in tags:
        v, e = _latest_instant(facts, [tag], concept, unit_contains=unit_contains)
        if v is not None:
            total += v
            used.append(e)
    return total, used


def extract_company(facts, ticker):
    """companyfacts → CompanyData + provenance[]。数据不满足 → ValuationError。"""
    revenue, rev_ev = _latest_annual(facts, TAG_REVENUE, "revenue")
    opinc, op_ev = _latest_annual(facts, TAG_OPINC, "operating_income")
    if revenue is None:
        raise ValuationError(f"{ticker}: 无完整财年营收（10-K/20-F/40-F, fp=FY, 340-380 天）")
    if opinc is None:
        raise ValuationError(f"{ticker}: 无完整财年营业利润（OperatingIncomeLoss 系 tag）")
    if rev_ev["period_end"] != op_ev["period_end"]:
        raise ValuationError(
            f"{ticker}: 营收财年 {rev_ev['period_end']} 与营业利润财年 {op_ev['period_end']} "
            "不一致，拒绝估值（营收与营业利润必须同财年）")

    debt, debt_evs = _sum_instant(facts, TAG_DEBT_NC, "debt_noncurrent")
    debt_c, debt_c_evs = _sum_instant(facts, TAG_DEBT_C, "debt_current")
    cash, cash_evs = _sum_instant(facts, TAG_CASH, "cash")
    sti, sti_evs = _sum_instant(facts, TAG_STI, "short_term_investments")
    shares, sh_ev = _latest_instant(facts, TAG_SHARES, "shares", unit_contains="share")
    equity, eq_ev = _latest_instant(facts, TAG_EQUITY, "equity")
    assets, as_ev = _latest_instant(facts, TAG_ASSETS, "assets")

    if shares is None or shares <= 0:
        raise ValuationError(f"{ticker}: 无有效稀释股数（WeightedAverageNumberOfDilutedSharesOutstanding）")

    prov = [{"concept": "revenue", "xbrl_tag": rev_ev["xbrl_tag"], "period_end": rev_ev["period_end"],
             "value": revenue, "form": rev_ev["form"], "accn": rev_ev["accn"]},
            {"concept": "operating_income", "xbrl_tag": op_ev["xbrl_tag"],
             "period_end": op_ev["period_end"], "value": opinc, "form": op_ev["form"],
             "accn": op_ev["accn"]}]
    for evs in (debt_evs, debt_c_evs, cash_evs, sti_evs):
        prov.extend({"concept": e["concept"], "xbrl_tag": e["xbrl_tag"],
                     "period_end": e["period_end"], "value": e["value"],
                     "form": e["form"], "accn": e["accn"]} for e in evs)
    for name, e in (("shares", sh_ev), ("equity", eq_ev), ("assets", as_ev)):
        if e:
            prov.append({"concept": name, "xbrl_tag": e["xbrl_tag"],
                         "period_end": e["period_end"], "value": e["value"],
                         "form": e["form"], "accn": e["accn"]})

    return {
        "ticker": ticker,
        "revenue": revenue,
        "operating_income": opinc,
        "total_debt": debt + debt_c,
        "cash": cash + sti,
        "shares": shares,
        "equity": equity,
        "assets": assets,
        "fy_end": rev_ev["period_end"],
        "debt_approx": not (debt_evs or debt_c_evs),
        "cash_approx": not (cash_evs or sti_evs),
        "provenance": prov,
    }, prov


# --------------------------------------------------------------------------
# 前向模型（移植 implied-expectations model.py 思路，参数化）
# --------------------------------------------------------------------------
def enterprise_value(revenue, growth, years, margin, wacc, tax_rate, roic,
                     terminal_growth):
    """两阶段 FCFF 企业价值。终期 RONIC = wacc（价值中性 Gordon 终值）。

    返回 (ev, pv_explicit, pv_terminal)。收敛性由调用方预检（wacc > terminal_growth）。
    """
    after_tax = 1.0 - tax_rate
    reinvest = max(0.0, growth / roic)      # 收缩不造现金流
    pv_explicit = 0.0
    for t in range(1, years + 1):
        rev_t = revenue * (1.0 + growth) ** t
        nopat = rev_t * margin * after_tax
        fcff = nopat * (1.0 - reinvest)
        pv_explicit += fcff / (1.0 + wacc) ** t
    term_reinvest = max(0.0, terminal_growth / wacc)   # RONIC = wacc，价值中性
    rev_n = revenue * (1.0 + growth) ** years
    nopat_next = rev_n * (1.0 + terminal_growth) * margin * after_tax
    fcff_next = nopat_next * (1.0 - term_reinvest)
    tv = fcff_next / (wacc - terminal_growth)
    pv_terminal = tv / (1.0 + wacc) ** years
    return pv_explicit + pv_terminal, pv_explicit, pv_terminal


def value_per_share(cmp, growth, years, margin, wacc, tax_rate, roic,
                    terminal_growth):
    """股权价值/每股。"""
    ev, _, _ = enterprise_value(cmp["revenue"], growth, years, margin, wacc,
                                tax_rate, roic, terminal_growth)
    equity = ev - cmp["total_debt"] + cmp["cash"]
    return equity / cmp["shares"]


# --------------------------------------------------------------------------
# 反解（移植 implied-expectations solver.py 思路）
# --------------------------------------------------------------------------
def _bisect(f, lo, hi):
    """二分求根，收敛 tol=1e-8，最大 200 迭代。"""
    f_lo = f(lo)
    f_hi = f(hi)
    if f_lo == 0:
        return lo
    if f_hi == 0:
        return hi
    if f_lo * f_hi > 0:
        raise ValueError("root not bracketed")
    for _ in range(_MAX_ITER):
        mid = (lo + hi) / 2.0
        f_mid = f(mid)
        if f_mid == 0 or (hi - lo) / 2.0 < _TOL:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2.0


def implied_growth(cmp, price, years, margin, wacc, tax_rate, roic,
                   terminal_growth, duration_growth=DEFAULT_DURATION_GROWTH,
                   cap=GROWTH_CAP, floor=GROWTH_FLOOR):
    """价格隐含增长（SOLVED）；无解回退 DURATION_AT_CAP / BEYOND_HORIZON / BELOW_FLOOR。"""
    if price <= 0:
        raise ValuationError("price 必须为正")
    if margin <= 0:
        raise ValuationError("营业利润率非正，隐含增长反解未定义（亏损公司需 --margin 显式给定）")

    def gap(g):
        return value_per_share(cmp, g, years, margin, wacc, tax_rate, roic,
                               terminal_growth) - price

    if gap(floor) >= 0:
        return {"mode": "BELOW_FLOOR", "implied_growth": None, "years": years,
                "margin": margin,
                "reason": f"即使 {floor:.0%} 年化收缩场景估值仍高于市价"}
    if gap(cap) < 0:
        return implied_duration(cmp, price, duration_growth, margin, wacc, tax_rate,
                                roic, terminal_growth, min_years=years)
    g = _bisect(gap, floor, cap)
    return {"mode": "SOLVED", "implied_growth": g, "years": years, "margin": margin,
            "reason": None}


def implied_duration(cmp, price, growth, margin, wacc, tax_rate, roic,
                     terminal_growth, min_years=0):
    """隐含增长持续年限（DURATION_AT_CAP）；50 年仍不够 → BEYOND_HORIZON。"""
    if price <= 0:
        raise ValuationError("price 必须为正")
    if margin <= 0:
        raise ValuationError("营业利润率非正，duration 反解未定义")

    def v(n):
        return value_per_share(cmp, growth, n, margin, wacc, tax_rate, roic,
                               terminal_growth)

    prev = v(max(min_years, 0))
    if prev >= price and min_years == 0:
        return {"mode": "SOLVED", "implied_growth": growth, "years": 0.0,
                "margin": margin, "reason": None}
    for n in range(max(min_years, 0) + 1, MAX_YEARS + 1):
        cur = v(n)
        if cur >= price:
            frac = (price - prev) / (cur - prev) if cur > prev else 1.0
            return {"mode": "DURATION_AT_CAP", "implied_growth": growth,
                    "implied_duration": (n - 1) + frac, "margin": margin,
                    "reason": f"增长按 {growth:.1%} 持续，市价需 {((n - 1) + frac):.1f} 年达到"}
        prev = cur
    return {"mode": "BEYOND_HORIZON", "implied_growth": growth,
            "implied_duration": None, "margin": margin,
            "reason": f"即使按 {growth:.1%} 增长持续 {MAX_YEARS} 年仍低于市价"}


def implied_margin(cmp, price, growth, years, wacc, tax_rate, roic,
                   terminal_growth):
    """价格隐含营业利润率（EV 对 margin 线性 → 精确除法）。价格 ≤ 每股净现金 → None。"""
    if price <= 0:
        raise ValuationError("price 必须为正")
    target_ev = price * cmp["shares"] + cmp["total_debt"] - cmp["cash"]
    if target_ev <= 0:
        return None
    ev_unit = value_per_share(cmp, growth, years, 1.0, wacc, tax_rate, roic,
                              terminal_growth) * cmp["shares"] + cmp["total_debt"] - cmp["cash"]
    if ev_unit <= 0:
        return None
    return target_ev / ev_unit


# --------------------------------------------------------------------------
# 参数装配
# --------------------------------------------------------------------------
def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def build_assumptions(args, cmp, provenance):
    """从 CLI 参数 + 基本面计算 assumptions。返回 (assumptions, prov_extend) 或抛 ValuationError。"""
    tax = _clamp(args.tax_rate, *TAX_CLAMP)
    wacc = args.wacc
    if wacc <= 0:
        raise ValuationError(f"wacc 必须为正（收到 {wacc}）")
    roic = args.roic
    if roic is None:
        nopat = cmp["operating_income"] * (1.0 - tax)
        capital = (cmp.get("equity") or 0) + cmp["total_debt"]
        if capital and capital > 0:
            roic = nopat / capital
            roic_note = f"computed: NOPAT/{capital:.0f} = {roic:.4f}"
        else:
            roic = FALLBACK_ROIC
            roic_note = f"资本(equity+debt)不可得，回退 {FALLBACK_ROIC}"
        prov_extend = [{"concept": "roic", "xbrl_tag": None, "period_end": cmp["fy_end"],
                        "value": roic, "form": "derived", "accn": None, "note": roic_note}]
    else:
        roic_note = "user-provided"
        prov_extend = [{"concept": "roic", "xbrl_tag": None, "period_end": None,
                        "value": roic, "form": "cli", "accn": None, "note": roic_note}]
    roic = _clamp(roic, *ROIC_CLAMP)
    margin = args.margin
    if margin is None:
        margin = cmp["operating_income"] / cmp["revenue"] if cmp["revenue"] > 0 else None
    return {
        "wacc": wacc,
        "tax_rate": tax,
        "roic": roic,
        "roic_note": roic_note + f"（clamp 后 {roic:.4f}）",
        "margin": margin,
        "horizon": args.horizon,
        "terminal_growth": args.terminal_g,
        "duration_growth": getattr(args, "duration_growth", DEFAULT_DURATION_GROWTH),
    }, prov_extend


def rejected_out(cmd, ticker, reason, assumptions=None, provenance=None, price=None):
    return {"command": cmd, "mode": "REJECTED", "ticker": ticker, "price": price,
            "reason": reason, "assumptions": assumptions or {},
            "provenance": provenance or [], "note": "数据/参数不满足，未编造数字"}


def _load_cmp(args, ticker):
    """拉取 companyfacts 并提取基本面。返回 (cmp, prov, fetch_meta) 或抛异常。"""
    if getattr(args, "no_network", False):
        raise ValuationError("--no-network 模式：跳过 companyfacts 拉取，无基本面数据")
    facts, fsrc, cik, name, fetched_at = fengpit.get_companyfacts(ticker)
    cmp, prov = extract_company(facts, ticker)
    fetch_meta = {"source": "sec-companyfacts", "cik": cik, "entity_name": name,
                  "fetch_source": fsrc, "fetched_at": fetched_at}
    return cmp, prov, fetch_meta


# --------------------------------------------------------------------------
# 子命令：expected
# --------------------------------------------------------------------------
def cmd_expected(args):
    ticker = args.ticker.upper()
    try:
        cmp, prov, fetch_meta = _load_cmp(args, ticker)
        assumptions, prov_ext = build_assumptions(args, cmp, prov)
        margin = assumptions["margin"]
        if margin is None or margin <= 0:
            return _out(rejected_out("expected", ticker, "营业利润率非正或不可得（亏损公司需 --margin）",
                                     assumptions, prov + prov_ext, args.price))
        terminal_g = assumptions["terminal_growth"]
        if assumptions["wacc"] <= terminal_g:
            return _out(rejected_out("expected", ticker,
                                     f"wacc({assumptions['wacc']:.4f}) <= terminal_growth({terminal_g:.4f})，终值不收敛",
                                     assumptions, prov + prov_ext, args.price))
        target = args.target
        if target == "growth":
            sol = implied_growth(cmp, args.price, assumptions["horizon"], margin,
                                 assumptions["wacc"], assumptions["tax_rate"],
                                 assumptions["roic"], terminal_g,
                                 duration_growth=assumptions["duration_growth"])
            out = {"command": "expected", "mode": sol["mode"], "ticker": ticker,
                   "price": args.price, "target": "growth",
                   "implied_growth": sol.get("implied_growth"),
                   "implied_duration": sol.get("implied_duration"),
                   "reason": sol.get("reason")}
        elif target == "duration":
            sol = implied_duration(cmp, args.price, assumptions["duration_growth"],
                                   margin, assumptions["wacc"], assumptions["tax_rate"],
                                   assumptions["roic"], terminal_g, min_years=assumptions["horizon"])
            out = {"command": "expected", "mode": sol["mode"], "ticker": ticker,
                   "price": args.price, "target": "duration",
                   "implied_growth": sol.get("implied_growth"),
                   "implied_duration": sol.get("implied_duration"),
                   "reason": sol.get("reason")}
        else:  # margin
            m = implied_margin(cmp, args.price, args.growth, assumptions["horizon"],
                               assumptions["wacc"], assumptions["tax_rate"],
                               assumptions["roic"], terminal_g)
            if m is None:
                return _out(rejected_out("expected", ticker,
                                         "价格 ≤ 每股净现金，无隐含利润率可解",
                                         assumptions, prov + prov_ext, args.price))
            out = {"command": "expected", "mode": "SOLVED", "ticker": ticker,
                   "price": args.price, "target": "margin", "implied_margin": m,
                   "at_growth": args.growth, "reason": None}
        out["assumptions"] = assumptions
        out["provenance"] = prov + prov_ext
        out["fetch"] = fetch_meta
        out["fundamentals"] = {k: cmp[k] for k in ("revenue", "operating_income",
                                                   "total_debt", "cash", "shares",
                                                   "fy_end", "debt_approx", "cash_approx")}
        return _out(out)
    except (ValuationError, RuntimeError, ValueError) as e:
        return _out(rejected_out("expected", ticker, str(e), None, None, args.price))


# --------------------------------------------------------------------------
# 子命令：dcf
# --------------------------------------------------------------------------
def cmd_dcf(args):
    ticker = args.ticker.upper()
    try:
        cmp, prov, fetch_meta = _load_cmp(args, ticker)
        assumptions, prov_ext = build_assumptions(args, cmp, prov)
        margin = assumptions["margin"]
        if margin is None or margin <= 0:
            return _out(rejected_out("dcf", ticker, "营业利润率非正或不可得（亏损公司需 --margin）",
                                     assumptions, prov + prov_ext, args.price))
        if assumptions["wacc"] <= assumptions["terminal_growth"]:
            return _out(rejected_out("dcf", ticker,
                                     f"wacc({assumptions['wacc']:.4f}) <= terminal_growth({assumptions['terminal_growth']:.4f})，终值不收敛",
                                     assumptions, prov + prov_ext, args.price))
        if args.growth <= -1:
            return _out(rejected_out("dcf", ticker, f"growth 必须 > -100%（收到 {args.growth}）",
                                     assumptions, prov + prov_ext, args.price))
        v = value_per_share(cmp, args.growth, assumptions["horizon"], margin,
                            assumptions["wacc"], assumptions["tax_rate"],
                            assumptions["roic"], assumptions["terminal_growth"])
        _, pv_e, pv_t = enterprise_value(cmp["revenue"], args.growth,
                                         assumptions["horizon"], margin,
                                         assumptions["wacc"], assumptions["tax_rate"],
                                         assumptions["roic"], assumptions["terminal_growth"])
        mos = (v - args.price) / args.price if args.price else None
        out = {"command": "dcf", "mode": "SOLVED", "ticker": ticker,
               "price": args.price, "value_per_share": v,
               "margin_of_safety_pct": round(mos * 100, 2) if mos is not None else None,
               "enterprise_value": pv_e + pv_t,
               "pv_explicit": pv_e, "pv_terminal": pv_t,
               "terminal_weight_pct": round(pv_t / (pv_e + pv_t) * 100, 2),
               "assumptions": assumptions,
               "provenance": prov + prov_ext, "fetch": fetch_meta}
        return _out(out)
    except (ValuationError, RuntimeError, ValueError) as e:
        return _out(rejected_out("dcf", ticker, str(e), None, None, args.price))


# --------------------------------------------------------------------------
# 子命令：sensitivity
# --------------------------------------------------------------------------
def cmd_sensitivity(args):
    ticker = args.ticker.upper()
    try:
        cmp, prov, fetch_meta = _load_cmp(args, ticker)
        assumptions, prov_ext = build_assumptions(args, cmp, prov)
        margin = assumptions["margin"]
        if margin is None or margin <= 0:
            return _out(rejected_out("sensitivity", ticker, "营业利润率非正或不可得",
                                     assumptions, prov + prov_ext, args.price))
        rows = [float(x) for x in args.growth_rows.split(",")]
        cols = [float(x) for x in args.wacc_cols.split(",")]
        grid = []
        for cap in rows:
            row = []
            for w in cols:
                if w <= assumptions["terminal_growth"]:
                    row.append({"wacc": w, "mode": "REJECTED",
                                "reason": "wacc <= terminal_growth，终值不收敛"})
                    continue
                try:
                    sol = implied_growth(cmp, args.price, assumptions["horizon"],
                                         margin, w, assumptions["tax_rate"],
                                         assumptions["roic"], assumptions["terminal_growth"],
                                         duration_growth=assumptions["duration_growth"],
                                         cap=cap)
                    row.append({"wacc": w, "mode": sol["mode"],
                                "implied_growth": sol.get("implied_growth"),
                                "implied_duration": sol.get("implied_duration"),
                                "reason": sol.get("reason")})
                except ValuationError as e:
                    row.append({"wacc": w, "mode": "REJECTED", "reason": str(e)})
            grid.append(row)
        out = {"command": "sensitivity", "mode": "SOLVED", "ticker": ticker,
               "price": args.price,
               "note": "行 = 增长上限(cap)，列 = WACC；格 = 该 (cap, wacc) 下反解的隐含增长（模式）",
               "rows_growth_cap": rows, "cols_wacc": cols, "grid": grid,
               "assumptions": assumptions, "provenance": prov + prov_ext,
               "fetch": fetch_meta}
        return _out(out)
    except (ValuationError, RuntimeError, ValueError) as e:
        return _out(rejected_out("sensitivity", ticker, str(e), None, None, args.price))


# --------------------------------------------------------------------------
# 子命令：composite
# --------------------------------------------------------------------------
def cmd_composite(args):
    ticker = args.ticker.upper()
    try:
        cmp, prov, fetch_meta = _load_cmp(args, ticker)
        assumptions, prov_ext = build_assumptions(args, cmp, prov)
    except (ValuationError, RuntimeError, ValueError) as e:
        return _out(rejected_out("composite", ticker, str(e), None, None, args.price))

    methods = [m.strip() for m in args.methods.split(",")]
    weights = {}
    for kv in (args.conf or []):
        k, _, v = kv.partition(":")
        try:
            weights[k.strip()] = float(v)
        except ValueError:
            return _out({"error": f"置信度格式错误: {kv}（应为 method:weight）"}, exit_code=2)
    known = set(methods) | set(weights)
    if not known <= {"expected", "dcf"}:
        return _out({"error": f"未知方法: {known - {'expected', 'dcf'}}（可用 expected,dcf）"},
                    exit_code=2)

    margin = assumptions["margin"]
    results = []
    for m in methods:
        if m == "dcf":
            if margin is None or margin <= 0:
                results.append({"method": "dcf", "mode": "REJECTED",
                                "reason": "营业利润率非正，无 --margin 显式假设"})
                continue
            if assumptions["wacc"] <= assumptions["terminal_growth"]:
                results.append({"method": "dcf", "mode": "REJECTED",
                                "reason": "wacc <= terminal_growth"})
                continue
            try:
                v = value_per_share(cmp, args.growth, assumptions["horizon"], margin,
                                    assumptions["wacc"], assumptions["tax_rate"],
                                    assumptions["roic"], assumptions["terminal_growth"])
                results.append({"method": "dcf", "mode": "SOLVED",
                                "point_estimate": v, "at_growth": args.growth,
                                "terminal_growth": assumptions["terminal_growth"]})
            except (ValuationError, ValueError) as e:
                results.append({"method": "dcf", "mode": "REJECTED", "reason": str(e)})
        else:  # expected
            try:
                sol = implied_growth(cmp, args.price, assumptions["horizon"], margin,
                                     assumptions["wacc"], assumptions["tax_rate"],
                                     assumptions["roic"], assumptions["terminal_growth"],
                                     duration_growth=assumptions["duration_growth"])
                if sol["mode"] == "SOLVED":
                    # 反解恒等式：按解出的增长重新估值 ≡ 市价
                    results.append({"method": "expected", "mode": "SOLVED",
                                    "point_estimate": args.price,
                                    "implied_growth": sol["implied_growth"],
                                    "note": "预期法反解值≡市价（按隐含增长重估恒等于 --price）"})
                else:
                    results.append({"method": "expected", "mode": sol["mode"],
                                    "reason": sol.get("reason"),
                                    "implied_growth": sol.get("implied_growth"),
                                    "implied_duration": sol.get("implied_duration")})
            except (ValuationError, ValueError) as e:
                results.append({"method": "expected", "mode": "REJECTED", "reason": str(e)})

    solved = [r for r in results if r.get("mode") == "SOLVED" and r.get("point_estimate") is not None]
    if not solved:
        base = rejected_out("composite", ticker,
                            "所有方法均无解（详见 methods 字段）", assumptions,
                            prov + prov_ext, args.price)
        base["methods"] = results
        return _out(base)
    wsum = 0.0
    wv = 0.0
    ws = 0.0
    for r in solved:
        w = weights.get(r["method"], 1.0 / len(methods))
        wsum += w
        wv += w * r["point_estimate"]
        ws += w * r["point_estimate"] ** 2
    mid = wv / wsum
    var = max(0.0, ws / wsum - mid ** 2)
    sd = var ** 0.5
    low = min(r["point_estimate"] for r in solved)
    high = max(r["point_estimate"] for r in solved)
    if len(solved) == 1:
        interval = {"low": low, "mid": mid, "high": high}
    else:
        interval = {"low": max(low, mid - sd), "mid": mid, "high": min(high, mid + sd)}
    out = {"command": "composite", "mode": "SOLVED", "ticker": ticker,
           "price": args.price, "methods": results,
           "confidence": {r["method"]: weights.get(r["method"], 1.0 / len(methods))
                          for r in results},
           "interval": interval,
           "note": "mid=置信度加权均值；low/high=加权区间裁剪到方法极值（单方法时三值相等）",
           "assumptions": assumptions, "provenance": prov + prov_ext,
           "fetch": fetch_meta}
    return _out(out)


def _out(obj, exit_code=0):
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    return exit_code


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def _add_common(ap, require_price=True):
    if require_price:
        ap.add_argument("--price", type=float, required=True, help="当前市价（用于反解/安全边际）")
    ap.add_argument("--wacc", type=float, default=DEFAULT_WACC, help=f"贴现率（默认 {DEFAULT_WACC}）")
    ap.add_argument("--tax-rate", type=float, default=DEFAULT_TAX,
                    help=f"税率（默认 {DEFAULT_TAX}，clamp 0-0.45）")
    ap.add_argument("--roic", type=float, default=None,
                    help="显式增量 ROIC（默认计算并 clamp 0.10-1.0，拿不到回退 0.20）")
    ap.add_argument("--horizon", type=int, default=DEFAULT_HORIZON,
                    help=f"显式期年限（默认 {DEFAULT_HORIZON}）")
    ap.add_argument("--margin", type=float, default=None,
                    help="显式营业利润率（默认用最新财年实际值）")
    ap.add_argument("--terminal-g", type=float, default=None,
                    help="终值永续增长（默认按子命令：expected 0.025 / dcf 0.03）")
    ap.add_argument("--no-network", action="store_true",
                    help="跳过 companyfacts 拉取（测试参数校验/REJECTED 路径用）")


def main():
    ap = argparse.ArgumentParser(
        description="fengvaluation — 多方法估值（预期法逆向 DCF / 前向 DCF / 敏感性 / 综合）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_e = sub.add_parser("expected", help="预期法：反解价格隐含增长（逆向 DCF）")
    p_e.add_argument("ticker")
    _add_common(p_e)
    p_e.add_argument("--target", choices=["growth", "duration", "margin"], default="growth",
                     help="反解目标（默认 growth）")
    p_e.add_argument("--duration-growth", type=float, default=DEFAULT_DURATION_GROWTH,
                     help="duration 回退模式的增长（默认 0.20）")
    p_e.add_argument("--growth", type=float, default=0.05, help="target=margin 时的增长假设")
    p_e.set_defaults(func=cmd_expected, default_terminal_g=DEFAULT_TERMINAL_G_EXPECTED)

    p_d = sub.add_parser("dcf", help="前向两阶段 DCF 估值（显式期 + 价值中性终值）")
    p_d.add_argument("ticker")
    _add_common(p_d)
    p_d.add_argument("--growth", type=float, default=DEFAULT_GROWTH_DCF,
                     help=f"显式期增长（默认 {DEFAULT_GROWTH_DCF}）")
    p_d.set_defaults(func=cmd_dcf, default_terminal_g=DEFAULT_TERMINAL_G_DCF)

    p_s = sub.add_parser("sensitivity", help="隐含增长敏感性网格（行=增长上限，列=WACC）")
    p_s.add_argument("ticker")
    _add_common(p_s)
    p_s.add_argument("--growth-rows", default="0.10,0.20,0.30",
                     help="行：增长上限(cap) 列表，逗号分隔")
    p_s.add_argument("--wacc-cols", default="0.08,0.095,0.11",
                     help="列：WACC 列表，逗号分隔")
    p_s.add_argument("--duration-growth", type=float, default=DEFAULT_DURATION_GROWTH)
    p_s.set_defaults(func=cmd_sensitivity, default_terminal_g=DEFAULT_TERMINAL_G_EXPECTED)

    p_c = sub.add_parser("composite", help="多方法综合（置信度加权区间）")
    p_c.add_argument("ticker")
    _add_common(p_c)
    p_c.add_argument("--methods", default="expected,dcf", help="方法列表（默认 expected,dcf）")
    p_c.add_argument("--conf", nargs="*", default=[], help="置信度 method:weight（默认均权）")
    p_c.add_argument("--growth", type=float, default=DEFAULT_GROWTH_DCF,
                     help="dcf 方法的显式期增长")
    p_c.add_argument("--duration-growth", type=float, default=DEFAULT_DURATION_GROWTH)
    p_c.set_defaults(func=cmd_composite, default_terminal_g=DEFAULT_TERMINAL_G_EXPECTED)

    args = ap.parse_args()
    if args.terminal_g is None:
        args.terminal_g = getattr(args, "default_terminal_g", DEFAULT_TERMINAL_G_EXPECTED)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
