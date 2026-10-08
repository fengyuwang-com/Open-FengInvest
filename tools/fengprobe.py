#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fengprobe — 工具链每日冒烟探针（2026-09-13 三件套①：让无声降级变有声）。

原理：每个铁律工具用轻量只读样本真跑一次（不是 --version），结果三分：
  ok      真跑成功且输出结构 sanity 通过
  partial 能跑但工具自报取数降级（fengmarket 缺源 / fengquant peer 失败 / data_health FAILED）
  fail    非零退出 / 超时 / 输出不可解析——死灯
  skip    前置文件缺失（如冒烟标的层产物未生成）——灰灯，不算工具死
结果写 data/reports/tool_health.json，/mission 看板（fengmission.py 只读渲染）挂灯；
探针自身退出码：有 fail → 1（定时任务/cron 里也有声音）。

用法:
  python tools/fengprobe.py                     # 全量跑 + 写报告
  python tools/fengprobe.py --json              # 同时把报告 dump 到 stdout
  python tools/fengprobe.py --only L2b,M        # 只跑指定探针项（调试）
  python tools/fengprobe.py --list              # 列探针项
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

# Windows GBK 控制台防崩：✅🟡🔴 输出统一走 UTF-8（否则每日冒烟在 GBK 终端假性崩溃）。
# 只加不减：不影响任何探针逻辑，仅让输出层在非 UTF-8 终端不假性崩溃。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT = os.path.join(ROOT, "data", "reports", "tool_health.json")
PY = sys.executable

# 冒烟标的：09988.HK（影子持仓样例，状态机有真状态、七层可跑）+ AAPL（yfinance 链路样例）
# 注：开源版不带真仓的完整七层产物样例（个人研究不开源，AGENTS §一.3），故冒烟改用影子标的。
SMOKE_TICKER = "09988.HK"
SMOKE_US = "AAPL"


def _latest_analysis_dir(ticker: str) -> str | None:
    """research/060-companies/<ticker>-*/ 下最新日期目录。"""
    companies = os.path.join(ROOT, "research", "060-companies")
    hits = sorted(glob.glob(os.path.join(companies, f"{ticker}-*")))
    if not hits:
        return None
    dates = sorted(d for d in glob.glob(os.path.join(hits[0], "20*")) if os.path.isdir(d))
    return dates[-1] if dates else None


def _layer_file(ticker: str, layer: str) -> str | None:
    d = _latest_analysis_dir(ticker)
    if not d:
        return None
    p = os.path.join(d, layer)
    return p if os.path.exists(p) else None


# ── 探针项定义 ─────────────────────────────────────────────────────────────
# keys: stdout JSON 必须包含的顶层键（缺 = fail，输出结构病变更早被发现）
# partial_via: (键, 值) 命中则 partial；或 data_health 里出现 FAILED/peers_failed 非空

def _mk(ticker=SMOKE_TICKER):
    return [
        {
            "name": "state", "tool": "fengstate.py", "layer": "状态机",
            "cmd": [PY, "tools/fengstate.py", "status", ticker], "timeout": 30, "json": False,
        },
        {
            "name": "db", "tool": "fengdb.py", "layer": "写库/变更集",
            "cmd": [PY, "tools/fengdb.py", "status"], "timeout": 60, "json": False,
        },
        {
            "name": "freshness", "tool": "fengmission.py", "layer": "看板探针",
            "cmd": [PY, "tools/fengmission.py"], "timeout": 90, "json": True,   # 2026-09-30：30s 误报（standalone 实测秒级过，探针内偶发慢盘）→ 90s
            "keys": ["freshness"],
        },
        {
            "name": "quote-fallback", "tool": "fengdata.py", "layer": "M 行情+备源链",
            "cmd": [PY, "tools/fengdata.py", SMOKE_US], "timeout": 120, "json": True,
            "keys": ["ticker"],
        },
        {
            "name": "yf-chain", "tool": "fengquick.py", "layer": "yfinance 直连链路",
            "cmd": [PY, "tools/fengquick.py", SMOKE_US], "timeout": 60, "json": True,
            "keys": ["ticker", "source"],
            "ok_when": lambda d: d.get("source") == "live",
            "fail_note": "yf 链路无声/有声失败（source≠live：限流或死）",
        },
        {
            "name": "L1", "tool": "fengrule.py", "layer": "L1 硬纪律",
            "cmd": [PY, "tools/fengrule.py", ticker], "timeout": 90, "json": True,
            "keys": ["rules"],
        },
        {
            "name": "L2b", "tool": "fengquant.py", "layer": "L2b 量化因子",
            "cmd": [PY, "tools/fengquant.py", SMOKE_US], "timeout": 150, "json": True,
            "keys": ["data_health"],
        },
        {
            "name": "L3", "tool": "fengcollision.py", "layer": "L3 碰撞",
            "cmd": None,  # 动态注入（依赖层产物文件），见 _resolve_dynamic
            "timeout": 30, "json": True, "keys": [],
            "prereq_layers": [("03-discipline.json", "--l1"), ("04-quantitative.json", "--l2b")],
        },
        {
            "name": "P", "tool": "fengportfolio.py", "layer": "P 组合",
            "cmd": [PY, "tools/fengportfolio.py", "check"], "timeout": 120, "json": False,
        },
        {
            "name": "M", "tool": "fengmarket.py", "layer": "M 市场温度",
            "cmd": [PY, "tools/fengmarket.py", "collect"], "timeout": 300, "json": True,
            "keys": ["status"],
            "partial_when": lambda d: d.get("status") == "partial",
        },
        {
            "name": "verify", "tool": "fengverify.py", "layer": "论断复测引擎",
            # #1 年线复测冒烟只验「引擎活性」：2026-09-30 数据扩张入库（全市场 13 市场）后单次全扫实测
            # ~160s/市场 × 13 市场 ≈ 35-45min，探针不等全程——超时但逐市场进度可见 → partial（引擎活着）；
            # 无声退出/非零退出 → fail。完成度复测走 fengverify 单独跑 + fengcheck。
            "cmd": [PY, "tools/fengverify.py", "1", "--out", "Temp/verify_probe"], "timeout": 240, "json": False,
            "liveness": True,   # 冒烟只验引擎活性：240s 内有逐市场进度 → partial；无声死 → fail
        },
    ]


def _resolve_dynamic(spec: dict) -> tuple[bool, str]:
    """L3 需要层产物文件；缺失则 skip（前置缺失≠工具死）。返回 (ok, note)。"""
    if spec.get("cmd"):
        return True, ""
    if spec["name"] != "L3":
        return False, "未定义命令"
    files = []
    for layer_file, flag in spec.get("prereq_layers", []):
        p = _layer_file(SMOKE_TICKER, layer_file)
        if not p:
            return False, f"缺前置产物 {layer_file}（{SMOKE_TICKER} 分析目录未就绪）"
        rel = os.path.relpath(p, ROOT).replace("\\", "/")
        files += [flag, f'"{rel}"']
    spec["cmd"] = [PY, "tools/fengcollision.py", SMOKE_TICKER] + files
    return True, ""


def _classify(spec: dict, rc: int, out: str) -> tuple[str, str]:
    """单项判定 → (status, note)。"""
    if rc != 0:
        return "fail", f"exit {rc}: {_tail(out)}"
    if not out.strip():
        return "fail", "空输出"
    if spec.get("json"):
        try:
            m = re.search(r"[\[{]", out)
            if not m:
                return "fail", "stdout 无 JSON"
            data = json.loads(out[m.start():])
        except (json.JSONDecodeError, ValueError) as e:
            return "fail", f"JSON 解析失败: {e}; {_tail(out)}"
        miss = [k for k in spec.get("keys", []) if not isinstance(data, dict) or k not in data]
        if miss:
            return "fail", f"输出缺键 {miss}（结构变更？{_tail(out)}）"
        if isinstance(data, dict):
            okw = spec.get("ok_when")
            if okw and not okw(data):
                return "fail", spec.get("fail_note", "ok_when 不满足")
            pw = spec.get("partial_when")
            if pw and pw(data):
                failed = data.get("failed_components") or []
                return "partial", f"自报降级: {failed}"
            dh = data.get("data_health")
            if isinstance(dh, dict):
                bad = [k for k, v in dh.items()
                       if v == "FAILED" or (isinstance(v, list) and v)]
                # fengquant 的 peers_failed / fengmarket 的 FAILED 组件
                if data.get("peers_failed"):
                    bad.append(f"peers_failed={len(data['peers_failed'])}")
                if bad:
                    return "partial", f"data_health 降级: {bad}"
    return "ok", ""


def _tail(s: str, n: int = 160) -> str:
    t = (s or "").strip().replace("\n", " | ")
    return t[-n:] if len(t) > n else t


def run_probes(only: set[str] | None = None) -> dict:
    t_all = time.monotonic()
    items = []
    for spec in _mk():
        if only and spec["name"] not in only:
            continue
        ok, skip_note = _resolve_dynamic(spec)
        if not ok:
            items.append({"name": spec["name"], "tool": spec["tool"], "layer": spec["layer"],
                          "status": "skip", "elapsed_ms": 0, "note": skip_note})
            continue
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                spec["cmd"], cwd=ROOT, capture_output=True, text=True,
                timeout=spec["timeout"], encoding="utf-8", errors="replace",
                env={**os.environ, "FENG_INTL_QUIET": "1"},
            )
            status, note = _classify(spec, proc.returncode, proc.stdout or "")
            if status == "fail" and proc.stderr:
                note += f"; stderr: {_tail(proc.stderr, 100)}"
        except subprocess.TimeoutExpired as e:
            # 活性类探针：超时但已产出逐市场进度 → 引擎活着（partial），只有无声死才算 fail
            so, se = e.stdout, e.stderr
            if isinstance(so, bytes):
                so = so.decode("utf-8", "replace")
            if isinstance(se, bytes):
                se = se.decode("utf-8", "replace")
            combined = (so or "") + "\n" + (se or "")
            # 活性信号 = 逐市场进度行（「[..] AU ...」开扫 或 「[..] AU done (n/m)」完成）
            if spec.get("liveness") and re.search(r"\] [A-Z]{2} (done \(\d+/\d+\)|\.\.\.)", combined):
                done = re.findall(r"\] ([A-Z]{2}) done", combined)
                status = "partial"
                note = (f"引擎活性确认（全扫预计~40min>{spec['timeout']}s，超时属预期）："
                        f"完成 {','.join(done) if done else '无（首个市场扫描中）'}；"
                        f"完成度复测走 fengverify 单独跑/fengcheck")
            else:
                status, note = "fail", f"TIMEOUT {spec['timeout']}s（超时前无市场进度=引擎无声死）"
        except FileNotFoundError as e:
            status, note = "fail", f"命令不存在: {e}"
        items.append({
            "name": spec["name"], "tool": spec["tool"], "layer": spec["layer"],
            "status": status, "elapsed_ms": int((time.monotonic() - t0) * 1000),
            "note": note[:300],
        })
    counts = {s: sum(1 for i in items if i["status"] == s)
              for s in ("ok", "partial", "fail", "skip")}
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "total_elapsed_ms": int((time.monotonic() - t_all) * 1000),
        "summary": counts,
        "items": items,
    }


def main():
    ap = argparse.ArgumentParser(description="工具链每日冒烟探针")
    ap.add_argument("--json", action="store_true", help="报告同时打 stdout")
    ap.add_argument("--only", default="", help="逗号分隔探针名（如 L2b,M）")
    ap.add_argument("--list", action="store_true", help="列探针项")
    args = ap.parse_args()

    if args.list:
        for s in _mk():
            print(f"{s['name']:>10}  {s['tool']:<18} {s['layer']}")
        return

    only = {x.strip() for x in args.only.split(",") if x.strip()} or None
    report = run_probes(only)

    # 选择性跑 --only 时不覆盖全量报告（避免部分结果顶掉全量灯）
    if only:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        sys.exit(1 if report["summary"]["fail"] else 0)

    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        s = report["summary"]
        for i in report["items"]:
            mark = {"ok": "✅", "partial": "🟡", "fail": "🔴", "skip": "⚪"}[i["status"]]
            print(f"{mark} {i['name']:>10}  {i['tool']:<18} {i['elapsed_ms']:>6}ms  {i['note']}")
        print(f"\n探针: ok={s['ok']} partial={s['partial']} fail={s['fail']} skip={s['skip']} "
              f"用时 {report['total_elapsed_ms'] // 1000}s → {os.path.relpath(REPORT, ROOT)}")
        if s["fail"]:
            print("[PROBE][FAIL] 有死灯，见上方 🔴 项与 /mission 看板", file=sys.stderr)
    sys.exit(1 if report["summary"]["fail"] else 0)


if __name__ == "__main__":
    main()
