#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sync-ai-berkshire.py — 同步 ai-berkshire 项目到 FengInvest。
集成策略：物理复制工具 + 方法引用 + 选择性导入研究报告。

用法：
    python tools/sync-ai-berkshire.py check     # 检查是否有更新
    python tools/sync-ai-berkshire.py update    # 更新工具 + 导入新报告

数据流：
    ai-berkshire/                     -> FengInvest/
    ├── tools/*.py                    -> tools/（物理复制，GBK 修复）
    ├── reports/<行业分析>            -> research/070-reports/（选择性）
    ├── reports/<股票分析>/           -> research/060-companies/<TICKER>-<name>/（如有则合并）
    └── reports/<策略/筛选>          -> research/050-strategies/（选择性）
"""

import json
import os
import shutil
import subprocess
import sys
import re
from datetime import datetime
from pathlib import Path

# ============================================================
# 配置
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AI_BERKSHIRE = Path(os.environ.get("AI_BERKSHIRE", Path.home() / "FengProj" / "ai-berkshire"))

SYNC_STATE_FILE = PROJECT_ROOT / "data" / ".ai-berkshire-sync.json"

# 同步策略文件
TOOLS_TO_SYNC = [
    "financial_rigor.py",
    "report_audit.py",
    "stock_screener.py",
    "xueqiu_scraper.py",
    "morningstar_fair_value.py",
    "twstock_data.py",
    "star_history_chart.py",
]

# 研究报告导入规则
IMPORT_RULES = {
    # 行业全景报告 -> 070-reports/
    "industry_to_070": {
        "patterns": [
            r"AI.*全景",
            r"AI.*产业链",
            r"AI.*格局",
            r"AI.*行业",
            r"核电",
            r"游戏",
            r"中国.*市场.*研究",
            r"AI.*创业公司",
            r"AI.*funnel",
            r"行业.*研究",
        ],
        "dest": "research/070-reports/",
    },
    # 筛选清单 -> 050-strategies/
    "screening_to_050": {
        "patterns": [
            r"破净",
            r"召回池",
            r"筛选",
            r"income-investment",
            r"候选池",
        ],
        "dest": "research/050-strategies/",
    },
}

# 已知公司映射（ai-berkshire 目录名 -> FengInvest TICKER-中文名）
COMPANY_MAP = {
    "腾讯": "0700.HK-腾讯",
    "阿里巴巴": "9988.HK-阿里巴巴",
    "拼多多": "PDD-拼多多",
    "小米": "1810.HK-小米集团",
    "茅台": "600519.SH-贵州茅台",
    "微软": "MSFT-微软",
}


# ============================================================
# 工具函数
# ============================================================

def load_state():
    if SYNC_STATE_FILE.exists():
        with open(SYNC_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state):
    SYNC_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SYNC_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def get_berkshire_head():
    result = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        capture_output=True, text=True, encoding="utf-8", cwd=AI_BERKSHIRE,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _git_log(args, cwd):
    result = subprocess.run(
        ["git"] + args, capture_output=True, text=True, encoding="utf-8", cwd=cwd,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def fix_gbk_encoding(filepath):
    fp = Path(filepath)
    try:
        with open(fp, "r", encoding="utf-8") as f:
            content = f.read()
    except UnicodeDecodeError:
        with open(fp, "r", encoding="gbk") as f:
            content = f.read()
        print(f"  [WARN] {fp.name} is GBK encoded, converting to UTF-8")

    lines = content.split("\n")
    fixed = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if 'open(' in stripped and 'encoding=' not in stripped and not stripped.startswith('#'):
            m = re.search(r'open\(([^)]+)\)', stripped)
            if m:
                args = m.group(1)
                if '"w"' in args or "'w'" in args:
                    if 'encoding=' not in args:
                        lines[i] = line.replace(
                            m.group(0),
                            f"open({args}, encoding='utf-8')"
                        )
                        fixed = True
                elif '"r"' in args or "'r'" in args:
                    if 'encoding=' not in args:
                        lines[i] = line.replace(
                            m.group(0),
                            f"open({args}, encoding='utf-8')"
                        )
                        fixed = True

    if fixed:
        with open(fp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"  [FIX] {fp.name} GBK encoding fixed")
        return True
    return False


def ensure_source_header(filepath, commit_hash):
    fp = Path(filepath)
    with open(fp, "r", encoding="utf-8") as f:
        content = f.read()

    header = f"# Source: ai-berkshire (https://github.com/xbtlin/ai-berkshire)\n# Commit: {commit_hash} | License: MIT | (c) 2026 xbtlin\n# Adapted for FengInvest project structure.\n# -----------------------------------------------------------\n"

    if "Source: ai-berkshire" not in content:
        if content.startswith("#!"):
            first_nl = content.index("\n")
            content = content[:first_nl + 1] + header + content[first_nl + 1:]
        else:
            content = header + content
        with open(fp, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    return False


# ============================================================
# 命令：check
# ============================================================

def cmd_check():
    state = load_state()
    prev_head = state.get("last_sync_commit", "unknown")
    curr_head = get_berkshire_head()
    if not curr_head:
        print("[ERROR] Cannot get ai-berkshire HEAD")
        return

    print(f"  Last sync: {prev_head}")
    print(f"  Current HEAD: {curr_head}")

    if prev_head != "unknown":
        log = _git_log(["log", f"{prev_head}..{curr_head}", "--oneline"], AI_BERKSHIRE)
        if log:
            lines = log.split("\n")
            print(f"  New commits: {len(lines)}")
            for line in lines:
                print(f"    {line}")
        else:
            print("  No new commits (up to date)")
    else:
        print("  First sync, no previous baseline")

    print(f"\n  HEAD: {curr_head}")


# ============================================================
# 命令：update
# ============================================================

def cmd_update():
    if not AI_BERKSHIRE.exists():
        print(f"[ERROR] ai-berkshire not found at: {AI_BERKSHIRE}")
        return

    print("== Updating ai-berkshire ==")
    result = subprocess.run(
        ["git", "pull", "--ff-only", "origin", "main"],
        capture_output=True, text=True, encoding="utf-8", cwd=AI_BERKSHIRE,
    )
    if result.returncode != 0:
        print(f"  [WARN] pull failed: {result.stderr}")
        print("  Continuing with current version")
    else:
        print(f"  {result.stdout.strip() or 'Already up to date'}")

    curr_head = get_berkshire_head()
    short_hash = curr_head.split()[0] if curr_head else "unknown"
    print(f"  HEAD: {short_hash}")

    print("\n== Syncing tools to tools/ ==")
    tools_src = AI_BERKSHIRE / "tools"
    tools_dst = PROJECT_ROOT / "tools"
    tools_dst.mkdir(parents=True, exist_ok=True)

    for tool_name in TOOLS_TO_SYNC:
        src = tools_src / tool_name
        dst = tools_dst / tool_name
        if not src.exists():
            print(f"  [SKIP] {tool_name} source not found")
            continue

        shutil.copy2(str(src), str(dst))
        ensure_source_header(str(dst), short_hash)
        fix_gbk_encoding(str(dst))
        print(f"  [OK] {tool_name}")

    print("\n== Syncing research reports ==")
    reports_src = AI_BERKSHIRE / "reports"
    if not reports_src.exists():
        print("  [WARN] ai-berkshire has no reports/ directory")
    else:
        dst_070 = PROJECT_ROOT / "research" / "070-reports"
        dst_070.mkdir(parents=True, exist_ok=True)
        synced_070 = 0

        for item in reports_src.iterdir():
            name = item.name
            for rule_name, rule in IMPORT_RULES.items():
                for pattern in rule["patterns"]:
                    if re.search(pattern, name):
                        dest_dir = PROJECT_ROOT / rule["dest"]
                        dest_dir.mkdir(parents=True, exist_ok=True)
                        dst = dest_dir / name
                        if item.is_dir():
                            if dst.exists():
                                shutil.rmtree(str(dst))
                            shutil.copytree(str(item), str(dst))
                        else:
                            shutil.copy2(str(item), str(dst))
                        print(f"  [OK] [{rule_name}] {name}")
                        synced_070 += 1
                        break
                else:
                    continue
                break

        print(f"  Industry/strategy reports: {synced_070} items")

        synced_company = 0
        for dir_name, company_path in COMPANY_MAP.items():
            src_dir = reports_src / dir_name
            if not src_dir.is_dir():
                continue
            dst_dir = PROJECT_ROOT / "research" / "060-companies" / company_path
            if not dst_dir.exists():
                dst_dir.mkdir(parents=True, exist_ok=True)
                print(f"  [NEW] Created company dir: {company_path}")

            for report_file in src_dir.iterdir():
                if report_file.is_file():
                    shutil.copy2(str(report_file), str(dst_dir / report_file.name))
                elif report_file.is_dir():
                    sub_dst = dst_dir / report_file.name
                    if sub_dst.exists():
                        shutil.rmtree(str(sub_dst))
                    shutil.copytree(str(report_file), str(sub_dst))

            synced_company += 1
            print(f"  [OK] [{company_path}] updated")

        print(f"  Company reports: {synced_company} companies")

    state = load_state()
    state["last_sync_commit"] = curr_head or state.get("last_sync_commit", "")
    state["last_sync_time"] = datetime.now().isoformat()
    state["tool_count"] = len(TOOLS_TO_SYNC)
    save_state(state)

    print(f"\n== Complete ==")
    print(f"  Sync baseline: {short_hash}")
    print(f"  Sync time: {state['last_sync_time']}")
    print(f"  State file: {SYNC_STATE_FILE}")


# ============================================================
# CLI 入口
# ============================================================

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("check", "update"):
        print(__doc__)
        return

    if sys.argv[1] == "check":
        cmd_check()
    elif sys.argv[1] == "update":
        cmd_update()


if __name__ == "__main__":
    main()
