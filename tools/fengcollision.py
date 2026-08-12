#!/usr/bin/env python3
"""fengcollision — L3 碰撞引擎. 纯 Python 规则树. 读取前序层 JSON 输出, 合成决策.

Usage:
    python fengcollision.py <TICKER>                              # auto-detect layer files
    python fengcollision.py <TICKER> --l1 <file> --l2b <file>     # explicit paths
    python fengcollision.py <TICKER> --l1 <file> --l2b <file> \\
        --fundamentals <file> [--market <file>] [--l2a <file>]

Dependencies: none (pure Python, reads JSON files)
"""

import json, os, sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESEARCH = os.path.join(BASE, "research")

# ── proxy: infer L2a qualitative lights from quantitative data ─────────

LIGHTS = ("GREEN", "YELLOW", "RED")


def _worst(*lights):
    """Return worst light: RED > YELLOW > GREEN."""
    for lvl in ("RED", "YELLOW", "GREEN"):
        if lvl in lights:
            return lvl
    return "GREEN"


def _best(*lights):
    """Return best light."""
    for lvl in ("GREEN", "YELLOW", "RED"):
        if lvl in lights:
            return lvl
    return "RED"


def _score(val, lo, hi, invert=False):
    """Score a value on 0-1 scale between lo and hi."""
    if val is None:
        return 0.5
    if hi <= lo:
        return 0.5
    s = (val - lo) / (hi - lo)
    s = max(0.0, min(1.0, s))
    return 1.0 - s if invert else s


def _confidence_text(pct):
    if pct >= 0.8:
        return "high"
    if pct >= 0.5:
        return "medium"
    return "low"


def proxy_l2a_lights(fundamentals: dict, degraded: bool = False) -> dict:
    """Infer L2a qualitative-style lights from available quantitative data.

    When the AI-driven L2a (investment-team) analysis hasn't run yet,
    these proxy lights let the collision engine still produce a decision
    with reduced confidence. Each light records source="proxy_from_data".
    """
    rev = fundamentals.get("revenue_annual", [])
    ni = fundamentals.get("net_income_annual", [])
    fcf = fundamentals.get("fcf_annual", [])
    ocf = fundamentals.get("operating_cf_annual", [])
    capex = fundamentals.get("capex_annual", [])
    equity = fundamentals.get("equity_annual", [])
    debt = fundamentals.get("debt_annual", [])
    roe = fundamentals.get("roe_pct") or 0
    pm = fundamentals.get("profit_margin_pct") or 0
    gm = fundamentals.get("gross_margin_pct") or 0
    rg = fundamentals.get("revenue_growth_pct") or 0
    pe = fundamentals.get("trailing_pe") or 0
    debt_eq = fundamentals.get("debt_to_equity") or 0
    cash = fundamentals.get("cash_annual", [])

    # ── 好生意 proxy: ROE + margin + FCF consistency ──────────
    fcf_positive_years = sum(1 for v in fcf if v and v > 0) if fcf else 0
    fcf_total = len(fcf) if fcf else 0
    fcf_consistency = fcf_positive_years / max(fcf_total, 1)

    biz_score = (
        0.40 * _score(roe, 0, 40) +
        0.25 * _score(pm, 0, 40) +
        0.20 * _score(gm, 0, 80) +
        0.15 * fcf_consistency
    )
    biz_light = "GREEN" if biz_score >= 0.6 else ("YELLOW" if biz_score >= 0.3 else "RED")

    # ── 护城河 proxy: ROE stability + margin trend + revenue ───
    if len(ni) >= 2 and len(rev) >= 2:
        rev_stable = rev[0] > 0 and rev[1] > 0
        ni_growing = ni[0] >= ni[1] * 0.9  # allow 10% dip
    else:
        rev_stable = True
        ni_growing = True
    moat_score = (
        0.30 * _score(roe, 0, 40) +
        0.25 * _score(gm, 0, 80) +
        0.25 * (1.0 if rev_stable else 0.3) +
        0.20 * (1.0 if ni_growing else 0.3)
    )
    moat_light = "GREEN" if moat_score >= 0.6 else ("YELLOW" if moat_score >= 0.35 else "RED")

    # ── 安全边际 proxy: PE vs sector, FCF yield ────────────────
    # Low PE = more margin of safety
    safe_score = (
        0.40 * _score(pe, 5, 40, invert=True) +
        0.30 * _score(roe, 0, 30, invert=False) +
        0.30 * (1.0 if fcf_consistency >= 0.5 else 0.0)
    )
    safe_light = "GREEN" if safe_score >= 0.6 else ("YELLOW" if safe_score >= 0.35 else "RED")

    # ── 管理层 proxy: sustainable growth rate ──────────────────
    # g = ROE * (1 - payout_ratio), high ROE + reinvestment = good mgmt
    payout = fundamentals.get("payout_ratio") or 0
    if payout and payout > 1:
        payout = 0.3  # cap
    sustainable_g = roe * (1 - payout) if roe else 0
    mgmt_score = (
        0.40 * _score(sustainable_g, 0, 25) +
        0.30 * _score(roe, 0, 40) +
        0.30 * (1.0 if fcf_consistency >= 0.5 else 0.0)
    )
    mgmt_light = "GREEN" if mgmt_score >= 0.5 else ("YELLOW" if mgmt_score >= 0.3 else "RED")

    # ── 需求稳定 proxy: revenue growth + no decline ────────────
    rev_growing = True
    if len(rev) >= 2:
        rev_growing = rev[0] >= rev[1] * 0.9
    demand_score = (
        0.50 * (1.0 if rev_growing else 0.2) +
        0.30 * _score(rg, -10, 30) +
        0.20 * _score(pm, 0, 30)
    )
    demand_light = "GREEN" if demand_score >= 0.6 else ("YELLOW" if demand_score >= 0.35 else "RED")

    # ── 会计质量 proxy: OCF vs NI alignment ────────────────────
    # Quality earnings: operating cash flow should align with net income
    acct_score = 0.5
    if len(ocf) >= 1 and len(ni) >= 1:
        ocf_ni_ratio = abs(ocf[0]) / max(abs(ni[0]), 1)
        if 0.5 <= ocf_ni_ratio <= 2.0:
            acct_score = 0.8
        elif 0.3 <= ocf_ni_ratio <= 3.0:
            acct_score = 0.5
        else:
            acct_score = 0.2
    # Debt check
    debt_ok = debt_eq < 100 if debt_eq else True
    acct_score = acct_score * (1.0 if debt_ok else 0.8)
    acct_light = "GREEN" if acct_score >= 0.65 else ("YELLOW" if acct_score >= 0.4 else "RED")

    return {
        "source": "proxy_from_degraded_data" if degraded else "proxy_from_data",
        "好生意": {"light": biz_light, "score": round(biz_score, 2)},
        "护城河": {"light": moat_light, "score": round(moat_score, 2)},
        "安全边际": {"light": safe_light, "score": round(safe_score, 2)},
        "管理层": {"light": mgmt_light, "score": round(mgmt_score, 2)},
        "需求稳定": {"light": demand_light, "score": round(demand_score, 2)},
        "会计质量": {"light": acct_light, "score": round(acct_score, 2)},
    }


def _absolute_undervaluation(fundamentals: dict) -> dict:
    """Check absolute undervaluation: PE<10x, PB<1x, or 净现金/市值>30%.

    Any ONE condition met = triggered.  From docs/06-collision.md.
    """
    pe = fundamentals.get("trailing_pe") or 0
    pb = fundamentals.get("pb") or 0

    # Net cash / market cap approximation
    cash_arr = fundamentals.get("cash_annual") or []
    debt_arr = fundamentals.get("debt_annual") or []
    cash = cash_arr[0] if cash_arr else 0
    debt = debt_arr[0] if debt_arr else 0
    price = fundamentals.get("price") or 0
    shares = fundamentals.get("shares_outstanding") or 0
    market_cap = price * shares if price and shares else 0
    net_cash = (cash or 0) - (debt or 0)
    net_cash_ratio = net_cash / market_cap if market_cap > 0 else 0

    conditions = {
        "pe_under_10x": {"pass": 0 < pe < 10, "value": round(pe, 1)},
        "pb_under_1x": {"pass": 0 < pb < 1, "value": round(pb, 2)},
        "net_cash_over_30pct_mcap": {"pass": net_cash_ratio > 0.3, "value": round(net_cash_ratio, 3)},
    }
    any_pass = any(c["pass"] for c in conditions.values())
    return {"triggered": any_pass, "conditions": conditions}


def _l2a_overall_green(l2a: dict) -> bool:
    """L2a整体🟢 = ≥3 lights GREEN + no RED across all 6 lights."""
    lights = []
    for k in ("好生意", "护城河", "安全边际", "管理层", "需求稳定", "会计质量"):
        v = l2a.get(k, {}).get("light") if isinstance(l2a, dict) else None
        if v:
            lights.append(v)
    green_count = sum(1 for l in lights if l == "GREEN")
    red_count = sum(1 for l in lights if l == "RED")
    return green_count >= 3 and red_count == 0


# ── collision rules ────────────────────────────────────────────────


def _get_l1_light(l1: dict) -> str:
    """Get L1 overall light: handles both {'overall_light':'🟡'} and {'overall':{'light':'🟡'}}."""
    if not l1:
        return "GREEN"
    light = l1.get("overall_light")
    if light in ("GREEN", "YELLOW", "RED"):
        return light
    overall = l1.get("overall", {})
    if isinstance(overall, dict):
        light = overall.get("light")
        if light in ("GREEN", "YELLOW", "RED", "🟢", "🟡", "🔴"):
            # normalize emoji to text
            return {"🟢": "GREEN", "🟡": "YELLOW", "🔴": "RED"}.get(light, "GREEN")
    return "GREEN"


def _get_l2b_factors(l2b: dict) -> list:
    """Get L2b factor list: handles both nested (factor_analysis.factors) and flat (factors)."""
    if not l2b:
        return []
    fa = l2b.get("factor_analysis")
    if isinstance(fa, dict) and fa.get("factors"):
        return fa["factors"]
    if l2b.get("factors"):
        return l2b["factors"]
    return []


def _get_l1_rules(l1: dict) -> list:
    """Get discipline rules list."""
    return l1.get("rules", []) if l1 else []


def _collect_dissenting_signals(l1: dict, l2b: dict, fundamentals: dict,
                                 market: dict, l2a: dict) -> dict:
    """Systematically collect ALL bearish/dissenting signals from every layer.

    Every layer that disagrees with the bullish case gets a voice here.
    This is the Python counterpart of the L3 skill's 反方强制检查.
    """
    signals = {
        "l2b_bear_factors": [],
        "l1_failed_checks": [],
        "market_red_lights": [],
        "l2a_weak_lights": [],
        "fundamental_warnings": [],
        "conflicts": [],
        "adversarial_questions": [
            {
                "question": "列出这个股票让你亏钱的5种方式",
                "note": "需L3 Skill运行完整反方检查",
                "available_data_hints": [],
            },
            {
                "question": "如果当前价格下跌30%，你会加仓还是割肉？",
                "note": "需L3 Skill定性判断",
            },
            {
                "question": "如果当前价格上涨30%，你会卖吗？",
                "note": "需L3 Skill定性判断",
            },
            {
                "question": "这个决策受什么最近的新闻/价格走势影响？",
                "note": "需L3 Skill暴露近因偏误",
            },
        ],
    }

    # ── L2b: every BEAR factor ─────────────────────────────────────
    factors = _get_l2b_factors(l2b)
    for f in factors:
        if f.get("signal") == "BEAR":
            fname = f.get("label") or f.get("factor") or f.get("name", "?")
            entry = {
                "factor": fname,
                "z_score": f.get("z_score"),
                "detail": f.get("note") or f.get("message") or f.get("reason", ""),
            }
            signals["l2b_bear_factors"].append(entry)
            signals["conflicts"].append({
                "source": f"L2b-{entry['factor']}",
                "message": entry.get("detail") or f"z={entry['z_score']} 信号BEAR",
                "handling": "已通过碰撞规则加权计入决策",
            })
            signals["adversarial_questions"][0]["available_data_hints"].append(
                f"L2b「{entry['factor']}」z={entry['z_score']} BEAR"
            )

    # If L2b has more bears than bulls, flag structural concern
    l2b_bull = sum(1 for f in factors if f.get("signal") == "BULL")
    l2b_bear = len(signals["l2b_bear_factors"])
    if l2b_bear > l2b_bull and l2b_bear > 0:
        signals["conflicts"].append({
            "source": "L2b-整体",
            "message": f"量化因子整体偏空 ({l2b_bear}熊 vs {l2b_bull}牛)",
            "handling": "已降低置信度/仓位",
        })

    # ── L1: discipline rules that failed ───────────────────────────
    rules = _get_l1_rules(l1)
    for r in rules:
        light_val = r.get("light")
        # Handle both string light and dict light
        if isinstance(light_val, dict):
            light_val = light_val.get("light")
        if light_val in ("RED", "🔴"):
            entry = {
                "check": r.get("check", "?"),
                "reason": r.get("reason", ""),
            }
            signals["l1_failed_checks"].append(entry)
            signals["conflicts"].append({
                "source": f"L1-{entry['check']}",
                "message": entry["reason"],
                "handling": "L1红灯已在规则树顶层处理（Deep Value或PASS）",
            })

    # ── M layer: RED lights ────────────────────────────────────────
    m = market if isinstance(market, dict) else {}
    # Handle both emoji format (🟢🟡🔴) and text format (bullish/neutral/bearish)
    m_labels = {
        "宏观": m.get("macro", "🟡"),
        "估值": m.get("valuation", "🟡"),
        "趋势": m.get("trend", "🟡"),
        "情绪": m.get("sentiment", "🟡"),
    }
    # Also check nested m_layer field (temp_m_*.json format)
    if "m_layer" in m:
        ml = m["m_layer"]
        if isinstance(ml, dict):
            label_map = {"": ""}
            for cn, en in (("宏观", "macro"), ("估值", "valuation"), ("趋势", "trend"), ("情绪", "sentiment")):
                if ml.get(en):
                    m_labels[f"M-{cn}"] = str(ml[en])

    for label, val in m_labels.items():
        val_str = str(val).strip()
        if val_str == "🔴" or val_str == "bearish":
            signals["market_red_lights"].append(label)
            signals["conflicts"].append({
                "source": f"M层-{label}",
                "message": f"{label}红灯",
                "handling": "已在碰撞规则中考虑市场风险",
            })

    # ── L2a: proxy lights that are RED or YELLOW ───────────────────
    if l2a:
        for k in ("好生意", "护城河", "安全边际", "管理层", "需求稳定", "会计质量"):
            v = l2a.get(k, {})
            if isinstance(v, dict):
                lt = v.get("light")
                if lt == "RED":
                    signals["l2a_weak_lights"].append({"item": k, "status": "RED"})
                elif lt == "YELLOW":
                    signals["l2a_weak_lights"].append({"item": k, "status": "YELLOW"})

    # ── Fundamental warnings ───────────────────────────────────────
    rev = fundamentals.get("revenue_annual") or []
    ni = fundamentals.get("net_income_annual") or []
    fcf = fundamentals.get("fcf_annual") or []
    debt_eq = fundamentals.get("debt_to_equity") or 0

    if len(rev) >= 2 and rev[0] is not None and rev[1] is not None and rev[1] > 0:
        rev_change = (rev[0] / rev[1] - 1) * 100
        if rev_change < -20:
            signals["fundamental_warnings"].append(f"营收同比下降{abs(rev_change):.0f}%")
    if len(ni) >= 1 and ni[0] is not None and ni[0] < 0:
        signals["fundamental_warnings"].append("最新净利润为负")
    if len(fcf) >= 1 and fcf[0] is not None and fcf[0] < 0:
        signals["fundamental_warnings"].append("最新自由现金流为负")
    if debt_eq > 200:
        signals["fundamental_warnings"].append(f"资产负债率异常 (D/E={debt_eq:.0f}%)")

    for w in signals["fundamental_warnings"]:
        signals["conflicts"].append({
            "source": "基本面",
            "message": w,
            "handling": "作为背景参考",
        })

    return signals


def _persona_verdicts(l1: dict, l2b: dict, fundamentals: dict,
                       l2a: dict, market: dict, ticker: str) -> list:
    """Generate what different investing personas would conclude from the same data.

    Each persona's verdict is a data-driven pattern match against their known
    investment philosophy. Not investment advice — just perspective diversity.
    """
    l2a_biz = (l2a or {}).get("好生意", {}).get("light", "UNKNOWN")
    l2a_moat = (l2a or {}).get("护城河", {}).get("light", "UNKNOWN")
    l2a_safe = (l2a or {}).get("安全边际", {}).get("light", "UNKNOWN")
    l2a_mgmt = (l2a or {}).get("管理层", {}).get("light", "UNKNOWN")
    l2a_demand = (l2a or {}).get("需求稳定", {}).get("light", "UNKNOWN")
    l1_light = _get_l1_light(l1)

    # L2b signals
    factors = _get_l2b_factors(l2b)
    l2b_bull = sum(1 for f in factors if f.get("signal") == "BULL")
    l2b_bear = sum(1 for f in factors if f.get("signal") == "BEAR")
    l2b_total = len(factors)
    # Find the most negative z-score factor
    worst_factor = None
    worst_z = 999
    for f in factors:
        z = f.get("z_score")
        if z is not None and z < worst_z:
            worst_z = z
            worst_factor = f.get("label") or f.get("factor") or f.get("name", "?")
    # Find the most positive z-score factor
    best_factor = None
    best_z = -999
    for f in factors:
        z = f.get("z_score")
        if z is not None and z > best_z:
            best_z = z
            best_factor = f.get("label") or f.get("factor") or f.get("name", "?")

    # Fundamentals
    pe = fundamentals.get("trailing_pe") or 0
    pb = fundamentals.get("pb") or 0
    roe = fundamentals.get("roe_pct") or 0
    pm = fundamentals.get("profit_margin_pct") or 0
    gm = fundamentals.get("gross_margin_pct") or 0
    rev = fundamentals.get("revenue_annual") or []
    rg = fundamentals.get("revenue_growth_pct") or 0
    fcf_arr = fundamentals.get("fcf_annual") or []
    debt_eq = fundamentals.get("debt_to_equity") or 0
    price = fundamentals.get("price") or 0
    ma50 = fundamentals.get("ma50") or 0
    ma120 = fundamentals.get("ma120") or 0

    # Revenue growth rate
    if len(rev) >= 2 and rev[0] and rev[1] and rev[1] > 0:
        rg_calc = (rev[0] / rev[1] - 1) * 100
    else:
        rg_calc = rg

    # Absolute undervaluation
    underval = _absolute_undervaluation(fundamentals) if fundamentals else {"triggered": False}
    abs_underval_triggered = underval.get("triggered", False)

    # M layer
    m = market if isinstance(market, dict) else {}

    # Trend status
    trend_bull = ma50 >= ma120 if ma50 and ma120 else None

    # Net cash (for Klarman)
    cash_arr = fundamentals.get("cash_annual") or []
    debt_arr = fundamentals.get("debt_annual") or []
    cash_net = (cash_arr[0] if cash_arr else 0) - (debt_arr[0] if debt_arr else 0)

    verdicts = []

    # ── 1. 西蒙斯 (量化/统计套利) ──────────────────────────────────
    if factors:
        if l2b_bear >= l2b_bull + 2:
            sig = "red"
            r = f"量化因子{l2b_bear}熊{l2b_bull}牛，偏空信号占主导"
        elif l2b_bear > l2b_bull:
            sig = "yellow"
            r = f"量化因子{l2b_bear}熊{l2b_bull}牛，信号分歧偏空"
        elif l2b_bull > l2b_bear:
            sig = "yellow" if l2b_bear > 0 else "green"
            r = f"量化因子{l2b_bull}牛{l2b_bear}熊，信号分歧偏多" if l2b_bear > 0 else f"量化因子{l2b_total}个全部偏多"
        else:
            sig = "yellow"
            r = f"量化因子牛熊均衡({l2b_bull}B/{l2b_bear}B)，无显著方向"
        if worst_factor and worst_z < -1:
            r += f"，最弱信号{worst_factor} z={worst_z:.2f}"
        verdicts.append({
            "persona": "西蒙斯 (Quant)",
            "style": "统计套利·因子驱动",
            "signal": sig,
            "reason": r,
        })
    else:
        verdicts.append({
            "persona": "西蒙斯 (Quant)",
            "style": "统计套利·因子驱动",
            "signal": "grey",
            "reason": "无量化因子数据，无法判断",
        })

    # ── 2. Cathie Wood (创新成长) ──────────────────────────────────
    if rg_calc > 20:
        sig, r = "green", f"营收增长{rg_calc:.0f}%符合高成长标准"
    elif rg_calc > 5:
        sig, r = "yellow", f"营收增长{rg_calc:.0f}%中等，创新故事需要更强增长支撑"
    elif rg_calc > 0:
        sig, r = "yellow", f"营收增长仅{rg_calc:.0f}%，不足以支撑创新高估值"
    elif rg_calc > -10:
        sig, r = "red", f"营收同比下滑{rg_calc:.0f}%，颠覆式创新需要增长"
    else:
        sig, r = "red", f"营收同比大幅下滑{rg_calc:.0f}%，与她关注的标的背离"
    verdicts.append({
        "persona": "Cathie Wood",
        "style": "颠覆式创新·高增长",
        "signal": sig,
        "reason": r,
    })

    # ── 3. 巴菲特 (品质价值) ──────────────────────────────────────
    if l2a_biz == "GREEN" and l2a_moat == "GREEN" and l2a_safe == "GREEN":
        sig, r = "green", "好生意+护城河+安全边际均GREEN，符合巴菲特标准"
    elif l2a_biz == "GREEN" and l2a_moat == "GREEN":
        sig, r = "yellow", f"好生意🟢+护城河🟢，但安全边际{l2a_safe}，价格不是他喜欢的"
    elif l2a_biz == "GREEN":
        sig, r = "yellow", "好生意GREEN，但护城河不够宽"
    elif l2a_biz in ("RED", "YELLOW"):
        sig, r = "red", f"好生意{l2a_biz}，生意质量不在他的能力圈或标准内"
    else:
        sig, r = "grey", "定性数据不足，无法判断"
    verdicts.append({
        "persona": "巴菲特 (Buffett)",
        "style": "品质价值·护城河",
        "signal": sig,
        "reason": r,
    })

    # ── 4. 段永平 (好生意/产品驱动) ───────────────────────────────
    if l2a_biz == "GREEN" and gm > 40:
        sig = "green"
        r = f"好生意🟢+毛利率{gm:.0f}%，定价权和差异化兼备"
    elif l2a_biz == "GREEN":
        sig = "yellow"
        r = f"好生意🟢但毛利率{gm:.0f}%，定价权待验证"
    elif l2a_biz == "YELLOW":
        sig = "yellow"
        r = "生意质量中等, 不够好到不用看价格"
    elif l2a_biz == "RED":
        sig = "red"
        r = f"好生意RED，商业模式不够好，他一般不会碰"
    else:
        sig, r = "grey", "定性数据不足"
    verdicts.append({
        "persona": "段永平",
        "style": "好生意·产品驱动",
        "signal": sig,
        "reason": r,
    })

    # ── 5. 卡拉曼 (深度价值) ──────────────────────────────────────
    if abs_underval_triggered:
        sig = "green"
        parts = [k for k, v in underval.get("conditions", {}).items() if v.get("pass")]
        r = f"绝对低估触发({', '.join(parts)})，深度价值机会"
    elif pe and pe < 15:
        sig = "yellow"
        r = f"PE {pe}x < 15x，估值偏低但未到极端水平"
    elif pe and pe < 25:
        sig = "yellow"
        r = f"PE {pe}x 处于合理区间，安全边际不足"
    else:
        sig = "red"
        r = f"PE {pe}x 偏高，没有足够的安全边际"
    # Add net cash context
    if cash_net and price:
        r += f" | 净现金占市值比值得关注"
    verdicts.append({
        "persona": "卡拉曼 (Klarman)",
        "style": "深度价值·安全边际",
        "signal": sig,
        "reason": r,
    })

    # ── 6. 彼得·林奇 (GARP) ──────────────────────────────────────
    if rg_calc > 15 and pe and 0 < pe < 25:
        sig = "green"
        r = f"营收增长{rg_calc:.0f}%，PE {pe}x，PEG有吸引力"
    elif rg_calc > 5 and pe and 0 < pe < 20:
        sig = "yellow"
        r = f"营收增长{rg_calc:.0f}% PE {pe}x，PEG合理但不是大发现"
    elif rg_calc <= 0 or not pe:
        sig = "red"
        r = f"营收增长{rg_calc:.0f}%，无增长则PEG = ∞，林奇不会买"
    else:
        sig = "yellow"
        r = f"增长{rg_calc:.0f}%/PE {pe}x 组合一般"
    verdicts.append({
        "persona": "彼得·林奇 (Lynch)",
        "style": "GARP·合理价格增长",
        "signal": sig,
        "reason": r,
    })

    return verdicts


def _deep_value_conditions(l1: dict, l2b: dict, fundamentals: dict, l2a: dict) -> dict:
    """Check all 4 Deep Value Path conditions."""
    roe = fundamentals.get("roe_pct") or 0
    pe = fundamentals.get("trailing_pe") or 99
    pb = fundamentals.get("pb") or 99
    fcf = fundamentals.get("fcf_annual", [])

    # A. 好生意: ROE > 10%
    cond_a = {"check": "好生意", "pass": roe > 10}
    # B. 极端低估: PE < 15 or PB < 1
    cond_b = {"check": "极端低估", "pass": pe < 15 or pb < 1}
    # C. 非价值陷阱: FCF positive (or capex-driven)
    latest_fcf = fcf[0] if fcf else 0
    cond_c = {"check": "非价值陷阱", "pass": latest_fcf > 0 or latest_fcf is not None}
    # D. 回归催化剂: buybacks or improving margins
    # Proxy: revenue growth positive or improving margins
    cond_d = {"check": "回归催化剂", "pass": fundamentals.get("revenue_growth_pct", 0) > 0}

    all_pass = all(c["pass"] for c in (cond_a, cond_b, cond_c, cond_d))
    return {
        "all_pass": all_pass,
        "conditions": [cond_a, cond_b, cond_c, cond_d],
    }


def deep_collision(l1: dict, l2b: dict, fundamentals: dict,
                   l2a: dict = None, market: dict = None,
                   dk: dict = None, degradation: dict = None) -> dict:
    """Priority-ordered rule tree returning one decision dict."""
    if market is None:
        market = {}
    if dk is None:
        dk = {}
    if degradation is None:
        degradation = {}

    # Degradation weight: if any input data is degraded, reduce factor impact
    m_degraded = degradation.get("m_layer", False) or False
    l2b_degraded = degradation.get("l2b", False) or False
    any_degraded = m_degraded or l2b_degraded
    degrade_weight = 0.5 if any_degraded else 1.0  # degraded data → half weight

    if l2a is None:
        l2a = proxy_l2a_lights(fundamentals, degraded=any_degraded)

    l1_light = _get_l1_light(l1)
    l2a_biz = l2a.get("好生意", {}).get("light", "GREEN")
    l2a_moat = l2a.get("护城河", {}).get("light", "GREEN")
    l2a_safe = l2a.get("安全边际", {}).get("light", "GREEN")

    # DK assessment defaults (GREEN when not provided)
    dk_coordinate = dk.get("坐标原则", "GREEN")
    dk_nation = dk.get("家国原则", "GREEN")
    dk_price = dk.get("息价原则", "GREEN")
    dk_tradeoff = dk.get("取舍原则", "GREEN")
    dk_lights = [dk_coordinate, dk_nation, dk_price, dk_tradeoff]
    dk_any_red = any(v == "RED" for v in dk_lights)
    dk_all_green = all(v == "GREEN" for v in dk_lights)
    dk_margin_lt_30 = dk.get("安全边际_pct", 100) < 30

    # L2b signals summary
    factors = _get_l2b_factors(l2b)
    l2b_available = len(factors) > 0
    l2b_bull = sum(1 for f in factors if f.get("signal") == "BULL")
    l2b_bear = sum(1 for f in factors if f.get("signal") == "BEAR")

    # M layer context
    m_macro = market.get("macro", "🟡") if isinstance(market, dict) else "🟡"
    m_valuation = market.get("valuation", "🟡")
    m_sentiment = market.get("sentiment", "🟡")

    # ── Conflicts tracking ──────────────────────────────────────────
    conflicts = []

    # ── Rule 1: 好生意/护城河 RED → PASS ────────────────────────────
    if l2a_biz == "RED" or l2a_moat == "RED":
        return {
            "decision": "PASS",
            "confidence": "high",
            "position_pct": 0,
            "applicable_rule": 1,
            "reason": f"好生意({l2a_biz})或护城河({l2a_moat})为RED — 商业模式受损",
            "conflicts": conflicts,
            "next_steps": "待L2a定性分析确认商业模式是否真正受损",
        }

    # ── Rule 10 (DK): 任何 DK 🔴 → PASS ──────────────────────
    if dk_any_red:
        red_principles = [k for k, v in dk.items() if v == "RED"]
        return {
            "decision": "PASS",
            "confidence": "high",
            "position_pct": 0,
            "applicable_rule": 10,
            "reason": f"DK原则拦截: {', '.join(red_principles)} 为🔴 — DK纪律高于一切",
            "conflicts": conflicts,
            "next_steps": "等待相关DK原则改善后再评估",
        }

    # ── L1 RED → Deep Value Path ────────────────────────────────────
    if l1_light == "RED":
        dv = _deep_value_conditions(l1, l2b, fundamentals, l2a)
        if dv["all_pass"]:
            return {
                "decision": "BUY",
                "confidence": "medium",
                "position_pct": 40,
                "applicable_rule": "deep_value",
                "reason": "Deep Value Path: L1 RED但4条件全满足, DCA入场30-50%",
                "deep_value_checks": dv,
                "conflicts": conflicts,
                "next_steps": "DCA入场,设好止损,跟踪基本面催化剂",
            }
        else:
            failed = [c["check"] for c in dv["conditions"] if not c["pass"]]
            return {
                "decision": "PASS",
                "confidence": "high",
                "position_pct": 0,
                "applicable_rule": "deep_value",
                "reason": f"L1 RED强制拦截: Deep Value条件不满足({', '.join(failed)})",
                "deep_value_checks": dv,
                "conflicts": conflicts,
                "next_steps": "等待MA50上穿MA120或基本面改善后再评估",
            }

    # ── L1 🟢/🟡 rules ──────────────────────────────────────────────

    # Rule 2: 好生意🟢+护城河🟢+安全边际🔴 → WAIT @ 0%
    if l2a_biz == "GREEN" and l2a_moat == "GREEN" and l2a_safe == "RED":
        return {
            "decision": "WAIT",
            "confidence": "medium",
            "position_pct": 0,
            "applicable_rule": 2,
            "reason": "好生意+护城河🟢 + 安全边际🔴 — WAIT等回调",
            "conflicts": conflicts,
            "next_steps": "设置价格提醒, PE回到合理区间再考虑",
        }

    # Rule 3: 好生意🟢+安全边际🟡 → BUY低置信 @ 30-50%
    if l2a_biz == "GREEN" and l2a_safe == "YELLOW":
        return {
            "decision": "BUY",
            "confidence": "low",
            "position_pct": 40,
            "applicable_rule": 3,
            "reason": "好生意🟢 + 安全边际🟡 — BUY低置信, DCA入场",
            "conflicts": conflicts,
            "next_steps": "DCA入场, 安全边际改善可加仓",
        }

    # ── DK rules 11-13 (priority 5) ──────────────────────────
    # Rule 11: 坐标原则 🔴 → 至少降一级置信度
    if dk_coordinate == "RED":
        return {
            "decision": "WAIT",
            "confidence": "low",
            "position_pct": 0,
            "applicable_rule": 11,
            "reason": "坐标原则🔴 — 无对标支撑的分析不可靠, WAIT",
            "conflicts": conflicts,
            "next_steps": "找到对标基准后再评估",
        }
    if dk_coordinate == "YELLOW":
        conflicts.append({
            "source": "DK 坐标原则",
            "message": "坐标原则🟡 — 对标关系不够清晰, 置信度降一级",
            "handling": "已降置信度, 缩小仓位",
        })

    # Rule 12: 家国原则 🔴 → PASS
    if dk_nation == "RED":
        return {
            "decision": "PASS",
            "confidence": "high",
            "position_pct": 0,
            "applicable_rule": 12,
            "reason": "家国原则🔴 — 方向与国家利益冲突, PASS",
            "conflicts": conflicts,
            "next_steps": "待政策方向明确后再评估",
        }

    # Rule 13: 安全边际<30% (息价原则) → WAIT
    if dk_margin_lt_30 or dk_price == "RED":
        return {
            "decision": "WAIT",
            "confidence": "low",
            "position_pct": 0,
            "applicable_rule": 13,
            "reason": "安全边际<30% — 价格不够便宜, WAIT等回调",
            "conflicts": conflicts,
            "next_steps": "设置价格提醒, 跌到安全边际范围内再考虑",
        }

    # Rule 14: 全部DK🟢+L1🟢 → 调高置信度（双重验证加分）
    dk_boost = dk_all_green and l1_light == "GREEN"
    if dk_boost:
        conflicts.append({
            "source": "DK 双重验证",
            "message": "全部DK原则🟢 + L1纪律🟢 — 双重验证通过, 可调高置信度",
            "handling": "已被用于提升后续规则的置信度和仓位",
        })

    # Rule 4: 好生意🟡+安全边际🟡+绝对低估 → BUY中置信 @ 50-80%
    if l2a_biz == "YELLOW" and l2a_safe == "YELLOW":
        underval = _absolute_undervaluation(fundamentals)
        if underval["triggered"]:
            details = [k for k, v in underval["conditions"].items() if v["pass"]]
            return {
                "decision": "BUY",
                "confidence": "medium",
                "position_pct": 65,
                "applicable_rule": 4,
                "reason": f"好生意🟡+安全边际🟡+绝对低估触发({', '.join(details)}) — BUY中置信",
                "conflicts": conflicts,
                "absolute_valuation": underval,
                "next_steps": "DCA入场, 估值回归均值后可加仓",
            }

    # ── L2a整体🟢 block (rules 5-9) ─────────────────────────────────
    l2a_ok = _l2a_overall_green(l2a)
    m_red = any(m == "🔴" for m in (m_macro, m_valuation, m_sentiment))

    if l2a_ok:
        # Rule 9: 全绿 → BUY满仓（最严格条件优先检查）
        all_green = all(
            l2a.get(k, {}).get("light") == "GREEN"
            for k in ("好生意", "护城河", "安全边际", "管理层", "需求稳定", "会计质量")
        )
        if all_green and l2b_available and l2b_bull >= l2b_bear and l1_light == "GREEN" and not m_red:
            return {
                "decision": "BUY",
                "confidence": "high",
                "position_pct": 100,
                "applicable_rule": 9,
                "reason": "全部🟢 — 全线一致, BUY满仓",
                "conflicts": conflicts,
                "next_steps": "执行买入计划",
            }

        # Rule 8: L2a整体🟢 + L2b🟢 + 无🔴 → BUY高置信 @ 上限
        if l2b_available and l2b_bull > l2b_bear and l1_light == "GREEN" and not m_red:
            return {
                "decision": "BUY",
                "confidence": "high",
                "position_pct": 100,
                "applicable_rule": 8,
                "reason": "L2a整体🟢 + 量化🟢 + 无🔴 — BUY高置信",
                "conflicts": conflicts,
                "next_steps": "执行买入计划, L2a定性完成可确认",
            }

        # Rule 7: L2a整体🟢 + M层🔴 → BUY + 提高安全边际
        if m_red:
            conflicts.append({
                "source": "M层 市场",
                "message": f"宏观({m_macro})/估值({m_valuation})/情绪({m_sentiment}) 指示风险",
                "handling": "已提高安全边际要求, 降低仓位",
            })
            boost_suffix = " + DK双验调高" if dk_boost else ""
            return {
                "decision": "BUY",
                "confidence": "high" if dk_boost else "medium",
                "position_pct": 90 if dk_boost else 70,
                "applicable_rule": 7,
                "reason": f"L2a整体🟢 + M层🔴 — BUY但提高安全边际要求{boost_suffix}",
                "conflicts": conflicts,
                "next_steps": "提高安全边际要求, 缩小仓位",
            }

        # Rule 6: L2a整体🟢 + 其他层🔴 → BUY低置信 @ 30-50%
        if l1_light != "GREEN":
            boost_suffix = " + DK双验调高" if dk_boost else ""
            return {
                "decision": "BUY",
                "confidence": "medium" if dk_boost else "low",
                "position_pct": 60 if dk_boost else 40,
                "applicable_rule": 6,
                "reason": f"L2a整体🟢 + 其他层({l1_light}) — BUY{'中' if dk_boost else '低'}置信{boost_suffix}",
                "conflicts": conflicts,
                "next_steps": "小仓位试探, 等信号改善加仓",
            }

        # Rule 5: L2a整体🟢 + L2b🟡/🔴 → BUY中置信 @ 80%
        if l2b_available and l2b_bear > 0:
            boost_suffix = " + DK双验调高" if dk_boost else ""
            return {
                "decision": "BUY",
                "confidence": "high" if dk_boost else "medium",
                "position_pct": 100 if dk_boost else 80,
                "applicable_rule": 5,
                "reason": f"L2a整体🟢 + 量化有分歧({l2b_bull}B/{l2b_bear}B) — BUY{'高' if dk_boost else '中'}置信{boost_suffix}",
                "conflicts": conflicts,
                "next_steps": "DCA入场",
            }

    # ── Fallback ────────────────────────────────────────────────────
    green_lights = sum(1 for k, v in l2a.items() if isinstance(v, dict) and v.get("light") == "GREEN")
    red_lights = sum(1 for k, v in l2a.items() if isinstance(v, dict) and v.get("light") == "RED")

    if l2a_biz == "GREEN" and l2a.get("需求稳定", {}).get("light") == "RED":
        reason = "好生意GREEN但需求稳定RED - 盈利指标好看但需求在下滑, 可能为价值陷阱"
        next_steps = "运行L2a定性分析确认需求下滑的性质: 临时性vs结构性"
    elif red_lights > green_lights:
        reason = f"L2a代理信号整体偏空(G{green_lights}R{red_lights}) - 多个维度亮红灯"
        next_steps = "运行L2a定性分析确认红灯的真实程度"
    elif green_lights == 0:
        reason = "L2a代理信号全部偏弱 - 各项指标均不理想"
        next_steps = "基本面未改善前不建议入场"
    else:
        reason = f"L2a代理信号矛盾(G{green_lights}R{red_lights}) - 需要定性分析澄清"
        next_steps = "运行L2a定性分析解决矛盾信号后再决策"

    return {
        "decision": "WAIT",
        "confidence": "low",
        "position_pct": 0,
        "applicable_rule": None,
        "reason": reason,
        "conflicts": conflicts,
        "next_steps": next_steps,
    }


# ── I/O helpers ────────────────────────────────────────────────────

def _find_file(ticker: str, prefix: str) -> str:
    """Find layer output file by prefix. Returns path or None."""
    state_dir = os.path.join(RESEARCH, "state")
    companies_dir = os.path.join(RESEARCH, "companies", ticker.upper())
    import glob as gmod

    # Check state file first for output paths
    state_file = os.path.join(state_dir, f"temp_state_{ticker.upper()}.json")
    if os.path.exists(state_file):
        try:
            with open(state_file) as f:
                state = json.load(f)
            for layer, info in state.get("completed", {}).items():
                if layer == prefix and info.get("output"):
                    return info["output"]
        except Exception:
            pass

    # Fallback: search common paths
    candidates = [
        os.path.join(state_dir, f"temp_{prefix}_{ticker.upper()}.json"),
        os.path.join(RESEARCH, f"temp_{prefix}_{ticker.upper()}.json"),
        os.path.join(RESEARCH, f"temp_{prefix}_{ticker.upper()}.md"),
    ]
    if os.path.isdir(companies_dir):
        for p in gmod.glob(os.path.join(companies_dir, "*", "temp", f"{prefix}.json")):
            candidates.insert(0, p)

    # Search new dir convention: research/<TICKER>-*/<date>/<prefix>.*
    for d in gmod.glob(os.path.join(RESEARCH, f"{ticker.upper()}-*")):
        for p in gmod.glob(os.path.join(d, "*", f"{prefix}.*")):
            candidates.insert(0, p)

    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def _read_json(path: str) -> dict:
    """Read and parse a JSON file."""
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _read_fundamentals(ticker: str) -> dict:
    """Build fundamentals dict from combined sources."""
    result = {}

    # Try fengdata output first
    data_file = _find_file(ticker, "02-market")
    if not data_file:
        data_file = os.path.join(RESEARCH, f"temp_m_{ticker.upper()}.json")
    raw = _read_json(data_file)
    fin = raw.get("financials", {}) if isinstance(raw, dict) else raw
    if fin:
        result.update(fin)

    # Try fengfundamentals for deeper data (US stocks)
    # Fundamentally, checking a state file reference or a named file
    ff_file = _find_file(ticker, "fundamentals")
    if not ff_file:
        ff_file = os.path.join(RESEARCH, f"temp_fundamentals_{ticker.upper()}.json")
    ff = _read_json(ff_file)
    if ff.get("ratios"):
        result["fundamentals_ratios"] = ff["ratios"]
    if ff.get("financial_statements"):
        result["fundamentals_statements"] = ff["financial_statements"]

    # Price data
    price_data = raw.get("price", {}) if isinstance(raw, dict) else {}
    if price_data:
        result["price"] = price_data.get("price")
        result["ma50"] = price_data.get("ma50")
        result["ma120"] = price_data.get("ma120")
        result["ma200"] = price_data.get("ma200")

    return result


def _read_market_data(ticker: str) -> dict:
    """Read market sentiment data."""
    market_file = os.path.join(RESEARCH, "market", "latest.json")
    mkt = _read_json(market_file)

    # Build simplified M-layer summary
    temp = mkt.get("temperature", {})
    behavior = mkt.get("behavior", {}).get("baseline", {})

    return {
        "composite_score": temp.get("composite"),
        "composite_label": temp.get("label", "neutral"),
        "macro": behavior.get("reading", "neutral"),
        "valuation": behavior.get("summary", ""),
    }


def main():
    if len(sys.argv) < 2:
        print(json.dumps({
            "error": "Usage: fengcollision.py TICKER [--l1 <file>] [--l2b <file>] "
                     "[--fundamentals <file>] [--market <file>] [--l2a <file>]\n"
                     "  Layers: 03-discipline (L1), 04-quantitative (L2b), "
                     "05-qualitative (L2a), 02-market (M)"
        }, indent=2))
        sys.exit(1)

    ticker = sys.argv[1].upper()

    # Parse optional paths
    paths = {}
    for flag in ("--l1", "--l2b", "--fundamentals", "--market", "--l2a"):
        if flag in sys.argv:
            idx = sys.argv.index(flag)
            paths[flag] = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else None

    # Read inputs
    l1_file = paths.get("--l1") or _find_file(ticker, "03-discipline")
    l2b_file = paths.get("--l2b") or _find_file(ticker, "04-quantitative")
    fundamentals_file = paths.get("--fundamentals")
    market_file = paths.get("--market")
    l2a_file = paths.get("--l2a") or _find_file(ticker, "05-qualitative")

    l1 = _read_json(l1_file)
    l2b = _read_json(l2b_file)
    fundamentals = _read_json(fundamentals_file) if fundamentals_file else _read_fundamentals(ticker)
    market = _read_json(market_file) if market_file else _read_market_data(ticker)
    l2a_raw = _read_json(l2a_file) if l2a_file else None

    # Build L2a qualitative dict (accepts investment-team format or proxy)
    l2a = None
    l2a_source = "not_available"
    if l2a_raw:
        # Check if this is a structured investment-team output
        if "好生意" in l2a_raw or "defensive_moat" in l2a_raw:
            l2a = l2a_raw
            l2a_source = "qualitative_analysis"
    if l2a is None:
        l2a = proxy_l2a_lights(fundamentals)
        l2a_source = "proxy_from_data"
        # degradation will be detected below; update source if needed later
    elif isinstance(l2a, dict) and l2a.get("source", "").startswith("proxy"):
        l2a_source = "proxy_from_data"

    # Track which layers have data
    missing_layers = []
    if not l1:
        missing_layers.append("03-discipline")
    if not l2b:
        missing_layers.append("04-quantitative")
    if not fundamentals:
        missing_layers.append("02-market")

    # Collect dissenting signals from ALL layers first
    l2a_lights_dict = {k: v for k, v in l2a.items() if isinstance(v, dict) and "light" in v}
    dissenting = _collect_dissenting_signals(l1, l2b, fundamentals, market, l2a_lights_dict)

    # Build degradation flags: read data_quality/source from M层 + L2b
    m_raw = _read_json(_find_file(ticker, "02-market"))
    degradation = {}
    if m_raw:
        m_dq = m_raw.get("data_quality", "")
        m_src = m_raw.get("source", "")
        degradation["m_layer"] = m_dq in ("degraded", "corrected") or m_src == "degraded"
    if l2b:
        l2b_src = l2b.get("source", "")
        l2b_note = l2b.get("note", "")
        degradation["l2b"] = l2b_src == "degraded" or ("deg" in l2b_src.lower())

    any_degraded = any(degradation.values())

    # Update l2a_source if proxy was generated from degraded data
    if any_degraded and l2a_source == "proxy_from_data":
        l2a_source = "proxy_from_degraded_data"

    # Run collision with degradation context
    decision = deep_collision(l1, l2b, fundamentals, l2a, market, degradation=degradation)

    # Merge conflicts: dissenting signals + decision-specific conflicts
    all_conflicts = dissenting["conflicts"] + decision.get("conflicts", [])

    # Apply degradation adjustment to confidence and position
    if any_degraded and decision["decision"] == "BUY":
        conf_map = {"high": 2, "medium": 1, "low": 0}
        conf_val = conf_map.get(decision["confidence"], 1)
        degraded_conf = max(0, conf_val - 1)
        rev_map = {2: "high", 1: "medium", 0: "low"}
        new_conf = rev_map[degraded_conf]
        decision["confidence"] = new_conf
        decision["position_pct"] = int(decision["position_pct"] * 0.5)
        degraded_sources = [k for k, v in degradation.items() if v]
        all_conflicts.append({
            "source": "数据质量",
            "message": f"输入数据含降级源（{', '.join(degraded_sources)}），置信度降一级，仓位减半",
            "handling": "已自动降级处理",
        })

    # Build output
    result = {
        "ticker": ticker,
        "collided_at": datetime.now().isoformat(),
        "decision": decision["decision"],
        "confidence": decision["confidence"],
        "position_pct": decision["position_pct"],
        "applicable_rule": decision.get("applicable_rule"),
        "reason": decision.get("reason", ""),
        "layer_summary": {
            "l1_light": _get_l1_light(l1),
            "l2b_bull": sum(1 for f in _get_l2b_factors(l2b) if f.get("signal") == "BULL") if l2b else None,
            "l2b_bear": sum(1 for f in _get_l2b_factors(l2b) if f.get("signal") == "BEAR") if l2b else None,
            "market_red_lights": dissenting.get("market_red_lights", []),
            "l1_failed_checks": len(dissenting.get("l1_failed_checks", [])),
        },
        "l2a_source": l2a_source,
        "l2a_lights": {k: v["light"] for k, v in l2a.items() if isinstance(v, dict) and "light" in v},
        "dissenting_signals": {
            "l2b_bear_factors": dissenting.get("l2b_bear_factors", []),
            "l1_failed_checks": dissenting.get("l1_failed_checks", []),
            "market_red_lights": dissenting.get("market_red_lights", []),
            "l2a_weak_lights": dissenting.get("l2a_weak_lights", []),
            "fundamental_warnings": dissenting.get("fundamental_warnings", []),
        },
        "adversarial_check": {
            "questions": dissenting.get("adversarial_questions", []),
            "note": "完整反方强制检查（4问）需L3 Skill在06-collision.md中完成",
        },
        "conflicts": all_conflicts,
        "degradation": {
            "detected": any_degraded,
            "sources": {k: v for k, v in degradation.items() if v},
            "weight": 0.5 if any_degraded else 1.0,
        },
        "deep_value_checks": decision.get("deep_value_checks"),
        "absolute_valuation": decision.get("absolute_valuation"),
        "missing_layers": missing_layers,
        "next_steps": decision.get("next_steps", ""),
        "persona_panel": {
            "disclaimer": "基于公开数据和已知投资风格的模式匹配，仅供参考，非真实投资建议",
            "verdicts": _persona_verdicts(l1, l2b, fundamentals, l2a, market, ticker),
        },
    }

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
