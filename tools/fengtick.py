#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FengInvest ←→ tickflow-stock-panel 侧车薄桥（纯本地、零依赖）

定位
----
按「独立仓库 + 薄桥」批复形态，本文件是 FengInvest 到 tickflow 侧车的**只读桥梁**：
- 只读参考 `~/tickflow-stock-panel`，**不修改它、不跑它的服务器、不安装其依赖**
  （tickflow 依赖 polars/pydantic 等，FengInvest 环境不装、不 import，T2 采用纯 Python 复刻）。
- 幽灵原则（见 .agents/skills/fengspec/SKILL.md 铁律）：
  **tickflow 只供 T0 触发数据 / T2 防线位数据 / T4 监控信号数据；纪律（T3）与卖出（T5）永远留在 FengInvest。**
  本工具只产出"数据/摘要"，绝不越过这条线生成任何买入/卖出结论。

映射到 fengspec 六步
--------------------
- T0 触发  → `t0` 子命令：读取 tickflow data/ 下已生成的扫描/信号结果（路径探测，存在才解析；
            不存在则友好提示 + 命令指引），聚合成 `research/speculative/<YYYY-MM-DD>-candidates.json`。
- T2 结构  → `t2` 子命令：复刻 tickflow `backend/app/indicators/levels.py` 的"防线位"纯函数
            （前高前低 / pivot / ATR 波动通道等），输出给决策卡：关键防线位（止损锚）摘要 + 一句话说明。
- T4 监控  → `t4` 子命令：仅在文档中说明如何把 tickflow 监控信号接入 `fengwatch`，**不修改 fengwatch.py**。

隐私 / 数据原则
---------------
- 产物全部落在 `research/speculative/`（gitignored）或 tickflow data/（读取侧），**绝不写公开目录**；
- 纯本地，不联网，无任何 API key，不调用 tickflow 接口。

用法（CLI）
-----------
    # T0：聚合今日 tickflow 扫描候选（日期默认今天，可用 --date 覆盖）
    python tools/fengtick.py t0 [--date 2026-08-19] [--tickflow-dir ~/tickflow-stock-panel]

    # T2：对本地 OHLCV 数据（CSV/JSON）输出防线位摘要（止损锚）
    python tools/fengtick.py t2 600519 --file path/to/ohlcv.csv
    python tools/fengtick.py t2 600519 --file path/to/ohlcv.json --json

    # T4：查看"tickflow 监控信号 → fengwatch"接入说明（纯文档，不改任何文件）
    python tools/fengtick.py t4
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from datetime import date, datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC_DIR = os.path.join(BASE, "research", "speculative")
TICKFLOW_DEFAULT_DIR = os.path.expanduser("~/tickflow-stock-panel")

# ================================================================
# T0 —— 探测 tickflow 数据目录
# ================================================================

def resolve_tickflow_root(explicit: str | None) -> str | None:
    """定位 tickflow 仓库根目录。

    优先级：--tickflow-dir 参数 > 环境变量 TICKFLOW_DIR > 本机默认路径。
    只做存在性检查，不联网、不改 tickflow。
    """
    candidates = [explicit, os.environ.get("TICKFLOW_DIR"), TICKFLOW_DEFAULT_DIR]
    for c in candidates:
        if c and os.path.isdir(c):
            return c
    return None


def resolve_tickflow_data(root: str) -> str | None:
    """解析 tickflow 的 data 目录。

    镜像 tickflow `backend/app/config.py` 的规则：
      - 非 frozen（开发模式）→ 项目根 data/
      - 可用环境变量 DATA_DIR 覆盖
    存在才返回，否则 None（由 T0 给友好指引）。
    """
    env_data = os.environ.get("DATA_DIR")
    if env_data and os.path.isdir(env_data):
        return env_data
    d = os.path.join(root, "data")
    return d if os.path.isdir(d) else None


# 扫描结果候选子路径（tickflow 侧车可能把结果放这里，全部只读探测）
_SCAN_SUBPATHS = [
    "signals",           # data/signals/*.json    信号扫描结果
    "scans",             # data/scans/*.json      手动扫描导出
    "signal_scans",      # data/signal_scans/*.json
    "user_data/signals", # data/user_data/signals（自定义信号定义亦可作为触发源）
]
# 文件名关键词（命中即视为扫描/触发类结果）
_SCAN_NAME_KEYWORDS = ("scan", "signal", "candidate", "候选", "突破", "trigger", "monitor", "alert")
# 直接命中的单文件（tickflow 固定产物）
_SCAN_DIRECT_FILES = [os.path.join("user_data", "alerts.jsonl")]


def _candidate_subdirs(data_dir: str, sub: str) -> list[str]:
    """data_dir 可能指向打包版（exe 旁），也可能指向开发版根；两层都试。"""
    out = []
    for base in (data_dir,):
        p = os.path.join(base, sub)
        if os.path.isdir(p):
            out.append(p)
    return out


def probe_scan_sources(data_dir: str) -> list[tuple[str, str | None]]:
    """探测 data/ 下已生成的扫描结果，返回 [(绝对路径, kind), ...]。

    kind：json | jsonl | None(无法判定)。探测多个候选子目录 + 固定单文件，
    只收集存在且为普通文件、扩展名 json/jsonl 或命中关键词名的文件。
    """
    found: list[tuple[str, str | None]] = []

    # 1) 子目录里所有 json/jsonl
    for sub in _SCAN_SUBPATHS:
        for d in _candidate_subdirs(data_dir, sub):
            if not os.path.isdir(d):
                continue
            for fn in sorted(os.listdir(d)):
                p = os.path.join(d, fn)
                if not os.path.isfile(p):
                    continue
                low = fn.lower()
                if low.endswith((".json", ".jsonl")):
                    found.append((p, "jsonl" if low.endswith(".jsonl") else "json"))
                elif any(k in low for k in _SCAN_NAME_KEYWORDS):
                    found.append((p, None))

    # 2) data 根下文件名命中关键词的 json/jsonl
    try:
        for fn in sorted(os.listdir(data_dir)):
            p = os.path.join(data_dir, fn)
            low = fn.lower()
            if os.path.isfile(p) and (low.endswith((".json", ".jsonl")) or any(k in low for k in _SCAN_NAME_KEYWORDS)):
                found.append((p, "jsonl" if low.endswith(".jsonl") else "json"))
    except OSError:
        pass

    # 3) 固定单文件（alerts.jsonl 等）
    for sub in _SCAN_DIRECT_FILES:
        p = os.path.join(data_dir, *os.path.split(sub))
        if os.path.isfile(p):
            found.append((p, "jsonl"))

    # 去重保序
    seen: set[str] = set()
    out = []
    for p, k in found:
        if p not in seen:
            seen.add(p)
            out.append((p, k))
    return out


# ================================================================
# T0 —— 解析扫描结果 → 候选对象
# ================================================================

_SYM_HINT_KEYS = ("symbol", "ticker", "code", "stock_code", "ts_code", "证券代码", "代码", "标的代码", "标的")
_EVENT_HINT_KEYS = ("event", "trigger", "trigger_reason", "reason", "title", "name", "signal_name",
                    "signal", "desc", "description", "事件", "触发源", "触发", "信号", "名称", "描述", "消息", "标题")
_TYPE_HINT_KEYS = ("trigger_type", "trigger_category", "type", "类别", "触发类型", "触发源类型")

_SYM_RE = re.compile(
    r"^(?P<alnum>[A-Z]{1,6}\d{0,5})$"               # AAPL / MSFT / HK00700
    r"|^(?P<num>\d{5,6})$"                           # A 股 6 位（600519）
    r"|^(?P<suffix>[0-9]{5,6}\.(SH|SZ|BJ)|HK[0-9]{5}|[A-Z]{1,5}\.[A-Z]{2})$"  # 600519.SH / BRK.B
)

_TRIGGER_TYPE_MAP = {
    "右侧突破": "右侧突破", "突破": "右侧突破", "breakout": "右侧突破", "resistance": "右侧突破",
    "事件驱动": "事件驱动", "事件": "事件驱动", "event": "事件驱动", "event_driven": "事件驱动",
    "动量": "动量", "momentum": "动量", "趋势": "动量",
}
# 关键词 → 触发类型（推断用；按特异性排序，事件类最优先命中）
_TYPE_KEYWORD_RULES = [
    ("事件驱动", ("重组", "并购", "收购", "股权", "业绩", "预告", "超预期", "题材", "公告",
               "利好", "中标", "订单", "增持", "回购", "st", "摘帽", "复牌", "事件")),
    ("动量", ("动量", "momentum", "加速", "起爆", "趋势强化", "主升浪")),
    ("右侧突破", ("突破", "breakout", "创新高", "新高", "放量上涨", "右侧", "阻力突破", "突破前高")),
]


def _looks_like_symbol(v) -> bool:
    if isinstance(v, str):
        v = v.strip()
        return bool(v and _SYM_RE.match(v))
    return False


def _extract_symbols(record) -> list[str]:
    """从一条记录里提取符号列表（优先带 hint 字段名的值，其次值是代码样式的字段）。"""
    if not isinstance(record, dict):
        return []
    syms: list[str] = []

    def _add(s):
        s = str(s).strip().upper()
        if s and s not in syms:
            syms.append(s)

    # 1) hint 字段
    for k, v in record.items():
        if k in _SYM_HINT_KEYS:
            if isinstance(v, list):
                for x in v:
                    if _looks_like_symbol(x):
                        _add(x)
            elif _looks_like_symbol(v):
                _add(v)
    # 2) 兜底：值长得像代码的字段
    for k, v in record.items():
        if isinstance(v, str) and _looks_like_symbol(v):
            _add(v)
    return syms


def _extract_event(record) -> str:
    """取事件描述：优先 hint 字段，其次任意字符串字段里第一个非空。"""
    if not isinstance(record, dict):
        return ""
    for k, v in record.items():
        if k in _EVENT_HINT_KEYS and isinstance(v, (str, int, float)) and str(v).strip():
            return str(v).strip()
    for k, v in record.items():
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _infer_trigger_type(record, explicit_type: str = "") -> str:
    """推断触发类型：显式字段 > 文本关键词规则，均无 → 右侧突破。"""
    for k in _TYPE_HINT_KEYS:
        if k in record and record[k]:
            mapped = _TRIGGER_TYPE_MAP.get(str(record[k]).strip().lower(), "")
            if mapped:
                return mapped
    if explicit_type in _TRIGGER_TYPE_MAP:
        return _TRIGGER_TYPE_MAP[explicit_type]
    text = _extract_event(record).lower()
    for ttype, kws in _TYPE_KEYWORD_RULES:
        for kw in kws:
            if kw in text:
                return ttype
    return "右侧突破"


def _iter_records(path: str, kind: str | None):
    """把文件读成记录流（dict），json / jsonl / 未知均容错。"""
    try:
        if kind == "jsonl" or path.lower().endswith(".jsonl"):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(obj, dict):
                        yield obj
                    elif isinstance(obj, list):
                        yield from (x for x in obj if isinstance(x, dict))
            return
        # json / 未知：按 json 解析
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
        if isinstance(obj, dict):
            # 可能是 {date:, items:[...]} 包壳；items/types 下钻找列表
            for key in ("candidates", "items", "records", "signals", "results", "data", "list"):
                if isinstance(obj.get(key), list):
                    yield from (x for x in obj[key] if isinstance(x, dict))
                    return
            yield obj
        elif isinstance(obj, list):
            yield from (x for x in obj if isinstance(x, dict))
    except (OSError, json.JSONDecodeError):
        return


def collect_candidates(data_dir: str) -> dict:
    """扫描 data/ 下所有结果，聚合候选。

    返回 {found_sources, items}；items 每个元素为
    {symbols, event, trigger_type, source}（均已去重保序，symbols ≤ 3）。
    """
    sources = probe_scan_sources(data_dir)
    items: list[dict] = []
    seen_syms: dict[str, dict] = {}

    for path, kind in sources:
        mtime = os.path.getmtime(path)
        for rec in _iter_records(path, kind):
            syms = _extract_symbols(rec)
            if not syms:
                continue
            event = _extract_event(rec)
            ttype = _infer_trigger_type(rec, str(rec.get("trigger_type", "")))
            syms = syms[:3]
            for s in syms:
                cur = seen_syms.get(s)
                if cur is None:
                    cur = {"symbols": [], "event": "", "trigger_type": ttype, "source": path, "mtime": mtime}
                    seen_syms[s] = cur
                if s not in cur["symbols"]:
                    cur["symbols"].append(s)  # 注：占位，最终在下方统一处理
                if event and not cur["event"]:
                    cur["event"] = event
                # 已有显式触发类型不覆盖
                cur["trigger_type"] = cur.get("trigger_type") or ttype

    # 伪列整理：只保留每条的 symbol（单条一个候选 = 一个 symbol，避免一条含多个）
    # 说明：aggregation 以"symbol"为最小候选单位——触发源一句话里可带 ≤3 只标的，
    # 但每条 record 内多个 symbol 拆开更利于去重排序。
    items = []
    for s, cur in seen_syms.items():
        items.append({
            "symbol": s,
            "event": cur["event"],
            "trigger_type": cur["trigger_type"],
            "source": cur["source"],
            "mtime": cur["mtime"],
        })
    return {"found_sources": sources, "items": items}


def cmd_t0(args) -> int:
    root = resolve_tickflow_root(args.tickflow_dir)
    print("fengtick T0 — 触发候选聚合（纯本地，不联网）")
    if not root:
        print(f"  ❌ 未找到 tickflow 仓库根目录。")
        print(f"     已尝试：--tickflow-dir 参数 / 环境变量 TICKFLOW_DIR / 默认 {TICKFLOW_DEFAULT_DIR}")
        print(f"     修正方法：python tools/fengtick.py t0 --tickflow-dir <tickflow 仓库根>")
        return 1

    data_dir = resolve_tickflow_data(root)
    if not data_dir or not os.path.isdir(data_dir):
        print(f"  ⚠️  tickflow 仓库存在（{root}），但其 data/ 目录尚未生成（开发版应为 {os.path.join(root, 'data')}）。")
        print()
        _print_t0_guidance(root)
        return 0

    agg = collect_candidates(data_dir)
    if not agg["found_sources"]:
        print(f"  ⚠️  data/ 存在但未发现扫描结果文件（已探测：{data_dir} 及其信号子目录）。")
        print()
        _print_t0_guidance(root, data_dir)
        return 0

    if args.json:
        print(json.dumps([p for p, _ in agg["found_sources"]], ensure_ascii=False, indent=2))
        return 0

    print(f"  ✅ 发现 {len(agg['found_sources'])} 个扫描结果文件，{len(agg['items'])} 个候选标的：")
    for p, _ in agg["found_sources"]:
        print(f"     - {p}")

    if not agg["items"]:
        print("  ⚠️  读取文件成功但未提取到候选标的（可检查字段名：symbol/ticker/code/代码）。")
        return 0

    chosen = choose_top_candidates(agg["items"])
    output_path = write_candidates_json(args.date, chosen, agg["found_sources"])
    print()
    print(f"  ✅ 候选已聚合 → {output_path}")
    for c in chosen["symbols_detail"]:
        print(f"     {c['symbol']:<12} 触发[{c['trigger_type']}]  {c['event'][:60] or '(无事件描述)'}")
    return 0


def choose_top_candidates(items: list[dict]) -> dict:
    """选取 ≤3 只候选：优先有事件描述者，其次按源文件新旧。"""
    ranked = sorted(items, key=lambda x: (1 if not x["event"] else 0, -x["mtime"]))
    picked = ranked[:3]
    # 触发类型 = 选中的里最常见，兜底 右侧突破
    tcount: dict[str, int] = {}
    for it in picked:
        tcount[it["trigger_type"]] = tcount.get(it["trigger_type"], 0) + 1
    main_type = max(tcount, key=tcount.get) if tcount else "右侧突破"

    details = []
    for it in picked:
        details.append({
            "symbol": it["symbol"],
            "event": it["event"] or "",
            "trigger_type": it["trigger_type"],
            "source": it["source"],
        })
    return {"symbols": [d["symbol"] for d in details], "symbols_detail": details,
            "trigger_type": main_type}


def write_candidates_json(day: date, chosen: dict, found_sources: list[tuple[str, str | None]]) -> str:
    os.makedirs(SPEC_DIR, exist_ok=True)
    path = os.path.join(SPEC_DIR, f"{day.isoformat()}-candidates.json")
    event_lines = []
    for d in chosen["symbols_detail"]:
        if d["event"]:
            event_lines.append(f"{d['symbol']}: {d['event'][:40]}")
    payload = {
        "date": day.isoformat(),
        "trigger_type": chosen["trigger_type"],
        "event": "；".join(event_lines)[:120],
        "symbols": chosen["symbols"],
        "trigger_source": "tickflow 扫描结果（fengtick T0 聚合）",
        "source_paths": [p for p, _ in found_sources],
        "generated_by": "fengtick.py T0",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return path


def _print_t0_guidance(root: str, data_dir: str | None = None) -> None:
    print("  【友好指引】fengtick T0 只读消费，等待 tickflow 侧车先生成扫描结果：")
    print(f"    1) 在 tickflow（仓库 {root}）里跑大腿扫描/监测，产出候选结果；")
    print(f"    2) 把扫描结果存为该仓库 {data_dir or 'data/'} 下的 JSON/JSONL，推荐：")
    print(f"         {data_dir or 'data'}/signals/<任意名>.json      （数组或包壳，每条含 symbol/ticker/code + event）")
    print(f"         {data_dir or 'data'}/user_data/alerts.jsonl    （tickflow 监测告警流，自带）")
    print(f"    3) 重跑： python tools/fengtick.py t0   → 产出 research/speculative/<日期>-candidates.json")
    print("    提示：本工具不启动 tickflow 服务器、不装其依赖、不改其任何文件；字段建议")
    print("         symbol/ticker/code（代码）、event/trigger（事件）、trigger_type（右侧突破|事件驱动|动量）。")


# ================================================================
# T2 —— 纯 Python 复刻 tickflow levels.py 的"防线位"纯函数
# ================================================================
# 说明：tickflow `backend/app/indicators/levels.py` 依赖 polars，FengInvest 环境
# 不装 polars → 此处在标准库内 1:1 复刻其逻辑，输出结构 {type: [点位], ...} 与
# LEVEL_TYPES 同名，保证"防线位摘要"语义一致。OHLCV 输入为逐行 dict 列表。
# ================================================================

LEVEL_TYPES = {
    "sr": "压力支撑(筹码密集区)",
    "pivot": "枢轴点",
    "extreme": "前高前低",
    "boll": "布林带",
    "keltner_s": "Keltner短期",
    "keltner_m": "Keltner中期",
    "keltner_l": "Keltner长期",
    "atr_stop": "ATR波动通道",
    "gap": "缺口位",
    "fib": "斐波那契",
    "round": "整数关口",
}
# T2 决策卡只摘「关键防线位 = 前高前低 / pivot / ATR 通道」三类，其余为参考
DEFENSE_KEYS = ("extreme", "pivot", "atr_stop")


def _ok(v) -> bool:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f) and f > 0


def _side(level: float, close: float) -> str:
    if level > close * 1.001:
        return "resistance"
    if level < close * 0.999:
        return "support"
    return "neutral"


def _aggregate_levels(values: list[float], tol: float) -> list[float]:
    if not values:
        return []
    values = sorted(values)
    out = [values[0]]
    for v in values[1:]:
        if abs(v - out[-1]) / out[-1] <= tol:
            out[-1] = v
        else:
            out.append(v)
    return out


def _columns(df: list[dict]):
    close = [float(r.get("close")) for r in df]
    high = [float(r.get("high")) for r in df]
    low = [float(r.get("low")) for r in df]
    open_ = [float(r.get("open")) for r in df]
    volume = [float(r.get("volume") or 0) for r in df]
    sell = [float(r.get("turnover_rate") or 0) for r in df]
    return close, high, low, open_, volume, sell


def _atr_14(high, low, close_):
    """TR=Max(H-L,|H-pc|,|L-pc|)，首行 TR=H-L；ATR 取最近 14 个 TR 的 SMA。
    近似 tickflow 预计算的 atr_14 列（Wilder 平滑 vs SMA 差异极小，够防线定位用）。"""
    tr = []
    prev = None
    for i in range(len(close_)):
        h, l, c = high[i], low[i], close_[i]
        if prev is None:
            tr.append(h - l)
        else:
            tr.append(max(h - l, abs(h - prev), abs(l - prev)))
        prev = c
    atr = []
    for i in range(len(tr)):
        win = tr[max(0, i - 13):i + 1]
        atr.append(sum(win) / len(win))
    return atr


def _rolling_mean(values, window):
    out = []
    s = 0.0
    for i, v in enumerate(values):
        s += v
        if i >= window:
            s -= values[i - window]
        out.append(s / window if i >= window - 1 else None)
    return out


def _support_resistance_py(df):
    """筹码分布（换手率衰减）→ POC + 高价密区（复刻 tickflow 算法）。"""
    n = len(df)
    if n < 20:
        return []
    close, high, low, _, volume, sell = _columns(df)
    hi, lo = max(high), min(low)
    if not (hi > lo > 0):
        return []
    bins = 40
    step = (hi - lo) / bins
    edges = [lo + i * step for i in range(bins + 1)]
    chips = [0.0] * bins
    for i in range(n):
        t = sell[i]
        decay = 1.0 - max(0.0, min(t, 100.0)) / 100.0
        if decay < 1.0:
            for k in range(bins):
                chips[k] *= decay
        v = volume[i]
        if v > 0:
            k_low = min(int((low[i] - lo) / step), bins - 1)
            k_high = min(int((high[i] - lo) / step), bins - 1)
            if k_low > k_high:
                k_low, k_high = k_high, k_low
            if k_high < 0 or k_low >= bins:
                continue
            k_low = max(k_low, 0)
            k_high = min(k_high, bins - 1)
            share = v / (k_high - k_low + 1)
            for k in range(k_low, k_high + 1):
                chips[k] += share
    bin_ids = [k for k in range(bins) if chips[k] > 0]
    if not bin_ids:
        return []
    vals = [chips[k] for k in bin_ids]
    mean_val = sum(vals) / len(vals)
    cur_close = close[-1]

    def mid(k):
        return (edges[k] + edges[k + 1]) / 2

    out = []
    poc_pos = max(range(len(vals)), key=lambda i: vals[i])
    poc_mid = mid(bin_ids[poc_pos])
    out.append({"value": round(poc_mid, 2), "label": "成交密集区(POC)",
                "type": "sr", "side": _side(poc_mid, cur_close), "strength": "strong"})
    candidates = [(i, v) for i, v in enumerate(vals) if v > mean_val and i != poc_pos]
    candidates.sort(key=lambda x: x[1], reverse=True)
    for i, _ in candidates[:2]:
        m = mid(bin_ids[i])
        out.append({"value": round(m, 2), "label": "成交密集区",
                    "type": "sr", "side": _side(m, cur_close), "strength": "medium"})
    return out


def _pivot_points_py(df):
    if not df:
        return []
    close, high, low, _, _, _ = _columns(df)
    h, l, c = high[-1], low[-1], close[-1]
    if not (_ok(h) and _ok(l) and _ok(c)):
        return []
    p = (h + l + c) / 3
    r1, s1 = 2 * p - l, 2 * p - h
    r2, s2 = p + (h - l), p - (h - l)
    r3 = h + 2 * (p - l)
    s3 = l - 2 * (h - p)

    def lv(v, label, side, strength, rank):
        return {"value": round(v, 2), "label": label, "type": "pivot",
                "side": side, "strength": strength, "rank": rank}

    return [
        lv(p, "枢轴位 P", "neutral", "strong", 0),
        lv(r1, "压力位 R1", "resistance", "medium", 1),
        lv(r2, "压力位 R2", "resistance", "medium", 2),
        lv(r3, "压力位 R3", "resistance", "weak", 3),
        lv(s1, "支撑位 S1", "support", "medium", 1),
        lv(s2, "支撑位 S2", "support", "medium", 2),
        lv(s3, "支撑位 S3", "support", "weak", 3),
    ]


def _extreme_levels_py(df):
    """前高前低：60/250 日极值 + 近期 swing 高低点（复刻）。"""
    if not df:
        return []
    close, high, low, _, _, _ = _columns(df)
    n = len(df)
    out = []
    for window in (60, 250):
        if n < window:
            continue
        sub_h = high[-window:]
        sub_l = low[-window:]
        if _ok(max(sub_h)):
            out.append({"value": round(max(sub_h), 2), "label": f"{window}日新高",
                        "type": "extreme", "side": "resistance", "strength": "strong"})
        if _ok(min(sub_l)):
            out.append({"value": round(min(sub_l), 2), "label": f"{window}日新低",
                        "type": "extreme", "side": "support", "strength": "strong"})

    win = 5
    if n > win * 2:
        swing_h, swing_l = [], []
        for i in range(win, n - win):
            if high[i] == max(high[i - win:i + win + 1]):
                swing_h.append(float(high[i]))
            if low[i] == min(low[i - win:i + win + 1]):
                swing_l.append(float(low[i]))
        cur_close = close[-1]
        agg_h = [v for v in _aggregate_levels(swing_h, 0.01) if v > cur_close * 1.001]
        agg_h.sort(key=lambda v: abs(v - cur_close))
        for v in agg_h[:2]:
            out.append({"value": round(v, 2), "label": "前高",
                        "type": "extreme", "side": "resistance", "strength": "medium"})
        agg_l = [v for v in _aggregate_levels(swing_l, 0.01) if v < cur_close * 0.999]
        agg_l.sort(key=lambda v: abs(v - cur_close))
        for v in agg_l[:2]:
            out.append({"value": round(v, 2), "label": "前低",
                        "type": "extreme", "side": "support", "strength": "medium"})
    return out


def _boll_channel_py(df):
    close, high, low, _, _, _ = _columns(df)
    if len(close) < 20:
        return []
    cur_close = close[-1]
    w = close[-20:]
    ma = sum(w) / 20
    var = sum((x - ma) ** 2 for x in w) / 20
    sd = math.sqrt(var)
    out = [
        {"value": round(ma + 2 * sd, 2), "label": "布林上轨", "type": "boll",
         "side": _side(ma + 2 * sd, cur_close), "strength": "medium"},
        {"value": round(ma - 2 * sd, 2), "label": "布林下轨", "type": "boll",
         "side": _side(ma - 2 * sd, cur_close), "strength": "medium"},
        {"value": round(ma, 2), "label": "布林中轨", "type": "boll",
         "side": _side(ma, cur_close), "strength": "medium"},
    ]
    return out


def _keltner_band_py(df, window, n, label_short, type_key):
    close, high, low, _, _, _ = _columns(df)
    if len(close) < max(window, 20):
        return []
    mav = _rolling_mean(close, window)[-1]
    atr = _atr_14(high, low, close)[-1]
    cur_close = close[-1]
    if mav is None or not (_ok(mav) and _ok(atr)):
        return []
    upper, lower = mav + n * atr, mav - n * atr
    return [
        {"value": round(upper, 2), "label": f"{label_short}通道上轨",
         "type": type_key, "side": _side(upper, cur_close), "strength": "medium"},
        {"value": round(lower, 2), "label": f"{label_short}通道下轨",
         "type": type_key, "side": _side(lower, cur_close), "strength": "medium"},
    ]


def _atr_stops_py(df):
    close, high, low, _, _, _ = _columns(df)
    if not df:
        return []
    c, atr = close[-1], _atr_14(high, low, close)[-1]
    if not (_ok(c) and _ok(atr)):
        return []

    def lv(v, label, side, strength):
        return {"value": round(v, 2), "label": label, "type": "atr_stop",
                "side": side, "strength": strength}

    return [
        lv(c + 2 * atr, "ATR 上轨(+2)", "resistance", "medium"),
        lv(c + 1.5 * atr, "ATR 上轨(+1.5)", "resistance", "weak"),
        lv(c - 1.5 * atr, "ATR 下轨(-1.5)", "support", "weak"),
        lv(c - 2 * atr, "ATR 下轨(-2)", "support", "medium"),
    ]


def _gap_levels_py(df, lookback=120):
    if len(df) < 5:
        return []
    close, high, low, _, _, _ = _columns(df)
    sub = df[-lookback:] if len(df) > lookback else df
    hi = [float(r["high"]) for r in sub]
    lo = [float(r["low"]) for r in sub]
    cur_close = close[-1]
    up_gaps, dn_gaps = [], []
    for i in range(1, len(hi)):
        if _ok(hi[i]) and _ok(lo[i]) and _ok(hi[i - 1]) and _ok(lo[i - 1]):
            if lo[i] > hi[i - 1]:
                up_gaps.append((i, float(hi[i - 1]), float(lo[i])))
            elif hi[i] < lo[i - 1]:
                dn_gaps.append((i, float(hi[i]), float(lo[i - 1])))

    def filter_unfilled(gaps):
        mids = []
        for i, g_lo, g_hi in gaps:
            filled = False
            for j in range(i + 1, len(hi)):
                if lo[j] <= g_hi and hi[j] >= g_lo:
                    filled = True
                    break
            if not filled:
                mids.append((g_lo + g_hi) / 2)
        agg = _aggregate_levels(mids, 0.005)
        agg.sort(key=lambda v: abs(v - cur_close))
        return agg[:3]

    out = []
    for mid in filter_unfilled(up_gaps):
        out.append({"value": round(mid, 2), "label": "向上缺口",
                    "type": "gap", "side": _side(mid, cur_close), "strength": "medium"})
    for mid in filter_unfilled(dn_gaps):
        out.append({"value": round(mid, 2), "label": "向下缺口",
                    "type": "gap", "side": _side(mid, cur_close), "strength": "medium"})
    return out


def _fibonacci_levels_py(df, window=120):
    if len(df) < 10:
        return []
    close, high, low, _, _, _ = _columns(df)
    sub = df[-window:] if len(df) > window else df
    hi = [float(r["high"]) for r in sub]
    lo = [float(r["low"]) for r in sub]
    cur_close = close[-1]
    hi_pos = hi.index(max(hi))
    lo_pos = lo.index(min(lo))
    hi_val, lo_val = float(max(hi)), float(min(lo))
    if not (_ok(hi_val) and _ok(lo_val)) or hi_val <= lo_val:
        return []
    ratios = [0.236, 0.382, 0.5, 0.618, 0.786]
    rng = hi_val - lo_val
    up_trend = hi_pos > lo_pos
    out = []
    for r in ratios:
        val = hi_val - rng * r if up_trend else lo_val + rng * r
        out.append({"value": round(val, 2), "label": f"Fib {r * 100:.1f}%",
                    "type": "fib", "side": _side(val, cur_close), "strength": "medium"})
    return out


def _round_numbers_py(df, pct=0.10, max_count=8):
    if not df:
        return []
    close = float(df[-1]["close"])
    if not _ok(close):
        return []
    if close < 10:
        step = 0.5
    elif close < 20:
        step = 1.0
    elif close < 100:
        step = 5.0
    elif close < 500:
        step = 10.0
    else:
        step = 50.0
    lo, hi = close * (1 - pct), close * (1 + pct)
    start = (int(lo / step) + (1 if lo % step > 0 else 0)) * step
    cands, v = [], start
    while v <= hi:
        if v > 0:
            cands.append(round(v, 2))
        v += step
    cands.sort(key=lambda x: abs(x - close))
    out = []
    for v in cands[:max_count]:
        if abs(v - close) / close < 0.01:
            continue
        out.append({"value": round(v, 2), "label": f"整数关口 {v:g}",
                    "type": "round", "side": _side(v, close), "strength": "weak"})
    return out


def compute_levels(df: list[dict]) -> dict[str, list[dict]]:
    """复刻 tickflow compute_levels：对 OHLCV dict 列表算 11 类价位。"""
    try:
        return {
            "sr": _support_resistance_py(df),
            "pivot": _pivot_points_py(df),
            "extreme": _extreme_levels_py(df),
            "boll": _boll_channel_py(df),
            "keltner_s": _keltner_band_py(df, 20, 2.0, "短期", "keltner_s"),
            "keltner_m": _keltner_band_py(df, 60, 2.5, "中期", "keltner_m"),
            "keltner_l": _keltner_band_py(df, 120, 3.0, "长期", "keltner_l"),
            "atr_stop": _atr_stops_py(df),
            "gap": _gap_levels_py(df),
            "fib": _fibonacci_levels_py(df),
            "round": _round_numbers_py(df),
        }
    except Exception:  # noqa: BLE001 —— 复刻容错：任何一处失败只影响该类点位
        return {k: [] for k in LEVEL_TYPES}


def summarize_levels(levels: dict[str, list[dict]], close: float | None) -> str:
    """复刻 tickflow summarize_levels：紧凑文本摘要。"""
    if not close:
        return "无价位数据"
    parts = [f"当前价 {close:.2f}"]
    for key, label in LEVEL_TYPES.items():
        pts = levels.get(key, [])
        if not pts:
            continue
        ranked = sorted(pts, key=lambda p: abs(p["value"] - close))[:2]
        desc = "、".join(f"{p['label']}={p['value']}" for p in ranked)
        parts.append(f"{label}: {desc}")
    return " · ".join(parts)


def defense_summary(levels: dict[str, list[dict]], close: float | None) -> dict:
    """关键防线位（止损锚）摘要：只摘 DEFENSE_KEYS（前高前低 / pivot / ATR 通道）。

    返回结构：
      {"close": float, "support_anchor": float|None, "resistance_anchor": float|None,
       "atr": float|None, "summary": str(文本), "one_liner": str(一句话说明)}
    """
    if not close:
        return {"close": None, "support_anchor": None, "resistance_anchor": None,
                "atr": None, "summary": "无价位数据", "one_liner": ""}
    line_parts = []
    for key in DEFENSE_KEYS:
        pts = levels.get(key, [])
        if not pts:
            continue
        ranked = sorted(pts, key=lambda p: abs(p["value"] - close))[:2]
        line_parts.append(f"{LEVEL_TYPES[key]}：" + "、".join(
            f"{p['label']}={p['value']}" for p in ranked
        ))

    # 止损锚：最接近且低于现价的 support 点（距离优先 = 机械止损规则，跌破最近支撑即离场）
    supports = []
    for key in DEFENSE_KEYS:
        for p in levels.get(key, []):
            if p["side"] == "support":
                supports.append(p)
    supports.sort(key=lambda p: (abs(p["value"] - close),
                                 0 if p["strength"] == "strong" else
                                 1 if p["strength"] == "medium" else 2))
    support_anchor = supports[0]["value"] if supports else None

    resistances = []
    for key in DEFENSE_KEYS:
        for p in levels.get(key, []):
            if p["side"] == "resistance":
                resistances.append(p)
    resistances.sort(key=lambda p: (abs(p["value"] - close),
                                    0 if p["strength"] == "strong" else
                                    1 if p["strength"] == "medium" else 2))
    resistance_anchor = resistances[0]["value"] if resistances else None

    atr = None
    pts_a = levels.get("atr_stop", [])
    if pts_a and close:
        # 从 ATR 下轨反推单倍 ATR ≈ (close - 下轨数对应) —— 直接用 -2 档一半近似
        for p in pts_a:
            if p["label"] == "ATR 下轨(-2)":
                atr = round((close - p["value"]) / 2, 2)
                break

    one_liner = build_one_liner(close, support_anchor, resistance_anchor, atr)
    return {
        "close": round(close, 2),
        "support_anchor": support_anchor,
        "resistance_anchor": resistance_anchor,
        "atr": atr,
        "summary": "；".join(line_parts),
        "one_liner": one_liner,
    }


def build_one_liner(close: float, support: float | None, resistance: float | None, atr: float | None) -> str:
    """一句话说明（进决策卡结构行）：止损锚 = 最近强支撑下方，跌破即结构证伪。"""
    parts = [f"现价 {close:.2f}"]
    if support is not None:
        parts.append(f"关键防线位/止损锚 {support:.2f}（最近支撑，跌破即结构证伪，无条件执行）")
    else:
        parts.append("关键防线位/止损锚：暂无近端支撑（需人工按前低补设）")
    if resistance is not None:
        parts.append(f"第一压力 {resistance:.2f}")
    if atr is not None:
        parts.append(f"单倍ATR≈{atr:.2f}（约现价{atr / close * 100:.1f}%，供分批止盈间距参考）")
    return "；".join(parts) + "。"


def _read_ohlcv(path):
    """读本地 OHLCV：CSV（逗号/制表/分号分隔，含表头）或 JSON（数组/包壳）。"""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return None, f"文件不存在: {path}"
    if path.lower().endswith((".json", ".jsonl")):
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
        if isinstance(obj, dict):
            for key in ("data", "records", "items", "kline", "rows", "list"):
                if isinstance(obj.get(key), list):
                    obj = obj[key]
                    break
        if not isinstance(obj, list) or not obj:
            return None, "JSON 需为数组（每条含 open/high/low/close/volume）或带 data/records 包壳"
        return obj, None
    # CSV
    import csv
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        sample = f.read(2048)
        f.seek(0)
        sniffer = csv.Sniffer()
        try:
            dialect = sniffer.sniff(sample, delimiters=",\t;")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(f, dialect=dialect)
        for r in reader:
            rows.append({(k.strip().lower()): v.strip() for k, v in r.items()})
    aliases = {"c": "close", "o": "open", "h": "high", "l": "low", "v": "volume", "turn": "turnover_rate"}
    norm = []
    for r in rows:
        d = {}
        for k, v in r.items():
            key = aliases.get(k, k.lower())
            if key in ("open", "high", "low", "close", "volume", "turnover_rate"):
                try:
                    d[key] = float(v)
                except (TypeError, ValueError):
                    d[key] = None
        if d.get("high") and d.get("low") and d.get("close"):
            norm.append(d)
    if not norm:
        return None, "CSV 需含表头列：open,high,low,close（volume/turnover_rate 可选）"
    return norm, None


def cmd_t2(args) -> int:
    ticker = (args.ticker or "").upper()
    print(f"fengtick T2 — 防线位摘要（止损锚）  {ticker or ''}".strip())
    if not args.file:
        print("  ❌ 缺少 OHLCV 数据。用法：")
        print("     python tools/fengtick.py t2 <TICKER> --file <ohlcv.csv|json>")
        print("     CSV 表头: date,open,high,low,close,volume,turnover_rate（后两列可选）")
        print("     数据纯本地读取；可用 fengdata/行情工具导出，或 tickflow 导出 K 线 JSON。")
        return 1
    df, err = _read_ohlcv(args.file)
    if err:
        print(f"  ❌ {err}")
        return 1
    close = float(df[-1]["close"])
    levels = compute_levels(df)
    if args.json:
        payload = {"ticker": ticker, **defense_summary(levels, close)}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    ds = defense_summary(levels, close)
    print(f"  K线根数: {len(df)}  现价: {close:.2f}")
    print()
    print("  【防线位摘要】（前高前低 / 枢轴 / ATR 通道）")
    for key in DEFENSE_KEYS:
        pts = levels.get(key, [])
        if not pts:
            print(f"    - {LEVEL_TYPES[key]}: （数据不足或无）")
            continue
        for p in pts:
            mark = " ← 压力" if p["side"] == "resistance" else " ← 支撑" if p["side"] == "support" else ""
            print(f"    - {p['label']:<10} = {p['value']:<10} [{p['strength']}]{mark}")
    print()
    print("  【完整摘要】")
    print("    " + ds["summary"])
    print()
    print("  【一句话说明】")
    print("    " + ds["one_liner"])
    print()
    print("  【进决策卡】")
    print(f"    结构(T2)：右侧信号 n/4 ｜ 关键防线位 {ds['support_anchor'] or '—'} ｜ 假突破 否")
    return 0


# ================================================================
# T4 —— 监控信号接入说明（仅文档，不改 fengwatch.py）
# ================================================================

_T4_DOC = """\
fengtick T4 — tickflow 监控信号 → fengwatch 接入说明（仅文档，不修改任何文件）

现状：
  - fengwatch.py 是 FengInvest 持仓监控引擎（daily/check/sell），消费
    holdings/hold_*.json 与 alerts/today.json，不感知 tickflow。
  - tickflow 是侧车：它的告警流落在 {tf}/data/user_data/alerts.jsonl（T0 已会读）。

幽灵原则：tickflow 只供"监控信号数据"，纪律（T3 铁律、止损咬死）与卖出（T5）留 FengInvest。

接入方式（三选一，均不改 fengwatch.py）：
  1) 人工对照（零改代码，最稳）
     - 每日跑 `python tools/fengwatch.py daily`（TRADING -20% 机械止损已强制）。
     - 另跑 `python tools/fengtick.py t0`，把 tickflow 当日新增触发的标的，
       与 fengwatch 监控点列表人工比对（止损线 / 结构证伪 / 事件兑现 / 滚存线 / 时间窗）。
  2) 信号落盘（推荐）
     - 在 tickflow 侧把当日触发的监控信号导出为 {tf}/data/signals/*.json
       （每条含 symbol + event + trigger_type），再由 fengtick T0 聚合到
       research/speculative/<日期>-candidates.json。
     - fengwatch 的后续版本可（届时另行评估）读该文件核对 T4 监控点；本版本不做，也不改 fengwatch.py。
  3) alerts.jsonl 直读
     - `python tools/fengtick.py t0` 已自动解析 {tf}/data/user_data/alerts.jsonl；
       当日有触发的标的会进 candidates.json，作为 T4 监控的"外部信号清单"。

边界：
  - 本命令不写盘、不联网、不启动 tickflow 服务器、不 import tickflow 代码。
  - 止损/卖出动作永远由 fengexit/fengwatch 执行，tickflow 信号只做参考输入。
"""


def cmd_t4(_args) -> int:
    print(_T4_DOC.format(tf=TICKFLOW_DEFAULT_DIR))
    return 0


# ================================================================
# CLI
# ================================================================

def parse_date(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        print(f"❌ 日期格式应为 YYYY-MM-DD: {s}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(prog="fengtick.py",
                                     description="FengInvest ←→ tickflow 侧车薄桥（T0/T2/T4，纯本地）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p0 = sub.add_parser("t0", help="T0 触发：聚合 tickflow data/ 扫描结果 → candidates.json")
    p0.add_argument("--date", default=None, help="产物日期（YYYY-MM-DD，默认今天）")
    p0.add_argument("--tickflow-dir", default=None, help="tickflow 仓库根目录（默认自动探测）")
    p0.add_argument("--json", action="store_true", help="只打印探测到的源文件路径(JSON)")

    p2 = sub.add_parser("t2", help="T2 结构：防线位摘要（止损锚）")
    p2.add_argument("ticker", help="标的代码")
    p2.add_argument("--file", default=None, help="本地 OHLCV CSV/JSON 路径")
    p2.add_argument("--json", action="store_true", help="JSON 输出防线位摘要")

    sub.add_parser("t4", help="T4 监控：tickflow→fengwatch 接入说明（仅文档）")

    args = parser.parse_args()
    if args.cmd == "t0":
        day = parse_date(args.date) if args.date else date.today()
        args.date = day
        sys.exit(cmd_t0(args))
    elif args.cmd == "t2":
        sys.exit(cmd_t2(args))
    else:
        sys.exit(cmd_t4(args))


if __name__ == "__main__":
    main()
