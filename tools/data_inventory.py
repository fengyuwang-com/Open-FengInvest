#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据快照盘点（只读，不删任何文件）。

扫描 data/ 递归列出全部文件，按目录聚合总量，单列 >100MB 大文件清单。
结果落 data/inventory_report.md（gitignored，不入库）；删除决策留用户拍板。

用法: python tools/data_inventory.py [--threshold-mb 100] [--root data]
"""
import argparse
import os
import sys
from datetime import datetime

MB = 1024 * 1024


def human(n: int) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.2f} GB"
    if n >= MB:
        return f"{n / MB:.1f} MB"
    return f"{n / 1024:.1f} KB"


def scan(root: str):
    dir_stats = {}   # 相对目录 -> [bytes, count]
    big_files = []   # (bytes, abs_path)
    total = 0
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            try:
                sz = os.path.getsize(p)
            except OSError:
                continue
            rel = os.path.relpath(dirpath, root)
            key = "." if rel == "." else rel
            st = dir_stats.setdefault(key, [0, 0])
            st[0] += sz
            st[1] += 1
            total += sz
            count += 1
            big_files.append((sz, p))
    return dir_stats, sorted(big_files, reverse=True), total, count


def main():
    ap = argparse.ArgumentParser(description="只读盘点 data/ 目录体积")
    ap.add_argument("--root", default="data")
    ap.add_argument("--threshold-mb", type=int, default=100)
    ap.add_argument("--report", default=None, help="报告输出路径（默认 <root>/inventory_report.md）")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"[ERR] 目录不存在: {root}", file=sys.stderr)
        sys.exit(1)

    dir_stats, big_files, total, count = scan(root)
    threshold = args.threshold_mb * MB

    lines = [
        "# 数据目录盘点报告（只读，不删任何文件）",
        "",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 扫描根: `{root}`",
        f"- 文件总数: {count}，总体积: {human(total)}",
        f"- 大文件阈值: >{args.threshold_mb} MB",
        "",
        "## 按目录聚合（体积降序）",
        "",
        "| 目录 | 体积 | 文件数 | 占比 |",
        "|------|------|--------|------|",
    ]
    for key, (sz, cnt) in sorted(dir_stats.items(), key=lambda kv: -kv[1][0]):
        pct = f"{sz / total * 100:.1f}%" if total else "-"
        lines.append(f"| `{key}` | {human(sz)} | {cnt} | {pct} |")

    lines += [
        "",
        f"## 大文件清单（> {args.threshold_mb} MB，{sum(1 for s, _ in big_files if s > threshold)} 个）",
        "",
        "| 体积 | 路径 |",
        "|------|------|",
    ]
    for sz, p in big_files:
        if sz > threshold:
            lines.append(f"| {human(sz)} | `{os.path.relpath(p, root)}` |")
    if not any(s > threshold for s, _ in big_files):
        lines.append("| - | （无超过阈值的文件） |")

    lines += [
        "",
        "## 处置建议（仅提示，删除留用户拍板）",
        "",
        "- `snapshots/` 与 `*.snap_*` 为 fengdb.py snapshot（VACUUM INTO）产物：确认 changeset 已稳定后旧快照可归档/删除。",
        "- `changesets/` 为增量变更集：undo 已确认不需要的旧 cs_*.bin 可清理（保持 index.jsonl 一致性，勿手工删）。",
        "- 本报告不入库（data/ gitignored）。",
        "",
    ]

    report = args.report or os.path.join(root, "inventory_report.md")
    with open(report, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[OK] 报告已写入 {report}")
    print(f"总文件 {count} 个，总 {human(total)}；>{args.threshold_mb}MB 大文件 "
          f"{sum(1 for s, _ in big_files if s > threshold)} 个")


if __name__ == "__main__":
    main()
