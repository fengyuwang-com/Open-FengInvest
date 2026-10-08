#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fengoslist.py — 开源项目决策台账校验器（data/config/opensource_list.json）。

用途
    把「开源项目登记簿」当决策台账来验：schema 完整性 + 条件必填 + status/kind 取值合法
    + 日期格式 + adopted 的落点文件必须真实存在；另给表格视图 / 分布统计 / evaluating 超期预警。
    背景：v1 的结论只写在 note 散文里，导致多条 evaluating 长期烂尾；v2 起结论必须落进
    verdict / salvage / reused_into 结构化字段，本工具就是这套规矩的守门人。

用法
    python tools/fengoslist.py validate                 # 全量校验；任一不合格 → 逐条明细 + exit(1)
    python tools/fengoslist.py list [--status X] [--kind Y]
    python tools/fengoslist.py stats                    # 条数与 status/kind 分布
    python tools/fengoslist.py due [--days N]           # 默认 14：揪出超期未动的 evaluating（防腐烂）
    python tools/fengoslist.py validate --json          # 任一子命令均可加 --json 取纯净输出
    python tools/fengoslist.py due --days 7 --today 2026-09-17   # --today 供确定性测试

铁律
    1. 只读：本工具绝不修改 opensource_list.json 与仓库任何文件。
    2. 有声失败：validate 不合格 / due 有超期 → exit(1) 并逐条打印，绝不静默通过。
    3. adopted 必带 reused_into，且每个落点（相对仓库根）必须 os.path.exists 为真。
    4. 结论不落结构化字段 = 不合格：evaluating 的 verdict 必须写明「待办：...」。
    5. 纯标准库、零第三方依赖；读写一律显式 encoding="utf-8"（Windows 默认 GBK 会乱码）。

退出码：0 = 通过 / 无超期；1 = 不合格或存在超期；2 = 文件缺失或 JSON 解析失败。
"""

import argparse
import datetime
import json
import os
import re
import sys
import unicodedata

# Windows GBK 控制台防崩：emoji/中文输出统一走 UTF-8（否则 ✅⚠️ 直接 UnicodeEncodeError）。
# 只加不减：不影响任何检查逻辑，仅让输出层在非 UTF-8 终端不假性崩溃。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

# ============================================================
# 常量与路径
# ============================================================

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIST_PATH = os.path.join(ROOT, "data", "config", "opensource_list.json")

# status 四取值（与 _schema.status 对齐；故意不加未使用的第 5 值）
STATUS_VALUES = ("adopted", "evaluating", "noted", "rejected")
# kind 五取值
KIND_VALUES = ("data", "framework", "toolchain", "project", "benchmark")
# 所有条目必填字段
REQUIRED_FIELDS = ("name", "repo", "kind", "status", "added", "updated", "note")
# 可选字段
OPTIONAL_FIELDS = ("reused_into", "verdict", "salvage", "eval_doc", "decided_at", "depends_on", "trigger")
# v1 遗留字段（迁移后不该再出现）
LEGACY_FIELDS = ("url", "date")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DUE_DEFAULT_DAYS = 14


# ============================================================
# 工具函数
# ============================================================

def load_list(path=LIST_PATH):
    """读台账（显式 utf-8）。返回 (data, err_msg)；err_msg 非空表示读不了。"""
    if not os.path.exists(path):
        return None, f"台账文件不存在: {path}"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except json.JSONDecodeError as e:
        return None, f"台账 JSON 解析失败: {e}"
    except OSError as e:
        return None, f"台账读取失败: {e}"


def parse_date(s):
    """YYYY-MM-DD → date；非法返回 None。"""
    if not isinstance(s, str) or not DATE_RE.match(s):
        return None
    try:
        return datetime.datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def dwidth(s):
    """显示宽度（CJK 全角按 2 计），用于终端表格对齐。"""
    w = 0
    for ch in str(s):
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return w


def pad(s, width):
    """按显示宽度右侧补空格（超宽不截断，交给调用方）。"""
    s = str(s)
    return s + " " * max(0, width - dwidth(s))


def trunc(s, width):
    """按显示宽度左截断并加省略号。"""
    s = str(s)
    if dwidth(s) <= width:
        return s
    out, w = "", 0
    for ch in s:
        cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if w + cw > width - 1:
            break
        out += ch
        w += cw
    return out + "…"


def render_table(headers, rows, widths):
    """朴素表格（分隔线 + 表头 + 行）。"""
    lines = []
    lines.append("  ".join(pad(h, w) for h, w in zip(headers, widths)).rstrip())
    lines.append("-" * (sum(widths) + 2 * (len(widths) - 1)))
    for row in rows:
        lines.append("  ".join(pad(c, w) for c, w in zip(row, widths)).rstrip())
    return "\n".join(lines)


def emit(obj, as_json, text):
    """统一输出：--json 走 json.dumps（ensure_ascii=False），否则走文本。"""
    if as_json:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    else:
        if text:
            sys.stdout.write(text + "\n")


# ============================================================
# validate：schema 校验 + 条件必填校验 + 落点存在性
# ============================================================

def validate_entry(idx, p):
    """校验单条，返回 (errors, warnings) 两个字符串列表。"""
    errors, warnings = [], []
    who = p.get("name") if isinstance(p, dict) else None
    tag = f"[{idx}] {who}" if who else f"[{idx}] <无名条目>"

    if not isinstance(p, dict):
        return [f"{tag}: 条目不是 JSON 对象"], []

    # 0) v1 遗留字段
    for lf in LEGACY_FIELDS:
        if lf in p:
            errors.append(f"{tag}: 存在 v1 遗留字段 `{lf}`，应改为 repo / added+updated")

    # 1) 必填字段
    for f in REQUIRED_FIELDS:
        if f not in p:
            errors.append(f"{tag}: 缺必填字段 `{f}`")
        elif not isinstance(p[f], str) or not p[f].strip():
            errors.append(f"{tag}: 必填字段 `{f}` 必须是非空字符串")

    # 2) 未知字段（warning，不致命）
    for k in p:
        if k not in REQUIRED_FIELDS and k not in OPTIONAL_FIELDS:
            warnings.append(f"{tag}: 未知字段 `{k}`（未在 _schema.fields 登记）")

    # 3) 取值合法
    if p.get("status") not in STATUS_VALUES:
        errors.append(f"{tag}: status=`{p.get('status')}` 非法，应为 {'/'.join(STATUS_VALUES)}")
    if p.get("kind") not in KIND_VALUES:
        errors.append(f"{tag}: kind=`{p.get('kind')}` 非法，应为 {'/'.join(KIND_VALUES)}")

    # 4) 日期格式（+ updated 不得早于 added）
    for f in ("added", "updated", "decided_at"):
        if p.get(f) is None:
            continue
        if parse_date(p.get(f)) is None:
            errors.append(f"{tag}: `{f}`=`{p.get(f)}` 日期格式非法，应为 YYYY-MM-DD")
    if parse_date(p.get("added")) and parse_date(p.get("updated")):
        if parse_date(p["updated"]) < parse_date(p["added"]):
            errors.append(f"{tag}: updated({p['updated']}) 早于 added({p['added']})")

    # 5) 条件必填
    st = p.get("status")

    if st == "adopted":
        ri = p.get("reused_into")
        if not isinstance(ri, list) or not ri:
            errors.append(f"{tag}: status=adopted 必填 `reused_into`（非空数组，落点文件相对路径）")
        else:
            for rel in ri:
                if not isinstance(rel, str) or not rel.strip():
                    errors.append(f"{tag}: reused_into 含非字符串/空项: {rel!r}")
                    continue
                if os.path.isabs(rel):
                    errors.append(f"{tag}: reused_into 必须写相对仓库根的路径，收到绝对路径 `{rel}`")
                    continue
                if not os.path.exists(os.path.join(ROOT, rel)):
                    errors.append(f"{tag}: reused_into 落点文件不存在 `{rel}`（仓库根 {ROOT}）")

    if st == "rejected":
        if not isinstance(p.get("verdict"), str) or not p["verdict"].strip():
            errors.append(f"{tag}: status=rejected 必填 `verdict`（一句话结论）")
        sv = p.get("salvage")
        if not isinstance(sv, list):
            errors.append(f"{tag}: status=rejected 必填 `salvage`（数组；没有可提取项写 []）")
        else:
            for item in sv:
                if not isinstance(item, str) or not item.strip():
                    errors.append(f"{tag}: salvage 含非字符串/空项: {item!r}")

    if st == "evaluating":
        vd = p.get("verdict")
        if not isinstance(vd, str) or not vd.strip():
            errors.append(f"{tag}: status=evaluating 必填 `verdict`（写明还在评什么）")
        elif "待办" not in vd:
            errors.append(f"{tag}: status=evaluating 的 verdict 必须写明还在评什么（形如「待办：...」），"
                          f"当前未含「待办」：{trunc(vd, 40)}")

    # 6) 其他字段类型
    if "salvage" in p and not isinstance(p["salvage"], list):
        errors.append(f"{tag}: `salvage` 必须是数组")
    for f in ("depends_on", "eval_doc", "trigger"):
        if f in p and (not isinstance(p[f], str) or not p[f].strip()):
            errors.append(f"{tag}: `{f}` 必须是非空字符串（若不需要请删掉该字段）")
    if p.get("eval_doc") and not os.path.exists(os.path.join(ROOT, p["eval_doc"])):
        warnings.append(f"{tag}: eval_doc 不存在 `{p['eval_doc']}`（可选字段，仅提示）")

    return errors, warnings


def cmd_validate(args):
    data, err = load_list(args.file)
    if err:
        payload = {"ok": False, "file": args.file, "fatal": err, "errors": [err], "warnings": [], "count": 0}
        emit(payload, args.json, f"[fengoslist] ❌ {err}")
        return 1

    projects = data.get("projects")
    errors, warnings = [], []
    if not isinstance(projects, list):
        errors.append("`projects` 必须是数组")
        projects = []
    if "_schema" not in data or not isinstance(data["_schema"], dict):
        errors.append("缺 `_schema` 块（v2 要求：version / status / kind / fields）")
    else:
        if not data["_schema"].get("version"):
            errors.append("`_schema.version` 缺失")
        for k in ("status", "kind", "fields"):
            if not isinstance(data["_schema"].get(k), dict):
                errors.append(f"`_schema.{k}` 必须是对象")

    seen = {}
    for i, p in enumerate(projects, 1):
        e, w = validate_entry(i, p)
        errors += e
        warnings += w
        if isinstance(p, dict) and p.get("name"):
            seen.setdefault(p["name"], []).append(i)
    for name, idxs in seen.items():
        if len(idxs) > 1:
            errors.append(f"重复条目名 `{name}`（出现于第 {idxs} 条）")

    payload = {"ok": not errors, "file": args.file, "count": len(projects),
               "errors": errors, "warnings": warnings}
    if args.json:
        emit(payload, True, "")
    else:
        if warnings:
            for w in warnings:
                print(f"[fengoslist] ⚠️  {w}")
        if errors:
            print(f"[fengoslist] ❌ 校验不合格：{len(errors)} 项问题 / 共 {len(projects)} 条")
            for e in errors:
                print(f"    - {e}")
            print("[fengoslist] 修完再跑 python tools/fengoslist.py validate")
        else:
            print(f"[fengoslist] ✅ 校验通过：{len(projects)} 条全部合格"
                  + (f"（{len(warnings)} 条提示）" if warnings else ""))
    return 0 if not errors else 1


# ============================================================
# list：表格视图
# ============================================================

def cmd_list(args):
    if args.status and args.status not in STATUS_VALUES:
        print(f"[fengoslist] ❌ --status 取值非法：{args.status}（应为 {'/'.join(STATUS_VALUES)}）")
        return 1
    if args.kind and args.kind not in KIND_VALUES:
        print(f"[fengoslist] ❌ --kind 取值非法：{args.kind}（应为 {'/'.join(KIND_VALUES)}）")
        return 1

    data, err = load_list(args.file)
    if err:
        print(f"[fengoslist] ❌ {err}")
        return 2

    items = [p for p in data.get("projects", [])
             if (not args.status or p.get("status") == args.status)
             and (not args.kind or p.get("kind") == args.kind)]

    if args.json:
        emit({"count": len(items), "items": items}, True, "")
        return 0

    if not items:
        print("[fengoslist] 无匹配条目")
        return 0

    headers = ["#", "NAME", "KIND", "STATUS", "ADDED", "UPDATED", "DEPENDS_ON", "NOTE"]
    widths = [3, 34, 10, 11, 10, 10, 12, 46]
    rows = []
    for i, p in enumerate(items, 1):
        rows.append([
            i,
            trunc(p.get("name"), 34),
            p.get("kind"),
            p.get("status"),
            p.get("added"),
            p.get("updated"),
            p.get("depends_on", ""),
            trunc(p.get("note", ""), 46),
        ])
    print(render_table(headers, rows, widths))
    print(f"\n[fengoslist] 共 {len(items)} 条"
          + (f"（status={args.status}）" if args.status else "")
          + (f"（kind={args.kind}）" if args.kind else ""))
    return 0


# ============================================================
# stats：条数与分布
# ============================================================

def cmd_stats(args):
    data, err = load_list(args.file)
    if err:
        print(f"[fengoslist] ❌ {err}")
        return 2

    projects = data.get("projects", [])
    total = len(projects)
    status_dist = {s: 0 for s in STATUS_VALUES}
    kind_dist = {k: 0 for k in KIND_VALUES}
    cross = {s: {k: 0 for k in KIND_VALUES} for s in STATUS_VALUES}
    stale = []  # evaluating 未更新天数
    today = datetime.date.today()
    for p in projects:
        s, k = p.get("status"), p.get("kind")
        if s in status_dist:
            status_dist[s] += 1
        if k in kind_dist:
            kind_dist[k] += 1
        if s in cross and k in cross[s]:
            cross[s][k] += 1
        d = parse_date(p.get("updated"))
        if s == "evaluating" and d:
            stale.append((p.get("name"), (today - d).days))

    if args.json:
        emit({"total": total, "status": status_dist, "kind": kind_dist,
              "cross": cross, "evaluating_age_days": sorted(stale, key=lambda x: -x[1])}, True, "")
        return 0

    print(f"[fengoslist] 台账总条数：{total}   （{os.path.relpath(args.file, ROOT)}）\n")
    print("status 分布：")
    for s in STATUS_VALUES:
        n = status_dist[s]
        pct = (n / total * 100) if total else 0
        print(f"  {pad(s, 12)} {n:>3}  ({pct:5.1f}%)  " + "#" * n)
    print("\nkind 分布：")
    for k in KIND_VALUES:
        n = kind_dist[k]
        pct = (n / total * 100) if total else 0
        print(f"  {pad(k, 12)} {n:>3}  ({pct:5.1f}%)  " + "#" * n)
    print("\nstatus × kind 交叉：")
    for s in STATUS_VALUES:
        cells = "  ".join(f"{k}={cross[s][k]}" for k in KIND_VALUES)
        print(f"  {pad(s, 12)} {cells}")
    if stale:
        print("\nevaluating 未更新天数（更新日期到今天）：")
        for name, age in sorted(stale, key=lambda x: -x[1]):
            print(f"  {pad(trunc(name, 34), 34)} {age:>4} 天")
    return 0


# ============================================================
# due：揪出超期未动的 evaluating
# ============================================================

def cmd_due(args):
    data, err = load_list(args.file)
    if err:
        print(f"[fengoslist] ❌ {err}")
        return 2

    today = parse_date(args.today) if args.today else datetime.date.today()
    if today is None:
        print(f"[fengoslist] ❌ --today 日期格式非法：{args.today}（应为 YYYY-MM-DD）")
        return 1

    overdue, skipped = [], []
    for p in data.get("projects", []):
        if p.get("status") != "evaluating":
            continue
        d = parse_date(p.get("updated"))
        if d is None:
            # validate 会报日期格式；这里不静默吞掉，标记出来
            skipped.append({"name": p.get("name"), "updated": p.get("updated"), "reason": "updated 缺失/非法"})
            continue
        age = (today - d).days
        if age >= args.days:
            overdue.append({"name": p.get("name"), "kind": p.get("kind"), "updated": p.get("updated"),
                            "age_days": age, "beyond_days": age - args.days,
                            "verdict": p.get("verdict", "")})
    overdue.sort(key=lambda x: -x["age_days"])

    payload = {"today": today.isoformat(), "days": args.days, "overdue_count": len(overdue),
               "overdue": overdue, "unreadable": skipped}
    if args.json:
        emit(payload, True, "")
    else:
        print(f"[fengoslist] due：status=evaluating 且 updated 已 ≥{args.days} 天未动（今天 {today.isoformat()}）")
        if not overdue:
            print(f"[fengoslist] ✅ 无超期 evaluating")
        else:
            headers = ["NAME", "KIND", "UPDATED", "未更新", "超期", "VERDICT(还在评什么)"]
            widths = [30, 10, 12, 8, 8, 50]
            rows = [[trunc(o["name"], 30), o["kind"], o["updated"],
                     f"{o['age_days']}天", f"{o['beyond_days']}天", trunc(o["verdict"], 50)] for o in overdue]
            print(render_table(headers, rows, widths))
            print(f"\n[fengoslist] ⚠️ {len(overdue)} 条 evaluating 已超期腐烂线（阈值 {args.days} 天），"
                  f"要么推进落地、要么按 note/verdict 改判 status。")
        for s in skipped:
            print(f"[fengoslist] ⚠️ {s['name']}: updated 缺失/非法（{s['updated']}），无法计算超期 —— {s['reason']}")
    return 1 if overdue else 0


# ============================================================
# CLI
# ============================================================

def add_common(sp, sub=False):
    """每个子命令都挂 --json / --file，放子命令之前或之后都能用。

    注意：Python 3.7+ 的子命令解析会把子解析器的默认值回写进主命名空间，
    因此子解析器侧必须用 argparse.SUPPRESS（不给默认值），否则
    `fengoslist.py --json stats` 这种「选项在前」的写法会被悄悄覆盖成 False。
    """
    d_json = argparse.SUPPRESS if sub else False
    d_file = argparse.SUPPRESS if sub else LIST_PATH
    sp.add_argument("--json", action="store_true", default=d_json, help="纯净 JSON 输出")
    sp.add_argument("--file", default=d_file, help="台账路径（默认 data/config/opensource_list.json）")


def build_parser():
    ap = argparse.ArgumentParser(
        prog="fengoslist.py",
        description="开源项目决策台账校验器（data/config/opensource_list.json）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
               "  python tools/fengoslist.py validate\n"
               "  python tools/fengoslist.py list --status rejected\n"
               "  python tools/fengoslist.py stats --json\n"
               "  python tools/fengoslist.py due --days 14\n",
    )
    add_common(ap)
    sub = ap.add_subparsers(dest="cmd")

    p_val = sub.add_parser("validate", help="schema/条件必填/落点存在性校验，不合格 exit(1)")
    add_common(p_val, sub=True)
    p_val.set_defaults(func=cmd_validate)

    p_list = sub.add_parser("list", help="表格视图")
    add_common(p_list, sub=True)
    p_list.add_argument("--status", help=f"按 status 过滤（{'/'.join(STATUS_VALUES)}）")
    p_list.add_argument("--kind", help=f"按 kind 过滤（{'/'.join(KIND_VALUES)}）")
    p_list.set_defaults(func=cmd_list)

    p_stats = sub.add_parser("stats", help="条数与 status/kind 分布")
    add_common(p_stats, sub=True)
    p_stats.set_defaults(func=cmd_stats)

    p_due = sub.add_parser("due", help="揪出超期未动的 evaluating（有声，超期 exit(1)）")
    add_common(p_due, sub=True)
    p_due.add_argument("--days", type=int, default=DUE_DEFAULT_DAYS,
                       help=f"超期阈值天数（默认 {DUE_DEFAULT_DAYS}）")
    p_due.add_argument("--today", help="把「今天」钉死为某天 YYYY-MM-DD（测试用）")
    p_due.set_defaults(func=cmd_due)

    return ap


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = build_parser()
    args = ap.parse_args(argv)
    if not getattr(args, "cmd", None):
        ap.print_help()
        return 1
    days = getattr(args, "days", None)
    if days is not None and days < 0:
        print("[fengoslist] ❌ --days 不能为负数")
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
