#!/usr/bin/env python3
"""
fengportfolio — P层 组合风险管理检查（正交维度 · 人民币一盘棋）。

风险归并按「正交维度」计算，不预设任何命名桶：
  - market   资产类别/家国市场（CN_A A股 / CN_HK 港股通 / CN_OVS 中概境外 / US / GLOBAL …）
  - segment  细分板块（互联网 / 半导体·AI算力 / 保险 …）
  - qualifier 现金属性（cash 真现金 / quasi_cash 准现金）
任一维度 + 任意组合（如 market×segment）都由运行期分组求和得出，
买新标的/新板块时直接加词即可，无需改代码。

资金墙（capital_zone）只作「买入预算」提示，不再产生任何风险告警。

Usage:
    python fengportfolio.py check        # 组合检查（JSON输出）
    python fengportfolio.py status       # 仪表盘（人类可读）
    python fengportfolio.py sector       # 板块集中度（segment 轴）
    python fengportfolio.py correlate    # 两两相关性矩阵
    python fengportfolio.py stress       # 宏观情景压力测试

数据来源: holdings/hold_*.json（真源）；汇率实时取自 fengdata --mode fx，失败回退快照。
"""

import json, os, re, sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOLDINGS_DIR = os.path.join(BASE, "holdings")
RESEARCH = os.path.join(BASE, "research")

# 汇率快照（2026-08-12 实测）—— 运行时优先取实时，失败回退此表
FX = {"CNY": 1.0, "HKD": 0.8586, "USD": 6.7414}

# 集中度阈值（占总资产%）
THRESH = {
    "market": {"red": 35, "yellow": 28},
    "segment": {"red": 25, "yellow": 20},
    "combo": {"red": 20, "yellow": 15},
    "single": {"red": 20, "yellow": 15},
}


def _get_fx():
    """实时汇率（fengdata._fx_rates），失败回退 FX 快照。带模块级缓存。"""
    global FX
    try:
        import fengdata as F
        r = F._fx_rates()
        if r and r.get("USDCNY") and r.get("HKDCNY"):
            FX = {"CNY": 1.0, "HKD": r["HKDCNY"], "USD": r["USDCNY"]}
            return {"FX": FX, "live": bool(r.get("live")), "date": r.get("date")}
    except Exception:
        pass
    return {"FX": FX, "live": False, "date": "snapshot"}


_FX_INFO = None


def fx_info():
    global _FX_INFO
    if _FX_INFO is None:
        _FX_INFO = _get_fx()
    return _FX_INFO


def parse_portfolio():
    """从 holdings/ 读取真实持仓（真源），返回规范化持仓列表。

    每个 position 含: id/name/asset_type/currency/zone(资金墙,仅供买入预算)/
                    market(资产类别)/segment(板块)/qualifier(现金属性)/
                    qty/avg_cost/current_price/market_value/market_value_cny/
                    sector(=segment 兼容)/return_pct/market_access。
    """
    fx = fx_info()["FX"]
    positions = []
    if not os.path.isdir(HOLDINGS_DIR):
        print(f"ERROR: holdings/ 目录不存在: {HOLDINGS_DIR}")
        return []
    for f in sorted(os.listdir(HOLDINGS_DIR)):
        m = re.match(r"^hold_([A-Za-z0-9_.]+)\.json$", f)
        if not m:
            continue
        try:
            with open(os.path.join(HOLDINGS_DIR, f), encoding="utf-8") as fh:
                h = json.load(fh)
        except Exception:
            continue
        cur = h.get("currency", "CNY")
        fxr = fx.get(cur, 1.0)
        p = h.get("position", {})
        qty = p.get("shares") or p.get("units") or 0
        avg = p.get("avg_cost") or p.get("nav") or p.get("amount") or 0
        px = p.get("current_price") or p.get("nav") or p.get("amount") or 0
        mv = p.get("market_value") or (qty * px) or (p.get("amount") or 0)
        hid = h.get("id") or h.get("ticker") or m.group(1)
        ret = (px / avg - 1) * 100 if (avg and px) else None
        pos = {
            "id": hid,
            "name": h.get("name", ""),
            "asset_type": h.get("asset_type", "stock"),
            "currency": cur,
            "zone": h.get("capital_zone", "CN_IN" if cur == "CNY" else "OVERSEAS"),
            "market": h.get("market", "其他"),
            "segment": h.get("segment", "其他"),
            "qualifier": h.get("qualifier"),
            "qty": qty,
            "avg_cost": avg,
            "current_price": px,
            "market_value": mv,
            "market_value_cny": round(mv * fxr, 2),
            "sector": h.get("segment") or h.get("sector", "其他"),  # 兼容旧字段
            "return_pct": round(ret, 1) if ret is not None else None,
            "market_access": h.get("market_access"),  # hksi=港股通
        }
        positions.append(pos)
    return positions


def _is_pool(p):
    """资金池：真现金(cash) + 准现金(quasi_cash，低波高息当现金用)。"""
    return p.get("qualifier") in ("cash", "quasi_cash") or p.get("asset_type") == "cash"


def check_concentration(positions):
    """按正交维度分组求和（不预设桶），返回分布 + 集中度告警。

    - market 轴：各资产类别占总量%
    - segment 轴：各板块占总量%
    - combo  轴：market×segment 组合占总量%（如 CN_OVS×互联网 自然浮现）
    - 资金池：真现金% + 准现金%（qualifier），不参与权益集中度
    - 单标：占总量% 超阈告警
    """
    total = sum(p["market_value_cny"] for p in positions) or 1
    equity = [p for p in positions if not _is_pool(p)]
    equity_mv = sum(p["market_value_cny"] for p in equity)

    pool_cash = sum(p["market_value_cny"] for p in positions if p.get("qualifier") == "cash")
    pool_quasi = sum(p["market_value_cny"] for p in positions if p.get("qualifier") == "quasi_cash")

    warnings = []

    # 单标（权益，占总资产%）
    for p in equity:
        w = p["market_value_cny"] / total * 100
        if w > THRESH["single"]["red"]:
            warnings.append(f"🔴 单标超限: {p['id']} ({w:.1f}% > {THRESH['single']['red']}%)")
        elif w > THRESH["single"]["yellow"]:
            warnings.append(f"🟡 单标接近上限: {p['id']} ({w:.1f}%)")

    # market 轴
    market_w = {}
    for p in equity:
        market_w[p["market"]] = market_w.get(p["market"], 0) + p["market_value_cny"]
    for mk, v in market_w.items():
        w = v / total * 100
        if w > THRESH["market"]["red"]:
            warnings.append(f"🔴 资产类别超限: {mk} ({w:.1f}% > {THRESH['market']['red']}%)")
        elif w > THRESH["market"]["yellow"]:
            warnings.append(f"🟡 资产类别偏高: {mk} ({w:.1f}%)")

    # segment 轴
    seg_w = {}
    for p in equity:
        seg_w[p["segment"]] = seg_w.get(p["segment"], 0) + p["market_value_cny"]
    for s, v in seg_w.items():
        w = v / total * 100
        if w > THRESH["segment"]["red"]:
            warnings.append(f"🔴 板块超限: {s} ({w:.1f}% > {THRESH['segment']['red']}%)")
        elif w > THRESH["segment"]["yellow"]:
            warnings.append(f"🟡 板块偏高: {s} ({w:.1f}%)")

    # combo 轴（market×segment）
    combo_w = {}
    for p in equity:
        key = f"{p['market']}×{p['segment']}"
        combo_w[key] = combo_w.get(key, 0) + p["market_value_cny"]
    for k, v in combo_w.items():
        w = v / total * 100
        if w > THRESH["combo"]["red"]:
            warnings.append(f"🔴 组合集中: {k} ({w:.1f}% > {THRESH['combo']['red']}%)")
        elif w > THRESH["combo"]["yellow"]:
            warnings.append(f"🟡 组合偏高: {k} ({w:.1f}%)")

    return {
        "total_value": round(total, 2),
        "equity_value": round(equity_mv, 2),
        "equity_pct": equity_mv / total * 100,
        "pool": {
            "true_cash": round(pool_cash, 2),
            "true_cash_pct": pool_cash / total * 100,
            "quasi_cash": round(pool_quasi, 2),
            "quasi_cash_pct": pool_quasi / total * 100,
            "pool_total": round(pool_cash + pool_quasi, 2),
            "pool_pct": (pool_cash + pool_quasi) / total * 100,
        },
        "market_axis": {k: {"value": round(v, 2), "pct_total": v / total * 100,
                            "pct_equity": v / equity_mv * 100 if equity_mv else 0}
                        for k, v in sorted(market_w.items(), key=lambda x: -x[1])},
        "segment_axis": {k: {"value": round(v, 2), "pct_total": v / total * 100,
                             "pct_equity": v / equity_mv * 100 if equity_mv else 0}
                         for k, v in sorted(seg_w.items(), key=lambda x: -x[1])},
        "combo_axis": {k: {"value": round(v, 2), "pct_total": v / total * 100,
                           "pct_equity": v / equity_mv * 100 if equity_mv else 0}
                       for k, v in sorted(combo_w.items(), key=lambda x: -x[1])},
        "warnings": warnings,
    }


def check_drawdown(positions):
    """Check current drawdown status."""
    max_single_drawdown = 0
    worst_position = None

    for p in positions:
        ret = p.get("return_pct")
        if ret is not None and ret < 0:
            if abs(ret) > abs(max_single_drawdown):
                max_single_drawdown = ret
                worst_position = p["id"]

    return {
        "max_single_drawdown": max_single_drawdown,
        "worst_position": worst_position,
    }


def check_budget(positions):
    """资金墙 = 买入预算提示（境内池/境外池余额），不产生告警。"""
    zones = {}
    for p in positions:
        z = p.get("zone") or "其他"
        zones[z] = zones.get(z, 0) + p["market_value_cny"]
    return {z: round(v, 2) for z, v in sorted(zones.items(), key=lambda x: -x[1])}


def cmd_check():
    """Full P layer check — JSON: 正交维度盘面 + 资金池 + 买入预算。"""
    positions = parse_portfolio()
    if not positions:
        sys.exit(1)

    c = check_concentration(positions)
    d = check_drawdown(positions)
    fx = fx_info()

    lights = []
    if c["warnings"]:
        has_red = any(w.startswith("🔴") for w in c["warnings"])
        lights.append("RED" if has_red else "YELLOW")
    else:
        lights.append("GREEN")
    if d["max_single_drawdown"] < -20:
        lights.append("RED")
    elif d["max_single_drawdown"] < -15:
        lights.append("YELLOW")
    else:
        lights.append("GREEN")
    light_order = {"GREEN": 0, "YELLOW": 1, "RED": 2}
    overall = max(lights, key=lambda x: light_order.get(x, 0))

    result = {
        "checked_at": datetime.now().isoformat(),
        "overall_light": overall,
        "fx": {"live": fx["live"], "date": fx["date"], "USDCNY": fx["FX"]["USD"], "HKDCNY": fx["FX"]["HKD"]},
        "overview": {
            "total_value": c["total_value"],
            "equity_value": c["equity_value"],
            "equity_pct": round(c["equity_pct"], 1),
            "pool_pct": round(c["pool"]["pool_pct"], 1),
        },
        "pool": c["pool"],
        "market_axis": c["market_axis"],
        "segment_axis": c["segment_axis"],
        "combo_axis": c["combo_axis"],
        "warnings": c["warnings"],
        "drawdown": d,
        "budget": check_budget(positions),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _flag(w, th):
    return '🔴' if w > th["red"] else '🟡' if w > th["yellow"] else '🟢'


def cmd_status():
    """Human-readable dashboard: 正交维度盘面 + 资金池 + 买入预算。"""
    positions = parse_portfolio()
    if not positions:
        print("## 组合盘面")
        print(" · holdings/ 目录为空或无法读取")
        return 0

    c = check_concentration(positions)
    d = check_drawdown(positions)
    budget = check_budget(positions)
    fx = fx_info()

    print("## 组合盘面（正交维度 · 人民币一盘棋）")
    fx_note = "实时" if fx["live"] else f"快照({fx['date']})"
    print(f"  汇率: USDCNY={fx['FX']['USD']:.4f} HKDCNY={fx['FX']['HKD']:.4f} [{fx_note}]")
    print(f"\n[总览]")
    print(f" · 总资产        {c['total_value']:,.0f}")
    print(f" · 权益          {c['equity_value']:,.0f} ({c['equity_pct']:.1f}%)")
    print(f" · 资金池        {c['pool']['pool_total']:,.0f} ({c['pool']['pool_pct']:.1f}%)")
    print(f"    真现金       {c['pool']['true_cash']:,.0f} ({c['pool']['true_cash_pct']:.1f}%)")
    print(f"    准现金       {c['pool']['quasi_cash']:,.0f} ({c['pool']['quasi_cash_pct']:.1f}%)  <- 低波高息当现金")

    print(f"\n[资产类别 market]")
    for mk, v in c["market_axis"].items():
        print(f"  {_flag(v['pct_total'], THRESH['market'])} {mk:12s} {v['pct_total']:5.1f}%  (占权益 {v['pct_equity']:.1f}%)")

    print(f"\n[板块 segment]")
    for s, v in c["segment_axis"].items():
        print(f"  {_flag(v['pct_total'], THRESH['segment'])} {s:12s} {v['pct_total']:5.1f}%  (占权益 {v['pct_equity']:.1f}%)")

    print(f"\n[组合集中 market×segment]")
    for k, v in c["combo_axis"].items():
        print(f"  {_flag(v['pct_total'], THRESH['combo'])} {k:24s} {v['pct_total']:5.1f}%  (占权益 {v['pct_equity']:.1f}%)")

    print(f"\n[买入预算 · 资金墙=划转约束，非配置维度]")
    for z, v in budget.items():
        print(f"  💰 {z:9s} 池 ¥{v:,.0f}")

    print(f"\n最大单标回撤   {d['max_single_drawdown']:.0f}% ({d['worst_position'] or '无'})")
    if c['warnings']:
        print(f"\n警告 ({len(c['warnings'])}):")
        for w in c['warnings']:
            print(f"  {w}")
    else:
        print("\n✅ 组合结构正常，无警告")
    return 0


def cmd_sector():
    """板块集中度（segment 轴）。"""
    positions = parse_portfolio()
    if not positions:
        print("无可分析持仓")
        return 0

    c = check_concentration(positions)
    print("板块集中度（segment 轴 · 占总资产%）")
    print(f"{'板块':16s} {'占总资产':>8s} {'上限':>8s} {'状态':>6s}")
    print("-" * 44)
    for s, v in c["segment_axis"].items():
        flag = _flag(v['pct_total'], THRESH['segment'])
        print(f"{s:16s} {v['pct_total']:7.1f}% {THRESH['segment']['red']:7d}% {flag:>6s}")
    return 0


def cmd_correlate():
    """Pairwise correlation matrix of all positions（修复：用 id 而非失效的 ticker）。"""
    positions = parse_portfolio()
    if not positions:
        print("{}")
        return 0

    ids = [p["id"] for p in positions]
    try:
        import yfinance as yf
        import pandas as pd
        import numpy as np
    except ImportError:
        print(json.dumps({"error": "需要 yfinance/pandas/numpy（未安装，跳过相关性）"}, indent=2, ensure_ascii=False))
        return 0

    data = yf.download(ids, period="1y", progress=False, auto_adjust=True)
    if data.empty:
        print("{}")
        return 0

    if isinstance(data.columns, pd.MultiIndex):
        close = data["Close"]
    else:
        close = data
    returns = close.pct_change().dropna()
    corr = returns.corr()
    triu = np.triu_indices_from(corr.values, k=1)
    avg_corr = round(float(corr.values[triu].mean()), 3) if len(ids) > 1 and triu[0].size > 0 else 1.0

    result = {
        "ids": ids,
        "correlation_matrix": corr.round(3).to_dict(),
        "avg_correlation": avg_corr,
        "note": "需 yfinance+pandas+numpy（本机可选安装）",
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_stress():
    """宏观情景压力测试（修复：用 market_value_cny 而非失效的 weight_pct）。"""
    positions = parse_portfolio()
    if not positions:
        print("[]")
        return 0

    total = sum(p["market_value_cny"] for p in positions) or 1
    equity = [p for p in positions if not _is_pool(p)]
    pool_pct = 100 - sum(p["market_value_cny"] for p in equity) / total * 100

    def seg(p):
        return p.get("segment", "")

    scenarios = [
        {
            "name": "inflation_shock",
            "label": "通胀反弹 · 利率升2%",
            "impact": "高估值成长/长久期资产受压，价值/现金牛受益",
            "est_drawdown_pct": -12,
            "hit": lambda p: seg(p) in ("半导体.AI算力", "互联网", "消费电子"),
        },
        {
            "name": "recession",
            "label": "经济衰退 · 消费萎缩",
            "impact": "可选消费/旅游承压，防御性资产(医药/低波)对冲",
            "est_drawdown_pct": -18,
            "hit": lambda p: seg(p) in ("互联网", "消费电子", "旅游", "家电"),
        },
        {
            "name": "market_crash",
            "label": "市场恐慌 · VIX>40",
            "impact": "所有风险资产同跌，现金/准现金为王",
            "est_drawdown_pct": -25,
            "hit": lambda p: not _is_pool(p),
        },
        {
            "name": "china_policy",
            "label": "中国监管/地缘冲击",
            "impact": "中概/港股通(CN_OVS, CN_HK)承压，境内A股相对受益",
            "est_drawdown_pct": -15,
            "hit": lambda p: p.get("market") in ("CN_OVS", "CN_HK"),
        },
    ]

    for s in scenarios:
        affected = sum(p["market_value_cny"] for p in positions if s["hit"](p))
        s["affected_value"] = round(affected, 2)
        s["affected_pct"] = round(affected / total * 100, 1)
        s["portfolio_impact_pct"] = round(affected / total * 100 * s["est_drawdown_pct"] / 100, 1)
        s["cash_buffer"] = round(pool_pct, 1)
        del s["hit"]

    print(json.dumps(scenarios, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    cmds = {
        "check": cmd_check,
        "status": cmd_status,
        "sector": cmd_sector,
        "correlate": cmd_correlate,
        "stress": cmd_stress,
    }

    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("FengInvest P层 — 组合风险管理（正交维度 · 人民币一盘棋）")
        print()
        print("用法:")
        print("  fengportfolio.py check         - 组合检查（JSON输出）")
        print("  fengportfolio.py status        - 仪表盘（人类可读）")
        print("  fengportfolio.py sector        - 板块集中度（segment 轴）")
        print("  fengportfolio.py correlate     - 两两相关性矩阵")
        print("  fengportfolio.py stress        - 宏观情景压力测试")
        print()
        print("数据来源: holdings/hold_*.json（真源）")
        print("分类维度: market(资产类别) × segment(板块) × qualifier(现金属性)")
        sys.exit(1)

    sys.exit(cmds[sys.argv[1]]())
