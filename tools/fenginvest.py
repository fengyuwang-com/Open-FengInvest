#!/usr/bin/env python3
"""FengInvest — 快速数据工具.

Machine tools for quick data, NOT a pipeline orchestrator.
Full analysis is driven by Claude through skills (fenginvest → 01→07).

Commands:
    screen <TICKER>  快速输出关键数据（价格/财务/量化/纪律）
    status <TICKER>  查看分析进度

Dependencies: yfinance, pandas, scipy, requests
"""

import json, os, subprocess, sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(BASE, "tools")
RESEARCH = os.path.join(BASE, "research")
STATE_DIR = os.path.join(RESEARCH, "state")
MARKET_DIR = os.path.join(RESEARCH, "market")

os.makedirs(RESEARCH, exist_ok=True)
os.makedirs(STATE_DIR, exist_ok=True)
os.makedirs(MARKET_DIR, exist_ok=True)


def _run_tool(name: str, args: list, label: str = None) -> dict:
    """Run a Python tool and return its JSON output."""
    label = label or name
    tool_path = os.path.join(TOOLS, name)
    if not os.path.exists(tool_path):
        tool_path = os.path.join(TOOLS, f"{name}.py")
    if not os.path.exists(tool_path):
        return {"error": f"Tool not found: {name}"}

    cmd = [sys.executable, tool_path] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            stderr = result.stderr.strip()[:500] if result.stderr else "unknown error"
            return {"error": stderr}
        return json.loads(result.stdout) if result.stdout.strip() else {"note": "no output"}
    except subprocess.TimeoutExpired:
        return {"error": f"{label} timed out after 300s"}
    except json.JSONDecodeError as e:
        return {"error": f"{label} output not valid JSON: {e}"}


def cmd_screen(ticker: str):
    """快速数据输出 — 价格, 财务摘要, 纪律检查, 量化因子."""
    ticker = ticker.upper()
    output = {"ticker": ticker, "fetched_at": datetime.now().isoformat()}

    # Price + financials
    raw = _run_tool("fengdata.py", [ticker])
    if "error" not in raw:
        output["price"] = raw.get("price", {})
        output["financials"] = raw.get("financials", {})
        output["data_sources"] = raw.get("data_sources", [])
    else:
        output["data_error"] = raw["error"]

    # L1 discipline check
    l1 = _run_tool("fengrule.py", [ticker])
    if "error" not in l1:
        output["discipline"] = {
            "overall": l1.get("overall_light"),
            "rules": l1.get("rules", []),
        }
    else:
        output["discipline_error"] = l1["error"]

    # L2b quantitative factors
    l2b = _run_tool("fengquant.py", [ticker])
    if "error" not in l2b:
        factors = l2b.get("factor_analysis", {}).get("factors", [])
        output["quantitative"] = {
            "bull_count": sum(1 for f in factors if f.get("signal") == "BULL"),
            "bear_count": sum(1 for f in factors if f.get("signal") == "BEAR"),
            "signal": l2b.get("signal"),
            "factors": factors,
        }
    else:
        output["quantitative_error"] = l2b["error"]

    print(json.dumps(output, indent=2, default=str))
    return 0


def cmd_status(ticker: str):
    """Show analysis progress via state machine."""
    ticker = ticker.upper()
    state_path = os.path.join(STATE_DIR, f"temp_state_{ticker}.json")
    if not os.path.exists(state_path):
        print(f"无进行中的分析: {ticker}")
        return 1

    with open(state_path) as f:
        state = json.load(f)

    SEQUENCE = ["01-capability", "02-market", "03-discipline", "04-quantitative",
                "05-qualitative", "06-collision", "07-report", "08-portfolio"]

    done = set(state.get("completed", {}))
    print(f"=== {ticker} 分析状态 ===")
    print(f"状态: {state.get('status', '?')}")
    print()
    for s in SEQUENCE:
        mark = "[x]" if s in done else "[ ]"
        print(f"  {mark}  {s}")
    print()
    print(f"创建: {state.get('created_at', '?')[:19]}")
    print(f"更新: {state.get('updated_at', '?')[:19]}")
    return 0


def main():
    if len(sys.argv) < 3:
        print("FengInvest — 快速数据工具")
        print()
        print("用法:")
        print("  fenginvest.py screen <TICKER>    # 快速输出关键数据")
        print("  fenginvest.py status <TICKER>    # 查看分析进度")
        print()
        print("注意: 完整分析请通过 Claude 技能链执行 (fenginvest → 01→07)")
        print()
        sys.exit(1)

    cmd = sys.argv[1]
    ticker = sys.argv[2]

    if cmd == "screen":
        sys.exit(cmd_screen(ticker))
    elif cmd == "status":
        sys.exit(cmd_status(ticker))
    else:
        print(f"未知命令: {cmd}")
        print("可用: screen, status")
        sys.exit(1)


if __name__ == "__main__":
    main()
