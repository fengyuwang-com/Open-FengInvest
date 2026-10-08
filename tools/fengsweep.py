#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fengsweep — 零输入发现协议的游标引擎（路径 1「需求锚定」程序化）。

对应《research/120-idea-sourcing/SWEEP-PROTOCOL.md》与格子表
data/config/needs_grid.json（创始人 2026-09-26 批准「就这么办」）。

一句话：什么都不说时，prompt 换成「一张需求表 + 一个游标 + 一套不变规则」。
接力扫描一次领一格（格子 × 市场），出候选卡或贫瘠记录，游标永远向前，
可复现、可审计——用确定性覆盖压过 AI 好奇心（防英文偏好/龙头偏好/筛子偏好）。

铁律（同 fengsource.py）：
  - 状态即台账：无独立状态文件，sweep.jsonl 顺序重放 = 当前游标。只追加，不覆盖。
  - 排序器不是筛子：本工具产出的 top-N 只是「先看谁」，被排序否掉 ≠ 排除出研究
    （2026-09-20 创始人裁定：闸门只许排序/标记，不许排除任何公司）。
  - ABSTAIN 出声：格子里算不出/查不到，必须留 barren 记录并写明原因，
    不许静默跳过，不许用默认值冒充结论。
  - 本工具只管游标与排序，绝不替代闸门 0/1/2 与七层分析。

CLI:
  python tools/fengsweep.py grid                        # 格子表体检（完整性/ID 唯一性）
  python tools/fengsweep.py status                      # 游标现状 + 覆盖率
  python tools/fengsweep.py next [--market CN]          # 本轮该扫的格子（含生意问句与数据通道）
  python tools/fengsweep.py record --cell needs-001 --market CN \
      --outcome candidates|barren --note "..." [--tickers 600519.SS,000858.SZ]
  python tools/fengsweep.py cursor --set 60 --market HK # 游标手动校正（创始人/巡检用）

退出码（与 tools/ 下其他工具一致）:
  0 = 成功；2 = 用法错误 / 校验失败
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import date

# 原生 GBK 控制台防崩（与 fengdoclint/fengadopt 等工具同款处理）
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GRID = os.path.join(ROOT, "data", "config", "needs_grid.json")
GLOBAL_MAP = os.path.join(ROOT, "data", "config", "sw_global_map.json")
LEDGER = os.path.join(ROOT, "research", "120-idea-sourcing", "sweep.jsonl")
POOL = os.path.join(ROOT, "research", "120-idea-sourcing", "pool")
REJECTED = os.path.join(ROOT, "research", "120-idea-sourcing", "rejected")
DB = os.path.join(ROOT, "data", "market_data.db")

OUTCOMES = ("candidates", "barren")
# 覆盖率分子只算 active 格子；retired 格子保留在表里但游标跳过
VALID_STATUS = ("active", "retired")
# 排序器参排门槛（2026-09-26 修复短历史偏差）：年度毛利率点 < 5 不参排——
# 新上市公司只有 3-4 年数据，天生极差小，曾把 3 年新股排到海天（10 年 11.7pp）之上。
# 不参排 ≠ 排除：它们计入 short_history 提示，走 AI 常识名单/人工闸门（排序器不筛人）。
MIN_RANK_YEARS = 5


def _trend_resid_std(points: list[tuple[int, float]]) -> float:
    """趋势残差标准差：毛利率围绕自身线性趋势的波动（pp）。

    科学性（2026-09-26 方法第五修）：极差把「单调改善」（NVDA 58%→75%）与
    「周期震荡」混为一谈；残差 std 只罚震荡不罚趋势，是「稳」的正确度量。
    点数 <3 返回 inf（不可得 → 不用稳度区分，退回年限键）。
    """
    if len(points) < 3:
        return float("inf")
    xs = [float(y) for y, _ in points]
    ys = [g for _, g in points]
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    slope = (sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den) if den else 0.0
    resid = [y - (my + slope * (x - mx)) for x, y in zip(xs, ys)]
    return (sum(r * r for r in resid) / n) ** 0.5


def _lane_select(scored: list[dict], top_n: int) -> list[dict]:
    """双梯队出榜（2026-09-26 四修，创始人哲学落地）。

    单一排序键「谷底年盈利✓优先」会把深周期公司（NVDA/MU 曾在金融危机年亏损）
    永远压出前 N——但「周期性公司在周期底部可以研究」（创始人 2026-09-20），
    它们必须以带周期标记的身份进入视野。故分两梯队：
      稳健梯队 = 窗口内从未亏损（同键内排：年限深 > 极差小）
      深周期梯队 = 曾亏损（同键内排；出榜后由周期闸打 CYCLIC 标记）
    每格 top_n 名额按前多后少分配（top3 = 稳健 2 + 深周期 1）。
    """
    lane_a = sorted((x for x in scored if x["worst_year_profitable"]),
                    key=lambda x: (-x["years"], x.get("resid_std", float("inf"))))
    lane_b = sorted((x for x in scored if not x["worst_year_profitable"]),
                    key=lambda x: (-x["years"], x.get("resid_std", float("inf"))))
    n_a = min(len(lane_a), (top_n + 1) // 2)
    picked = [{**x, "lane": "稳健"} for x in lane_a[:n_a]] \
        + [{**x, "lane": "深周期"} for x in lane_b[:top_n - n_a]]
    return picked


# ── 格子表 ────────────────────────────────────────────────────────────────

def load_grid() -> dict:
    with open(GRID, "r", encoding="utf-8") as f:
        return json.load(f)


def grid_health(grid: dict) -> list[str]:
    """结构体检，返回问题清单（空 = 健康）。"""
    problems = []
    cells = grid.get("cells", [])
    ids = [c.get("id", "") for c in cells]
    if len(set(ids)) != len(ids):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        problems.append(f"格子 ID 重复: {dupes}")
    for c in cells:
        cid = c.get("id", "?")
        if c.get("status") not in VALID_STATUS:
            problems.append(f"{cid}: status 非法（{c.get('status')!r}，须为 {VALID_STATUS}）")
        for key in ("need", "domain", "guiding_questions"):
            if not str(c.get(key, "")).strip():
                problems.append(f"{cid}: 缺 {key}")
    return problems


# ── 台账（状态即台账：重放 = 游标） ────────────────────────────────────────

def read_ledger() -> list[dict]:
    if not os.path.exists(LEDGER):
        return []
    out = []
    with open(LEDGER, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                out.append(json.loads(ln))
            except json.JSONDecodeError:
                out.append({"_bad_line": ln})
    return out


def scanned_mark(ledger: list[dict]) -> set[tuple[str, str]]:
    """已扫过的 (cell, market)。重复记录视为重复扫（容错，不算错误）。"""
    return {(r["cell"], r["market"]) for r in ledger
            if "cell" in r and "market" in r}


def active_cells(grid: dict) -> list[dict]:
    return [c for c in grid.get("cells", []) if c.get("status") == "active"]


def markets(grid: dict) -> list[str]:
    return grid.get("_markets", ["CN", "HK", "US", "KR", "JP"])


# ── DB 排序器（只排序，不筛人） ───────────────────────────────────────────

SW_CACHE = os.path.join(ROOT, "data", "cache", "sw_cons_cache.json")


def _sw_members(sw_codes: list[str], notes: list[str]) -> tuple[list[tuple[str, str]], str]:
    """取申万二级行业成分（带本地缓存，按月新鲜）。

    返回 ([(stkcd, name)], 来源描述)。失败不抛异常：返回空列表 + note，
    调用方降级关键词兜底。纯关键词会漏“名字不带行业字”的龙头
    （伊利教训：行业标注=食品制造业，名字无乳/奶），sw_codes 是主通道。
    """
    if not sw_codes:
        return [], ""
    cache: dict = {}
    if os.path.exists(SW_CACHE):
        try:
            with open(SW_CACHE, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except (OSError, json.JSONDecodeError):
            cache = {}
    today = date.today().isoformat()
    members: list[tuple[str, str]] = []
    stale: list[str] = []
    for code in sw_codes:
        ent = cache.get(code)
        if ent and str(ent.get("fetched", ""))[:7] == today[:7]:  # 按月新鲜
            members.extend((m[0], m[1]) for m in ent.get("members", []))
        else:
            stale.append(code)
    if stale:
        try:
            import akshare as ak
            for code in stale:
                df = ak.index_component_sw(symbol=code)
                rows = []
                for _, r in df.iterrows():
                    c6 = str(r.iloc[1]).strip().zfill(6)
                    nm = str(r.iloc[2]).strip()
                    if c6.isdigit():
                        rows.append([c6, nm])
                cache[code] = {"fetched": today, "members": rows}
                members.extend((m[0], m[1]) for m in rows)
            os.makedirs(os.path.dirname(SW_CACHE), exist_ok=True)
            with open(SW_CACHE, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False, indent=1)
        except Exception as e:
            notes.append(f"申万成分拉取失败（{type(e).__name__}），降级关键词兜底")
            return [], ""
    return members, f"申万二级行业成分 {','.join(sw_codes)}（akshare index_component_sw，缓存按月刷新）"


def rank_candidates(cell: dict, market: str, top_n: int = 5) -> dict:
    """在「市场 × 格子」内给出生意质量排序的候选（top-N 仅是先看谁）。

    排序口径（十年生意质量，全部来自本地库，缺数据 = 不参排，不猜）：
      CN: cn_financials 毛利率极差（小 = 稳）+ 最差年归母净利为正
      其他市场: 本地库暂无多年财务序列（已知缺口，见 SWEEP-PROTOCOL §局限）
        → ABSTAIN + 返回该市场的股票名单样本（由 AI 人工走闸门）
    """
    hints = cell.get("industry_hints", [])
    result: dict = {"mode": None, "candidates": [], "notes": []}

    if not os.path.exists(DB):
        result["mode"] = "ABSTAIN"
        result["notes"].append("本地库 data/market_data.db 不存在，无法排序 → 全部走人工闸门")
        return result

    sw_codes = cell.get("sw_codes") or []
    if not sw_codes and not hints:
        result["mode"] = "ABSTAIN"
        result["notes"].append("格子缺 sw_codes 与 industry_hints，排序器无从定位行业 → 走人工闸门")
        return result

    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=15)
    try:
        if market == "CN":
            # 行业成员三级定位（2026-09-26 三修）：① 申万成分（sw_codes 主通道）
            # ② 关键词 LIKE 兜底（sw 拉取失败/格子未配码）。
            members, member_src = _sw_members(sw_codes, result["notes"])
            if not members:
                conds, params = [], []
                for h in hints:
                    conds.append("short_name LIKE ?")
                    params.append(f"%{h}%")
                    conds.append("industry_csrc_name LIKE ?")
                    params.append(f"%{h}%")
                sql = (f"SELECT stkcd, short_name, MAX(accper) FROM cn_financials "
                       f"WHERE typrep='A' AND ({' OR '.join(conds)}) GROUP BY stkcd LIMIT 400")
                try:
                    rows = conn.execute(sql, params).fetchall()
                    members = [(r[0], r[1]) for r in rows]
                    member_src = f"关键词检索（hints={hints}，兜底通道）"
                except sqlite3.Error as e:
                    result["mode"] = "ABSTAIN"
                    result["notes"].append(f"名称检索失败（{e}），排序器 ABSTAIN → 走人工闸门")
                    return result
            if not members:
                result["mode"] = "ABSTAIN"
                result["notes"].append(
                    "申万成分与关键词检索均零命中——可能是该格子在 A 股无纯标的；"
                    "如实写进贫瘠记录，不许静默跳格")
                return result
            result["notes"].insert(0, f"行业成员来源: {member_src}（去重前 {len(members)} 家）")
            scored = []
            short_history: list[str] = []
            seen: set[str] = set()
            for stkcd, name in members:
                if stkcd in seen:
                    continue
                seen.add(stkcd)
                ticker = stkcd + (".SS" if stkcd.startswith(("6", "9", "5")) else ".SZ")
                fin = conn.execute(
                    """SELECT accper, if_correct, gross_margin, parent_net_profit
                       FROM cn_financials
                       WHERE stkcd=? AND typrep='A' AND accper LIKE '%-12-31'
                       ORDER BY accper DESC LIMIT 24""",
                    (stkcd,)).fetchall()
                # 同年多版本时优先 if_correct=0（与 fengsource 口径一致）
                by_year: dict[str, tuple] = {}
                for acc, ic, gm, np_ in fin:
                    if acc not in by_year or (by_year[acc][1] and not ic):
                        by_year[acc] = (acc, ic, gm, np_)
                recents = sorted(by_year.values(), key=lambda r: r[0], reverse=True)[:10]
                gms = [r[2] for r in recents if r[2] is not None]
                profits = [r[3] for r in recents if r[3] is not None]
                if len(gms) < MIN_RANK_YEARS:
                    # 短历史不参排（不判负）：新上市公司天生极差小，会污染排序
                    if gms:
                        short_history.append(f"{name}({len(gms)}年)")
                    continue
                rng = (max(gms) - min(gms)) * 100
                gm_pts = [(int(r[0][:4]), r[2]) for r in recents if r[2] is not None]
                worst_ok = (min(profits) > 0) if profits else False
                scored.append({"ticker": ticker, "name": name,
                               "gm_range_pp": round(rng, 1),
                               "resid_std": round(_trend_resid_std(gm_pts), 2),
                               "worst_year_profitable": worst_ok,
                               "years": len(gms)})
            # 排序哲学（2026-09-26 二修）：**数据年限深的先看**——10 年老兵 > 5 年次新，
            # 同深度内毛利率越稳越靠前。旧排序（纯极差）会把没经历周期的 3 年新股排到海天
            # （10 年 11.7pp）之上。排序器只定「先看谁」：年限浅的经 short_history 提示
            # 走 AI 常识名单，不排除。
            scored.sort(key=lambda x: (not x["worst_year_profitable"], -x["years"], x["gm_range_pp"]))
            picked = _lane_select(scored, top_n)
            result["mode"] = "RANKED" if picked else "ABSTAIN"
            result["candidates"] = picked
            result["members_all"] = sorted(scored, key=lambda x: (not x["worst_year_profitable"],
                                                                   -x["years"], x.get("resid_std", 0)))
            if short_history:
                result["notes"].append(
                    f"另有 {len(short_history)} 家命中但历史 <{MIN_RANK_YEARS} 年不参排（新上市非排除，走 AI 常识名单）："
                    + "、".join(short_history[:6]))
            if not scored:
                result["notes"].append(
                    f"有名称命中但无一家 ≥{MIN_RANK_YEARS} 个年度毛利率点，排序器 ABSTAIN")
            return result

        if market in ("HK", "US"):
            # 港美通道（2026-09-26 创始人指令「搞定港股和美股」）：
            # 成员 = fundamentals 行业标注（Morningstar 英文名）× sw_global_map 关键词映射，
            #   行业标注未覆盖的标的降级全池通道（备注出声，不筛人）；
            # 序列 = global_financials（fengexpand_fin_global 回填，东财源，毛利率小数刻度同 cn_financials）。
            gmap = {}
            if os.path.exists(GLOBAL_MAP):
                try:
                    with open(GLOBAL_MAP, "r", encoding="utf-8") as f:
                        gmap = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
                except (OSError, json.JSONDecodeError):
                    gmap = {}
            kw = gmap.get(str(sw_codes[0]) if sw_codes else "", []) if (sw_codes or hints) else []
            # sw_codes 可能多个：取所有映射并集
            kw = sorted({k2 for code in (sw_codes or []) for k2 in gmap.get(str(code), [])})
            if not kw:
                result["mode"] = "ABSTAIN"
                result["notes"].append(
                    f"格子 {cell['id']} 无 sw_codes 映射到英文行业关键词（sw_global_map），"
                    "港美成员定位不可用 → 走 AI 常识名单")
                return result
            like = " OR ".join(["f.industry LIKE ?"] * len(kw))
            params = [f"%{k}%" for k in kw]
            try:
                rows = conn.execute(
                    f"""SELECT i.ticker, i.name, i.market FROM indices i
                       JOIN fundamentals f ON f.index_id=i.id
                       WHERE i.market=? AND i.category='stock' AND ({like})""",
                    [market] + params).fetchall()
            except sqlite3.Error as e:
                result["mode"] = "ABSTAIN"
                result["notes"].append(f"行业成员检索失败（{e}）→ 走人工闸门")
                return result
            n_industry = len(rows)
            if n_industry < 3:
                # 2026-09-26 三修：行业命中不足时**不再降级全池**——全池会把无关行业
                # （中国中铁/江西铜业）排进调味品格子，是误导性排序。改为 ABSTAIN
                # 走 AI 常识名单（行业相关性是人的判断，不是排序器的）。
                result["mode"] = "ABSTAIN"
                result["notes"].append(
                    f"{market} 行业标注（fundamentals×sw_global_map 关键词 {kw}）仅命中 {n_industry} 家"
                    "（<3，标注覆盖不足），排序器 ABSTAIN → 走 AI 常识名单；"
                    "扩大覆盖需回填更多 fundamentals 行业标注")
                return result
            result["notes"].insert(0, f"行业成员来源: fundamentals.industry LIKE {kw}（去重前 {len(rows)} 家）")
            scored = []
            short_history: list[str] = []
            seen: set[str] = set()
            for tk, nm, mk2 in rows:
                # 同票异格式去重（HK 库里 01099.HK 与 1099.HK 并存）：取数字代码规范化
                key = tk.split(".")[0].lstrip("0") if "." in tk else tk
                if key in seen:
                    continue
                seen.add(key)
                fin = conn.execute(
                    """SELECT fiscal_year, gross_margin, net_profit FROM global_financials
                       WHERE ticker=? AND market=? ORDER BY fiscal_year DESC LIMIT 10""",
                    (tk, mk2)).fetchall()
                gms = [r[1] for r in fin if r[1] is not None]
                profits = [r[2] for r in fin if r[2] is not None]
                if len(gms) < MIN_RANK_YEARS:
                    if gms:
                        short_history.append(f"{nm or tk}({len(gms)}年)")
                    continue
                rng = (max(gms) - min(gms)) * 100
                gm_pts = [(r[0], r[1]) for r in fin if r[1] is not None]
                worst_ok = (min(profits) > 0) if profits else False
                scored.append({"ticker": tk, "name": nm or tk,
                               "gm_range_pp": round(rng, 1),
                               "resid_std": round(_trend_resid_std(gm_pts), 2),
                               "worst_year_profitable": worst_ok,
                               "years": len(gms)})
            # 同一科学键：谷底盈利✓ > 年限深 > 极差小
            picked = _lane_select(scored, top_n)
            result["mode"] = "RANKED" if picked else "ABSTAIN"
            result["candidates"] = picked
            result["members_all"] = sorted(scored, key=lambda x: (not x["worst_year_profitable"],
                                                                   -x["years"], x.get("resid_std", 0)))
            if short_history:
                result["notes"].append(
                    f"另有 {len(short_history)} 家命中但历史 <{MIN_RANK_YEARS} 年不参排（非排除）："
                    + "、".join(short_history[:6]))
            if not scored:
                result["notes"].append(
                    f"{market} 成员中无一家 ≥{MIN_RANK_YEARS} 个年度毛利率点，排序器 ABSTAIN "
                    "→ 先跑 fengexpand_fin_global 回填更多标的")
            return result

        # 其他市场（KR/JP）：本地库无多年财务序列（SWEEP-PROTOCOL §局限）
        result["mode"] = "ABSTAIN"
        result["notes"].append(
            f"{market} 市场本地库暂无多年财务序列（周期闸对非 A 股 ABSTAIN 的同一缺口），"
            "排序器不参排 → 由 AI 按当地语言搜索列观察名单后走闸门")
        return result
    finally:
        conn.close()


# ── 子命令 ────────────────────────────────────────────────────────────────

def cmd_grid(args) -> int:
    grid = load_grid()
    problems = grid_health(grid)
    cells = grid.get("cells", [])
    print(f"=== 需求格子表体检 — {GRID and os.path.relpath(GRID, ROOT)} ===")
    print(f"格子总数: {len(cells)}（active {len(active_cells(grid))} / retired {len(cells) - len(active_cells(grid))}）")
    print(f"市场: {'/'.join(markets(grid))}")
    if problems:
        print()
        for p in problems:
            print(f"  [问题] {p}")
        print("\n> 结论: 校验失败，修格子表后再扫（exit 2）")
        return 2
    print("\n> 结论: 格子表健康（ID 唯一、字段齐、status 合法）")
    return 0


def cmd_status(args) -> int:
    grid = load_grid()
    problems = grid_health(grid)
    ledger = read_ledger()
    bad = [r for r in ledger if "_bad_line" in r]
    done = scanned_mark(ledger)
    acts = active_cells(grid)
    mkts = markets(grid)
    total = len(acts) * len(mkts)
    print("=== 零输入扫描游标现状 ===")
    if problems:
        print("[警告] 格子表存在问题（跑 fengsweep.py grid 查看），以下统计按现状算")
    print(f"格子: {len(acts)} active × {len(mkts)} 市场 = {total} 格次")
    print(f"已扫: {len(done)} 格次（覆盖率 {len(done) / total * 100:.1f}%）")
    if bad:
        print(f"[警告] 台账坏行 {len(bad)} 行（保留原样，不吞错）")
    by_outcome: dict[str, int] = {}
    for r in ledger:
        o = r.get("outcome", "?")
        by_outcome[o] = by_outcome.get(o, 0) + 1
    if by_outcome:
        print("结果分布: " + " / ".join(f"{k}={v}" for k, v in sorted(by_outcome.items())))
    # 按市场的覆盖
    for m in mkts:
        n = sum(1 for c, mm in done if mm == m)
        print(f"  {m}: {n}/{len(acts)}")
    print()
    if not ledger:
        print(">> 结论: 游标在起点，一格未扫 → 跑 next 领第一格")
    else:
        print(f">> 结论: 已推进 {len(done)} 格次 → 跑 next 领下一格")
    return 0


def cmd_next(args) -> int:
    grid = load_grid()
    problems = grid_health(grid)
    if problems:
        for p in problems:
            print(f"[问题] {p}")
        print("> 格子表校验失败，先修表（exit 2）")
        return 2
    ledger = read_ledger()
    done = scanned_mark(ledger)
    acts = active_cells(grid)
    mkts = markets(grid)

    # 指定市场 → 在该市场内找第一个未扫格子；否则格子主序 × 市场序
    order = [(c, m) for c in acts for m in mkts]
    if args.market:
        mk = args.market.upper()
        if mk not in mkts:
            print(f"[ERR] 市场 {mk} 不在格子表 _markets {mkts} 里")
            return 2
        order = [(c, m) for c, m in order if m == mk]
    nxt = next(((c, m) for c, m in order if (c["id"], m) not in done), None)

    if nxt is None:
        scope = f"市场 {args.market.upper()}" if args.market else "全表"
        print(f">> {scope} 已全部扫完 → 3-6 个月后按游标重扫（格子表常数几年才改一次），"
              "或先扩充格子表/新市场")
        return 0

    cell, market = nxt
    print(f"=== 本轮扫描格子: {cell['id']} [{market}] ===")
    print(f"需求域: {cell['need']} → {cell['domain']}")
    print(f"生意问句: {cell['guiding_questions']}")
    print()
    print("流程（SWEEP-PROTOCOL，一步不可少）:")
    print("  1. 生意先行：先答生意问句（谁在满足/供给格局稳吗），不先跑指标")
    print("  2. 排序器定「先看谁」（top-N 仅排序，被否 ≠ 排除出研究）；排序器之外，"
         "按行业常识把 obvious 龙头/代表者一并列入闸门 0 观察名单——排名不是门槛，排序器漏的常识龙头照样进")
    print("  3. 闸门 0: ≥3 条带 URL 证据（主营/竞争格局/定价权）")
    print("  4. 闸门 1: python tools/fengsource.py gate <TICKER>（周期标记，非 A 股会 ABSTAIN 出声）")
    print("  5. 闸门 2: 护城河证据 ≥1 条（品牌溢价/转换成本/网络效应/规模/牌照/技术代差）")
    print("  6. 出卡 research/120-idea-sourcing/pool/<TICKER>.md 并登记 research_list.json")
    print("     或留贫瘠记录（barren，必须写明为什么贫瘠）")
    print()
    rank = rank_candidates(cell, market)
    print(f"排序器: {rank['mode']}")
    for n in rank["notes"]:
        print(f"  备注: {n}")
    for c in rank["candidates"]:
        flag = "✓" if c["worst_year_profitable"] else "?"
        print(f"  {c['ticker']:12s} {c['name']:16s} 毛利率极差 {c['gm_range_pp']:>6.1f}pp "
              f"谷底年盈利 {flag}（{c['years']} 年）")
    if rank["mode"] == "RANKED" and rank["candidates"]:
        print("  ⚠️ top-N 只是「先看谁」；闸门 0 证据不足时任何公司都不得因此被跳过")
    print()
    print(f"完成后记账: python tools/fengsweep.py record --cell {cell['id']} --market {market} "
          f"--outcome candidates|barren --note \"...\"")
    return 0


def cmd_record(args) -> int:
    grid = load_grid()
    problems = grid_health(grid)
    if problems:
        for p in problems:
            print(f"[问题] {p}")
        return 2
    cell_ids = {c["id"] for c in grid.get("cells", [])}
    if args.cell not in cell_ids:
        print(f"[ERR] 格子 {args.cell} 不在格子表（先跑 fengsweep.py grid 看合法 ID）")
        return 2
    mk = args.market.upper()
    if mk not in markets(grid):
        print(f"[ERR] 市场 {mk} 不在 _markets {markets(grid)}")
        return 2
    if args.outcome not in OUTCOMES:
        print(f"[ERR] outcome 须为 {'/'.join(OUTCOMES)}")
        return 2
    if args.outcome == "barren" and not (args.note or "").strip():
        print("[ERR] barren 必须写明为什么贫瘠（--note），不许静默跳格")
        return 2
    if (args.cell, mk) in scanned_mark(read_ledger()):
        print("[警告] 该格次已扫过：本次为重复记录（append-only 照记不覆盖，游标不受影响；"
              "若为误操作请留 note 说明，由巡检轮清理）")
    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()] if args.tickers else []

    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    rec = {
        "date": date.today().isoformat(),
        "cell": args.cell,
        "market": mk,
        "outcome": args.outcome,
        "tickers": tickers,
        "note": args.note,
        "by": args.by,
    }
    with open(LEDGER, "a", encoding="utf-8") as f:  # 只追加，不覆盖
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"[sweep] + {rec['date']} {rec['cell']} [{mk}] → {rec['outcome']}"
          + (f" ({len(tickers)} 只: {', '.join(tickers[:5])}{'...' if len(tickers) > 5 else ''})" if tickers else ""))
    if args.note:
        print(f"        note: {args.note}")
    print(f"        台账: {os.path.relpath(LEDGER, ROOT)}（append-only，状态即台账）")
    return 0


def cmd_cursor(args) -> int:
    """游标手动校正：在台账里追加一条 cursor_override，next/status 把该格次视为已扫。"""
    grid = load_grid()
    cell_ids = {c["id"] for c in grid.get("cells", [])}
    if args.set not in cell_ids:
        print(f"[ERR] 格子 {args.set} 不在格子表")
        return 2
    mk = args.market.upper()
    if mk not in markets(grid):
        print(f"[ERR] 市场 {mk} 不在 _markets {markets(grid)}")
        return 2
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    rec = {
        "date": date.today().isoformat(),
        "cell": args.set,
        "market": mk,
        "outcome": "cursor_override",
        "tickers": [],
        "note": args.note or "游标手动校正",
        "by": args.by,
    }
    with open(LEDGER, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"[cursor] 游标校正: {args.set} [{mk}] 记为已过（override，不覆盖历史）")
    return 0


# ── batch 子命令：全格子批量排序（2026-09-26 创始人授权） ─────────────────

def _global_gate(ticker: str, market: str) -> dict:
    """HK/US 周期闸：global_financials 序列按 fengsource 同阈值复算
    （B: 近10年毛利率极差>15pp；C: 谷底亏损）。阈值不新增自由度。"""
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=15)
    try:
        rows = conn.execute(
            "SELECT fiscal_year, gross_margin, net_profit FROM global_financials "
            "WHERE ticker=? AND market=? ORDER BY fiscal_year DESC LIMIT 10",
            (ticker, market)).fetchall()
    finally:
        conn.close()
    gms = [r[1] for r in rows if r[1] is not None]
    profs = [r[2] for r in rows if r[2] is not None]
    base: dict = {"judge_B": {"status": "ABSTAIN"}, "judge_C": {"status": "ABSTAIN"},
                  "hits": [], "notes": []}
    if len(gms) < MIN_RANK_YEARS:
        base["verdict"] = "ABSTAIN"
        base["notes"].append(f"global_financials 年度点 {len(gms)} <{MIN_RANK_YEARS}，周期闸 ABSTAIN")
        return base
    rng = (max(gms) - min(gms)) * 100
    b_signal = rng > 15.0
    c_signal = bool(profs) and min(profs) < 0
    base["judge_B"] = {"status": "computed", "range_pp": round(rng, 1),
                       "points": len(gms), "signal": b_signal, "window": sorted(r[0] for r in rows)}
    base["judge_C"] = {"status": "computed", "signal": c_signal,
                       "is_loss": c_signal, "worst_profit": min(profs) if profs else None}
    base["hits"] = [j for j, s in (("B", b_signal), ("C", c_signal)) if s]
    base["verdict"] = "CYCLIC_SUSPECT" if base["hits"] else "NO_CYCLIC_SIGNAL"
    base["notes"].append("非 A 股：global_financials 复算判据 B/C（阈值同 fengsource），窗口=全部年度点；"
                         "判据 A/D 仍须人工")
    return base


def _gate_tag(ticker: str, cache: dict, market: str = "CN") -> dict:
    """周期闸标记：CN 复用 fengsource.gate 判据 B/C（含窗口与口径）；
    HK/US 走 _global_gate 同阈值复算。结果缓存；ABSTAIN 原样透传，不猜。"""
    key = (market, ticker)
    if key not in cache:
        if market == "CN":
            try:
                import fengsource
                cache[key] = fengsource._gate(ticker)
            except Exception as e:  # 闸门失败也是结果，出声不吞
                cache[key] = {"verdict": "ABSTAIN", "hits": [],
                              "notes": [f"gate 调用失败: {type(e).__name__}: {e}"],
                              "judge_B": {"status": "ABSTAIN"}, "judge_C": {"status": "ABSTAIN"}}
        else:
            cache[key] = _global_gate(ticker, market)
    return cache[key]


def cmd_batch(args) -> int:
    """全格子批量排序：所有行业「值得先看」的名单，附周期闸标记。

    科学性边界（与单格 rank_candidates 同一口径，无新增自由度）：
      - 仅 CN（其余市场无多年财务序列，ABSTAIN 出声）
      - 行业成员 = 申万二级成分（缓存按月）；排序键 = 谷底年盈利✓ > 年限深 > 毛利率极差小
      - 年度点 <MIN_RANK_YEARS 不参排（短历史另列，不排除）
      - 周期标记 = fengsource 判据 B/C（A 价格接受者/D 提价历史只能人工）
      - 本名单是「先看谁」，不是候选卡：闸门 0/1/2 与七层仍在前方，不排除任何公司
    """
    grid = load_grid()
    problems = grid_health(grid)
    if problems:
        for p in problems:
            print(f"[问题] {p}")
        return 2
    mk = (args.market or "CN").upper()
    if mk not in ("CN", "HK", "US"):
        print(f"[ABSTAIN] {mk} 本地库无多年财务序列，批量排序暂不支持（见 SWEEP-PROTOCOL §5）；"
              "补 KR/JP 财务通路后开放")
        return 2

    from collections import OrderedDict
    cells = active_cells(grid)
    gate_cache: dict = {}
    per_domain: "OrderedDict[str, list]" = OrderedDict()
    abstain_cells: list[tuple[str, str, str]] = []  # (cell, market, 原因)
    all_ranked: dict[str, dict] = {}
    t0 = time.time()
    print(f"[BATCH] {len(cells)} 格 × top{args.top}，周期闸逐只打标…", flush=True)
    for i, cell in enumerate(cells, 1):
        rank = rank_candidates(cell, mk, top_n=args.top)
        if rank["mode"] != "RANKED":
            reason = "；".join(rank["notes"]) or "无候选"
            abstain_cells.append((cell["id"], cell["domain"], reason))
        else:
            rows = []
            for c in rank["candidates"]:
                g = _gate_tag(c["ticker"], gate_cache, mk)
                rows.append({**c,
                             "gate_verdict": g["verdict"],
                             "gate_hits": g.get("hits", []),
                             "gm_window": (g.get("judge_B") or {}).get("window", [])})
                all_ranked[c["ticker"]] = {"name": c["name"], "cell": cell["id"], **c}
            per_domain.setdefault(cell["need"], []).append(
                {"cell": cell["id"], "domain": cell["domain"], "rows": rows,
                 "members_all": rank.get("members_all", []),
                 "notes": rank["notes"]})
        if i % 10 == 0 or i == len(cells):
            print(f"  [{i}/{len(cells)}] {time.time() - t0:.0f}s", flush=True)

    # 报告产出
    today = date.today().isoformat()
    out_dir = os.path.join(ROOT, "research", "120-idea-sourcing", "reports")
    os.makedirs(out_dir, exist_ok=True)
    md_path = os.path.join(out_dir, f"sweep-{today}-{mk}.md")
    n_unique = len(all_ranked)
    n_cyclic = sum(1 for t in all_ranked
                   if _gate_tag(t, gate_cache, mk)["verdict"] == "CYCLIC_SUSPECT")
    n_abstain = sum(1 for t in all_ranked
                    if _gate_tag(t, gate_cache, mk)["verdict"] == "ABSTAIN")
    lines = []
    lines.append(f"# 零输入扫描·全行业先看名单（{mk}）— {today}\n")
    lines.append("> 生成: tools/fengsweep.py batch（创始人 2026-09-26 授权）。"
                 "本名单是**排序器产出=先看谁**，不是候选卡、不是买入建议；"
                 "闸门 0/1/2 与七层仍在前方，任何公司未因本名单被排除。\n")
    lines.append("\n## 方法（科学性口径，全部机器可证）\n")
    if mk == "CN":
        lines.append("- 行业成员: 申万二级行业成分（akshare index_component_sw，本地缓存按月刷新: data/cache/sw_cons_cache.json）")
    else:
        lines.append("- 行业成员: fundamentals 行业标注（Morningstar 英文名）× data/config/sw_global_map.json 关键词映射；标注未覆盖标的降级全池通道（备注出声）")
        lines.append("- 财务序列: global_financials（tools/fengexpand_fin_global.py 回填，东财源，毛利率小数刻度与 cn_financials 同；美股财年按报告期入账，非自然年公司如苹果按其财年）")
    lines.append(f"- 排序键: ① 谷底年盈利✓优先 ② 数据年限深优先 ③ 近10年毛利率极差小优先；年度点 <{MIN_RANK_YEARS} 不参排（短历史不排除，走 AI 常识名单）")
    lines.append("- 周期标记: tools/fengsource.py gate 判据 B（毛利率极差>15pp）/C（谷底亏损），窗口=近10年报，仅覆盖 B/C；"
                 "判据 A（价格接受者）/D（提价历史）只能人工——标记不是否决（2026-09-20 创始人裁定）")
    lines.append(f"- 数据源: data/market_data.db cn_financials 年报（if_correct=0 优先，毛利率字段缺失用 营收-成本 推算并标注）；"
                 f"同行多版本取未更正版；ABSTAIN 一律出声，不用默认值冒充")
    lines.append(f"- 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}，耗时 {time.time() - t0:.0f}s\n")
    lines.append(f"\n## 总览\n")
    lines.append(f"- 格子: {len(cells)} active；有排序结果 {sum(len(v) for v in per_domain.values())} 格；"
                 f"排序 ABSTAIN {len(abstain_cells)} 格（走 AI 常识名单通道）")
    lines.append(f"- 先看名单: 唯一公司 {n_unique} 只；其中周期标记 {n_cyclic} 只、"
                 f"闸门 ABSTAIN {n_abstain} 只（非 A 股口径序列不足时出现）")
    lines.append("- 下一步: 对感兴趣的格子走闸门 0（≥3 条带 URL 证据）→ 候选卡 → 排队七层\n")
    for need, groups in per_domain.items():
        lines.append(f"\n## {need}\n")
        lines.append("| 格子 | 行业 | 代码 | 公司 | 年限 | 毛利率极差 | 谷底年盈利 | 周期标记 |")
        lines.append("|:--|:--|:--|:--|:--|:--|:--|:--|")
        for g in groups:
            for r in g["rows"]:
                mark = {"CYCLIC_SUSPECT": f"⚠️ {'/'.join(r['gate_hits'])}",
                        "ABSTAIN": "—(ABSTAIN)",
                        "NO_CYCLIC_SIGNAL": "✅未见"}.get(r["gate_verdict"], r["gate_verdict"])
                lines.append(
                    f"| {g['cell']} | {g['domain']} | {r['ticker']} | {r['name']} | "
                    f"{r['years']}年 | {r['gm_range_pp']:.1f}pp | "
                    f"{'✓' if r['worst_year_profitable'] else '✗'} | {mark} |")
    if abstain_cells:
        lines.append(f"\n## 排序 ABSTAIN 格子（{len(abstain_cells)}，原因逐格留痕）\n")
        for cid, dom, why in abstain_cells:
            lines.append(f"- {cid} {dom}: {why}")
    lines.append("\n---\n")
    lines.append("*口径声明：本表所有数字来自 data/market_data.db（本地，只读），生成即冻结；"
                 "闸门 0 取证时必须重新对拍。B/C 周期标记的窗口与阈值详见 fengsource gate 输出。*")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    json_path = md_path.replace(".md", ".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"date": today, "market": mk, "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "method": {"member_source": ("sw_index_component(30d cache)" if mk == "CN"
                                                else "fundamentals.industry x sw_global_map"),
                              "rank_key": "worst_profitable>years>gm_range", "min_rank_years": MIN_RANK_YEARS,
                              "gate": "fengsource judge B/C only"},
                   "unique_tickers": n_unique, "cells_ranked": sum(len(v) for v in per_domain.values()),
                   "cells_abstain": len(abstain_cells),
                   "domains": {k: v for k, v in per_domain.items()},
                   "abstain_cells": abstain_cells}, f, ensure_ascii=False, indent=1)
    print(f"\n[SAVED] 报告: {os.path.relpath(md_path, ROOT)}")
    print(f"[SAVED] 数据: {os.path.relpath(json_path, ROOT)}")
    print(f">> 唯一公司 {n_unique} 只（周期标记 {n_cyclic} / ABSTAIN {n_abstain}）；"
          f"排序 ABSTAIN 格子 {len(abstain_cells)} 格已逐格留痕")
    print(">> 记住: 这是「先看谁」名单——闸门 0 取证、候选卡、七层分析仍在前方")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        prog="fengsweep.py",
        description="零输入发现协议游标引擎（路径 1 需求锚定程序化；机制见 research/120-idea-sourcing/SWEEP-PROTOCOL.md）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("退出码: 0=成功 / 2=用法错误或校验失败\n"
                "铁律: 排序器只定先看谁，不排除任何公司；barren 必须写明原因；状态即台账（append-only）。"),
    )
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("grid", help="格子表体检（完整性/ID 唯一性）")
    p.set_defaults(func=cmd_grid)

    p = sub.add_parser("status", help="游标现状 + 覆盖率")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("next", help="本轮该扫的格子（含生意问句与流程）")
    p.add_argument("--market", default="", help="只在该市场内推进（CN/HK/US/KR/JP）")
    p.set_defaults(func=cmd_next)

    p = sub.add_parser("record", help="记一格的结果（candidates 或 barren）")
    p.add_argument("--cell", required=True, help="格子 ID（needs-###）")
    p.add_argument("--market", required=True, help="市场（CN/HK/US/KR/JP）")
    p.add_argument("--outcome", required=True, help="candidates=出了候选卡 / barren=贫瘠（必须写原因）")
    p.add_argument("--tickers", default="", help="本格出卡的 ticker（逗号分隔，可选）")
    p.add_argument("--note", default="", help="一句话备注（barren 必填）")
    p.add_argument("--by", default="fengsweep", help="记录人（默认 fengsweep）")
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("cursor", help="游标手动校正（巡检/创始人用）")
    p.add_argument("--set", required=True, help="把该格子记为已过")
    p.add_argument("--market", required=True, help="市场")
    p.add_argument("--note", default="", help="校正原因")
    p.add_argument("--by", default="fengsweep", help="记录人")
    p.set_defaults(func=cmd_cursor)

    p = sub.add_parser("batch", help="全格子批量排序：全行业先看名单（附周期闸标记）")
    p.add_argument("--market", default="CN", help="支持 CN/HK/US（KR/JP 无财务序列，ABSTAIN）")
    p.add_argument("--top", type=int, default=5, help="每格取前 N（默认 5：稳健 3 + 深周期 2）")
    p.set_defaults(func=cmd_batch)

    args = ap.parse_args()
    if not getattr(args, "cmd", None):
        ap.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
