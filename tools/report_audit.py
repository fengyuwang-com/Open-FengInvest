#!/usr/bin/env python3
# Source: ai-berkshire (https://github.com/xbtlin/ai-berkshire)
# Commit: bf21649 | License: MIT | (c) 2026 xbtlin
# Adapted for FengInvest project structure.
# -----------------------------------------------------------
"""Report Audit Tool for AI Berkshire.

数据抽检工具：从研究报告中抽取15%的财务数据点，与可靠信源比对，
通过则准出，不通过则打回并说明原因。

Zero external dependencies — uses only Python stdlib.
Requires Python >= 3.7.

工作流程（三步）：
  Step 1 — 提取数据点，随机抽样15%：
    python3 tools/report_audit.py extract --report reports/xxx.md

  Step 2 — Claude 对抽检清单中的每个数据点，从可靠信源（macrotrends/
            stockanalysis/aastocks/eastmoney）取数，填入 fetched_value

  Step 3 — 输入核验结果，输出准出/打回判决：
    python3 tools/report_audit.py verdict --results '[...]'

  一步完成（仅提取+打印抽检清单，不做网络验证）：
    python3 tools/report_audit.py extract --report reports/xxx.md --dry-run

报告质量三件套（--report 支持文件或目录，目录 → 逐个 .md 文件）：
  check      结构校验（必填章节/关键字段/章节最少条目数）：
    python3 tools/report_audit.py check --report reports/xxx.md \
      --required "第一章" --required "投资结论" \
      --min-items 5 --section "持股名单"

  sources    来源标注检查（含数字/断言但无 URL 或「来源：」的段落 + 整节无来源）：
    python3 tools/report_audit.py sources --report reports/xxx.md --require-per-section

  csvdetect  CSV 乱入检测（表列数错位/未加引号逗号数字/裸 CSV 文本块）：
    python3 tools/report_audit.py csvdetect --report reports/xxx.md
"""

import argparse
import json
import math
import os
import re
import sys
from decimal import Decimal, Context, ROUND_HALF_EVEN
from random import Random

_CTX = Context(prec=28, rounding=ROUND_HALF_EVEN)

# ---------------------------------------------------------------------------
# 数据点提取：从 Markdown 报告中识别财务数字
# ---------------------------------------------------------------------------

# 匹配模式：数字 + 单位，前面有上下文标签
# 例：收入：1,239亿元、PE 18.8x、毛利率 56%、市值 ~$5,670亿
_PATTERNS = [
    # 百分比
    (r'([\d,，\.]+)\s*%',                        '%',    'percent'),
    # 亿元/亿美元/亿港元
    (r'([\d,，\.]+)\s*亿(元|美元|港元|RMB|USD|HKD)?', '亿',    'hundred_million'),
    # 倍数 PE/PB/PS
    (r'([\d,，\.]+)\s*[xX倍]',                   'x',    'multiple'),
    # 万亿
    (r'([\d,，\.]+)\s*万亿',                      '万亿', 'trillion'),
    # 美元绝对值（B/T）
    (r'\$\s*([\d,，\.]+)\s*([BMT亿])',             '$',    'usd_abs'),
    # 纯整数（如市值、收入、用户数等，出现在表格 | 里）
    (r'\|\s*[~约]?\$?([\d,，\.]+)\s*\|',          '',     'table_num'),
]

_LABEL_RE = re.compile(
    r'(?P<label>[^\|\n：:]{2,25})[：:\s]+[~约]?\$?(?P<num>[\d,，\.]+)\s*(?P<unit>亿[元美港]?元?|万亿|[xX倍]|%|[BMT])?'
)

_TABLE_ROW_RE = re.compile(
    r'\|\s*(?P<label>[^|]{1,40})\s*\|\s*[~约]?\$?(?P<num>[\d,，\.]+)\s*(?P<unit>亿[元美港]?元?|万亿|[xX倍]|%|[BMT])?\s*\|'
)


def _clean_num(s: str) -> float:
    """把带逗号、中文逗号的数字字符串转为 float。"""
    s = s.replace(',', '').replace('，', '').strip()
    try:
        return float(s)
    except ValueError:
        return None


def _is_valid_label(label: str) -> bool:
    """判断标签是否是有意义的财务字段名，过滤噪声。"""
    label = label.strip()
    # 太短
    if len(label) < 2:
        return False
    # 纯数字或纯年份
    if re.fullmatch(r'[\d\s年季度Q]+', label):
        return False
    # 以符号/markdown标记开头
    if re.match(r'^[+\-\*#\|~/$>_`]', label):
        return False
    # 含有 markdown 粗体/代码标记
    if '**' in label or '`' in label or '__' in label:
        return False
    # 标签含有纯增速符号（如 +56%、-13% 单独作标签）
    if re.fullmatch(r'[+\-]?\d+(\.\d+)?%', label):
        return False
    # 常见无意义标签
    _SKIP = {'来源', 'sources', 'source', '说明', '注意', '备注', '数据来源',
             'n/a', '—', '-', '/', '合计', 'total', '单位', '趋势'}
    if label.lower() in _SKIP:
        return False
    return True


# 两列表格行：| 标签 | 数值 unit |（专为财务报告的 KV 表设计）
_KV_TABLE_RE = re.compile(
    r'^\|\s*(?P<label>[^|*\n]{2,40}?)\s*\|\s*[~约]?\$?(?P<num>-?[\d,，\.]+)\s*'
    r'(?P<unit>亿[元美港]?元?|万亿|[xX倍]|%|[BMT亿])?\s*[\|（\(]'
)

# 带标签的 KV 行：标签：数值 单位
_KV_LABEL_RE = re.compile(
    r'(?P<label>[\u4e00-\u9fa5A-Za-z][^\|\n：:*]{1,30})[：:]\s*[~约]?\$?'
    r'(?P<num>-?[\d,，\.]+)\s*(?P<unit>亿[元美港]?元?|万亿|[xX倍]|%|[BMT])?'
)

# 文件名/日期/URL 噪声 token：表格「来源」列、正文引用串里的 02-market.json、
# dividendhistory.org、2026-06-30、05-qualitative 这类字符串不是财务数据点，
# 抽数字前先剔除，防止 "02-market.json" 被抽成 Beta=2.00（2026-09-13 LVHI 复盘修复）。
# 注意不含 `\d+[.]\d` 之类，避免误伤 "19.79" 等正常小数。
_NOISE_TOKEN_RE = re.compile(
    r'https?://\S+'                                                        # URL
    r'|[\w\-./]*\.(?:json|jsonl|md|markdown|csv|tsv|pdf|html?|txt|py|ipynb|ya?ml|log|xlsx?|docx?)\b'  # 文件名
    r'|\b[\w\-]+\.(?:com|org|net|io|cn|gov|edu|info|co|me|tv|xyz|dev|app|wiki|news)(?:\.[a-z]{2,3})?(?:/\S*)?\b'  # 域名
    r'|\b\d{4}[-/]\d{1,2}(?:[-/]\d{1,2})?\b'                               # 日期 2016-07-27 / 2026-06
    r'|\b\d+-(?=[A-Za-z])[\w\-]+',                                         # 数字前缀标识 02-market
    re.IGNORECASE,
)


def _strip_noise(text: str) -> str:
    """剔除文件名/日期/URL 等噪声 token（用空格占位，不粘连剩余内容）。"""
    return _NOISE_TOKEN_RE.sub(' ', text)


def _parse_md_tables(lines: list) -> list:
    """解析 Markdown 中所有表格，返回 (row_label, col_header, value, unit, lineno, raw) 列表。"""
    results = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # 检测表头行（含 | 且不是分隔行）
        if '|' in line and not re.match(r'^\|[\-\s\|:]+\|$', line):
            headers_raw = [h.strip().strip('*_').strip() for h in line.split('|')]
            headers_raw = [h for h in headers_raw if h]
            # 下一行应是分隔行
            if i + 1 < len(lines) and re.match(r'^\|[\-\s\|:]+\|$', lines[i+1].strip()):
                i += 2  # 跳过分隔行
                # 读数据行
                while i < len(lines):
                    dline = lines[i].strip()
                    if not dline or not dline.startswith('|'):
                        break
                    cells = [c.strip().strip('*_~').strip() for c in dline.split('|')]
                    cells = [c for c in cells if c != '']
                    if len(cells) < 2:
                        i += 1
                        continue
                    row_label = cells[0]
                    for col_idx, cell in enumerate(cells[1:], start=1):
                        col_header = headers_raw[col_idx] if col_idx < len(headers_raw) else f'列{col_idx}'
                        # 提取 cell 中的数字+单位（含负号，2026-08-16 修复：原正则漏 - 导致 -1.28 → 1.28）
                        # 先剔除文件名/日期/URL 噪声 token，防止来源列 "02-market.json" 抽出假数字
                        m = re.search(
                            r'[~约]?\$?(-?[\d,，\.]+)\s*(亿[元美港]?元?|万亿|[xX倍]|%|[BMT])?',
                            _strip_noise(cell)
                        )
                        if m:
                            val = _clean_num(m.group(1))
                            unit = (m.group(2) or '').strip()
                            if val and val != 0 and val < 1e15:
                                results.append((row_label, col_header, val, unit, i + 1, dline))
                    i += 1
                continue
        i += 1
    return results


def extract_data_points(md_text: str) -> list:
    """从 Markdown 报告中提取所有可识别的财务数据点。

    覆盖三类结构：
      1. 多列 Markdown 表格（最主要的来源）：(行标签 + 列标题) → 数值
      2. 带冒号的 KV 行：标签：数值 单位
      3. 加粗数字行：**数值** 单位

    返回 list of dict：
      {id, label, reported_value, unit, raw_text, line_number}
    """
    points = []
    seen = set()

    def _add(label, val, unit, lineno, raw):
        label = re.sub(r'[\*_`]+', '', label).strip()
        if not _is_valid_label(label):
            return
        if val is None or val == 0 or val > 1e15:
            return
        # 过滤纯年份/季度
        if re.fullmatch(r'(20\d{2}|Q[1-4]|\d{4}\s*Q[1-4])', label.strip()):
            return
        key = f"{label}|{round(val,4)}|{unit}"
        if key in seen:
            return
        seen.add(key)
        points.append({
            'id': len(points) + 1,
            'label': label,
            'reported_value': val,
            'unit': unit,
            'raw_text': raw[:120],
            'line_number': lineno,
        })

    lines = md_text.split('\n')
    in_code = False

    # --- 1. 多列表格 ---
    for row_label, col_header, val, unit, lineno, raw in _parse_md_tables(lines):
        # 跳过无意义行标签
        if not _is_valid_label(row_label):
            continue
        # 跳过无意义列标题（YoY增速列单独标注，不作为待核验数据；来源列整列跳过，2026-09-13 LVHI 复盘）
        if col_header.upper() in ('YOY', 'YOY增速', '增速', '同比', '变化', '趋势', '说明', '备注') \
                or col_header.strip().lower() in ('来源', '出处', '数据源', 'source', 'sources'):
            continue
        # label = "行标签 · 列标题"（若列标题是行标签的补充）
        if col_header and col_header != row_label:
            label = f"{row_label} · {col_header}"
        else:
            label = row_label
        _add(label, val, unit, lineno, raw)

    # --- 2. KV 冒号行 ---
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith('```'):
            in_code = not in_code
            continue
        if in_code or stripped.startswith('> ') or re.match(r'^#{1,6}\s', stripped):
            continue
        if '|' in stripped:
            continue  # 表格已在上面处理

        for m in _KV_LABEL_RE.finditer(_strip_noise(stripped)):
            label = m.group('label')
            val = _clean_num(m.group('num'))
            unit = (m.group('unit') or '').strip()
            _add(label, val, unit, lineno, stripped)

    return points


def sample_points(points: list, ratio: float = 0.15, seed: int = None) -> list:
    """随机抽取 ratio 比例的数据点，最少 3 个，最多 30 个。"""
    n = max(3, min(30, math.ceil(len(points) * ratio)))
    n = min(n, len(points))
    rng = Random(seed)
    sampled = rng.sample(points, n)
    # 按行号排序，方便人工比对
    return sorted(sampled, key=lambda p: p['line_number'])


# ---------------------------------------------------------------------------
# 准出/打回判决
# ---------------------------------------------------------------------------

_TOLERANCE = 0.01   # 1% 容差


def _pct_diff(reported: float, fetched: float) -> float:
    """相对偏差 (absolute)。"""
    if reported == 0:
        return 0.0 if fetched == 0 else float('inf')
    return abs(reported - fetched) / abs(reported)


def render_verdict(results: list, report_name: str = "") -> dict:
    """
    根据核验结果输出准出/打回判决。

    results: list of dict，每项包含：
      - id, label, reported_value, unit, fetched_value, fetched_source
      - (可选) fetched_value2, fetched_source2   ← 第二来源

    返回：
      {
        'verdict': 'PASS' | 'FAIL',
        'pass_count': int,
        'fail_count': int,
        'total': int,
        'fail_items': [...],
        'summary': str,
      }
    """
    BOLD = '\033[1m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RESET = '\033[0m'

    print('=' * 70)
    print(f'{BOLD}报告数据抽检 — 准出/打回判决{RESET}')
    if report_name:
        print(f'报告：{report_name}')
    print('=' * 70)
    print()

    fail_items = []
    warn_items = []

    for item in results:
        label = item.get('label', '?')
        reported = float(item.get('reported_value', 0))
        unit = item.get('unit', '')
        fetched = item.get('fetched_value')
        source = item.get('fetched_source', '?')
        fetched2 = item.get('fetched_value2')
        source2 = item.get('fetched_source2', '')

        # --- 主来源比对 ---
        if fetched is None:
            # 没有提供核验值 → 跳过（不计入通过/失败）
            print(f'  ⬜ [{item["id"]:>2}] {label[:35]:35s} {reported:>12.2f} {unit}  →  [未提供核验值，跳过]')
            continue

        fetched = float(fetched)
        diff1 = _pct_diff(reported, fetched)

        # --- 第二来源比对（如有）---
        diff2 = None
        if fetched2 is not None:
            fetched2 = float(fetched2)
            diff2 = _pct_diff(reported, fetched2)

        # 判断
        pass1 = diff1 <= _TOLERANCE
        pass2 = (diff2 is None) or (diff2 <= _TOLERANCE)

        if pass1 and pass2:
            status = f'{GREEN}✅ 通过{RESET}'
            detail = f'{source}: {fetched:.2f} (偏差 {diff1*100:.2f}%)'
            if diff2 is not None:
                detail += f'  |  {source2}: {fetched2:.2f} (偏差 {diff2*100:.2f}%)'
        elif not pass1 and not pass2:
            status = f'{RED}❌ 不通过{RESET}'
            detail = f'{source}: {fetched:.2f} (偏差 {diff1*100:.2f}%)'
            if diff2 is not None:
                detail += f'  |  {source2}: {fetched2:.2f} (偏差 {diff2*100:.2f}%)'
            fail_items.append({
                'id': item['id'],
                'label': label,
                'reported': reported,
                'unit': unit,
                'fetched': fetched,
                'source': source,
                'fetched2': fetched2,
                'source2': source2,
                'diff1_pct': round(diff1 * 100, 2),
                'diff2_pct': round(diff2 * 100, 2) if diff2 is not None else None,
                'raw_text': item.get('raw_text', ''),
                'line_number': item.get('line_number', 0),
            })
        else:
            # 一个来源通过，一个不通过 → 警告，不计入失败
            status = f'{YELLOW}⚠️  警告{RESET}'
            detail = f'{source}: {fetched:.2f} (偏差 {diff1*100:.2f}%)'
            if diff2 is not None:
                detail += f'  |  {source2}: {fetched2:.2f} (偏差 {diff2*100:.2f}%)'
            warn_items.append({
                'id': item['id'], 'label': label,
                'reported': reported, 'unit': unit,
                'diff1_pct': round(diff1 * 100, 2),
                'diff2_pct': round(diff2 * 100, 2) if diff2 is not None else None,
            })

        print(f'  {status} [{item["id"]:>2}] {label[:35]:35s}  报告: {reported:>12.2f} {unit}')
        print(f'              {" " * 38}{detail}')

    print()
    print('-' * 70)

    total = len([r for r in results if r.get('fetched_value') is not None])
    fail_count = len(fail_items)
    warn_count = len(warn_items)
    pass_count = total - fail_count - warn_count

    print(f'  抽检总数: {total}  |  通过: {GREEN}{pass_count}{RESET}  |  警告: {YELLOW}{warn_count}{RESET}  |  不通过: {RED}{fail_count}{RESET}')
    print()

    if fail_count == 0:
        print(f'{BOLD}{GREEN}【准出】所有抽检数据通过，报告可发布。{RESET}')
        verdict = 'PASS'
    else:
        print(f'{BOLD}{RED}【打回】{fail_count} 个数据点核验不通过，报告需修正后重审。{RESET}')
        print()
        print(f'{BOLD}打回原因：{RESET}')
        for fi in fail_items:
            print(f'  ❌ 第 {fi["line_number"]} 行 | {fi["label"]}')
            print(f'     报告值：{fi["reported"]} {fi["unit"]}')
            print(f'     {fi["source"]}：{fi["fetched"]}  （偏差 {fi["diff1_pct"]}%）')
            if fi.get('fetched2') is not None:
                print(f'     {fi["source2"]}：{fi["fetched2"]}  （偏差 {fi["diff2_pct"]}%）')
            print(f'     原文：{fi["raw_text"][:80]}')
            print()
        verdict = 'FAIL'

    if warn_count > 0:
        print(f'{YELLOW}注意：{warn_count} 个数据点两来源结果不一致（超过1%），可能是口径差异（GAAP/Non-GAAP或汇率），请人工复核。{RESET}')
        for wi in warn_items:
            print(f'  ⚠️  {wi["label"]}  报告:{wi["reported"]} {wi["unit"]}  偏差: {wi["diff1_pct"]}% / {wi["diff2_pct"]}%')

    print('=' * 70)

    return {
        'verdict': verdict,
        'pass_count': pass_count,
        'warn_count': warn_count,
        'fail_count': fail_count,
        'total': total,
        'fail_items': fail_items,
        'warn_items': warn_items,
    }


# ---------------------------------------------------------------------------
# 报告质量三件套：check / sources / csvdetect
# ---------------------------------------------------------------------------

_HEADING_RE = re.compile(r'^(#{1,6})\s+(.+?)\s*$')
_SEP_RE = re.compile(r'^\|?[\s\-:|]+\|?$')          # markdown 表格分隔行
_URL_RE = re.compile(r'https?://\S+')
_SOURCE_MARK_RE = re.compile(r'(来源[:：]|数据来源[:：]|参考[:：]|source[:：])', re.IGNORECASE)
_NUM_CLAIM_RE = re.compile(r'\d[\d,，\.]*\s*(亿|万|%|％|元|美元|港元|x|X|倍|亿港元|亿美元)')
_CLAIM_RE = re.compile(
    r'(结论|预计|认为|表明|判断|大概率|目标价|评级|推荐|建议|应该|必须|龙头|领先|风险|盈利|亏损)')
_LIST_ITEM_RE = re.compile(r'^\s*([-*+]|\d+[.、)])\s')


def _resolve_report(path):
    """--report 支持文件或目录；目录 → 递归收集 *.md / *.markdown。"""
    if os.path.isdir(path):
        out = []
        for root, _dirs, files in os.walk(path):
            for f in sorted(files):
                if f.lower().endswith(('.md', '.markdown')):
                    out.append(os.path.join(root, f))
        return sorted(out)
    if os.path.isfile(path):
        return [path]
    return []


def _read_text(path):
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        return f.read()


def _collect_sections(lines):
    """返回章节列表 [{level, title, line(标题行号,1起), end_line(独占)}]，
    按文档出现顺序；end_line 为下一标题行号-1 或文件尾。"""
    heads = []
    for i, ln in enumerate(lines):
        m = _HEADING_RE.match(ln.strip())
        if m:
            heads.append((len(m.group(1)), m.group(2).strip(), i + 1))
    out = []
    for idx, (lv, title, ln) in enumerate(heads):
        end = heads[idx + 1][2] - 1 if idx + 1 < len(heads) else len(lines)
        out.append({'level': lv, 'title': title, 'line': ln, 'end_line': end})
    return out


def _section_of(sections, lineno):
    for s in sections:
        if s['line'] <= lineno <= s['end_line']:
            return s['title']
    return ''


def _count_items(body_lines):
    """统计章节内条目数：表格数据行（排除表头/分隔行）+ 列表项。"""
    n = 0
    for idx, ln in enumerate(body_lines):
        s = ln.strip()
        if not s or s.startswith('#'):
            continue
        if s.startswith('|'):
            if _SEP_RE.match(s):
                continue
            nxt = body_lines[idx + 1].strip() if idx + 1 < len(body_lines) else ''
            if nxt.startswith('|') and _SEP_RE.match(nxt):
                continue  # 表头行不计
            n += 1
        elif _LIST_ITEM_RE.match(s):
            n += 1
    return n


# ─── check：结构校验 ──────────────────────────────────────────

_DEFAULT_KEY_FIELDS = [
    ('日期', r'报告日期|日期|date|20\d{2}[-/年]\d{1,2}'),
    ('ticker/代码', r'ticker|股票代码|证券代码|代码'),
    # “结论”认同义词“投资论点”（现行报告多用“## 1. 投资论点”作结论章，防误杀）；
    # ticker 另有首行标题回退（见 _ticker_title_hit）。
    ('结论', r'结论|投资论点|投资结论|综合判断|建议|verdict'),
]


def _ticker_title_hit(path: str, text: str) -> bool:
    """ticker 回退命中：从 `<TICKER>-<中文名>` 目录名推断 TICKER，
    若报告首个 `#` 标题行含该 TICKER 即算命中（防 over-strict 误杀）。

    例：research/060-companies/NVDA-英伟达/.../07-report.md 首行
    `# NVDA — ...` 含 NVDA → 命中。目录名无中文后缀（如 2026-09-09）
    不参与推断，避免年份误判。
    """
    cand = None
    for part in os.path.normpath(path).split(os.sep):
        m = re.match(r'^([A-Za-z0-9.]+)-.*[\u4e00-\u9fa5]', part)
        if m:
            cand = m.group(1).upper()
            break
    if not cand:
        return False
    first_heading = ''
    for ln in text.splitlines():
        if ln.strip().startswith('#'):
            first_heading = ln.strip()
            break
    if not first_heading:
        return False
    return cand in first_heading.upper()


def _check_one(path, required, key_fields, min_items):
    text = _read_text(path)
    lines = text.splitlines()
    sections = _collect_sections(lines)

    missing_sections = []
    for req in required:
        if not any(req in s['title'] for s in sections):
            missing_sections.append(req)

    missing_fields = []
    for name, pat in key_fields:
        try:
            found = re.search(pat, text, re.IGNORECASE)
        except re.error:
            found = re.search(re.escape(pat), text, re.IGNORECASE)
        if not found:
            # ticker/代码回退：默认 key_fields 的 ticker 项若未命中，
            # 看首行标题是否含目录名推断的 TICKER（含即命中，防误杀）。
            # 用户显式 --key-field 追加的同名项不参与回退（只对默认项）。
            if name == 'ticker/代码' and (name, pat) == (
                    _DEFAULT_KEY_FIELDS[1][0], _DEFAULT_KEY_FIELDS[1][1]) \
                    and _ticker_title_hit(path, text):
                continue
            missing_fields.append(name)

    min_fails = []
    for sec_name, n_min in min_items:
        sec = next((s for s in sections if sec_name in s['title']), None)
        if sec is None:
            min_fails.append({'section': sec_name, 'expected': n_min, 'found': 0,
                              'reason': 'section_not_found'})
            continue
        body = lines[sec['line']:sec['end_line']]
        found_n = _count_items(body)
        if found_n < n_min:
            min_fails.append({'section': sec_name, 'expected': n_min, 'found': found_n})

    return {
        'file': path,
        'passed': not missing_sections and not missing_fields and not min_fails,
        'missing_sections': missing_sections,
        'missing_key_fields': missing_fields,
        'min_items_failures': min_fails,
        'sections_found': [s['title'] for s in sections],
    }


def cmd_check(args):
    files = _resolve_report(args.report)
    if not files:
        return {'error': f'未找到 Markdown 文件: {args.report}'}
    required = list(args.required or []) + list(args.required_section or [])
    min_items = list(zip(args.section or [], args.min_items or []))
    if len(args.section or []) != len(args.min_items or []):
        return {'error': '--min-items 与 --section 必须成对出现（数量不一致）'}
    key_fields = list(_DEFAULT_KEY_FIELDS)
    for kf in (args.key_field or []):
        if '=' in kf:
            name, _, pat = kf.partition('=')
        elif ':' in kf:
            name, _, pat = kf.partition(':')
        else:
            name, pat = kf, re.escape(kf)
        key_fields.append((name.strip(), pat))
    return [_check_one(p, required, key_fields, min_items) for p in files]


# ─── sources：来源标注检查 ────────────────────────────────────

def _sources_one(path, require_per_section):
    text = _read_text(path)
    lines = text.splitlines()
    sections = _collect_sections(lines)

    # 逐段扫描：段落 = 连续非空正文行；跳过标题/表格行/分隔行/引用/代码块
    unsourced = []
    para_lines = []   # [(lineno, text)]
    para_start = 0
    in_code = False

    def flush():
        nonlocal para_lines
        if not para_lines:
            return
        joined = '\n'.join(t for _, t in para_lines)
        has_src = any(_URL_RE.search(t) or _SOURCE_MARK_RE.search(t) for _, t in para_lines)
        has_num = any((not _LIST_ITEM_RE.match(t)) and _NUM_CLAIM_RE.search(t) for _, t in para_lines)
        has_claim = any(_CLAIM_RE.search(t) for _, t in para_lines)
        if (has_num or has_claim) and not has_src:
            unsourced.append({
                'line': para_start,
                'section': _section_of(sections, para_start),
                'reason': 'number_without_source' if has_num else 'claim_without_source',
                'snippet': joined[:120],
            })
        para_lines = []

    for idx, ln in enumerate(lines, 1):
        s = ln.strip()
        if s.startswith('```'):
            flush()
            in_code = not in_code
            continue
        if in_code:
            continue
        if not s:
            flush()
            continue
        if _HEADING_RE.match(s) or s.startswith('|') or _SEP_RE.match(s) or s.startswith('>'):
            flush()
            continue
        if not para_lines:
            para_start = idx
        para_lines.append((idx, s))
    flush()

    # 整节无来源（--require-per-section 时记录）
    section_unsourced = []
    sections_with_src = 0
    for sec in sections:
        body = lines[sec['line']:sec['end_line']]
        has = any(_URL_RE.search(ln) or _SOURCE_MARK_RE.search(ln) for ln in body)
        if has:
            sections_with_src += 1
        elif require_per_section:
            section_unsourced.append({'section': sec['title'], 'line': sec['line']})

    return {
        'file': path,
        'unsourced_count': len(unsourced),
        'unsourced': unsourced,
        'require_per_section': require_per_section,
        'section_unsourced': section_unsourced,
        'sections_total': len(sections),
        'sections_with_source': sections_with_src,
    }


def cmd_sources(args):
    files = _resolve_report(args.report)
    if not files:
        return {'error': f'未找到 Markdown 文件: {args.report}'}
    return [_sources_one(p, args.require_per_section) for p in files]


# ─── csvdetect：CSV 乱入检测 ──────────────────────────────────

def _cols(line):
    """行按 | 拆列：去掉首尾空单元格。"""
    cells = [c.strip() for c in line.split('|')]
    if cells and cells[0] == '':
        cells = cells[1:]
    if cells and cells[-1] == '':
        cells = cells[:-1]
    return cells


def _csv_one(path):
    text = _read_text(path)
    lines = text.splitlines()
    issues = []
    n = len(lines)

    # 表格块扫描：表头 + 分隔行 + 数据行；校验列数一致性
    i = 0
    in_code = False
    while i < n:
        s = lines[i].strip()
        if s.startswith('```'):
            in_code = not in_code
            i += 1
            continue
        if in_code:
            i += 1
            continue
        if '|' in s and not _SEP_RE.match(s) and i + 1 < n and _SEP_RE.match(lines[i + 1].strip()):
            hdr_cols = _cols(s)
            sep_cols = _cols(lines[i + 1].strip())
            if len(sep_cols) != len(hdr_cols):
                issues.append({'type': 'header_separator_mismatch', 'line': i + 2,
                               'table_start_line': i + 1, 'expected_cols': len(hdr_cols),
                               'actual_cols': len(sep_cols), 'snippet': lines[i + 1].strip()[:80]})
            j = i + 2
            while j < n and '|' in lines[j] and not _SEP_RE.match(lines[j].strip()):
                row_cols = _cols(lines[j])
                if len(row_cols) != len(hdr_cols):
                    if re.search(r'\d\s*,\s*-?\d', lines[j]):
                        itype = 'comma_cell_misalignment'   # 单元格逗号数字未加引号致错位
                    else:
                        itype = 'column_count_mismatch'     # 表头与数据列数不符
                    issues.append({'type': itype, 'line': j + 1, 'table_start_line': i + 1,
                                   'expected_cols': len(hdr_cols), 'actual_cols': len(row_cols),
                                   'snippet': lines[j].strip()[:80]})
                j += 1
            i = j
            continue
        i += 1

    # 原始 CSV 文本块：连续 ≥2 行、每行 ≥2 个 ASCII 逗号、无 |、非标题/非代码
    # 排除 markdown 列表项（- / * / + / 「N.」开头）：裸 CSV 导出不会带列表项目符号，
    # 而分析报告里连续几条含逗号的要点句是常态（AAPL 2026-09-15 三条 ROE/因子要点被
    # 整块误判为 CSV，从而把 Gate 3 卡死）。列表项本身另有 number_without_source 检查覆盖。
    _LIST_ITEM_RE = re.compile(r'^([-*+]|\d+[.)])\s+\S')
    run = []
    in_code2 = False
    for idx, ln in enumerate(lines, 1):
        s = ln.strip()
        if s.startswith('```'):
            in_code2 = not in_code2
            continue
        is_csv = (not in_code2) and s and '|' not in s and not s.startswith('#') \
                 and not _HEADING_RE.match(s) and not _LIST_ITEM_RE.match(s) \
                 and s.count(',') >= 2
        if is_csv:
            run.append(idx)
        else:
            if len(run) >= 2:
                issues.append({'type': 'raw_csv_block', 'line_start': run[0], 'line_end': run[-1],
                               'lines': len(run), 'snippet': lines[run[0] - 1].strip()[:80]})
            run = []
    if len(run) >= 2:
        issues.append({'type': 'raw_csv_block', 'line_start': run[0], 'line_end': run[-1],
                       'lines': len(run), 'snippet': lines[run[0] - 1].strip()[:80]})

    issues.sort(key=lambda x: (x.get('line') or x.get('line_start') or 0))
    return {'file': path, 'issue_count': len(issues), 'issues': issues}


def cmd_csvdetect(args):
    files = _resolve_report(args.report)
    if not files:
        return {'error': f'未找到 Markdown 文件: {args.report}'}
    return [_csv_one(p) for p in files]


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Report Audit Tool — 研究报告数据抽检工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
工作流程：

  Step 1 — 提取数据点并随机抽样 15%，输出抽检清单：
    python3 tools/report_audit.py extract --report reports/腾讯/腾讯-research-20260408.md

  Step 2 — Claude 对清单中每个数据点，从可靠信源取数，
            填入 fetched_value / fetched_source / fetched_value2 / fetched_source2

  Step 3 — 输入核验结果，输出准出/打回判决：
    python3 tools/report_audit.py verdict --results '[
      {"id":1,"label":"营业收入","reported_value":7518,"unit":"亿","fetched_value":7518,"fetched_source":"macrotrends","fetched_value2":7500,"fetched_source2":"stockanalysis"},
      ...
    ]'

  一步预览（只打印抽检清单，不核验）：
    python3 tools/report_audit.py extract --report reports/xxx.md --dry-run

  指定抽样比例（默认0.15）：
    python3 tools/report_audit.py extract --report reports/xxx.md --ratio 0.20

  固定随机种子（复现同一批样本）：
    python3 tools/report_audit.py extract --report reports/xxx.md --seed 42

报告质量三件套（--report 支持文件或目录；输出 JSON 到 stdout，摘要到 stderr）：

  check — 结构校验：
    python3 tools/report_audit.py check --report reports/xxx.md \\
        --required "第一章" --required "投资结论" \\
        --min-items 5 --section "持股名单"          # 持股名单至少 5 行

  sources — 来源标注检查：
    python3 tools/report_audit.py sources --report reports/xxx.md --require-per-section

  csvdetect — CSV 乱入检测：
    python3 tools/report_audit.py csvdetect --report reports/xxx.md
        """)

    sub = parser.add_subparsers(dest='command')

    # extract
    ext = sub.add_parser('extract', help='从报告提取数据点并随机抽样')
    ext.add_argument('--report', required=True, help='报告文件路径（Markdown）')
    ext.add_argument('--ratio', type=float, default=0.15, help='抽样比例，默认 0.15')
    ext.add_argument('--seed', type=int, default=None, help='随机种子（可选，用于复现）')
    ext.add_argument('--dry-run', action='store_true', help='只打印，不输出 JSON')

    # verdict
    vrd = sub.add_parser('verdict', help='根据核验结果输出准出/打回判决')
    vrd.add_argument('--results', required=True, help='JSON 数组，含 fetched_value 等字段')
    vrd.add_argument('--report', default='', help='报告名称（可选，用于显示）')
    vrd.add_argument('--output-json', action='store_true', help='将判决结果以 JSON 输出到 stdout')

    # check — 结构校验
    chk = sub.add_parser('check', help='结构校验：必填章节/关键字段/章节最少条目数')
    chk.add_argument('--report', required=True, help='报告文件或目录（Markdown）')
    chk.add_argument('--required', action='append', default=None,
                     help='必填章节名（可重复传，如 --required "第一章"）')
    chk.add_argument('--required-section', action='append', default=None,
                     help='必填章节名别名（与 --required 等价，可重复传）')
    chk.add_argument('--key-field', action='append', default=None,
                     help='附加关键字段，格式 name=regex 或纯文本（可重复传；默认检查日期/ticker/结论）')
    chk.add_argument('--min-items', type=int, action='append', default=None,
                     help='章节最少条目数（需与 --section 成对，可重复）')
    chk.add_argument('--section', action='append', default=None,
                     help='--min-items 对应的章节名（可重复）')

    # sources — 来源标注检查
    src = sub.add_parser('sources', help='来源标注检查：无来源的含数/断言段落 + 整节无来源')
    src.add_argument('--report', required=True, help='报告文件或目录（Markdown）')
    src.add_argument('--require-per-section', action='store_true',
                     help='整节无任何来源标注（URL 或「来源：」）时记入 section_unsourced')

    # csvdetect — CSV 乱入检测
    csvp = sub.add_parser('csvdetect', help='CSV 乱入检测：表列数错位/未加引号逗号数字/裸 CSV 文本块')
    csvp.add_argument('--report', required=True, help='报告文件或目录（Markdown）')

    args = parser.parse_args()

    if args.command == 'extract':
        if not os.path.exists(args.report):
            print(f'❌ 文件不存在: {args.report}', file=sys.stderr)
            sys.exit(1)

        with open(args.report, 'r', encoding='utf-8') as f:
            text = f.read()

        all_points = extract_data_points(text)
        sampled = sample_points(all_points, ratio=args.ratio, seed=args.seed)

        print('=' * 70)
        print(f'报告数据抽检清单')
        print(f'文件：{args.report}')
        print(f'总提取数据点：{len(all_points)}  |  抽样比例：{args.ratio:.0%}  |  抽检数量：{len(sampled)}')
        if args.seed is not None:
            print(f'随机种子：{args.seed}（可用于复现同一批样本）')
        print('=' * 70)
        print()
        print(f'{"ID":>3}  {"行号":>5}  {"数据标签":<35}  {"报告值":>12}  {"单位"}')
        print(f'{"─"*3}  {"─"*5}  {"─"*35}  {"─"*12}  {"─"*6}')
        for p in sampled:
            print(f'{p["id"]:>3}  {p["line_number"]:>5}  {p["label"][:35]:<35}  {p["reported_value"]:>12.2f}  {p["unit"]}')
        print()
        print('↑ 请对上述每个数据点，从以下信源取数，填入 fetched_value：')
        print('  美股：macrotrends.net（主）+ stockanalysis.com（副）')
        print('  港股：aastocks.com（主）+ macrotrends ADR（副）')
        print('  A股： eastmoney.com（主）+ cninfo.com.cn（副）')
        print()

        if not args.dry_run:
            # 输出可填写的 JSON 模板
            template = []
            for p in sampled:
                template.append({
                    'id': p['id'],
                    'label': p['label'],
                    'reported_value': p['reported_value'],
                    'unit': p['unit'],
                    'line_number': p['line_number'],
                    'raw_text': p['raw_text'],
                    'fetched_value': None,       # ← 填入主来源核验值
                    'fetched_source': '',        # ← 填入主来源名称
                    'fetched_value2': None,      # ← 填入副来源核验值（可选）
                    'fetched_source2': '',       # ← 填入副来源名称（可选）
                })
            print('抽检清单 JSON（填入 fetched_value 后，传给 verdict 命令）：')
            print()
            print(json.dumps(template, ensure_ascii=False, indent=2))

    elif args.command == 'verdict':
        try:
            results = json.loads(args.results)
        except json.JSONDecodeError as e:
            print(f'❌ JSON 解析失败: {e}', file=sys.stderr)
            sys.exit(1)

        report_name = args.report or ''
        outcome = render_verdict(results, report_name=report_name)

        if args.output_json:
            print(json.dumps(outcome, ensure_ascii=False, indent=2))

        # 非零退出码表示打回，方便 CI/脚本判断
        sys.exit(0 if outcome['verdict'] == 'PASS' else 1)

    elif args.command == 'check':
        res = cmd_check(args)
        if isinstance(res, dict) and 'error' in res:
            print(json.dumps(res, ensure_ascii=False, indent=2), file=sys.stderr)
            sys.exit(1)
        passed = all(r['passed'] for r in res)
        for r in res:
            parts = []
            if r['missing_sections']:
                parts.append('缺章节:' + ','.join(r['missing_sections']))
            if r['missing_key_fields']:
                parts.append('缺字段:' + ','.join(r['missing_key_fields']))
            if r['min_items_failures']:
                parts.append(f"条目不足:{len(r['min_items_failures'])}处")
            line = f"[CHECK] {'通过' if r['passed'] else '不通过'} {r['file']}"
            if parts:
                line += ' — ' + '; '.join(parts)
            print(line, file=sys.stderr)
        out = res[0] if len(res) == 1 else {'files': res, 'passed': passed}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        sys.exit(0 if passed else 1)

    elif args.command == 'sources':
        res = cmd_sources(args)
        if isinstance(res, dict) and 'error' in res:
            print(json.dumps(res, ensure_ascii=False, indent=2), file=sys.stderr)
            sys.exit(1)
        for r in res:
            print(f"[SOURCES] {r['file']} — 无来源段落:{r['unsourced_count']}"
                  f" 整节无来源:{len(r['section_unsourced'])}"
                  f" (共{r['sections_total']}节, {r['sections_with_source']}节有来源)", file=sys.stderr)
        out = res[0] if len(res) == 1 else {'files': res}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        sys.exit(0)

    elif args.command == 'csvdetect':
        res = cmd_csvdetect(args)
        if isinstance(res, dict) and 'error' in res:
            print(json.dumps(res, ensure_ascii=False, indent=2), file=sys.stderr)
            sys.exit(1)
        for r in res:
            print(f"[CSVDETECT] {r['file']} — 可疑 {r['issue_count']} 处", file=sys.stderr)
        out = res[0] if len(res) == 1 else {'files': res}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        sys.exit(0)

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
