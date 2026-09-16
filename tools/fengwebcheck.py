# -*- coding: utf-8 -*-
"""FengInvest 全站体检脚本 fengwebcheck.py

维度: A 路由存活 / B API连通 / C MD渲染 / D 溢出 / E 数据新鲜度 /
      F 前后端字段贴合 / G 控制台错误 / H 性能冒烟
用法: python tools/fengwebcheck.py [--base http://localhost:23456] [--quick] [--no-color]
  --quick 只跑 A+B+C
输出: 终端彩色表 + reports/webcheck_YYYY-MM-DD_HHMM.json, fail>0 则 exit 1
依赖缺失(requests/playwright)自动降级,中文 utf-8.
"""
import argparse
import datetime
import json
import os
import re
import sqlite3
import sys
import time
from urllib.parse import quote

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from playwright.sync_api import sync_playwright
    HAS_PW = True
except ImportError:
    HAS_PW = False

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(TOOLS_DIR)
REPORTS_DIR = os.path.join(PROJECT_DIR, "reports")

GREEN, RED, YELLOW, CYAN, DIM, RESET = "", "", "", "", "", ""
USE_COLOR = False


def adjacent_btn_gap_hits(src):
    """相邻btn无gap容器:找同一父元素内相邻的两个以上btn元素(<a class="btn...">或
    <button class="btn...">),父元素(标签栈顶,跳过已闭合标签)无flex/grid/gap/btn-group则命中。
    返回命中处的父标签原文列表(空=无命中)。"""
    hits = []
    pat = (r'<(a|button)\b[^>]*class="[^"]*\bbtn\b[^"]*"[^>]*>[\s\S]*?</\1>'
           r"(?:\s|<%[\s\S]*?%>)*"
           r'<(?:a|button)\b[^>]*class="[^"]*\bbtn\b')
    for m in re.finditer(pat, src, re.I | re.S):
        before = src[max(0, m.start() - 2000):m.start()]
        stack = []
        for t in re.finditer(
                r"</?(div|td|span|p|li|th|ul|section|article|header|footer|nav|"
                r"form|tr|table|body)[^>]*>", before, re.I):
            tag = t.group(0)
            if tag.startswith("</"):
                if stack and stack[-1][0].lower() == t.group(1).lower():
                    stack.pop()
            elif not tag.endswith("/>"):
                stack.append((t.group(1), tag))
        parent = stack[-1][1] if stack else ""
        if not re.search(r"display\s*:\s*(flex|inline-flex|grid)|gap\s*:|btn-group|d-flex",
                         parent, re.I):
            hits.append(parent or "(无父标签)")
    return hits


# 裸链接白名单:class 或 style 已带这些语义的 <a> 不算裸链接(按钮/导航/卡片块/图标链接)
BARE_LINK_EXEMPT = (
    "btn", "nav-item", "entry-item", "nav-more", "sidebar-logo", "crumb",
    "kb-mini-card", "source-tag", "badge", "tab", "nav-link", "footer",
)


def bare_link_hits(src):
    """裸下划线超链接:正文中 <a href=...> 既无 class、style 里也没有
    text-decoration:none 的,会渲染成默认下划线蓝链——创始人立规:动作一律按钮化。
    返回命中链接文本列表(空=无命中)。"""
    hits = []
    src = re.sub(r"<script[\s\S]*?</script>", "", src, flags=re.I)  # JS 模板串非静态链接
    for m in re.finditer(r'<a\b([^>]*)>([\s\S]*?)</a>', src, re.I):
        attrs, inner = m.group(1), m.group(2)
        if '<%' in attrs or '%>' in attrs:
            continue  # EJS 插值在标签里,属性解析不可靠,跳过(防误报)
        back = src[max(0, m.start() - 200):m.start()]
        if 'breadcrumb' in back and '</div>' not in back[back.rfind('breadcrumb'):]:
            continue  # 面包屑容器内的链接是位置导航,不是动作按钮
        if 'FengI18n' in inner or '<%' in inner:
            continue  # JS/EJS 动态拼出的链接文本,静态解析不可靠
        if not re.search(r'\bhref\s*=\s*["\'](?!#)', attrs, re.I):
            continue
        if re.search(r'\bclass\s*=\s*["\']', attrs, re.I):
            cls = re.search(r'\bclass\s*=\s*["\']([^"\']*)["\']', attrs, re.I)
            if cls and any(w in cls.group(1) for w in BARE_LINK_EXEMPT):
                continue
            if cls and cls.group(1).strip():
                continue  # 有任意 class 即有样式语义,交给 CSS 管
        style = re.search(r'\bstyle\s*=\s*["\']([^"\']*)["\']', attrs, re.I)
        if style and re.search(r'text-decoration\s*:\s*none', style.group(1), re.I):
            continue
        text = re.sub(r"<%[\s\S]*?%>", "", inner)
        text = re.sub(r"<[^>]+>", "", text).strip()
        if text:
            hits.append(text[:24])
    return hits


# ---------- D维静态扩充:i18n对账 / EJS未定义变量 ----------
# 引用面属性:data-i18n(textContent)及其 -ph/-placeholder/-html/-tt 变体;
# 值按包围引号配对匹配(值内允许出现另一种引号,如 <%= cond ? 'a' : 'b' %>)
I18N_ATTR_RE = re.compile(
    r"data-i18n(?:-ph|-placeholder|-html|-tt)?\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", re.I)
# data-empty-key=词典键(data-block 渲染器的空态文案键,由 js 消费)
I18N_EMPTY_KEY_RE = re.compile(r"data-empty-key\s*=\s*[\"']([^\"']+)[\"']", re.I)
# JS 静态调用 T('key') / FengI18n.t('key', ...):独立 t/T 名 + 引号字面量首参
I18N_TCALL_RE = re.compile(r"\b(?:FengI18n\s*\.\s*t|[Tt])\(\s*[\"']([A-Za-z_$][\w.\-]*)[\"']")
I18N_KEY_LIT_RE = re.compile(r"[\"']([A-Za-z_$][\w.\-]*[\.][\w.\-]+)[\"']")
# T('key')/T(expr || 'key') 首参内的全部引号键字面量:定位调用起点后按括号深度
# 走到首个顶层逗号/闭括号,收集其中所有点号键(兜底含 getAttribute 的嵌套括号)
I18N_TCALL_START_RE = re.compile(r"\b(?:FengI18n\s*\.\s*t|[Tt])\(")


def _t_call_first_arg_keys(src):
    """收集 T(...) 首参内出现的引号点号键字面量(含 expr || 'key' 兜底)。"""
    keys = set()
    for m in I18N_TCALL_START_RE.finditer(src):
        i, n, depth = m.end(), len(src), 1
        seg_start = i
        while i < n and depth > 0:
            c = src[i]
            if c in "'\"`":
                q = c
                i += 1
                while i < n and src[i] != q:
                    i += 2 if src[i] == "\\" else 1
                i += 1
                continue
            if c in "([{":
                depth += 1
            elif c in ")]}":
                depth -= 1
                if depth == 0:
                    break
            elif c == "," and depth == 1:
                break
            i += 1
        seg = src[seg_start:i]
        keys |= set(I18N_KEY_LIT_RE.findall(seg))
    return keys
EJS_EMIT_RE = re.compile(r"<%[=\-]([\s\S]*?)%>")
EJS_SCRIPTLET_RE = re.compile(r"<%(?![=\-#%])([\s\S]*?)%>")
EJS_IDENT_RE = re.compile(r"[A-Za-z_$][\w$]*")
EJS_KW_GLOBALS = set("""
if else for while do switch case default break continue return typeof instanceof
new in of var let const function true false null undefined this delete void
try catch finally throw yield async await class extends super import export
JSON Math String Number Boolean Array Object Date RegExp Error Promise Symbol
Map Set WeakMap WeakSet Intl isNaN parseInt parseFloat isFinite NaN Infinity
encodeURIComponent decodeURIComponent encodeURI decodeURI arguments
require module exports window document console localStorage sessionStorage
location navigator fetch alert confirm prompt setTimeout setInterval clearTimeout
""".split())
# render locals 通用白名单:前9项为基线;names=server.ts res.locals 注入;
# body=express-ejs-layouts 布局注入(按 fengweb/src/server.ts 实际情况定)
EJS_COMMON_LOCALS = {"title", "error", "user", "session", "req", "query",
                     "data", "config", "alerts", "names", "body"}


def _strip_js_comments(src):
    """字符串感知地剥离 JS 的 // 与 /* */ 注释,防注释里的示例键(如 i18n.js
    文档头的 data-i18n="key")被误当引用;字符串字面量原样保留。"""
    out, i, n = [], 0, len(src)
    quote = None
    while i < n:
        c = src[i]
        if quote:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(src[i + 1]); i += 2; continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "'\"`":
            quote = c; out.append(c); i += 1
            continue
        if c == "/" and src[i:i + 2] == "//":
            nl = src.find("\n", i)
            i = nl if nl >= 0 else n
            continue
        if c == "/" and src[i:i + 2] == "/*":
            e = src.find("*/", i + 2)
            i = (e + 2) if e >= 0 else n
            continue
        out.append(c); i += 1
    return "".join(out)


def _flatten_i18n_keys(obj, prefix=""):
    """词典键展平:嵌套 dict 用点号路径;标量为叶子(扁平带点键自然保留)。"""
    keys = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = "%s.%s" % (prefix, k) if prefix else str(k)
            if isinstance(v, dict):
                keys |= _flatten_i18n_keys(v, p)
            else:
                keys.add(p)
    return keys


def _balanced_braces(src, start):
    """src[start]须为'{',带字符串/注释感知地找配对'}',返回含括号块文本(失配返回None)。"""
    depth, quote, i, n = 0, None, start, len(src)
    while i < n:
        c = src[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
        elif c == "/" and src[i:i + 2] == "//":
            nl = src.find("\n", i)
            i = nl if nl >= 0 else n
            continue
        elif c == "/" and src[i:i + 2] == "/*":
            e = src.find("*/", i + 2)
            i = (e + 2) if e >= 0 else n
            continue
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
        i += 1
    return None


def _obj_literal_keys(block):
    """对象字面量顶层键:key: value / 'key': value / 简写标识符;忽略 ...spread。"""
    inner = block[1:-1] if block.startswith("{") and block.endswith("}") else block
    parts, depth, quote, seg = [], 0, None, 0
    i = 0
    while i < len(inner):
        c = inner[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "'\"`":
            quote = c
        elif c == "/" and inner[i:i + 2] == "//":
            nl = inner.find("\n", i)
            i = nl if nl >= 0 else len(inner)
            continue
        elif c == "/" and inner[i:i + 2] == "/*":
            e = inner.find("*/", i + 2)
            i = (e + 2) if e >= 0 else len(inner)
            continue
        elif c in "{[(":
            depth += 1
        elif c in "}])":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append(inner[seg:i])
            seg = i + 1
        i += 1
    parts.append(inner[seg:])
    keys = set()
    for p in parts:
        p = p.strip()
        if not p or p.startswith("..."):
            continue
        m = re.match(r"[\"']?([A-Za-z_$][\w$]*)[\"']?\s*:", p)
        if m:
            keys.add(m.group(1))
            continue
        if re.match(r"[A-Za-z_$][\w$]*$", p):
            keys.add(p)
    return keys


def _ejs_top_idents(expr):
    """emit表达式(<%= %> / <%- %>)内的顶层标识符:跳过字符串字面量、.prop/?.prop
    成员属性、对象字面量键({ k: })与 ...spread;返回标识符集合。"""
    out = set()
    i, n = 0, len(expr)
    quote = None
    while i < n:
        c = expr[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
            i += 1
            continue
        if c in "'\"`":
            quote = c
            i += 1
            continue
        if c == "/":
            prev = expr[:i].rstrip()
            if not prev or prev[-1] in "(,=:[!&|?{};+-*%~^<>":
                # 正则字面量(前文是运算/开括号语境):跳过本体与 flags,避免 g/i 等误报
                j, in_cls = i + 1, False
                while j < n:
                    ch = expr[j]
                    if ch == "\\":
                        j += 2
                        continue
                    if ch == "[":
                        in_cls = True
                    elif ch == "]":
                        in_cls = False
                    elif ch == "/" and not in_cls:
                        break
                    j += 1
                i = j + 1
                while i < n and (expr[i].isalpha() or expr[i] == "_"):
                    i += 1
                continue
        m = EJS_IDENT_RE.match(expr, i)
        if m:
            before = expr[:i].rstrip()
            after = expr[m.end():].lstrip()
            if not (before.endswith(".") or before.endswith("?.") or
                    (after.startswith(":") and before.endswith(("{", ",")))):
                out.add(m.group(0))
            i = m.end()
            continue
        i += 1
    return out


def enable_color(no_color: bool):
    global GREEN, RED, YELLOW, CYAN, DIM, RESET, USE_COLOR
    USE_COLOR = (not no_color) and sys.stdout.isatty()
    try:
        import colorama  # type: ignore
        colorama.just_fix_windows_console()
        USE_COLOR = not no_color
    except ImportError:
        pass
    if USE_COLOR:
        GREEN, RED, YELLOW, CYAN, DIM, RESET = (
            "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[2m", "\033[0m")


class Checker:
    def __init__(self, base: str, quick: bool):
        self.base = base.rstrip("/")
        self.quick = quick
        self.items = []          # 每项 {dim,name,url,status,ms,evidence,snippet}
        self.timings = []        # (name,url,ttfb_ms,total_ms)
        self.server_up = False
        self._api_cache = {}     # path -> (status,data_dict_or_None)

    # ---------- 基础 ----------
    def add(self, dim, name, url, status, evidence="", snippet="", ms=None):
        assert status in ("pass", "warn", "fail", "skip")
        self.items.append({"dim": dim, "name": name, "url": url,
                           "status": status, "ms": ms,
                           "evidence": evidence, "snippet": (snippet or "")[:300]})

    def fetch(self, path, timeout=15, method="GET", json_body=None):
        """返回 dict(code,ms,ttfb_ms,ctype,text,data,err)。"""
        url = self.base + path
        if not HAS_REQUESTS:
            return {"code": None, "ms": None, "ttfb_ms": None, "ctype": "",
                    "text": "", "data": None, "err": "no-requests(已降级,未实测)", "url": url}
        t0 = time.time()
        try:
            if method == "GET":
                r = requests.get(url, timeout=timeout, stream=True)
            else:
                r = requests.post(url, json=json_body or {}, timeout=timeout, stream=True)
            ttfb = (time.time() - t0) * 1000
            chunks = []
            for c in r.iter_content(chunk_size=65536, decode_unicode=False):
                if c:
                    chunks.append(c)
            total = (time.time() - t0) * 1000
            raw = b"".join(chunks)
            try:
                text = raw.decode("utf-8", errors="replace")
            except Exception:
                text = ""
            ctype = r.headers.get("Content-Type", "")
            data = None
            if "application/json" in ctype or text.lstrip().startswith(("{", "[")):
                try:
                    data = json.loads(text)
                except Exception:
                    data = None
            return {"code": r.status_code, "ms": round(total), "ttfb_ms": round(ttfb),
                    "ctype": ctype, "text": text, "data": data, "err": "", "url": url}
        except requests.exceptions.Timeout:
            return {"code": None, "ms": None, "ttfb_ms": None, "ctype": "",
                    "text": "", "data": None, "err": "timeout(>%ss)" % timeout, "url": url}
        except requests.exceptions.ConnectionError:
            return {"code": None, "ms": None, "ttfb_ms": None, "ctype": "",
                    "text": "", "data": None, "err": "connection-refused", "url": url}
        except Exception as e:
            return {"code": None, "ms": None, "ttfb_ms": None, "ctype": "",
                    "text": "", "data": None, "err": "error:%s" % str(e)[:120], "url": url}

    def check_server(self):
        r = self.fetch("/", timeout=10)
        self.server_up = r["code"] == 200
        return r

    # ---------- 动态路由样本发现(运行时,保真) ----------
    def discover(self):
        d = {"research": [], "report_shelf": [], "report_doc": [],
             "discuss": [], "knowledge": [], "masters": [], "holding": []}
        comp_dir = os.path.join(PROJECT_DIR, "research", "060-companies")
        try:
            comps = sorted([e for e in os.listdir(comp_dir)
                            if os.path.isdir(os.path.join(comp_dir, e))])
        except OSError:
            comps = []

        def ticker_of(dirname):
            m = re.match(r"^([A-Za-z0-9.]+)-", dirname)
            return m.group(1) if m else None

        for c in comps:
            t = ticker_of(c)
            if t and t not in d["research"]:
                d["research"].append(t)
        # 优先固定 3 个(跨市场代表),不足则补发现值
        prefer = ["NVDA", "0700.HK", "002032.SZ"]
        ordered = [t for t in prefer if t in d["research"]]
        ordered += [t for t in d["research"] if t not in ordered]
        d["research"] = ordered[:3]

        layer_re = re.compile(r"^(0[1-6]-|08-|l[0-4][abn]?\.(md|json)$|m\.(md|json)$|temp_)", re.I)
        for t in d["research"]:
            cdir = next((os.path.join(comp_dir, c) for c in comps if ticker_of(c) == t), None)
            if not cdir:
                continue
            d["report_shelf"].append(t)
            for root, dirs, files in os.walk(cdir):
                dirs[:] = [x for x in dirs if x not in ("sources", "temp")]
                for f in sorted(files):
                    if not f.endswith(".md"):
                        continue
                    if re.match(r"^(README|TODO|AUDIT_REPORT|00-INDEX)\.md$", f, re.I):
                        continue  # 与书架契约一致：审计产物与批次索引不进书架，撞 URL 必 404
                    if re.match(r"^\d{4}-\d{2}-\d{2}$", os.path.basename(root)) and layer_re.match(f):
                        continue  # 日期目录层文件走研究层视图，不进书架；own/community 不套用
                    rel = os.path.relpath(os.path.join(root, f), cdir).replace("\\", "/")
                    d["report_doc"].append((t, rel))
                    break
                if len(d["report_doc"]) >= 3:
                    break

        disc_dir = os.path.join(PROJECT_DIR, "Discussion")
        try:
            d["discuss"] = sorted([f for f in os.listdir(disc_dir) if f.endswith(".md")])[:3]
        except OSError:
            pass
        know_dir = os.path.join(PROJECT_DIR, "knowledge")
        for root, dirs, files in os.walk(know_dir):
            if "personal" in dirs:
                dirs.remove("personal")
            for f in sorted(files):
                if f.endswith(".md"):
                    rel = os.path.relpath(os.path.join(root, f), know_dir).replace("\\", "/")
                    d["knowledge"].append(rel)
                    if len(d["knowledge"]) >= 3:
                        break
            if len(d["knowledge"]) >= 3:
                break
        ppl_dir = os.path.join(PROJECT_DIR, "research", "040-people", "named")
        try:
            d["masters"] = sorted([f[:-3] for f in os.listdir(ppl_dir) if f.endswith(".md")])[:3]
        except OSError:
            pass
        hold_dir = os.path.join(PROJECT_DIR, "holdings")
        try:
            for f in sorted(os.listdir(hold_dir)):
                m = re.match(r"^hold_([A-Za-z0-9.]+)\.json$", f)
                if m:
                    d["holding"].append(m.group(1))
                    if len(d["holding"]) >= 2:
                        break
        except OSError:
            pass
        return d

    # ---------- A. 路由存活 ----------
    STATIC_PAGES = ["/", "/system", "/ledger", "/holdings", "/holdings/new",
                    "/research", "/reports", "/portfolio", "/alerts", "/workspace",
                    "/discuss", "/spec", "/masters", "/knowledge", "/rollover",
                    "/journal", "/market", "/sector", "/watch", "/watch/history"]

    def dim_a(self, dyn):
        if not HAS_REQUESTS:
            self.add("A", "路由存活", self.base, "skip", "requests缺失,整维跳过")
            return
        for p in self.STATIC_PAGES:
            r = self.fetch(p, timeout=20)
            self.record_page("A", "页面 %s" % p, p, r)
        h = dyn["holding"][:1]
        for t in h:
            for p in ["/holdings/%s" % t, "/holdings/%s/review" % t, "/watch/sell/%s" % t]:
                r = self.fetch(p, timeout=20)
                self.record_page("A", "页面 %s" % p, p, r)
        for t in dyn["research"]:
            for p in ["/research/%s" % quote(t, safe="")]:
                r = self.fetch(p, timeout=20)
                self.record_page("A", "页面 %s" % p, p, r)
        for t in dyn["report_shelf"]:
            p = "/reports/%s" % quote(t, safe="")
            r = self.fetch(p, timeout=20)
            self.record_page("A", "页面 %s" % p, p, r)
        for (t, rel) in dyn["report_doc"]:
            p = "/reports/%s/%s" % (quote(t, safe=""), quote(rel))
            r = self.fetch(p, timeout=25)
            self.record_page("A", "报告 %s/%s" % (t, rel), p, r, md_page=True)
        for f in dyn["discuss"]:
            p = "/discuss/%s" % quote(f)
            r = self.fetch(p, timeout=20)
            self.record_page("A", "讨论 %s" % f, p, r, md_page=True)
        for rel in dyn["knowledge"]:
            p = "/knowledge/%s" % quote(rel)
            r = self.fetch(p, timeout=20)
            self.record_page("A", "知识 %s" % rel, p, r, md_page=True)
        for mid in dyn["masters"]:
            p = "/masters/%s" % quote(mid)
            r = self.fetch(p, timeout=20)
            self.record_page("A", "列传 %s" % mid, p, r, md_page=True)
        # 404 负测(期望404=pass)
        for p in ["/holdings/NOPE123XYZ", "/reports/NOPE123XYZ",
                  "/knowledge/__not_exist__.md", "/masters/__not_exist__"]:
            r = self.fetch(p, timeout=15)
            if r["code"] == 404:
                self.add("A", "负测 %s" % p, self.base + p, "pass",
                         "期望404,实际404", ms=r["ms"])
            elif r["code"] is None:
                self.add("A", "负测 %s" % p, self.base + p, "fail", r["err"])
            else:
                self.add("A", "负测 %s" % p, self.base + p, "fail",
                         "期望404,实际HTTP %s" % r["code"], r["text"][:200], ms=r["ms"])

    def record_page(self, dim, name, path, r, md_page=False):
        url = self.base + path
        if r["code"] is None:
            self.add(dim, name, url, "fail", r["err"])
            return
        self.timings.append((name, url, r["ttfb_ms"], r["ms"]))
        if r["code"] == 200:
            self.add(dim, name, url, "pass", "HTTP 200", ms=r["ms"])
        elif r["code"] == 404:
            self.add(dim, name, url, "fail", "HTTP 404(路由/文件缺失)", r["text"][:200], ms=r["ms"])
        elif r["code"] == 500:
            self.add(dim, name, url, "fail", "HTTP 500(服务端异常)", r["text"][:200], ms=r["ms"])
        else:
            self.add(dim, name, url, "warn", "HTTP %s" % r["code"], r["text"][:200], ms=r["ms"])
        if md_page and r["code"] == 200:
            self.md_assert(url, r["text"])

    # ---------- C. MD渲染 ----------
    MD_PATTERNS = [
        (re.compile(r"^#{1,6}\s+\S", re.M), "##裸标题"),
        (re.compile(r"\*\*[^\n*]{1,80}\*\*"), "**裸加粗"),
        (re.compile(r"```"), "```围栏残留"),
        (re.compile(r"\|\s*:?-{3,}:?\s*\|"), "|表头分隔残留"),
    ]

    def md_assert(self, url, html):
        # 只看 body 文本,避开 <script>/<style> 误伤
        body = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.I)
        body = re.sub(r"<style[\s\S]*?</style>", "", body, flags=re.I)
        text_full = re.sub(r"<[^>]+>", "", body)
        # 已渲染 <table> 的剥标签文本会把 "#" 序号列拼成 "# xxx" 行,
        # 形如裸标题(误报)——标题/分隔线两项改用"去表后文本"判定;
        # **加粗/围栏不受表影响,仍用全文判定(表内残留亦属渲染缺陷)
        no_table = re.sub(r"<table[\s\S]*?</table>", "", body, flags=re.I)
        text_notab = re.sub(r"<[^>]+>", "", no_table)
        hits = []
        for pat, label, txt in [(self.MD_PATTERNS[0][0], self.MD_PATTERNS[0][1], text_notab),
                                (self.MD_PATTERNS[1][0], self.MD_PATTERNS[1][1], text_full),
                                (self.MD_PATTERNS[2][0], self.MD_PATTERNS[2][1], text_full),
                                (self.MD_PATTERNS[3][0], self.MD_PATTERNS[3][1], text_notab)]:
            t = txt.replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&")
            m = pat.search(t)
            if m:
                i = max(0, m.start() - 40)
                hits.append("%s: …%s…" % (label, t[i:m.start() + 60].replace("\n", " ")))
        if hits:
            self.add("C", "MD裸写 %s" % url.split(self.base)[-1], url,
                     "fail", "raw-markdown", " | ".join(hits)[:300])
        else:
            self.add("C", "MD渲染 %s" % url.split(self.base)[-1], url,
                     "pass", "无裸markdown残留")

    # ---------- B. API连通 ----------
    # (path模板,关键字段,慢接口标记,占位来源)
    FAST_APIS = [
        ("/api/dashboard", [], False, None),
        ("/api/market", [], False, None),
        ("/api/holdings", [], False, None),
        ("/api/holdings/{HOLD}", ["id"], False, "HOLD"),
        ("/api/research", [], False, None),
        ("/api/research/{RES}", [], False, "RES"),
        ("/api/knowledge", [], False, None),
        ("/api/knowledge/{KNOW}", ["title", "content"], False, "KNOW"),
        ("/api/company/{RES}", ["ticker"], False, "RES"),
        ("/api/system/status", ["states", "db", "env"], False, None),
        ("/api/discipline/ledger", ["thesis_rate", "review_overdue"], False, None),
        ("/api/portfolio/matrix", ["matrix", "holdings_count"], False, None),
        ("/api/portfolio/overview", ["holdings_count", "total_market_value", "opportunity_rows"], False, None),
        ("/api/spec/t0", [], False, None),
        ("/api/screen/pipeline", ["lists", "batches"], False, None),
        ("/api/data/last-update", ["last_update", "running"], False, None),
        ("/api/reports/{SHELF}", ["name", "reports"], False, "SHELF"),
        ("/api/report/{RDOC}", ["content", "title"], False, "RDOC"),
        ("/api/prompt/templates", ["layers"], False, None),
        ("/api/journal?limit=5", [], False, None),
        ("/api/watch/status", [], False, None),
        ("/api/watch/log?limit=5", ["entries"], False, None),
        ("/api/watch/history", ["active", "closed"], False, None),
        ("/api/review/{HOLD}", ["reviews", "thesis"], False, "HOLD"),
        ("/api/search?q=%E8%85%BE%E8%AE%AF", ["query", "count", "results"], False, None),
        ("/api/llm/config", ["configured"], False, None),
    ]
    SLOW_APIS = [
        ("/api/market/futu-overview", ["indices"], "RES"),
        ("/api/market/comprehensive", [], None),
        ("/api/sector/rotation", [], None),
        ("/api/sector/longterm", [], None),
        ("/api/stock-quick/{RES}", ["ticker", "price"], "RES"),
        ("/api/stock/valuation/{RES}", [], "RES"),
        ("/api/stock/profile/{RES}", [], "RES"),
        ("/api/company/{ASH}", ["ticker"], "ASH"),
        ("/api/watch/check/{HOLD}", [], "HOLD"),
        ("/api/spec/t2/{RES}", [], "RES"),
    ]
    # 只读安全 POST(纯计算/模板渲染,无落盘副作用)
    SAFE_POSTS = [
        ("/api/rollover/calculate",
         {"avg_cost": 10, "shares": 1000, "current_price": 15},
         ["total_invested", "market_value", "profit_pct", "can_recover"]),
        ("/api/prompt/generate",
         {"ticker": "0700.HK", "layer": "05-qualitative"},
         ["ticker", "layer", "prompt"]),
    ]
    # 写操作/长任务 POST:只登记跳过,不实打
    SKIPPED_POSTS = [
        "/api/holdings", "/api/holdings/{T}/buy-register",
        "/api/prompt/submit", "/api/prompt/submit-md", "/api/verify/{claim}",
        "/api/review/{T}", "/api/research-list/{T}/status", "/api/portfolio/risk",
        "/api/portfolio/budget-check", "/api/sell/execute/{T}", "/api/data/update",
        "/api/data/update/{job}", "/api/watch/daily", "/api/watch/review/{T}",
        "/api/watch/sell/{T}", "/api/llm/config", "/api/llm/test",
        "/api/stock/*", "/api/screen/pipeline(POST)",
    ]

    def dim_b(self, dyn):
        if not HAS_REQUESTS:
            self.add("B", "API连通", self.base, "skip", "requests缺失,整维跳过")
            return
        sub = {"HOLD": (dyn["holding"] + ["0700.HK"])[0] if dyn["holding"] else "0700.HK",
               "RES": (dyn["research"] + ["NVDA"])[0] if dyn["research"] else "NVDA",
               "KNOW": dyn["knowledge"][0] if dyn["knowledge"] else "discipline/双账户制.md",
               "SHELF": (dyn["report_shelf"] + ["0700.HK"])[0],
               "ASH": "600519.SH"}
        if dyn["report_doc"]:
            t, rel = dyn["report_doc"][0]
            sub["RDOC"] = "%s/%s" % (t, rel)
        else:
            sub["RDOC"] = "0700.HK/2026-07-23/07-report.md"
        for path, keys, _slow, slot in self.FAST_APIS:
            p = path.format(**{k: quote(v, safe="/") for k, v in sub.items()}) \
                if "{" in path else path
            self.check_api(p, keys, timeout=25)
        if self.quick:
            for path, _k, _s in self.SLOW_APIS:
                self.add("B", "API %s" % path, self.base + path, "skip",
                         "quick模式跳过慢接口(fengdata/fengsector系,全量模式实测)")
        else:
            for path, keys, slot in self.SLOW_APIS:
                p = path.format(**{k: quote(sub[k], safe="/") for k in [slot]}) if slot else path
                self.check_api(p, keys, timeout=150)
        for path, body, keys in self.SAFE_POSTS:
            r = self.fetch(path, timeout=30, method="POST", json_body=body)
            self.check_api_result("B POST %s" % path, path, r, keys)
        for path in self.SKIPPED_POSTS:
            self.add("B", "API %s" % path, self.base + path, "skip",
                     "POST写操作/长任务,不实打(防误写持仓/误触发卖出/长回测)")

    def check_api(self, path, keys, timeout=25):
        r = self.fetch(path, timeout=timeout)
        self.check_api_result("API %s" % path, path, r, keys)
        if r["code"] == 200 and isinstance(r["data"], dict):
            self._api_cache[path] = r["data"]

    def check_api_result(self, name, path, r, keys):
        url = self.base + path
        if r["code"] is None:
            self.add("B", name, url, "fail", r["err"])
            return
        self.timings.append((name, url, r["ttfb_ms"], r["ms"]))
        if r["code"] == 500:
            self.add("B", name, url, "fail", "HTTP 500", r["text"][:200], ms=r["ms"])
            return
        if r["code"] in (404, 400):
            self.add("B", name, url, "warn", "HTTP %d(可能无数据/参数问题)" % r["code"],
                     r["text"][:200], ms=r["ms"])
            return
        if r["code"] != 200:
            self.add("B", name, url, "warn", "HTTP %d" % r["code"], r["text"][:200], ms=r["ms"])
            return
        if not r["text"].strip():
            self.add("B", name, url, "fail", "空体(200但body为空)", ms=r["ms"])
            return
        if r["data"] is None:
            if "text/html" in (r["ctype"] or ""):
                self.add("B", name, url, "fail", "HTML误报(API返回了HTML页面,疑似路由miss)",
                         r["text"][:200], ms=r["ms"])
            else:
                self.add("B", name, url, "fail", "JSON不可解析", r["text"][:200], ms=r["ms"])
            return
        if isinstance(r["data"], dict) and "error" in r["data"] and len(r["data"]) <= 2:
            self.add("B", name, url, "warn", "业务级错误:{%s}" % r["data"].get("error", "")[:80],
                     r["text"][:200], ms=r["ms"])
            return
        missing = [k for k in keys if isinstance(r["data"], dict) and k not in r["data"]]
        if missing:
            self.add("B", name, url, "warn", "缺关键字段:%s" % ",".join(missing),
                     r["text"][:200], ms=r["ms"])
        else:
            extra = "keys=%s" % ",".join(list(r["data"].keys())[:12]) \
                if isinstance(r["data"], dict) else "list[%d]" % len(r["data"])
            self.add("B", name, url, "pass", "HTTP200+JSON可解析,%s" % extra, ms=r["ms"])

    # ---------- D. 溢出 ----------
    def _read_web_files(self):
        """[(显示名, 绝对路径, 源码)],覆盖 views/*.ejs + public/js/*.js;读失败跳过。"""
        out = []
        for d, exts in ((os.path.join(PROJECT_DIR, "fengweb", "views"), (".ejs",)),
                        (os.path.join(PROJECT_DIR, "fengweb", "public", "js"), (".js",))):
            try:
                names = sorted(os.listdir(d))
            except OSError:
                continue
            for f in names:
                if not f.endswith(tuple(exts)):
                    continue
                p = os.path.join(d, f)
                try:
                    with open(p, encoding="utf-8") as fh:
                        out.append((f, p, fh.read()))
                except OSError:
                    continue
        return out

    def check_i18n_usage(self):
        """i18n键双向对账:收集面=views/*.ejs的data-i18n + JS/EJS里T('key')/FengI18n.t('key',...)
        首参字面量;词典面=public/locales/en.json(嵌套JSON点号展平)。
        EJS插值型键(如 page.title.<%= %>)按前缀豁免,不算缺失。
        返回(缺失键列表, 未引用键列表)。fengweb/locales/ 是服务端另一套词典,有意不对账。"""
        used, dyn_prefixes = set(), set()
        for _name, _p, src in self._read_web_files():
            if _p.endswith(".js"):
                src = _strip_js_comments(src)
            for m in I18N_ATTR_RE.finditer(src):
                k = (m.group(1) if m.group(1) is not None else m.group(2) or "").strip()
                if "<%" in k:
                    prefix = k.split("<%")[0].strip()
                    if prefix:
                        dyn_prefixes.add(prefix)
                    # 表达式内的引号点号键字面量(三元/或兜底)算确定引用
                    used |= set(I18N_KEY_LIT_RE.findall(k))
                    continue  # 其余插值型:静态前缀豁免,不算缺失
                if k:
                    used.add(k)
            for m in I18N_EMPTY_KEY_RE.finditer(src):
                k = m.group(1).strip()
                if k and "<%" not in k:
                    used.add(k)
            for m in I18N_TCALL_RE.finditer(src):
                used.add(m.group(1))
            used |= _t_call_first_arg_keys(src)
            # EJS scriptlet(<% %>)内赋值的键字面量也算引用:
            # var stKey = cond ? 'holdingdetail.stValid' : ... 之后经 <%= stKey %> 消费
            for m in EJS_SCRIPTLET_RE.finditer(src):
                used |= set(I18N_KEY_LIT_RE.findall(m.group(1)))
        dict_path = os.path.join(PROJECT_DIR, "fengweb", "public", "locales", "en.json")
        try:
            with open(dict_path, encoding="utf-8") as fh:
                dict_keys = _flatten_i18n_keys(json.load(fh))
        except (OSError, ValueError):
            return [], []
        missing = []
        for k in sorted(used):
            if k in dict_keys:
                continue
            if any(k.startswith(p) for p in dyn_prefixes):
                continue
            missing.append(k)
        # 动态前缀池覆盖的词典键(如 masters.school.<%= m.school %> 的候选键)
        # 无法静态判定引用与否,从未引用清单剔除(其"缺失"也不会误报)
        unreferenced = sorted(
            k for k in (dict_keys - used)
            if not any(k.startswith(p) for p in dyn_prefixes))
        return missing, unreferenced

    def check_ejs_locals(self):
        """EJS未定义变量静态检查:逐视图提取 <%= / <%- 顶层标识符,对照 server.ts
        res.render('视图名', {...}) 传入的 locals 顶层键 + 通用白名单。
        返回 (视图名, 变量名) 列表。脚本片段 <% %> 内声明的变量视为已定义。"""
        # 1) 找 render 调用所在文件(默认 server.ts,grep 失败回退)
        server_files = [os.path.join(PROJECT_DIR, "fengweb", "src", "server.ts")]
        src_dir = os.path.join(PROJECT_DIR, "fengweb", "src")
        try:
            for root, _dirs, files in os.walk(src_dir):
                for f in files:
                    if f.endswith(".ts"):
                        p = os.path.join(root, f)
                        if p not in server_files:
                            server_files.append(p)
        except OSError:
            pass
        render_code = ""
        for p in server_files:
            try:
                with open(p, encoding="utf-8") as fh:
                    render_code += fh.read() + "\n"
            except OSError:
                continue
        locals_by_view = {}
        for m in re.finditer(
                r"res\s*\.\s*render\s*\(\s*[\"'`]([\w\-]+)[\"'`]\s*,", render_code):
            brace = render_code.find("{", m.end())
            if brace < 0 or render_code[m.end():brace].strip():
                continue  # 第二参不是紧随的对象字面量,跳过
            block = _balanced_braces(render_code, brace)
            if block:
                locals_by_view.setdefault(m.group(1), set()).update(
                    _obj_literal_keys(block))
        # 2) 逐视图收集:脚本片段声明 + emit 顶层标识符
        results = []
        views_dir = os.path.join(PROJECT_DIR, "fengweb", "views")
        try:
            ejs_files = sorted(f for f in os.listdir(views_dir) if f.endswith(".ejs"))
        except OSError:
            ejs_files = []
        for f in ejs_files:
            try:
                with open(os.path.join(views_dir, f), encoding="utf-8") as fh:
                    src = fh.read()
            except OSError:
                continue
            declared = set()
            for m in EJS_SCRIPTLET_RE.finditer(src):
                declared.update(EJS_IDENT_RE.findall(m.group(1)))
            for m in re.finditer(r"\bvar\s+([A-Za-z_$][\w$]*)", src):
                declared.add(m.group(1))
            used_top = set()
            for m in EJS_EMIT_RE.finditer(src):
                expr = m.group(1)
                used_top |= _ejs_top_idents(expr)
                # emit 表达式内的函数参数也是已声明(reduce/forEach 回调等)
                for pm in re.finditer(r"\bfunction\b[^()]*\(([^()]*)\)", expr):
                    for p in pm.group(1).split(","):
                        p = p.strip()
                        if re.fullmatch(r"[A-Za-z_$][\w$]*", p or ""):
                            declared.add(p)
                for pm in re.finditer(r"\(([^()]*)\)\s*=>", expr):
                    for p in pm.group(1).split(","):
                        p = p.strip()
                        if re.fullmatch(r"[A-Za-z_$][\w$]*", p or ""):
                            declared.add(p)
                for pm in re.finditer(r"[=(\[{,\s:?&!]([A-Za-z_$][\w$]*)\s*=>", expr):
                    declared.add(pm.group(1))
            used_top -= (declared | EJS_KW_GLOBALS | EJS_COMMON_LOCALS)
            view_key = f[:-4]
            passed = locals_by_view.get(view_key)
            if passed is None:
                continue  # 找不到对应 render 调用(布局/动态include),不误报
            for v in sorted(used_top - passed):
                results.append((f, v))
        return results

    def dim_d(self):
        views_dir = os.path.join(PROJECT_DIR, "fengweb", "views")
        issues = []
        try:
            files = [f for f in os.listdir(views_dir) if f.endswith(".ejs")]
        except OSError:
            files = []
        for f in files:
            try:
                with open(os.path.join(views_dir, f), encoding="utf-8") as fh:
                    src = fh.read()
            except OSError:
                continue
            if "<table" in src and "overflow" not in src:
                issues.append((f, "table无滚动容器"))
            for m in re.finditer(r"(?:width|min-width)\s*:\s*(\d+)px", src):
                if int(m.group(1)) >= 320:
                    issues.append((f, "固定px宽 %s" % m.group(0)))
                    break
            if re.search(r"display\s*:\s*grid", src) and "@media" not in src:
                issues.append((f, "内联grid覆盖响应式(无@media兜底)"))
            if "display:flex" in src.replace(" ", "") and "min-width:0" not in src.replace(" ", ""):
                issues.append((f, "flex子项缺min-width:0(长串可撑破)"))
            for _hit in adjacent_btn_gap_hits(src):
                issues.append((f, "相邻btn无gap容器(换行粘连)"))
                break
            for hit in bare_link_hits(src):
                issues.append((f, "裸下划线链接须按钮化: %s" % hit))
        css_path = os.path.join(PROJECT_DIR, "fengweb", "public", "css", "style.css")
        try:
            with open(css_path, encoding="utf-8") as fh:
                css = fh.read()
            for m in re.finditer(r"(?:width|min-width)\s*:\s*(\d+)px", css):
                if int(m.group(1)) >= 600:
                    issues.append(("style.css", "固定px宽 %s" % m.group(0)))
                    break
        except OSError:
            pass
        # i18n 键双向对账(public/locales/en.json 客户端词典;服务端 fengweb/locales 另一套,不对账)
        try:
            missing, unreferenced = self.check_i18n_usage()
            ev = "词典面en.json,引用面views+js;缺失%d键,未引用%d键" % (
                len(missing), len(unreferenced))
            if missing:
                ev += ";缺失:%s" % ",".join(missing[:10])
            if unreferenced:
                ev += ";未引用:%s" % ",".join(unreferenced[:10])
            self.add("D", "i18n对账", os.path.join(PROJECT_DIR, "fengweb", "public",
                     "locales", "en.json"), "warn" if missing else "pass", ev[:300])
        except Exception as e:
            self.add("D", "i18n对账", self.base, "warn", "i18n检查异常:%s" % str(e)[:120])
        # EJS 未定义变量静态检查(对照 server.ts render locals)
        try:
            ejs_issues = self.check_ejs_locals()
            if ejs_issues:
                self.add("D", "EJS未定义变量", views_dir, "warn", "共%d处:%s" % (
                    len(ejs_issues), "; ".join(
                        "%s:EJS变量%s未在render locals中" % (f, v)
                        for f, v in ejs_issues[:10])))
            else:
                self.add("D", "EJS未定义变量", views_dir, "pass",
                         "全部视图emit标识符均在render locals/白名单/scriptlet声明内")
        except Exception as e:
            self.add("D", "EJS未定义变量", views_dir, "warn", "EJS检查异常:%s" % str(e)[:120])
        browser_done = False
        if HAS_PW and self.server_up:
            try:
                browser_done = self.dim_d_browser()
            except Exception as e:
                self.add("D", "浏览器真测", self.base, "warn",
                         "playwright启动失败,降级为静态:%s" % str(e)[:120])
        if not browser_done:
            note = "静态检查" + ("(本机无playwright/chromium,已降级)" if not HAS_PW else
                               "(浏览器不可用,已降级)" if self.server_up else "(服务未启动,已降级)")
            if issues:
                shown = "; ".join("%s:%s" % (f, w) for f, w in issues[:15])
                self.add("D", "溢出静态检查", self.base, "warn",
                         "%s,共%d处:%s" % (note, len(issues), shown))
            else:
                self.add("D", "溢出静态检查", self.base, "pass", "%s,0处可疑" % note)

    def dim_d_browser(self):
        """双视口真测,有异常直接抛给调用方降级。返回True=实测完成。"""
        targets = ["/", "/holdings", "/research", "/reports", "/portfolio", "/market"]
        bad = []
        with sync_playwright() as pw:
            br = pw.chromium.launch(args=["--no-sandbox"])
            for vw in (390, 1440):
                pg = br.new_page(viewport={"width": vw, "height": 900})
                for t in targets:
                    try:
                        pg.goto(self.base + t, timeout=30000, wait_until="networkidle")
                        over = pg.evaluate(
                            "() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
                        if over > 1:
                            bad.append("%s@%dpx溢出%dpx" % (t, vw, over))
                    except Exception as e:
                        bad.append("%s@%dpx加载失败:%s" % (t, vw, str(e)[:80]))
                pg.close()
            br.close()
        if bad:
            self.add("D", "浏览器双视口真测", self.base, "fail",
                     "390/1440真测%d处:%s" % (len(bad), "; ".join(bad)[:280]))
        else:
            self.add("D", "浏览器双视口真测", self.base, "pass",
                     "390/1440六核心页均无横向溢出")
        return True

    # ---------- E. 数据新鲜度(只读) ----------
    def dim_e(self):
        today = datetime.date.today().isoformat()
        db_path = os.path.join(PROJECT_DIR, "data", "market_data.db")
        if not os.path.exists(db_path):
            self.add("E", "market_data.db", db_path, "fail", "库文件不存在")
        else:
            try:
                con = sqlite3.connect("file:%s?mode=ro" % db_path.replace("\\", "/"), uri=True)
                checks = [("daily_data", "date"), ("dividends", "ex_date"),
                          ("fundamentals", "updated_at"), ("update_log", "last_date")]
                for t, col in checks:
                    try:
                        mx = con.execute("SELECT MAX([%s]) FROM [%s]" % (col, t)).fetchone()[0]
                    except Exception as e:
                        self.add("E", "表 %s" % t, db_path, "warn", "查询失败:%s" % str(e)[:100])
                        continue
                    mx_s = str(mx)[:10] if mx else "空"
                    if not mx:
                        self.add("E", "表 %s.MAX(%s)" % (t, col), db_path, "warn", "表空")
                    else:
                        try:
                            age = (datetime.date.today() -
                                   datetime.date.fromisoformat(mx_s)).days
                        except ValueError:
                            age = None
                        # dividends 为事件表：新记录只在除息日产生，>1天告警无意义，改用 90 天事件窗口
                        limit = 90 if t == "dividends" else 1
                        if age is not None and age > limit:
                            self.add("E", "表 %s.MAX(%s)" % (t, col), db_path, "warn",
                                     "MAX=%s,今天=%s,滞后%d天(>%d天告警)" % (mx_s, today, age, limit))
                        else:
                            self.add("E", "表 %s.MAX(%s)" % (t, col), db_path, "pass",
                                     "MAX=%s" % mx_s)
                # cn_financials:declare_date多为空,改报行数+最大accper
                try:
                    n = con.execute("SELECT COUNT(*) FROM [cn_financials]").fetchone()[0]
                    acc = con.execute("SELECT MAX([accper]) FROM [cn_financials]").fetchone()[0]
                    self.add("E", "表 cn_financials", db_path, "pass" if n else "warn",
                             "行数=%s,MAX(accper)=%s(declare_date’多为空,改看accper)" % (n, acc))
                except Exception as e:
                    self.add("E", "表 cn_financials", db_path, "warn", "查询失败:%s" % str(e)[:100])
                con.close()
            except Exception as e:
                self.add("E", "market_data.db", db_path, "fail", "只读打开失败:%s" % str(e)[:150])
        fx_path = os.path.join(PROJECT_DIR, "data", "cache", "fx_latest.json")
        try:
            with open(fx_path, encoding="utf-8") as fh:
                fx = json.load(fh)
            d = fx.get("date", "")
            try:
                age = (datetime.date.today() - datetime.date.fromisoformat(d)).days \
                    if d else 999
            except ValueError:
                age = 999
            self.add("E", "fx_latest.json", fx_path,
                     "warn" if age > 1 else "pass",
                     "date=%s%s" % (d, ",滞后%d天(>24h告警)" % age if age > 1 else ""))
        except (OSError, ValueError) as e:
            self.add("E", "fx_latest.json", fx_path, "fail", "读取失败:%s" % str(e)[:120])
        lu_path = os.path.join(PROJECT_DIR, "data", "cache", "last_update.json")
        try:
            with open(lu_path, encoding="utf-8") as fh:
                lu = json.load(fh)
            fin = lu.get("finished_at", "")
            st = lu.get("status", "")
            try:
                fdt = datetime.datetime.fromisoformat(fin.replace("Z", "+00:00"))
                ageh = (datetime.datetime.now(datetime.timezone.utc) - fdt).total_seconds() / 3600
                detail = "status=%s,finished=%s,%.1fh前" % (st, fin, ageh)
                self.add("E", "last_update.json", lu_path,
                         "warn" if (ageh > 24 or st == "failed") else "pass", detail)
            except ValueError:
                self.add("E", "last_update.json", lu_path, "warn",
                         "status=%s,finished_at不可解析:%s" % (st, fin))
        except (OSError, ValueError) as e:
            self.add("E", "last_update.json", lu_path, "fail", "读取失败:%s" % str(e)[:120])

    # ---------- F. 前后端字段贴合 ----------
    META_IGNORED = {"_source", "_date", "_stale", "_age_hours", "generated_at",
                    "fetched_at", "success", "raw", "message"}
    EXPECTED = {
        "/api/portfolio/overview": ["holdings_count", "total_market_value", "opportunity_rows"],
        "/api/portfolio/matrix": ["matrix", "holdings_count"],
        "/api/discipline/ledger": ["thesis_rate", "review_overdue", "states_abandoned"],
        "/api/system/status": ["states", "db", "env"],
        "/api/watch/history": ["active", "closed"],
        "/api/screen/pipeline": ["lists", "batches"],
        "/api/search": ["query", "count", "results"],
    }

    def frontend_fields(self):
        fields = set()
        for root in (os.path.join(PROJECT_DIR, "fengweb", "views"),
                     os.path.join(PROJECT_DIR, "fengweb", "public", "js")):
            try:
                files = os.listdir(root)
            except OSError:
                continue
            for f in files:
                if not (f.endswith(".ejs") or f.endswith(".js")):
                    continue
                try:
                    with open(os.path.join(root, f), encoding="utf-8") as fh:
                        src = fh.read()
                except OSError:
                    continue
                for m in re.finditer(
                        r"(?:data|d|res|result|json|item|row|h|j|out|payload)\.([A-Za-z_][A-Za-z0-9_]*)", src):
                    fields.add(m.group(1))
        return fields

    def dim_f(self):
        if not self._api_cache:
            self.add("F", "字段贴合", self.base, "skip", "B维无可用JSON缓存(服务未起或全失败)")
            return
        consumed = self.frontend_fields()
        for path, data in sorted(self._api_cache.items()):
            if not isinstance(data, dict):
                continue
            base_path = path.split("?")[0]
            exp = None
            for k in self.EXPECTED:
                if base_path == k or base_path.startswith(k + "/"):
                    exp = self.EXPECTED[k]
                    break
            missing = [k for k in (exp or []) if k not in data]
            extra = [k for k in data.keys()
                     if k not in consumed and k not in self.META_IGNORED and k not in (exp or [])]
            if missing:
                self.add("F", "字段 %s" % path, self.base + path, "warn",
                         "前端要但API缺:%s" % ",".join(missing),
                         "多余:%s" % ",".join(extra[:10]) if extra else "")
            else:
                self.add("F", "字段 %s" % path, self.base + path, "pass",
                         "期望字段齐%s" % (";前端未消费的多余:" + ",".join(extra[:10]) if extra else ""))

    # ---------- G. 控制台错误 ----------
    def dim_g(self):
        if not HAS_PW or not self.server_up:
            self.add("G", "控制台错误", self.base, "skip",
                     "无浏览器(%s)/服务未起,跳过并注明" % ("有playwright" if HAS_PW else "无playwright"))
            return
        try:
            errs = []
            with sync_playwright() as pw:
                br = pw.chromium.launch(args=["--no-sandbox"])
                pg = br.new_page()
                pg.on("console", lambda m: errs.append("[console.%s] %s %s" % (
                    m.type, pg.url, m.text[:150])) if m.type == "error" else None)
                pg.on("pageerror", lambda e: errs.append("[pageerror] %s %s" % (pg.url, str(e)[:150])))
                for t in ["/", "/holdings", "/research", "/portfolio", "/market"]:
                    try:
                        pg.goto(self.base + t, timeout=30000, wait_until="networkidle")
                    except Exception as e:
                        errs.append("[load] %s %s" % (t, str(e)[:100]))
                br.close()
            if errs:
                self.add("G", "控制台错误", self.base, "warn",
                         "共%d条" % len(errs), "; ".join(errs[:5])[:300])
            else:
                self.add("G", "控制台错误", self.base, "pass", "五核心页零console.error/零pageerror")
        except Exception as e:
            self.add("G", "控制台错误", self.base, "skip", "浏览器启动失败,跳过:%s" % str(e)[:120])

    # ---------- H. 性能冒烟 ----------
    def dim_h(self):
        if not self.timings:
            self.add("H", "性能冒烟", self.base, "skip", "无计时样本")
            return
        # warmup 重测：首日冷缓存/瞬时 CPU 争抢的单点慢不代表稳态性能——
        # 超 3s 的样本重测一次取最小；持续慢（重测仍 >3s）照样落 warn。
        retested = []
        for (n, u, t, m) in self.timings:
            if m and m > 3000:
                r = self.fetch(u.replace(self.base, "", 1), timeout=30)
                if r["ms"] and r["ms"] < m:
                    m, n = r["ms"], n + "(重测)"
            retested.append((n, u, t, m))
        slow = [(n, u, m) for n, u, t, m in retested if m and m > 3000]
        worst = sorted(retested, key=lambda x: x[3] or 0, reverse=True)[:5]
        detail = "样本%d,最慢:%s" % (len(retested), "; ".join(
            "%s %dms" % (n[:24], m) for n, u, t, m in worst))
        if slow:
            self.add("H", "性能冒烟", self.base, "warn",
                     "超3s共%d页:%s。%s" % (len(slow), "; ".join(
                         "%s %dms" % (n[:24], m) for n, u, m in slow[:8])[:200], detail))
        else:
            self.add("H", "性能冒烟", self.base, "pass", detail)

    # ---------- I. 无声降级静态检查（fail-loud 审计提案，2026-09-13 董事长点头） ----------
    # 判据（docs/FAIL-LOUD-AUDIT.md 三条件之静态可查部分）：
    #   ① 前端 .ts/.js（去 vendor）空 .catch(() => {}) / catch {} —— 零容忍
    #   ② tools/*.py 宽异常无标注静默吞：except Exception[ as e]: 且体只有
    #      pass/continue/return None/{}/[]，邻近行无 # 注释、体内无声——
    #      按存量基线管理，超过 FAIL_LOUD_BASELINE 才 warn（旧账治理渐进，新账当场可见）
    # 基线 36 = 2026-09-13 I维首跑存量（含 fengrule/fengdata 等"链尾有声"合规样板的
    # 行级无标注接力——审计已定音不动它们）。此数只准降不准升：升=新增无声点，当场 warn。
    FAIL_LOUD_BASELINE = 36

    def dim_i(self):
        import re as _re
        rx_js = _re.compile(
            r"\.catch\(\s*(?:\(\s*\)|[A-Za-z_$]\w*)\s*=>\s*\{\s*\}\s*\)"
            r"|catch\s*(?:\([^)]*\))?\s*\{\s*\}")
        rx_ex = _re.compile(r"^(\s*)except\s+(?:Exception|BaseException)\s*(?:as\s+\w+)?\s*:\s*(\S.*)?$")
        rx_body_silent = _re.compile(r"^(pass|continue|break|return (None|\{\}|\[\])?)\s*(#.*)?$")
        hits_js, hits_py = [], []
        for d in (os.path.join(PROJECT_DIR, "fengweb", "src"),
                  os.path.join(PROJECT_DIR, "fengweb", "public", "js")):
            for root, dirs, fs in os.walk(d):
                dirs[:] = [x for x in dirs if x not in ("node_modules", "dist", "vendor")]
                for f in fs:
                    if not f.endswith((".ts", ".js")):
                        continue
                    p = os.path.join(root, f)
                    try:
                        txt = open(p, encoding="utf-8", errors="replace").read()
                    except OSError:
                        continue
                    for m in rx_js.finditer(txt):
                        ln = txt[:m.start()].count("\n") + 1
                        hits_js.append("%s:%d" % (os.path.relpath(p, PROJECT_DIR), ln))
        td = os.path.join(PROJECT_DIR, "tools")
        for f in sorted(os.listdir(td)):
            if not f.endswith(".py"):
                continue
            p = os.path.join(td, f)
            try:
                lines = open(p, encoding="utf-8", errors="replace").read().splitlines()
            except OSError:
                continue
            for i, ln in enumerate(lines):
                m = rx_ex.match(ln)
                if not m or (m.group(2) or "").strip():  # 同行带注释视为已标注
                    continue
                indent = len(m.group(1))
                body = []
                j = i + 1
                while j < len(lines):
                    s = lines[j]
                    if not s.strip():
                        j += 1
                        continue
                    if len(s) - len(s.lstrip()) <= indent:
                        break
                    body.append(s.strip())
                    j += 1
                if not body or not all(rx_body_silent.match(b) for b in body):
                    continue
                if any(k in " ".join(body) for k in ("stderr", "print", "logging", "logger")):
                    continue
                ctx = "\n".join(lines[max(0, i - 2):min(len(lines), j + 1)])
                if "#" in ctx:  # 邻近有注释（回退/降级/不影响…）不报
                    continue
                hits_py.append("%s.py:%d" % (f[:-3], i + 1))
        over_py = len(hits_py) - self.FAIL_LOUD_BASELINE
        problems = []
        if hits_js:
            problems.append("前端空catch %d处:%s" % (len(hits_js), "; ".join(hits_js[:8])))
        if over_py > 0:
            problems.append("tools无标注吞错新增%d处(存量%d/基线%d):%s"
                            % (over_py, len(hits_py), self.FAIL_LOUD_BASELINE,
                               "; ".join([h for h in hits_py][:8])))
        if problems:
            self.add("I", "无声降级静态检查", "fengweb+tools", "warn",
                     ("；".join(problems))[:400])
        else:
            self.add("I", "无声降级静态检查", "fengweb+tools", "pass",
                     "前端零空catch；tools无标注吞错%d处≤基线%d（存量渐进治理，新账当场可见）"
                     % (len(hits_py), self.FAIL_LOUD_BASELINE))


def main():
    ap = argparse.ArgumentParser(description="FengInvest 全站体检")
    ap.add_argument("--base", default="http://localhost:23456")
    ap.add_argument("--quick", action="store_true", help="只跑A+B+C")
    ap.add_argument("--no-color", action="store_true")
    a = ap.parse_args()
    enable_color(a.no_color)

    if not HAS_REQUESTS:
        print("WARN: requests缺失,HTTP实测全部降级为skip; pip install requests 后重跑")

    ck = Checker(a.base, a.quick)
    ck.check_server()
    if not ck.server_up:
        ck.add("A", "服务存活", a.base, "fail", "根路由不可达,服务可能未启动")
    dyn = ck.discover()

    ck.dim_a(dyn)
    ck.dim_b(dyn)
    # C由A内md_assert产出;无MD页时补一条
    if not [i for i in ck.items if i["dim"] == "C"]:
        ck.add("C", "MD渲染", a.base, "skip", "本轮无MD阅读器页面样本")
    if not a.quick:
        ck.dim_d()
        ck.dim_e()
        ck.dim_f()
        ck.dim_g()
        ck.dim_h()
    else:
        # H免费(复用A/B计时)
        ck.dim_h()
    ck.dim_i()  # 纯静态扫描，quick 也跑（无声降级增量当场可见）

    os.makedirs(REPORTS_DIR, exist_ok=True)
    now = datetime.datetime.now()
    stamp = now.strftime("%Y-%m-%d_%H%M")
    out_path = os.path.join(REPORTS_DIR, "webcheck_%s.json" % stamp)
    counts = {"pass": 0, "warn": 0, "fail": 0, "skip": 0}
    for i in ck.items:
        counts[i["status"]] += 1
    report = {"base": a.base, "quick": a.quick, "at": now.isoformat(timespec="seconds"),
              "counts": counts, "dyn_samples": {k: (v if k != "report_doc" else
                ["%s/%s" % (t, r) for t, r in v]) for k, v in dyn.items()},
              "items": ck.items}
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)

    # 终端彩色表
    color = {"pass": GREEN, "warn": YELLOW, "fail": RED, "skip": DIM}
    cur = None
    for i in ck.items:
        if i["dim"] != cur:
            cur = i["dim"]
            print("\n%s[%s]%s" % (CYAN, cur, RESET))
        mark = {"pass": "PASS", "warn": "WARN", "fail": "FAIL", "skip": "SKIP"}[i["status"]]
        ms = " %dms" % i["ms"] if i["ms"] else ""
        print("  %s%-4s%s %-42s %s%s" % (color[i["status"]], mark, RESET,
                                        i["name"][:42], i["evidence"][:90], ms))
        if i["status"] == "fail" and i["snippet"]:
            print("        %s%s%s" % (DIM, i["snippet"][:160], RESET))
    print("\n%s合计 pass=%d warn=%d fail=%d skip=%d%s" % (
        CYAN, counts["pass"], counts["warn"], counts["fail"], counts["skip"], RESET))
    print("落盘 %s" % out_path)
    sys.exit(1 if counts["fail"] > 0 else 0)


if __name__ == "__main__":
    main()
