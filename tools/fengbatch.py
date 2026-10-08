#!/usr/bin/env python3
"""fengbatch.py — 批量自动选股流水线管理器（纯本地，零 LLM）

流程: 公开 list → 规则粗筛(fengscreen 四维排名) → 规则精筛(--hard-rules 7硬指标+3豁免)
      → 幸存者名单 → AI 逐只 /fenginvest 七层分析（AI skill 负责） → 汇总报告

用法:
  python tools/fengbatch.py plan --list-name cn_dividend [--top 50] [--file xxx.txt]
  python tools/fengbatch.py status <批次名>
  python tools/fengbatch.py summary <批次名>

批次名规则: <list名或文件名>-<YYYYMMDD>（--batch-name 可覆盖）
断点续跑: plan 幂等（同输入重跑产同样结果，覆盖同名批次）；status/summary 随时可跑
"""

import argparse, json, os, re, sys, time
from datetime import datetime
from pathlib import Path

TOOLS_DIR = Path(__file__).parent
PROJECT_DIR = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))

import fengscreen  # 复用 fetch_fundamentals / compute_scores / run_hard_rules 等

BATCH_DIR = PROJECT_DIR / "research" / "070-reports" / "batch"
STATE_DIR = PROJECT_DIR / "research" / "state"
SEQUENCE = ["01-capability", "02-market", "03-discipline", "04-quantitative",
            "05-qualitative", "06-collision", "07-report", "08-portfolio"]


def _batch_dir(batch_name):
    return BATCH_DIR / batch_name


def _load_batch(batch_name):
    """读批次元数据 + survivors.json。返回 (meta, survivors, batch_path)。"""
    bdir = _batch_dir(batch_name)
    meta_p = bdir / "meta.json"
    surv_p = bdir / "survivors.json"
    if not meta_p.exists() or not surv_p.exists():
        return None, [], bdir
    with open(meta_p, encoding="utf-8") as f:
        meta = json.load(f)
    with open(surv_p, encoding="utf-8") as f:
        surv = json.load(f)
    return meta, surv, bdir


def cmd_plan(args):
    t0 = time.time()

    # ── 1. 取候选池 ──
    if args.file:
        tickers = fengscreen.read_tickers_file(args.file)
        source = f"文件 {args.file}"
        list_key = Path(args.file).stem
    elif args.list_name:
        try:
            tickers, src = fengscreen.fetch_list_tickers(args.list_name)
        except RuntimeError as e:
            print(f"[ERR] {e}")
            return 1
        source = f"list:{args.list_name} ({src})"
        list_key = args.list_name
    else:
        print("[ERR] 需要 --list-name <内置list> 或 --file <txt/json>")
        return 1
    if not tickers:
        print("[ERR] 候选池为空")
        return 1
    print(f"[POOL] 候选池 {len(tickers)} 只，来源: {source}")

    # ── 2. 粗筛：四维因子排名（复用 fengscreen 排名引擎）──
    print(f"[STEP1] 粗筛: 四维因子排名（质量>价值≈增长>动量）...")
    stocks_data = []
    failed = []
    for i, t in enumerate(tickers, 1):
        d = fengscreen.fetch_fundamentals(t)
        if d:
            stocks_data.append(d)
        else:
            failed.append(t)
        if i % 20 == 0:
            print(f"  [WAIT] {i}/{len(tickers)} ...", flush=True)
    print(f"[STEP1] 拿到基本面 {len(stocks_data)}/{len(tickers)} 只"
          + (f"，{len(failed)} 只失败: {failed[:10]}" if failed else ""))
    if not stocks_data:
        print("[ERR] 全部候选取数失败，无法粗筛")
        return 1
    ranked = fengscreen.compute_scores(stocks_data)

    # ── 3. 取 top N 进精筛 ──
    top_n = args.top
    candidates = ranked[:top_n]
    print(f"[STEP2] 取排名前 {len(candidates)} 只进硬指标精筛")

    # ── 4. 精筛：7 硬指标 + 3 豁免 ──
    results = []
    for i, c in enumerate(candidates, 1):
        print(f"  [精筛 {i}/{len(candidates)}] {c['ticker']} ...", flush=True)
        r = fengscreen.check_hard_rules(c["ticker"])
        r["rank"] = c["rank"]
        r["score"] = c["scores"]["total"]
        results.append(r)

    survivors = [r for r in results if r["verdict"] in ("PASS", "EXEMPT")]
    excluded = [r for r in results if r["verdict"] == "FAIL"]
    skipped = [r for r in results if r["verdict"] == "SKIP"]

    # ── 5. 落盘（幂等：同输入覆盖同名批次）──
    batch_name = args.batch_name or f"{list_key}-{datetime.now().strftime('%Y%m%d')}"
    bdir = _batch_dir(batch_name)
    bdir.mkdir(parents=True, exist_ok=True)

    with open(bdir / "survivors.json", "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.now().isoformat(),
                   "batch": batch_name, "source": source,
                   "pool_size": len(tickers), "ranked": len(stocks_data),
                   "top_n": top_n,
                   "survivors": survivors, "results": results},
                  f, ensure_ascii=False, indent=2)
    with open(bdir / "meta.json", "w", encoding="utf-8") as f:
        json.dump({"batch": batch_name, "created_at": datetime.now().isoformat(),
                   "source": source, "pool_size": len(tickers),
                   "n_survivors": len(survivors)}, f, ensure_ascii=False, indent=2)

    # ── 6. 人话摘要表 ──
    marks = {"PASS": "✅", "FAIL": "❌", "EXEMPT": "⚠️", "SKIP": "⏭️"}
    print(f"\n{'=' * 92}")
    print(f"  批次 [{batch_name}] 幸存者名单（粗筛 top{top_n} → 硬指标精筛）")
    print(f"{'=' * 92}")
    print(f"{'排名':<6} {'代码':<12} {'名称':<22} {'精筛':<6} {'综合分':>6}  说明")
    print(f"{'-' * 92}")
    for r in results:
        name = (r["name"][:20] + "…") if r["name"] and len(r["name"]) > 21 else (r["name"] or "")
        print(f"{r['rank']:<6} {r['ticker']:<12} {name:<22} {marks.get(r['verdict'], '?'):<4} "
              f"{r['score']:>6.1f}  {r['reason']}")
    print(f"\n  幸存者 {len(survivors)} 只: {', '.join(r['ticker'] for r in survivors) or '无'}")
    if skipped:
        print(f"  ⏭️ 数据拿不到（不算 FAIL）: {', '.join(r['ticker'] for r in skipped)}")
    print(f"\n[SAVED] {bdir / 'survivors.json'}")
    print(f"[NEXT] 对每只幸存者执行 /fenginvest <TICKER>（AI 七层分析），"
          f"然后 python tools/fengbatch.py summary {batch_name}")
    print(f"[DONE] {time.time() - t0:.1f}s")
    return 0


def _completed_map(state):
    """state['completed'] 兼容两种格式: dict {layer: info} / list [[layer, info]]。
    返回 dict(layer -> info)。"""
    comp = state.get("completed") or {}
    if isinstance(comp, dict):
        return comp
    if isinstance(comp, list):
        return {item[0]: item[1] for item in comp if isinstance(item, (list, tuple)) and item}
    return {}


def _read_state(ticker):
    p = STATE_DIR / f"temp_state_{ticker.upper()}.json"
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def cmd_status(args):
    batch_name = args.batch
    meta, surv, bdir = _load_batch(batch_name)
    if meta is None:
        print(f"[i] 批次 [{batch_name}] 不存在或还没跑 plan。")
        print(f"    可用批次: {', '.join(sorted(d.name for d in BATCH_DIR.iterdir() if d.is_dir())) if BATCH_DIR.exists() else '（无）'}")
        return 1
    survivors = surv.get("survivors", [])
    if not survivors:
        print(f"[i] 批次 [{batch_name}] 暂无幸存者，无需分析。")
        return 0
    print(f"=== 批次 [{batch_name}] 七层分析进度 ===")
    print(f"来源: {meta.get('source')} | 幸存者 {len(survivors)} 只\n")
    any_state = False
    for s in survivors:
        t = s["ticker"]
        state = _read_state(t)
        if not state:
            print(f"  {t:<12} 未开始（还没 init 七层状态机）")
            continue
        any_state = True
        done = set(_completed_map(state))
        status = state.get("status", "?")
        bar = "".join("x" if l in done else "·" for l in SEQUENCE)
        print(f"  {t:<12} [{bar}] {len(done)}/8 层  状态={status}")
    if not any_state:
        print("\n[i] 暂无任何幸存者开始七层分析。下一步: 对每只幸存者执行 /fenginvest <TICKER>")
    return 0


def _find_latest_output(ticker, layer_prefix="06-collision"):
    """从状态文件读某层产物路径；fallback 扫 research/060-companies 目录。"""
    state = _read_state(ticker)
    if state:
        for layer, info in _completed_map(state).items():
            if layer.startswith(layer_prefix) and info.get("output"):
                p = PROJECT_DIR / info["output"]
                if p.exists():
                    return p
    # fallback: 目录扫描找最新
    base = PROJECT_DIR / "research" / "060-companies"
    if not base.exists():
        return None
    hits = sorted(base.glob(f"{ticker.upper()}-*/*/{layer_prefix}.*"))
    return hits[-1] if hits else None


def cmd_summary(args):
    batch_name = args.batch
    meta, surv, bdir = _load_batch(batch_name)
    if meta is None:
        print(f"[i] 批次 [{batch_name}] 不存在或还没跑 plan。")
        print(f"    可用批次: {', '.join(sorted(d.name for d in BATCH_DIR.iterdir() if d.is_dir())) if BATCH_DIR.exists() else '（无）'}")
        return 1
    survivors = surv.get("survivors", [])
    if not survivors:
        print(f"[i] 批次 [{batch_name}] 暂无幸存者，无可汇总。")
        return 0

    rows = []
    pending = []
    for s in survivors:
        t = s["ticker"]
        state = _read_state(t)
        done = set(_completed_map(state)) if state else set()
        if "06-collision" not in done and "07-report" not in done:
            pending.append(t)
            continue
        # 提取 decision / confidence / 一句话结论
        decision, confidence, oneliner = None, None, ""
        col_p = _find_latest_output(t, "06-collision")
        if col_p and col_p.suffix == ".json":
            try:
                with open(col_p, encoding="utf-8") as f:
                    cj = json.load(f)
                decision = cj.get("decision") or cj.get("conclusion") or cj.get("verdict")
                confidence = cj.get("confidence") or cj.get("confidence_level")
                oneliner = cj.get("one_liner") or cj.get("summary") or cj.get("reason", "")
            except Exception:
                pass
        if not decision and col_p:
            # markdown 产物：抓前几行非标题文本当结论
            try:
                text = col_p.read_text(encoding="utf-8")
                m = re.search(r"决策[^:：]*[:：]\s*(\S[^\n]*)", text)
                decision = m.group(1).strip() if m else "见报告"
                mc = re.search(r"置信[^:：]*[:：]\s*(\S+)", text)
                confidence = mc.group(1).strip() if mc else None
                for line in text.splitlines():
                    ls = line.strip()
                    if ls and not ls.startswith(("#", "|", ">", "-", "*", "```")):
                        oneliner = ls[:100]
                        break
            except Exception:
                pass
        conf_num = None
        if confidence is not None:
            mm = re.search(r"(\d+(?:\.\d+)?)", str(confidence))
            conf_num = float(mm.group(1)) if mm else None
        rows.append({"ticker": t, "name": s.get("name", ""), "decision": decision or "见报告",
                     "confidence": confidence, "conf_num": conf_num if conf_num is not None else -1,
                     "oneliner": oneliner or "", "report": str(col_p) if col_p else ""})

    if not rows:
        print(f"[i] 批次 [{batch_name}] 暂无已完成分析（06-collision 未完成），无可汇总。")
        print(f"    待分析: {', '.join(pending)}")
        print("    下一步: 对幸存者逐只执行 /fenginvest <TICKER>")
        return 0

    # 按置信度排序（conf_num 降序，未知排最后）
    rows.sort(key=lambda r: -r["conf_num"])
    lines = [
        f"# 批次汇总 [{batch_name}]",
        "",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 来源: {meta.get('source')}",
        f"- 幸存者: {len(survivors)} 只 | 已完成分析: {len(rows)} 只 | 待分析: {len(pending)} 只",
        "",
        "| 代码 | 名称 | 决策 | 置信度 | 一句话结论 |",
        "|:-----|:-----|:-----|:-------|:-----------|",
    ]
    for r in rows:
        lines.append(f"| {r['ticker']} | {r['name']} | {r['decision']} | "
                     f"{r['confidence'] if r['confidence'] is not None else '—'} | {r['oneliner']} |")
    if pending:
        lines += ["", f"## 待分析（尚未完成 06-collision）", ""]
        lines += [f"- {t}" for t in pending]
    out_p = bdir / "SUMMARY.md"
    with open(out_p, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[SAVED] {out_p}")
    print("\n".join(lines[7:7 + len(rows) + 3]))
    return 0


def main():
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="批量自动选股流水线管理器（plan/status/summary）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="粗筛→精筛→幸存者名单")
    p_plan.add_argument("--list-name", help="内置 list (cn_dividend/us_quality/us_dividend)")
    p_plan.add_argument("--file", help="自定义 ticker 文件（txt 一行一个 / JSON 数组）")
    p_plan.add_argument("--top", type=int, default=50, help="粗筛取前 N 名进精筛 (默认 50)")
    p_plan.add_argument("--batch-name", help="批次名（默认 <list名>-<YYYYMMDD>）")

    p_st = sub.add_parser("status", help="批次内每只幸存者的七层分析进度")
    p_st.add_argument("batch", help="批次名")

    p_sum = sub.add_parser("summary", help="已完成分析股票的汇总报告")
    p_sum.add_argument("batch", help="批次名")

    args = parser.parse_args()
    if args.cmd == "plan":
        sys.exit(cmd_plan(args))
    elif args.cmd == "status":
        sys.exit(cmd_status(args))
    elif args.cmd == "summary":
        sys.exit(cmd_summary(args))


if __name__ == "__main__":
    main()
