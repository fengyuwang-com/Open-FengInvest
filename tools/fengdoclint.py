#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fengdoclint — 个股分析文档合规扫描（双格式 + 总览）。

用途：对照 fenginvest SKILL「产出文档规范」，扫描某个分析目录（或整库）
是否每层都有可读 MD（双格式）+ L4 双版本 + 00-INDEX 总览。

2026-09-20 创始人定序升级（只加不减）：
- L0 项目结构第一：整库扫描时先验 docs/PROJECT-STRUCTURE.md 唯一基准的锦点存在性，
  再验报告结构（"项目结构是第一个，然后接下来是那些报告的结构"）。
- 他人存档豁免：own / 《…》目录是创始人存档的他人报告，不是 AI 生产，不进合规。

这是 fengstate.py _check_dual_format 闸门的**审计伴侣**：
- 闸门（complete/accept）= 事前硬拦，逐层；
- 本工具 = 事后/整库总览，一次性看全仓库哪些合规、哪些不合规。

只做结构检查（文件存在 + 同名配对 + 轻量非空/必要章节），不做内容正确性审查
（MD 与 JSON 是否一致、数字是否编造等由人工/其他工具负责）。

用法：
  python tools/fengdoclint.py                  # 扫描整库 research/060-companies/*
  python tools/fengdoclint.py LVHI             # 按 TICKER 解析 <TICKER>-* 公司目录，取最新日期目录
  python tools/fengdoclint.py 1810.HK-小米     # 精确公司目录名：扫该 ticker 下所有日期目录
  python tools/fengdoclint.py <分析日期目录>   # 扫单个目录(绝对/相对路径)
  python tools/fengdoclint.py --strict         # 任不合规则 exit 1（可作 CI 闸门）

输出：每层 ✅/❌ 表 + 汇总；不合规返回非零退出码（--strict 时）。
"""
import os
import re
import sys

# Windows GBK 控制台防崩：emoji/中文输出统一走 UTF-8（否则 ✅❌ 直接 UnicodeEncodeError）。
# 只加不减：不影响任何检查逻辑，仅让输出层在非 UTF-8 终端不假性崩溃。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPANIES = os.path.join(ROOT, "research", "060-companies")

# JSON 层必须同名 .md 配对
JSON_LAYERS = ["02-market", "03-discipline", "04-quantitative", "06-collision", "08-portfolio"]
# 本身是 .md 的必需文件
REQUIRED_MD = ["01-capability.md", "05-qualitative.md", "07-report.md", "07-narrative.md", "00-INDEX.md"]
# 00-INDEX 必要章节（轻量检查，缺则 WARN 不 FAIL）
INDEX_SECTIONS = ["层间关系", "核心数据速查"]

# 不视为分析日期目录的子目录
SKIP_DIRS = {"sources", "temp", "__pycache__"}

# 他人存档豁免（2026-09-20 创始人定音）：这些子目录是创始人手工存档的他人报告/笔记，
# 不是 AI 七层生产产物，不适用双格式合规。own = 自选汇编；《…》 = 整本书/整篇他人文章。
ARCHIVE_DIRS = {"own"}


def _is_archive_dirname(name):
    """他人存档目录判定：own 或《…》书名号目录。"""
    return name in ARCHIVE_DIRS or (name.startswith("《") and name.endswith("》"))


# L0 项目结构锦点（2026-09-20 预检全存在后落清单；基准 = docs/PROJECT-STRUCTURE.md）。
# 只列结构性的；data/market_data.db 虽为🔴本地不入库，但本机必须存在（工具链依赖）。
PROJECT_ANCHORS = [
    "CLAUDE.md", "README.md", "AGENTS.md",
    "docs/PROJECT-STRUCTURE.md", "docs/00-workflow.md", "docs/DATA-MANAGEMENT.md",
    "tools", "rules", "knowledge/principles",
    "design/FOUNDER-VOICES.md", "design/SESSION-INDEX.md", "Discussion",
    "research/120-idea-sourcing/README.md", "research/120-idea-sourcing/RELAY-PROMPT.md",
    "research/120-idea-sourcing/SWEEP-PROTOCOL.md",
    "research/120-idea-sourcing/pool", "research/120-idea-sourcing/rejected",
    "research/120-idea-sourcing/ledger.jsonl", "research/130-external-frameworks",
    "data/config/research_list.json", "data/config/opensource_list.json",
    "data/config/needs_grid.json",
    "data/config/company_names.json", "fengweb/src/index.ts", ".gitignore",
    "data/market_data.db", "holdings", "portfolio", "logs", "reviews", "alerts",
]


def _is_analysis_dir(path):
    """含至少一层 0x- 文件即视为分析日期目录。"""
    try:
        files = os.listdir(path)
    except OSError:
        return False
    return any(
        f[:2] in {f"0{i}" for i in range(1, 9)} and (f.endswith(".json") or f.endswith(".md"))
        for f in files
    )


def lint_dir(path):
    """返回 (ok: bool, issues: list[str], warns: list[str])。"""
    files = set(os.listdir(path))
    issues, warns = [], []

    for L in JSON_LAYERS:
        j, m = f"{L}.json", f"{L}.md"
        if j in files and m not in files:
            issues.append(f"缺 {m}（{j} 无可读版）")
        elif m in files and os.path.getsize(os.path.join(path, m)) < 120:
            warns.append(f"{m} 过小(<120B)，可能为空壳")

    for f in REQUIRED_MD:
        if f not in files:
            issues.append(f"缺 {f}")
        elif os.path.getsize(os.path.join(path, f)) < 120:
            warns.append(f"{f} 过小(<120B)，可能为空壳")

    # 游离 09- 文件（框架外）
    stray = [f for f in files if f.startswith("09-") and f.endswith(".md")]
    if stray:
        warns.append("框架外游离文件: " + ", ".join(stray))

    # 00-INDEX 必要章节
    if "00-INDEX.md" in files:
        txt = open(os.path.join(path, "00-INDEX.md"), encoding="utf-8").read()
        for sec in INDEX_SECTIONS:
            if sec not in txt:
                warns.append(f"00-INDEX.md 缺章节「{sec}」")

    return (len(issues) == 0), issues, warns


def _latest_date_dir(company_dir):
    """公司目录下最新的分析日期目录（优先 YYYY-MM-DD 命名，字典序最大即最新）。"""
    dirs = [n for n in sorted(os.listdir(company_dir))
            if n not in SKIP_DIRS and not _is_archive_dirname(n)
            and os.path.isdir(os.path.join(company_dir, n))
            and _is_analysis_dir(os.path.join(company_dir, n))]
    dated = [n for n in dirs if re.match(r"^\d{4}[-.]\d{2}[-.]\d{2}$", n)]
    pick = (dated or dirs)
    return os.path.join(company_dir, pick[-1]) if pick else None


def _collect_targets(arg):
    targets = []
    if arg:
        if os.path.isdir(arg):
            targets.append(arg)
            return targets
        # 精确目录名：扫 research/060-companies/<arg>/*（日期目录）
        cand = os.path.join(COMPANIES, arg)
        if os.path.isdir(cand):
            for name in sorted(os.listdir(cand)):
                p = os.path.join(cand, name)
                if os.path.isdir(p) and name not in SKIP_DIRS and _is_analysis_dir(p):
                    targets.append(p)
            return targets
        # 纯 TICKER（无中文后缀）：解析 <TICKER>-* 公司目录，各取最新日期目录
        # （2026-09-13 LVHI 复盘修复：fengcheck Gate 2 支持直接传 TICKER）
        if os.path.isdir(COMPANIES):
            prefix = arg.upper() + "-"
            for name in sorted(os.listdir(COMPANIES)):
                if name.upper().startswith(prefix):
                    p = _latest_date_dir(os.path.join(COMPANIES, name))
                    if p:
                        targets.append(p)
            if targets:
                return targets
        print(f"[WARN] 无法解析参数: {arg}", file=sys.stderr)
        return []
    # 整库
    if not os.path.isdir(COMPANIES):
        print(f"[WARN] 目录不存在: {COMPANIES}", file=sys.stderr)
        return []
    for ticker in sorted(os.listdir(COMPANIES)):
        tc = os.path.join(COMPANIES, ticker)
        if not os.path.isdir(tc):
            continue
        for name in sorted(os.listdir(tc)):
            p = os.path.join(tc, name)
            if os.path.isdir(p) and name not in SKIP_DIRS and not _is_archive_dirname(name) and _is_analysis_dir(p):
                targets.append(p)
    return targets


def main():
    args = sys.argv[1:]
    strict = "--strict" in args
    pos = [a for a in args if not a.startswith("--")]
    arg = pos[0] if pos else None

    targets = _collect_targets(arg)
    if not targets:
        print("无分析目录可扫。")
        return 0

    # L0 项目结构第一（2026-09-20 创始人定序）：只做整库扫描时先验基准锦点。
    structure_ok = True
    structure_missing = []
    if not arg:
        for p in PROJECT_ANCHORS:
            if not os.path.exists(os.path.join(ROOT, p)):
                structure_ok = False
                structure_missing.append(p)
        print("L0 项目结构（锦点 %d 个，基准 docs/PROJECT-STRUCTURE.md）：%s" % (
            len(PROJECT_ANCHORS),
            "✅ 全部存在" if structure_ok else "❌ 缺失: " + ", ".join(structure_missing)))
        # 他人存档统计（豁免，不进合规，但要有声可见）
        archives = []
        if os.path.isdir(COMPANIES):
            for ticker in sorted(os.listdir(COMPANIES)):
                tc = os.path.join(COMPANIES, ticker)
                if os.path.isdir(tc):
                    for name in sorted(os.listdir(tc)):
                        if _is_archive_dirname(name) and os.path.isdir(os.path.join(tc, name)):
                            archives.append(f"{ticker}/{name}")
        if archives:
            print(f"他人存档豁免 {len(archives)} 处（不进合规）：" + "、".join(archives))
        print()

    print(f"{'分析目录':44s} {'合规':4s} 问题/警告")
    print("-" * 96)
    n_ok = n_bad = 0
    for t in targets:
        rel = os.path.relpath(t, ROOT)
        ok, issues, warns = lint_dir(t)
        if ok:
            n_ok += 1
            note = "clean" if not warns else " | ".join(warns)
            print(f"{rel:44s} {'✅':4s} {note}")
        else:
            n_bad += 1
            note = "❌ " + "; ".join(issues) + (" || " + "; ".join(warns) if warns else "")
            print(f"{rel:44s} {'❌':4s} {note}")

    print(f"\n扫描 {len(targets)} 个目录：合规 {n_ok} / 不合规 {n_bad}")
    if not structure_ok:
        print("L0 项目结构缺失项需按 docs/PROJECT-STRUCTURE.md 恢复（或更新基准后再扫）。")
        return 1 if strict else 0
    if n_bad:
        print("不合规目录需补齐双格式 MD / 00-INDEX（见 fenginvest SKILL「产出文档规范」）。")
        return 1 if strict else 0
    print("全部合规 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
