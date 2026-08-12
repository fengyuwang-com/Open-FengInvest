#!/usr/bin/env python3
"""
fengview.py — FengInvest 知识库速查工具

不用一个个翻文件，敲命令就看。

用法:
  fengview.py                  列出可用章节
  fengview.py all              看全部速查
  fengview.py macro            宏观体制+配置
  fengview.py sentiment        市场情绪
  fengview.py asset            资产类别
  fengview.py position         仓位计算
  fengview.py sell             卖出+再平衡
  fengview.py strategy         策略一览
  fengview.py --search 滞胀    全文搜索
"""

import re, sys
from pathlib import Path

REF_FILE = Path(__file__).resolve().parent.parent / "research" / "000-QUICK-REFERENCE.md"

# 章节名称 → 匹配的标题关键词
SECTIONS = {
    "macro": ["宏观体制", "1."],
    "sentiment": ["市场情绪", "2."],
    "asset": ["资产", "4."],
    "position": ["仓位", "买多少", "5."],
    "sell": ["卖出", "再平衡", "6.", "7."],
    "strategy": ["策略"],
}


def find_section(text: str, title_keywords: list[str]):
    """找到匹配标题关键词的章节，返回 (start, end)"""
    lines = text.split("\n")
    start = None
    depth = None

    for i, line in enumerate(lines):
        if line.startswith("## "):
            title = line[3:].strip()
            if any(k in title for k in title_keywords):
                start = i
                depth = 2
                break

    if start is None:
        return None

    # 找到下一个同级别的标题
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("## "):
            return "\n".join(lines[start:i])
        # 如果遇到 ###，继续（属于当前章节的子标题）

    return "\n".join(lines[start:])


def search(text: str, query: str):
    """全文搜索，返回匹配行及其上下文"""
    lines = text.split("\n")
    results = []
    for i, line in enumerate(lines):
        if query in line:
            context_start = max(0, i - 1)
            context_end = min(len(lines), i + 2)
            ctx = lines[context_start:context_end]
            # 找最近的标题
            section = ""
            for j in range(i, -1, -1):
                if lines[j].startswith("## "):
                    section = lines[j].strip()
                    break
            results.append((section, i + 1, line.strip()))
    return results


def main():
    # Windows UTF-8 支持
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if not REF_FILE.exists():
        print(f"错误: 找不到 {REF_FILE}")
        sys.exit(1)

    text = REF_FILE.read_text(encoding="utf-8")
    args = sys.argv[1:]

    if not args:
        print("FengInvest 速查工具")
        print()
        print("可用章节:")
        for k in SECTIONS:
            print(f"  fengview.py {k:<12} — {SECTIONS[k][0]}")
        print(f"  fengview.py all          — 全部内容")
        print(f"  fengview.py --search <词> — 全文搜索")
        print()
        print("例: fengview.py macro")
        return

    if args[0] == "all":
        print(text)
        return

    if args[0] == "--search":
        query = " ".join(args[1:])
        if not query:
            print("指定搜索词: fengview.py --search 滞胀")
            return
        results = search(text, query)
        if not results:
            print(f"未找到: {query}")
            return
        print(f"搜索 '{query}' 共 {len(results)} 处:\n")
        for section, line_no, line in results:
            print(f"  [{section}] (第{line_no}行)")
            print(f"    {line}")
            print()
        return

    if args[0] in SECTIONS:
        block = find_section(text, SECTIONS[args[0]])
        if block:
            print(block)
        else:
            print(f"未找到章节: {args[0]}")
        return

    print(f"未知章节: {args[0]}")
    print("可用: macro / sentiment / asset / position / sell / strategy / all")
    sys.exit(1)


if __name__ == "__main__":
    main()
