#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fengadopt.py — 外部框架并入对账器（research/130-external-frameworks/<项目>/）。

用途
    外部项目并入本仓后，最怕四件事：① 台账写着"已并入"但落点文件根本不存在；
    ② 台账写着"自有承接"但承接者是个不存在的名字；③ 本仓副本被人（或未来的自己）偷改，
    与上游原文不再逐字一致，而没人发现；④ 条目既没有承接者、又被硬写成 absorbed 糊过去
    （2026-09-17 起这种条目必须判 kept，owner 留空，本工具硬闸门）。本工具就是这四件事的守门人：
    读 ADOPTION.json（逐文件归属）+ UPSTREAM.json（上游指纹）→ 四项检查 → 任一漂移 exit(1) 有声。

用法
    python tools/fengadopt.py verify                 # 四项检查；全过 ✅ exit(0)，任一不合格 exit(1)
    python tools/fengadopt.py stats                  # 四档计数 + 按 owner 分组
    python tools/fengadopt.py list --status kept     # 按状态列出条目
    python tools/fengadopt.py stats --json           # 任一子命令均可 --json 取纯净输出
    python tools/fengadopt.py verify --project ai-berkshire

四档与校验规则（与 AGENTS.md「外部框架并入铁律」同源）
    absorbed   = 正文在本仓 + 有自有承接者  → landing 存在且非空，owner 非空且逐个能解析到 .agents/skills/<owner>/ 或 tools/<owner>.py
    kept       = 正文在本仓 + 无自有承接者  → landing 存在且非空，owner 必须为空（有值即报错）
    superseded = 上游有、本系统已自有承接    → owner 非空且逐个能解析到
    referenced = 本仓无正文副本，只写上游仓库 + 上游文件路径 → landing 可空；若写了落点则须存在且非空

四项检查（检查①③按 status 分派：absorbed / kept / superseded 必须有本仓正文，referenced 不要求）
    ① landing 存在且非空（absorbed / kept：正文在本仓就必须有落点；referenced 写了 landing 才查）
    ② owner 硬校验（absorbed / superseded 的 owner 必须能在 .agents/skills/ 或 tools/ 解析到；
       kept 的 owner 必须为空——"正文在仓但没人用"不许冒充 absorbed）
    ③ 台账与正文对得上：absorbed / kept / superseded 的 upstream_file 在 <项目>/skills/ 下有对应非空文件；
       referenced 不要求本仓正文（本仓无副本是它的定义）。反向也对（正文文件没有台账条目 = 漏登记；
       要求有正文的上游文件在本仓没有正文 = 漏落）；UPSTREAM.json 的 files 与 ADOPTION.json 条目一一对应
    ④ 正文 sha256 与 UPSTREAM.json 记录一致（剥掉 2 行来源标注头 + 1 空行后重算 → 防偷改）

铁律
    1. 只读：本工具绝不修改 ADOPTION.json / UPSTREAM.json / 仓库任何文件与 DB。
    2. 有声失败：任一检查不合格 → 逐条打印明细 + exit(1)，绝不静默通过、绝不用 ⚠️ 宽宥放行。
    3. sha256 只对"上游原文"计算：本仓副本正文 = 上游原文逐字节，标注头由工具剥掉后再算。
    4. 纯标准库、零第三方依赖；读写一律显式 encoding="utf-8"（Windows 默认 GBK 会乱码）。

退出码：0 = 全通过；1 = 存在漂移；2 = 文件缺失 / JSON 解析失败。
"""

import argparse
import hashlib
import json
import os
import sys

# Windows GBK 控制台防崩：emoji/中文输出统一走 UTF-8（否则 ✅❌ 直接 UnicodeEncodeError）。
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
EXT_ROOT_REL = os.path.join("research", "130-external-frameworks")
DEFAULT_PROJECT = "ai-berkshire"

STATUS_VALUES = ("absorbed", "kept", "referenced", "superseded")
# 要求"本仓必须有非空正文"的状态；referenced 是四档里唯一允许本仓无正文的档
BODY_STATUS_VALUES = ("absorbed", "kept", "superseded")
ENTRY_KEYS = ("upstream_file", "status", "owner", "landing", "note")

# 来源标注头：逐行以 <!-- 开头的注释行，其后紧跟 1 个空行（由导入脚本统一生成）
HEADER_COMMENT_PREFIX = "<!--"
HEADER_BLANK_AFTER = 1


# ============================================================
# 工具函数
# ============================================================

def emit(obj, as_json, text):
    """统一输出：--json 走 json.dumps（ensure_ascii=False），否则走文本。"""
    if as_json:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    else:
        if text:
            sys.stdout.write(text + "\n")


def dwidth(s):
    """显示宽度（东亚宽字符算 2）。"""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in str(s))


def pad(s, width):
    s = str(s)
    return s + " " * max(0, width - dwidth(s))


def trunc(s, width):
    import unicodedata
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
    lines = ["  ".join(pad(h, w) for h, w in zip(headers, widths)).rstrip(),
             "-" * (sum(widths) + 2 * (len(widths) - 1))]
    for row in rows:
        lines.append("  ".join(pad(c, w) for c, w in zip(row, widths)).rstrip())
    return "\n".join(lines)


def strip_header(raw):
    """剥掉导入时加的来源标注头（若干 <!-- ... --> 行 + 其后 1 个空行），返回正文 bytes。

    只按"行首是否为 HTML 注释起始"判断，正文里出现的 <!-- 不受影响（正文不以注释开头）。
    """
    lines = raw.split(b"\n")
    i = 0
    while i < len(lines) and lines[i].startswith(HEADER_COMMENT_PREFIX.encode("utf-8")):
        i += 1
    if i > 0:
        for _ in range(HEADER_BLANK_AFTER):
            if i < len(lines) and lines[i].strip() == b"":
                i += 1
    return b"\n".join(lines[i:])


def sha256_raw(raw):
    return hashlib.sha256(raw).hexdigest()


def expected_local_name(upstream_file):
    """上游相对路径 → 本仓 skills/ 下的文件名。

    惯例：skills/x.md → x.md；嵌套的 SKILL.md（如 codex-skills/foo/SKILL.md）→ foo.md。
    """
    base = os.path.basename(upstream_file)
    if base.lower() == "skill.md":
        return os.path.basename(os.path.dirname(upstream_file)) + ".md"
    return base


def read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def load_json(path):
    """返回 (data, err)。"""
    if not os.path.isfile(path):
        return None, "文件不存在: %s" % path
    try:
        return json.loads(read_text(path)), None
    except json.JSONDecodeError as e:
        return None, "JSON 解析失败 %s: %s" % (path, e)


# ============================================================
# 项目路径
# ============================================================

def project_paths(project):
    rel = os.path.join(EXT_ROOT_REL, project)
    absdir = os.path.join(ROOT, rel)
    return {
        "rel": rel.replace(os.sep, "/"),
        "abs": absdir,
        "adoption": os.path.join(absdir, "ADOPTION.json"),
        "upstream": os.path.join(absdir, "UPSTREAM.json"),
        "skills": os.path.join(absdir, "skills"),
    }


def to_rel_ok(path):
    """把 landing 归一成相对路径（正斜杠）。绝对路径视为不合格（公开文件禁止本机路径）。"""
    if os.path.isabs(path):
        return None
    return path.replace("\\", "/").lstrip("./")


# ============================================================
# 检查
# ============================================================

def resolve_owner(token):
    """owner token 是否能在本仓解析到自有 skill/tool。返回 (ok, 说明)。"""
    token = token.strip()
    if not token:
        return False, "空 owner"
    if "/" in token or "\\" in token:
        p = os.path.join(ROOT, token.replace("/", os.sep))
        return (os.path.exists(p), "路径落点 %s" % token)
    if token.endswith(".py"):
        p = os.path.join(ROOT, "tools", token)
        return (os.path.isfile(p), "tools/%s" % token)
    skill = os.path.join(ROOT, ".agents", "skills", token, "SKILL.md")
    if os.path.isfile(skill):
        return True, ".agents/skills/%s/SKILL.md" % token
    tool = os.path.join(ROOT, "tools", token + ".py")
    if os.path.isfile(tool):
        return True, "tools/%s.py" % token
    return False, "既无 .agents/skills/%s/SKILL.md 也无 tools/%s.py" % (token, token)


def split_owners(owner):
    if owner is None:
        return []
    if isinstance(owner, list):
        raw = [str(x) for x in owner]
    else:
        raw = str(owner).replace(",", "+").split("+")
    return [t.strip() for t in raw if t.strip()]


def owner_is_empty(owner):
    """owner 是否为空（null / "" / 空数组 / 纯空白）。"""
    return not split_owners(owner)


def short_file(upstream_file):
    """显示用的短名：只剥掉开头的 `skills/`（不能对 `codex-skills/` 做替换，否则会削成乱名）。"""
    s = str(upstream_file or "")
    return s[len("skills/"):] if s.startswith("skills/") else s


def run_checks(project):
    """跑四项检查，返回 (errors, warnings, info, entries, upstream)。"""
    pp = project_paths(project)
    errors, warnings = [], []

    adoption, err1 = load_json(pp["adoption"])
    if err1:
        return [err1], [], {}, None, None
    upstream, err2 = load_json(pp["upstream"])
    if err2:
        return [err2], [], {}, None, None

    entries = adoption.get("entries")
    if not isinstance(entries, list):
        return ["ADOPTION.json: `entries` 必须是数组"], [], {}, None, None
    files = upstream.get("files")
    if not isinstance(files, dict):
        return ["UPSTREAM.json: `files` 必须是对象"], [], {}, None, None

    sk = pp["skills"]
    if not os.path.isdir(sk):
        errors.append("正文目录不存在: %s" % os.path.join(pp["rel"], "skills"))

    # ---- 逐条 ----
    seen = set()
    for i, e in enumerate(entries):
        tag = "[%02d] %s" % (i + 1, e.get("upstream_file") if isinstance(e, dict) else "?")
        if not isinstance(e, dict):
            errors.append("%s: 条目不是 JSON 对象" % tag)
            continue
        for k in ENTRY_KEYS:
            if k not in e:
                errors.append("%s: 缺字段 `%s`" % (tag, k))
        uf = e.get("upstream_file") or ""
        st = e.get("status")
        landing = e.get("landing")
        owner = e.get("owner")

        if uf in seen:
            errors.append("%s: upstream_file 重复登记" % tag)
        seen.add(uf)
        if st not in STATUS_VALUES:
            errors.append("%s: status=`%s` 非法，应为 %s" % (tag, st, "/".join(STATUS_VALUES)))
        if not isinstance(e.get("note"), str) or not (e.get("note") or "").strip():
            errors.append("%s: note 不能为空（每条都要有依据）" % tag)

        # status 决定"本仓是否必须有正文"：只有 referenced 允许本仓无正文
        requires_body = st in BODY_STATUS_VALUES
        has_landing = isinstance(landing, str) and bool(landing.strip())

        # landing 归一 + 与上游文件名的对应关系（referenced 允许为空；其余必须给落点）
        land_rel = None
        if not has_landing:
            if st != "referenced":
                errors.append("%s: landing 不能为空" % tag)
        else:
            land_rel = to_rel_ok(landing)
            if land_rel is None:
                errors.append("%s: landing 必须写本仓相对路径，禁止本机绝对路径 `%s`" % (tag, landing))
            elif requires_body:
                exp = "%s/skills/%s" % (pp["rel"], expected_local_name(uf)) if uf else None
                if exp and land_rel != exp:
                    errors.append("%s: landing=`%s` 与上游文件名推不出的一致落点 `%s` 不符" % (tag, land_rel, exp))

        # ① absorbed / kept：正文在本仓 → landing 必须存在且非空
        if st in ("absorbed", "kept") and land_rel:
            p = os.path.join(ROOT, land_rel)
            if not os.path.isfile(p):
                errors.append("%s: [检查①] %s 的 landing 在本仓不存在 → %s" % (tag, st, land_rel))
            elif os.path.getsize(p) == 0:
                errors.append("%s: [检查①] %s 的 landing 是空文件 → %s" % (tag, st, land_rel))

        # ② owner 硬校验：absorbed / superseded 必须非空且逐个可解析；kept 必须为空
        if st in ("absorbed", "superseded"):
            toks = split_owners(owner)
            if not toks:
                errors.append("%s: [检查②] %s 必须写 owner（本仓真实存在的承接 skill/tool 名）" % (tag, st))
            for t in toks:
                ok, how = resolve_owner(t)
                if not ok:
                    errors.append("%s: [检查②] %s 的 owner `%s` 无法解析（%s）" % (tag, st, t, how))
        if st == "kept":
            if not owner_is_empty(owner):
                errors.append("%s: [检查②] kept 的 owner 必须为空（`%s`）——正文在本仓但无承接者才算留档；"
                              "若有真实承接者请改判 absorbed 并填 owner" % (tag, owner))

        # ③ upstream_file 与正文的对应（按 status 分派）
        if uf:
            if uf not in files:
                errors.append("%s: [检查③] upstream_file 不在 UPSTREAM.json.files 中" % tag)
            if requires_body:
                exp_local = os.path.join(sk, expected_local_name(uf))
                if not os.path.isfile(exp_local):
                    errors.append("%s: [检查③] 本仓无对应正文文件 → %s" % (tag, os.path.relpath(exp_local, ROOT).replace(os.sep, "/")))
                elif os.path.getsize(exp_local) == 0:
                    errors.append("%s: [检查③] 正文文件为空 → %s" % (tag, os.path.relpath(exp_local, ROOT).replace(os.sep, "/")))
        # referenced 本仓本就没有正文（合法）；但既然写了 landing，就不许指空
        if st == "referenced" and land_rel:
            p = os.path.join(ROOT, land_rel)
            if not os.path.isfile(p):
                errors.append("%s: [检查③] referenced 写了 landing 但该路径在本仓不存在 → %s" % (tag, land_rel))
            elif os.path.getsize(p) == 0:
                errors.append("%s: [检查③] referenced 的 landing 是空文件 → %s" % (tag, land_rel))

    # ---- 反向：只对"要求有本地正文"的 status 计数（referenced 本仓无正文，不参与计数）----
    if os.path.isdir(sk):
        status_of = {e.get("upstream_file"): e.get("status")
                     for e in entries if isinstance(e, dict) and e.get("upstream_file")}
        # 上游文件里哪些必须在 <项目>/skills/ 下另有正文；referenced 不要求
        body_upstream = [uf for uf in sorted(files) if status_of.get(uf) != "referenced"]
        on_disk = sorted(f for f in os.listdir(sk) if f.lower().endswith(".md"))
        claimed = {expected_local_name(e.get("upstream_file") or "") for e in entries if isinstance(e, dict)}
        for f in on_disk:
            if f not in claimed:
                errors.append("[检查③] 正文文件 `%s` 没有台账条目（漏登记）" % f)
        n_files = upstream.get("file_count")
        if isinstance(n_files, int) and n_files != len(files):
            errors.append("[检查③] UPSTREAM.json.file_count=%d 与 files 条数 %d 不符" % (n_files, len(files)))
        if len(on_disk) != len(body_upstream):
            errors.append("[检查③] 本仓正文文件数 %d 与要求有正文的上游文件数 %d 不符"
                          "（absorbed / kept / superseded 必须有正文；referenced 无正文）"
                          % (len(on_disk), len(body_upstream)))
        for uf in body_upstream:
            exp_local = os.path.join(sk, expected_local_name(uf))
            if not os.path.isfile(exp_local):
                errors.append("[检查③] UPSTREAM.json 的上游文件 `%s` 在本仓无对应正文" % uf)

    # ---- ④ sha256 防偷改 ----
    for uf, want in sorted(files.items()):
        local = os.path.join(sk, expected_local_name(uf))
        if not os.path.isfile(local):
            continue  # 已在检查③ 报过
        got = sha256_raw(strip_header(read_bytes(local)))
        if got != want:
            errors.append("[检查④] 正文被改过（sha256 不符）→ %s\n            上游记录 %s\n            本仓实算 %s"
                          % (os.path.relpath(local, ROOT).replace(os.sep, "/"), want, got))

    info = {
        "project": project,
        "dir": pp["rel"],
        "commit": upstream.get("commit"),
        "repo": upstream.get("repo"),
        "entries": len(entries),
        "upstream_files": len(files),
        "local_bodies": len([f for f in (os.listdir(sk) if os.path.isdir(sk) else []) if f.lower().endswith(".md")]),
    }
    return errors, warnings, info, entries, upstream


# ============================================================
# 子命令
# ============================================================

def cmd_verify(args):
    errors, warnings, info, entries, _ = run_checks(args.project)
    ok = not errors
    if args.json:
        emit({"ok": ok, "info": info, "errors": errors, "warnings": warnings}, True, None)
    else:
        if info:
            print("[fengadopt] 项目 %s（commit %s）｜台账 %d 条 / 上游 %d 文件 / 本仓正文 %d 份"
                  % (info["project"], info["commit"], info["entries"], info["upstream_files"], info["local_bodies"]))
        if errors:
            print("[fengadopt] ❌ 检查未通过，共 %d 项漂移：" % len(errors))
            for e in errors:
                print("  - %s" % e)
        else:
            print("[fengadopt] ✅ 四项检查全过（落点存在 / owner 硬校验：absorbed·superseded 必填且可解析、kept 必空 / 台账与正文一一对应：absorbed·kept·superseded 必有正文、referenced 无正文 / sha256 未被偷改）")
        for w in warnings:
            print("  ⚠️  %s" % w)
    return 0 if ok else 1


def cmd_stats(args):
    errors, warnings, info, entries, _ = run_checks(args.project)
    if entries is None:
        emit({"ok": False, "errors": errors}, args.json, "[fengadopt] ❌ " + "；".join(errors))
        return 2
    counts = {s: 0 for s in STATUS_VALUES}
    for e in entries:
        st = e.get("status")
        counts[st] = counts.get(st, 0) + 1
    owner_groups = {}
    for e in entries:
        toks = split_owners(e.get("owner"))
        if e.get("status") not in ("absorbed", "superseded"):
            continue
        for t in toks:
            owner_groups.setdefault(t, []).append(e.get("upstream_file"))
    payload = {
        "ok": not errors,
        "project": args.project,
        "total": len(entries),
        "status_counts": counts,
        "owner_groups": {k: v for k, v in sorted(owner_groups.items())},
        "without_owner": sorted(e.get("upstream_file") for e in entries
                                if e.get("status") in ("absorbed", "superseded") and not split_owners(e.get("owner"))),
        "kept": sorted(e.get("upstream_file") for e in entries if e.get("status") == "kept"),
    }
    if args.json:
        emit(payload, True, None)
    else:
        lines = ["[fengadopt] 项目 %s ｜ 条目 %d（%s）" % (args.project, len(entries),
                 "，".join("%s %d" % (s, counts.get(s, 0)) for s in STATUS_VALUES))]
        widths = (18, 8, 46)
        rows = [[s, str(counts.get(s, 0)), ""] for s in STATUS_VALUES]
        lines.append(render_table(["status", "条数", ""], rows, widths))
        lines.append("")
        lines.append("按 owner 分组（absorbed / superseded 条目，多承接者按 token 拆开）：")
        if owner_groups:
            rows = [[t, str(len(v)), ", ".join(short_file(x) for x in v)] for t, v in sorted(owner_groups.items())]
            lines.append(render_table(["owner（自有承接者）", "条数", "上游文件"], rows, (24, 6, 60)))
        else:
            lines.append("  （无）")
        if payload["kept"]:
            lines.append("")
            lines.append("留档（kept，正文在本仓、无承接者）：%d 条 —— %s"
                         % (len(payload["kept"]), ", ".join(short_file(x) for x in payload["kept"])))
        if payload["without_owner"]:
            lines.append("")
            lines.append("⚠️  absorbed / superseded 但没写 owner：%s" % ", ".join(payload["without_owner"]))
        emit(payload, False, "\n".join(lines))
    return 0 if not errors else 1


def cmd_list(args):
    errors, warnings, info, entries, _ = run_checks(args.project)
    if entries is None:
        emit({"ok": False, "errors": errors}, args.json, "[fengadopt] ❌ " + "；".join(errors))
        return 2
    rows_data = []
    for e in entries:
        st = e.get("status")
        if args.status and st != args.status:
            continue
        land = e.get("landing") or ""
        land_rel = to_rel_ok(land) if isinstance(land, str) else None
        exists = bool(land_rel) and os.path.isfile(os.path.join(ROOT, land_rel))
        rows_data.append({
            "upstream_file": e.get("upstream_file"),
            "status": st,
            "owner": e.get("owner"),
            "landing": land_rel,
            "landing_exists": exists,
        })
    hit = len(rows_data)
    if args.json:
        emit({"ok": not errors, "project": args.project, "status_filter": args.status,
              "count": hit, "entries": rows_data}, True, None)
    else:
        rows = [[trunc(r["upstream_file"], 48), r["status"], trunc(r["owner"] if r["owner"] else "—", 26),
                 "✅" if r["landing_exists"] else "❌"] for r in rows_data]
        hdr = "[fengadopt] 项目 %s ｜ status=%s ｜ %d 条" % (args.project, args.status or "全部", hit)
        emit(None, False, hdr + "\n" + render_table(["upstream_file", "status", "owner", "落点"], rows, (48, 12, 26, 6)))
    return 0 if not errors else 1


# ============================================================
# 入口
# ============================================================

def add_common(sp, sub=False):
    """每个子命令都挂 --json / --project，放子命令之前或之后都能用。

    注意：Python 3.7+ 的子命令解析会把子解析器的默认值回写进主命名空间，
    因此子解析器侧必须用 argparse.SUPPRESS（不给默认值），否则
    `fengadopt.py --json stats` 这种「选项在前」的写法会被悄悄覆盖成 False。
    """
    d_json = argparse.SUPPRESS if sub else False
    d_proj = argparse.SUPPRESS if sub else DEFAULT_PROJECT
    sp.add_argument("--json", action="store_true", default=d_json, help="纯净 JSON 输出")
    sp.add_argument("--project", default=d_proj,
                    help="research/130-external-frameworks/ 下的项目目录名（默认 %s）" % DEFAULT_PROJECT)


def build_parser():
    ap = argparse.ArgumentParser(
        prog="fengadopt.py",
        description="外部框架并入对账器（research/130-external-frameworks/<项目>/ 的 ADOPTION.json + UPSTREAM.json）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例：\n"
               "  python tools/fengadopt.py verify\n"
               "  python tools/fengadopt.py stats --json\n"
               "  python tools/fengadopt.py list --status superseded\n",
    )
    add_common(ap)
    sub = ap.add_subparsers(dest="cmd")

    p_v = sub.add_parser("verify", help="四项检查（含 owner 硬校验）；任一漂移 → 逐条明细 + exit(1)")
    add_common(p_v, sub=True)
    p_v.set_defaults(func=cmd_verify)

    p_s = sub.add_parser("stats", help="四档计数 + 按 owner 分组")
    add_common(p_s, sub=True)
    p_s.set_defaults(func=cmd_stats)

    p_l = sub.add_parser("list", help="按状态列出条目")
    add_common(p_l, sub=True)
    p_l.add_argument("--status", help="按 status 过滤（%s）" % "/".join(STATUS_VALUES))
    p_l.set_defaults(func=cmd_list)

    return ap


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = build_parser()
    args = ap.parse_args(argv)
    if not getattr(args, "cmd", None):
        ap.print_help()
        return 1
    if getattr(args, "cmd", None) == "list" and args.status and args.status not in STATUS_VALUES:
        print("[fengadopt] ❌ --status=`%s` 非法，应为 %s" % (args.status, "/".join(STATUS_VALUES)))
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
