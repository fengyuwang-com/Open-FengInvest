#!/usr/bin/env python3
"""
FengInvest SEC EDGAR 一手资料工具（美股年报/季报/13F 原始文件）

来源：SEC EDGAR 官方公开接口（免费，无 API key）：
  - CIK 映射:   https://www.sec.gov/files/company_tickers.json
  - 公司提交:   https://data.sec.gov/submissions/CIK##########.json
  - 全文:       https://www.sec.gov/Archives/edgar/data/<cik>/<accession>/<doc>

价值：一手资料原则（ai-berkshire earnings-review）——美股公司的 10-K/10-Q/
13F 直接从 SEC 取原始文件，不经过二手源转述；filings 带 filingDate，
天然满足 PIT 点及时纪律（分析只能用决策时点已公开的财报）。

════════ edgartools 数据层（可选依赖，5.x）════════
新命令 facts / filings（新路径）/ financials / ownership / 13f 以 edgartools
为数据层（HTTP/XBRL 部分直接复用其实现，替代自建请求 + fengthrottle）：

  路径关系：
    - lookup / fetch / filings(降级时)  → 旧路径：fengthrottle + SEC 原生 JSON
    - facts      → EntityFacts（Company(ticker).get_facts()）；逐 fact 保留
                    filed→filing_date（得知日）+ period_end（财报期）+ form
                    （PIT 双轴，与 tools/fengpit.py 同源思路）；--as-of 走
                    FactQuery.as_of 过滤（filing_date <= as_of 的可见事件）
    - filings    → 按 CIK 拉 submissions（EntityFilings）；year/quarter 为
                    【提交日/日历口径】非财报期口径（edgartools get_filings
                    同款语义，docstring 明示）；edgartools 缺失时自动回退
                    旧 fengthrottle 路径（行为与升级前一致）
    - financials → 单份 filing 的 XBRL 标准化三表（Financials.extract +
                    14 个标准化 getter；期间列排序按官方 _order_period_columns）
    - ownership  → Form 3/4/5 内部人交易（ownership 包；交易类型/日期/数量/
                    10b5-1 标记）；--insider-buys 聚合净买入（信号观察，不下结论）
    - 13f        → 13F-HR 持仓（XML 2013+ / TXT 2012-，ThirteenF.holdings）

  限流：edgartools 内置 9 req/s 令牌桶；fengthrottle 仅服务旧路径，不改动。
  UA：优先 EDGAR_IDENTITY 环境变量（"Name email" 格式）；未设但 FENG_HTTP_UA
      含邮箱时自动映射（可直接作身份）；都没有则报错提示，不硬编码邮箱。
  可选依赖：import 失败 → 新命令输出 {"error": "edgartools not installed",
      "hint": "pip install edgartools"}（exit 1，绝不崩溃）；filings 例外，
      自动降级回旧路径。
  已知坑（edgartools 官方）：Archives 永久缓存曾缓存空响应（官方已修）；
      filed 是 EDGAR 接受日，非新闻发布日。

旧命令 lookup / fetch / filings（降级路径）行为保持不变，只增不改。

用法：
  python tools/fengsec.py lookup AAPL                    # 查 CIK
  python tools/fengsec.py filings AAPL --form 10-K --limit 3   # 列最近年报
  python tools/fengsec.py fetch AAPL <ACCESSION>         # 抓全文（存 data/sec/）
  python tools/fengsec.py facts AAPL --as-of 2025-06-30 --concept revenue  # PIT 可见事件
  python tools/fengsec.py facts AAPL --concept all --pit                   # 全部版本+restated 标记
  python tools/fengsec.py filings 0000320193 --limit 5 --year 2024        # 按 CIK / 按提交年
  python tools/fengsec.py financials AAPL --form 10-K --fiscal-year 2024  # 标准化三表+14 指标
  python tools/fengsec.py ownership AAPL --limit 10 --insider-buys        # 内部人交易+净买入聚合
  python tools/fengsec.py 13f 0001067983 --quarter 2025Q2                 # 13F 持仓（伯克希尔）
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fengthrottle as FT

# ── edgartools 可选依赖（新命令数据层）─────────────────────────────────────
# 新包名顶层模块为 edgartools；部分发行版（含本机 5.48.0 wheel）顶层模块为 edgar。
try:
    import edgartools as EG
except ImportError:
    try:
        import edgar as EG
    except ImportError:
        EG = None

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEC_DIR = os.path.join(BASE, "data", "sec")

EDGAR_TICKERS = "https://www.sec.gov/files/company_tickers.json"
EDGAR_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{0:010d}.json"
EDGAR_ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{doc}"

TTL_DAILY = 86400          # 公司元数据/提交列表缓存 1 天
MIN_INTERVAL = 0.15        # SEC 官方 10 req/s → 最小间隔 0.15s

RESTATE_PCT = 0.005        # 重述阈值：同 period 值变化 >0.5% → restated=True（fengpit 同款）

# 概念映射（tag 消歧：同概念多候选 tag，取 filing_date 最新者）
CONCEPT_TAGS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    "net_income": ["NetIncomeLoss"],
    "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "assets": ["Assets"],
    "equity": ["StockholdersEquity"],
    "eps": ["EarningsPerShareDiluted"],
}

# Financials 14 个标准化指标（13 标量 + get_financial_metrics 字典）
SCALAR_METRICS = [
    ("revenue", "get_revenue"),
    ("net_income", "get_net_income"),
    ("operating_income", "get_operating_income"),
    ("total_assets", "get_total_assets"),
    ("total_liabilities", "get_total_liabilities"),
    ("stockholders_equity", "get_stockholders_equity"),
    ("operating_cash_flow", "get_operating_cash_flow"),
    ("free_cash_flow", "get_free_cash_flow"),
    ("capital_expenditures", "get_capital_expenditures"),
    ("current_assets", "get_current_assets"),
    ("current_liabilities", "get_current_liabilities"),
    ("shares_outstanding_basic", "get_shares_outstanding_basic"),
    ("shares_outstanding_diluted", "get_shares_outstanding_diluted"),
]

# 与 edgar.financials._NON_PERIOD_COLUMNS 同款（RenderedStatement.to_dataframe
# 的元数据列，非期间值列；本地复制避免依赖私有常量）
NON_PERIOD_COLUMNS = frozenset(
    {"concept", "label", "level", "abstract", "dimension", "is_breakdown", "unit", "point_in_time"}
)

# 官方 getter 的 label 正则未覆盖部分公司措辞（如 AAPL "Cash generated by
# operating activities" 不匹配 'Net Cash...' 模式 → get_operating_cash_flow 返
# None）。兜底走官方同一管道：_get_standardized_concept_by_xbrl + 官方
# standardization 映射 key（概念级匹配，非手填数字）。
METRIC_FALLBACK = {
    "operating_cash_flow": ("cashflow", ["Net Cash from Operating Activities"]),
    "capital_expenditures": ("cashflow", ["Payments for Property, Plant and Equipment"]),
}


# ── edgartools 数据层通用助手 ───────────────────────────────────────────────

def _eg_version():
    return getattr(EG, "__version__", "unknown") if EG else None


def _fetched_at():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _edgar_error(msg, hint=None):
    """打印错误 JSON（新命令统一错误格式），返回 exit code 1。"""
    out = {"error": msg}
    if hint:
        out["hint"] = hint
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 1


def _identity_error():
    """SEC 身份 UA 检查。返回 None 表示就绪；否则返回 (error, hint)。

    规则：EDGAR_IDENTITY 显式优先；未设但 FENG_HTTP_UA 含邮箱 → 自动映射
    （可直接作身份）；都没有 → 报错提示设置，不硬编码任何个人邮箱。
    """
    if os.environ.get("EDGAR_IDENTITY"):
        return None
    ua = os.environ.get("FENG_HTTP_UA")
    if ua and "@" in ua:
        # 自动映射：FENG_HTTP_UA 含邮箱 → 直接作 SEC 身份（"Name email" 格式）
        os.environ["EDGAR_IDENTITY"] = ua
        return None
    if ua:
        return ("EDGAR_IDENTITY 未设置且 FENG_HTTP_UA 不含邮箱"
                "（SEC 身份需 \"Name email\" 格式，含联系邮箱）",
                'set EDGAR_IDENTITY="你的名字 邮箱"（例：set EDGAR_IDENTITY="Zhang San zhangsan@example.com"）')
    return ("EDGAR_IDENTITY 未设置（edgartools 请求 SEC 需要身份 UA）",
            'set EDGAR_IDENTITY="你的名字 邮箱"（例：set EDGAR_IDENTITY="Zhang San zhangsan@example.com"）')


def _eg_guard():
    """新命令前置：edgartools 已装 + 身份 UA 就绪。不满足时已打印错误，返回 False。"""
    if EG is None:
        _edgar_error("edgartools not installed", "pip install edgartools")
        return False
    ident = _identity_error()
    if ident:
        _edgar_error(*ident)
        return False
    return True


def _eg_meta(**extra):
    """新命令统一 meta：source / fetched_at / 版本号。"""
    meta = {"source": "edgartools", "fetched_at": _fetched_at(),
            "edgartools_version": _eg_version()}
    meta.update(extra)
    return meta


def _json_safe(v):
    """把 pandas/numpy 值转成 JSON 可序列化的 Python 原生值。"""
    if v is None:
        return None
    if isinstance(v, bool):
        return bool(v)
    if isinstance(v, (str, int, float)):
        return v
    if isinstance(v, (list, tuple)):
        return [_json_safe(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _json_safe(x) for k, x in v.items()}
    if isinstance(v, (datetime, date)):
        return str(v)
    try:
        import pandas as pd
        if pd.isna(v):  # 标量缺失值（np.nan / pd.NA / NaT）
            return None
    except Exception:
        pass
    if hasattr(v, "item"):  # numpy 标量
        try:
            return _json_safe(v.item())
        except Exception:
            pass
    return str(v)


# ── 旧路径（fengthrottle，行为保持不变）────────────────────────────────────

def _cik_lookup(ticker):
    """ticker → (cik, name)。company_tickers.json 全量映射（~1 万家公司）。"""
    data, _ = FT.cached_get(EDGAR_TICKERS, ttl=TTL_DAILY, min_interval=MIN_INTERVAL)
    t = ticker.upper()
    for row in data.values():
        if row.get("ticker") == t:
            return int(row["cik_str"]), row.get("title", "")
    return None, None


def _submissions(cik):
    """公司提交记录（含 recent filings 数组，最新在前）。"""
    data, _ = FT.cached_get(EDGAR_SUBMISSIONS.format(cik), ttl=TTL_DAILY, min_interval=MIN_INTERVAL)
    return data


def _recent_filings(cik, form=None, limit=10):
    """从 submissions.recent 提取 (accession, form, filing_date, doc, desc)。"""
    data = _submissions(cik)
    recent = (data.get("filings") or {}).get("recent") or {}
    out = []
    for i in range(len(recent.get("accessionNumber", []))):
        f = recent["form"][i]
        if form and f != form:
            continue
        out.append({
            "accession": recent["accessionNumber"][i],
            "form": f,
            "filing_date": recent["filingDate"][i],
            "doc": recent["primaryDocument"][i] if i < len(recent.get("primaryDocument", [])) else "",
            "description": (recent.get("primaryDocDescription") or [""] * len(recent["accessionNumber"]))[i],
        })
        if len(out) >= limit:
            break
    return out


def _filings_legacy(args):
    """旧路径：fengthrottle + submissions JSON（edgartools 缺失时降级，行为与升级前一致）。"""
    cik, name = _cik_lookup(args.ticker)
    if not cik:
        print(json.dumps({"error": f"ticker {args.ticker.upper()} 未找到"}, indent=2, ensure_ascii=False))
        return 1
    files = _recent_filings(cik, form=args.form, limit=args.limit)
    print(json.dumps({
        "ticker": args.ticker.upper(), "cik": cik, "name": name,
        "form_filter": args.form, "count": len(files),
        "filings": files,
        "note": "filing_date 即 PIT 点及时基准：分析只能用当天已公开的财报",
    }, indent=2, ensure_ascii=False))
    return 0


def cmd_lookup(args):
    cik, name = _cik_lookup(args.ticker)
    if not cik:
        print(json.dumps({"error": f"ticker {args.ticker.upper()} 未找到（SEC company_tickers.json 无此代码）",
                          "hint": "仅美股；港股/A股不在 SEC 覆盖范围"}, indent=2, ensure_ascii=False))
        return 1
    print(json.dumps({"ticker": args.ticker.upper(), "cik": cik, "name": name}, indent=2, ensure_ascii=False))
    return 0


def cmd_filings(args):
    """filings：edgartools 可用 → 新路径（支持 CIK / --year / --quarter）；
    缺失 → 降级旧 fengthrottle 路径（行为不变）。"""
    if EG is None:
        return _filings_legacy(args)
    ident = _identity_error()
    if ident:
        return _edgar_error(*ident)
    try:
        if str(args.ticker).isdigit():
            company = EG.Company(int(args.ticker))
        else:
            company = EG.Company(args.ticker)
        form = args.form if args.form and args.form != "ALL" else None
        kwargs = {"form": form, "amendments": False}
        if args.year is not None:
            kwargs["year"] = args.year
        if args.quarter is not None:
            kwargs["quarter"] = args.quarter
        # 两段式：先近期页（1 次请求）；按提交年过滤且近期页无命中 → 全量历史重试
        filings = company.get_filings(**kwargs, trigger_full_load=False)
        if args.year is not None and len(filings) == 0:
            filings = company.get_filings(**kwargs, trigger_full_load=True)
        limit = min(args.limit, len(filings))
        rows = []
        for i in range(limit):
            f = filings[i]
            rows.append({
                "accession": f.accession_number,
                "form": f.form,
                "filing_date": str(f.filing_date),
                "period_of_report": getattr(f, "report_date", None) or None,
                "primary_doc": getattr(f, "primary_document", None) or "",
            })
        out = {
            "ticker": getattr(company, "get_ticker", lambda: args.ticker.upper())(),
            "cik": company.cik, "name": company.name,
            "form_filter": args.form, "count": len(rows),
            "filings": rows,
            "note": ("filing_date 即 PIT 点及时基准：分析只能用当天已公开的财报；"
                     "year/quarter 为提交日（日历）口径，非财报期口径"),
            "meta": _eg_meta(),
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    except Exception as e:
        return _edgar_error(str(e), "edgartools 路径失败；如网络/UA 问题可排查 EDGAR_IDENTITY")


def cmd_fetch(args):
    cik, name = _cik_lookup(args.ticker)
    if not cik:
        print(json.dumps({"error": f"ticker {args.ticker.upper()} 未找到"}, indent=2, ensure_ascii=False))
        return 1
    acc = args.accession
    # 全文检索 recent 数组（苹果等高频提交公司 10-K 常不在最近 50 条内）
    data = _submissions(cik)
    recent = (data.get("filings") or {}).get("recent") or {}
    match = None
    for i in range(len(recent.get("accessionNumber", []))):
        if recent["accessionNumber"][i] == acc:
            match = {
                "accession": acc,
                "form": recent["form"][i],
                "filing_date": recent["filingDate"][i],
                "doc": recent["primaryDocument"][i] if i < len(recent.get("primaryDocument", [])) else "",
            }
            break
    if not match or not match["doc"]:
        print(json.dumps({"error": f"accession {acc} 未找到（不在 recent 提交列表）",
                          "hint": f"python tools/fengsec.py filings {args.ticker.upper()} --limit 50"},
                         indent=2, ensure_ascii=False))
        return 1
    doc = match["doc"]
    url = EDGAR_ARCHIVE.format(cik=cik, accession=acc.replace("-", ""), doc=doc)
    body, source = FT.cached_get(url, ttl=TTL_DAILY, min_interval=MIN_INTERVAL)
    os.makedirs(SEC_DIR, exist_ok=True)
    fname = f"{args.ticker.upper()}_{acc.replace('-', '')}_{match['form']}.htm"
    path = os.path.join(SEC_DIR, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body if isinstance(body, str) else json.dumps(body))
    print(json.dumps({
        "ticker": args.ticker.upper(), "cik": cik, "name": name,
        "accession": acc, "form": match["form"], "filing_date": match["filing_date"],
        "saved_to": path, "chars": os.path.getsize(path), "source": source,
    }, indent=2, ensure_ascii=False))
    return 0


# ── 新命令：facts（companyfacts 逐 fact 双轴事件表，PIT）────────────────────

def _fact_value(fact):
    """优先 numeric_value，否则原始字符串值。"""
    if fact.numeric_value is not None:
        return _json_safe(fact.numeric_value)
    return _json_safe(fact.value)


def _is_restated(prev, cur):
    """同 period 相邻版本重述判定：|cur−prev|/|prev| > 0.5%（fengpit 同款阈值）。"""
    if prev is None or cur is None:
        return False
    if prev == cur:
        return False
    if prev == 0 or cur == 0:  # 从零到非零 / 归零：视为重述
        return True
    return abs(cur - prev) / abs(prev) > RESTATE_PCT


def _tag_rows(facts, tag, as_of):
    """按 tag 拉事实（as_of 先行过滤）：概念带命名空间前缀（us-gaap:xxx），
    故在 as_of 过滤后用本地名精确匹配；无命中再兜底标签精确匹配。

    注意：FactQuery 过滤器是累积 AND 的，不能在同一 query 上先 exact 后 fuzzy
    重试（空集过滤器会一直为空），每次匹配必须基于新 query。"""
    q = facts.query()
    if as_of:
        q = q.as_of(as_of)
    all_rows = q.execute()
    exact = [f for f in all_rows if (f.concept or "").split(":")[-1] == tag]
    if exact:
        return exact
    # 兜底：human-readable 标签精确匹配
    lbl = [f for f in all_rows if (f.label or "").strip().lower() == tag.lower()]
    return lbl


def cmd_facts(args):
    if not _eg_guard():
        return 1
    try:
        as_of = date.fromisoformat(args.as_of) if args.as_of else None
    except ValueError:
        return _edgar_error(f"无效日期格式 {args.as_of!r}，应为 YYYY-MM-DD")
    try:
        company = EG.Company(args.ticker)
        facts = company.get_facts()
        if facts is None:
            return _edgar_error(f"未找到 {args.ticker.upper()} 的 companyfacts（CIK {company.cik}）")

        # 概念 → tag 列表（tag 消歧取 filing_date 最新者）
        concept = args.concept
        tag_selected = None
        if concept == "all":
            rows = _all_rows(facts, as_of)
        else:
            candidates = CONCEPT_TAGS[concept]
            best = None  # (max_filing_date, order_index, tag)
            for idx, tag in enumerate(candidates):
                rows = _tag_rows(facts, tag, as_of)
                if not rows:
                    continue
                last = max((f.filing_date for f in rows if f.filing_date), default=None)
                key = (last or date.min, -idx)
                if best is None or key > best[0]:
                    best = (key, tag, rows)
            if best is None:
                return _edgar_error(f"概念 {concept}（{candidates}）无可用事实", "可尝试 --concept all")
            _, tag_selected, rows = best

        # 事件表
        events = []
        for f in rows:
            events.append({
                "concept": concept if concept != "all" else f.concept,
                "period_start": str(f.period_start) if f.period_start else None,
                "period_end": str(f.period_end) if f.period_end else None,
                "form_type": f.form_type,
                "value": _fact_value(f),
                "filing_date": str(f.filing_date) if f.filing_date else None,
                "accession": f.accession,
            })

        # 排序 + 去重 / vintage
        if args.pit:
            events.sort(key=lambda e: (e["period_end"] or "", e["filing_date"] or "", e["accession"]))
            # restated 标记：同 (concept, period_end) 相邻版本值变化 >0.5%
            by_period = {}
            for e in events:
                by_period.setdefault((e["concept"], e["period_end"]), []).append(e)
            for group in by_period.values():
                prev = None
                for e in group:
                    cur = e["value"]
                    e["restated"] = _is_restated(prev, cur)
                    prev = cur
        else:
            # 默认：每 (concept, period_end) 只保留 filing_date 最新版本（可见事件）
            latest = {}
            for e in events:
                key = (e["concept"], e["period_end"])
                old = latest.get(key)
                if old is None or (e["filing_date"] or "") > (old["filing_date"] or ""):
                    latest[key] = e
            events = sorted(latest.values(), key=lambda e: (e["period_end"] or "", e["concept"]))

        out = {
            "ticker": args.ticker.upper(), "cik": company.cik, "name": company.name,
            "concept": concept, "as_of": args.as_of, "pit": bool(args.pit),
            "tag": tag_selected,
            "count": len(events),
            "events": events,
            "note": ("filing_date=得知日（SEC 接受日，非新闻发布日）；--as-of 只含 filing_date<=as_of "
                     "的可见事件；默认每期保留最新版本，--pit 保留全部 vintage 并标 restated"),
            "meta": _eg_meta(),
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    except Exception as e:
        return _edgar_error(str(e))


def _all_rows(facts, as_of):
    q = facts.query()
    if as_of:
        q = q.as_of(as_of)
    return q.execute()


# ── 新命令：financials（单份 filing 的 XBRL 标准化三表 + 14 指标）────────────

def _order_period_columns_guarded(rendered, period_cols):
    """期间列排序按官方实现 _order_period_columns（edgar.financials）；
    私有 API 缺失/变动时回退 DataFrame 原列序。"""
    try:
        from edgar.financials import _order_period_columns
        return _order_period_columns(rendered, period_cols)
    except Exception:
        return period_cols


def _extract_statement(financials, attr):
    """单张报表 → {periods: 期间列（官方序）, rows: [{label, concept, 期间值...}]}"""
    statement = getattr(financials, attr)()
    if statement is None:
        return None
    try:
        rendered = statement.render(standard=True)
        df = rendered.to_dataframe()
    except Exception:
        rendered, df = None, statement.to_dataframe()
    if df is None or len(df) == 0:
        return None
    period_cols = [c for c in df.columns if c not in NON_PERIOD_COLUMNS]
    if rendered is not None:
        period_cols = _order_period_columns_guarded(rendered, period_cols)
    rows = []
    for _, r in df.iterrows():
        row = {"label": _json_safe(r.get("label")), "concept": _json_safe(r.get("concept"))}
        for p in period_cols:
            row[p] = _json_safe(r.get(p))
        rows.append(row)
    return {"periods": period_cols, "rows": rows}


def cmd_financials(args):
    if not _eg_guard():
        return 1
    try:
        company = EG.Company(args.ticker)
        form = args.form or "10-K"
        # 两段式：先近期页；fiscal-year 在近期页无命中 → 全量历史重试
        filings = company.get_filings(form=form, amendments=False, trigger_full_load=False)
        target = None
        if args.fiscal_year is not None:
            for i in range(len(filings)):
                f = filings[i]
                rdate = str(getattr(f, "report_date", "") or "")
                if rdate[:4] == str(args.fiscal_year):
                    target = f
                    break
            if target is None:
                filings = company.get_filings(form=form, amendments=False, trigger_full_load=True)
                for i in range(len(filings)):
                    f = filings[i]
                    rdate = str(getattr(f, "report_date", "") or "")
                    if rdate[:4] == str(args.fiscal_year):
                        target = f
                        break
        else:
            if len(filings) > 0:
                target = filings[0]
        if target is None:
            return _edgar_error(
                f"未找到 {args.ticker.upper()} 的 {form}"
                + (f"（report_date 年份 = {args.fiscal_year}）" if args.fiscal_year else ""))
        financials = EG.Financials.extract(target)
        if financials is None:
            return _edgar_error(f"filing {target.accession_number} 无 XBRL 数据，无法提取标准化三表")

        # 14 个标准化指标（13 标量 getter + get_financial_metrics 字典）
        metrics = {}
        for mname, mgetter in SCALAR_METRICS:
            try:
                val = getattr(financials, mgetter)()
            except Exception:
                val = None
            if val is None and mname in METRIC_FALLBACK:
                stype, keys = METRIC_FALLBACK[mname]
                try:
                    val = financials._get_standardized_concept_by_xbrl(stype, keys, 0)
                except Exception:
                    val = None
            metrics[mname] = _json_safe(val)
        # free_cash_flow 官方公式兜底：OCF − |capex|
        if (metrics.get("free_cash_flow") is None
                and isinstance(metrics.get("operating_cash_flow"), (int, float))
                and isinstance(metrics.get("capital_expenditures"), (int, float))):
            metrics["free_cash_flow"] = _json_safe(
                metrics["operating_cash_flow"] - abs(metrics["capital_expenditures"]))
        try:
            metrics["financial_metrics"] = _json_safe(financials.get_financial_metrics())
        except Exception:
            metrics["financial_metrics"] = None

        statements = {
            "income": _extract_statement(financials, "income_statement"),
            "balance": _extract_statement(financials, "balance_sheet"),
            "cash_flow": _extract_statement(financials, "cash_flow_statement"),
        }

        out = {
            "ticker": args.ticker.upper(), "cik": company.cik, "name": company.name,
            "form": form, "fiscal_year": args.fiscal_year,
            "filing": {
                "accession": target.accession_number,
                "form": target.form,
                "filing_date": str(target.filing_date),
                "period_of_report": getattr(target, "report_date", None) or None,
                "primary_doc": getattr(target, "primary_document", None) or "",
            },
            "statements": statements,
            "metrics": metrics,
            "note": ("标准化指标取当期（period_offset=0，官方 _order_period_columns 排序）；"
                     "期间列为 XBRL 原始数值（负数=流出，未做符号翻转）；"
                     "cash-flow 指标若官方 label 正则未命中，已用官方 standardization 映射兜底"),
            "meta": _eg_meta(),
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    except Exception as e:
        return _edgar_error(str(e))


# ── 新命令：ownership（Form 3/4/5 内部人交易）───────────────────────────────

def _transaction_row(f, own, act):
    return {
        "accession": f.accession_number,
        "form": own.form or f.form,
        "filing_date": str(f.filing_date),
        "insider": own.insider_name,
        "position": own.position,
        "aff10b5_one": own.aff10b5_one,   # 10b5-1 交易计划标记（True/False/None）
        "code": act.code,
        "transaction_type": act.transaction_type,
        "security_type": act.security_type,
        "security": act.security_title,
        "underlying_security": act.underlying_security,
        "shares": _json_safe(act.shares_numeric if act.shares_numeric is not None else act.shares),
        "price": _json_safe(act.price_numeric),
        "value": _json_safe(act.value_numeric),
    }


def cmd_ownership(args):
    if not _eg_guard():
        return 1
    try:
        company = EG.Company(args.ticker)
        filings = company.get_filings(form=["3", "4", "5"], amendments=False,
                                      trigger_full_load=False)
        limit = min(args.limit or 10, len(filings))
        filings_out, transactions, skipped = [], [], 0
        for i in range(limit):
            f = filings[i]
            try:
                own = f.obj()  # Form3 / Form4 / Form5
            except Exception:
                skipped += 1
                continue
            if own is None:
                skipped += 1
                continue
            acts = own.get_transaction_activities()
            filings_out.append({
                "accession": f.accession_number,
                "form": own.form or f.form,
                "filing_date": str(f.filing_date),
                "insider": own.insider_name,
                "position": own.position,
                "aff10b5_one": own.aff10b5_one,
                "transactions": len(acts),
            })
            for act in acts:
                transactions.append(_transaction_row(f, own, act))

        out = {
            "ticker": args.ticker.upper(), "cik": company.cik, "name": company.name,
            "limit": limit, "filings_processed": len(filings_out),
            "filings_skipped": skipped,
            "filings": filings_out,
            "count": len(transactions),
            "transactions": transactions,
            "meta": _eg_meta(),
        }
        if args.insider_buys:
            out["insider_buys"] = _aggregate_insider_buys(transactions, filings_out)
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    except Exception as e:
        return _edgar_error(str(e))


def _aggregate_insider_buys(transactions, filings_out):
    """净买入聚合（参考 Stocksera「30 日净买入」思路：只做聚合，不下投资结论）。
    仅统计公开市场 purchase/sale（P/S 代码，market_trades），排除期权行权/赠予等。"""
    dates = [f["filing_date"] for f in filings_out if f.get("filing_date")]
    buys = [t for t in transactions if t["transaction_type"] == "purchase"]
    sells = [t for t in transactions if t["transaction_type"] == "sale"]

    def _sum(rows, key):
        return sum(r[key] for r in rows if isinstance(r.get(key), (int, float)))

    agg = {
        "window": {"from": min(dates) if dates else None, "to": max(dates) if dates else None},
        "purchases": {"count": len(buys), "shares": _sum(buys, "shares"), "value": _sum(buys, "value")},
        "sales": {"count": len(sells), "shares": _sum(sells, "shares"), "value": _sum(sells, "value")},
        "net_shares": _sum(buys, "shares") - _sum(sells, "shares"),
        "net_value": _sum(buys, "value") - _sum(sells, "value"),
        "note": "聚合仅作内部人增持信号观察（未做市值占比），不构成投资结论",
    }
    return agg


# ── 新命令：13f（13F-HR 持仓，XML 2013+ / TXT 2012-）───────────────────────

def cmd_13f(args):
    if not _eg_guard():
        return 1
    try:
        company = EG.Company(args.ticker)
        # 两段式：先近期页；--quarter 在近期页无命中 → 全量历史重试
        filings = company.get_filings(form=["13F-HR", "13F-HR/A"], amendments=False,
                                      trigger_full_load=False)
        target = None
        if args.quarter:
            year = int(args.quarter[:4])
            q = int(args.quarter[-1])

            def _match(f):
                rdate = str(getattr(f, "report_date", "") or "")
                return (len(rdate) >= 7 and rdate[:4] == str(year)
                        and (int(rdate[5:7]) - 1) // 3 + 1 == q)

            for i in range(len(filings)):
                if _match(filings[i]):
                    target = filings[i]
                    break
            if target is None:
                filings = company.get_filings(form=["13F-HR", "13F-HR/A"], amendments=False,
                                              trigger_full_load=True)
                for i in range(len(filings)):
                    if _match(filings[i]):
                        target = filings[i]
                        break
        else:
            if len(filings) > 0:
                target = filings[0]
        if target is None:
            return _edgar_error(f"未找到 {args.ticker.upper()} 的 13F-HR"
                                + (f"（report_date 季度 = {args.quarter}）" if args.quarter else ""))
        thirteen_f = EG.ThirteenF(target)
        holdings = thirteen_f.holdings
        if holdings is None or len(holdings) == 0:
            return _edgar_error(f"13F {target.accession_number} 无持仓数据（infotable 缺失/解析失败）")
        rows = []
        for _, r in holdings.iterrows():
            rows.append({
                "issuer": _json_safe(r.get("Issuer")),
                "class": _json_safe(r.get("Class")),
                "cusip": _json_safe(r.get("Cusip")),
                "ticker": _json_safe(r.get("Ticker")),
                "shares": _json_safe(r.get("SharesPrnAmount")),
                "value": _json_safe(r.get("Value")),
                "put_call": _json_safe(r.get("PutCall")) if "PutCall" in holdings.columns else None,
            })
        total_value = sum(r["value"] for r in rows if isinstance(r["value"], (int, float)))
        out = {
            "manager": {"cik": company.cik, "name": company.name},
            "filing": {
                "accession": target.accession_number,
                "form": target.form,
                "filing_date": str(target.filing_date),
                "period_of_report": getattr(target, "report_date", None) or None,
            },
            "holdings_count": len(rows),
            "total_value": total_value,
            "holdings": rows,
            "note": ("13F 为机构管理人季度持仓（XML 2013+ / TXT 2012- 自动解析）；"
                     "value 已按 filing 单位归一为美元；按 CUSIP+PutCall 聚合"),
            "meta": _eg_meta(),
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    except Exception as e:
        return _edgar_error(str(e))


# ── 入口 ───────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="FengInvest SEC EDGAR 一手资料（美股 10-K/10-Q/13F）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_lookup = sub.add_parser("lookup", help="ticker → CIK")
    p_lookup.add_argument("ticker")
    p_lookup.set_defaults(func=cmd_lookup)

    p_filings = sub.add_parser("filings", help="列最近提交（edgartools 新路径；缺失时降级旧路径）")
    p_filings.add_argument("ticker", help="TICKER 或纯数字 CIK")
    p_filings.add_argument("--form", default=None, help="过滤表单：10-K/10-Q/8-K/13F-HR…（ALL=全部）")
    p_filings.add_argument("--limit", type=int, default=10)
    p_filings.add_argument("--year", type=int, default=None,
                           help="提交年（日历口径，非财报期；例 2024）")
    p_filings.add_argument("--quarter", type=int, choices=[1, 2, 3, 4], default=None,
                           help="提交季度（日历口径，与 --year 搭配）")
    p_filings.set_defaults(func=cmd_filings)

    p_fetch = sub.add_parser("fetch", help="抓全文到 data/sec/")
    p_fetch.add_argument("ticker")
    p_fetch.add_argument("accession", help="如 000032019322000047")
    p_fetch.set_defaults(func=cmd_fetch)

    p_facts = sub.add_parser("facts", help="companyfacts 逐 fact 双轴事件表（PIT，得知日= filing_date）")
    p_facts.add_argument("ticker")
    p_facts.add_argument("--as-of", default=None, help="YYYY-MM-DD：只输出 filing_date<=as_of 的可见事件")
    p_facts.add_argument("--concept", default="all",
                         choices=["revenue", "net_income", "ocf", "assets", "equity", "eps", "all"],
                         help="概念（多 tag 候选取 filing_date 最新消歧；默认 all）")
    p_facts.add_argument("--pit", action="store_true",
                         help="保留全部版本（vintage 不去重）并标 restated（同 period 值变化>0.5%%）")
    p_facts.set_defaults(func=cmd_facts)

    p_financials = sub.add_parser("financials", help="单份 filing 的 XBRL 标准化三表 + 14 指标")
    p_financials.add_argument("ticker")
    p_financials.add_argument("--form", default="10-K", choices=["10-K", "10-Q"])
    p_financials.add_argument("--fiscal-year", type=int, default=None,
                              help="按 report_date 年份选 filing（默认最近一份）")
    p_financials.set_defaults(func=cmd_financials)

    p_ownership = sub.add_parser("ownership", help="Form 3/4/5 内部人交易")
    p_ownership.add_argument("ticker")
    p_ownership.add_argument("--limit", type=int, default=10, help="处理最近 N 份 ownership filing")
    p_ownership.add_argument("--insider-buys", action="store_true",
                             help="过滤并聚合净买入（公开市场 P/S，参考 Stocksera 思路，不下结论）")
    p_ownership.set_defaults(func=cmd_ownership)

    p_13f = sub.add_parser("13f", help="13F-HR 机构持仓（XML 2013+ / TXT 2012-）")
    p_13f.add_argument("ticker", help="管理人 TICKER 或纯数字 CIK（如伯克希尔 0001067983）")
    p_13f.add_argument("--quarter", default=None, help="YYYYQ1 形式：按 report_date 季度选报告（默认最近）")
    p_13f.set_defaults(func=cmd_13f)

    args = ap.parse_args()
    try:
        return args.func(args)
    except Exception as e:
        hint = ""
        if "403" in str(e):
            hint = ("；SEC 拒绝 UA——请先设置联系方式："
                    'set FENG_HTTP_UA="你的名字 邮箱"（例：set FENG_HTTP_UA="Zhang San zhangsan@example.com"）')
        print(json.dumps({"error": str(e), "hint": hint.strip("；") or None},
                         ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
