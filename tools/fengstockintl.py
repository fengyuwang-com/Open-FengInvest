#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fengstockintl.py — 非中港台市场日线补齐适配器（研发版，2026-08-24）

背景：yfinance 因 Yahoo 全域 403 已死，indices/daily_data 中非中港台市场的日线
停在 2026-07-21。本工具提供三个子命令：
    probe  --market US --sample 5     抽样实测各源覆盖率，输出 JSON 矩阵
    fetch   <TICKER> [--market XX]    单只取数打印 JSON（含 source_used/rows/首末日期）
    fill   --market XX [--dry-run]    批量补齐（本轮只留代码路径，默认 dry-run 且需环境变量二次确认）

数据源与 2026-08-24 实测结论：
    yfinance   ★主源★。当日复活实测：16 个非中港台市场的成分股抽样全通
               （US/JP/KR/IN/AU/CA/UK/DE/FR/IT/ES/SE/NL/CH/SG/NZ），17 个全球指数
               全通（^GSPC/^N225/^KS11/^KQ11/^AXJO/^STI/^KLSE/^JKSE/^FTSE/^GDAXI/
               ^FCHI/^STOXX50E/^BSESN/^NSEI/^DJI/^IXIC/^RUT）。ticker 即库内 Yahoo 式
               原样（英国裸代码补 .L）。
    tencent    腾讯 ifzq 日K（美股历史 OK；日/韩只有最新一根，仅兜底）
    eastmoney  东财 push2his 日K + searchapi suggest 解析 secid（美/英/日/韩/全球指数）
    naver      韩国 fchart 日K（股票 + KOSPI/KOSDAQ 指数，单次上限 3000 根 ≈ 12 年）
    stooq      ★判死★（2026-08-24 双任务实测：JS PoW 质询 + CSV 端点 Access denied，
               curl_cffi 也绕不过）。PoW 解算器保留在本文件 _StooqSession，端点解锁即可用。

═══════════════ 符号映射规则（全部 2026-08-24 实测） ═══════════════

【腾讯 web.ifzq.gtimg.cn/appstock/app/fqkline/get】
  URL: ?param={code},day,{YYYYMMDD起},{YYYYMMDD止},320,qfq
  美股: us{BASE}.OQ = 纳斯达克；us{BASE}.N  = NYSE/AMEX/Arca（实测 usSPY.N 返回真实代码
        "SPY.AM" 即 NYSE Arca）；us{BASE}.UQ = NYSE 部分（实测 BABA/KO 用 .UQ 反而空，
        用 .N 全量返回 → 规则：按 [.OQ, .N, .UQ] 顺序尝试，取 rows>1 的第一个）。
        ★ 关键坑：错后缀不报错，服务端回退成"仅最新一根"（rows==1），必须以 >1 判成功。
  日股: jp{4位代码}（jp7203 ✓）；韩股: kr{6位代码}（kr005930 ✓）——但无论怎么传日期/
        count 都只返回最新一根 K 线，不能用于补历史，仅作"最新价兜底"。
  K线数组字段序: [date, open, close, high, low, volume] —— ★close 在 high 前面★。
  复权: qfq=前复权；param 尾段留空则返回未复权 day 数组（fill 时取 unadj_close 用）。

【东财 push2his.eastmoney.com/api/qt/stock/kline/get】
  secid = {MktNum}.{Code}；MktNum 实测: 105/106/107=美股(纳斯达克/纽交所/美交所)、
  100=全球指数、116=港股、155=英股LSE、153=粉单ADR、176=日股、177=韩股。
  secid 解析用 searchapi.eastmoney.com/api/suggest/get?input={基础代码}&type=14&count=20
  （token D43BF722C8E33BDC906FB84D85E326E8 为网页公开 token）。
  ★ suggest 必须查基础代码（查 "AZN.L" 为空，查 "AZN" 才能同时给出美股/LSE 两行）。
  美股裸代码按 SecurityTypeName=美股 且 MktNum∈{105,106,107} 精确匹配 Code；
  英国裸代码按 MktNum=155 精确匹配 Code（如 AZN→155.AZN 阿斯利康(UK)）。
  klines 字段串: f51..f57 = date,open,close,high,low,volume,amount —— ★同样是 close 在前★。
  LSE 价格单位为 GBX（便士），如 AZN≈11926 = 119.26 英镑，入库时要注意单位。
  指数映射（实测 2026-08-24 可取到日K）: ^GSPC→100.SPX、^DJI→100.DJI、^IXIC→100.IXIC、
  ^N225→100.N225、^KS11→100.KS11、^FTSE→100.FTSE、^GDAXI→100.GDAXI、^FCHI→100.FCHI、
  ^BSESN→100.SENSEX、^NSEI→100.NIFTY 等，候选表见 INDEX_EM_CANDIDATES。
  覆盖边界（suggest 多轮实测均无本土上市，只有 ADR）：DE/FR/IT/ES/SE/NL/CH/AU/CA/
  IN/SG/NZ 十二个市场在东财无本土行情 → 如实标"无源"（参考 KWEB/LVHI 先例）。
  ★ 限流行为：连发约 20+ 个请求后 push2his 开始 RemoteDisconnected（连接直接掐断，
  urllib/requests/curl 一视同仁），冷却数十秒恢复。对策：全局节流 ≥1s/请求 + 断连退避 +
  镜像子域轮换（63./21.push2his.eastmoney.com）+ curl 子进程兜底传输。

【韩国 naver fchart.stock.naver.com/sise.nhn】
  ?symbol={6位代码|KOSPI|KOSDAQ}&timeframe=day&count=3000&requestType=0
  返回 EUC-KR XML，行格式 data="date|open|high|low|close|volume"。
  单次最多约 3000 根（2014-05 起 ≈12 年）；指数用 symbol=KOSPI/^KS11→KOSPI、^KQ11→KOSDAQ。
  复权状态：naver 官方未声明 → 一律标 unverified，只作趋势判据，不当复权价/绝对价基准。
  实测（2026-09-16）：序列跨 2018-05-04 三星 50:1 拆股处连续（005930 于 2014-06-27 收 26,220、
  2018-04-27 收 53,000，无 50 倍断崖）→ 至少含拆股复权；但与东财 KR 在个别票/时段仍有恒定
  倍数差（247540.KQ 2026-09-02 及更早为 naver/东财 ≈0.9843），故口径仍判未定，由对拍暴露。

【韩国 naver 移动端 m.stock.naver.com（2026-09-16 新增，KR 财务/同业唯一活源）】
  /api/stock/{6位代码}/integration    报价 + 估值（per/cnsPer/pbr/bps/eps/
       dividendYieldRatio/marketValue/52周高低）+ industryCode + industryCompareInfo
       （★同行业公司名单，含 itemCode/stockName —— fengquant KR 同行组的唯一来源）
  /api/stock/{6位代码}/finance/annual 年报科目（매출액/영업이익/당기순이익/영업이익률/
       순이익률/ROE/부채비율/당좌비율/유보율/EPS/PER/BPS/PBR/주당배당금）
  ★ 口径铁律：trTitleList 里 isConsensus="Y" 的年份是【券商一致预期】，不是已披露业绩；
    naver_finance_annual 默认剔除预期列，实际业绩与预期不得混用（防前视）。
  ★ 金额单位 억원(1e8 KRW)；市值字符串形如 "1,256조 4,469억"（_naver_krw 解析）。
  ★ totalInfos.lastClosePrice 是"전일"(前收)，不是实时价 —— 实时价仍走 fchart 日K。

【stooq q/d/l CSV】
  质询机制：首次请求返回 796 字节 HTML，内含 SHA-256 工作量证明（找 n 使 sha256(c+n)
  前 d=4 位为 0），POST /__verify(c,n) 后种 auth cookie 并 reload。PoW 本身可程序化解出
  （本工具 _StooqSession 已实现，单次 ~1 秒），且 HTML 行情页能正常打开，但批量 CSV
  端点 /q/d/l/ 在持有完整 cookie 会话时仍返回 "Access denied"（端点级封锁）。
  → 2026-08-24 判定：无源。若未来换 IP/UA 解锁，_StooqSession.get_csv 可直接使用。
  符号体系（官方文档口径，未能实测验证）: 美股 {base}.us、英国 .uk、德国 .de、
  日本 .jp、香港 .hk、指数 ^spx/^nkx 等。

【各市场推荐源（2026-08-24 实测）】
  全部 16 市场 + 全部指数: yfinance 主源（成分股/指数抽样全通，与库内 ticker 同体系）。
    备源: US→tencent(.OQ/.N/.UQ)；JP/KR/UK/指数→eastmoney；KR→naver(深历史)。
  口径铁证（AAPL 2026-01-02 对拍）: 库内 unadj_close=裸 Close 分毫不差，
    close=前复权(下载日锚定)。灌库正解 = yfinance auto_adjust=False 一把取回，
    close 写 'Adj Close' 列、unadj_close 写裸 Close——与库内语义完全一致。
  ★ fengstockdb.download_yf 未显式传 auto_adjust（yfinance 0.2.51 起默认 True），
    复用其 update 路径前先小样对拍两列口径。

═══════════════ fill 设计说明（本轮绝不执行） ═══════════════

  首选：直接复用现成管道 `python tools/fengstockdb.py update <us|jp|kr|uk|...>`
  （维基成分刷新 → seed_and_map → 并发 download_yf → 单批 safe_batch + update_log）。
  本工具 fill 仅作兜底路径。四重保险：dry-run 默认开 + FENG_INTL_FILL_CONFIRM=YES
  二次确认 + fengdb/safe_batch 仅在本函数 import + 每市场独立 changeset 可 undo。
  写入行: INSERT OR REPLACE INTO daily_data
          (index_id,date,open,high,low,close,volume,unadj_close)，
  close=复权收盘('Adj Close')、unadj_close=裸收盘；naver/tencent 单一口径源
  unadj_close=close 并在 label 注明。
"""
from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import os
import random
import re
import sqlite3
import subprocess
import sys
import time
import urllib.parse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, "data", "market_data.db")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

TARGET_MARKETS = ["US", "JP", "KR", "IN", "AU", "CA", "UK", "DE", "FR",
                  "IT", "ES", "SE", "NL", "CH", "SG", "NZ", "AP", "EU"]

# ── 每市场源计划（顺序即优先级；probe/fetch 命中 hist_ok 即短路）────────────
_Y = "yfinance"
SOURCE_PLAN = {
    "US": [_Y, "tencent"],
    "JP": [_Y, "eastmoney", "tencent"],
    "KR": [_Y, "naver", "eastmoney"],
    "UK": [_Y, "eastmoney"],
    "IN": [_Y, "eastmoney"], "AU": [_Y, "eastmoney"], "CA": [_Y, "eastmoney"],
    "DE": [_Y, "eastmoney"], "FR": [_Y, "eastmoney"], "IT": [_Y, "eastmoney"],
    "ES": [_Y, "eastmoney"], "SE": [_Y, "eastmoney"], "NL": [_Y, "eastmoney"],
    "CH": [_Y, "eastmoney"], "SG": [_Y, "eastmoney"], "NZ": [_Y, "eastmoney"],
    "AP": [_Y], "EU": [_Y],
}
INDEX_SOURCES = {
    "^KS11": [_Y, "naver", "eastmoney"], "^KQ11": [_Y, "naver", "eastmoney"],
}  # 其余指数默认 [_Y, "eastmoney"]

# 东财全球指数候选码（按序试 kline，取到即用）
INDEX_EM_CANDIDATES = {
    "^GSPC": ["SPX"], "^DJI": ["DJI"], "^IXIC": ["IXIC"], "^RUT": ["RUT"],
    "^N225": ["N225"], "^KS11": ["KS11"], "^KQ11": ["KOSDAQ"],
    "^FTSE": ["FTSE"], "^GDAXI": ["GDAXI"], "^FCHI": ["FCHI"], "^STOXX50E": ["STOXX50E"],
    "^AXJO": ["ASX"], "^STI": ["STI"], "^KLSE": ["KLSE"], "^JKSE": ["JKSE"],
    "^BSESN": ["SENSEX"], "^NSEI": ["NIFTY"],
}

# ── 传输层：requests 优先，断连退避 + curl 子进程兜底 ──────────────────────
_MIN_INTERVAL = {"push2his.eastmoney.com": 1.05, "searchapi.eastmoney.com": 0.45,
                 "web.ifzq.gtimg.cn": 0.25, "fchart.stock.naver.com": 0.35,
                 "m.stock.naver.com": 0.35, "push2delay.eastmoney.com": 1.05,
                 "stooq.com": 0.9, "default": 0.2}
_last_hit: dict[str, float] = {}
try:
    import requests as _rq
except ImportError:
    _rq = None


def _pace(host: str):
    iv = _MIN_INTERVAL.get(host, _MIN_INTERVAL["default"])
    wait = _last_hit.get(host, 0.0) + iv - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.time()


def _curl_get(url: str, timeout: int = 25) -> bytes:
    p = subprocess.run(["curl", "-sS", "-m", str(timeout), "-A", UA, "--compressed", url],
                       capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f"curl exit {p.returncode}: {p.stderr.decode('utf-8', 'replace')[:120]}")
    return p.stdout


def http_get(url: str, *, params: dict | None = None, timeout: int = 25,
             retries: int = 2) -> bytes:
    """GET：requests → 退避重试 → curl 子进程。返回原始 bytes。"""
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    host = urllib.parse.urlsplit(url).netloc
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        _pace(host)
        try:
            if _rq is not None:
                r = _rq.get(url, headers={"User-Agent": UA}, timeout=timeout)
                r.raise_for_status()
                return r.content
            raise RuntimeError("requests not installed")
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(4.0 * (attempt + 1))  # 退避 4s/8s
    # curl 兜底（不同 TLS/HTTP 栈指纹，实测可绕开 push2his 对 python 栈的掐断）
    for attempt in range(retries + 1):
        _pace("curl." + host)
        try:
            return _curl_get(url, timeout=timeout)
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(3.0 * (attempt + 1))
    raise RuntimeError(f"HTTP GET failed after retries: {url} :: {type(last_err).__name__}: "
                       f"{str(last_err)[:160]}")


def get_json(url: str, **kw) -> dict:
    raw = http_get(url, **kw)
    return json.loads(raw.decode("utf-8", "replace"))


# ── 源 0：yfinance（2026-08-24 复活实测：16 市场成分股 + 17 指数全通）────────
_YF_SESSION = None


def _get_yf_session():
    """轮换 UA 的 requests 会话（yfinance 接受 session 参数，防限流）。"""
    global _YF_SESSION
    if _YF_SESSION is None:
        uas = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15",
        ]
        _YF_SESSION = _rq.Session()
        _YF_SESSION.headers["User-Agent"] = random.choice(uas)
    return _YF_SESSION


def yahoo_symbol(market: str, ticker: str) -> str:
    """库内 Yahoo 式 ticker → yfinance 符号。英国裸代码补 .L，其余原样直用。"""
    t = ticker.strip()
    if t.startswith("^") or "." in t:
        return t
    if market == "UK":
        return f"{t}.L"
    return t


def yfinance_fetch(ticker: str, market: str, start: str, end: str) -> dict:
    """yfinance 日K。auto_adjust=False：Close=裸价、Adj Close=前复权。
    返回行含 unadj_close（裸收盘），与库内口径铁证一一对应。"""
    import yfinance as yf
    res = {"ok": False, "hist_ok": False, "source": "yfinance", "symbol_used": None,
           "rows": 0, "first_date": None, "last_date": None,
           "adjusted": "close=Adj Close(复权), unadj_close=裸Close", "note": "", "data": []}
    sym = yahoo_symbol(market, ticker)
    res["symbol_used"] = sym
    time.sleep(random.uniform(0.5, 1.0))  # 限速礼貌间隔（Yahoo 429 阈值紧，实测 KR 批被限）
    try:
        df = yf.Ticker(sym, session=_get_yf_session()).history(
            start=_dashed(start), end=_dashed(end), auto_adjust=False)
    except Exception as e:  # noqa: BLE001
        res["note"] = f"yf_fail:{type(e).__name__}:{str(e)[:80]}"
        return res
    if df is None or len(df) == 0:
        res["note"] = "no_data"
        return res
    has_adj = "Adj Close" in df.columns
    rows = []
    for dt_idx, r in df.iterrows():
        d = dt_idx.strftime("%Y-%m-%d") if hasattr(dt_idx, "strftime") else str(dt_idx)[:10]
        try:
            raw_c = float(r["Close"])
            rows.append({"date": d,
                         "open": float(r["Open"]), "high": float(r["High"]),
                         "low": float(r["Low"]),
                         "close": float(r["Adj Close"]) if has_adj else raw_c,
                         "unadj_close": raw_c,
                         "volume": float(r["Volume"])})
        except (ValueError, TypeError, KeyError):
            continue
    res.update(ok=bool(rows), hist_ok=len(rows) > 0, rows=len(rows),
               first_date=rows[0]["date"] if rows else None,
               last_date=rows[-1]["date"] if rows else None, data=rows)
    return res


# ── 源 1：腾讯 ifzq ────────────────────────────────────────────────────────
TX_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"


def _dashed(d: str) -> str:
    """YYYYMMDD → YYYY-MM-DD（腾讯 ifzq 只认横线日期，紧凑格式返回空）。"""
    if "-" in d:
        return d
    return f"{d[:4]}-{d[4:6]}-{d[6:]}"


def _tx_code_candidates(market: str, base: str) -> list[str]:
    b = base.upper()
    variants = [b]
    if "-" in b:
        variants += [b.replace("-", "_"), b.replace("-", ""), b.replace("-", ".")]
    elif "." in b:
        variants += [b.replace(".", "-"), b.replace(".", ""), b.replace(".", "_")]
    if market == "US":
        codes = []
        for v in variants:
            codes += [f"us{v}.OQ", f"us{v}.N", f"us{v}.UQ"]
        return codes
    if market == "JP":
        return [f"jp{variants[0]}"]
    if market == "KR":
        return [f"kr{variants[0].zfill(6)}"]
    return []


def tencent_fetch(market: str, base: str, start: str, end: str, adj: bool = True) -> dict:
    """腾讯日K。adj=True 取 qfq 前复权，False 取未复权。rows<=1 视为'仅报价兜底'。"""
    res = {"ok": False, "hist_ok": False, "source": "tencent", "symbol_used": None,
           "rows": 0, "first_date": None, "last_date": None,
           "adjusted": "qfq" if adj else "raw", "note": "", "data": []}
    tail = "qfq" if adj else ""
    d1, d2 = _dashed(start), _dashed(end)
    for code in _tx_code_candidates(market, base):
        url = f"{TX_URL}?param={code},day,{d1},{d2},320,{tail}"
        try:
            j = get_json(url)
        except Exception as e:  # noqa: BLE001
            res["note"] = f"http_fail:{type(e).__name__}"
            continue
        node = (j.get("data") or {}).get(code) or {}
        arr = node.get("qfqday") or node.get("day") or []
        rows = []
        for it in arr:
            try:  # 字段序 [date, open, close, high, low, volume]
                rows.append({"date": it[0], "open": float(it[1]), "close": float(it[2]),
                             "high": float(it[3]), "low": float(it[4]),
                             "volume": float(it[5])})
            except (ValueError, IndexError):
                continue
        res.update(symbol_used=code, rows=len(rows))
        if len(rows) > 1:
            res.update(ok=True, hist_ok=True,
                       first_date=rows[0]["date"], last_date=rows[-1]["date"], data=rows)
            return res
        if len(rows) == 1:  # 错后缀回退的"最新一根"，记住但继续试别的后缀
            res["ok"] = True
            res["note"] = "quote_only_fallback"
            res["data"] = rows
    if not res["hist_ok"] and res["rows"] == 0:
        res["note"] = res["note"] or "no_data"
    return res


# ── 源 2：东财（suggest 解析 + kline）─────────────────────────────────────
EM_KLINE_HOSTS = ["push2his.eastmoney.com", "63.push2his.eastmoney.com",
                  "21.push2his.eastmoney.com"]
EM_SUGGEST = ("https://searchapi.eastmoney.com/api/suggest/get?type=14"
              "&token=D43BF722C8E33BDC906FB84D85E326E8&count=20&input=")
_SECID_CACHE: dict[str, str | None] = {}

EM_MKT_HINTS = {"US": {"105", "106", "107"}, "UK": {"155"}, "JP": {"176"}, "KR": {"177"}}


_JSONP_RE = re.compile(r"^[^(]*\((.*)\)\s*;?\s*$", re.S)


def _urllib_get_json(url: str, timeout: int = 15) -> dict:
    """searchapi 专用：urllib 直连返回纯 JSON；requests 栈会被回成 JSONP。"""
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def em_suggest(query: str) -> list[dict]:
    url = EM_SUGGEST + urllib.parse.quote(query)
    try:
        j = _urllib_get_json(url)
        return (j.get("QuotationCodeTable") or {}).get("Data") or []
    except Exception:  # noqa: BLE001 — urllib 被掐时退回通用传输 + JSONP 剥壳
        pass
    raw = http_get(url).decode("utf-8", "replace").strip()
    try:
        j = json.loads(raw)
    except json.JSONDecodeError:
        m = _JSONP_RE.match(raw)
        if not m:
            return []
        j = json.loads(m.group(1))
    table = j.get("QuotationCodeTable") or ((j.get("result") or {}).get("QuotationCodeTable"))
    return (table or {}).get("Data") or []


def em_resolve_secid(market: str, base: str) -> str | None:
    """把 Yahoo 式 ticker 解析成东财 secid。解析不了返回 None（如实无源）。"""
    key = f"{market}:{base}"
    if key in _SECID_CACHE:
        return _SECID_CACHE[key]
    secid = None
    hint_mkts = EM_MKT_HINTS.get(market)
    try:
        items = em_suggest(base)
    except Exception:  # noqa: BLE001
        items = []
    cands = []
    for it in items:
        mkt, code = str(it.get("MktNum")), str(it.get("Code"))
        cands.append((mkt, code))
        if hint_mkts and mkt in hint_mkts and code.upper() == base.upper():
            secid = f"{mkt}.{code}"
            break
    if secid is None:  # 精确码没对上，退而取该市场组第一项（如日股数字码模糊命中）
        if hint_mkts:
            for mkt, code in cands:
                if mkt in hint_mkts:
                    secid = f"{mkt}.{code}"
                    break
    _SECID_CACHE[key] = secid
    return secid


def em_kline(secid: str, start: str, end: str, fqt: int = 1) -> dict:
    """东财日K。fqt: 0=不复权 1=前复权。字段序 date,open,close,high,low,volume,amount。"""
    res = {"ok": False, "hist_ok": False, "source": "eastmoney", "symbol_used": secid,
           "rows": 0, "first_date": None, "last_date": None,
           "adjusted": "fqt1" if fqt else "raw", "note": "", "data": []}
    params = ("fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57"
              "&klt=101&beg={beg}&end={end}&fqt={fqt}&secid={sid}")
    path = "/api/qt/stock/kline/get?" + params.format(beg=start, end=end, fqt=fqt, sid=secid)
    body = None
    for host in EM_KLINE_HOSTS:
        try:
            body = get_json(f"https://{host}{path}")
            break
        except Exception:  # noqa: BLE001
            continue
    if body is None:
        res["note"] = "all_hosts_failed"
        return res
    d = body.get("data")
    if not d:
        res["note"] = "no_data"
        return res
    rows = []
    for line in d.get("klines") or []:
        p = line.split(",")
        try:
            rows.append({"date": p[0], "open": float(p[1]), "close": float(p[2]),
                         "high": float(p[3]), "low": float(p[4]), "volume": float(p[5])})
        except (ValueError, IndexError):
            continue
    res.update(ok=True, rows=len(rows),
               first_date=rows[0]["date"] if rows else None,
               last_date=rows[-1]["date"] if rows else None,
               hist_ok=len(rows) > 1, data=rows,
               note=str(d.get("name") or ""))
    return res


def eastmoney_fetch(market: str, ticker: str, base: str, start: str, end: str) -> dict:
    if ticker.startswith("^"):
        last_err = ""
        for code in INDEX_EM_CANDIDATES.get(ticker, []):
            r = em_kline(f"100.{code}", start, end)
            if r["hist_ok"]:
                return r
            last_err = r["note"]
        return {"ok": False, "hist_ok": False, "source": "eastmoney", "symbol_used": None,
                "rows": 0, "first_date": None, "last_date": None, "adjusted": "n/a",
                "note": last_err or "index_not_found", "data": []}
    secid = em_resolve_secid(market, base)
    if not secid:
        return {"ok": False, "hist_ok": False, "source": "eastmoney", "symbol_used": None,
                "rows": 0, "first_date": None, "last_date": None, "adjusted": "n/a",
                "note": "secid_not_found(无此市场本土上市)", "data": []}
    return em_kline(secid, start, end)


# ── 源 3：韩国 naver fchart ───────────────────────────────────────────────
# ★ 复权口径铁律（2026-09-16 实测，不许猜）：naver 官方未声明 sise.nhn 的复权口径，
#   故一律标 unverified，**只当趋势/均线/区间收益的价格序列用，不得当复权价或绝对价基准**。
#   实测证据：东财 KR 的 fqt=0(不复权) 与 fqt=1(前复权) 返回值完全一致（KR 无复权因子），
#   以东财 fqt 为"原始价"参照，247540.KQ 上 naver 与东财在 2026-09-03 起逐根相等，而
#   2026-09-02 及更早为恒定 0.9843 倍（≈ 1/1.016）—— 形态符合 naver 侧按某除权日回乘了
#   一个 ~1.6% 的复权因子；000660.KS/005930.KS 近 20 根则两源在 ±1% 内一致。
#   结论：差异真实存在且随个股/时点变化 → 必须由 fengdata 的 _kr_cross_check 逐票对拍暴露。
NAVER_URL = "https://fchart.stock.naver.com/sise.nhn"
NAVER_INDEX_SYMBOL = {"^KS11": "KOSPI", "^KQ11": "KOSDAQ"}
_ITEM_RE = re.compile(r'data="(\d{8})\|([^"]*)"')


def naver_fetch(market: str, base: str, count: int = 3000) -> dict:
    res = {"ok": False, "hist_ok": False, "source": "naver", "symbol_used": None,
           "rows": 0, "first_date": None, "last_date": None,
           "adjusted": "unverified(naver未声明；实测含拆股复权)", "note": "", "data": []}
    sym = NAVER_INDEX_SYMBOL.get(base, base.zfill(6) if market == "KR" else base)
    try:
        raw = http_get(NAVER_URL, params={"symbol": sym, "timeframe": "day",
                                          "count": str(count), "requestType": "0"})
    except Exception as e:  # noqa: BLE001
        res["note"] = f"http_fail:{type(e).__name__}"
        return res
    body = raw.decode("euc-kr", "replace")
    pairs = _ITEM_RE.findall(body)
    rows = []
    for d8, rest in pairs:
        p = rest.split("|")
        if len(p) < 5:
            continue
        try:  # 字段序 date|open|high|low|close|volume
            rows.append({"date": f"{d8[:4]}-{d8[4:6]}-{d8[6:]}",
                         "open": float(p[0]), "high": float(p[1]), "low": float(p[2]),
                         "close": float(p[3]), "volume": float(p[4])})
        except ValueError:
            continue
    res.update(symbol_used=sym, rows=len(rows),
               ok=bool(rows), hist_ok=len(rows) > 1,
               first_date=rows[0]["date"] if rows else None,
               last_date=rows[-1]["date"] if rows else None, data=rows)
    if not rows:
        res["note"] = "no_data"
    return res


# ── 源 3b：韩国 naver 移动端财务/报价（2026-09-16 新增，见文件头口径说明）────
NAVER_M_BASE = "https://m.stock.naver.com/api/stock"


def naver_m_json(code: str, path: str) -> dict:
    """naver 移动端 JSON（EUC-KR 无关，接口回 UTF-8）。失败上抛，调用方决定降级。"""
    return json.loads(http_get(f"{NAVER_M_BASE}/{code}/{path}").decode("utf-8", "replace"))


def _naver_num(v):
    """'7.67배' / '370,432원' / '0.17%' / '-77,303' → float；'-'/'N/A'/空 → None。"""
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "--", "N/A", "nan"):
        return None
    m = re.match(r"^[+-]?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


def _naver_krw(v):
    """naver 韩元金额：'1,256조 4,469억' → 1.256e15+4.469e11；无单位按原数解析。"""
    if not v:
        return None
    t = str(v).replace(",", "").replace(" ", "")
    total, found = 0.0, False
    for unit, mult in (("조", 1e12), ("억", 1e8), ("만", 1e4)):
        m = re.search(r"([\d.]+)" + unit, t)
        if m:
            total += float(m.group(1)) * mult
            found = True
    return total if found else _naver_num(t)


def naver_quote(code: str) -> dict:
    """naver integration：名称/估值/同行业公司名单。拿不到 → ok=False（不编数）。

    返回键 per/cns_per 为 PER(实际 TTM) / 추정PER(券商预期)；price 一栏不取自此处
    （lastClosePrice 是前收），实时价走 naver_fetch 日K。
    """
    res = {"ok": False, "source": "naver_m_integration", "code": code, "note": "",
           "peers": [], "peers_source": None}
    try:
        j = naver_m_json(code, "integration")
    except Exception as e:  # noqa: BLE001
        res["note"] = f"http_fail:{type(e).__name__}"
        return res
    ti = {t.get("code"): t.get("value") for t in (j.get("totalInfos") or [])}
    peers = []
    for p in (j.get("industryCompareInfo") or []):
        if not p.get("itemCode"):
            continue
        sosok = str(p.get("sosok") or "")
        # sosok: naver 市场码 '0'=KOSPI(' .KS') / '1'=KOSDAQ('.KQ')；未识别 → suffix=None（不猜）
        peers.append({"code": str(p.get("itemCode")), "name": p.get("stockName"),
                      "sosok": sosok,
                      "suffix": {"0": "KS", "1": "KQ"}.get(sosok),
                      "market_cap_100m_krw": _naver_num(p.get("marketValue"))})
    res.update(
        ok=bool(ti), name_kr=j.get("stockName"), industry_code=j.get("industryCode"),
        prev_close=_naver_num(ti.get("lastClosePrice")),
        per=_naver_num(ti.get("per")), cns_per=_naver_num(ti.get("cnsPer")),
        pbr=_naver_num(ti.get("pbr")), bps=_naver_num(ti.get("bps")),
        eps=_naver_num(ti.get("eps")), cns_eps=_naver_num(ti.get("cnsEps")),
        dps=_naver_num(ti.get("dividend")),
        dividend_yield_pct=_naver_num(ti.get("dividendYieldRatio")),
        market_cap_krw=_naver_krw(ti.get("marketValue")),
        high_52w=_naver_num(ti.get("highPriceOf52Weeks")),
        low_52w=_naver_num(ti.get("lowPriceOf52Weeks")),
        peers=peers,
        peers_source="naver industryCompareInfo(同行业对照)" if peers else None,
        valuation_note="per/pbr/dividend_yield_pct 为 naver integration 原值(TTM口径，未经第三方对拍)",
    )
    if not ti:
        res["note"] = "no_data"
    return res


# naver 年报科目中文映射（只映射本框架消费的科目，其余原样保留韩文键）
NAVER_ROW_MAP = {
    "매출액": "revenue", "영업이익": "operating_income", "당기순이익": "net_income",
    "영업이익률": "operating_margin_pct", "순이익률": "net_margin_pct", "ROE": "roe_pct",
    "부채비율": "debt_ratio_pct", "당좌비율": "quick_ratio_pct", "유보율": "retained_ratio_pct",
    "EPS": "eps", "PER": "per", "BPS": "bps", "PBR": "pbr", "주당배당금": "dps",
}


def naver_finance_annual(code: str, include_consensus: bool = False) -> dict:
    """naver 年报科目。默认剔除 isConsensus='Y' 的预期年份（实际业绩 ≠ 券商预期）。

    返回 {"ok","source","years","consensus_years","rows","unit_note","note"}；
    rows = {英文科目名: {年key: float}}，year key 形如 "202512"（期末年月）。
    """
    res = {"ok": False, "source": "naver_m_finance_annual", "code": code,
           "years": [], "consensus_years": [], "rows": {}, "note": "",
           "unit_note": "金额单位 억원(1e8 KRW)；比率类科目为百分数原值"}
    try:
        j = naver_m_json(code, "finance/annual")
    except Exception as e:  # noqa: BLE001
        res["note"] = f"http_fail:{type(e).__name__}"
        return res
    fi = j.get("financeInfo") or {}
    titles = fi.get("trTitleList") or []
    actual = [t["key"] for t in titles if t.get("key") and str(t.get("isConsensus")) != "Y"]
    consensus = [t["key"] for t in titles if t.get("key") and str(t.get("isConsensus")) == "Y"]
    keep = actual + (consensus if include_consensus else [])
    rows = {}
    for r in fi.get("rowList") or []:
        title = str(r.get("title") or "").strip()
        if not title:
            continue
        vals = {}
        for y, cell in (r.get("columns") or {}).items():
            if y not in keep:
                continue
            v = _naver_num((cell or {}).get("value"))
            if v is not None:
                vals[y] = v
        if vals:
            rows[NAVER_ROW_MAP.get(title, title)] = vals
    res.update(ok=bool(rows), years=sorted(actual), consensus_years=sorted(consensus), rows=rows)
    if not rows:
        res["note"] = "no_data"
    return res


# ── 源 2b：东财 push2delay（延时行情；push2 主域对 python/curl 栈直接掐断）────
EM_DELAY_HOST = "push2delay.eastmoney.com"


def em_quote_delay(secid: str, fields: str = "f43,f58,f84,f92,f116,f164,f167,f173") -> dict:
    """东财延时报价/估值（push2delay 域实测可通，push2 主域 RemoteDisconnected）。
    f43价/f58名/f84总股本/f92每股净资产/f116总市值/f164市盈率/f167市净率/f173净资产收益率。
    仅作 KR 估值对拍用；'-' 表示该市场无此科目 → None（不编数）。"""
    res = {"ok": False, "source": "eastmoney_delay", "secid": secid, "note": "", "fields": {}}
    url = f"https://{EM_DELAY_HOST}/api/qt/stock/get?secid={secid}&fltt=2&invt=2&fields={fields}"
    try:
        body = get_json(url)
    except Exception as e:  # noqa: BLE001
        res["note"] = f"http_fail:{type(e).__name__}"
        return res
    d = body.get("data") or {}
    if not d:
        res["note"] = "no_data"
        return res
    names = {"f43": "price", "f58": "name", "f84": "shares", "f92": "bps",
             "f116": "market_cap", "f164": "pe", "f167": "pb", "f173": "roe_pct"}
    out = {}
    for k, v in d.items():
        key = names.get(k, k)
        if isinstance(v, str) and v.strip() in ("", "-", "--"):
            out[key] = None if key != "name" else v  # '-' = 该市场无此科目；名称允许原样
        elif key == "name":
            out[key] = v
        else:
            out[key] = _naver_num(v)
    res.update(ok=True, fields=out, note="延时行情(push2delay)口径，仅作对拍")
    return res


# ── 源 4：stooq（PoW 会话；CSV 端点 2026-08-24 仍 Access denied）───────────
class _StooqSession:
    """stooq JS 工作量证明会话：解 sha256(c+n) 前导零 → POST /__verify → 带 cookie 取数。"""

    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))
        self.solved = False

    def _pow(self, challenge: str, difficulty: int) -> int:
        target = "0" * difficulty
        n = 0
        while not hashlib.sha256((challenge + str(n)).encode()).hexdigest().startswith(target):
            n += 1
        return n

    def get(self, url: str) -> tuple[str, bool]:
        """返回 (body, challenged)。challenged=True 表示又遇到质询页。"""
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with self.opener.open(req, timeout=20) as r:
            body = r.read().decode("utf-8", "replace")
        if "<!DOCTYPE" in body[:60] and "const c=" in body:
            c = re.search(r'const c="([^"]+)"', body).group(1)
            d = int(re.search(r"\bd=(\d+)", body).group(1))
            n = self._pow(c, d)
            vreq = urllib.request.Request(
                "https://stooq.com/__verify",
                data=("c=" + urllib.parse.quote(c) + "&n=" + str(n)).encode(),
                headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded",
                         "Referer": url})
            self.opener.open(vreq, timeout=20).read()
            self.solved = True
            time.sleep(1.0)
            req2 = urllib.request.Request(url, headers={"User-Agent": UA})
            with self.opener.open(req2, timeout=20) as r2:
                return r2.read().decode("utf-8", "replace"), True
        return body, False


_STOOQ: _StooqSession | None = None

STOOQ_SUFFIX = {"US": "us", "UK": "uk", "DE": "de", "FR": "fr", "NL": "nl", "IT": "it",
                "ES": "es", "SE": "se", "CH": "sw", "JP": "jp", "HK": "hk", "AU": "au",
                "CA": "to", "IN": "in", "SG": "sg", "NZ": "nz"}


def stooq_fetch(market: str, base: str, start: str, end: str) -> dict:
    global _STOOQ
    res = {"ok": False, "hist_ok": False, "source": "stooq", "symbol_used": None,
           "rows": 0, "first_date": None, "last_date": None, "adjusted": "unknown",
           "note": "", "data": []}
    sym = f"{base.lower()}.{STOOQ_SUFFIX.get(market, market.lower())}"
    res["symbol_used"] = sym
    try:
        if _STOOQ is None:
            _STOOQ = _StooqSession()
        body, _challenged = _STOOQ.get(
            f"https://stooq.com/q/d/l/?s={urllib.parse.quote(sym)}&d1={start}&d2={end}&i=d")
    except Exception as e:  # noqa: BLE001
        res["note"] = f"http_fail:{type(e).__name__}"
        return res
    if "<!DOCTYPE" in body[:60]:
        res["note"] = "challenge_page"
        return res
    if "Access denied" in body[:60]:
        res["note"] = "access_denied(CSV端点封锁)"
        return res
    lines = [ln for ln in body.strip().splitlines() if ln]
    if not lines or lines[0].lower().startswith("no data"):
        res["note"] = "no_data"
        return res
    rows = []
    for ln in lines[1:]:
        p = ln.split(",")
        if len(p) < 6:
            continue
        try:  # stooq 字段序 Date,Open,High,Low,Close,Volume
            rows.append({"date": p[0], "open": float(p[1]), "high": float(p[2]),
                         "low": float(p[3]), "close": float(p[4]), "volume": float(p[5])})
        except ValueError:
            continue
    res.update(ok=bool(rows), hist_ok=len(rows) > 1, rows=len(rows),
               first_date=rows[0]["date"] if rows else None,
               last_date=rows[-1]["date"] if rows else None, data=rows)
    return res


# ── 编排 ───────────────────────────────────────────────────────────────────
def parse_ticker(ticker: str, market: str | None = None) -> tuple[str, str]:
    """返回 (market, base)。裸代码默认 US（UK 裸代码场景由 --market 显式给）。"""
    t = ticker.strip()
    if t.startswith("^"):
        return market or "US", t
    m = re.match(r"^([^.]+)\.(T|KS|KQ|NS|AX|TO|DE|PA|MI|MC|ST|AS|SW|SI|NZ|HK|SS|SZ)$", t)
    if m:
        suffix = m.group(2)
        mk = {"T": "JP", "KS": "KR", "KQ": "KR", "NS": "IN", "AX": "AU", "TO": "CA",
              "DE": "DE", "PA": "FR", "MI": "IT", "MC": "ES", "ST": "SE", "AS": "NL",
              "SW": "CH", "SI": "SG", "NZ": "NZ"}.get(suffix, "US")
        return market or mk, m.group(1)
    return market or "US", t


def sources_for(market: str, ticker: str) -> list[str]:
    if ticker.startswith("^"):
        return INDEX_SOURCES.get(ticker, [_Y, "eastmoney"])
    return SOURCE_PLAN.get(market, [_Y, "eastmoney"])


def fetch_one(ticker: str, market: str | None = None,
              start: str = "20260701", end: str = "20260824",
              keep_data: bool = False) -> dict:
    """按源计划顺序取数，命中 hist_ok 即短路（生产 fill 同语义，省调用配额）。
    stooq 已判死：不再发网络请求，直接记 dead_source。"""
    mk, base = parse_ticker(ticker, market)
    results = {}
    # 有声失败（2026-09-13）：单只走全源链时可静默重试 2 分钟+（push2his 掐断 python 栈
    # 后 requests 3×25s + curl 3×25s 深退避），操作者只见空白。每源向 stderr 打心跳；
    # stdout 的 JSON 结果结构不变。FENG_INTL_QUIET=1 可关（体检探针批量跑时用）。
    _beat = os.environ.get("FENG_INTL_QUIET", "") != "1"
    for src in sources_for(mk, ticker):
        _t0 = time.time()
        if _beat:
            print(f"[{ticker}] 源={src} 请求中…", file=sys.stderr, flush=True)
        if src == "yfinance":
            r = yfinance_fetch(ticker, mk, start, end)
        elif src == "tencent":
            r = tencent_fetch(mk, base, start, end)
        elif src == "eastmoney":
            r = eastmoney_fetch(mk, ticker, base, start, end)
        elif src == "naver":
            r = naver_fetch(mk, base)
        elif src == "stooq":
            r = {"ok": False, "hist_ok": False, "source": "stooq", "symbol_used": None,
                 "rows": 0, "first_date": None, "last_date": None, "adjusted": "unknown",
                 "note": "dead_source(JS质询+Access denied)", "data": []}
        else:
            continue
        if not keep_data:
            r = {k: v for k, v in r.items() if k != "data"}
        results[src] = r
        if _beat:
            print(f"[{ticker}] 源={src} {'HIT' if r['hist_ok'] else 'miss'} "
                  f"用时{time.time() - _t0:.0f}s rows={r['rows']} note={str(r['note'])[:60]}",
                  file=sys.stderr, flush=True)
        if r["hist_ok"]:
            break
    chosen = next(({"source": s, **results[s]} for s in results if results[s]["hist_ok"]), None)
    return {"ticker": ticker, "market": mk, "results": results, "chosen": chosen}


# ── 只读 DB ────────────────────────────────────────────────────────────────
def db_readonly():
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def market_tickers(market: str) -> list[str]:
    with db_readonly() as con:
        rows = con.execute("SELECT ticker FROM indices WHERE market=? ORDER BY id",
                           (market,)).fetchall()
    return [r["ticker"] for r in rows]


# ── 子命令：probe ──────────────────────────────────────────────────────────
def cmd_probe(args) -> dict:
    tickers = market_tickers(args.market)
    stocks = [t for t in tickers if not t.startswith("^")]
    idxs = [t for t in tickers if t.startswith("^")]
    rng = random.Random(args.seed)
    sample = sorted(rng.sample(stocks, min(args.sample, len(stocks)))) if stocks else []
    matrix = {"market": args.market, "total": len(tickers), "sampled_stocks": sample,
              "sample_size": len(sample), "sources": {}, "detail": [], "indices_note": None}
    counters: dict[str, dict[str, int]] = {}
    for t in sample:
        fr = fetch_one(t, args.market, args.start, args.end)
        row = {"ticker": t}
        for src, r in fr["results"].items():
            c = counters.setdefault(src, {"ok": 0, "hist_ok": 0, "fail": 0})
            if r["hist_ok"]:
                c["hist_ok"] += 1
            elif r.get("ok"):
                c["ok"] += 1  # 有响应但无历史（如腾讯 quote_only 回退）
            else:
                c["fail"] += 1
            row[src] = {"hist_ok": r["hist_ok"], "rows": r["rows"],
                        "symbol": r["symbol_used"], "note": r["note"],
                        "range": [r["first_date"], r["last_date"]]}
        matrix["detail"].append(row)
    matrix["sources"] = counters
    if idxs:
        irow = {}
        for t in idxs:
            fr = fetch_one(t, args.market, args.start, args.end)
            hit = [s for s, r in fr["results"].items() if r["hist_ok"]]
            irow[t] = {"hit_sources": hit,
                       "symbols": {s: fr["results"][s]["symbol_used"] for s in fr["results"]}}
        matrix["indices_note"] = irow
    return matrix


# ── 子命令：fill（本轮只留代码路径，绝不执行真库写入）──────────────────────
def cmd_fill(args) -> int:
    """批量补齐。四重保险：dry-run 默认开 + FENG_INTL_FILL_CONFIRM=YES 二次确认 +
    fengdb/safe_batch 仅在本函数 import + 每市场独立 changeset 可 undo。"""
    mk = args.market
    tickers = market_tickers(mk)
    print(f"[fill:{mk}] {len(tickers)} tickers, range {args.start}-{args.end}, "
          f"dry_run={args.dry_run}")
    if args.dry_run:
        plans = []
        for t in tickers:
            mk2, base = parse_ticker(t, mk)
            srcs = sources_for(mk2, t)
            plans.append({"ticker": t, "planned_sources": srcs})
        ok_n = sum(1 for p in plans if p["planned_sources"])
        print(json.dumps({"dry_run": True, "market": mk, "tickers": len(plans),
                          "with_source_plan": ok_n,
                          "would_write_table": "daily_data(index_id,date,O,H,L,C,V,unadj_close)",
                          "write_path": "tools/fengdb.safe_batch(['daily_data','update_log'],"
                                        f"'intl_fill_{mk}_<date>')"}, ensure_ascii=False))
        print("[fill] dry-run 结束，未写任何数据。去掉 --dry-run 也需要 "
              "FENG_INTL_FILL_CONFIRM=YES 才会真正写库。")
        return 0
    if os.environ.get("FENG_INTL_FILL_CONFIRM") != "YES":
        print("[fill] REFUSED: 需要 FENG_INTL_FILL_CONFIRM=YES 才允许真实写库。")
        return 2
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from fengdb import safe_batch  # noqa: PLC0415 — 仅真实写库时才 import

    written = skipped = failed = 0
    with db_readonly() as ro:
        id_map = {r["ticker"]: r["id"] for r in
                  ro.execute("SELECT id,ticker FROM indices WHERE market=?", (mk,))}
    with safe_batch(["daily_data", "update_log"], f"intl_fill_{mk}", DB_PATH) as con:
        for t in tickers:
            fr = fetch_one(t, mk, args.start, args.end, keep_data=True)
            ch = fr["chosen"]
            if not ch:
                failed += 1
                continue
            iid = id_map.get(t)
            if iid is None:
                skipped += 1
                continue
            for row in ch["data"]:
                con.execute(
                    "INSERT OR REPLACE INTO daily_data"
                    "(index_id,date,open,high,low,close,volume,unadj_close) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (iid, row["date"], row["open"], row["high"], row["low"],
                     row["close"], row["volume"], row.get("unadj_close", row["close"])))
            written += 1
    print(f"[fill:{mk}] done: fetched={written} no_source={failed} no_index_id={skipped}; "
          f"changeset 已落盘可用 fengdb.undo_changeset 精确撤销。")
    return 0


# ── CLI ────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="非中港台市场日线多源适配器（研发版）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pp = sub.add_parser("probe", help="每市场抽 N 只实测各源覆盖率")
    pp.add_argument("--market", required=True, choices=TARGET_MARKETS)
    pp.add_argument("--sample", type=int, default=5)
    pp.add_argument("--start", default="20260701")
    pp.add_argument("--end", default="20260824")
    pp.add_argument("--seed", type=int, default=42)
    pp.set_defaults(fn=lambda a: print(json.dumps(cmd_probe(a), ensure_ascii=False)))

    fp = sub.add_parser("fetch", help="单只取数打印 JSON")
    fp.add_argument("ticker")
    fp.add_argument("--market", choices=TARGET_MARKETS)
    fp.add_argument("--start", default="20260701")
    fp.add_argument("--end", default="20260824")
    fp.add_argument("--keep-data", action="store_true", help="附全量K线（默认只附最后2根）")

    def _fetch_fn(a):
        fr = fetch_one(a.ticker, a.market, a.start, a.end, keep_data=True)
        out = dict(fr)
        for s, r in out["results"].items():
            if isinstance(r.get("data"), list) and len(r["data"]) > 2:
                r["data_head"] = r["data"][:1]
                r["data_last2"] = r["data"][-2:]
                del r["data"]
        if out.get("chosen") and isinstance(out["chosen"].get("data"), list) \
                and len(out["chosen"]["data"]) > 4:
            out["chosen"]["data"] = out["chosen"]["data"][-2:]
        print(json.dumps(out, ensure_ascii=False))

    fp.set_defaults(fn=_fetch_fn)

    fl = sub.add_parser("fill", help="批量补齐（默认 dry-run；真实写库需双重确认）")
    fl.add_argument("--market", required=True, choices=TARGET_MARKETS)
    fl.add_argument("--start", default="20260722")
    fl.add_argument("--end", default=time.strftime("%Y%m%d"))
    fl.add_argument("--dry-run", dest="dry_run", action=argparse.BooleanOptionalAction,
                    default=True)
    fl.set_defaults(fn=cmd_fill)

    args = ap.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
