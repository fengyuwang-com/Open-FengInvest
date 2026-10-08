#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自主选股队列接力——本地调度台账（research/120-idea-sourcing 机制的调度件）。

与已作废的 Temp/batch_relay.py 的区别：**队列是数据驱动的**，不再硬编码一份
标的名单。队列来源 = data/config/research_list.json 里 status 为
researching / candidate 的条目；AI（或 /fengsource）往那份清单里加标的，
本工具下一轮就会把它排进接力。这正是"让 AI 自己去找股票"的调度落点。

每只标的四态（优先级从上到下）：
  DONE       分析目录里跑完全程（有 08-portfolio.json 或 AUDIT_REPORT.md）→ 跳过
  IN_FLIGHT  有派单登记且仍活跃 → 正在跑，别动
  STALLED    有派单登记但活跃条件不成立 → 疑似卡死，需人工释放后重派
  QUEUED     在队列里、没派单登记、没跑完 → 可以派

活跃条件（IN_FLIGHT 判据）：
  age(claim) <= 40min（刚派出去还在读 SKILL/取数，允许暂时没落盘）
  或 该标的分析目录里有文件在最近 60min 内被写过

调度台账：Temp/fengqueue_claims.jsonl（一行一条，只追加）。
暂停标志：Temp/fengqueue.paused（存在则只监督不派单）。

本脚本只读状态 + 维护自己的台账，绝不碰 research/state/ 与 fengstate 状态机，
也不改 research_list.json。

CLI:
  python tools/fengqueue.py status            # 队列状态表 + 本轮该派谁
  python tools/fengqueue.py claim <T> [<T>]   # 派单后登记
  python tools/fengqueue.py release <T>       # 卡死释放后再重派
"""
from __future__ import annotations

import glob
import json
import os
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(ROOT, "Temp", "fengqueue_claims.jsonl")
PAUSE_FLAG = os.path.join(ROOT, "Temp", "fengqueue.paused")
COMPANIES = os.path.join(ROOT, "research", "060-companies")
RESEARCH_LIST = os.path.join(ROOT, "data", "config", "research_list.json")

SLOTS = 2                 # 同时在跑上限
FRESH_CLAIM_MIN = 40.0    # 刚派出去多久内无条件算"在跑"
DIR_ACTIVITY_MIN = 60.0   # 分析目录多久内有写入算"在跑"
CLAIM_TTL_MIN = 600.0     # 派单登记最长有效 10h，超过视为陈旧登记可忽略

# 进入接力的 research_list status。parked/holding 不在队列里。
QUEUED_STATUS = ("researching", "candidate")
DONE_MARKERS = ("08-portfolio.json", "AUDIT_REPORT.md")


def _now_min() -> float:
    return time.time() / 60.0


def _read_queue() -> list[dict]:
    """从 research_list.json 读队列（status 为 researching/candidate 的条目）。"""
    if not os.path.exists(RESEARCH_LIST):
        return []
    try:
        with open(RESEARCH_LIST, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    items = data if isinstance(data, list) else data.get("items", data.get("companies", []))
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        tk = it.get("ticker")
        if not tk or it.get("status") not in QUEUED_STATUS:
            continue
        out.append(
            {
                "ticker": tk,
                "name": it.get("name", ""),
                "status": it.get("status", ""),
                "note": it.get("note", ""),
            }
        )
    return out


def _read_claims() -> dict[str, float]:
    """返回 ticker -> 最近一次**有效**派单的 unix 分钟。

    release 记录会作废它之前的所有 claim；release 之后若又有新 claim 则以后者为准。
    """
    claims: dict[str, float] = {}
    released: dict[str, float] = {}
    if not os.path.exists(LEDGER):
        return claims
    try:
        with open(LEDGER, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                tk = rec.get("ticker")
                if not tk:
                    continue
                for key, bucket in (("dispatched_at", claims), ("released_at", released)):
                    ts = rec.get(key)
                    if not ts:
                        continue
                    try:
                        minute = datetime.fromisoformat(ts).timestamp() / 60.0
                    except ValueError:
                        continue
                    if tk not in bucket or minute > bucket[tk]:
                        bucket[tk] = minute
    except OSError:
        return claims
    return {tk: mn for tk, mn in claims.items() if tk not in released or mn > released[tk]}


def _analysis_dirs(ticker: str) -> list[str]:
    return glob.glob(os.path.join(COMPANIES, ticker + "-*")) + glob.glob(
        os.path.join(COMPANIES, ticker)
    )


def _is_done(ticker: str) -> tuple[bool, str]:
    """分析目录里出现完成标记即判跑完。"""
    for d in _analysis_dirs(ticker):
        for marker in DONE_MARKERS:
            hits = glob.glob(os.path.join(d, "*", marker))
            if hits:
                return True, os.path.dirname(hits[-1])
    return False, ""


def _dir_activity_min(ticker: str) -> float | None:
    """该标的"最新一次写入"距今多少分钟；没有任何痕迹返回 None。

    取三处的最新鲜值：分析目录（research/060-companies/<T>/…）、状态机文件
    （research/state/temp_state_<T>.json）、状态日志（research/state/log_<T>.jsonl）。
    只认分析目录是不够的——代理刚跑完 fengstate init、还没写第一份产物时目录
    可能都不存在，只看目录会把它误判成空闲而重复派单。
    """
    newest: float | None = None

    def _bump(path: str) -> None:
        nonlocal newest
        try:
            mt = os.path.getmtime(path) / 60.0
        except OSError:
            return
        if newest is None or mt > newest:
            newest = mt

    for d in _analysis_dirs(ticker):
        for root, _dirs, files in os.walk(d):
            for fn in files:
                _bump(os.path.join(root, fn))
    for path in (
        os.path.join(ROOT, "research", "state", f"temp_state_{ticker}.json"),
        os.path.join(ROOT, "research", "state", f"log_{ticker}.jsonl"),
    ):
        _bump(path)
    if newest is None:
        return None
    return _now_min() - newest


def _classify() -> list[dict]:
    claims = _read_claims()
    now = _now_min()
    rows = []
    for item in _read_queue():
        ticker = item["ticker"]
        done, base = _is_done(ticker)
        claim_age = round(now - claims[ticker], 1) if ticker in claims else None
        act_age = _dir_activity_min(ticker)
        # 判"在跑"的两条独立依据，任一成立即可。特意让**近期写盘**哪怕没有派单
        # 登记也算在跑：代理可能是上一轮手工派的、登记漏了，误判成空闲就会重复派单。
        alive = (act_age is not None and act_age <= DIR_ACTIVITY_MIN) or (
            claim_age is not None and claim_age <= FRESH_CLAIM_MIN
        )
        # 完成标记齐了**不等于**可以验收：实测 601000.SS 在 09:50 就把状态机翻成
        # completed，10:00 还在回头改写 02-market / 03-discipline。此时按 DONE 收尾
        # 会拿一个**还在变的产物**去过闸门，验收结论立刻作废。故 DONE 必须额外要求
        # "近期没人再写盘"；标记齐但仍在写 → FINALIZING（仍在跑，不得验收）。
        still_writing = act_age is not None and act_age <= DIR_ACTIVITY_MIN
        if done and still_writing:
            state = "FINALIZING"
        elif done:
            state = "DONE"
        elif alive:
            state = "IN_FLIGHT"
        elif claim_age is not None:
            state = "STALLED"
        else:
            state = "QUEUED"
        rows.append(
            {
                "ticker": ticker,
                "name": item["name"],
                "status": item["status"],
                "state": state,
                "claim_age_min": claim_age,
                "dir_activity_min": None if act_age is None else round(act_age, 1),
                "base": base,
                "note": item["note"],
            }
        )
    return rows


def _offqueue_active(queue_tickers: set[str]) -> list[tuple[str, float]]:
    """找出不在队列里、但近期仍在写盘的标的（含状态机已 completed 却还在改的）。

    队列只含 researching/candidate，但别的 status（如 watching）也可能有代理在跑
    （历史遗留批次）。不看见它们就会漏算并发度，可能同时堆起 3-4 个代理。
    特意把 `completed` 也算进来：状态机翻成 completed 之后代理仍可能回头修层
    （601000.SS 实测），只认 "active" 会让它在收尾阶段**整个消失**，既漏算并发度
    又让"何时可以验收"失去依据。真正跑完的标的近期无写盘，天然被下面的窗口滤掉。
    """
    out = []
    state_dir = os.path.join(ROOT, "research", "state")
    for path in glob.glob(os.path.join(state_dir, "temp_state_*.json")):
        base = os.path.basename(path)[len("temp_state_"):-len(".json")]
        if base in queue_tickers:
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                st = json.load(f).get("status")
        except (OSError, json.JSONDecodeError):
            continue
        if st not in ("active", "completed"):
            continue
        age = _dir_activity_min(base)
        if age is not None and age <= DIR_ACTIVITY_MIN:
            out.append((base, round(age, 1)))
    return sorted(out, key=lambda x: x[1])


def _pause_reason() -> str | None:
    if not os.path.exists(PAUSE_FLAG):
        return None
    try:
        with open(PAUSE_FLAG, "r", encoding="utf-8") as f:
            txt = f.read().strip()
    except OSError:
        txt = ""
    return txt or "未注明原因"


def cmd_status() -> int:
    rows = _classify()
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    print(f"=== 自主选股队列状态（队列 {len(rows)} 只，来自 research_list.json 的 researching/candidate）===")
    if not rows:
        print("  队列为空。")
    for r in rows:
        extra = []
        if r["claim_age_min"] is not None:
            extra.append(f"派单{r['claim_age_min']}min前")
        if r["dir_activity_min"] is not None:
            extra.append(f"目录活动{r['dir_activity_min']}min前")
        print(f"  {r['ticker']:12s} {r['name']:10s} {r['state']:10s} " + " ".join(extra))
    print()
    print("汇总: " + " ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    inflight = [r["ticker"] for r in rows if r["state"] == "IN_FLIGHT"]
    finalizing = [r["ticker"] for r in rows if r["state"] == "FINALIZING"]
    stalled = [r["ticker"] for r in rows if r["state"] == "STALLED"]
    todo = [r["ticker"] for r in rows if r["state"] == "QUEUED"]
    print(f"IN_FLIGHT : {inflight or 'NONE'}")
    print(f"FINALIZING: {finalizing or 'NONE'}"
          + ("   ← 完成标记已齐但仍在写盘，**不得验收**（产物还在变）" if finalizing else ""))
    print(f"STALLED   : {stalled or 'NONE'}")
    print(f"QUEUED    : {todo or 'NONE'}")

    offqueue = _offqueue_active({r["ticker"] for r in rows})
    if offqueue:
        print()
        print("队列之外仍在跑（不在接力名单，仅用于算清并发度，不要重派）:")
        for tk, age in offqueue:
            print(f"  {tk:12s} 目录活动 {age}min 前")

    pause = _pause_reason()
    if pause is not None:
        print(f"PAUSED   : {pause}")
        print(f">> 结论: 已暂停派单（{pause}）→ 本轮只监督，不派新单")
        return 0

    # FINALIZING 也算"在跑"：它占着一个代理、且产物还在变，既不派新单也不能验收。
    busy = inflight + finalizing
    running = len(busy) + len(offqueue)
    if running >= SLOTS:
        who = busy + [tk for tk, _ in offqueue]
        print(f">> 结论: 含队列外共 {running} 只在跑 {who} → 本轮只监督，不派新单")
        if finalizing:
            print(f">> 注意: {finalizing} 是 FINALIZING（标记齐但仍在写盘）→ 本轮**不验收**，等其停笔")
        if stalled:
            print(f">> 另需处理卡死: {stalled}")
    elif busy:
        slots = SLOTS - running
        if todo:
            print(f">> 结论: 含队列外共 {running} 只在跑 → 队列内可补派 {slots} 只: {todo[:slots]}")
        else:
            print(f">> 结论: 含队列外共 {running} 只在跑、队列已空 → 可补派 {slots} 只，但需先跑 /fengsource 补充队列")
    elif stalled:
        print(f">> 结论: 无人在跑但存在卡死登记 {stalled} → 释放后重派这些（最多 {SLOTS} 只）")
    elif todo:
        print(f">> 结论: 无人在跑 → 派下 {min(SLOTS, len(todo))} 只: {todo[:SLOTS]}")
    else:
        print(">> 结论: 无人在跑且队列为空 → 本轮不派单，跑 /fengsource 发现新标的填队列")
    return 0


def cmd_claim(tickers: list[str]) -> int:
    if not tickers:
        print("用法: claim <TICKER> [<TICKER> ...]")
        return 2
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    now = datetime.now().isoformat(timespec="seconds")
    with open(LEDGER, "a", encoding="utf-8") as f:
        for t in tickers:
            f.write(json.dumps({"ticker": t, "dispatched_at": now}, ensure_ascii=False) + "\n")
            print(f"[claim] {t} @ {now}")
    return 0


def cmd_release(tickers: list[str]) -> int:
    if not tickers:
        print("用法: release <TICKER> [<TICKER> ...]")
        return 2
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    now = datetime.now().isoformat(timespec="seconds")
    with open(LEDGER, "a", encoding="utf-8") as f:
        for t in tickers:
            f.write(json.dumps({"ticker": t, "released_at": now}, ensure_ascii=False) + "\n")
            print(f"[release] {t} @ {now}")
    return 0


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1].lower()
    rest = sys.argv[2:]
    if cmd == "status":
        return cmd_status()
    if cmd == "claim":
        return cmd_claim(rest)
    if cmd == "release":
        return cmd_release(rest)
    print(f"未知命令: {cmd}")
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
