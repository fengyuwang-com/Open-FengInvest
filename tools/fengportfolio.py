#!/usr/bin/env python3
"""
fengportfolio — P层 组合风险管理检查。

检查组合仪表盘指标：总仓位/行业集中度/相关性/回撤/汇率敞口等。

Usage:
    python fengportfolio.py check        # 检查当前组合（从 portfolio/current.md 读取）
    python fengportfolio.py status       # 查看组合仪表盘
    python fengportfolio.py sector       # 行业集中度分析
    python fengportfolio.py correlate    # 两两相关性矩阵
    python fengportfolio.py stress       # 宏观情景压力测试

读取 portfolio/current.md 中的持仓数据，计算组合级指标。
"""

import json, os, re, sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORTFOLIO_FILE = os.path.join(BASE, "portfolio", "current.md")
RESEARCH = os.path.join(BASE, "research")


def parse_portfolio():
    """Parse portfolio/current.md into a list of positions."""
    if not os.path.exists(PORTFOLIO_FILE):
        print(f"ERROR: 组合文件不存在: {PORTFOLIO_FILE}")
        return None

    with open(PORTFOLIO_FILE, encoding="utf-8") as f:
        text = f.read()

    # Parse markdown table format
    positions = []
    lines = text.split("\n")
    in_table = False
    headers = []

    for line in lines:
        line = line.strip()
        if line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line.split("|")[1:-1]]

            # Header row detection
            if "标的" in line and "仓位" in line and "行业" in line:
                headers = cells
                in_table = True
                continue

            # Separator row (|---|---|)
            if set(line.replace("|", "").replace("-", "").replace(":", "")) == set():
                continue

            if in_table and len(cells) >= 5:
                pos = {
                    "ticker": cells[0].strip(" **"),
                    "name": cells[1] if len(cells) > 1 else "",
                    "sector": cells[2] if len(cells) > 2 else "",
                    "weight_pct": float(cells[3].replace("%", "")) if len(cells) > 3 and "%" in cells[3] else 0,
                    "cost_basis": cells[4] if len(cells) > 4 else "",
                    "return_pct": float(cells[5].replace("%", "")) if len(cells) > 5 and "%" in cells[5] else None,
                }
                positions.append(pos)
        else:
            in_table = False

    return positions


def check_concentration(positions):
    """Check sector concentration and single position limits."""
    warnings = []
    total = sum(p["weight_pct"] for p in positions)

    # Single position limits
    for p in positions:
        if p["weight_pct"] > 20:
            warnings.append(f"🔴 单标超限: {p['ticker']} ({p['weight_pct']}% > 20%)")
        elif p["weight_pct"] > 15:
            warnings.append(f"🟡 单标接近上限: {p['ticker']} ({p['weight_pct']}%)")

    # Sector concentration
    sector_weights = {}
    for p in positions:
        sector = p.get("sector", "未知")
        sector_weights[sector] = sector_weights.get(sector, 0) + p["weight_pct"]

    for sector, weight in sector_weights.items():
        if weight > 30:
            warnings.append(f"🔴 行业超限: {sector} ({weight:.0f}% > 30%)")
        elif weight > 25:
            warnings.append(f"🟡 行业偏高: {sector} ({weight:.0f}%)")

    return {
        "total_pct": total,
        "cash_pct": max(0, 100 - total),
        "position_count": len(positions),
        "sector_weights": sector_weights,
        "warnings": warnings,
    }


def check_drawdown(positions):
    """Check current drawdown status."""
    total_return = 0
    max_single_drawdown = 0
    worst_position = None

    for p in positions:
        ret = p.get("return_pct")
        if ret is not None and ret < 0:
            if abs(ret) > abs(max_single_drawdown):
                max_single_drawdown = ret
                worst_position = p["ticker"]

    return {
        "max_single_drawdown": max_single_drawdown,
        "worst_position": worst_position,
    }


def cmd_check():
    """Full P layer check — output dashboard JSON."""
    positions = parse_portfolio()
    if positions is None:
        sys.exit(1)

    concentration = check_concentration(positions)
    drawdown = check_drawdown(positions)

    # Determine overall light
    lights = []
    if concentration["total_pct"] > 85:
        lights.append("RED")  # 仓位太高
    elif concentration["total_pct"] > 75:
        lights.append("YELLOW")
    else:
        lights.append("GREEN")

    if concentration["cash_pct"] < 10:
        lights.append("RED")
    elif concentration["cash_pct"] < 15:
        lights.append("YELLOW")
    else:
        lights.append("GREEN")

    if concentration["warnings"]:
        has_red = any(w.startswith("🔴") for w in concentration["warnings"])
        lights.append("RED" if has_red else "YELLOW")
    else:
        lights.append("GREEN")

    if drawdown["max_single_drawdown"] < -20:
        lights.append("RED")  # 单标跌破硬止损
    elif drawdown["max_single_drawdown"] < -15:
        lights.append("YELLOW")  # 接近硬止损
    else:
        lights.append("GREEN")

    light_order = {"GREEN": 0, "YELLOW": 1, "RED": 2}
    overall = max(lights, key=lambda x: light_order.get(x, 0))

    result = {
        "checked_at": datetime.now().isoformat(),
        "overall_light": overall,
        "dashboard": {
            "total_position": f"{concentration['total_pct']:.0f}%",
            "cash": f"{concentration['cash_pct']:.0f}%",
            "position_count": concentration['position_count'],
            "sector_weights": {k: f"{v:.0f}%" for k, v in concentration['sector_weights'].items()},
            "warnings": concentration['warnings'],
        },
        "drawdown": drawdown,
    }

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_status():
    """Human-readable portfolio dashboard."""
    positions = parse_portfolio()
    if positions is None:
        # Show empty dashboard template
        print("## 组合仪表盘")
        print(" · 总仓位         0%   ▸ 上限85%")
        print(" · 现金           100% ▸ 建议15-25% 🟡")
        print(" · 持仓数量       0")
        print(" · 行业分布       (无)")
        print("")
        print(">> portfolio/current.md 未创建或为空。")
        print(">> 新建持仓后在 portfolio/current.md 中按格式填写。")
        print(">> 格式: | 标的 | 名称 | 行业 | 仓位% | 成本 | 收益率% |")
        return 0

    c = check_concentration(positions)
    d = check_drawdown(positions)

    print("## 组合仪表盘")
    print(f" · 总仓位         {c['total_pct']:.0f}%   ▸ 上限85% {'🟢' if c['total_pct'] <= 75 else '🟡' if c['total_pct'] <= 85 else '🔴'}")
    print(f" · 现金           {c['cash_pct']:.0f}%   ▸ 建议15-25% {'🟢' if 15 <= c['cash_pct'] <= 25 else '🟡' if c['cash_pct'] >= 10 else '🔴'}")
    print(f" · 持仓数量       {c['position_count']}")
    print(f" · 最大单标回撤   {d['max_single_drawdown']:.0f}% ({d['worst_position'] or '无'})")

    print(f"\n行业分布:")
    for sector, w in sorted(c['sector_weights'].items(), key=lambda x: -x[1]):
        flag = '🔴' if w > 30 else '🟡' if w > 20 else '🟢'
        print(f"  {flag} {sector}: {w:.0f}%")

    if c['warnings']:
        print(f"\n警告 ({len(c['warnings'])}):")
        for w in c['warnings']:
            print(f"  {w}")
    else:
        print("\n✅ 组合结构正常，无警告")

    return 0


def cmd_sector():
    """Sector concentration breakdown."""
    positions = parse_portfolio()
    if not positions:
        print("无可分析持仓")
        return 0

    c = check_concentration(positions)
    print(f"{'行业':20s} {'仓位':>8s} {'上限':>8s} {'状态':>6s}")
    print("-" * 44)
    for sector, w in sorted(c['sector_weights'].items(), key=lambda x: -x[1]):
        flag = '🔴' if w > 30 else '🟡' if w > 20 else '🟢'
        print(f"{sector:20s} {w:>7.0f}% {30:>7d}% {flag:>6s}")
    print(f"\n合计: {c['total_pct']:.0f}%")
    print(f"现金: {c['cash_pct']:.0f}%")
    return 0


def cmd_correlate():
    """Pairwise correlation matrix of all positions."""
    positions = parse_portfolio()
    if not positions:
        print("{}")
        return 0

    tickers = [p["ticker"] for p in positions]
    import yfinance as yf
    import pandas as pd
    import numpy as np
    # Fetch 1 year of daily returns
    data = yf.download(tickers, period="1y", progress=False, auto_adjust=True)
    if data.empty:
        print("{}")
        return 0

    if isinstance(data.columns, pd.MultiIndex):
        close = data["Close"]
    else:
        close = data

    returns = close.pct_change().dropna()
    corr = returns.corr()

    # Upper triangle mask (k=1 = exclude diagonal)
    triu = np.triu_indices_from(corr.values, k=1)
    avg_corr = round(float(corr.values[triu].mean()), 3) if len(tickers) > 1 and triu[0].size > 0 else 1.0

    result = {
        "tickers": tickers,
        "correlation_matrix": corr.round(3).to_dict(),
        "avg_correlation": avg_corr,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_stress():
    """Macro scenario stress test."""
    positions = parse_portfolio()
    if not positions:
        print("[]")
        return 0

    # Read latest market temp for context
    market_data = {}
    try:
        with open(os.path.join(RESEARCH, "market", "latest.json")) as f:
            market_data = json.load(f)
    except Exception:
        pass

    scenarios = [
        {
            "name": "inflation_shock",
            "label": "通胀反弹 · 利率升2%",
            "impact": "高负债/成长股受压, 价值/现金牛受益",
            "est_drawdown_pct": -12,
            "hit_positions": [p["ticker"] for p in positions
                              if p.get("sector") in ("科技", "成长", "消费")],
        },
        {
            "name": "recession",
            "label": "经济衰退 · 消费萎缩",
            "impact": "可选消费承压, 防御性资产(公用/医疗)对冲",
            "est_drawdown_pct": -18,
            "hit_positions": [p["ticker"] for p in positions
                              if p.get("sector") in ("科技", "消费", "工业")],
        },
        {
            "name": "market_crash",
            "label": "市场恐慌 · VIX>40",
            "impact": "所有风险资产同跌, 现金为王",
            "est_drawdown_pct": -25,
            "hit_positions": [p["ticker"] for p in positions],
        },
        {
            "name": "sector_regulation",
            "label": "行业监管打击",
            "impact": "特定行业受政策冲击",
            "est_drawdown_pct": -15,
            "hit_positions": [],
        },
    ]

    # Apply current temperature context
    temp = market_data.get("temperature", {})
    current_score = temp.get("composite", 50)
    if current_score >= 80:
        scenarios[2]["est_drawdown_pct"] = -30  # More downside at high valuations

    total_pct = sum(p["weight_pct"] for p in positions)

    for s in scenarios:
        affected = sum(p["weight_pct"] for p in positions if p["ticker"] in s["hit_positions"])
        s["affected_position_pct"] = affected
        s["portfolio_impact_pct"] = round(affected * s["est_drawdown_pct"] / 100, 1)
        s["estimated_portfolio_value_after"] = max(0, round(100 + s["portfolio_impact_pct"], 1))
        s["cash_buffer"] = round(100 - total_pct, 1)

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
        print("FengInvest P层 — 组合风险管理")
        print()
        print("用法:")
        print("  fengportfolio.py check         - 组合检查（JSON输出）")
        print("  fengportfolio.py status        - 仪表盘（人类可读）")
        print("  fengportfolio.py sector        - 行业集中度分析")
        print("  fengportfolio.py correlate     - 两两相关性矩阵")
        print("  fengportfolio.py stress        - 宏观情景压力测试")
        print()
        print("数据来源: portfolio/current.md")
        print("格式:    | 标的 | 名称 | 行业 | 仓位% | 成本 | 收益率% |")
        sys.exit(1)

    sys.exit(cmds[sys.argv[1]]())
