#!/usr/bin/env python3
"""fengmarketdata — Comprehensive market data for value investing dashboard.

2026-09-11 创始人指令: Futu OpenD 退出数据工作流。本工具改为免费公开源：
  - 指数行情: 腾讯 qt.gtimg.cn（hkHSI/hkHSTECH/hkHSCEI/sh000300）+ Yahoo chart HTTP（SPY/QQQ）
  - 其余节（估值分位/涨跌榜/广度/FedWatch/板块/IPO/日历）原依赖 Futu 独占 API，
    无替代免费源 → 返回 {'_error': ...} 明确说明，绝不编数。

Usage:
    python tools/fengmarketdata.py

Output sections:
    - indices:      Major index quotes（腾讯 + Yahoo）
    - valuation:    _error（已停用）
    - top_movers / breadth / fedwatch / sectors / ipos / economic_calendar: _error（已停用）
"""
import json, os, sys
from datetime import datetime

os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE, "tools"))

from fengdata import _yahoo_chart_http  # stdlib Yahoo chart fetcher（零 futu 依赖）

_RETIRED_NOTE = ("该节数据原由 Futu OpenD 提供，2026-09-11 已按创始人指令退出数据工作流，"
                 "暂无等效免费替代源，已停用（不编造数据）")

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Referer": "https://gu.qq.com/"}


def _sf(v):
    """Safe float."""
    if v is None:
        return None
    try:
        fv = float(v)
        import math
        if math.isnan(fv) or math.isinf(fv):
            return None
        return fv
    except (ValueError, TypeError):
        return None


def _tx_snapshot(codes, retries=3):
    """腾讯 qt.gtimg.cn 批量快照。返回 {code: dict}。参考 fengnames.py 写法：UA+Referer+重试。"""
    import time
    import urllib.request
    out = {}
    for attempt in range(retries):
        try:
            url = "https://qt.gtimg.cn/q=" + ",".join(codes)
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=12) as r:
                body = r.read().decode("gbk", "ignore")
            for seg in body.split(";"):
                seg = seg.strip()
                if '="' not in seg:
                    continue
                key = seg.split("=", 1)[0].replace("v_", "")
                fields = seg.split('="', 1)[1].split("~")
                if len(fields) > 32:
                    out[key] = fields
            if out:
                return out
        except Exception:
            if attempt < retries - 1:
                time.sleep(0.8 * (attempt + 1))
    return out


def _yahoo_index(code):
    """US 指数代理（SPY/QQQ）Yahoo chart 兜底（单次尝试，避免拖慢整页）。返回 dict 或 None。"""
    try:
        r = _yahoo_chart_http(code, range_str="5d", _tries=1)
        if not r.get("ok"):
            return None
        meta = r.get("meta") or {}
        price = (r.get("data") or {}).get("price") or meta.get("regularMarketPrice")
        prev = meta.get("chartPreviousClose") or meta.get("previousClose")
        if not price:
            return None
        return {
            "name": code, "code": code,
            "price": _sf(price),
            "change_pct": round((_sf(price) / _sf(prev) - 1) * 100, 2) if price and prev else None,
            "high": None, "low": None, "volume": None, "turnover": None,
            "pe": None, "pb": None,
            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source": "yahoo_chart_http (stdlib)",
        }
    except Exception:
        return None


# 指数代码（腾讯 qt.gtimg.cn）→ 显示名：港股/在岸指数/美股（usSPY/usQQQ 腾讯直供）
_TX_INDICES = [
    ("hkHSI", "恒生指数"),
    ("hkHSTECH", "恒生科技"),
    ("hkHSCEI", "国企指数"),
    ("sh000300", "沪深300"),
    ("usSPY", "S&P 500 (SPY)"),
    ("usQQQ", "Nasdaq 100"),
]
# Yahoo 兜底映射（腾讯缺某代码时）
_YAHOO_FALLBACK = {"usSPY": "SPY", "usQQQ": "QQQ"}


def fetch_indices():
    """Major index quotes: 腾讯 qt.gtimg.cn 一站式（港股/A股/美股），Yahoo 兜底。"""
    result = {}
    snaps = _tx_snapshot([c for c, _ in _TX_INDICES])
    for code, name in _TX_INDICES:
        f = snaps.get(code)
        if not f:
            fb = _YAHOO_FALLBACK.get(code)
            row = _yahoo_index(fb) if fb else None
            if row:
                row["name"] = name
                result[code] = row
            else:
                result[code] = {"name": name, "code": code, "_error": "腾讯/Yahoo 均无该代码快照"}
            continue
        price = _sf(f[3])
        prev = _sf(f[4])
        result[code] = {
            "name": name, "code": code,
            "price": price,
            "change_pct": _sf(f[32]) if len(f) > 32 and f[32] not in ("", "-") else
                          (round((price / prev - 1) * 100, 2) if price and prev else None),
            "high": _sf(f[33]) if len(f) > 33 else None,
            "low": _sf(f[34]) if len(f) > 34 else None,
            "volume": _sf(f[36]) if len(f) > 36 else None,
            "turnover": None,
            "pe": None, "pb": None,
            "update_time": f[30] if len(f) > 30 else "",
            "source": "tencent_qtgimg (stdlib)",
        }
    return result


def _retired_section():
    return {"_error": _RETIRED_NOTE}


def fetch_valuation():
    """Index PE/PB percentile — 原 Futu get_valuation_detail，已停用。"""
    return _retired_section()


def fetch_top_movers():
    return _retired_section()


def fetch_breadth():
    return _retired_section()


def fetch_fedwatch():
    return _retired_section()


def fetch_sectors():
    return _retired_section()


def fetch_ipos():
    return _retired_section()


def fetch_economic_calendar():
    return _retired_section()


def main():
    result = {
        'fetched_at': datetime.now().isoformat(),
        '_warnings': ['⚠️ Futu 已退出数据工作流（2026-09-11）：仅指数行情可用（腾讯+Yahoo），其余节停用',
                      '⚠️ S&P 500 使用 SPY ETF 作为代理'],
    }

    print("[*] Fetching indices (tencent + yahoo)...", file=sys.stderr)
    result['indices'] = fetch_indices()

    print("[*] valuation (retired)...", file=sys.stderr)
    result['valuation'] = fetch_valuation()

    result['top_movers'] = fetch_top_movers()
    result['breadth'] = fetch_breadth()
    result['fedwatch'] = fetch_fedwatch()
    result['sectors'] = fetch_sectors()
    result['ipos'] = fetch_ipos()
    result['economic_calendar'] = fetch_economic_calendar()

    # Clean None values
    result = {k: v for k, v in result.items() if v}

    print(json.dumps(result, indent=2, default=str, ensure_ascii=False))


if __name__ == "__main__":
    main()
