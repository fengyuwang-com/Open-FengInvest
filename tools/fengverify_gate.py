#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fengverify_gate — 五步快败验证闸门（借鉴 QuantMind verify.sh）。

原理：五个门按顺序执行，任一门失败立即停止，不再跑后续步骤。
这和 QuantMind 的 `set -euo pipefail` 一脉相承——前一步不过，后一步不跑。

用法：
  python tools/fengverify_gate.py <TICKER>           # 跑全部五门
  python tools/fengverify_gate.py <TICKER> --gate 3  # 只跑第三门（调试用）
  python tools/fengverify_gate.py --consistency-only  # 只跑跨文件一致性（项目级，不需 TICKER）
  python tools/fengverify_gate.py <TICKER> --json     # 输出 JSON（供 AI 消费）

五门：
  1. state      — fengstate.py verify（状态机完整性）
  2. structure  — fengdoclint.py --strict（文档结构合规）
  3. report     — report_audit.py check + sources + csvdetect（报告质量）
  4. pipeline   — fengstate.py accept 逐层验收（管线完整性）
  5. consistency — 跨文件一致性（AGENTS.md 声明的工具/配置 vs 实际文件）

退出码：
  0 = 全部通过
  1 = 某门失败（stderr 输出失败详情）
  2 = 用法错误
"""
import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── 数据结构 ──────────────────────────────────────────────────────────

@dataclass
class GateResult:
    name: str
    label: str
    passed: bool
    details: str = ""
    elapsed_ms: int = 0


@dataclass
class VerifyReport:
    ticker: str
    gates: list = field(default_factory=list)
    all_passed: bool = True
    failed_gate: str = ""

    def add(self, result: GateResult):
        self.gates.append(result)
        if not result.passed:
            self.all_passed = False
            if not self.failed_gate:
                self.failed_gate = result.name

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "all_passed": self.all_passed,
            "failed_gate": self.failed_gate,
            "gates": [
                {
                    "name": g.name,
                    "label": g.label,
                    "passed": g.passed,
                    "details": g.details,
                    "elapsed_ms": g.elapsed_ms,
                }
                for g in self.gates
            ],
        }


# ── 工具运行器 ──────────────────────────────────────────────────────────

def run_cmd(cmd: list, cwd: str = ROOT, timeout: int = 120) -> tuple[int, str, str]:
    """运行命令，返回 (returncode, stdout, stderr)。"""
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 1, "", f"TIMEOUT after {timeout}s"
    except FileNotFoundError:
        return 1, "", f"COMMAND NOT FOUND: {cmd[0]}"


# ── Gate 1: 状态机完整性 ──────────────────────────────────────────────

def gate_state(ticker: str) -> GateResult:
    """fengstate.py verify — 状态机完整性 + 跨层一致性。"""
    import time
    t0 = time.monotonic()

    rc, out, err = run_cmd(
        [sys.executable, os.path.join(ROOT, "tools", "fengstate.py"), "verify", ticker]
    )
    elapsed = int((time.monotonic() - t0) * 1000)

    # 解析输出，提取关键信息
    combined = (out + "\n" + err).strip()
    if rc == 0:
        # 统计通过/失败层数
        pass_count = combined.count("PASS") + combined.count("OK") + combined.count("✅")
        warn_count = combined.count("WARN") + combined.count("WARNING")
        detail = f"state verify OK (pass={pass_count}, warn={warn_count})"
        if warn_count > 0:
            detail += f"\nWarnings:\n{combined}"
        return GateResult("state", "状态机完整性", True, detail, elapsed)
    else:
        return GateResult("state", "状态机完整性", False,
                          f"EXIT {rc}\n{combined}", elapsed)


# ── Gate 2: 文档结构合规 ──────────────────────────────────────────────

def gate_structure(ticker: str) -> GateResult:
    """fengdoclint.py --strict — 文档结构合规（双格式 + 总览）。"""
    import time
    t0 = time.monotonic()

    # 找到该 ticker 最新的分析目录
    companies_dir = os.path.join(ROOT, "research", "060-companies")
    analysis_dir = _find_latest_analysis(companies_dir, ticker)
    if not analysis_dir:
        elapsed = int((time.monotonic() - t0) * 1000)
        return GateResult("structure", "文档结构合规", False,
                          f"未找到 {ticker} 的分析目录", elapsed)

    rc, out, err = run_cmd(
        [sys.executable, os.path.join(ROOT, "tools", "fengdoclint.py"),
         analysis_dir, "--strict"]
    )
    elapsed = int((time.monotonic() - t0) * 1000)

    combined = (out + "\n" + err).strip()
    if rc == 0:
        # 统计合规层
        ok_lines = [l for l in combined.splitlines() if "✅" in l or "PASS" in l]
        return GateResult("structure", "文档结构合规", True,
                          f"all layers OK ({len(ok_lines)} layers)", elapsed)
    else:
        fail_lines = [l for l in combined.splitlines() if "❌" in l or "FAIL" in l]
        return GateResult("structure", "文档结构合规", False,
                          f"EXIT {rc}\n" + "\n".join(fail_lines[:10]), elapsed)


# ── Gate 3: 报告质量 ──────────────────────────────────────────────────

def gate_report(ticker: str) -> GateResult:
    """report_audit.py check + sources + csvdetect — 报告质量三连。"""
    import time
    t0 = time.monotonic()

    companies_dir = os.path.join(ROOT, "research", "060-companies")
    analysis_dir = _find_latest_analysis(companies_dir, ticker)
    if not analysis_dir:
        elapsed = int((time.monotonic() - t0) * 1000)
        return GateResult("report", "报告质量", False,
                          f"未找到 {ticker} 的分析目录", elapsed)

    report_md = os.path.join(analysis_dir, "07-report.md")
    if not os.path.exists(report_md):
        elapsed = int((time.monotonic() - t0) * 1000)
        return GateResult("report", "报告质量", False,
                          f"07-report.md 不存在: {report_md}", elapsed)

    report_tool = os.path.join(ROOT, "tools", "report_audit.py")
    issues = []

    # 3a: 结构校验
    rc, out, err = run_cmd(
        [sys.executable, report_tool, "check", "--report", report_md]
    )
    combined = (out + "\n" + err).strip()
    if rc != 0:
        issues.append(f"[check] EXIT {rc}: {combined[:300]}")

    # 3b: 来源标注
    rc, out, err = run_cmd(
        [sys.executable, report_tool, "sources", "--report", report_md]
    )
    combined = (out + "\n" + err).strip()
    if rc != 0:
        issues.append(f"[sources] EXIT {rc}: {combined[:300]}")

    # 3c: CSV 乱入
    rc, out, err = run_cmd(
        [sys.executable, report_tool, "csvdetect", "--report", report_md]
    )
    combined = (out + "\n" + err).strip()
    if rc != 0:
        issues.append(f"[csvdetect] EXIT {rc}: {combined[:300]}")

    elapsed = int((time.monotonic() - t0) * 1000)

    if not issues:
        return GateResult("report", "报告质量", True,
                          "check + sources + csvdetect all passed", elapsed)
    else:
        return GateResult("report", "报告质量", False,
                          "\n".join(issues), elapsed)


# ── Gate 4: 管线完整性 ──────────────────────────────────────────────

def gate_pipeline(ticker: str) -> GateResult:
    """fengstate.py accept 逐层验收 — 管线完整性。"""
    import time
    t0 = time.monotonic()

    layers = [
        "01-capability", "02-market", "03-discipline",
        "04-quantitative", "05-qualitative",
        "06-collision", "07-report", "08-portfolio",
    ]

    passed = []
    failed = []

    for layer in layers:
        rc, out, err = run_cmd(
            [sys.executable, os.path.join(ROOT, "tools", "fengstate.py"),
             "accept", ticker, layer],
            timeout=30,
        )
        combined = (out + "\n" + err).strip()
        if rc == 0:
            passed.append(layer)
        else:
            failed.append(f"{layer}: {combined[:200]}")

    elapsed = int((time.monotonic() - t0) * 1000)

    if not failed:
        return GateResult("pipeline", "管线完整性", True,
                          f"all {len(passed)} layers accepted", elapsed)
    else:
        return GateResult("pipeline", "管线完整性", False,
                          f"passed={len(passed)}, failed={len(failed)}\n" +
                          "\n".join(failed), elapsed)


# ── Gate 5: 跨文件一致性 ──────────────────────────────────────────────

def gate_consistency() -> GateResult:
    """跨文件一致性检查 — AGENTS.md 声明 vs 实际文件。

    检查项：
    1. AGENTS.md 中引用的工具 .py 文件是否都实际存在于 tools/
    2. AGENTS.md 中声明的 skill 目录是否都实际存在
    3. AGENTS.md 中引用的配置文件是否存在
    4. SKILL.md 中引用的工具是否存在
    """
    import time
    import re
    t0 = time.monotonic()

    issues = []

    # ── 1. 工具文件一致性 ──
    agents_md = os.path.join(ROOT, "AGENTS.md")
    if os.path.exists(agents_md):
        with open(agents_md, "r", encoding="utf-8") as f:
            agents_content = f.read()

        # 提取 AGENTS.md 中引用的 .py 文件名
        referenced_tools = set(re.findall(r'(?:tools/)?(\w+\.py)', agents_content))
        # 去重：只保留 feng*.py 风格的工具引用
        referenced_tools = {t for t in referenced_tools if t.startswith("feng") and t.endswith(".py")}

        # 实际存在的工具
        tools_dir = os.path.join(ROOT, "tools")
        if os.path.isdir(tools_dir):
            actual_tools = {f for f in os.listdir(tools_dir)
                           if f.endswith(".py") and not f.startswith("__")}
        else:
            actual_tools = set()

        missing = referenced_tools - actual_tools
        if missing:
            issues.append(f"AGENTS.md 引用了但 tools/ 中不存在: {', '.join(sorted(missing))}")

        # 反向检查：tools/ 中有但 AGENTS.md 未提及的 feng*.py 工具（仅记录，不判 FAIL）
        undocumented = {f for f in actual_tools
                       if f.startswith("feng") and f not in referenced_tools}
        if undocumented:
            issues.append(f"[WARN] tools/ 中有但 AGENTS.md 未声明（非致命）: {', '.join(sorted(undocumented))}")

    # ── 2. Skill 目录一致性 ──
    skills_dir = os.path.join(ROOT, ".agents", "skills")
    if os.path.isdir(skills_dir):
        actual_skills = {d for d in os.listdir(skills_dir)
                        if os.path.isdir(os.path.join(skills_dir, d))}

        if os.path.exists(agents_md):
            # 检查 AGENTS.md 中引用的 skill 名是否都有对应目录
            # 只匹配 `/fengXxx` 格式（skill 引用），排除 `fengXxx.py`（工具引用）
            referenced_skills = set(re.findall(r'(?<!\w)/feng([A-Za-z]\w+)', agents_content))
            # 转为目录名格式
            expected_skill_dirs = {"feng" + s for s in referenced_skills}

            missing_skills = expected_skill_dirs - actual_skills
            if missing_skills:
                issues.append(f"AGENTS.md 引用了但 .agents/skills/ 中不存在: {', '.join(sorted(missing_skills))}")

    # ── 3. 配置文件一致性 ──
    config_checks = [
        ("data/config/research_list.json", "研究清单"),
        ("knowledge/基准参考.md", "基准参考清单"),
    ]
    for rel_path, label in config_checks:
        full_path = os.path.join(ROOT, rel_path)
        if not os.path.exists(full_path):
            issues.append(f"{label}不存在: {rel_path}")

    # ── 4. 核心 SKILL.md 引用的工具一致性 ──
    core_skills = ["fenginvest", "fengholding", "fengexit", "fengreview", "fengcheck"]
    for skill_name in core_skills:
        skill_path = os.path.join(ROOT, ".agents", "skills", skill_name, "SKILL.md")
        if not os.path.exists(skill_path):
            issues.append(f"核心 skill 不存在: {skill_name}/SKILL.md")
            continue

        with open(skill_path, "r", encoding="utf-8") as f:
            skill_content = f.read()

        # 提取 skill 中引用的工具
        skill_tools = set(re.findall(r'feng\w+\.py', skill_content))
        for tool in skill_tools:
            tool_path = os.path.join(ROOT, "tools", tool)
            if not os.path.exists(tool_path):
                issues.append(f"Skill {skill_name} 引用了不存在的工具: {tool}")

    elapsed = int((time.monotonic() - t0) * 1000)

    if not issues:
        return GateResult("consistency", "跨文件一致性", True,
                          "AGENTS.md / skills / configs / tools 一致", elapsed)

    # 区分 WARN 和 FAIL：只有 [WARN] 前缀的是警告，其余是真正的失败
    fails = [i for i in issues if not i.startswith("[WARN]")]
    warns = [i for i in issues if i.startswith("[WARN]")]

    if fails:
        # 有真正的失败
        detail = "\n".join(fails)
        if warns:
            detail += "\n\nWarnings (non-fatal):\n" + "\n".join(warns)
        return GateResult("consistency", "跨文件一致性", False, detail, elapsed)
    else:
        # 只有警告，不算失败（Gate 5 设计为 WARN 不 HALT）
        return GateResult("consistency", "跨文件一致性", True,
                          "AGENTS.md / skills / configs / tools 一致\n" +
                          "\n".join(warns), elapsed)


# ── 辅助函数 ──────────────────────────────────────────────────────────

def _find_latest_analysis(companies_dir: str, ticker: str) -> str | None:
    """找到指定 ticker 最新的分析日期目录。"""
    if not os.path.isdir(companies_dir):
        return None

    candidates = []
    prefix = f"{ticker}-"
    for name in os.listdir(companies_dir):
        if name.startswith(prefix) and os.path.isdir(os.path.join(companies_dir, name)):
            date_dir = os.path.join(companies_dir, name)
            # 列出子目录（日期目录）
            for sub in os.listdir(date_dir):
                sub_path = os.path.join(date_dir, sub)
                if os.path.isdir(sub_path) and len(sub) == 10:  # YYYY-MM-DD
                    candidates.append(sub_path)

    if not candidates:
        return None

    # 按路径排序，最新的在最后
    candidates.sort()
    return candidates[-1]


# ── 主入口 ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="五步快败验证闸门（借鉴 QuantMind verify.sh）"
    )
    parser.add_argument("ticker", nargs="?", help="标的代码（如 NVDA）")
    parser.add_argument("--gate", type=int, choices=[1, 2, 3, 4, 5],
                       help="只跑第 N 门（调试用）")
    parser.add_argument("--consistency-only", action="store_true",
                       help="只跑跨文件一致性（项目级，不需 TICKER）")
    parser.add_argument("--json", action="store_true",
                       help="输出 JSON 格式")

    args = parser.parse_args()

    # ── 一致性专用模式 ──
    if args.consistency_only:
        result = gate_consistency()
        if args.json:
            report = VerifyReport(ticker="(project-level)")
            report.add(result)
            print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        else:
            status = "PASS" if result.passed else "FAIL"
            print(f"[{status}] {result.label}: {result.details}")
        sys.exit(0 if result.passed else 1)

    # ── 正常模式：需要 TICKER ──
    if not args.ticker:
        parser.error("需要指定 TICKER（或使用 --consistency-only）")

    ticker = args.ticker
    report = VerifyReport(ticker=ticker)

    # 五门定义
    gates = [
        (1, "state",     lambda: gate_state(ticker)),
        (2, "structure", lambda: gate_structure(ticker)),
        (3, "report",    lambda: gate_report(ticker)),
        (4, "pipeline",  lambda: gate_pipeline(ticker)),
    ]
    consistency_gate = (5, "consistency", gate_consistency)

    # 快败执行：任一失败立即停止
    for gate_num, gate_name, gate_fn in gates:
        if args.gate and args.gate != gate_num:
            continue

        if not args.json:
            print(f"==> [{gate_num}/5] {gate_name}")

        result = gate_fn()
        report.add(result)

        if not args.json:
            status = "PASS" if result.passed else "FAIL"
            print(f"    [{status}] {result.details[:200]}")

        if not result.passed:
            if not args.json:
                print(f"\n[HALT] Gate {gate_num} ({gate_name}) failed — skipping remaining gates")
            break
    else:
        # 所有非一致性门都通过，跑一致性门
        if not args.gate or args.gate == 5:
            if not args.json:
                print(f"==> [5/5] consistency")
            result = gate_consistency()
            report.add(result)
            if not args.json:
                status = "PASS" if result.passed else "FAIL"
                print(f"    [{status}] {result.details[:200]}")

    # ── 输出 ──
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print()
        if report.all_passed:
            print("[OK] verify gate passed — all 5 checks green")
        else:
            print(f"[FAIL] halted at gate: {report.failed_gate}")

    sys.exit(0 if report.all_passed else 1)


if __name__ == "__main__":
    main()
