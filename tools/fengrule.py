#!/usr/bin/env python3
"""fengrule — L1 硬纪律检查. Output JSON.

Usage:
    python fengrule.py 0700.HK          # full L1 check
    python fengrule.py 0700.HK --json   # raw data
    python fengrule.py LVHI --asset-type etf --etf-metrics metrics.json
        # ETF 资产级模式：公司科目规则 ABSTAIN，改走基金口径规则

公司路径数据源（2026-09-13 换源，yfinance 全域 403 已退役）：
    K线序列: 本地 data/market_data.db > 腾讯 fqkline > akshare(美股) > Yahoo chart（复用 fengdata 转换件）
    基本面:   本地库 fundamentals / cn_financials 表（yfinance 403 后无实时基本面源，
              拿不到即 None 弃权——看不见≠不好，不得据缺失判红）
    科目查不到历史序列 → light=YELLOW「数据不足/跳过」，绝不崩溃。
Dependencies: stdlib(sqlite3/urllib) + fengdata(同目录 import)；akshare 仅美股备源惰性导入
"""

import json, os, re, sqlite3, sys
import statistics
from datetime import datetime

os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

# 取数层（2026-09-13 换源）：复用 fengdata 的腾讯代码映射/Yahoo 件，不重写取数优先级本身。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fengdata

_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "market_data.db")
_MIN_SERIES_BARS = 30  # 低于此根数视为取数失败，继续降级


def _num(v):
    """DB 值 → float；None/NaN → None。"""
    import math
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _ma(closes, n):
    return sum(closes[-n:]) / n if len(closes) >= n else None


def _latest(rows, i):
    """取第一个非空值（rows 已按报告期降序）。"""
    for r in rows:
        v = _num(r[i])
        if v is not None:
            return v
    return None


# ── K线序列：本地库 > 腾讯 fqkline > akshare(美股) > Yahoo chart ──
_SERIES_CACHE = {}


def _db_closes(ticker, n=400):
    """本地 market_data.db：daily_data 经 indices.ticker 关联，返回 (closes升序, as_of日期)。"""
    try:
        conn = sqlite3.connect(_DB_PATH, timeout=5)
        try:
            row = conn.execute("SELECT id FROM indices WHERE ticker = ?", (ticker,)).fetchone()
            if not row:
                return None, None
            rows = conn.execute(
                "SELECT date, close FROM daily_data WHERE index_id = ? AND close IS NOT NULL "
                "ORDER BY date DESC LIMIT ?", (row[0], n)).fetchall()
        finally:
            conn.close()
        closes = [_num(r[1]) for r in rows]
        pairs = [(r[0], c) for r, c in zip(rows, closes) if c is not None]
        if not pairs:
            return None, None
        pairs.reverse()
        return [c for _, c in pairs], pairs[-1][0]
    except Exception:
        return None, None


def _tencent_closes(ticker, n=400):
    """腾讯 qfq 日K（qt 现价接口无历史，用 ifzq fqkline）。美股该端点只有零星数据 → 按不足处理。"""
    try:
        import urllib.request
        code = fengdata._to_tencent_code(ticker)
        if not code:
            return None, None
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,{n},qfq"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        d = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "ignore"))
        node = (d.get("data") or {}).get(code) or {}
        rows = node.get("qfqday") or node.get("day") or []
        pairs = []
        for r in rows:
            try:
                c = _num(r[2])
            except (IndexError, TypeError, ValueError):
                continue
            if c is not None:
                pairs.append((str(r[0]), c))
        if len(pairs) < _MIN_SERIES_BARS:
            return None, None
        return [c for _, c in pairs], pairs[-1][0]
    except Exception:
        return None, None


def _akshare_us_closes(ticker, n=400):
    """美股/美ETF 备源：akshare stock_us_daily（新浪）。yfinance 403 后美股本地缺席时的活路。"""
    t = (ticker or "").upper()
    if not re.match(r"^[A-Z][A-Z.]{0,8}$", t):
        return None, None
    try:
        import akshare as ak
        df = ak.stock_us_daily(symbol=t.replace(".", "-"))
        closes = [_num(v) for v in list(df["close"])[-n:]]
        pairs = [c for c in closes if c is not None]
        if len(pairs) < _MIN_SERIES_BARS:
            return None, None
        as_of = str(list(df["date"])[-1])[:10]
        return pairs, as_of
    except Exception:
        return None, None


def _yahoo_closes(ticker, n=400):
    """最后兜底 Yahoo chart HTTP（本机现状 403，大概率失败，保留链路完整）。"""
    try:
        import urllib.request
        sym = fengdata._to_yahoo_code(ticker)
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
               f"?range=2y&interval=1d&includePrePost=false")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                                   "Accept": "application/json"})
        d = json.loads(urllib.request.urlopen(req, timeout=15).read().decode("utf-8"))
        res = d["chart"]["result"][0]
        raw = (res.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
        closes = [c for c in (_num(v) for v in raw) if c is not None]
        if len(closes) < _MIN_SERIES_BARS:
            return None, None
        ts = res.get("timestamp") or []
        as_of = datetime.utcfromtimestamp(ts[-1]).strftime("%Y-%m-%d") if ts else None
        return closes[-n:], as_of
    except Exception:
        return None, None


def _series(ticker):
    """K线序列统一入口。返回 {"closes","as_of","source"} 或 None（全部源失败=数据不可得）。"""
    if ticker in _SERIES_CACHE:
        return _SERIES_CACHE[ticker]
    out = None
    for name, fn in (("local_db", _db_closes), ("tencent_qfq", _tencent_closes),
                     ("akshare_us", _akshare_us_closes), ("yahoo_chart", _yahoo_closes)):
        closes, as_of = fn(ticker)
        if closes and len(closes) >= _MIN_SERIES_BARS:
            out = {"closes": closes, "as_of": as_of, "source": name}
            break
    _SERIES_CACHE[ticker] = out
    return out


# ── 基本面：本地库 fundamentals（US/HK 快照）+ cn_financials（A股财报 fengfuyao）──
_FUND_CACHE = {}


def _get_fundamentals(ticker):
    """科目级取数：每科目独立可为 None（不可得）。语义：看不见≠不好——None 只触发弃权，不触发判红。"""
    if ticker in _FUND_CACHE:
        return _FUND_CACHE[ticker]
    f = {k: None for k in ("roe_pct", "revenue_latest", "revenue_prev", "net_margin_pct",
                           "revenue_growth_pct", "fcf_latest", "ocf_latest", "capex_latest",
                           "trailing_pe", "pb", "dividend_yield_pct", "source")}
    try:
        conn = sqlite3.connect(_DB_PATH, timeout=5)
        try:
            row = conn.execute("""SELECT f.return_on_equity,f.profit_margin,f.revenue_growth,f.free_cashflow,
                                         f.operating_cashflow,f.capital_expenditure,f.trailing_pe,f.price_to_book,
                                         f.dividend_yield,f.enterprise_value,f.enterprise_to_revenue,f.updated_at
                                  FROM fundamentals f JOIN indices i ON i.id=f.index_id WHERE i.ticker=?""",
                               (ticker,)).fetchone()
        finally:
            conn.close()
    except Exception:
        row = None
    if row:
        (f["roe_pct"], f["net_margin_pct"], f["revenue_growth_pct"], f["fcf_latest"], f["ocf_latest"],
         f["capex_latest"], f["trailing_pe"], f["pb"], f["dividend_yield_pct"],
         _ev, _ev_rev, _upd) = (_num(x) for x in row)
        for k in ("roe_pct", "net_margin_pct", "revenue_growth_pct"):  # 比率科目为小数口径 → %
            if f[k] is not None:
                f[k] *= 100.0
        if f["net_margin_pct"] is not None and abs(f["net_margin_pct"]) > 150:
            f["net_margin_pct"] = None
        if f["roe_pct"] is not None and abs(f["roe_pct"]) > 300:
            f["roe_pct"] = None
        if f["revenue_growth_pct"] is not None and abs(f["revenue_growth_pct"]) > 500:
            f["revenue_growth_pct"] = None
        if _ev and _ev_rev:
            f["revenue_latest"] = _ev / _ev_rev  # 营收由 EV/EV-Revenue 反推（单期，无 prev）
        f["source"] = f"fundamentals_snapshot@{_upd}" if _upd else "fundamentals_snapshot"
    # A股：cn_financials 补营收/利润/ROE/现金流/PE/PB（fundamentals 快照缺席或科目为空时）
    m = re.match(r"^(\d{6})\.(SS|SH|SZ)$", ticker.upper())
    if m:
        try:
            conn = sqlite3.connect(_DB_PATH, timeout=5)
            try:
                rows = conn.execute("""SELECT accper,total_revenue,weighted_avg_roe,net_margin,
                                              operating_cf_net,capital_expenditure,revenue_growth_A,pe_ttm,pb
                                       FROM cn_financials WHERE stkcd=? ORDER BY accper DESC LIMIT 12""",
                                    (m.group(1),)).fetchall()
            finally:
                conn.close()
        except Exception:
            rows = []
        if rows:
            revs = [(_num(r[1]), r[0]) for r in rows if _num(r[1]) is not None]
            if revs:
                f["revenue_latest"], _la = revs[0]
                _ly = str(int(_la[:4]) - 1)  # 最新报告期非年报（如 Q1）→ 优先对比上年同期
                cand = next((p for p in revs[1:] if p[1][:4] == _ly), None)
                if cand is None:
                    ann = [p for p in revs[1:] if p[1].endswith("12-31")]
                    cand = ann[0] if ann else None
                f["revenue_prev"] = cand[0] if cand else None
                if f["revenue_prev"]:
                    f["revenue_growth_pct"] = (f["revenue_latest"] / f["revenue_prev"] - 1) * 100.0
            for key, i, scale in (("roe_pct", 2, None), ("net_margin_pct", 3, 100.0),
                                  ("revenue_growth_pct", 6, 100.0),
                                  ("ocf_latest", 4, None), ("capex_latest", 5, None),
                                  ("trailing_pe", 7, None), ("pb", 8, None)):
                if f[key] is None:
                    v = _latest(rows, i)
                    if v is not None:
                        f[key] = v * scale if scale else v
            if f["fcf_latest"] is None and f["ocf_latest"] is not None:
                f["fcf_latest"] = f["ocf_latest"] - abs(f["capex_latest"] or 0.0)
            f["source"] = (f["source"] + "+cn_financials" if f["source"]
                           else f"cn_financials@{rows[0][0]}")
    if all(v is None for k, v in f.items() if k != "source"):
        f = None
    _FUND_CACHE[ticker] = f
    return f


# 文献：本规则=趋势确认+极端估值双条件。极端估值判断（PE<10/PB<1/股息率>5%）属估值类，
# → Liu-Stambaugh-Yuan 2019（A股价值首选 EP 口径，PB 用于 A 股有口径风险）；趋势部分无直接单篇标尺
def check_no_knife(ticker: str) -> dict:
    """L1-1: 不接飞刀（趋势 MA 来自 _series 多源序列；基本面科目不可得按弃权，不判红）"""
    s = _series(ticker)
    closes = (s or {}).get("closes") or []
    price = closes[-1] if closes else None
    ma50 = _ma(closes, 50)
    ma120 = _ma(closes, 120)

    f = _get_fundamentals(ticker) or {}
    roe_pct = f.get("roe_pct")

    rev_shrinking = None
    if f.get("revenue_growth_pct") is not None:
        rev_shrinking = f["revenue_growth_pct"] < 0

    # FCF 为负的解释：OCF 为正且资本开支占比高 → 投入周期而非恶化（docs/03-discipline.md 核心原则C）
    fcf = f.get("fcf_latest")
    ocf = f.get("ocf_latest")
    capex = f.get("capex_latest")
    fcf_negative = fcf < 0 if fcf is not None else None
    fcf_capex_driven = None
    if fcf_negative and ocf is not None:
        fcf_capex_driven = ocf > 0 and (capex is None or ocf > abs(capex) * 0.5)

    # fundamentals_bad: True/False=有证据；None=科目不可得（弃权）——弃权不得触发 RED
    _evidence = [fcf_negative, rev_shrinking]
    if all(e is None for e in _evidence):
        fundamentals_bad = None
    else:
        fundamentals_bad = bool((fcf_negative and not fcf_capex_driven) or rev_shrinking)

    _pe, _pb, _dy = f.get("trailing_pe"), f.get("pb"), f.get("dividend_yield_pct")
    if _pe is None and _pb is None and _dy is None:
        extreme_value = None  # 估值三科目全不可得 → 极端估值不可判
    else:
        extreme_value = bool((_pe is not None and _pe < 10) or (_pb is not None and _pb < 1)
                             or (_dy is not None and _dy > 5))

    # Determine level
    if ma50 is not None and ma120 is not None and ma50 < ma120:
        if fundamentals_bad:
            # RED: hard block
            level = "RED"
            signal = "硬拦截"
            reason = f"MA50({ma50:.2f}) < MA120({ma120:.2f}) + 基本面恶化"
        elif fundamentals_bad is None:
            level = "YELLOW"
            signal = "条件通过"
            reason = (f"MA50({ma50:.2f}) < MA120({ma120:.2f})，趋势恶化但基本面科目不可得，"
                      f"按弃权处理（不判红）。数据截至 {(s or {}).get('as_of')}")
        elif roe_pct is not None and roe_pct > 10 and extreme_value:
            level = "YELLOW"
            signal = "条件通过(DCA)"
            reason = f"MA50({ma50:.2f}) < MA120({ma120:.2f}) + 真价值+极端估值, 可DCA入场"
        else:
            level = "YELLOW"
            signal = "条件通过"
            reason = f"MA50({ma50:.2f}) < MA120({ma120:.2f}) + 基本面尚可, DCA条件通过"
    elif price is None or ma50 is None or ma120 is None:
        level = "YELLOW"
        signal = "数据不足"
        reason = (f"趋势K线数据不足(需120根, 实得{len(closes)}根, "
                  f"源={(s or {}).get('source') or '全部失败'})，飞刀检查跳过，按弃权处理")
    else:
        level = "GREEN"
        signal = "PASS"
        reason = f"Price({price:.2f}) >= MA50({ma50:.2f}) >= MA120({ma120:.2f})" if ma50 and ma120 else "趋势右侧"

    return {
        "check": "no_knife",
        "label": "不接飞刀",
        "light": level,
        "signal": signal,
        "price": price,
        "ma50": ma50,
        "ma120": ma120,
        "price_above_ma50": price > ma50 if ma50 and price is not None else None,
        "ma50_above_ma120": ma50 > ma120 if ma50 and ma120 else None,
        "roe_pct": roe_pct,
        "fcf_negative": fcf_negative,
        "revenue_shrinking": rev_shrinking,
        "fundamentals_bad": fundamentals_bad,
        "extreme_valuation": extreme_value,
        "series_source": (s or {}).get("source"),
        "series_as_of": (s or {}).get("as_of"),
        "fundamentals_source": f.get("source"),
        "reason": reason,
    }


def check_no_fomo(ticker: str) -> dict:
    """L1-2: 不蹭热点（月涨幅>30%硬拦截；序列不可得→弃权黄，不崩溃）"""
    s = _series(ticker)
    closes = (s or {}).get("closes") or []
    price = closes[-1] if closes else None
    m1 = (closes[-1] / closes[-22] - 1) * 100 if len(closes) >= 22 else None

    if m1 is None:
        level = "YELLOW"
        signal = "数据不足"
        reason = (f"K线序列不足(需22根, 实得{len(closes)}根, "
                  f"源={(s or {}).get('source') or '全部失败'})，热点检查跳过，按弃权处理")
    elif m1 > 30:
        level = "RED"
        signal = "硬拦截"
        reason = f"上月涨幅{m1:.0f}% > 30%, 禁止买入"
    else:
        level = "GREEN"
        signal = "PASS"
        reason = f"上月涨幅{m1:.1f}% < 30%"

    return {
        "check": "no_fomo",
        "label": "不蹭热点",
        "light": level,
        "signal": signal,
        "return_1m_pct": round(m1, 1) if m1 is not None else None,
        "series_source": (s or {}).get("source"),
        "series_as_of": (s or {}).get("as_of"),
        "reason": reason,
    }


def check_no_leverage(ticker: str) -> dict:
    """L1-3: 杠杆=0"""
    return {
        "check": "no_leverage",
        "label": "杠杆=0",
        "light": "GREEN",
        "signal": "PASS",
        "reason": "无杠杆（框架硬规则，默认通过）",
        "note": "交易账户杠杆=0是铁律，此检查需用户自行确认。脚本不访问券商账户。"
    }


def check_true_value(ticker: str) -> dict:
    """L1-4: 真价值（FCF/营收/利润率来自本地库；科目不可得按弃权，绝不判红）"""
    f = _get_fundamentals(ticker)
    if not f:
        return {
            "check": "true_value",
            "label": "真价值",
            "light": "YELLOW",
            "signal": "弃权",
            "has_cashflow": None,
            "has_revenue": None,
            "is_profitable": None,
            "fundamentals_source": None,
            "reason": "FCF/营收/利润率科目本地不可得，按弃权处理（看不见≠不好，不判红）",
        }

    fcf, rev, margin = f.get("fcf_latest"), f.get("revenue_latest"), f.get("net_margin_pct")
    has_cashflow = fcf > 0 if fcf is not None else None
    has_revenue = rev > 0 if rev is not None else None
    is_profitable = margin > 0 if margin is not None else None

    if is_profitable is False or has_revenue is False:
        # RED 只由正向证据触发：确认亏损或确认无营收
        level, signal = "RED", "假价值"
        reason = "本地财报确认无营收支撑或持续亏损"
    elif has_cashflow is True and has_revenue is True and is_profitable is True:
        level, signal = "GREEN", "PASS"
        reason = (f"真实消费需求 + 正现金流(FCF={fcf/1e9:.1f}B) + 盈利(利润率{margin:.1f}%"
                  f")，源={f.get('source')}")
    elif has_cashflow is False and has_revenue is True and is_profitable is True:
        level, signal = "YELLOW", "存疑"
        reason = f"有收入和利润但FCF为负(FCF={fcf/1e9:.1f}B)，需进一步确认"
    else:
        _missing = [name for name, v in (("FCF", has_cashflow), ("营收", has_revenue),
                                         ("利润率", is_profitable)) if v is None]
        level, signal = "YELLOW", "弃权"
        reason = (f"已得科目无负面证据，{('、'.join(_missing))}科目不可得，按弃权处理。源={f.get('source')}")

    return {
        "check": "true_value",
        "label": "真价值",
        "light": level,
        "signal": signal,
        "has_cashflow": has_cashflow,
        "has_revenue": has_revenue,
        "is_profitable": is_profitable,
        "fundamentals_source": f.get("source"),
        "reason": reason,
    }


def _market_index_for(ticker: str) -> str:
    """大盘位置基准指数。2638 是【上证综指】的绝对点位分界（docs/03-discipline.md），
    故 .SZ 票必须用 000001.SS 检查——旧版映射到深证成指(~万点级)导致永远 >2638 恒假绿。
    港股用恒生、其余（美股）用标普做年线分界。"""
    suffix = ticker.split(".")[-1].upper() if "." in ticker else ""
    if suffix in ("SS", "SH", "SZ"):
        return "000001.SS"
    if suffix == "HK":
        return "^HSI"
    return "^GSPC"


def check_no_2638(ticker: str) -> dict:
    """DK: no_2638 — 大盘位置检查（A股统一上证指数2638/年线；港股恒生年线；美股标普年线）
    年线口径统一 MA250（与 M 层/L2b/fengdata ma250 同根）。
    兼容说明：legacy 键 index_ma200/above_ma200 保留，承载年线(MA250)口径值。"""
    idx_ticker = _market_index_for(ticker)
    s = _series(idx_ticker)
    closes = (s or {}).get("closes") or []
    price = closes[-1] if closes else None

    if price is None:
        return {
            "check": "no_2638",
            "label": "2638法則/大盘位置",
            "light": "YELLOW",
            "signal": "数据不可用",
            "index_ticker": idx_ticker,
            "reason": f"无法获取{idx_ticker}序列（本地库/腾讯/akshare/Yahoo均失败），跳过检查",
        }

    ma250 = _ma(closes, 250)
    above = price > ma250 if ma250 else None
    is_a = (ticker.split(".")[-1].upper() if "." in ticker else "") in ("SS", "SH", "SZ")
    ctx = "上证综指" if is_a else ("恒生指数" if idx_ticker == "^HSI" else "标普500指数")

    if is_a:
        if price <= 2638:
            level = "RED"
            signal = "硬拦截"
            reason = f"{ctx}{price:.0f} ≤ 2638，仓位≤30%，不做新增多头"
        elif above is False:
            level = "YELLOW"
            signal = "降仓位"
            reason = f"{ctx}低于年线(MA250={ma250:.0f})，仓位<30%"
        elif ma250 is None:
            level = "YELLOW"
            signal = "数据不足"
            reason = f"{ctx}{price:.0f} > 2638，但年线数据不足(需250根实得{len(closes)}根)，按弃权处理"
        else:
            level = "GREEN"
            signal = "PASS"
            reason = f"{ctx}{price:.0f} > 2638 + 年线(MA250={ma250:.0f})上方"
    else:
        if above is False:
            level = "YELLOW"
            signal = "降仓位"
            reason = f"{ctx}{price:.0f} < 年线(MA250={ma250:.0f})，注意仓位控制"
        elif ma250 is None:
            level = "YELLOW"
            signal = "数据不足"
            reason = f"{ctx}{price:.0f}，年线数据不足(需250根实得{len(closes)}根)，按弃权处理"
        else:
            level = "GREEN"
            signal = "PASS"
            reason = f"{ctx}{price:.0f} 在年线(MA250={ma250:.0f})上方"

    return {
        "check": "no_2638",
        "label": "2638法則/大盘位置",
        "light": level,
        "signal": signal,
        "index_ticker": idx_ticker,
        "index_price": price,
        "index_ma250": ma250,
        "above_ma250": above,
        "index_ma200": ma250,       # legacy 键（承载年线MA250，兼容不删）
        "above_ma200": above,       # legacy 键
        "market_context": ctx,
        "series_source": (s or {}).get("source"),
        "series_as_of": (s or {}).get("as_of"),
        "reason": reason,
    }


def check_no_chasing(ticker: str) -> dict:
    """DK: no_chasing — 年线检查（个股是否在年线之上追高）
    年线口径统一 MA250（与 M 层/L2b/fengdata 的 ma250 同根，2026-09-13 修正旧 MA200 口径）。
    兼容说明：legacy 键 ma200/above_ma200/deviation_from_ma200_pct 保留，承载年线(MA250)口径值。"""
    s = _series(ticker)
    closes = (s or {}).get("closes") or []
    price = closes[-1] if closes else None
    ma250 = _ma(closes, 250)

    if price is None or ma250 is None:
        return {
            "check": "no_chasing",
            "label": "年线法则(追高检查)",
            "light": "YELLOW",
            "signal": "数据不足",
            "price": price,
            "ma250": None,
            "series_source": (s or {}).get("source"),
            "series_as_of": (s or {}).get("as_of"),
            "reason": (f"年线(MA250)数据不足(需250个交易日, 实得{len(closes)}根, "
                       f"源={(s or {}).get('source') or '全部失败'})，跳过检查，按弃权处理"),
        }

    above_ma250 = price > ma250
    # 年线上方偏离程度
    deviation_pct = (price / ma250 - 1) * 100

    if above_ma250:
        if deviation_pct > 30:
            level = "RED"
            signal = "硬拦截"
            reason = f"价格{price:.2f} 高于年线(MA250){ma250:.2f} {deviation_pct:.0f}%，严重追高"
        elif deviation_pct > 15:
            level = "YELLOW"
            signal = "警惕追高"
            reason = f"价格{price:.2f} 高于年线(MA250){ma250:.2f} {deviation_pct:.0f}%，不建议重仓"
        else:
            level = "YELLOW"
            signal = "偏高但可接受"
            reason = f"价格{price:.2f} 略高于年线(MA250){ma250:.2f}，注意回调风险"
    else:
        level = "GREEN"
        signal = "PASS"
        reason = f"价格{price:.2f} 低于年线(MA250){ma250:.2f}，安全边际充足"

    return {
        "check": "no_chasing",
        "label": "年线法则(追高检查)",
        "light": level,
        "signal": signal,
        "price": price,
        "ma250": ma250,
        "above_ma250": above_ma250,
        "deviation_from_ma250_pct": round(deviation_pct, 1),
        "ma200": ma250,                          # legacy 键（承载 MA250，兼容不删）
        "above_ma200": above_ma250,              # legacy 键
        "deviation_from_ma200_pct": round(deviation_pct, 1),  # legacy 键
        "series_source": (s or {}).get("source"),
        "series_as_of": (s or {}).get("as_of"),
        "reason": reason,
    }


def check_no_first_mover(ticker: str) -> dict:
    """DK: no_first_mover — 后发制人（右侧确认检查）
    注：本规则是均线排列（MA50/120/200）口径，非「年线」科目，MA200 保持不变。"""
    s = _series(ticker)
    closes = (s or {}).get("closes") or []
    price = closes[-1] if closes else None

    ma50 = _ma(closes, 50)
    ma120 = _ma(closes, 120)
    ma200 = _ma(closes, 200)

    if price is None or ma50 is None or ma120 is None:
        return {
            "check": "no_first_mover",
            "label": "后发制人(右侧确认)",
            "light": "YELLOW",
            "signal": "数据不足",
            "series_source": (s or {}).get("source"),
            "series_as_of": (s or {}).get("as_of"),
            "reason": (f"趋势数据不足(需120个交易日, 实得{len(closes)}根, "
                       f"源={(s or {}).get('source') or '全部失败'})，跳过检查，按弃权处理"),
        }

    # 右侧信号判断
    price_above_ma50 = price > ma50 if ma50 else None
    ma50_above_ma120 = ma50 > ma120 if ma50 and ma120 else None
    ma120_above_ma200 = ma120 > ma200 if ma120 and ma200 else None

    # 近3月涨幅（判断是否还在做价格发现）
    price_3mo_ago = closes[-66] if len(closes) >= 66 else None
    return_3m = (price / price_3mo_ago - 1) * 100 if price_3mo_ago else None

    signals = 0
    if price_above_ma50:
        signals += 1
    if ma50_above_ma120:
        signals += 1
    if ma120_above_ma200:
        signals += 1
    if return_3m and return_3m > 0:
        signals += 1

    if signals >= 3:
        level = "GREEN"
        signal = "右侧已确认"
        reason = f"右侧信号{signals}/4满足，大局已定，可以买入"
    elif signals >= 2:
        level = "YELLOW"
        signal = "偏右侧"
        reason = f"右侧信号{signals}/4满足，建议分批建仓，等更多确认"
    elif signals >= 1:
        level = "YELLOW"
        signal = "左侧/价格发现"
        reason = f"右侧信号{signals}/4满足，还在做价格发现，建议等待"
    else:
        level = "RED"
        signal = "左侧下行"
        reason = f"右侧信号{signals}/4满足，均线空头排列，禁止买入"

    return {
        "check": "no_first_mover",
        "label": "后发制人(右侧确认)",
        "light": level,
        "signal": signal,
        "price_above_ma50": price_above_ma50,
        "ma50_above_ma120": ma50_above_ma120,
        "ma120_above_ma200": ma120_above_ma200,
        "return_3m_pct": round(return_3m, 1) if return_3m else None,
        "right_side_signals": signals,
        "right_side_max": 4,
        "series_source": (s or {}).get("source"),
        "series_as_of": (s or {}).get("as_of"),
        "reason": reason,
    }


# 文献：波动率→敞口判断属「现金/波动率管理」类 → Moreira-Muir 2017（波动率高时降敞口提升风险调整收益）；
# 反证 Cederburg et al. 2020 JFE（波动率择时样本外不可实施）
def check_divergence_consensus(ticker: str) -> dict:
    """DK: divergence_or_consensus — 买分歧卖共识（分歧/共识判断）"""
    s = _series(ticker)
    closes = (s or {}).get("closes") or []
    price = closes[-1] if closes else None

    # 波动率作为分歧/共识的代理指标（样本标准差 × √252 年化；6m=近126根，同原 period=6mo 口径）
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)) if closes[i - 1]]
    rets_6m = rets[-125:]
    volatility_6m = statistics.stdev(rets_6m) * (252 ** 0.5) if len(rets_6m) >= 30 else None
    volatility_1m = statistics.stdev(rets[-22:]) * (252 ** 0.5) if len(rets) >= 22 else None

    # 近期涨幅/跌幅（判断是否过热）
    return_1m = (price / closes[-22] - 1) * 100 if price and len(closes) >= 22 else None
    return_3m = (price / closes[-66] - 1) * 100 if price and len(closes) >= 66 else None

    if volatility_6m is None:
        return {
            "check": "divergence_or_consensus",
            "label": "买分歧卖共识",
            "light": "YELLOW",
            "signal": "数据不足",
            "series_source": (s or {}).get("source"),
            "series_as_of": (s or {}).get("as_of"),
            "reason": (f"波动率数据不足(需30根K线, 实得{len(closes)}根, "
                       f"源={(s or {}).get('source') or '全部失败'})，跳过检查，按弃权处理"),
        }

    # 判断分歧 vs 共识
    # 高波动 + 价格无明显方向 = 分歧
    # 低波动 + 趋势明确 = 共识
    # 异常高波动 = 恐慌/狂热
    if volatility_6m > 0.6:
        # 超高波动
        if return_1m and return_1m > 20:
            level = "RED"
            signal = "狂热(警惕)"
            reason = f"年化波动率{volatility_6m:.0%}异常高 + 月涨{return_1m:.0f}%，市场狂热，一致看多危险"
        elif return_1m and return_1m < -15:
            level = "YELLOW"
            signal = "恐慌(机会?)"
            reason = f"年化波动率{volatility_6m:.0%}高 + 月跌{return_1m:.0f}%，恐慌抛售中，需要分辨是真跌还是错杀"
        else:
            level = "YELLOW"
            signal = "分歧偏大"
            reason = f"年化波动率{volatility_6m:.0%}，市场存在显著分歧，注意方向选择"
    elif volatility_6m > 0.35:
        if return_1m and return_1m > 10:
            level = "YELLOW"
            signal = "共识偏多"
            reason = f"波动率{volatility_6m:.0%}中等 + 上涨中，市场正在形成共识，安全边际在缩小"
        elif return_1m and return_1m < -10:
            level = "YELLOW"
            signal = "共识偏空"
            reason = f"波动率{volatility_6m:.0%}中等 + 下跌中，市场一致看空，可能有错杀机会"
        else:
            level = "GREEN"
            signal = "存在分歧"
            reason = f"波动率{volatility_6m:.0%}适中 + 价格震荡，市场存在分歧，安全边际来源充足"
    else:
        # 低波动
        if return_1m and abs(return_1m) < 5:
            level = "YELLOW"
            signal = "共识(无人讨论)"
            reason = f"波动率仅{volatility_6m:.0%}，市场已形成共识或无人关注，缺少安全边际来源"
        else:
            level = "GREEN"
            signal = "存在分歧"
            reason = f"波动率{volatility_6m:.0%}偏低但有方向，分歧尚存"

    return {
        "check": "divergence_or_consensus",
        "label": "买分歧卖共识",
        "light": level,
        "signal": signal,
        "volatility_annualized_6m": round(volatility_6m, 3),
        "volatility_annualized_1m": round(volatility_1m, 3) if volatility_1m else None,
        "return_1m_pct": round(return_1m, 1) if return_1m else None,
        "return_3m_pct": round(return_3m, 1) if return_3m else None,
        "series_source": (s or {}).get("source"),
        "series_as_of": (s or {}).get("as_of"),
        "reason": reason,
    }


# ── ETF 资产级规则（2026-09-13 修 fengcheck 审计发现：ETF 无资产级感知）──────────
# 背景：ETF 无公司科目（ROE/FCF/营收增速），数据缺失被机械判灯 = "数据盲当负面证据"。
# ETF 模式：依赖公司科目的规则输出 ABSTAIN（非负面证据）；基金财报（N-CSR）/fact sheet
# 口径的真实指标（净投资收入收益率/分配率/费率/AUM/组合PE/PB）由 --etf-metrics JSON 供数，
# 字段缺省 → 该规则 ABSTAIN。不得为公司科目编造数字。

# 分配覆盖率 = SEC 30天净收益率 / TTM 分配率。<80% 意味着分配长期依赖本金返还(ROC)，
# NAV 侵蚀是结构性的 → RED；80%-100% 部分 ROC → YELLOW；≥100% 净投资收入可覆盖 → GREEN。
ETF_COVERAGE_RED_BELOW = 0.80
ETF_COVERAGE_GREEN_FROM = 1.00
# 默认无风险利率 3.7%：Fed 2025-12-10 降息后目标区间上限 3.50-3.75%（源：LVHI 02-market dk_policy，
# 2026年1-7月连续按兵）。净收益率低于无风险利率只是"息不抵债"的机会成本问题，不是造假 → 不判 RED。
ETF_RISK_FREE_RATE_DEFAULT = 0.037
# 费率：>0.5% 相对被动基准（宽基 ETF 0.03-0.20%）偏高 → YELLOW；>1.0% 高费率对复利是结构性拖累 → RED。
ETF_ER_YELLOW_ABOVE = 0.005
ETF_ER_RED_ABOVE = 0.010
# AUM < 5 亿美元：行业通用清盘风险阈值，只黄不红（清盘是流动性风险，非价值否定证据）。
ETF_AUM_LIQUIDATION_RISK_BELOW = 5e8
# 组合口径估值与 PE/PB 检查沿用现有公司阈值口径：
# pe<15 GREEN / 15-25 YELLOW / >25 RED —— 15 = fengcollision 深度价值"极端低估"线，
# 25 = 卡拉曼人设 PE 分带（<15 偏低 / <25 合理 / ≥25 偏高）上沿。
ETF_PE_GREEN_BELOW = 15.0
ETF_PE_RED_ABOVE = 25.0
# pb 同理按两段制对偶：pb<1 GREEN（现有极端低估线）/ 1-2 YELLOW / >2 RED。
ETF_PB_GREEN_BELOW = 1.0
ETF_PB_RED_ABOVE = 2.0

_ETF_ABSTAIN_NOTE = "ETF 无公司口径，非负面证据"


def _etf_num(metrics: dict, key: str):
    """取指标数值；缺省/非数值 → None（触发该规则 ABSTAIN）。"""
    v = metrics.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _etf_abstain(check: str, label: str, reason: str) -> dict:
    return {
        "check": check,
        "label": label,
        "light": "ABSTAIN",
        "signal": "弃权",
        "reason": reason,
    }


def etf_distribution_coverage(metrics: dict) -> dict:
    """ETF-1 分配覆盖率：sec_net_yield / distribution_rate_ttm。"""
    entry = {"check": "etf_distribution_coverage", "label": "分配覆盖率(净收入/分配)"}
    ny = _etf_num(metrics, "sec_net_yield")
    dr = _etf_num(metrics, "distribution_rate_ttm")
    if ny is None or dr is None or dr == 0:
        return _etf_abstain(entry["check"], entry["label"],
                            f"{_ETF_ABSTAIN_NOTE}；缺 sec_net_yield/distribution_rate_ttm，覆盖率不可算")
    cov = ny / dr
    if cov < ETF_COVERAGE_RED_BELOW:
        light, signal = "RED", "本金付息(ROC)"
        reason = f"分配覆盖率{cov:.1%} < {ETF_COVERAGE_RED_BELOW:.0%}，净投资收入不足，分配含本金返还(ROC)，NAV侵蚀结构性"
    elif cov < ETF_COVERAGE_GREEN_FROM:
        light, signal = "YELLOW", "部分依赖资本利得"
        reason = f"分配覆盖率{cov:.1%} 处于 {ETF_COVERAGE_RED_BELOW:.0%}-{ETF_COVERAGE_GREEN_FROM:.0%}，分配部分依赖资本利得/本金"
    else:
        light, signal = "GREEN", "PASS"
        reason = f"分配覆盖率{cov:.1%} ≥ {ETF_COVERAGE_GREEN_FROM:.0%}，净投资收入可覆盖分配"
    entry.update({"light": light, "signal": signal, "coverage": round(cov, 4),
                  "sec_net_yield": ny, "distribution_rate_ttm": dr, "reason": reason})
    return entry


def etf_net_yield_vs_riskfree(metrics: dict) -> dict:
    """ETF-2 SEC 30天净收益率 vs 无风险利率（息价原则的基金口径化）。"""
    entry = {"check": "etf_net_yield_vs_riskfree", "label": "净收益率vs无风险利率"}
    ny = _etf_num(metrics, "sec_net_yield")
    if ny is None:
        return _etf_abstain(entry["check"], entry["label"],
                            f"{_ETF_ABSTAIN_NOTE}；缺 sec_net_yield")
    rf = _etf_num(metrics, "risk_free_rate")
    rf_source = "metrics.risk_free_rate"
    if rf is None:
        rf = ETF_RISK_FREE_RATE_DEFAULT
        rf_source = "默认(Fed目标区间上限)"
    if ny >= rf:
        light, signal = "GREEN", "PASS"
        reason = f"净收益率{ny:.2%} ≥ 无风险{rf:.2%}（{rf_source}），息价上有相对吸引力"
    else:
        light, signal = "YELLOW", "息低于无风险"
        reason = f"净收益率{ny:.2%} < 无风险{rf:.2%}（{rf_source}），承担风险未获超额息差；低息非造假，不判RED"
    entry.update({"light": light, "signal": signal, "sec_net_yield": ny,
                  "risk_free_rate": rf, "reason": reason})
    return entry


def etf_expense_ratio(metrics: dict) -> dict:
    """ETF-3 费率 ER。"""
    entry = {"check": "etf_expense_ratio", "label": "费率ER"}
    er = _etf_num(metrics, "expense_ratio")
    if er is None:
        return _etf_abstain(entry["check"], entry["label"],
                            f"{_ETF_ABSTAIN_NOTE}；缺 expense_ratio")
    if er > ETF_ER_RED_ABOVE:
        light, signal = "RED", "高费率"
        reason = f"费率{er:.2%} > {ETF_ER_RED_ABOVE:.1%}，费用侵蚀长期复利，结构性拖累"
    elif er > ETF_ER_YELLOW_ABOVE:
        light, signal = "YELLOW", "费率偏高"
        reason = f"费率{er:.2%} > {ETF_ER_YELLOW_ABOVE:.1%}，相对被动基准偏高"
    else:
        light, signal = "GREEN", "PASS"
        reason = f"费率{er:.2%} ≤ {ETF_ER_YELLOW_ABOVE:.1%}，成本可接受"
    entry.update({"light": light, "signal": signal, "expense_ratio": er, "reason": reason})
    return entry


def etf_aum(metrics: dict) -> dict:
    """ETF-4 AUM 清盘风险。"""
    entry = {"check": "etf_aum", "label": "AUM/清盘风险"}
    aum = _etf_num(metrics, "aum_usd")
    if aum is None:
        return _etf_abstain(entry["check"], entry["label"],
                            f"{_ETF_ABSTAIN_NOTE}；缺 aum_usd")
    if aum < ETF_AUM_LIQUIDATION_RISK_BELOW:
        light, signal = "YELLOW", "清盘风险"
        reason = f"AUM {aum/1e8:.1f}亿 < {ETF_AUM_LIQUIDATION_RISK_BELOW/1e8:.0f}亿美元，清盘/流动性风险（风险类信号只黄不红）"
    else:
        light, signal = "GREEN", "PASS"
        reason = f"AUM {aum/1e9:.1f}B ≥ {ETF_AUM_LIQUIDATION_RISK_BELOW/1e9:.0f}B，规模充足"
    entry.update({"light": light, "signal": signal, "aum_usd": aum, "reason": reason})
    return entry


def etf_portfolio_valuation(metrics: dict) -> dict:
    """ETF-5 组合口径估值 PE/PB（fact sheet 口径），阈值与公司 pe/pb 检查同刻度。"""
    entry = {"check": "etf_portfolio_valuation", "label": "组合估值(PE/PB)"}
    pe = _etf_num(metrics, "portfolio_pe")
    pb = _etf_num(metrics, "portfolio_pb")
    if pe is None and pb is None:
        return _etf_abstain(entry["check"], entry["label"],
                            f"{_ETF_ABSTAIN_NOTE}；缺 portfolio_pe/portfolio_pb，组合估值不可判")
    order = {"GREEN": 0, "YELLOW": 1, "RED": 2}
    lights, parts = [], []
    if pe is not None:
        l = "GREEN" if pe < ETF_PE_GREEN_BELOW else ("YELLOW" if pe <= ETF_PE_RED_ABOVE else "RED")
        lights.append(l)
        parts.append(f"组合PE {pe:.2f} → {l}（<{ETF_PE_GREEN_BELOW:.0f}绿/{ETF_PE_GREEN_BELOW:.0f}-{ETF_PE_RED_ABOVE:.0f}黄/>{ETF_PE_RED_ABOVE:.0f}红）")
    if pb is not None:
        l = "GREEN" if pb < ETF_PB_GREEN_BELOW else ("YELLOW" if pb <= ETF_PB_RED_ABOVE else "RED")
        lights.append(l)
        parts.append(f"组合PB {pb:.2f} → {l}（<{ETF_PB_GREEN_BELOW:.0f}绿/{ETF_PB_GREEN_BELOW:.0f}-{ETF_PB_RED_ABOVE:.0f}黄/>{ETF_PB_RED_ABOVE:.0f}红）")
    light = max(lights, key=lambda x: order[x])
    signal = {"GREEN": "PASS", "YELLOW": "估值温和", "RED": "组合口径偏贵"}[light]
    entry.update({"light": light, "signal": signal, "portfolio_pe": pe,
                  "portfolio_pb": pb, "reason": "；".join(parts)})
    return entry


def build_etf_rules(ticker: str, metrics: dict) -> list:
    """ETF 模式 L1 规则集（≥8 条，兼容 fengstate VERIFY_RULES.min_rules）。

    - no_knife/true_value 依赖公司科目（fundamentals_bad/roe/FCF/营收/利润率）→ ABSTAIN，
      趋势信息仅作参考附在 reason，不据数据缺失判灯；
    - 纯价格/趋势/大盘规则（no_fomo/no_2638/no_chasing/no_first_mover/divergence）与公司模式同款；
    - no_leverage 框架硬规则不变；
    - 追加 5 条基金口径规则（--etf-metrics 供数，缺字段 → ABSTAIN）。
    """
    rules = []
    try:
        knife = check_no_knife(ticker)
        trend_ref = f"趋势参考: MA50={knife.get('ma50')} / MA120={knife.get('ma120')}"
    except Exception:
        trend_ref = "趋势数据不可用"
    rules.append(_etf_abstain(
        "no_knife", "不接飞刀",
        f"{_ETF_ABSTAIN_NOTE}（基本面恶化/ROE极端估值子条件依赖公司科目，无法评估，不据缺失判灯）。{trend_ref}",
    ))
    rules.append(check_no_fomo(ticker))
    rules.append(check_no_leverage(ticker))
    tv = _etf_abstain(
        "true_value", "真价值",
        f"{_ETF_ABSTAIN_NOTE}（FCF/营收/利润率科目不存在，真值判断让位于 ETF 侧分配覆盖/净收益规则）",
    )
    # 显式 None 字段：供下游（fengcollision）识别"数据盲"而非"数据为 False"
    tv.update({"has_cashflow": None, "has_revenue": None, "is_profitable": None})
    rules.append(tv)
    rules.append(check_no_2638(ticker))
    rules.append(check_no_chasing(ticker))
    rules.append(check_no_first_mover(ticker))
    rules.append(check_divergence_consensus(ticker))
    rules.append(etf_distribution_coverage(metrics))
    rules.append(etf_net_yield_vs_riskfree(metrics))
    rules.append(etf_expense_ratio(metrics))
    rules.append(etf_aum(metrics))
    rules.append(etf_portfolio_valuation(metrics))
    return rules


def _get_flag(name: str):
    """最小化旗标解析：--name value。缺失返回 None（不改公司路径既有 argv 约定）。"""
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return None


def _load_etf_metrics(path):
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: fengrule.py TICKER"}, indent=2))
        sys.exit(1)

    ticker = sys.argv[1].upper()

    # ── ETF 资产级模式（2026-09-13）：不带 --asset-type 时走下方公司路径，行为逐字节不变 ──
    if (_get_flag("--asset-type") or "company").lower() == "etf":
        metrics = _load_etf_metrics(_get_flag("--etf-metrics"))
        results = {
            "ticker": ticker,
            "checked_at": datetime.now().isoformat(),
            "asset_type": "etf",
            "rules": build_etf_rules(ticker, metrics),
        }
        # overall 聚合：ABSTAIN 不参与（既不算绿也不算红）；全 ABSTAIN → YELLOW 数据不足
        order = {"GREEN": 0, "YELLOW": 1, "RED": 2}
        decisive = [r.get("light") for r in results["rules"] if r.get("light") in order]
        abstain_ct = sum(1 for r in results["rules"] if r.get("light") == "ABSTAIN")
        if decisive:
            worst = max(decisive, key=lambda x: order[x])
            results["overall_light"] = worst
            results["overall_status"] = {
                "GREEN": "全部通过",
                "YELLOW": "条件通过",
                "RED": "硬拦截",
            }[worst]
            if abstain_ct:
                results["abstain_note"] = f"{abstain_ct} 条规则 ABSTAIN（数据盲非负面证据），不参与聚合"
        else:
            results["overall_light"] = "YELLOW"
            results["overall_status"] = "数据不足"
            results["abstain_note"] = "全部规则 ABSTAIN：ETF 指标与价格数据均不足，数据盲不判红"
        print(json.dumps(results, indent=2, default=str))
        return

    results = {
        "ticker": ticker,
        "checked_at": datetime.now().isoformat(),
        "rules": [],
    }

    # 单条规则内部已全链路降级；此处兜底——任何意外异常也不许整个工具崩溃（IndexError 铁律）
    for _fn in (check_no_knife, check_no_fomo, check_no_leverage, check_true_value,
                check_no_2638, check_no_chasing, check_no_first_mover,
                check_divergence_consensus):
        try:
            results["rules"].append(_fn(ticker))
        except Exception as e:
            results["rules"].append({
                "check": _fn.__name__.replace("check_", ""),
                "label": _fn.__doc__.split("—")[0].strip() if _fn.__doc__ else _fn.__name__,
                "light": "YELLOW",
                "signal": "数据错误",
                "reason": f"规则执行异常({type(e).__name__})，科目不可得按弃权处理，不判红",
            })

    # Overall L1 status: worst light
    light_order = {"GREEN": 0, "YELLOW": 1, "RED": 2}
    lights = [r["light"] for r in results["rules"]]
    worst = max(lights, key=lambda x: light_order.get(x, 0))
    results["overall_light"] = worst
    results["overall_status"] = {
        "GREEN": "全部通过",
        "YELLOW": "条件通过",
        "RED": "硬拦截",
    }[worst]

    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
