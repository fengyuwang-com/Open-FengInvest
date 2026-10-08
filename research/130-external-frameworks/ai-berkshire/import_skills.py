#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""import_skills.py — 从上游 ai-berkshire 重导 21 个 skill 正文 + 刷新 UPSTREAM.json。

为什么要有这个脚本
    "如何更新（上游 pull 后重跑）"不能只是口头禅：来源标注头长什么样、sha256 算原文还是算副本、
    21 个文件怎么从 skills/ 与 codex-skills/ 两个上游目录凑齐——这些约定必须可复现，否则下一个人
    （或半年后的自己）只能靠猜，猜错就与 tools/fengadopt.py 的校验打架。本脚本就是这套约定的机器化版本。

用法
    AI_BERKSHIRE=../ai-berkshire python research/130-external-frameworks/ai-berkshire/import_skills.py
    # 默认上游目录 = 仓库同级的 ../ai-berkshire（可用环境变量 AI_BERKSHIRE 覆盖）
    # 跑完必须：python tools/fengadopt.py verify  → 必须 exit 0

铁律
    1. 正文 = 上游原文**逐字节**副本（含换行符），一个字都不改、不排版、不压缩。
    2. 文件头 = 2 行 `<!-- ... -->` 来源标注 + 1 个空行；sha256 一律对**上游原文**计算（不含标注头）。
    3. 上游新增/删除/改名的 skill 不在本脚本的映射表里 → 打印警告，由人补 ADOPTION.json / 映射表。
    4. 纯标准库；读写一律显式 encoding="utf-8"（Windows 默认 GBK 会乱码）；正文按二进制搬运。
"""

import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))  # 仓库根
SKILLS_DIR = os.path.join(HERE, "skills")

# 上游 skills/ 全量（19 个）+ codex-skills/ 独有的 investment-memo-craft（上游 skills/ 无同名件）
SKILLS_SUBDIR = [
    "bottleneck-hunter", "deep-company-series", "dyp-ask", "earnings-review", "earnings-team",
    "financial-data", "income-investment", "industry-funnel", "industry-research",
    "investment-checklist", "investment-research", "investment-team", "management-deep-dive",
    "news-pulse", "portfolio-review", "private-company-research", "quality-screen",
    "thesis-drift", "thesis-tracker", "wechat-article",
]
CODEX_ONLY = ["investment-memo-craft"]

HEADER = (
    "<!-- Source: ai-berkshire | Repo: https://github.com/xbtlin/ai-berkshire | Commit: {commit} |"
    " License: MIT (c) 2026 xbtlin -->\n"
    "<!-- Imported verbatim as reference material. FengInvest-local copy is authoritative for our own use. -->\n"
    "\n"
)


def upstream_dir():
    d = os.environ.get("AI_BERKSHIRE") or os.path.join(ROOT, os.pardir, "ai-berkshire")
    return os.path.abspath(d)


def head_commit(up):
    try:
        out = subprocess.run(["git", "-C", up, "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, check=True)
        full = subprocess.run(["git", "-C", up, "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
        date = subprocess.run(["git", "-C", up, "log", "-1", "--format=%ad", "--date=short"],
                              capture_output=True, text=True, check=True).stdout.strip()
        return out.stdout.strip(), full, date
    except Exception as e:  # 上游不是 git 仓库/无 git：退回读 UPSTREAM.json 的旧值
        print("[warn] 取上游 commit 失败（%s），沿用 UPSTREAM.json 旧值" % e)
        p = os.path.join(HERE, "UPSTREAM.json")
        if os.path.isfile(p):
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            return d.get("commit"), d.get("commit_full"), d.get("commit_date")
        return None, None, None


def main():
    up = upstream_dir()
    if not os.path.isdir(up):
        print("[import_skills] ❌ 上游目录不存在：%s（用 AI_BERKSHIRE=... 指定）" % up)
        return 2
    commit, full, date = head_commit(up)
    if not commit:
        print("[import_skills] ❌ 拿不到上游 commit，拒绝导入（来源不可考 = 不存在）")
        return 2

    os.makedirs(SKILLS_DIR, exist_ok=True)
    files, written = {}, []
    pairs = [("skills/%s.md" % s, s + ".md") for s in SKILLS_SUBDIR]
    for slug in CODEX_ONLY:
        pairs.append(("codex-skills/%s/SKILL.md" % slug, slug + ".md"))

    for rel, slug in pairs:
        src = os.path.join(up, rel.replace("/", os.sep))
        if not os.path.isfile(src):
            print("[import_skills] ❌ 上游缺文件：%s" % rel)
            return 2
        with open(src, "rb") as f:
            raw = f.read()
        files[rel] = hashlib.sha256(raw).hexdigest()
        with open(os.path.join(SKILLS_DIR, slug), "wb") as f:
            f.write(HEADER.format(commit=commit).encode("utf-8") + raw)
        written.append(slug)

    # 反向警告：上游多了/少了 skill，或本仓有未被映射的正文
    up_skill_mds = sorted(f[:-3] for f in os.listdir(os.path.join(up, "skills")) if f.endswith(".md"))
    not_mapped = [s for s in up_skill_mds if s not in SKILLS_SUBDIR]
    if not_mapped:
        print("[import_skills] ⚠️  上游 skills/ 有未纳入映射表的 skill：%s → 请补映射表 + ADOPTION.json"
              % ", ".join(not_mapped))
    orphan = [f for f in sorted(os.listdir(SKILLS_DIR)) if f.endswith(".md") and f not in written]
    if orphan:
        print("[import_skills] ⚠️  本仓有不在本次映射表的正文（旧版残留？）：%s" % ", ".join(orphan))

    upstream = {
        "repo": "https://github.com/xbtlin/ai-berkshire",
        "commit": commit,
        "commit_full": full,
        "commit_date": date,
        "license": "MIT (c) 2026 xbtlin",
        "synced_at": __import__("datetime").date.today().isoformat(),
        "file_count": len(files),
        "files": files,
    }
    with open(os.path.join(HERE, "UPSTREAM.json"), "w", encoding="utf-8") as f:
        f.write(json.dumps(upstream, ensure_ascii=False, indent=2) + "\n")

    print("[import_skills] ✅ 重导 %d 份正文（上游 %s @ %s，commit %s）" % (len(written), up, date, commit))
    print("[import_skills] 下一步必跑：python tools/fengadopt.py verify  → 必须 exit 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
