#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fengfinviz — finviz.com 美股旁路数据源（finvizfinance 直接合并）。

来源与许可:
  上游: https://github.com/lit26/finvizfinance（PyPI finvizfinance，MIT）
  评估档案: research/opensource-eval/finvizfinance-EVAL.md
    （判定: 可借鉴，倾向"有限可集成"——美股侧旁路数据源，不进核心链路）
  台账: data/config/opensource_list.json #16 finvizfinance

三路补缺数据（对照评估 §重叠矩阵，全部是现有工具的缺口）:
  ratings   分析师评级汇总（fengsec/fengdata 均无）
  news      个股新闻列表（无系统化新闻源）
  insider   内部人交易易读视图（fengsec Form 3/4/5 有一手 PIT，缺易读汇总）
  fundament 估值/表现快照（40+ 字段，旁路参考；PIT 口径仍以 fengsec XBRL 为准）

定位铁律（评估 §落地建议）:
  - 旁路薄封装：给 L2a 定性层供参考表，fenginvest 七层**不得强依赖**本工具
    （finviz 是网页爬取无 API 承诺，一次改版即断；失败必须可降级）
  - 低频日线级调用；爬虫失败原样报错不吞，由调用方决定降级

CLI:
  python tools/fengfinviz.py MSFT              # 三路汇总（评级+新闻+内部人）
  python tools/fengfinviz.py MSFT --only ratings
  python tools/fengfinviz.py MSFT --json
"""
from __future__ import annotations

import argparse
import json
import sys
import time

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _fetch(ticker: str, only: str | None) -> dict:
    """拉取三路数据。任何一路失败记录 error 不拖垮其余路（降级不阻塞）。"""
    from finvizfinance.quote import finvizfinance

    s = finvizfinance(ticker.upper())
    out: dict = {"ticker": ticker.upper(), "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "source": "finviz.com via finvizfinance（旁路爬取，无 API 承诺）", "sections": {}}

    def _want(name: str) -> bool:
        return only is None or only == name

    if _want("ratings"):
        try:
            df = s.ticker_outer_ratings()
            out["sections"]["ratings"] = {
                "count": int(len(df)),
                "rows": df.tail(10).to_dict("records"),  # 最近 10 条
                "note": "Date/Status/Outer/Rating/Price；Outer=机构名",
            }
        except Exception as e:
            out["sections"]["ratings"] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    if _want("news"):
        try:
            df = s.ticker_news()
            out["sections"]["news"] = {
                "count": int(len(df)),
                "rows": df.head(10).to_dict("records"),  # 最新 10 条
                "note": "Date/Title/Link/Source",
            }
        except Exception as e:
            out["sections"]["news"] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    if _want("insider"):
        try:
            df = s.ticker_inside_trader()
            cols = [c for c in ("Insider Trading", "Relationship", "Date", "Transaction",
                                "Cost", "#Shares", "Value ($)", "SEC Form 4 Link") if c in df.columns]
            out["sections"]["insider"] = {
                "count": int(len(df)),
                "rows": df[cols].head(10).to_dict("records"),
                "note": "近月内部人交易；一手 PIT 用 tools/fengsec.py insider 对拍",
            }
        except Exception as e:
            out["sections"]["insider"] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    if _want("fundament"):
        try:
            fd = s.ticker_fundament()
            out["sections"]["fundament"] = {
                "count": len(fd),
                "snapshot": {k: fd.get(k) for k in (
                    "Market Cap", "P/E", "Forward P/E", "PEG", "P/B", "Dividend Est.",
                    "Target Price", "Short Float", "Perf Week", "Perf Month", "Perf Year",
                    "Insider Own", "Inst Own", "EPS next Y") if k in fd},
                "note": "快照级参考；PIT 口径以 tools/fengsec.py facts 为准",
            }
        except Exception as e:
            out["sections"]["fundament"] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    return out


def _print(out: dict) -> None:
    print(f"=== finviz 旁路数据 — {out['ticker']} ===")
    print(f"来源: {out['source']}  @ {out['fetched_at']}")
    for name, sec in out["sections"].items():
        print()
        if "error" in sec:
            print(f"[{name}] 失败（降级不阻塞）: {sec['error']}")
            continue
        print(f"[{name}] {sec['count']} 条")
        for r in sec["rows"][:5]:
            if name == "ratings":
                print(f"  {r.get('Date', '')} {r.get('Outer', '')} → {r.get('Rating', '')} ({r.get('Price', '')})")
            elif name == "news":
                print(f"  {r.get('Date', '')} [{r.get('Source', '')}] {str(r.get('Title', ''))[:70]}")
            elif name == "insider":
                print(f"  {r.get('Date', '')} {r.get('Insider Trading', '')} ({r.get('Relationship', '')}) "
                      f"{r.get('Transaction', '')} {r.get('#Shares', '')}股 @ {r.get('Cost', '')}")
            else:
                print(f"  {r}: {sec['snapshot'][r]}")
        if sec["count"] > 5:
            print(f"  …（其余 {sec['count'] - 5} 条见 --json）")


def main() -> int:
    ap = argparse.ArgumentParser(description="finviz 旁路数据源（finvizfinance 合并；L2a 参考表，不进核心链路）")
    ap.add_argument("ticker", help="美股代码（如 MSFT）")
    ap.add_argument("--only", choices=["ratings", "news", "insider", "fundament"],
                    help="只取一路（默认三路+快照全取）")
    ap.add_argument("--json", action="store_true", help="纯 JSON 输出（供 AI 消费）")
    args = ap.parse_args()
    out = _fetch(args.ticker, args.only)
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        _print(out)
    # 任何一路成功即 exit 0（降级不阻塞）；全失败 exit 1
    secs = out["sections"]
    if secs and all("error" in s for s in secs.values()):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
