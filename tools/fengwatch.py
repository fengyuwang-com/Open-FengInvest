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
    sell <ticker>       记录卖出、归档持仓、写日志
    history             历史持仓总览（胜率/盈亏/持有期）
    history losses      亏损交易分析（排行/原因/复盘记录）
    history import      导入历史交易（JSON格式）
    log [--limit N]     查看决策日志
    alert               显示当前提醒

Rules applied (from docs/08-exit.md):
    - 价格止损: 买入后跌>20% → 强制退出
    - 趋势反转: MA50<MA200+月跌>10% → 退50%
    - 论文失效: thesis_invalidation标志 → 立即清仓
    - 审核提醒: next_review_date到期
    - 钱仓滚存: 现价>成本时 可回收本金
"""

import json, os, re, sys, time
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

# Defer yfinance import — use fengdata.py (Futu primary) when possible
HOLDINGS_DIR = os.path.join(BASE, "holdings")
ALERTS_DIR = os.path.join(BASE, "alerts")
LOGS_DIR = os.path.join(BASE, "logs")
REVIEWS_DIR = os.path.join(BASE, "reviews")
JOURNAL_FILE = os.path.join(LOGS_DIR, "journal.jsonl")

os.makedirs(ALERTS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(REVIEWS_DIR, exist_ok=True)


# ─── Data Loading ────────────────────────────────────────────────

def load_holdings():
    """Load active hold_<TICKER>.json files (excludes closed/archived)."""
    holdings = []
    for f in sorted(os.listdir(HOLDINGS_DIR)):
        m = re.match(r"^hold_([A-Za-z0-9.]+)\.json$", f)
        if m:
            with open(os.path.join(HOLDINGS_DIR, f), encoding="utf-8") as fh:
                h = json.load(fh)
                h["_file"] = f
                holdings.append(h)
    return holdings


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
    """Fetch current price + MA data via fengdata.py (Futu primary, yfinance fallback).

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
    """Fetch key financial data via fengdata.py (Futu primary, yfinance fallback)."""
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(TOOLS, "fengdata.py"), ticker, "--mode", "financials", "--backend=auto"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            f = data.get("financials", {})
            if f and "error" not in f:
                return {
                    "trailing_pe": f.get("trailing_pe"),
                    "forward_pe": f.get("forward_pe"),
                    "roe_pct": f.get("roe_pct"),
                    "market_cap": f.get("market_cap"),
                    "fcf_annual": f.get("fcf_annual", []),
                    "revenue_annual": f.get("revenue_annual", []),
                    "fcf_latest_positive": None,
                    "mcap_fcf_ratio": None,
                }
    except Exception:
        pass
    return {}


# ─── Exit Rule Checks ────────────────────────────────────────────

def check_price_stop(h, price_data):
    """价格止损: 买入后跌>20% → 强制退出。"""
    avg_cost = h.get("position", {}).get("avg_cost", 0)
    if avg_cost <= 0:
        return None
    p = price_data.get("price", 0) if price_data else 0
    if p <= 0:
        return None
    drawdown = round((p - avg_cost) / avg_cost * 100, 1)
    if drawdown <= -20:
        return {"level": "RED", "signal": "EXIT", "label": f"价格止损触发: 现价{p:.2f}, 成本{avg_cost:.2f}, 回撤{drawdown:.1f}%", "value": drawdown}
    elif drawdown <= -15:
        return {"level": "YELLOW", "signal": "WARN", "label": f"接近止损: 回撤{drawdown:.1f}%（阈值-20%）", "value": drawdown}
    else:
        return {"level": "GREEN", "signal": "OK", "label": f"回撤{drawdown:.1f}%", "value": drawdown}


def check_trend_reversal(h, price_data):
    """趋势反转: MA50<MA200+月跌>10% → 退50%。"""
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
    """论文失效: thesis_invalidation标志。"""
    triggers = h.get("triggers", {})
    if triggers.get("thesis_invalidation", False):
        return {"level": "RED", "signal": "EXIT", "label": "论文已标记失效 → 立即清仓"}
    return {"level": "GREEN", "signal": "OK", "label": "论文有效"}


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
    """钱仓滚存: 现价>成本时可回收本金。"""
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

    if roll.get("phase") == "capital_recovered":
        return {"level": "GREEN", "signal": "DONE", "label": "本金已收回, 零成本持有中", "value": market_value}

    if p >= avg_cost:
        recoverable = avg_cost * shares
        sell_shares = int(recoverable / p)
        keep = shares - sell_shares
        return {"level": "YELLOW", "signal": "OPPORTUNITY", "label": f"可滚存: 卖{sell_shares}股回收{recoverable:.0f}, 留{keep}股零成本",
                "value": round(market_value - total_invested, 0)}
    return None


def check_fundamental_stop(h, fin_data):
    """基本面止损: FCF由正转负/营收连续降/ROE<10%。"""
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
    """估值泡沫: FCF/市值比率 >50x → 清仓。"""
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

    checks = {}
    checks["price_stop"] = check_price_stop(h, price_data)
    checks["trend"] = check_trend_reversal(h, price_data)
    checks["thesis"] = check_thesis_invalidation(h)
    checks["review_due"] = check_review_due(h)
    checks["price_trigger"] = check_price_triggers(h, price_data)
    checks["rollover"] = check_capital_rollover(h, price_data)
    checks["fundamental"] = check_fundamental_stop(h, fin_data)
    checks["valuation"] = check_valuation_bubble(h, fin_data)

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
        "name": h.get("thesis", {}).get("benchmark", ticker),
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
        "capital_phase": h.get("capital_rollover", {}).get("phase", "capital_at_risk"),
    }


# ─── Journal (Decision Log) ──────────────────────────────────────

def append_journal(entry):
    """Append an entry to the decision journal (JSONL format)."""
    entry["timestamp"] = entry.get("timestamp", datetime.now(timezone.utc).isoformat())
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

def cmd_daily(json_output=False):
    """一键每日分析: 检查所有持仓, 生成提醒, 写日志."""
    holdings = load_holdings()
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
        holdings_data = [(_holding_id(h), h) for h in load_holdings()]
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

    hold_period = 0
    buy_date = h.get("buy_date", "")
    if buy_date:
        try:
            hold_period = (date.today() - datetime.strptime(buy_date, "%Y-%m-%d").date()).days
        except ValueError:
            pass

    # Build closed record
    closed = dict(h)
    closed["status"] = "closed"
    closed["sell_info"] = {
        "sell_date": today_str,
        "sell_price": round(sell_price, 2),
        "shares_sold": sell_shares,
        "total_returned": round(total_returned, 0),
        "return_pct": return_pct,
        "hold_period_days": hold_period,
        "sell_reason": sell_reason,
    }

    # Archive: rename file
    old_path = os.path.join(HOLDINGS_DIR, f"hold_{ticker}.json")
    new_name = f"hold_{ticker}_closed_{today_str}.json"
    new_path = os.path.join(HOLDINGS_DIR, new_name)
    os.rename(old_path, new_path)
    with open(new_path, "w", encoding="utf-8") as f:
        json.dump(closed, f, indent=2, ensure_ascii=False)

    # Journal entry
    entry = {
        "type": "sell",
        "ticker": ticker,
        "date": today_str,
        "summary": f"卖出{ticker}: {sell_shares:.0f}股 @ {sell_price:.2f}, 盈亏{return_pct:+.1f}%, 持有{hold_period}天",
        "details": closed["sell_info"],
    }
    append_journal(entry)

    print(f"\n  ✅ 已记录卖出 {ticker}")
    print(f"     卖出: {sell_shares:.0f}股 @ {sell_price:.2f}")
    print(f"     盈亏: {return_pct:+.1f}%")
    print(f"     持有: {hold_period}天")
    print(f"     理由: {sell_reason or '未指定'}")
    print(f"     归档: {new_name}")
    print(f"     📝 日志已记录\n")
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
    active = load_holdings()
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
        print(f"     🟢 {h['ticker']}  成本{ac:.2f} → 现价{cp:.2f}  ({pct})")

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
        print(f"     {icon} {h['ticker']}  {s.get('sell_date', '?')}  盈亏{pct:+.1f}%  ({pnl:+.0f})  持有{days}天")
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

def main():
    if len(sys.argv) < 2:
        print("FengWatch — 持仓监控引擎")
        print()
        print("用法:")
        print("  fengwatch.py daily                 一键每日分析")
        print("  fengwatch.py check [TICKER]        检查退出条件")
        print("  fengwatch.py review <TICKER>       复盘持仓")
        print("  fengwatch.py sell <TICKER>         记录卖出并归档")
        print("  fengwatch.py history               历史持仓总览")
        print("  fengwatch.py history losses        亏损交易分析")
        print("  fengwatch.py history import <file> 导入历史交易")
        print("  fengwatch.py log [--limit N]       查看决策日志")
        print("  fengwatch.py alert                 显示当前提醒")
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
        "sell": lambda: cmd_sell(args),
        "history": lambda: cmd_history(args),
        "log": lambda: cmd_log(args),
        "alert": cmd_alert,
    }

    if cmd not in cmds:
        print(f"未知命令: {cmd}")
        print("可用: daily, check, review, sell, history, log, alert")
        sys.exit(1)

    sys.exit(cmds[cmd]())


if __name__ == "__main__":
    main()
