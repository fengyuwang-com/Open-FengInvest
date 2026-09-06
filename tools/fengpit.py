#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fengpit.py — PIT 双轴可见性（Point-In-Time：事件日 × 得知日）

每个基本面数字都带两个日期轴：
  事件轴 period_end —— 财报覆盖的期间（或资产负债表日）结束日；
  得知轴 filed     —— 该数字首次公开的日期（SEC 提交日 / A 股 declare_date）。

PIT 核心语义：截至 as-of 日，只能使用 filed <= as-of 的数字；period 再新，
没 filed 也看不见。本工具输出全事件表（含重述 vintage 与 tag 切换），并提供
as-of 单值查询。

来源：
  - us: SEC EDGAR companyfacts API（经 fengthrottle 限流 + TTL 缓存；
        另落 data/pit/<TICKER>.json 独立缓存，TTL 1 天）
  - cn: 本地 data/market_data.db 的 cn_financials（accper=事件日，
        declare_date=得知日；历史老数据 declare_date='None' → filed_reliable=False，
        规则参考 pit-fundamentals「日期不可靠宁可标记不伪造」）

用法：
  python tools/fengpit.py us AAPL --concept revenue --as-of 2025-06-30
  python tools/fengpit.py cn 600036 --concept total_assets --as-of 2024-12-31
  python tools/fengpit.py asof AAPL --concept revenue --as-of 2025-06-30 [--source us|cn]
  python tools/fengpit.py verify AAPL --reference <CSV> [--concept revenue]
  python tools/fengpit.py status <TICKER|STKCD>
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
import time
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fengthrottle as FT  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIT_DIR = os.path.join(BASE, "data", "pit")
DB_PATH = os.path.join(BASE, "data", "market_data.db")

TTL_DAILY = 86400              # companyfacts 缓存 TTL 1 天
MIN_INTERVAL = 0.15            # SEC 官方限流 10 req/s → 最小间隔 0.15s
RESTATE_PCT = 0.005            # 重述阈值：同 period 值变化 >0.5% → restated=True

EDGAR_TICKERS = "https://www.sec.gov/files/company_tickers.json"
EDGAR_FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{0:010d}.json"

# 概念映射：多 tag 候选（tag_switch 消歧：同 period 多 tag 取 filed 最新者）
CONCEPTS_US = {
    "revenue": {
        "tags": ["RevenueFromContractWithCustomerExcludingAssessedTax",
                 "SalesRevenueNet", "Revenues"],
        "kind": "flow",
    },
    "net_income": {
        "tags": ["NetLoss", "NetIncomeLoss"],
        "kind": "flow",
    },
    "ocf": {
        "tags": ["NetCashProvidedByUsedInOperatingActivities",
                 "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
        "kind": "flow",
    },
    "assets": {"tags": ["Assets"], "kind": "instant"},
    "equity": {
        "tags": ["StockholdersEquity",
                 "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
        "kind": "instant",
    },
    "eps": {"tags": ["EarningsPerShareDiluted"], "kind": "instant"},
}

# CN 概念 → cn_financials 列
CONCEPTS_CN = {
    "total_assets": "total_assets",
    "total_liabilities": "total_liabilities",
    "total_equity": "total_equity",
    "revenue": "total_revenue",
    "net_income": "net_profit",
}

# 本工具概念名 → pit-fundamentals CSV concept 名
CONCEPT_TO_CSV = {
    "revenue": "Revenue",
    "net_income": "NetIncome",
    "ocf": "OperatingCashFlow",
    "assets": "Assets",
    "equity": "StockholdersEquity",
    "eps": "EPSDiluted",
}

DEFAULT_REFERENCE = os.path.join(
    BASE, "..", "_research", "pit-fundamentals", "data", "pit_fundamentals_history.csv")


# --------------------------------------------------------------------------
# 通用小工具
# --------------------------------------------------------------------------
def _is_cn(t):
    """纯数字 stkcd → CN 来源（可用 --source 覆盖）。"""
    return str(t).strip().isdigit()


def _pdate(s):
    """ISO 日期字符串 → date；解析失败返回 None。"""
    if not s:
        return None
    s = str(s).strip()
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _lag_days(filed, period_end):
    fd, pe = _pdate(filed), _pdate(period_end)
    if fd is None or pe is None:
        return None
    return (fd - pe).days


def _restated(orig, latest):
    """同 period 多版本，latest 相对 original 变化 >0.5% → 重述。"""
    if orig is None or latest is None:
        return False
    if orig == 0:
        return latest != 0
    return abs(latest - orig) / abs(orig) > RESTATE_PCT


def _out(obj, exit_code=0):
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    return exit_code


# --------------------------------------------------------------------------
# SEC companyfacts 获取（含 data/pit/<TICKER>.json 独立 TTL 缓存）
# --------------------------------------------------------------------------
def _cik_lookup(ticker):
    """ticker → (cik, name)。company_tickers.json 全量映射。"""
    data, _ = FT.cached_get(EDGAR_TICKERS, ttl=TTL_DAILY, min_interval=MIN_INTERVAL)
    t = ticker.upper()
    if isinstance(data, dict):
        for row in data.values():
            if isinstance(row, dict) and str(row.get("ticker", "")).upper() == t:
                return int(row["cik_str"]), row.get("title", "")
    return None, None


def get_companyfacts(ticker, ttl=TTL_DAILY):
    """拉取 companyfacts 全量 JSON。

    返回 (facts, source, cik, entity_name, fetched_at)：
      source = cache_file（data/pit 缓存未过期）| network（新拉取）。
    网络失败：有缓存文件 → 回退（source=cache_stale）；无缓存 → 抛异常。
    """
    t = str(ticker).strip().upper()
    cik, name = _cik_lookup(t)
    if not cik:
        raise ValueError(f"{ticker}: 未在 SEC company_tickers 找到 CIK")
    cache_path = os.path.join(PIT_DIR, f"{t}.json")
    if os.path.exists(cache_path):
        mtime = os.path.getmtime(cache_path)
        if time.time() - mtime < ttl:
            with open(cache_path, encoding="utf-8") as f:
                data = json.load(f)
            return data, "cache_file", cik, name, datetime.fromtimestamp(mtime).isoformat()
    try:
        data, _src = FT.cached_get(EDGAR_FACTS.format(cik), ttl=ttl, min_interval=MIN_INTERVAL)
    except Exception:
        if os.path.exists(cache_path):
            with open(cache_path, encoding="utf-8") as f:
                data = json.load(f)
            return data, "cache_stale", cik, name, datetime.fromtimestamp(
                os.path.getmtime(cache_path)).isoformat()
        raise
    os.makedirs(PIT_DIR, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return data, "network", cik, name, datetime.now().isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# 事件表解析（公共：fengvaluation.py 复用）
# --------------------------------------------------------------------------
def parse_us_events(facts, tags, concept, unit_contains=None):
    """从 companyfacts 解析 facts.us-gaap.<tag>.units[] 为事件列表。

    默认取美元单位（unit 名含 'usd'，如 'USD'、'USD/shares' 的 EPS 均可）；
    unit_contains 可覆盖（如股数概念取 'share'）。
    每项事件: {concept, xbrl_tag, period_start, period_end, fiscal_year,
              value, filed, form, fp, fy, accn, lag_days}
    同 (tag, period_end, filed, accn) 去重；未做重述标记（由 tag_restatements 做）。
    """
    gaap = (facts or {}).get("facts", {}).get("us-gaap", {})
    events = []
    for tag in tags:
        node = gaap.get(tag)
        if not node:
            continue
        for unit, items in (node.get("units") or {}).items():
            ul = str(unit).lower()
            if unit_contains is not None:
                if unit_contains.lower() not in ul:
                    continue
            elif "usd" not in ul:
                continue
            for it in items or []:
                end = it.get("end")
                if not end:
                    continue
                val = it.get("val")
                if val is None:
                    continue
                start = it.get("start") or end
                filed = it.get("filed")
                events.append({
                    "concept": concept,
                    "xbrl_tag": tag,
                    "period_start": start,
                    "period_end": end,
                    "fiscal_year": it.get("fy") or end[:4],
                    "value": val,
                    "filed": filed,
                    "form": it.get("form"),
                    "fp": it.get("fp"),
                    "fy": it.get("fy"),
                    "accn": it.get("accn"),
                    "lag_days": _lag_days(filed, end),
                })
    # 去重（同 tag + period + filed + accn）
    seen = set()
    out = []
    for e in events:
        k = (e["xbrl_tag"], e["period_end"], e["filed"], e["accn"])
        if k in seen:
            continue
        seen.add(k)
        out.append(e)
    out.sort(key=lambda e: (e["period_end"], e["filed"] or "", e["xbrl_tag"]))
    return out


def tag_restatements(events):
    """按 (concept, period_end) 分组做 vintage 标记。

    同 period 多版本全保留；每组：
      original_value = 最早 filed 版本值
      latest_value   = 最晚 filed 版本值
      restated       = |latest−original|/|original| > 0.5%
      canonical_tag  = 该 period 下 filed 最新的 tag（tag_switch 消歧结果）
    """
    by_period = {}
    for e in events:
        by_period.setdefault((e["concept"], e["period_end"]), []).append(e)
    for (_, pend), evs in by_period.items():
        evs.sort(key=lambda e: (e["filed"] or "", e["xbrl_tag"]))
        orig, last = evs[0], evs[-1]
        restated = _restated(orig["value"], last["value"])
        for e in evs:
            e["original_value"] = orig["value"]
            e["latest_value"] = last["value"]
            e["restated"] = restated
            e["canonical_tag"] = last["xbrl_tag"]
    return events


def us_events(facts, concept):
    """concept 名 → 完整事件表（多 tag 合并 + vintage 标记）。"""
    spec = CONCEPTS_US.get(concept)
    if not spec:
        raise ValueError(f"未知 US 概念: {concept}（可用: {', '.join(CONCEPTS_US)}）")
    events = parse_us_events(facts, spec["tags"], concept)
    return tag_restatements(events)


def canonical_tag_of(events):
    """概念级 canonical tag：数据延伸到最近 period 的 tag（pit-fundamentals 法）。"""
    if not events:
        return None
    by_tag = {}
    for e in events:
        by_tag.setdefault(e["xbrl_tag"], []).append(e)
    return max(by_tag, key=lambda t: (max(e["period_end"] for e in by_tag[t]),
                                      len(by_tag[t])))


# --------------------------------------------------------------------------
# CN：cn_financials 直读
# --------------------------------------------------------------------------
def _cn_filed_date(declare_date):
    """declare_date → (最早得知日, filed_reliable)。

    'None'/''/'0' → (None, False)（历史老数据，宁可标记不可伪造）；
    '2015-03-13,2014-10-24' 多日期 → 取最早（首次可知）。
    """
    s = str(declare_date or "").strip()
    if s in ("None", "", "0"):
        return None, False
    days = []
    for part in s.split(","):
        d = _pdate(part)
        if d is not None:
            days.append(d)
    if not days:
        return None, False
    return min(days), True


def cn_events(stkcd, concept):
    """cn_financials → 事件表（filed=declare_date 最早日；'None' → filed_reliable=False）。"""
    col = CONCEPTS_CN.get(concept)
    if not col:
        raise ValueError(f"未知 CN 概念: {concept}（可用: {', '.join(CONCEPTS_CN)}）")
    if not os.path.exists(DB_PATH):
        raise RuntimeError(f"本地库不存在: {DB_PATH}")
    con = sqlite3.connect(DB_PATH)
    try:
        rows = con.execute(
            f"SELECT accper, declare_date, typrep, {col} FROM cn_financials "
            "WHERE stkcd = ? AND accper IS NOT NULL AND accper != '' "
            "AND {0} IS NOT NULL ORDER BY accper".format(col),
            (str(stkcd).strip(),)).fetchall()
    finally:
        con.close()
    events = []
    for accper, declare_date, typrep, val in rows:
        filed, reliable = _cn_filed_date(declare_date)
        events.append({
            "concept": concept,
            "xbrl_tag": col,
            "period_start": accper,
            "period_end": accper,
            "fiscal_year": accper[:4],
            "value": val,
            "filed": filed.isoformat() if filed else None,
            "filed_reliable": reliable,
            "form": "CN-" + str(typrep or "?"),
            "fp": None,
            "fy": None,
            "accn": None,
            "lag_days": _lag_days(filed.isoformat() if filed else None, accper),
        })
    return tag_restatements(events)


# --------------------------------------------------------------------------
# PIT as-of 查询
# --------------------------------------------------------------------------
def asof_query(events, as_of):
    """单概念 as-of 查询：最新可见值（filed <= as_of 的最晚 period 的最晚版本）。

    可见性严格限定在 as-of 可见的版本内计算 original/latest/restated，
    保证查询结果与当日实际可知一致。
    """
    d = _pdate(as_of)
    if d is None:
        raise ValueError(f"as-of 日期无法解析: {as_of}")
    vis = [e for e in events
           if e.get("filed") and _pdate(e["filed"]) is not None
           and _pdate(e["filed"]) <= d]
    vis.sort(key=lambda e: (e["period_end"], e["filed"] or ""))
    if not vis:
        return {"found": False, "as_of": d.isoformat(), "note": "截至该日无可见事件"}
    pend = vis[-1]["period_end"]
    period_vis = [e for e in vis if e["period_end"] == pend]
    latest = period_vis[-1]
    orig = period_vis[0]
    return {
        "found": True,
        "as_of": d.isoformat(),
        "concept": latest["concept"],
        "period_start": latest["period_start"],
        "period_end": latest["period_end"],
        "fiscal_year": latest["fiscal_year"],
        "value": latest["value"],
        "filed": latest["filed"],
        "form": latest["form"],
        "accn": latest["accn"],
        "xbrl_tag": latest["xbrl_tag"],
        "original_value": orig["value"],
        "latest_value": latest["value"],
        "restated": _restated(orig["value"], latest["value"]),
        "filed_reliable": latest.get("filed_reliable", True),
        "n_visible_events": len(period_vis),
    }


def _visible(events, as_of):
    d = _pdate(as_of)
    if d is None:
        return events
    return [e for e in events
            if e.get("filed") and _pdate(e["filed"]) is not None
            and _pdate(e["filed"]) <= d]


# --------------------------------------------------------------------------
# 子命令：us / cn
# --------------------------------------------------------------------------
def _concept_arg(args, default_concepts):
    if args.all_concepts:
        return list(default_concepts)
    if args.concept:
        return [args.concept]
    return []


def cmd_us(args):
    t = args.ticker.upper()
    try:
        facts, src, cik, name, fetched_at = get_companyfacts(t)
    except Exception as e:
        return _out({"error": f"companyfacts 拉取失败: {e}",
                     "hint": "检查网络或 FENG_HTTP_UA 环境变量；已缓存则下次自动回退"}, exit_code=1)
    concepts = _concept_arg(args, CONCEPTS_US)
    if not concepts:
        return _out({"error": "请指定 --concept 或 --all-concepts",
                     "available": list(CONCEPTS_US)}, exit_code=2)
    meta = {
        "source": "sec-companyfacts",
        "ticker": t,
        "cik": cik,
        "entity_name": name,
        "fetched_at": fetched_at,
        "fetch_source": src,
        "cache_file": os.path.join(PIT_DIR, f"{t}.json"),
        "cache_ttl_days": TTL_DAILY // 86400,
    }
    concepts_out = {}
    asof_out = {}
    all_events = []
    for c in concepts:
        try:
            events = us_events(facts, c)
        except ValueError as e:
            return _out({"error": str(e)}, exit_code=2)
        events = _visible(events, args.as_of)
        all_events.extend(events)
        concepts_out[c] = {
            "xbrl_tag": canonical_tag_of(events),
            "tag_candidates": CONCEPTS_US[c]["tags"],
            "kind": CONCEPTS_US[c]["kind"],
            "n_events": len(events),
            "n_periods": len({e["period_end"] for e in events}),
        }
        if args.as_of:
            asof_out[c] = asof_query(us_events(facts, c), args.as_of)
    out = {"meta": meta, "concepts": concepts_out, "events": all_events}
    if args.as_of:
        out["asof"] = asof_out
    return _out(out)


def cmd_cn(args):
    t = str(args.stkcd).strip()
    concepts = _concept_arg(args, CONCEPTS_CN)
    if not concepts:
        return _out({"error": "请指定 --concept 或 --all-concepts",
                     "available": list(CONCEPTS_CN)}, exit_code=2)
    meta = {
        "source": "cn_financials",
        "stkcd": t,
        "db": DB_PATH,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "note": "declare_date='None' 的历史行 filed_reliable=False（日期不可靠宁可标记不伪造）",
    }
    concepts_out = {}
    asof_out = {}
    all_events = []
    for c in concepts:
        try:
            events = cn_events(t, c)
        except (RuntimeError, ValueError) as e:
            return _out({"error": str(e)}, exit_code=1)
        visible = events if not args.as_of else _visible(events, args.as_of)
        all_events.extend(visible)
        concepts_out[c] = {
            "column": CONCEPTS_CN[c],
            "n_events": len(visible),
            "n_periods": len({e["period_end"] for e in visible}),
            "n_unreliable_filed": sum(1 for e in visible if not e.get("filed_reliable", True)),
        }
        if args.as_of:
            asof_out[c] = asof_query(events, args.as_of)
    out = {"meta": meta, "concepts": concepts_out, "events": all_events}
    if args.as_of:
        out["asof"] = asof_out
    return _out(out)


# --------------------------------------------------------------------------
# 子命令：asof
# --------------------------------------------------------------------------
def cmd_asof(args):
    if not args.as_of:
        return _out({"error": "asof 需要 --as-of YYYY-MM-DD"}, exit_code=2)
    if args.concept not in CONCEPTS_US and args.concept not in CONCEPTS_CN:
        return _out({"error": f"未知概念 {args.concept}",
                     "us": list(CONCEPTS_US), "cn": list(CONCEPTS_CN)}, exit_code=2)
    src = (args.source or ("cn" if _is_cn(args.ticker) else "us")).lower()
    try:
        if src == "cn":
            events = cn_events(args.ticker, args.concept)
            return _out(asof_query(events, args.as_of))
        t = args.ticker.upper()
        facts, fsrc, cik, name, fetched_at = get_companyfacts(t)
        events = us_events(facts, args.concept)
        res = asof_query(events, args.as_of)
        res["meta"] = {"source": "sec-companyfacts", "ticker": t, "cik": cik,
                       "entity_name": name, "fetched_at": fetched_at,
                       "fetch_source": fsrc, "concept": args.concept,
                       "xbrl_tag": canonical_tag_of(events)}
        return _out(res)
    except Exception as e:
        return _out({"error": str(e)}, exit_code=1)


# --------------------------------------------------------------------------
# 子命令：verify（与 pit-fundamentals CSV 对拍）
# --------------------------------------------------------------------------
def cmd_verify(args):
    t = args.ticker.upper()
    ref = args.reference or DEFAULT_REFERENCE
    if not os.path.exists(ref):
        return _out({"error": f"参考 CSV 不存在: {ref}（可用 --reference 指定）"}, exit_code=1)
    concept = args.concept or "revenue"
    csv_concept = CONCEPT_TO_CSV.get(concept)
    if not csv_concept:
        return _out({"error": f"概念 {concept} 无 CSV 对应（可用: {', '.join(CONCEPT_TO_CSV)}）"},
                    exit_code=2)
    try:
        facts, fsrc, cik, name, fetched_at = get_companyfacts(t)
    except Exception as e:
        return _out({"error": f"companyfacts 拉取失败: {e}"}, exit_code=1)
    ours = us_events(facts, concept)
    our_by_period = {}
    for e in ours:
        our_by_period.setdefault(e["period_end"], []).append(e)
    with open(ref, encoding="utf-8") as f:
        ref_rows = list(csv.DictReader(f))
    ref_map = {r["period_end"]: r for r in ref_rows
               if r.get("ticker") == t and r.get("concept") == csv_concept}
    if not ref_map:
        return _out({"error": f"CSV 中无 {t} 的 {csv_concept} 行"}, exit_code=1)
    rows = []
    for pend in sorted(ref_map, reverse=True):
        r = ref_map[pend]
        evs = our_by_period.get(pend, [])
        if not evs:
            rows.append({"period_end": pend, "our_first_filed": None,
                         "csv_first_filed": r.get("first_filed"),
                         "filed_diff_days": None, "our_value": None,
                         "csv_value": r.get("original_value"),
                         "value_pct_diff": None, "verdict": "OURS_MISSING"})
            continue
        first = min(evs, key=lambda e: e["filed"] or "")
        last = max(evs, key=lambda e: e["filed"] or "")
        csv_filed = _pdate(r.get("first_filed"))
        our_filed = _pdate(first["filed"])
        fd_diff = (our_filed - csv_filed).days if our_filed and csv_filed else None
        csv_val = _csv_float(r.get("original_value"))
        pct = None
        if csv_val and first["value"]:
            pct = (first["value"] - csv_val) / abs(csv_val) * 100.0
        filed_ok = fd_diff is not None and abs(fd_diff) <= 1
        val_ok = pct is not None and abs(pct) < 0.5
        rows.append({
            "period_end": pend,
            "fiscal_year": r.get("fiscal_year"),
            "our_first_filed": first["filed"],
            "csv_first_filed": r.get("first_filed"),
            "filed_diff_days": fd_diff,
            "our_original_value": first["value"],
            "our_latest_value": last["value"],
            "csv_original_value": csv_val,
            "value_pct_diff": round(pct, 4) if pct is not None else None,
            "our_xbrl_tag": first["xbrl_tag"],
            "csv_xbrl_tag": r.get("xbrl_tag"),
            "verdict": ("MATCH" if (filed_ok and val_ok)
                        else "FILED_DIFF" if not filed_ok else "VALUE_DIFF"),
        })
    n_match = sum(1 for x in rows if x["verdict"] == "MATCH")
    return _out({
        "meta": {"source": "sec-companyfacts", "ticker": t, "cik": cik,
                 "entity_name": name, "fetched_at": fetched_at, "concept": concept,
                 "csv_concept": csv_concept, "reference": ref,
                 "note": "our_first_filed=该 period 最早 filed；CSV first_filed 应≈它"},
        "summary": {"n_periods": len(rows), "n_match": n_match,
                    "n_filed_diff": sum(1 for x in rows if x["verdict"] == "FILED_DIFF"),
                    "n_value_diff": sum(1 for x in rows if x["verdict"] == "VALUE_DIFF"),
                    "n_missing": sum(1 for x in rows if x["verdict"] == "OURS_MISSING")},
        "periods": rows,
    })


def _csv_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# 子命令：status
# --------------------------------------------------------------------------
def cmd_status(args):
    t = str(args.ticker).strip()
    src = (args.source or ("cn" if _is_cn(t) else "us")).lower()
    if src == "cn":
        if not os.path.exists(DB_PATH):
            return _out({"error": f"本地库不存在: {DB_PATH}"}, exit_code=1)
        con = sqlite3.connect(DB_PATH)
        try:
            total = con.execute("SELECT COUNT(*) FROM cn_financials WHERE stkcd = ?",
                                (t,)).fetchone()[0]
            reliable = con.execute(
                "SELECT COUNT(*) FROM cn_financials WHERE stkcd = ? AND declare_date != 'None'",
                (t,)).fetchone()[0]
        finally:
            con.close()
        return _out({
            "meta": {"source": "cn_financials", "stkcd": t, "db": DB_PATH,
                     "fetched_at": datetime.now().isoformat(timespec="seconds")},
            "cache": None,
            "rows_in_db": total,
            "filed_reliable_rows": reliable,
            "concepts_available": list(CONCEPTS_CN),
        })
    t = t.upper()
    cache_path = os.path.join(PIT_DIR, f"{t}.json")
    cache_info = None
    if os.path.exists(cache_path):
        mtime = os.path.getmtime(cache_path)
        age_h = (time.time() - mtime) / 3600.0
        cache_info = {"file": cache_path, "fetched_at": datetime.fromtimestamp(mtime).isoformat(),
                      "age_hours": round(age_h, 2), "fresh": age_h < TTL_DAILY / 3600.0}
    concepts_out = {}
    if cache_info:
        with open(cache_path, encoding="utf-8") as f:
            facts = json.load(f)
        for c in CONCEPTS_US:
            try:
                events = us_events(facts, c)
            except ValueError:
                events = []
            visible = _visible(events, args.as_of)
            concepts_out[c] = {
                "xbrl_tag": canonical_tag_of(events),
                "n_events": len(events),
                "n_visible_asof": len(visible),
                "n_periods": len({e["period_end"] for e in events}),
                "n_restated": sum(1 for e in events if e.get("restated")),
            }
    return _out({
        "meta": {"source": "sec-companyfacts", "ticker": t, "cache_dir": PIT_DIR,
                 "fetched_at": datetime.now().isoformat(timespec="seconds")},
        "cache": cache_info,
        "concepts": concepts_out,
        "hint": "未缓存时先运行: python tools/fengpit.py us <TICKER> --all-concepts",
    })


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="fengpit — PIT 双轴可见性（事件日 × 得知日，SEC companyfacts / cn_financials）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_us = sub.add_parser("us", help="美股 companyfacts 事件表（SEC）")
    p_us.add_argument("ticker")
    p_us.add_argument("--concept", choices=list(CONCEPTS_US))
    p_us.add_argument("--as-of", help="YYYY-MM-DD，仅输出 filed<=as-of 的可见事件")
    p_us.add_argument("--all-concepts", action="store_true")
    p_us.set_defaults(func=cmd_us)

    p_cn = sub.add_parser("cn", help="A 股 cn_financials 事件表（本地库）")
    p_cn.add_argument("stkcd")
    p_cn.add_argument("--concept", choices=list(CONCEPTS_CN))
    p_cn.add_argument("--as-of", help="YYYY-MM-DD，仅输出 declare_date<=as-of 的可见事件")
    p_cn.add_argument("--all-concepts", action="store_true")
    p_cn.set_defaults(func=cmd_cn)

    p_asof = sub.add_parser("asof", help="单值 PIT 查询（最新可见值）")
    p_asof.add_argument("ticker")
    p_asof.add_argument("--concept", required=True, choices=list(CONCEPTS_US) + list(CONCEPTS_CN))
    p_asof.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    p_asof.add_argument("--source", choices=["us", "cn"])
    p_asof.set_defaults(func=cmd_asof)

    p_v = sub.add_parser("verify", help="与 pit-fundamentals CSV 对拍 first_filed")
    p_v.add_argument("ticker")
    p_v.add_argument("--reference", help="pit_fundamentals_history.csv 路径（默认自动找）")
    p_v.add_argument("--concept", choices=list(CONCEPT_TO_CSV), default="revenue")
    p_v.set_defaults(func=cmd_verify)

    p_s = sub.add_parser("status", help="缓存状态 / 可见事件数")
    p_s.add_argument("ticker")
    p_s.add_argument("--as-of", help="YYYY-MM-DD")
    p_s.add_argument("--source", choices=["us", "cn"])
    p_s.set_defaults(func=cmd_status)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
