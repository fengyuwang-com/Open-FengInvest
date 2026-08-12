#!/usr/bin/env python3
"""
renumber_refs.py — 批量重编号参考文档

用法:
  python tools/renumber_refs.py manifest.json

manifest.json 格式:
{
  "root": "./",
  "renames": [
    {"old": "research/010-macro/020-business-cycle.md", "new": "research/010-macro/002-business-cycle.md"}
  ],
  "scan_dirs": ["research", "."]
}

规则:
  1. 按 manifest 的 renames 顺序执行文件重命名（os.rename）
  2. 扫描所有 scan_dirs 下的 .md 文件
  3. 将所有文件中出现的旧相对路径替换为新路径（文本替换）
  4. 输出所有改动的日志

注意:
  - 替换是纯文本匹配，不是正则。旧路径应足够独特避免误伤
  - 建议先 dry_run = True 预览，确认无误后再改
  - 执行前确保 git 工作区干净，方便 diff 审查
"""

import json, os, sys
from pathlib import Path


def main():
    if len(sys.argv) < 2:
        print("用法: python tools/renumber_refs.py manifest.json [--dry-run]")
        sys.exit(1)

    manifest_file = Path(sys.argv[1])
    dry_run = "--dry-run" in sys.argv

    with open(manifest_file, encoding="utf-8") as f:
        manifest = json.load(f)

    root = Path(manifest["root"]).resolve()
    renames = manifest["renames"]
    scan_dirs = manifest.get("scan_dirs", ["research"])

    print(f"{'[DRY RUN] ' if dry_run else ''}重编号: {root}")
    print(f"  扫描目录: {scan_dirs}")
    print(f"  重命名条目: {len(renames)}")
    print()

    # === Phase 1: 重命名文件 ===
    print("=== Phase 1: 文件重命名 ===")
    for entry in renames:
        old_path = (root / entry["old"]).resolve()
        new_path = (root / entry["new"]).resolve()
        new_path.parent.mkdir(parents=True, exist_ok=True)

        if not old_path.exists():
            print(f"  !! 文件不存在, 跳过: {entry['old']}")
            continue

        if dry_run:
            print(f"  mv {entry['old']} -> {entry['new']}")
        else:
            os.rename(str(old_path), str(new_path))
            print(f"  OK {entry['old']} -> {entry['new']}")

    if dry_run:
        print("  (dry-run, 未实际移动)")
    print()

    # === Phase 2: 收集所有 .md 文件 ===
    md_files = []
    for sd in scan_dirs:
        scan_path = (root / sd).resolve()
        if scan_path.is_dir():
            md_files.extend(scan_path.rglob("*.md"))
        elif scan_path.is_file() and scan_path.suffix == ".md":
            md_files.append(scan_path)

    # 去重
    md_files = sorted(set(md_files))
    print(f"=== Phase 2: 更新引用 ({len(md_files)} 个 .md 文件) ===")

    total_replacements = 0
    for entry in renames:
        old_fname = Path(entry["old"]).name        # "020-business-cycle.md"
        new_fname = Path(entry["new"]).name        # "002-business-cycle.md"
        if old_fname == new_fname:
            continue

        for md_file in md_files:
            try:
                original = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            if old_fname not in original:
                continue

            count = original.count(old_fname)
            if not dry_run:
                md_file.write_text(original.replace(old_fname, new_fname), encoding="utf-8")

            rel = md_file.relative_to(root)
            print(f"  {rel}: {old_fname} -> {new_fname} (x{count})")
            total_replacements += count

    if dry_run:
        print(f"  (dry-run, 共 {total_replacements} 处待替换)")
    else:
        print(f"  共替换 {total_replacements} 处引用")

    print()
    print("完成。" if not dry_run else "dry-run 完成，确认无误后去掉 --dry-run 执行。")


if __name__ == "__main__":
    main()
