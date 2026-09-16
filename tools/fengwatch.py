#!/usr/bin/env python3
"""
fengwatch — 持仓监控引擎

闭环系统的执行端：
  分析→买入→持有→检查→卖出→复盘→再买入
                 ^^^^^^^^   ^^^^   ^^^^
                 fengwatch  卖出   复盘

Commands:
    daily               一键每日分析（更新价格+检查退出条件+生成提醒+写日志）
    check [ticker]      检查持仓退出条件触发状态（不指定=全部）
    review <ticker>     复盘持仓并写日志
    outcome [ticker]    复盘 outcome 追踪：统计 hypotheses[].outcome 状态（不指定=全部）
    sell <ticker>       记录卖出、归档持仓、写日志
    history             历史持仓总览（胜率/盈亏/持有期）
    history losses      亏损交易分析（排行/原因/复盘记录）
    history import      导入历史交易（JSON格式）
    log [--limit N]     查看决策日志
    alert               显示当前提醒
    fund-share [opts]   ETF/LOF 份额变动监控（沪深交易所直连）

Rules applied (from docs/08-exit.md):
    - 价格止损: 买入后跌>20% → 强制退出
    - 趋势反转: MA50<MA200+月跌>10% → 退50%
    - 论文失效: thesis_invalidation标志 → 立即清仓
    - 审核提醒: next_review_date到期
    - 钱仓滚存: 浮盈≥15%关注 / ≥30%建议回收本金（回收股数 ceil）
    - 时间止损: 持有≥6个月论文未兑现 → 审视
    - 估值回归: 超期限价差未兑现 → 审视
    - 估值泡沫: 市值/FCF>50x → 清仓
"""

import json, math, os, re, sys, time
import sqlite3
import urllib.request
import urllib.parse
from datetime import datetime, date, timezone, timedelta
from pathlib import Path

# Windows GBK fix: force UTF-8 for console output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(BASE, "tools")

# Defer yfinance import — use fengdata.py (腾讯/Yahoo 多源) when possible
HOLDINGS_DIR = os.path.join(BASE, "holdings")
ALERTS_DIR = os.path.join(BASE, "alerts")
LOGS_DIR = os.path.join(BASE, "logs")
REVIEWS_DIR = os.path.join(BASE, "reviews")
JOURNAL_FILE = os.path.join(LOGS_DIR, "journal.jsonl")

os.makedirs(ALERTS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(REVIEWS_DIR, exist_ok=True)


# ─── Fund Share API (ETF/LOF 份额变动监控) ────────────────────────
# 数据来源：RockyZSU/Stock 开源项目逆向的交易所直连 API
# SSE（上交所）: query.sse.com.cn — ETF 份额 + LOF 份额
# SZSE（深交所）: fund.szse.cn — LOF/ETF 份额
# 单位：SSE ETF = 份, SSE LOF = 万份(INTERNAL_VOL), SZSE = 万份(dqgm)

# 默认阈值：份额日环比变动超过该百分比时告警
FUND_SHARE_WARN_PCT = 5.0

# 交易所 API 超时（秒），交易所接口不稳定需合理超时
FUND_SHARE_TIMEOUT = 15


# fail-loud（2026-09-13 有声失败审计 P2）：份额取数的 HTTP 失败不再与
# "正常翻页结束"混淆——逐次记入模块级列表并打到 stderr，由 fund-share 输出透出。
_FUND_FETCH_ERRORS = []


def fund_fetch_errors():
    """返回本进程内份额取数的失败明细（copy）。"""
    return list(_FUND_FETCH_ERRORS)


def _fund_http_get(url, headers=None, timeout=FUND_SHARE_TIMEOUT):
    """通用 HTTP GET 请求，带超时和错误处理。

    交易所 API 不稳定，失败时返回 None 而非抛异常（有声：记明细+stderr）。
    """
    if headers is None:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        msg = "%s: %s" % (url[:90], str(e)[:80])
        _FUND_FETCH_ERRORS.append(msg)
        print("[fengwatch][fund-fetch] 请求失败: %s" % msg, file=sys.stderr)
        return None


def _parse_jsonp(text):
    """将 JSONP 响应（jsonpCallbackXXXX({...})）解析为 Python dict。

    SSE 接口返回 JSONP 格式，需剥离回调函数包装。
    """
    if not text:
        return None
    # 匹配 jsonpCallback...(  {...}  ) 或 callback...(  {...}  )
    m = re.search(r'\w+\s*\(\s*(\{.*\})\s*\)', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return None
    # 兜底：尝试直接 JSON 解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def fetch_sse_etf_shares(date_str=None):
    """查询上交所 ETF 份额数据。

    API: query.sse.com.cn/commonQuery.do
    sqlId: COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L
    返回字段: SEC_CODE(代码), SEC_NAME(名称), TOT_VOL(总份额/份), STAT_DATE(日期)
    分页: 每页 25 条，自动翻页获取全量。

    Args:
        date_str: 日期字符串 YYYY-MM-DD，默认取前一交易日
    Returns:
        list[dict]: [{code, name, share, date}, ...]，share 单位为份
    """
    if date_str is None:
        # 默认取昨天（交易所数据通常 T+1 更新）
        date_str = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

    base_url = (
        "http://query.sse.com.cn/commonQuery.do"
        "?jsonCallBack=jsonpCallback"
        "&isPagination=true"
        "&pageHelp.pageSize=25"
        "&pageHelp.pageNo={page}"
        "&pageHelp.cacheSize=1"
        "&sqlId=COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L"
        "&STAT_DATE={dt}"
        "&pageHelp.beginPage={page}"
        "&pageHelp.endPage=30"
    )

    headers = {
        "Host": "query.sse.com.cn",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "http://www.sse.com.cn/market/funddata/volumn/etfvol/",
    }

    results = []
    page = 1
    while True:
        url = base_url.format(page=page, dt=date_str)
        text = _fund_http_get(url, headers=headers)
        data = _parse_jsonp(text)
        if not data:
            break

        items = data.get("result") or []
        if not items:
            break

        for item in items:
            code = item.get("SEC_CODE", "")
            name = item.get("SEC_NAME", "")
            stat_date = item.get("STAT_DATE", date_str)
            try:
                share = float(str(item.get("TOT_VOL", "0")).replace(",", ""))
            except (ValueError, TypeError):
                share = 0.0
            results.append({
                "code": code, "name": name,
                "share": share, "date": stat_date,
                "exchange": "SSE", "type": "ETF",
            })

        # 检查是否还有下一页
        total = 0
        page_help = data.get("pageHelp") or {}
        total = page_help.get("total", 0)
        if page * 25 >= total:
            break
        page += 1

    return results


def fetch_sse_lof_shares(date_str=None):
    """查询上交所 LOF 份额数据。

    API: query.sse.com.cn/commonQuery.do
    sqlId: COMMON_SSE_FUND_LOF_SCALE_CX_S
    返回字段: FUND_CODE(代码), FUND_ABBR(简称), INTERNAL_VOL(内部份额/万份), TRADE_DATE(日期)
    一次性返回全量（pageSize=10000）。

    Args:
        date_str: 日期字符串 YYYYMMDD 格式，默认取前一交易日
    Returns:
        list[dict]: [{code, name, share, date}, ...]，share 单位为万份
    """
    if date_str is None:
        date_str = (date.today() - timedelta(days=1)).strftime("%Y%m%d")

    url = (
        "http://query.sse.com.cn/commonQuery.do"
        "?=&jsonCallBack=jsonpCallback"
        "&sqlId=COMMON_SSE_FUND_LOF_SCALE_CX_S"
        "&pageHelp.pageSize=10000"
        f"&FILEDATE={date_str}"
        f"&_={int(time.time() * 1000)}"
    )

    headers = {
        "Host": "query.sse.com.cn",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "*/*",
        "Referer": "http://www.sse.com.cn/market/funddata/volumn/lofvolumn/",
    }

    text = _fund_http_get(url, headers=headers)
    data = _parse_jsonp(text)
    if not data:
        return []

    results = []
    for item in (data.get("result") or []):
        code = item.get("FUND_CODE", "")
        name = item.get("FUND_ABBR", "")
        trade_date = item.get("TRADE_DATE", date_str)
        try:
            share = float(str(item.get("INTERNAL_VOL", "0")).replace(",", ""))
        except (ValueError, TypeError):
            share = 0.0
        results.append({
            "code": code, "name": name,
            "share": share, "date": trade_date,
            "exchange": "SSE", "type": "LOF",
        })

    return results


def fetch_szse_fund_shares(page=1):
    """查询深交所 LOF/ETF 份额数据。

    API: fund.szse.cn/api/report/ShowReport/data
    CATALOGID: 1000_lf (LOF 列表页)
    返回字段: dqgm(当前规模/万份), jjlb(基金类别), tzlb(投资类别),
              ssrq(上市日期), glrmc(管理人), sys_key(基金代码,HTML格式), jjjcurl(基金名称,HTML格式)
    分页: 每页约 50 条，自动翻页。

    Args:
        page: 起始页码
    Returns:
        list[dict]: [{code, name, share, date, category}, ...]，share 单位为万份
    """
    base_url = (
        "http://fund.szse.cn/api/report/ShowReport/data"
        "?SHOWTYPE=JSON"
        "&CATALOGID=1000_lf"
        "&TABKEY=tab1"
        "&PAGENO={page}"
        "&random={rand}"
    )

    headers = {
        "Host": "fund.szse.cn",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Referer": "http://fund.szse.cn/marketdata/fundslist/index.html?catalogId=1000_lf",
        "X-Requested-With": "XMLHttpRequest",
    }

    today = date.today().isoformat()
    results = []
    current_page = page

    while True:
        url = base_url.format(page=current_page, rand=time.time())
        text = _fund_http_get(url, headers=headers)
        if not text:
            break

        try:
            js_data = json.loads(text)
        except json.JSONDecodeError:
            break

        if not js_data or not isinstance(js_data, list):
            break

        data = js_data[0].get("data") if js_data else None
        if not data:
            break

        for item in data:
            # 从 HTML 标签中提取代码和名称
            code_match = re.search(r'<u>(\d{6})</u>', item.get("sys_key", ""))
            name_match = re.search(r'<u>(.*?)</u>', item.get("jjjcurl", ""))
            code = code_match.group(1) if code_match else ""
            name = name_match.group(1) if name_match else ""

            if not code:
                continue

            # 当前规模（万份），去除千分位逗号
            raw_share = item.get("dqgm", "0")
            try:
                share = float(str(raw_share).replace(",", ""))
            except (ValueError, TypeError):
                share = 0.0

            category = item.get("jjlb", "")  # 基金类别（LOF/ETF 等）
            results.append({
                "code": code, "name": name,
                "share": share, "date": today,
                "exchange": "SZSE", "type": category,
                "category": category,
            })

        # 深交所分页：每页约 50 条，数据量不大时一页即够
        if len(data) < 50:
            break
        current_page += 1

    return results


def fetch_all_fund_shares(codes=None, exchanges=None):
    """统一入口：查询沪深交易所 ETF/LOF 份额，支持按交易所/代码过滤。

    Args:
        codes: 代码列表（如 ["510300", "161725"]），None=全量
        exchanges: 交易所过滤 ["SSE", "SZSE"]，None=全部
    Returns:
        list[dict]: 合并后的份额数据
    """
    all_data = []
    _FUND_FETCH_ERRORS.clear()  # 本轮聚合开始，失败明细重新计（fail-loud）

    # 上交所 ETF
    if exchanges is None or "SSE" in exchanges:
        try:
            all_data.extend(fetch_sse_etf_shares())
        except Exception as e:
            _FUND_FETCH_ERRORS.append("SSE-ETF 整源失败: %s" % str(e)[:90])
            print("[fengwatch][fund-fetch] SSE-ETF 整源失败: %s" % str(e)[:90], file=sys.stderr)
        # 上交所 LOF
        try:
            all_data.extend(fetch_sse_lof_shares())
        except Exception as e:
            _FUND_FETCH_ERRORS.append("SSE-LOF 整源失败: %s" % str(e)[:90])
            print("[fengwatch][fund-fetch] SSE-LOF 整源失败: %s" % str(e)[:90], file=sys.stderr)

    # 深交所
    if exchanges is None or "SZSE" in exchanges:
        try:
            all_data.extend(fetch_szse_fund_shares())
        except Exception as e:
            _FUND_FETCH_ERRORS.append("SZSE 整源失败: %s" % str(e)[:90])
            print("[fengwatch][fund-fetch] SZSE 整源失败: %s" % str(e)[:90], file=sys.stderr)

    # 按代码过滤
    if codes:
        code_set = set(c.upper() for c in codes)
        all_data = [d for d in all_data if d["code"] in code_set]

    return all_data


def compute_share_changes(current_data, warn_pct=FUND_SHARE_WARN_PCT):
    """计算份额变动（今日 vs 昨日），标记超阈值的异动。

    注意：单次调用只能获取最新一天数据。要计算环比变动，需配合缓存/历史数据。
    本函数先尝试获取前两天数据进行对比，若无法获取历史数据则标记为 "无历史数据"。

    Args:
        current_data: fetch_all_fund_shares() 返回的最新数据
        warn_pct: 告警阈值百分比，默认 ±5%
    Returns:
        list[dict]: 每条记录附加 change_pct / change_shares / alert_level 字段
    """
    # 尝试获取前一天数据作为对比基准
    yesterday = (date.today() - timedelta(days=2)).strftime("%Y-%m-%d")
    yesterday_lof = (date.today() - timedelta(days=2)).strftime("%Y%m%d")

    prev_data = {}
    # 尝试上交所 ETF 昨日
    try:
        for item in fetch_sse_etf_shares(date_str=yesterday):
            prev_data[item["code"]] = item["share"]
    except Exception:
        pass
    # 尝试上交所 LOF 昨日
    try:
        for item in fetch_sse_lof_shares(date_str=yesterday_lof):
            prev_data[item["code"]] = item["share"]
    except Exception:
        pass
    # 深交所没有日期参数，无法获取历史；用缓存兜底
    # TODO: 后续可对接本地 DB 缓存历史份额

    results = []
    for item in current_data:
        code = item["code"]
        current_share = item["share"]
        prev_share = prev_data.get(code)

        change_pct = None
        change_shares = None
        alert_level = "N/A"

        if prev_share is not None and prev_share > 0:
            change_shares = current_share - prev_share
            change_pct = round((current_share - prev_share) / prev_share * 100, 2)
            if abs(change_pct) >= warn_pct:
                alert_level = "WARN"
            elif abs(change_pct) >= warn_pct * 0.5:
                alert_level = "WATCH"
            else:
                alert_level = "OK"

        results.append({
            **item,
            "prev_share": prev_share,
            "change_shares": change_shares,
            "change_pct": change_pct,
            "alert_level": alert_level,
        })

    return results


# ─── Data Loading ────────────────────────────────────────────────

def load_holdings():
    """Load active hold_*.json files (excludes closed/archived).

    口径：全部活跃持仓（含现金，14 个）。风险类命令（daily/check/history）
    用 risk_holdings() 排除现金 —— 现金/资金池不参与退出条件检查。
    """
    holdings = []
    closed_re = re.compile(r"^hold_.+_closed_\d{4}-\d{2}-\d{2}\.json$")
    for f in sorted(os.listdir(HOLDINGS_DIR)):
        m = re.match(r"^hold_(.+)\.json$", f)
        if m and not closed_re.match(f):
            with open(os.path.join(HOLDINGS_DIR, f), encoding="utf-8") as fh:
                h = json.load(fh)
                h["_file"] = f
                holdings.append(h)
    return holdings


def _is_cash(h):
    """现金判断（资金池语义）：qualifier==cash 或 asset_type==cash。准现金(quasi_cash)不算。"""
    return h.get("qualifier") == "cash" or h.get("asset_type") == "cash"


def risk_holdings():
    """风险持仓：排除真现金（=11 权益+准现金；总持仓 14 含现金，见 fengholding list）。"""
    return [h for h in load_holdings() if not _is_cash(h)]


def load_closed_holdings():
    """Load closed hold_<TICKER>_closed_<DATE>.json files."""
    holdings = []
    for f in sorted(os.listdir(HOLDINGS_DIR)):
        m = re.match(r"^hold_([A-Za-z0-9.]+)_closed_(\d{4}-\d{2}-\d{2})\.json$", f)
        if m:
            with open(os.path.join(HOLDINGS_DIR, f), encoding="utf-8") as fh:
                h = json.load(fh)
                h["_file"] = f
                h["_closed_date"] = m.group(2)
                holdings.append(h)
    return holdings


def load_all_holdings():
    """Load both active and closed holdings."""
    active = load_holdings()
    closed = load_closed_holdings()
    return active + closed


def load_holding(ticker):
    """Load a single holding by ticker/id."""
    f = os.path.join(HOLDINGS_DIR, f"hold_{ticker.upper()}.json")
    if not os.path.exists(f):
        return None
    with open(f, encoding="utf-8") as fh:
        return json.load(fh)


def _holding_id(h):
    """Get the unique identifier for a holding record (id or ticker field)."""
    return h.get("id") or h.get("ticker", "?")


def save_holding(h):
    """Save a single holding back to disk."""
    hid = _holding_id(h)
    f = os.path.join(HOLDINGS_DIR, f"hold_{hid.upper()}.json")
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(h, fh, indent=2, ensure_ascii=False)


# Per-ticker price cache (60s) so repeated calls don't re-hit slow US Yahoo source.
_PRICE_CACHE: dict = {}
_PRICE_CACHE_TTL = 60


def fetch_price_data(ticker, holding=None):
    """Fetch current price + MA data via fengdata.py (腾讯/Yahoo 多源).

    - Quick-path: serve 60s module cache to make daily check fast.
    - Fallback: if live fetch fails/times out, use the holding's stored current_price
      so a slow US Yahoo source doesn't block the whole daily run.
    """
    now = time.time()
    cached = _PRICE_CACHE.get(ticker)
    if cached and now - cached["ts"] < _PRICE_CACHE_TTL:
        return cached["data"]

    price_data = None
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(TOOLS, "fengdata.py"), ticker, "--mode", "price", "--backend=auto"],
            capture_output=True, text=True, timeout=20
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            p = data.get("price", {})
            if p and "error" not in p:
                price_data = {
                    "price": p.get("price"),
                    "ma50": p.get("ma50"),
                    "ma100": p.get("ma100") or p.get("ma120"),
                    "ma200": p.get("ma200"),
                    "return_1m_pct": p.get("return_1m_pct"),
                    "avg_volume": p.get("avg_volume_30d"),
                    "_backend": data.get("data_sources", [{}])[0].get("source", "unknown") if data.get("data_sources") else "unknown",
                }
    except Exception:
        price_data = None

    # Direct fallback via fengdata stdlib-Yahoo helper (no yfinance dependency).
    # 快速失败（_tries=2）→ 落到持仓缓存价，避免慢源拖垮整个 daily。
    if not price_data:
        try:
            import fengdata as _fd
            http = _fd._yahoo_chart_http(_fd._to_yahoo_code(ticker) or ticker, _tries=2)
            if http["ok"]:
                d = http["data"]
                price_data = {
                    "price": d["price"], "ma50": d["ma50"], "ma100": d["ma120"], "ma200": d["ma200"],
                    "return_1m_pct": d["return_1m_pct"], "avg_volume": None,
                    "_backend": "yahoo_chart_http (stdlib)",
                }
        except Exception:
            price_data = None

    # Ultimate fallback: use stored holding price so a slow US source never blocks.
    if not price_data and holding and holding.get("position", {}).get("current_price"):
        price_data = {
            "price": holding["position"]["current_price"],
            "ma50": None, "ma100": None, "ma200": None,
            "return_1m_pct": None, "avg_volume": None,
            "_backend": "holding_cached",
        }

    if price_data:
        _PRICE_CACHE[ticker] = {"ts": now, "data": price_data}
    return price_data


def fetch_financials(ticker):
    """Fetch key financial data via fengdata.py (yfinance/腾讯)."""
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(TOOLS, "fengdata.py"), ticker, "--mode", "financials", "--backend=auto"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            f = data.get("financials", {})
            if f and "error" not in f:
                fcf = f.get("fcf_annual", [])
                mcap = f.get("market_cap")
                # 估值泡沫规则需要市值/FCF 比 —— 由 market_cap + 最新 FCF 计算（原恒 None → 死规则）
                mcap_fcf = round(mcap / fcf[0], 1) if (mcap and fcf and fcf[0]) else None
                return {
                    "trailing_pe": f.get("trailing_pe"),
                    "forward_pe": f.get("forward_pe"),
                    "roe_pct": f.get("roe_pct"),
                    "market_cap": mcap,
                    "fcf_annual": fcf,
                    "revenue_annual": f.get("revenue_annual", []),
                    "fcf_latest_positive": (fcf[0] > 0) if fcf else None,
                    "mcap_fcf_ratio": mcap_fcf,
                }
    except Exception:
        pass
    return {}


# ─── Exit Rule Checks ────────────────────────────────────────────

def check_price_stop(h, price_data, mechanical=False):
    """价格止损（双账户分流，2026-08-16 定稿）。

    - TRADING 账户（mechanical=True）：-20% 机械止损线 → RED EXIT；
      环境条件化：MA50<MA200（非动量环境）降级为 YELLOW 警示；ma50/ma200 缺失时保持 RED（风控优先）。
    - INVESTMENT 账户（mechanical=False）：论文驱动，价格跌不触发卖出，
      -20% 仅降级为 YELLOW 警示 + 触发重审（反对机械止损，见 docs/01-philosophy.md）。
    # 文献标尺: Kaminski & Lo 2014《When Do Stop-Loss Rules Stop Losses?》——止损在随机游走环境有害、动量环境增值（月增 50-100bps，1950-2004 美股）
    # 反证: 非动量/震荡环境下机械止损是负贡献，故仅动量环境保持 RED EXIT
    """
    avg_cost = h.get("position", {}).get("avg_cost", 0)
    if avg_cost <= 0:
        return None
    p = price_data.get("price", 0) if price_data else 0
    if p <= 0:
        return None
    drawdown = round((p - avg_cost) / avg_cost * 100, 1)
    if drawdown <= -20:
        if mechanical:
            # 环境条件化（Kaminski-Lo 2014）：动量环境（MA50>MA200）止损增值 → RED EXIT；
            # 非动量环境（MA50<MA200）机械止损有害 → 降级 YELLOW；数据缺失 → 保守保持 RED。
            ma50 = price_data.get("ma50") if price_data else None
            ma200 = price_data.get("ma200") if price_data else None
            if ma50 is not None and ma200 is not None and ma50 < ma200:
                return {"level": "YELLOW", "signal": "WARN", "label": f"价格止损降级(TRADING非动量环境): 现价{p:.2f}, 成本{avg_cost:.2f}, 回撤{drawdown:.1f}% —— 机械止损在非动量环境降级为警示（Kaminski-Lo 2014: 止损仅在动量环境增值）", "value": drawdown}
            return {"level": "RED", "signal": "EXIT", "label": f"价格止损触发(TRADING机械线): 现价{p:.2f}, 成本{avg_cost:.2f}, 回撤{drawdown:.1f}%", "value": drawdown}
        return {"level": "YELLOW", "signal": "WARN", "label": f"浮亏{drawdown:.1f}%（>20%），论文未失效前不卖——触发论文复盘", "value": drawdown}
    elif drawdown <= -15:
        return {"level": "YELLOW", "signal": "WARN", "label": f"接近止损: 回撤{drawdown:.1f}%（阈值-20%）", "value": drawdown}
    else:
        return {"level": "GREEN", "signal": "OK", "label": f"回撤{drawdown:.1f}%", "value": drawdown}


def check_trend_reversal(h, price_data):
    """趋势反转: MA50<MA200+月跌>10% → 退50%。
    # 文献标尺: Brock et al. 1992（买信号收益高）；反证 Huang & Huang 2020（可交易口径跑输）
    """
    if not price_data:
        return None
    ma50 = price_data.get("ma50")
    ma200 = price_data.get("ma200")
    m1 = price_data.get("return_1m_pct")
    if ma50 is None or ma200 is None or m1 is None:
        return None
    if ma50 < ma200 and m1 < -10:
        return {"level": "RED", "signal": "EXIT_HALF", "label": f"趋势反转: MA50({ma50:.1f})<MA200({ma200:.1f}), 月跌{m1:.1f}%", "value": m1}
    elif ma50 < ma200:
        return {"level": "YELLOW", "signal": "WARN", "label": f"MA50({ma50:.1f})<MA200({ma200:.1f})，趋势偏弱", "value": round(ma50 - ma200, 1)}
    else:
        return {"level": "GREEN", "signal": "OK", "label": f"趋势正常 MA50>MA200", "value": None}


def check_thesis_invalidation(h):
    """论文失效: thesis_invalidation标志。
    # 文献标尺: 论文驱动退出（Odean 1998b 处置效应——持有依据必须可证伪）
    """
    triggers = h.get("triggers", {})
    if triggers.get("thesis_invalidation", False):
        return {"level": "RED", "signal": "EXIT", "label": "论文已标记失效 → 立即清仓"}
    return {"level": "GREEN", "signal": "OK", "label": "论文有效"}


def check_thesis_missing(h):
    """论文缺失黄灯（INVESTMENT 账户）: 无 thesis.original 或占位文本 → 黄灯。

    亏损持有无论文支撑 = 处置效应（Odean 1998: 散户 PGR 14.8% vs PLR 9.8%）。
    持有依据必须白纸黑字，缺了就是黄灯，提醒补论文，不直接触发卖出。
    """
    thesis = h.get("thesis", {}) or {}
    original = (thesis.get("original") or "").strip()
    redlines = thesis.get("redlines")
    placeholder = (not original) or "待补" in original or "券商导入" in original
    missing = placeholder or not redlines
    if missing:
        part = "论文缺失" if placeholder else "证伪条件(redlines)缺失"
        return {"level": "YELLOW", "signal": "THESIS_MISSING",
                "label": f"{part}: 亏损持有无论文支撑=处置效应（Odean 1998b: 持亏年化成本约4.4%），请用七层框架/复盘补齐 thesis.original + redlines"}
    return None


def check_review_due(h):
    """审核提醒: next_review_date。"""
    triggers = h.get("triggers", {})
    next_review = triggers.get("next_review_date")
    if not next_review:
        return None
    try:
        rd = datetime.strptime(next_review, "%Y-%m-%d").date()
        today = date.today()
        days_left = (rd - today).days
        if days_left < 0:
            return {"level": "RED", "signal": "REVIEW", "label": f"审核到期: 应于{next_review}审核，已超{abs(days_left)}天"}
        elif days_left <= 7:
            return {"level": "YELLOW", "signal": "SOON", "label": f"审核临近: {days_left}天后（{next_review}）"}
        else:
            return {"level": "GREEN", "signal": "OK", "label": f"下次审核: {next_review}（{days_left}天后）"}
    except ValueError:
        return None


def check_price_triggers(h, price_data):
    """价格提醒触发器: price_up_alert / price_down_alert。"""
    if not price_data:
        return None
    triggers = h.get("triggers", {})
    avg_cost = h.get("position", {}).get("avg_cost", 0)
    p = price_data.get("price", 0)
    if avg_cost <= 0 or p <= 0:
        return None
    change = round((p - avg_cost) / avg_cost * 100, 1)
    up = triggers.get("price_up_alert")
    down = triggers.get("price_down_alert")
    # Normalize: if value looks like decimal (<=1), treat as fraction; otherwise treat as percent
    if up is not None:
        up = up * 100 if up <= 1 else up
    if down is not None:
        down = down * 100 if down >= -1 else down
    alerts = []
    if up and change >= up:
        alerts.append(f"涨幅触发: +{change:.1f}% >= 提醒阈值+{up:.0f}%")
    if down and change <= down:
        alerts.append(f"跌幅触发: {change:.1f}% <= 提醒阈值{down:.0f}%")
    if alerts:
        return {"level": "YELLOW", "signal": "TRIGGER", "label": "; ".join(alerts), "value": change}
    return None


def check_capital_rollover(h, price_data):
    """钱仓滚存: 浮盈≥15%关注, ≥30%建议回收本金（文档两级门槛；0% 不再触发，避免噪音）。
    # 文献标尺: Moreira-Muir 2017（高波动降敞口提升夏普）；反证 Cederburg et al. 2020（样本外不可实施）
    """
    if not price_data:
        return None
    pos = h.get("position", {})
    roll = h.get("capital_rollover", {})
    avg_cost = pos.get("avg_cost", 0)
    shares = pos.get("shares", 0)
    p = price_data.get("price", 0)
    if avg_cost <= 0 or p <= 0 or shares <= 0:
        return None

    total_invested = avg_cost * shares
    market_value = p * shares
    ret = round((p - avg_cost) / avg_cost * 100, 1) if avg_cost else 0

    if roll.get("phase") == "capital_recovered":
        return {"level": "GREEN", "signal": "DONE", "label": "本金已收回, 零成本持有中", "value": market_value}

    if ret >= 30:
        # ceil 保证足额回收本金（与 web /rollover/calculate 取整一致）
        sell_shares = math.ceil(total_invested / p)
        keep = shares - sell_shares
        return {"level": "YELLOW", "signal": "OPPORTUNITY",
                "label": f"滚存建议: 浮盈{ret}%≥30%, 卖{sell_shares}股回收{total_invested:.0f}, 留{keep}股零成本",
                "value": round(market_value - total_invested, 0)}
    if ret >= 15:
        return {"level": "YELLOW", "signal": "SOON",
                "label": f"滚存关注: 浮盈{ret}%≥15%, 可择机回收本金",
                "value": round(market_value - total_invested, 0)}
    return None


def check_fundamental_stop(h, fin_data):
    """基本面止损: FCF由正转负/营收连续降/ROE<10%。
    # 文献标尺: Piotroski 2000（财务强弱预测收益）
    """
    if not fin_data:
        return None

    issues = []
    # FCF latest negative
    fcf = fin_data.get("fcf_annual", [])
    if len(fcf) >= 2 and fcf[0] < 0 and fcf[1] > 0:
        issues.append(f"FCF由正转负 ({fcf[1]:.0f}→{fcf[0]:.0f})")
    elif fcf and fcf[0] < 0:
        issues.append(f"FCF为负 ({fcf[0]:.0f})")

    # Revenue decline
    rev = fin_data.get("revenue_annual", [])
    if len(rev) >= 2 and rev[0] < rev[1]:
        issues.append(f"营收连续下降")

    # ROE
    roe = fin_data.get("roe_pct")
    if roe is not None and roe < 10:
        issues.append(f"ROE {roe:.1f}% < 10%")

    if len(issues) >= 2:
        return {"level": "RED", "signal": "EXIT", "label": "; ".join(issues)}
    elif issues:
        return {"level": "YELLOW", "signal": "WARN", "label": "; ".join(issues)}
    return {"level": "GREEN", "signal": "OK", "label": "基本面正常"}


def check_valuation_bubble(h, fin_data):
    """估值泡沫: FCF/市值比率 >50x → 清仓。
    # 文献标尺: Campbell & Shiller（估值比率预测长期收益）
    """
    if not fin_data:
        return None
    ratio = fin_data.get("mcap_fcf_ratio")
    if ratio is None or isinstance(ratio, str):
        return None
    if ratio > 50:
        return {"level": "RED", "signal": "EXIT", "label": f"市值/FCF = {ratio:.0f} > 50x, 估值泡沫"}
    elif ratio > 35:
        return {"level": "YELLOW", "signal": "WARN", "label": f"市值/FCF = {ratio:.0f}x, 偏高"}
    else:
        return {"level": "GREEN", "signal": "OK", "label": f"市值/FCF = {ratio:.0f}x"}


def _buy_date(h):
    """买入日期：trades[] 首笔 buy，回退 meta.created_at。"""
    for t in (h.get("trades") or []):
        if t.get("type") == "buy" and t.get("date"):
            return t.get("date")
    return (h.get("meta") or {}).get("created_at")


def check_time_stop(h, price_data):
    """时间止损: 持有≥6个月论文未兑现（无 thesis_valid=true 复盘确认）→ 审视（08-exit.md）。

    环境条件化（Kaminski-Lo 2014 条件性）：动量环境（MA50>MA200）维持 YELLOW REVIEW 审视；
    非动量环境（MA50<MA200）暂停时间止损（GREEN 可见，不占级别）；ma50/ma200 缺失 → 维持原判定（保守）。
    # 文献标尺: Kaminski-Lo 2014（条件性）——退出规则仅在动量环境生效，非动量环境执行反而有害
    """
    buy_date = _buy_date(h)
    if not buy_date:
        return None
    try:
        held_days = (date.today() - datetime.strptime(buy_date, "%Y-%m-%d").date()).days
    except ValueError:
        return None
    if held_days < 180:
        return None
    confirmed = any(r.get("thesis_valid") for r in (h.get("reviews") or []))
    if confirmed:
        return {"level": "GREEN", "signal": "OK", "label": f"持有{held_days}天, 论文已复盘确认", "value": held_days}
    # 无 thesis_valid 复盘确认 → 原判定为审视；先做环境判断（Kaminski-Lo 2014: 退出规则仅在动量环境生效）
    ma50 = price_data.get("ma50") if price_data else None
    ma200 = price_data.get("ma200") if price_data else None
    if ma50 is not None and ma200 is not None and ma50 < ma200:
        return {"level": "GREEN", "signal": "OK",
                "label": "时间止损暂停（非动量环境，Kaminski-Lo 2014: 退出规则仅在动量环境生效）",
                "value": held_days}
    return {"level": "YELLOW", "signal": "REVIEW",
            "label": f"时间止损: 持有{held_days}天(≥6个月)论文未兑现/未复盘确认, 需重新评估", "value": held_days}


def check_valuation_regression(h, fin_data):
    """估值回归: thesis 预期价差(valuation_gap/expected_return)未在期限内兑现 → 审视。

    注: 文档「PE>历史80%分位」需历史 PE 分布数据（当前数据源无），
    用 thesis 价差兑现度做可用代理：超期限且浮盈未达预期价差一半 → 审视。
    # 文献标尺: Campbell & Shiller（估值比率预测长期收益）
    """
    the = h.get("thesis") or {}
    gap = the.get("valuation_gap") or the.get("expected_return")
    horizon = the.get("time_horizon_months")
    if not gap or not horizon:
        return None
    buy_date = _buy_date(h)
    if not buy_date:
        return None
    try:
        held_days = (date.today() - datetime.strptime(buy_date, "%Y-%m-%d").date()).days
    except ValueError:
        return None
    if held_days < horizon * 30:
        return None
    pos = h.get("position", {})
    avg = pos.get("avg_cost", 0)
    px = pos.get("current_price", 0)
    if not avg or not px:
        return None
    ret = (px - avg) / avg * 100
    if ret < gap * 50:
        return {"level": "YELLOW", "signal": "WARN",
                "label": f"估值回归未兑现: 持有已超{horizon}个月期限, 浮盈{ret:.1f}%, 未达预期价差{gap*100:.0f}%一半",
                "value": round(ret, 1)}
    return {"level": "GREEN", "signal": "OK", "label": f"估值回归在途: 浮盈{ret:.1f}%, 期限内", "value": round(ret, 1)}


# ─── Analysis Engine ─────────────────────────────────────────────

def analyze_holding(ticker, h=None):
    """Full analysis of a single holding against all exit rules."""
    if h is None:
        h = load_holding(ticker)
    if h is None:
        return {"ticker": ticker, "error": "未找到持仓数据"}

    ticker = _holding_id(h)
    price_data = fetch_price_data(ticker, holding=h)
    fin_data = fetch_financials(ticker)

    # 双账户规则分离（2026-08-16 定稿）：
    #   INVESTMENT（默认）= 论文驱动 —— 价格止损降级为警示，论文/复盘/时间/估值回归为主规则
    #   TRADING          = 机械止损 —— -20% 价格线 RED EXIT，论文类检查不适用
    acct = (h.get("account_type") or "INVESTMENT").upper()
    is_trading = acct == "TRADING"

    checks = {}
    checks["price_stop"] = check_price_stop(h, price_data, mechanical=is_trading)
    checks["trend"] = check_trend_reversal(h, price_data)
    checks["price_trigger"] = check_price_triggers(h, price_data)
    checks["rollover"] = check_capital_rollover(h, price_data)
    checks["fundamental"] = check_fundamental_stop(h, fin_data)
    checks["valuation"] = check_valuation_bubble(h, fin_data)
    if not is_trading:
        checks["thesis"] = check_thesis_invalidation(h)
        # 现金/准现金（LVHI 等"等机会栖身"）不需要论文——论文检查只对权益持仓
        if h.get("qualifier") not in ("cash", "quasi_cash") and h.get("asset_type") != "cash":
            checks["thesis_missing"] = check_thesis_missing(h)
        checks["review_due"] = check_review_due(h)
        checks["time_stop"] = check_time_stop(h, price_data)
        checks["valuation_regression"] = check_valuation_regression(h, fin_data)

    # Determine overall level
    levels = {"GREEN": 0, "YELLOW": 1, "RED": 2}
    worst = "GREEN"
    for name, c in checks.items():
        if c and levels.get(c["level"], 0) > levels[worst]:
            worst = c["level"]

    pos = h.get("position", {})
    p = price_data.get("price") if price_data else None
    avg_cost = pos.get("avg_cost", 0)

    return {
        "ticker": ticker,
        "name": h.get("name") or ticker,  # benchmark 是对标标的，不是持仓名（原误用已修）
        "overall": worst,
        "position": {
            "shares": pos.get("shares", 0),
            "avg_cost": avg_cost,
            "current_price": p if p else pos.get("current_price", 0),
            "total_invested": round(avg_cost * pos.get("shares", 0), 0) if avg_cost and pos.get("shares") else 0,
            "market_value": round(p * pos.get("shares", 0), 0) if p and pos.get("shares") else 0,
            "return_pct": round((p - avg_cost) / avg_cost * 100, 1) if p and avg_cost else None,
        },
        "checks": checks,
        "thesis": h.get("thesis", {}).get("original", ""),
        "account_type": acct,
        "capital_phase": h.get("capital_rollover", {}).get("phase", "capital_at_risk"),
    }


# ─── Journal (Decision Log) ──────────────────────────────────────

def append_journal(entry):
    """Append an entry to the decision journal (JSONL format)."""
    entry["timestamp"] = entry.get("timestamp", datetime.now(timezone.utc).isoformat())
    entry.setdefault("message", entry.get("summary", ""))
    entry.setdefault("action", entry.get("type", ""))
    with open(JOURNAL_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_journal(limit=50):
    """Read journal entries, newest first."""
    if not os.path.exists(JOURNAL_FILE):
        return []
    entries = []
    with open(JOURNAL_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    entries.reverse()
    return entries[:limit]


# ─── Commands ─────────────────────────────────────────────────────

# ─── FX 在岸/离岸价差警戒（fengfx 后续；数据源 = fengfx.py 入库的本地库，纯本地零网络）───
# 语义：USDCNH（离岸）相对 USDCNY（在岸）价差绝对值 > 阈值 → 提醒。
# 离岸显著贵/贱于在岸均代表跨市场资金压力或预期分化，值得关注但非卖出信号。
FX_SPREAD_WARN_PCT = 0.5


def check_fx_spread():
    """读本地库 fx 收盘，计算 USDCNH−USDCNY 价差；缺数据返回 None（不猜数）。"""
    db = os.path.join(BASE, "data", "market_data.db")
    if not os.path.exists(db):
        return None
    con = sqlite3.connect(db)
    try:
        out = {}
        for tk in ("USDCNY", "USDCNH"):
            row = con.execute(
                """SELECT d.date, d.close FROM indices i JOIN daily_data d ON d.index_id=i.id
                   WHERE i.ticker=? AND i.category='fx' ORDER BY d.date DESC LIMIT 1""", (tk,)
            ).fetchone()
            if not row:
                return None
            out[tk] = row
    finally:
        con.close()
    cny_date, cny = out["USDCNY"]
    cnh_date, cnh = out["USDCNH"]
    spread_pct = (cnh - cny) / cny * 100.0
    return {"usdcny": cny, "usdcny_date": cny_date, "usdcnh": cnh, "usdcnh_date": cnh_date,
            "spread_pct": spread_pct, "threshold_pct": FX_SPREAD_WARN_PCT,
            "warn": abs(spread_pct) > FX_SPREAD_WARN_PCT}


def cmd_daily(json_output=False):
    """一键每日分析: 检查所有持仓, 生成提醒, 写日志."""
    holdings = risk_holdings()  # 风险口径：排除真现金（资金池不参与退出检查）
    if not holdings:
        if json_output:
            print(json.dumps({"error": "No holdings"}))
        else:
            print("❌ 无持仓数据. holdings/ 目录为空.")
        return 1

    today = date.today().isoformat()
    results = []
    red_count = 0
    yellow_count = 0

    for h in holdings:
        ticker = _holding_id(h)
        r = analyze_holding(ticker, h)
        results.append(r)
        if r["overall"] == "RED":
            red_count += 1
        elif r["overall"] == "YELLOW":
            yellow_count += 1

    # Save alerts
    alerts = {
        "date": today,
        "total_holdings": len(results),
        "red": red_count,
        "yellow": yellow_count,
        "green": len(results) - red_count - yellow_count,
        "results": results,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    # Web 契约：file-store.getAlerts 读 .alerts[]（AlertItem: ticker/type/message/severity/date）。
    # 非 GREEN 持仓 → 一条提醒（RED=danger / YELLOW=warning），GREEN 不产生提醒。
    alerts["alerts"] = []
    for r in results:
        if r["overall"] == "RED":
            labels = [c["label"] for c in r["checks"].values() if c and c["level"] == "RED"]
            alerts["alerts"].append({
                "ticker": r["ticker"], "type": "EXIT", "severity": "danger",
                "message": "触发退出条件: " + "; ".join(labels), "date": today,
            })
        elif r["overall"] == "YELLOW":
            labels = [c["label"] for c in r["checks"].values() if c and c["level"] == "YELLOW"]
            alerts["alerts"].append({
                "ticker": r["ticker"], "type": "WARN", "severity": "warning",
                "message": "需关注: " + "; ".join(labels), "date": today,
            })
    # FX 在岸/离岸价差警戒（纯本地，缺数据静默跳过不告警）
    fx = check_fx_spread()
    fx_warn = None
    if fx and fx["warn"]:
        direction = "离岸贵于在岸" if fx["spread_pct"] > 0 else "离岸贱于在岸"
        fx_warn = ("汇率价差警戒: USDCNH−USDCNY 价差 %.2f%% 超过 %.1f%%（%s，"
                   "在岸%s / 离岸%s）" % (fx["spread_pct"], fx["threshold_pct"], direction,
                                          fx["usdcny_date"], fx["usdcnh_date"]))
        alerts["alerts"].append({
            "ticker": "FX", "type": "WARN", "severity": "warning",
            "message": fx_warn, "date": today,
        })
    with open(os.path.join(ALERTS_DIR, "today.json"), "w", encoding="utf-8") as f:
        json.dump(alerts, f, indent=2, ensure_ascii=False)

    # Log summary to journal
    entry = {
        "type": "daily_check",
        "date": today,
        "summary": f"检查{len(results)}个持仓: 🟢{alerts['green']} 🟡{yellow_count} 🔴{red_count}",
        "details": {r["ticker"]: r["overall"] for r in results},
    }
    append_journal(entry)

    if json_output:
        print(json.dumps(alerts, indent=2, ensure_ascii=False))
        return 0 if red_count == 0 else 2

    # Human output
    print(f"\n{'='*60}")
    print(f"  FengWatch — 每日持仓检查  {today}")
    print(f"{'='*60}")

    for r in results:
        pos = r["position"]
        label = f"{r['ticker']}  成本{pos['avg_cost']:.0f} → 现价{pos['current_price']:.0f}  ({pos.get('return_pct', '?')}%)"
        icon = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(r["overall"], "⚪")
        print(f"\n  {icon}  {label}")
        for cname, c in r["checks"].items():
            if c and c["level"] != "GREEN":
                signal_icon = {"EXIT": "🚨", "WARN": "⚠️", "OPPORTUNITY": "💰", "REVIEW": "📋", "SOON": "🔔", "TRIGGER": "⚡", "EXIT_HALF": "⚠️"}.get(c.get("signal", ""), "•")
                print(f"     {signal_icon} [{c['level']}] {c['label']}")

    total = len(results)
    green = total - red_count - yellow_count
    print(f"\n{'─'*60}")
    print(f"  总计: {total} 持仓  🟢{green}  🟡{yellow_count}  🔴{red_count}")
    if red_count > 0:
        print(f"\n  🚨 有 {red_count} 个持仓触发退出条件!")
        for r in results:
            if r["overall"] == "RED":
                print(f"     {r['ticker']} — 需立即处理")
    if yellow_count > 0:
        print(f"\n  ⚠️ 有 {yellow_count} 个持仓需关注。")
        for r in results:
            if r["overall"] == "YELLOW":
                trouble = [c["label"] for c in r["checks"].values() if c and c["level"] == "YELLOW"]
                for t in trouble:
                    print(f"     {r['ticker']} — {t}")
    if red_count == 0 and yellow_count == 0:
        print("  ✅ 一切正常，无待处理事项")
    if fx_warn:
        print(f"  ⚠️  {fx_warn}")
    print(f"{'='*60}\n")
    print(f"  [记录] alerts/today.json 已更新")
    print(f"  [日志] 已追加到 logs/journal.jsonl")

    return 0 if red_count == 0 else 2


def cmd_check(args):
    """检查持仓退出条件。不指定ticker则全部。"""
    json_output = "--json" in args
    if json_output:
        args = [a for a in args if a != "--json"]

    ticker = args[0].upper() if args else None

    if ticker:
        h = load_holding(ticker)
        if not h:
            if json_output:
                print(json.dumps({"error": f"未找到持仓: {ticker}"}))
            else:
                print(f"❌ 未找到持仓: {ticker}")
            return 1
        holdings_data = [(ticker, h)]
    else:
        holdings_data = [(_holding_id(h), h) for h in risk_holdings()]  # 风险口径：排除真现金
        if not holdings_data:
            if json_output:
                print(json.dumps({"error": "无持仓数据"}))
            else:
                print("❌ 无持仓数据")
            return 1

    results = []
    for ticker, h in holdings_data:
        r = analyze_holding(ticker, h)
        results.append(r)

    if json_output:
        print(json.dumps(results, indent=2, ensure_ascii=False))
        return 0

    for r in results:
        pos = r["position"]
        icon = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(r["overall"], "⚪")
        ret = pos.get("return_pct")
        ret_str = f"{ret:+.1f}%" if ret is not None else "?"

        print(f"\n{'─'*50}")
        print(f"  {icon} {r['ticker']}")
        print(f"    持仓: {pos['shares']}股 × 均价{pos['avg_cost']:.2f}")
        print(f"    现价: {pos['current_price']:.2f}  ({ret_str})")
        print(f"    市值: {pos['market_value']:.0f}  投入: {pos['total_invested']:.0f}")

        if r.get("thesis"):
            print(f"    论文: {r['thesis'][:80]}{'…' if len(r['thesis']) > 80 else ''}")

        print(f"\n    退出条件检查:")
        for cname, c in r["checks"].items():
            if c:
                icons = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}
                print(f"      {icons.get(c['level'], '⚪')} {c['label']}")
            else:
                print(f"     ⚪ {cname} (无数据)")

        print()

    return 0


def cmd_review(ticker):
    """复盘持仓: 记入日志 & 生成复盘文件。"""
    h = load_holding(ticker)
    if not h:
        print(f"❌ 未找到持仓: {ticker}")
        return 1

    r = analyze_holding(ticker, h)
    pos = r["position"]
    today_str = date.today().isoformat()

    print(f"\n{'='*60}")
    print(f"  复盘: {ticker}")
    print(f"{'='*60}")
    print(f"\n  当前状态:")
    print(f"    成本: {pos['avg_cost']:.2f}  现价: {pos['current_price']:.2f}")
    print(f"    盈亏: {pos.get('return_pct', '?')}%")
    print(f"    论文: {h.get('thesis', {}).get('original', '无')}")
    print(f"    资本阶段: {h.get('capital_rollover', {}).get('phase', 'capital_at_risk')}")

    review_path = os.path.join(REVIEWS_DIR, f"review_{ticker}_{today_str}.md")
    with open(review_path, "w", encoding="utf-8") as f:
        f.write(f"""# 复盘: {ticker}

日期: {today_str}

## 持仓数据

| 字段 | 值 |
|:----|:---|
| 持仓数 | {pos['shares']} 股 |
| 均价 | {pos['avg_cost']:.2f} |
| 现价 | {pos['current_price']:.2f} |
| 盈亏 | {pos.get('return_pct', '?')}% |
| 市值 | {pos['market_value']:.0f} |
| 资本阶段 | {r.get('capital_phase', 'capital_at_risk')} |

## 投资论文

{h.get('thesis', {}).get('original', '无')}

## 退出条件状态

""")
        for cname, c in r["checks"].items():
            if c:
                f.write(f"- [{c['level']}] {c['label']}\n")
            else:
                f.write(f"- [N/A] {cname}: 无数据\n")

        f.write(f"""

## 复盘笔记

- **论文是否仍然有效**:
- **学到了什么**:
- **下次关注点**:
- **操作**:

## 操作日志

| 日期 | 操作 | 理由 |
|:----|:----|:-----|
| {today_str} | 复盘 | — |
""")

    # Log the review
    entry = {
        "type": "review",
        "ticker": ticker,
        "date": today_str,
        "summary": f"复盘{ticker}: 盈亏{pos.get('return_pct', '?')}%",
        "review_file": review_path,
    }
    append_journal(entry)

    print(f"\n  ✅ 复盘文件已生成: {review_path}")
    print(f"  📝 编辑该文件填写复盘笔记后保存。")
    print(f"  📋 日志已记录。")
    return 0


def cmd_outcome(args):
    """复盘 outcome 追踪: 统计 hypotheses[].outcome 状态（不指定 TICKER=全部）。

    预测-结果闭环（holdings/SCHEMA.md「outcome 判定」章）：登记时
    hypotheses[].outcome.expected 必填，复盘时判定 hit/falsified/partial/pending
    并写回 evidence（由 /fengreview 执行）。本命令只读统计，不写任何持仓 JSON。
    """
    json_output = "--json" in args
    if json_output:
        args = [a for a in args if a != "--json"]

    ticker = args[0].upper() if args else None
    if ticker:
        h = load_holding(ticker)
        if not h:
            if json_output:
                print(json.dumps({"error": f"未找到持仓: {ticker}"}, ensure_ascii=False))
            else:
                print(f"❌ 未找到持仓: {ticker}")
            return 1
        holdings_data = [h]
    else:
        holdings_data = load_holdings()

    OUTCOME_STATES = ("hit", "falsified", "partial", "pending")
    agg = {"total_hypotheses": 0, "hit": 0, "falsified": 0, "partial": 0, "pending": 0, "missing_outcome": 0}
    items = []
    for h in holdings_data:
        hyps = (h.get("thesis") or {}).get("hypotheses") or []
        counts = {k: 0 for k in OUTCOME_STATES}
        missing_outcome = 0
        missing_expected = 0
        detail = []
        for hp in hyps:
            oc = hp.get("outcome") if isinstance(hp.get("outcome"), dict) else {}
            st = oc.get("status")
            if st in OUTCOME_STATES:
                counts[st] += 1
            else:
                missing_outcome += 1
            exp = oc.get("expected")
            if not exp:
                missing_expected += 1
            detail.append({
                "id": hp.get("id"),
                "statement": hp.get("statement"),
                "status": hp.get("status"),          # 四态 valid/weakened/damaged/broken
                "outcome": {
                    "status": st,
                    "expected": exp,
                    "horizon": oc.get("horizon"),
                    "evaluated_date": oc.get("evaluated_date"),
                    "evidence": oc.get("evidence"),
                },
            })
        hid = _holding_id(h)
        item = {
            "ticker": hid,
            "name": h.get("name") or hid,
            "hypotheses_total": len(hyps),
            "outcome_counts": counts,
            "missing_outcome": missing_outcome,
            "missing_expected": missing_expected,
        }
        if detail:
            item["hypotheses"] = detail
        hints = []
        if not hyps:
            hints.append("thesis.hypotheses 为空，尚未建立可证伪假设（见 fengholding 论文建立）")
        if missing_outcome:
            hints.append(f"{missing_outcome} 条假设缺 outcome.status（复盘必判）")
        if missing_expected:
            hints.append(f"{missing_expected} 条假设缺 outcome.expected（登记必填）")
        if hints:
            item["hint"] = "; ".join(hints)
        items.append(item)
        agg["total_hypotheses"] += len(hyps)
        for k in counts:
            agg[k] += counts[k]
        agg["missing_outcome"] += missing_outcome

    result = {
        "command": "outcome",
        "date": date.today().isoformat(),
        "holdings": len(items),
        "summary": agg,
        "items": items,
    }

    if json_output:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"\n{'='*60}")
    print(f"  outcome 追踪（预测-结果闭环）  {result['date']}")
    print(f"{'='*60}")
    s = agg
    print(f"\n  汇总: {s['total_hypotheses']} 条假设  ✅hit {s['hit']}  ❌falsified {s['falsified']}  ⚠️partial {s['partial']}  ⏳pending {s['pending']}  缺判定 {s['missing_outcome']}")
    for it in items:
        c = it["outcome_counts"]
        line = f"  {it['ticker']:<12} 假设 {it['hypotheses_total']} 条  hit {c['hit']}  falsified {c['falsified']}  partial {c['partial']}  pending {c['pending']}"
        if it["missing_outcome"] or it["missing_expected"]:
            line += f"  [缺判定 {it['missing_outcome']} / 缺expected {it['missing_expected']}]"
        print(line)
        if it.get("hint"):
            print(f"      ↳ {it['hint']}")
        for hp in it.get("hypotheses", []):
            oc = hp["outcome"]
            st = oc.get("status") or "⛔无判定"
            print(f"      {st:<10} {hp.get('id')}  {str(hp.get('statement'))[:48]}")
            if oc.get("evidence"):
                print(f"                evidence: {str(oc['evidence'])[:64]}")
    print(f"\n  [提示] 复盘判定与写回见 /fengreview（4.2）；本命令只读不写。")
    print(f"{'='*60}\n")
    return 0


def cmd_log(args):
    """查看决策日志。"""
    limit = 50
    if args and args[0] == "--limit" and len(args) > 1:
        limit = int(args[1])

    entries = read_journal(limit)
    if not entries:
        print("📝 决策日志为空。执行 daily/review 后会有记录。")
        return 0

    print(f"\n{'='*60}")
    print(f"  决策日志  (最近{len(entries)}条)")
    print(f"{'='*60}")

    for e in entries:
        ts = e.get("timestamp", e.get("date", "?"))
        if len(ts) > 19:
            ts = ts[:19]
        dtype = e.get("type", "?")
        ticker = e.get("ticker", "")
        summary = e.get("summary", "")
        icons = {"daily_check": "📊", "review": "📝", "buy": "🟢", "sell": "🔴", "alert": "🔔"}
        icon = icons.get(dtype, "•")
        print(f"\n  {icon} [{ts}] {dtype.upper()} {ticker}")
        if summary:
            print(f"     {summary}")

    print(f"\n{'='*60}\n")
    return 0


def cmd_alert():
    """显示当前提醒。"""
    today_file = os.path.join(ALERTS_DIR, "today.json")
    if not os.path.exists(today_file):
        print("📭 无提醒。先执行 `fengwatch.py daily` 生成。")
        return 0

    with open(today_file, encoding="utf-8") as f:
        alerts = json.load(f)

    print(f"\n{'='*60}")
    print(f"  当前提醒  ({alerts.get('date', '?')})")
    print(f"{'='*60}")
    print(f"  持仓: {alerts['total_holdings']}  🟢{alerts['green']}  🟡{alerts['yellow']}  🔴{alerts['red']}")

    results = alerts.get("results", [])
    for r in results:
        icon = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}.get(r.get("overall", ""), "⚪")
        ret = r.get("position", {}).get("return_pct", "?")
        print(f"  {icon} {r['ticker']}  ({ret}%)")

    print(f"\n  生成: {alerts.get('generated_at', '?')[:19]}")
    print(f"\n  重新运行: fengwatch.py daily")
    print(f"{'='*60}\n")
    return 0


# ─── Sell Command ────────────────────────────────────────────────

_EXIT_REASON_KEYS = ("价格止损", "基本面", "时间止损", "估值回归", "估值泡沫", "论文失效", "滚存")


def _warn_if_no_exit_reason(reason):
    """六类退出理由/滚存关键词未命中 → 软警示（不阻断执行，提示确认纪律依据）。"""
    if not any(k in (reason or "") for k in _EXIT_REASON_KEYS):
        print("  ⚠️ 理由未匹配六类退出理由（价格止损/基本面/时间止损/估值回归/估值泡沫/论文失效/滚存）")
        print("     —— 无纪律依据的卖出需用户二次确认；组合超限不是卖出理由（见 fengexit SKILL 拦截原则）")


def _credit_cash(currency, amount, zone):
    """卖出回笼资金入池：CN_IN → cash_cny（按实时汇率折 CNY）；OVERSEAS → cash_<币种>（原币）。

    找不到对应现金持仓 → 返回 False 并提示人工登记，不崩溃。"""
    try:
        import fengportfolio as FP
        fxr = FP.fx_info()["FX"].get(currency, 1.0)
    except Exception:
        fxr = 1.0
    if zone == "CN_IN":
        target, credit = "cash_cny", round(amount * fxr, 2)
    else:
        cur = (currency or "").lower()
        if cur not in ("cny", "hkd", "usd"):
            return False
        target, credit = f"cash_{cur}", round(amount, 2)
    path = os.path.join(HOLDINGS_DIR, f"hold_{target}.json")
    if not os.path.exists(path):
        print(f"  ⚠️ 未找到现金持仓 {target}，回笼资金 {credit:,.2f} 未入池（请用 fengholding add 登记）")
        return False
    with open(path, encoding="utf-8") as f:
        c = json.load(f)
    pos = c.setdefault("position", {})
    pos["amount"] = round((pos.get("amount") or 0) + credit, 2)
    pos["market_value"] = pos["amount"]
    cap = c.setdefault("capital", {})
    cap["cost_basis"] = round((cap.get("cost_basis") or 0) + credit, 2)
    cap["market_value_equiv_cny"] = round(pos["amount"] * (1.0 if target == "cash_cny" else fxr), 2)
    c.setdefault("meta", {})["updated_at"] = date.today().isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=2, ensure_ascii=False)
    return True


def cmd_sell(args):
    """记录卖出: fengwatch.py sell <TICKER> [--price P] [--shares N] [--reason REASON]"""
    if not args:
        print("用法: fengwatch.py sell <TICKER> [--price P] [--shares N] [--reason '理由']")
        return 1

    ticker = args[0].upper()
    # Parse optional flags
    sell_price = None
    sell_shares = None
    sell_reason = ""
    i = 1
    while i < len(args):
        if args[i] == "--price" and i + 1 < len(args):
            sell_price = float(args[i + 1])
            i += 2
        elif args[i] == "--shares" and i + 1 < len(args):
            sell_shares = float(args[i + 1])
            i += 2
        elif args[i] == "--reason" and i + 1 < len(args):
            sell_reason = args[i + 1]
            i += 2
        else:
            i += 1

    h = load_holding(ticker)
    if not h:
        print(f"❌ 未找到持仓: {ticker}")
        return 1

    pos = h.get("position", {})
    today_str = date.today().isoformat()

    # Default to current market price
    if sell_price is None:
        price_data = fetch_price_data(ticker)
        sell_price = price_data["price"] if price_data else pos.get("current_price", 0)

    if sell_shares is None:
        sell_shares = pos.get("shares", 0)

    # Calculate
    buy_cost = pos.get("avg_cost", 0)
    total_invested = buy_cost * sell_shares
    total_returned = sell_price * sell_shares
    return_pct = round((sell_price - buy_cost) / buy_cost * 100, 1) if buy_cost else 0
    realized_pnl = round(total_returned - total_invested, 2)

    hold_period = 0
    buy_date = _buy_date(h) or h.get("buy_date", "")
    if buy_date:
        try:
            hold_period = (date.today() - datetime.strptime(buy_date, "%Y-%m-%d").date()).days
        except ValueError:
            pass

    trade_record = {
        "date": today_str, "type": "sell", "shares": round(sell_shares, 4),
        "price": round(sell_price, 2), "currency": h.get("currency", ""),
        "note": f"卖出理由: {sell_reason or '未指定'}",
    }
    # 2.6 卖出闭环：trades / capital.realized_pl / lifecycle_phase 全字段更新
    trades = list(h.get("trades") or [])
    trades.append(trade_record)
    cap = dict(h.get("capital") or {})
    cap["realized_pl"] = round((cap.get("realized_pl") or 0) + realized_pnl, 2)

    sell_info = {
        "sell_date": today_str,
        "sell_price": round(sell_price, 2),
        "shares_sold": sell_shares,
        "total_invested": round(total_invested, 0),
        "total_returned": round(total_returned, 0),
        "return_pct": return_pct,
        "hold_period_days": hold_period,
        "sell_reason": sell_reason,
    }

    total_shares = pos.get("shares", 0)
    is_partial = sell_shares < total_shares

    if is_partial:
        # 部分卖出（滚存回收本金/减仓）：持仓保持活跃，更新余仓 + 滚存状态
        h["trades"] = trades
        h["capital"] = cap
        pos["shares"] = round(total_shares - sell_shares, 4)
        if "market_value" in pos and pos["market_value"]:
            pos["market_value"] = round((total_shares - sell_shares) * sell_price, 2)
        roll = dict(h.get("capital_rollover") or {})
        roll["recovered"] = round((roll.get("recovered") or 0) + total_returned, 2)
        roll["recoverable_at_price"] = sell_price
        roll["zero_cost_shares"] = round(total_shares - sell_shares, 4)
        roll["phase"] = "capital_recovered" if (roll.get("recovered") or 0) >= (roll.get("total_invested") or 0) else "partial_recovery"
        h["capital_rollover"] = roll
        meta = h.setdefault("meta", {})
        meta["updated_at"] = today_str
        h["sell_info"] = sell_info  # 最近一次卖出信息
        with open(os.path.join(HOLDINGS_DIR, f"hold_{ticker}.json"), "w", encoding="utf-8") as f:
            json.dump(h, f, indent=2, ensure_ascii=False)

        if _credit_cash(h.get("currency", ""), total_returned, h.get("capital_zone", "OVERSEAS")):
            print(f"     回笼资金 {total_returned:,.0f} {h.get('currency','')} 已入池（买入预算可用）")

        entry = {
            "type": "sell",
            "ticker": ticker,
            "date": today_str,
            "summary": f"部分卖出{ticker}: {sell_shares:.0f}股 @ {sell_price:.2f}, 回收{total_returned:.0f}, 余{pos['shares']:.0f}股, 盈亏{return_pct:+.1f}%",
            "details": sell_info,
        }
        append_journal(entry)

        print(f"\n  ✅ 已记录部分卖出 {ticker}（滚存/减仓）")
        print(f"     卖出: {sell_shares:.0f}股 @ {sell_price:.2f}, 回收本金 {total_returned:.0f}")
        print(f"     余仓: {pos['shares']:.0f}股（零成本筹码）")
        print(f"     滚存阶段: {roll['phase']}")
        print(f"     已实现盈亏: {realized_pnl:+.0f}")
        print(f"     📝 日志已记录\n")
        _warn_if_no_exit_reason(sell_reason)
        return 0

    # 全部卖出 → 归档（SCHEMA 闭仓流程）
    closed = dict(h)
    closed["status"] = "closed"
    closed["lifecycle_phase"] = "closed"
    closed["trades"] = trades
    closed["capital"] = cap
    closed["sell_info"] = sell_info

    # Archive: rename file
    old_path = os.path.join(HOLDINGS_DIR, f"hold_{ticker}.json")
    new_name = f"hold_{ticker}_closed_{today_str}.json"
    new_path = os.path.join(HOLDINGS_DIR, new_name)
    os.rename(old_path, new_path)
    with open(new_path, "w", encoding="utf-8") as f:
        json.dump(closed, f, indent=2, ensure_ascii=False)

    if _credit_cash(closed.get("currency", ""), total_returned, closed.get("capital_zone", "OVERSEAS")):
        print(f"     回笼资金 {total_returned:,.0f} {closed.get('currency','')} 已入池（买入预算可用）")

    # Journal entry
    entry = {
        "type": "sell",
        "ticker": ticker,
        "date": today_str,
        "summary": f"卖出{ticker}: {sell_shares:.0f}股 @ {sell_price:.2f}, 盈亏{return_pct:+.1f}%, 持有{hold_period}天",
        "details": sell_info,
    }
    append_journal(entry)

    print(f"\n  ✅ 已记录卖出 {ticker}")
    print(f"     卖出: {sell_shares:.0f}股 @ {sell_price:.2f}")
    print(f"     盈亏: {return_pct:+.1f}%（已实现 {realized_pnl:+.0f} 入 capital.realized_pl）")
    print(f"     持有: {hold_period}天")
    print(f"     理由: {sell_reason or '未指定'}")
    print(f"     归档: {new_name}")
    print(f"     📝 日志已记录\n")
    _warn_if_no_exit_reason(sell_reason)
    return 0


# ─── History Commands ────────────────────────────────────────────

def cmd_history(args):
    """历史持仓分析: history, history losses, history import <file>"""
    if not args:
        return _show_history_summary()

    sub = args[0]
    rest = args[1:]

    if sub == "losses":
        return _show_history_losses()
    elif sub == "import":
        return cmd_history_import(rest)
    else:
        print("用法:")
        print("  fengwatch.py history                  显示所有历史持仓")
        print("  fengwatch.py history losses           只看亏损交易")
        print("  fengwatch.py history import <file>    导入历史交易")
        return 1


def _show_history_summary():
    """Show summary of all trades (active + closed)."""
    active = risk_holdings()  # 交易历史视角：现金非交易，排除
    closed = load_closed_holdings()

    print(f"\n{'='*60}")
    print(f"  持仓历史总览")
    print(f"{'='*60}")

    print(f"\n  当前持仓: {len(active)}")
    for h in active:
        pos = h.get("position", {})
        ac = pos.get("avg_cost", 0)
        cp = pos.get("current_price", 0)
        if ac and cp:
            rp = round((cp - ac) / ac * 100, 1)
            pct = f"{rp:+.1f}%"
        else:
            pct = "?"
        print(f"     🟢 {_holding_id(h)}  成本{ac:.2f} → 现价{cp:.2f}  ({pct})")

    print(f"\n  已平仓: {len(closed)}")
    total_pnl = 0
    wins = 0
    losses = 0
    total_days = 0

    for h in closed:
        s = h.get("sell_info", {})
        pct = s.get("return_pct", 0)
        pnl = s.get("total_returned", 0) - s.get("total_invested", 0)
        days = s.get("hold_period_days", 0)
        total_pnl += pnl
        total_days += days

        icon = "🟢" if pct >= 0 else "🔴"
        print(f"     {icon} {_holding_id(h)}  {s.get('sell_date', '?')}  盈亏{pct:+.1f}%  ({pnl:+.0f})  持有{days}天")
        if s.get("sell_reason"):
            print(f"        理由: {s['sell_reason']}")
        if pct >= 0:
            wins += 1
        else:
            losses += 1

    total_trades = wins + losses
    print(f"\n{'─'*60}")
    print(f"  胜率: {wins}/{total_trades} ({round(wins/total_trades*100, 1) if total_trades else 0}%)")
    print(f"  总盈亏: {total_pnl:+.0f}")
    print(f"  平均持有: {round(total_days/total_trades) if total_trades else 0}天")
    print(f"{'='*60}\n")
    return 0


def _show_history_losses():
    """Show only losing trades."""
    closed = load_closed_holdings()
    losses_data = []

    for h in closed:
        s = h.get("sell_info", {})
        pct = s.get("return_pct", 0)
        if pct >= 0:
            continue
        losses_data.append({
            "ticker": _holding_id(h),
            "sell_date": s.get("sell_date", "?"),
            "return_pct": pct,
            "pnl": s.get("total_returned", 0) - s.get("total_invested", 0),
            "hold_days": s.get("hold_period_days", 0),
            "sell_reason": s.get("sell_reason", ""),
        })

    losses_data.sort(key=lambda x: x["return_pct"])

    print(f"\n{'='*60}")
    print(f"  亏损交易分析  ({len(losses_data)}笔)")
    print(f"{'='*60}")

    if not losses_data:
        print("\n  🎉 暂无亏损记录！\n")
        return 0

    total_lost = sum(l["pnl"] for l in losses_data)
    print(f"\n  总亏损: {total_lost:.0f}")
    print(f"  平均亏损: {round(total_lost/len(losses_data)):.0f}" if losses_data else "")

    # Worst trades
    print(f"\n  亏损排行:")
    for i, l in enumerate(losses_data, 1):
        print(f"    {i}. 🔴 {l['ticker']}  {l['return_pct']:.1f}% ({l['pnl']:+.0f})  持有{l['hold_days']}天")
        if l["sell_reason"]:
            print(f"       理由: {l['sell_reason']}")

    # Pattern analysis from reviews
    reviews = [f for f in os.listdir(REVIEWS_DIR) if f.endswith(".md")] if os.path.isdir(REVIEWS_DIR) else []
    if reviews:
        print(f"\n  复盘记录: {len(reviews)}篇")
        for r in reviews[-5:]:
            print(f"    📝 {r}")

    sell_entries = [e for e in read_journal(200) if e.get("type") == "sell"]
    if sell_entries:
        print(f"\n  卖出记录: {len(sell_entries)}次")
        for e in sell_entries[-5:]:
            print(f"    📄 {e.get('date','?')} — {e.get('summary','')}")

    print(f"\n{'='*60}\n")
    return 0


def cmd_history_import(args):
    """导入历史交易: fengwatch.py history import <file.json>"""
    if not args:
        print("用法: fengwatch.py history import <file.json>")
        return 1

    file_path = args[0]
    if not os.path.exists(file_path):
        print(f"❌ 文件不存在: {file_path}")
        return 1

    with open(file_path, encoding="utf-8") as f:
        trades = json.load(f)

    if not isinstance(trades, list):
        trades = [trades]

    imported = 0
    for t in trades:
        ticker = t.get("ticker", "").upper()
        if not ticker:
            continue

        buy_date = t.get("buy_date", "")
        sell_date = t.get("sell_date", date.today().isoformat())
        buy_price = t.get("buy_price", 0)
        sell_price = t.get("sell_price", 0)
        shares = t.get("shares", 0)
        sell_reason = t.get("sell_reason", "")

        if not buy_price or not sell_price or not shares:
            print(f"  ⚠️ 跳过 {ticker}: 数据不完整")
            continue

        total_invested = buy_price * shares
        total_returned = sell_price * shares
        return_pct = round((sell_price - buy_price) / buy_price * 100, 1)
        hold_days = 0
        if buy_date and sell_date:
            try:
                hold_days = (datetime.strptime(sell_date, "%Y-%m-%d").date() - datetime.strptime(buy_date, "%Y-%m-%d").date()).days
            except ValueError:
                pass

        closed = {
            "ticker": ticker,
            "status": "closed",
            "buy_date": buy_date,
            "position": {"avg_cost": buy_price, "shares": shares},
            "sell_info": {
                "sell_date": sell_date,
                "sell_price": sell_price,
                "shares_sold": shares,
                "total_invested": round(total_invested, 0),
                "total_returned": round(total_returned, 0),
                "return_pct": return_pct,
                "hold_period_days": hold_days,
                "sell_reason": sell_reason,
            },
        }

        new_name = f"hold_{ticker}_closed_{sell_date}.json"
        new_path = os.path.join(HOLDINGS_DIR, new_name)
        with open(new_path, "w", encoding="utf-8") as f:
            json.dump(closed, f, indent=2, ensure_ascii=False)

        print(f"  ✅ 导入 {ticker}: 买入{buy_price:.2f} → 卖出{sell_price:.2f} ({return_pct:+.1f}%)  {sell_date}")
        imported += 1

    print(f"\n  共导入 {imported} 笔交易")
    if imported > 0:
        print(f"  文件: holdings/hold_<TICKER>_closed_<DATE>.json\n")
    return 0

def cmd_fund_share(args):
    """ETF/LOF 份额变动监控：查询沪深交易所直连 API，检测份额异动。

    用法:
        fengwatch.py fund-share                  查询全量 ETF/LOF 份额
        fengwatch.py fund-share --codes 510300,161725   指定代码查询
        fengwatch.py fund-share --exchange SSE   只查上交所
        fengwatch.py fund-share --exchange SZSE  只查深交所
        fengwatch.py fund-share --threshold 3    设置告警阈值（百分比）
        fengwatch.py fund-share --json           纯净 JSON 输出
        fengwatch.py fund-share --top 20         只显示变动最大的前 N 条
    """
    json_output = "--json" in args

    # 解析参数
    codes = None
    exchange = None
    threshold = FUND_SHARE_WARN_PCT
    top_n = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--json":
            i += 1
        elif arg == "--codes" and i + 1 < len(args):
            codes = [c.strip() for c in args[i + 1].split(",")]
            i += 2
        elif arg == "--exchange" and i + 1 < len(args):
            exchange = args[i + 1].upper()
            i += 2
        elif arg == "--threshold" and i + 1 < len(args):
            try:
                threshold = float(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif arg == "--top" and i + 1 < len(args):
            try:
                top_n = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        else:
            i += 1

    exchanges = [exchange] if exchange else None

    # 查询份额数据
    try:
        raw_data = fetch_all_fund_shares(codes=codes, exchanges=exchanges)
    except Exception as e:
        if json_output:
            print(json.dumps({"error": f"份额查询失败: {str(e)}"}))
        else:
            print(f"份额查询失败: {e}")
        return 1

    if not raw_data:
        if json_output:
            print(json.dumps({"error": "未获取到份额数据", "hint": "交易所 API 可能未更新或非交易日",
                              "fetch_errors": fund_fetch_errors()}))
        else:
            print("未获取到份额数据。可能原因：交易所 API 未更新（非交易日/数据延迟）。")
        return 1

    # 计算份额变动
    results = compute_share_changes(raw_data, warn_pct=threshold)

    # 按变动幅度排序（绝对值大的在前）
    results.sort(key=lambda x: abs(x.get("change_pct") or 0), reverse=True)

    # 截取 top N
    if top_n and top_n > 0:
        results = results[:top_n]

    # 统计
    total = len(results)
    warn_count = sum(1 for r in results if r["alert_level"] == "WARN")
    watch_count = sum(1 for r in results if r["alert_level"] == "WATCH")
    ok_count = sum(1 for r in results if r["alert_level"] == "OK")
    na_count = sum(1 for r in results if r["alert_level"] == "N/A")

    output = {
        "command": "fund-share",
        "date": date.today().isoformat(),
        "threshold_pct": threshold,
        "summary": {
            "total": total,
            "warn": warn_count,
            "watch": watch_count,
            "ok": ok_count,
            "no_data": na_count,
        },
        "items": results,
    }
    # fail-loud：某源 HTTP 失败导致结果截断时，把明细透出——有数据≠全拿到了
    if _FUND_FETCH_ERRORS:
        output["fetch_errors"] = fund_fetch_errors()

    if json_output:
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return 0

    # 人类可读输出
    print(f"\n{'='*65}")
    print(f"  ETF/LOF 份额变动监控  {output['date']}")
    print(f"  数据来源: 上交所 + 深交所直连 API  |  告警阈值: ±{threshold}%")
    print(f"{'='*65}")

    # 先显示告警项
    alerts = [r for r in results if r["alert_level"] in ("WARN", "WATCH")]
    if alerts:
        print(f"\n  --- 份额异动告警 ({len(alerts)} 只) ---")
        for r in alerts:
            icon = "!!" if r["alert_level"] == "WARN" else " ~"
            cp = r.get("change_pct")
            cs = r.get("change_shares")
            unit = "万份" if r.get("exchange") == "SZSE" or (r.get("exchange") == "SSE" and r.get("type") == "LOF") else "份"
            cp_str = f"{cp:+.2f}%" if cp is not None else "N/A"
            cs_str = f"{cs:+,.0f}{unit}" if cs is not None else ""
            print(f"  {icon} {r['code']}  {r['name'][:12]:<12}  {r['share']:>14,.0f}{unit}  变动 {cp_str:>8}  ({cs_str})")
            print(f"      [{r['exchange']}] {r.get('type', 'ETF')}")

    # 正常项汇总
    ok_items = [r for r in results if r["alert_level"] == "OK"]
    na_items = [r for r in results if r["alert_level"] == "N/A"]

    print(f"\n  --- 份额正常 ({len(ok_items)} 只) ---")
    for r in ok_items[:10]:
        cp = r.get("change_pct")
        cp_str = f"{cp:+.2f}%" if cp is not None else "N/A"
        print(f"     {r['code']}  {r['name'][:12]:<12}  变动 {cp_str}")
    if len(ok_items) > 10:
        print(f"     ... 还有 {len(ok_items) - 10} 只正常（用 --json 查看完整列表）")

    if na_items:
        print(f"\n  --- 无历史对比数据 ({len(na_items)} 只) ---")
        for r in na_items[:5]:
            print(f"     {r['code']}  {r['name'][:12]:<12}  当前份额 {r['share']:>14,.0f}")
        if len(na_items) > 5:
            print(f"     ... 还有 {len(na_items) - 5} 只")

    print(f"\n{'─'*65}")
    print(f"  总计: {total} 只  告警: {warn_count}  关注: {watch_count}  正常: {ok_count}  无数据: {na_count}")
    print(f"  用法: --codes 510300,161725 --threshold 3 --top 20 --json")
    print(f"{'='*65}\n")
    return 0


def main():
    if len(sys.argv) < 2:
        print("FengWatch — 持仓监控引擎")
        print()
        print("用法:")
        print("  fengwatch.py daily                 一键每日分析")
        print("  fengwatch.py check [TICKER]        检查退出条件")
        print("  fengwatch.py review <TICKER>       复盘持仓")
        print("  fengwatch.py outcome [TICKER]      复盘假设 outcome 统计（--json）")
        print("  fengwatch.py sell <TICKER>         记录卖出并归档")
        print("  fengwatch.py history               历史持仓总览")
        print("  fengwatch.py history losses        亏损交易分析")
        print("  fengwatch.py history import <file> 导入历史交易")
        print("  fengwatch.py log [--limit N]       查看决策日志")
        print("  fengwatch.py alert                 显示当前提醒")
        print("  fengwatch.py fund-share [opts]     ETF/LOF 份额变动监控")
        print()
        sys.exit(1)

    cmd = sys.argv[1]
    args = sys.argv[2:]
    json_output = "--json" in args
    if json_output:
        args = [a for a in args if a != "--json"]

    cmds = {
        "daily": lambda: cmd_daily(json_output),
        "check": lambda: cmd_check(args + (["--json"] if json_output else [])),
        "review": lambda: cmd_review(args[0]) if args else (print("用法: fengwatch.py review <TICKER>") or 1),
        "outcome": lambda: cmd_outcome(args + (["--json"] if json_output else [])),
        "sell": lambda: cmd_sell(args),
        "history": lambda: cmd_history(args),
        "log": lambda: cmd_log(args),
        "alert": cmd_alert,
        "fund-share": lambda: cmd_fund_share(args + (["--json"] if json_output else [])),
    }

    if cmd not in cmds:
        print(f"未知命令: {cmd}")
        print("可用: daily, check, review, outcome, sell, history, log, alert, fund-share")
        sys.exit(1)

    sys.exit(cmds[cmd]())


if __name__ == "__main__":
    main()
