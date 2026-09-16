#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fengastock.py — A股数据工具包（整合自上游 simonlin1212/a-stock-data V3.7.1，Apache-2.0）

定位
----
FengInvest 的 A股多源取数工具：估值历史 / 上市退市日 / 申万行业变迁史 / 新浪复权因子 /
腾讯实时行情 / 人行社融+统计局 PMI，以及东财系 best-effort 端点（龙虎榜 / 涨停池 /
解禁 / 两融 / 资金流）。所有端点代码抽取自 vendor 原文：
    research/070-reports/vendor/a-stock-data-SKILL.md
抽取时保留上游防坑逻辑与关键注释（腾讯字段 43=振幅%/46=PB、新浪 qfq 是除数 hfq 是乘数、
北交所老码僵尸报价 is_stale、baostock 登录前拦截北交所、东财 em_get 限流防封）。

铁律
----
- 本轮所有端点只打印 JSON，绝不写 data/market_data.db（入库统一走 tools/fengdb.py）。
- 无来源 = 不存在：每个输出带 source 标注；网络失败如实报错（{"error": ...} + exit 1），不编造。

用法（CLI）
-----------
    # 实时行情（腾讯）：价/PE(TTM)/PB/总市值/流通市值/换手率/涨跌停价，含 is_stale 僵尸报价标志
    python tools/fengastock.py quote 600036
    python tools/fengastock.py quote 600519 sz000001 sh000001     # 支持显式前缀消歧

    # 估值历史（baostock 日频 PE/PB/PS/PCF + 换手率 + 停牌 + ST），附窗口分位数
    python tools/fengastock.py valuation-hist 600519 --start 2016-01-01 --end 2026-08-24
    python tools/fengastock.py valuation-hist 600036 --metric pe

    # 上市日/退市日/状态（baostock；北交所 4/8/92/920 号段登录前拦截并明确报错）
    python tools/fengastock.py ipo-date 600036

    # 申万行业变迁史（该股票历次行业调整；--as-of 取某日当时归属）
    python tools/fengastock.py sw-industry 000001
    python tools/fengastock.py sw-industry 000001 --as-of 2016-01-01

    # 新浪复权因子序列（qfq=前复权除数 / hfq=后复权乘数）
    python tools/fengastock.py adj-factor 600519 --kind qfq

    # 宏观：人行社融月度12列 + 统计局 PMI（制造业/非制造业/综合 + 大中小型分档）
    python tools/fengastock.py macro
    python tools/fengastock.py macro --year 2024

    # —— 第二批（东财系，走 em_get() 限流）——
    python tools/fengastock.py lhb 002475 --date 2026-08-21        # 个股龙虎榜席位
    python tools/fengastock.py lhb-market --min-net-buy 5000       # 全市场龙虎榜
    python tools/fengastock.py limit-pool                          # 涨停/炸板/跌停/昨日涨停四池
    python tools/fengastock.py unlock 002475                       # 解禁日历（历史+未来90天）
    python tools/fengastock.py margin 600519                       # 两融明细
    python tools/fengastock.py moneyflow 600519                    # 个股资金流120日

环境变量
--------
    EM_MIN_INTERVAL=1.0   东财两次请求最小间隔秒数，批量任务调大到 1.5~2 防封 IP
"""
from __future__ import annotations

import argparse
import io
import json
import random
import re
import sys
import time
import urllib.request
import warnings
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd
import requests

sys.stdout.reconfigure(encoding="utf-8")

# ═══════════════════════════════ 共享 helper（抽自上游，保留注释） ═══════════════════════════════

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# 沪市指数白名单：与深市 000xxx 个股同段，需白名单区分（沪深300/上证50/中证500/科创50/中证1000/上证180）
SH_INDEX = {"000300", "000905", "000016", "000688", "000852", "000010"}

# 整串锚定匹配，只认列出的写法；市场标识前缀、后缀**二选一，不能同时出现**。
# 上游坑注：① 别用 re.search(r"\d{6}") 从任意串里"捞"6 位（"6005190" 会被截成 600519）；
#           ② 别让前后缀同时可选（SH000001.SZ 这种自相矛盾写法会被照单全收 → 选错标的）。
_TICKER_RE = re.compile(
    r"^(?:(sh|sz|bj)(\d{6})|(\d{6})(?:\.(sh|sz|bj))?)$", re.IGNORECASE)


def _natural_market(digits: str) -> str:
    """6 位码的自然归属市场。仅用于校验显式前缀是否自相矛盾。
    注意 000xxx 是沪指数/深个股共用的歧义段，由调用处单独处理，不走这里。"""
    if digits.startswith("92") or digits[:2] in ("43", "83", "87"):
        return "bj"                      # 北交所（920 现行 / 43·83·87 老号段）
    if digits[0] in ("5", "6", "9"):
        return "sh"                      # 5x 沪 ETF/LOF，6xx 沪个股，9xx 沪 B 股
    return "sz"                          # 00x/30x/15x/16x/39x 等


def norm_ticker(code: str, stock_only: bool = False) -> str:
    """任意受支持写法 → 纯 6 位数字代码。

    支持 600519 / SH600519 / sh600519 / 600519.SH / BJ920982 等。
    ⚠️ 不匹配时抛 ValueError，绝不静默返回空串或猜一个代码——否则调用方会把
    「代码格式写错」误读成「这只票没有数据」，或拿到另一只股票的数据还以为是对的。
    """
    raw = str(code).strip()
    m = _TICKER_RE.match(raw)
    if not m:
        raise ValueError(
            f"无法把 {code!r} 解析为 6 位股票代码；"
            f"支持格式：600519 / SH600519 / sh600519 / 600519.SH"
            f"（前缀与后缀二选一，不能同时写）"
        )
    digits = m.group(2) or m.group(3)
    market = (m.group(1) or m.group(4) or "").lower()      # 前缀式与后缀式都要认
    if market:
        if digits.startswith("000"):
            # 000xxx 是沪市指数/深市个股共用歧义段：sh000001=上证指数 vs sz000001=平安银行。
            if market == "bj":
                raise ValueError(f"{code!r} 市场标识与号段矛盾：000xxx 不属北交所。")
            if stock_only and market == "sh":
                raise ValueError(
                    f"{code!r} 指向沪市指数而非个股（沪市无 000xxx 个股）。"
                    f"要查同号段的深市个股请显式传 sz{digits}。"
                )
        else:
            nat = _natural_market(digits)
            if market != nat:
                raise ValueError(
                    f"{code!r} 的市场标识与号段矛盾：{digits} 属 {nat} 市，而不是 {market} 市。"
                    f"（改用 {nat}{digits} 或去掉市场标识）"
                )
    return digits


def get_prefix(code: str) -> str:
    """6位代码 → 市场前缀（sh/sz/bj）。支持显式前缀/后缀（sh000016 / 000016.SH）透传以解决歧义。"""
    c = code.lower().strip()
    if c.endswith((".sh", ".sz", ".bj")):    # 后缀写法与前缀等价：000016.SH ≡ sh000016
        return c[-2:]
    if c.startswith(("sh", "sz", "bj")):     # 显式前缀透传（如 sh000001=上证指数 vs sz000001=平安银行）
        return c[:2]
    if c.startswith("92"):                   # 北交所 2024-10 起新股号段，必须先于下面的 9x 判断
        return "bj"
    if c.startswith(("5", "6", "9")):        # 5x=沪 ETF/LOF，6/9=沪个股（900xxx=沪 B 股）
        return "sh"
    if c.startswith(("4", "8")):             # 4x/8x=北交所老号段，多数已迁 920
        return "bj"
    if c in SH_INDEX:                         # 沪深300/上证50 等沪指数（000xxx）
        return "sh"
    return "sz"                              # 深市个股/ETF，深指数 399xxx 亦走 sz


def em_market_code(code: str) -> int:
    """东财 secid 的市场号：沪=1，深/北=0。
    ⚠️ 绝不要用 startswith("6") 判市场——会把沪 ETF(51x)/科创 ETF(588x)/沪 B(900x) 全错判成深市。"""
    return 1 if get_prefix(code) == "sh" else 0


# ── 东财防封：全局节流 + 会话复用 ────────────────────────────────────
# 上游坑注：东财系 HTTP 接口有风控：每秒 >5 次 / 单 IP 并发 ≥10 / 1 分钟 ≥200 次 → 临时封 IP。
# 所有 eastmoney.com 请求一律走 em_get()。403 不重试（风控信号，重试无益反而加重）。
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})
try:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    _em_adapter = HTTPAdapter(max_retries=Retry(
        total=3, connect=3, backoff_factor=0.6,
        status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"]))
    EM_SESSION.mount("https://", _em_adapter)
    EM_SESSION.mount("http://", _em_adapter)
except Exception:
    pass  # 老版本 urllib3 缺 allowed_methods 时降级为无重试，不影响主流程

EM_MIN_INTERVAL = float(__import__("os").environ.get("EM_MIN_INTERVAL", "1.0"))
_em_last_call = [0.0]


def em_get(url: str, params: Optional[dict] = None, headers: Optional[dict] = None,
           timeout: int = 15, **kwargs):
    """东财统一请求入口：自动节流 + 复用 session + 默认 UA。"""
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
    finally:
        _em_last_call[0] = time.time()


def eastmoney_datacenter(report_name: str, columns: str = "ALL",
                         filter_str: str = "", page_size: int = 50,
                         sort_columns: str = "", sort_types: str = "-1") -> list:
    """东财数据中心统一查询 — 龙虎榜/解禁/融资融券等共用（已内置限流）"""
    params = {
        "reportName": report_name, "columns": columns,
        "filter": filter_str, "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    }
    r = em_get(DATACENTER_URL, params=params, timeout=15)
    d = r.json()
    if d.get("result") and d["result"].get("data"):
        return d["result"]["data"]
    return []


def cn_today() -> str:
    """A股的「今天」按北京时间算。海外时区跑本机 date.today() 会错开一天。"""
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def _clean(obj):
    """numpy/pandas 标量 → 原生 Python 类型，保证 json 可序列化且无 NaN。"""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        v = float(obj)
        return None if v != v else v      # NaN → null
    if isinstance(obj, (pd.Timestamp, datetime)):
        s = obj.strftime("%Y-%m-%d %H:%M:%S")
        return s[:10] if s[10:] == " 00:00:00" else s
    return obj


def _print_json(obj) -> None:
    print(json.dumps(_clean(obj), indent=2, ensure_ascii=False))


# ═══════════════════════════════ baostock 底座（§6.5/6.6/6.7 共用） ═══════════════════════════════

@contextmanager
def bs_session():
    """baostock 登录会话 — 必须用上下文管理器，异常路径也保证 logout。
    本地适配：baostock login/logout 会向 stdout 打印「login success!」污染 JSON 输出，
    用 redirect_stdout 吞掉（仅吞库自身的提示打印，不影响数据）。"""
    import baostock as bs          # 惰性导入：HTTP 类端点不必付 TCP 库加载成本
    lg_buf = io.StringIO()
    with redirect_stdout(lg_buf):
        lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock 登录失败: {lg.error_code} {lg.error_msg}")
    try:
        yield
    finally:
        with redirect_stdout(io.StringIO()):
            bs.logout()


def _rs_to_df(rs) -> pd.DataFrame:
    """baostock ResultData → DataFrame；错误码转异常，绝不静默返回空表"""
    if rs.error_code != "0":
        raise RuntimeError(f"baostock 查询失败: {rs.error_code} {rs.error_msg}")
    rows = []
    while rs.next():
        rows.append(rs.get_row_data())
    return pd.DataFrame(rows, columns=rs.fields)


def _bs_code(code: str) -> str:
    """6位代码 → baostock 格式；北交所在登录前就拦掉。
    🔴 baostock 服务端直接拒绝 4/8/92/920 号段（报 10004011 股票代码未标识sh或sz，
    上游 2026-08-19 实测），这里提前拦截给出可操作错误，不浪费一次会话也不静默空表。"""
    code = str(code).zfill(6)
    if code[:2] in ("60", "68", "90"):
        return f"sh.{code}"
    if code[:2] in ("00", "30", "20"):
        return f"sz.{code}"
    raise ValueError(
        f"baostock 不支持该代码: {code}（北交所 4/8/92/920 号段会被服务端拒绝，"
        f"报 10004011 股票代码未标识sh或sz）。北交所当日估值请改用 quote 子命令（腾讯源）。"
    )


# ── §6.5 估值历史 ──────────────────────────────────────────────────

_VAL_FIELDS = "date,code,close,peTTM,pbMRQ,psTTM,pcfNcfTTM,turn,tradestatus,isST"
_METRIC_MAP = {"pe": "peTTM", "pb": "pbMRQ", "ps": "psTTM",
               "pcf": "pcfNcfTTM", "turn": "turn"}


def baostock_valuation_history(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """估值历史序列 — PE/PB/PS/PCF + 换手率 + 停牌 + ST，日频"""
    bs_code = _bs_code(norm_ticker(code))     # 先校验，失败就不必登录
    import baostock as bs
    with bs_session():
        rs = bs.query_history_k_data_plus(
            bs_code, _VAL_FIELDS, start_date=start_date, end_date=end_date,
            frequency="d", adjustflag="3",     # 3=不复权
        )
        df = _rs_to_df(rs)
    for c in ("close", "peTTM", "pbMRQ", "psTTM", "pcfNcfTTM", "turn"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


# ── §6.6 上市/退市基本信息 ─────────────────────────────────────────

def baostock_stock_basic(code: str) -> dict:
    """标的基本信息 — ipoDate(上市日) / outDate(退市日，在市为空) / status(1=上市 0=退市)"""
    bs_code = _bs_code(norm_ticker(code))
    import baostock as bs
    with bs_session():
        df = _rs_to_df(bs.query_stock_basic(code=bs_code))
    return df.iloc[0].to_dict() if not df.empty else {}


# ── §6.7 申万行业分类历史 ──────────────────────────────────────────

SW_URL = "https://www.swsresearch.com/swindex/pdf/SwClass2021/StockClassifyUse_stock.xls"


def sw_industry_history():
    """申万行业归属变迁史 — 每只股票每次行业调整一行。
    返回 (df, ssl_verify_skipped)。本地适配（2026-08-24 实测）：swsresearch.com 网关只下发
    叶子证书 *.swsresearch.com、缺 GeoTrust G2 中间证书（openssl verify return code 21），
    任何本机 CA 包都无法补链，且明文 http 直接断连——属站点侧配置缺陷，非本机 CA 过旧。
    故 SSLError 时降级 verify=False 重试（仅下载官方静态公开 xls，可接受），并如实标注；
    站点日后修好证书链则第一段 verify=True 直接成功，不会进入降级分支。"""
    ssl_verify_skipped = False
    try:
        r = requests.get(SW_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        r.raise_for_status()
    except requests.exceptions.SSLError as e:
        # 上游注：站点证书链正常时不会走到这；遇到多半是本机 CA 包过旧或中间人代理。
        # 本地适配：实测为站点缺中间证书，降级重试并在输出 JSON 里标注 ssl_verify_skipped。
        ssl_verify_skipped = True
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")   # 压掉 InsecureRequestWarning（stderr 不污染）
            try:
                r = requests.get(SW_URL, headers={"User-Agent": "Mozilla/5.0"},
                                 timeout=60, verify=False)
                r.raise_for_status()
            except Exception as e2:
                raise RuntimeError(
                    f"申万站点下载失败（SSL 校验与降级两种方式均尝试）: {e2}") from e2
    df = pd.read_excel(io.BytesIO(r.content))
    df = df.rename(columns={"股票代码": "code", "计入日期": "start_date",
                            "行业代码": "industry_code", "更新日期": "update_date"})
    missing = {"code", "start_date", "industry_code"} - set(df.columns)
    if missing:
        raise RuntimeError(f"申万表结构变了，缺列 {sorted(missing)}；实际列={list(df.columns)}")
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["industry_code"] = df["industry_code"].astype(str).str.zfill(6)
    # 层级码补成规范 6 位（一级 480000 / 二级 480300），截断式无法与官方指数 join。
    df["l1_code"] = df["industry_code"].str[:2] + "0000"
    df["l2_code"] = df["industry_code"].str[:4] + "00"
    df["start_date"] = pd.to_datetime(df["start_date"], errors="coerce")
    return df.sort_values(["code", "start_date"]).reset_index(drop=True), ssl_verify_skipped


def sw_industry_as_of(df: pd.DataFrame, code: str, as_of: str) -> Optional[dict]:
    """某只股票在 as_of 日所属的申万行业（取不晚于该日的最后一次调整）"""
    code = str(code).zfill(6)
    sub = df[(df["code"] == code) & (df["start_date"] <= pd.Timestamp(as_of))]
    if sub.empty:
        return None                  # 该日尚未上市 / 无归属记录
    row = sub.iloc[-1]
    return {"code": code, "as_of": as_of,
            "industry_code": row["industry_code"],
            "l1_code": row["l1_code"], "l2_code": row["l2_code"],
            "since": row["start_date"].strftime("%Y-%m-%d")}


# ── §1.4 新浪复权因子 ──────────────────────────────────────────────

def sina_adjust_factor(code: str, kind: str = "qfq") -> list:
    """新浪复权因子序列 — kind='qfq'(前复权) | 'hfq'(后复权)，按日期倒序（最新在前）。
    🔴 qfq 是**除数**（前复权价 = 不复权价 ÷ factor）、hfq 是**乘数**
    （后复权价 = 不复权价 × factor）；方向反了不报错只出错数（上游实测对照表见 vendor 文档）。"""
    if kind not in ("qfq", "hfq"):
        raise ValueError(f"kind 只能是 'qfq' 或 'hfq'，收到 {kind!r}")
    raw = str(code).strip()
    digits = norm_ticker(raw)
    # 市场：显式写法优先——前缀或 .SH 后缀直接采信；都没有才按号段推断（已处理 92 先于 9x）。
    m = re.match(r"^(sh|sz|bj)", raw, re.I) or re.search(r"\.(sh|sz|bj)$", raw, re.I)
    prefix = m.group(1).lower() if m else get_prefix(digits)
    symbol = f"{prefix}{digits}"
    url = f"https://finance.sina.com.cn/realstock/company/{symbol}/{kind}.js"
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0",
                                   "Referer": "https://finance.sina.com.cn/"}, timeout=10)
    r.raise_for_status()
    # 🔴 响应形如 `var sh600519qfq={...}` 且末尾挂着 /* base64 */ 注释块，
    #    不能用 $ 锚定正则。从第一个 { 起用 raw_decode，让解析器自己在 JSON 结束处停下。
    text = r.text
    brace = text.find("{")
    if brace < 0:
        raise RuntimeError(f"新浪复权因子响应无 JSON（{symbol}/{kind}）: {text[:120]}")
    try:
        data, _ = json.JSONDecoder().raw_decode(text[brace:])
    except json.JSONDecodeError as e:
        raise RuntimeError(f"新浪复权因子 JSON 解析失败（{symbol}/{kind}）: {e}") from e
    return [{"date": it["d"], "factor": float(it["f"])} for it in data.get("data", [])]


# ── §1.2 腾讯实时行情 ──────────────────────────────────────────────

def tencent_quote(codes: list) -> dict:
    """批量拉取腾讯财经实时行情。GBK 编码，~ 分隔字段，不封IP。
    也支持指数（sh000001=上证指数）与 ETF（sh510050）。"""
    SH_IDX = set(SH_INDEX)
    prefixed = []
    key_of = {}          # 带前缀的查询键 → 调用方原始写法，保证结果键与入参一一对应
    for c in codes:
        low = c.lower()
        if low.startswith(("sh", "sz", "bj")):        # 显式前缀透传，解决 000001 等歧义
            p = low
        elif c.startswith("92"):                      # 北交所 920 号段须先于 9x 判断
            p = f"bj{c}"
        elif c in SH_IDX or c.startswith(("5", "6", "9")):
            p = f"sh{c}"
        elif c.startswith(("4", "8")):
            p = f"bj{c}"
        else:
            p = f"sz{c}"
        prefixed.append(p)
        key_of[p] = c    # 显式前缀入参原样返回，裸代码返回裸代码

    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0")
    resp = urllib.request.urlopen(req, timeout=10)
    data = resp.read().decode("gbk")

    result = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        # 用入参原样做键：批量里同时传 sh000001 与 sz000001 时避免撞键静默覆盖。
        code = key_of.get(key, key[2:])
        result[code] = {
            "name":         vals[1],
            "price":        float(vals[3]) if vals[3] else 0,
            "last_close":   float(vals[4]) if vals[4] else 0,
            "open":         float(vals[5]) if vals[5] else 0,
            "change_amt":   float(vals[31]) if vals[31] else 0,
            "change_pct":   float(vals[32]) if vals[32] else 0,
            "high":         float(vals[33]) if vals[33] else 0,
            "low":          float(vals[34]) if vals[34] else 0,
            "amount_wan":   float(vals[37]) if vals[37] else 0,
            "turnover_pct": float(vals[38]) if vals[38] else 0,
            "pe_ttm":       float(vals[39]) if vals[39] else 0,
            # ⚠️ 上游实测校准（勿改回网上教程的错误映射）：
            #    43=振幅%（不是PB！）、44=流通市值、45=总市值（曾标反）、46=PB。
            "amplitude_pct": float(vals[43]) if vals[43] else 0,
            "float_mcap_yi": float(vals[44]) if vals[44] else 0,
            "mcap_yi":      float(vals[45]) if vals[45] else 0,
            "pb":           float(vals[46]) if vals[46] else 0,
            "limit_up":     float(vals[47]) if vals[47] else 0,
            "limit_down":   float(vals[48]) if vals[48] else 0,
            "vol_ratio":    float(vals[49]) if vals[49] else 0,
            "pe_static":    float(vals[52]) if vals[52] else 0,
        }
        # 僵尸报价检测：腾讯对「已迁移的北交所老码 / 长期停牌股」照样返回 HTTP 200 +
        # 一份定格在最后交易日的报价（成交量 0、最新价==昨收），不报任何错。
        q = result[code]
        q["is_stale"] = (q["amount_wan"] == 0 and q["price"] == q["last_close"] and q["price"] > 0)
        if q["is_stale"] and key[2:4] in ("43", "83", "87"):
            q["stale_reason"] = "北交所老号段，多数已迁至 920xxx，请按名称反查现行代码"
        elif q["is_stale"]:
            q["stale_reason"] = "成交量为 0（停牌 / 未开盘 / 废码），报价非当日真实成交"
    return result


# ── §11.1 人行社融 + §11.2 统计局 PMI ─────────────────────────────

_UA_JSON = {"User-Agent": "Mozilla/5.0"}
PBC_BASE = "https://www.pbc.gov.cn"
PBC_INDEX = f"{PBC_BASE}/diaochatongjisi/116219/116319/index.html"
NBS_INDEX = "https://www.stats.gov.cn/sj/zxfb/"


def _macro_get(url: str, timeout: int = 30) -> str:
    r = requests.get(url, headers=_UA_JSON, timeout=timeout)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text


def _abs_pbc(href: str) -> str:
    return href if href.startswith("http") else PBC_BASE + href


def pboc_social_financing(year: Optional[int] = None) -> pd.DataFrame:
    """人民银行「社会融资规模增量统计表」— 月度，单位亿元；year=None 取最新年。
    ⚠️ 仅支持 2021 年起（2020 及更早是旧版式，传入会抛错而不是返回可疑数据）；
    链路是索引→年份页→专题页→xls 三级跳，任何一级结构变更都 fail-fast 抛错。"""
    idx = _macro_get(PBC_INDEX)
    years = re.findall(r"""href=["']([^"']+)["'][^>]*>\s*(\d{4})年统计数据\s*</a>""", idx)
    if not years:
        raise RuntimeError("人民银行索引页未找到「XXXX年统计数据」链接，页面结构可能已变更")
    table = {int(y): href for href, y in years}
    target = max(table) if year is None else year
    if target not in table:
        raise ValueError(f"人民银行无 {target} 年数据，可选年份: {sorted(table, reverse=True)[:8]}")

    ypage = _macro_get(_abs_pbc(table[target]))
    topics = re.findall(r"""href=["']([^"']+)["'][^>]*>\s*(社会融资规模)\s*</a>""", ypage)
    if not topics:
        raise RuntimeError(f"{target} 年页未找到「社会融资规模」专题链接")

    tpage = _macro_get(_abs_pbc(topics[0][0]))
    books = re.findall(r"""href=["']([^"']+\.xlsx?)["']""", tpage)
    if not books:
        raise RuntimeError(f"{target} 年社融专题页未找到 xls/xlsx 附件")

    content = requests.get(_abs_pbc(books[0]), headers=_UA_JSON, timeout=60).content
    raw = pd.read_excel(io.BytesIO(content), header=None)

    start = None                      # 表头是中英双行 + 单位说明，用「月份」列定位数据起点
    for i in range(len(raw)):
        if str(raw.iloc[i, 0]).strip() == "月份":
            start = i
            break
    if start is None:
        raise RuntimeError(
            f"{target} 年社融表没有独立的「月份」表头单元格。"
            "**2020 及更早采用旧版式**，本端点仅支持 **2021 年起**。"
        )

    cols = ["month", "afre_total", "rmb_loans", "fx_loans", "entrusted_loans",
            "trust_loans", "undiscounted_bankers_acceptance", "corporate_bonds",
            "government_bonds", "equity_financing", "abs_by_depository", "loans_written_off"]
    df = raw.iloc[start + 3:].copy().iloc[:, :len(cols)]
    df.columns = cols
    df = df[df["month"].astype(str).str.match(r"^\d{4}\.\d{1,2}$", na=False)].copy()
    for c in cols[1:]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    def _month_label(v):
        """`2026.01` → 2026-01；`2026.1` → 2026-10。
        Excel 把 `2026.10` 读成浮点 `2026.1` 与 1 月撞车：单个小数位必然是被吃尾零的 x0 月。
        按单元格逐行解析，跨年工作簿也不会错位。"""
        m = re.match(r"^(\d{4})\.(\d{1,2})$", str(v).strip())
        if not m:
            return None
        year_s, mon_s = m.group(1), m.group(2)
        if len(mon_s) == 1:
            mon_s += "0"
        return f"{year_s}-{int(mon_s):02d}"

    df["month"] = [_month_label(v) for v in df["month"]]
    df = df[df["month"].notna()]
    # 旧工作簿底部会附「2017 年以来各月…」的历史区，只保留目标年，防跨年污染
    df = df[df["month"].str.startswith(f"{target}-")].reset_index(drop=True)
    # 未发布月份整行为空 —— 必须丢掉，否则调用方会把 12 行当成 12 个月的真数据。
    df = df.dropna(subset=["afre_total"]).reset_index(drop=True)
    if df.empty:
        raise RuntimeError(f"社融表解析后无有效月份（{target} 年），格式可能已变更")
    return df


def nbs_pmi() -> dict:
    """国家统计局最新 PMI — 制造业 / 非制造业商务活动 / 综合产出 + 大中小型企业"""
    idx = _macro_get(NBS_INDEX)
    links = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>\s*([^<]{6,80}?)\s*</a>', idx)
    hit = next(((u, t) for u, t in links if "采购经理指数" in t), None)
    if not hit:
        raise RuntimeError("国家统计局最新发布页未找到「采购经理指数」条目")
    href, title = hit
    url = href if href.startswith("http") else NBS_INDEX + href.lstrip("./")

    html = _macro_get(url)
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    # 🔴 正文是全角括号且括号内带空格（`（ PMI ）为 49.2%`），空白必须整个删掉才匹配得到。
    text = re.sub(r"[\s\u3000\xa0]+", "", text)

    def grab(pat):
        m = re.search(pat, text)
        return float(m.group(1)) if m else None

    ym = re.search(r"(\d{4})年(\d{1,2})月", title)

    # 分档措辞统计局用过三种版式，逐层回退；解析不到留 None（属可选字段）。
    large = medium = small = None
    combined = re.search(r"大、中、小型企业PMI分别为([\d.]+)%、([\d.]+)%和([\d.]+)%", text)
    if combined:
        large, medium, small = (float(x) for x in combined.groups())
    else:
        m_ms = re.search(r"中、小型企业PMI分别为([\d.]+)%和([\d.]+)%", text)
        if m_ms:                            # 半拆版式：中小型合并一句
            medium, small = (float(x) for x in m_ms.groups())
        for _name, _pat in (("large", r"大型企业PMI为([\d.]+)%"),
                            ("medium", r"中型企业PMI为([\d.]+)%"),
                            ("small", r"小型企业PMI为([\d.]+)%")):
            _m = re.search(_pat, text)
            if _m:
                _v = float(_m.group(1))
                if _name == "large":
                    large = _v
                elif _name == "medium" and medium is None:
                    medium = _v
                elif _name == "small" and small is None:
                    small = _v

    result = {
        "title": title.strip(),
        "period": f"{ym.group(1)}-{int(ym.group(2)):02d}" if ym else None,
        "manufacturing_pmi": grab(r"(?<!非)制造业采购经理指数（PMI）为([\d.]+)%"),
        "non_manufacturing_pmi": grab(r"非制造业商务活动指数为([\d.]+)%"),
        "composite_pmi": grab(r"综合PMI产出指数为([\d.]+)%"),
        "pmi_large": large,
        "pmi_medium": medium,
        "pmi_small": small,
        "source_url": url,
    }
    # 三个主指标是本端点的承诺输出，解析不到必须 fail-fast。
    core = ("manufacturing_pmi", "non_manufacturing_pmi", "composite_pmi")
    absent = [k for k in core if result[k] is None]
    if absent:
        raise RuntimeError(
            f"PMI 正文措辞可能已变更，无法解析 {absent}；请核对页面：{url}"
        )
    return result


# ── §3.5/3.6/3.9/4.1/4.5/8.1 东财系端点（第二批） ─────────────────

def dragon_tiger_board(code: str, trade_date: str, look_back: int = 30) -> dict:
    """龙虎榜数据聚合：上榜记录 + 买卖席位 TOP5 + 机构动向。
    上游 #45 修复注：buy_data/sell_data 必须先初始化——回看窗口内无上榜记录
    （大市值/低换手标的常态）时 if 分支不执行，曾致 UnboundLocalError。"""
    code = norm_ticker(code)
    start = datetime.strptime(trade_date, "%Y-%m-%d") - timedelta(days=look_back)
    start_str = start.strftime("%Y-%m-%d")

    records = []
    data = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE>='{start_str}')(TRADE_DATE<='{trade_date}')(SECURITY_CODE=\"{code}\")",
        page_size=50,
        sort_columns="TRADE_DATE", sort_types="-1",
    )
    for row in data:
        records.append({
            "date": str(row.get("TRADE_DATE", ""))[:10],
            "reason": row.get("EXPLANATION", ""),
            "net_buy": round((row.get("BILLBOARD_NET_AMT") or 0) / 10000, 1),
            "turnover": round(float(row.get("TURNOVERRATE") or 0), 2),
        })

    buy_data, sell_data = [], []   # ⚠️ 必须在 if 之前初始化（上游 #45 UnboundLocalError 修复）
    seats = {"buy": [], "sell": []}
    if records:
        latest_date = records[0]["date"]
        buy_data = eastmoney_datacenter(
            "RPT_BILLBOARD_DAILYDETAILSBUY",
            filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")",
            page_size=10,
            sort_columns="BUY", sort_types="-1",
        )
        for row in buy_data[:5]:
            seats["buy"].append({
                "name": row.get("OPERATEDEPT_NAME", ""),
                "buy_amt": round((row.get("BUY") or 0) / 10000, 1),
                "sell_amt": round((row.get("SELL") or 0) / 10000, 1),
                "net": round((row.get("NET") or 0) / 10000, 1),
            })
        sell_data = eastmoney_datacenter(
            "RPT_BILLBOARD_DAILYDETAILSSELL",
            filter_str=f"(TRADE_DATE='{latest_date}')(SECURITY_CODE=\"{code}\")",
            page_size=10,
            sort_columns="SELL", sort_types="-1",
        )
        for row in sell_data[:5]:
            seats["sell"].append({
                "name": row.get("OPERATEDEPT_NAME", ""),
                "buy_amt": round((row.get("BUY") or 0) / 10000, 1),
                "sell_amt": round((row.get("SELL") or 0) / 10000, 1),
                "net": round((row.get("NET") or 0) / 10000, 1),
            })

    institution = {"buy_amt": 0, "sell_amt": 0, "net_amt": 0}
    for detail_data, side in [(buy_data, "buy"), (sell_data, "sell")]:
        for row in detail_data:
            if str(row.get("OPERATEDEPT_CODE", "")) == "0":   # 机构专用席位
                amt = (row.get("BUY") or 0) if side == "buy" else (row.get("SELL") or 0)
                if side == "buy":
                    institution["buy_amt"] += amt
                else:
                    institution["sell_amt"] += amt
    institution["buy_amt"] = round(institution["buy_amt"] / 10000, 1)
    institution["sell_amt"] = round(institution["sell_amt"] / 10000, 1)
    institution["net_amt"] = round(institution["buy_amt"] - institution["sell_amt"], 1)

    return {"code": code, "trade_date": trade_date, "look_back_days": look_back,
            "records": records, "seats": seats, "institution": institution}


def daily_dragon_tiger(trade_date: str = None, min_net_buy: float = None) -> dict:
    """全市场龙虎榜：当日所有触发龙虎榜的股票 + 上榜原因 + 买卖净额 + 换手率。"""
    if trade_date is None:
        trade_date = cn_today()

    data = eastmoney_datacenter(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        filter_str=f"(TRADE_DATE>='{trade_date}')(TRADE_DATE<='{trade_date}')",
        page_size=500,
        sort_columns="BILLBOARD_NET_AMT", sort_types="-1",
    )
    if not data:
        return {"date": trade_date, "total_records": 0, "stocks": [],
                "note": "无数据（非交易日或盘后未更新）"}

    actual_date = str(data[0].get("TRADE_DATE", ""))[:10] if data else trade_date
    stocks = []
    for row in data:
        net_buy = (row.get("BILLBOARD_NET_AMT") or 0) / 10000
        if min_net_buy is not None and net_buy < min_net_buy:
            continue
        stocks.append({
            "code": row.get("SECURITY_CODE", ""),
            "name": row.get("SECURITY_NAME_ABBR", ""),
            "reason": row.get("EXPLANATION", ""),
            "close": row.get("CLOSE_PRICE") or 0,
            "change_pct": round(float(row.get("CHANGE_RATE") or 0), 2),
            "net_buy_wan": round(net_buy, 1),
            "buy_wan": round((row.get("BILLBOARD_BUY_AMT") or 0) / 10000, 1),
            "sell_wan": round((row.get("BILLBOARD_SELL_AMT") or 0) / 10000, 1),
            "turnover_pct": round(float(row.get("TURNOVERRATE") or 0), 2),
        })
    return {"date": actual_date, "total_records": len(stocks), "stocks": stocks}


def lockup_expiry(code: str, trade_date: str, forward_days: int = 90) -> dict:
    """限售解禁日历：历史解禁 + 未来 forward_days 天待解禁。"""
    code = norm_ticker(code)

    def _row(row):
        return {
            "date": str(row.get("FREE_DATE", ""))[:10],
            "type": row.get("FREE_SHARES_TYPE", ""),        # 解禁类型（东财2026改列名，旧LIMITED_STOCK_TYPE已废）
            "shares": row.get("FREE_SHARES", 0),             # 本次解禁股数(万股)
            "able_shares": row.get("ABLE_FREE_SHARES", 0),   # 实际可流通股数(万股，更贴近真实抛压)
            "ratio": row.get("FREE_RATIO", 0),               # 占总股本比(小数，×100 得百分比)
        }

    history_data = eastmoney_datacenter(
        "RPT_LIFT_STAGE",
        filter_str=f"(SECURITY_CODE=\"{code}\")",
        page_size=15,
        sort_columns="FREE_DATE", sort_types="-1",
    )
    history = [_row(row) for row in history_data]

    end_date = datetime.strptime(trade_date, "%Y-%m-%d") + timedelta(days=forward_days)
    end_str = end_date.strftime("%Y-%m-%d")
    upcoming_data = eastmoney_datacenter(
        "RPT_LIFT_STAGE",
        filter_str=f"(SECURITY_CODE=\"{code}\")(FREE_DATE>='{trade_date}')(FREE_DATE<='{end_str}')",
        page_size=20,
        sort_columns="FREE_DATE", sort_types="1",
    )
    upcoming = [_row(row) for row in upcoming_data]

    return {"code": code, "trade_date": trade_date, "forward_days": forward_days,
            "history": history, "upcoming": upcoming}


def margin_trading(code: str, page_size: int = 30) -> list:
    """融资融券明细（日级）。"""
    code = norm_ticker(code)
    data = eastmoney_datacenter(
        "RPTA_WEB_RZRQ_GGMX",
        filter_str=f'(SCODE="{code}")',
        page_size=page_size,
        sort_columns="DATE", sort_types="-1",
    )
    rows = []
    for row in data:
        rows.append({
            "date": str(row.get("DATE", ""))[:10],
            "rzye": row.get("RZYE", 0),       # 融资余额(元)
            "rzmre": row.get("RZMRE", 0),      # 融资买入额
            "rzche": row.get("RZCHE", 0),      # 融资偿还额
            "rqye": row.get("RQYE", 0),        # 融券余额(元)
            "rqmcl": row.get("RQMCL", 0),      # 融券卖出量
            "rqchl": row.get("RQCHL", 0),      # 融券偿还量
            "rzrqye": row.get("RZRQYE", 0),    # 融资融券余额合计
        })
    return rows


def stock_fund_flow_120d(code: str) -> list:
    """个股资金流（日级，最近120个交易日），单位元。
    ⚠️ push2his 对部分大陆住宅 IP 有连接级风控（偶发 HTTP 000 / 空），
    不是代码问题：隔几分钟重试 / 换网络 / 调大 EM_MIN_INTERVAL。"""
    code = norm_ticker(code)
    url = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
    params = {
        "secid": f"{em_market_code(code)}.{code}",
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65",
        "lmt": "120",
    }
    headers = {
        "User-Agent": UA,
        "Referer": "https://quote.eastmoney.com/",
        "Origin": "https://quote.eastmoney.com",
    }
    r = em_get(url, params=params, headers=headers, timeout=15)
    d = r.json()
    klines = (d.get("data") or {}).get("klines") or []

    rows = []
    for line in klines:
        parts = line.split(",")
        if len(parts) >= 7:
            rows.append({
                "date": parts[0],
                "main_net": float(parts[1]) if parts[1] != "-" else 0,
                "small_net": float(parts[2]) if parts[2] != "-" else 0,
                "mid_net": float(parts[3]) if parts[3] != "-" else 0,
                "large_net": float(parts[4]) if parts[4] != "-" else 0,
                "super_net": float(parts[5]) if parts[5] != "-" else 0,
            })
    return rows


ZTB_UT = "7eea3edcaed734bea9cbfc24409ed989"


def _fmt_zt_time(t) -> str:
    """涨停板时间整数 → HH:MM:SS（92500 → 09:25:00）。"""
    s = str(t).zfill(6)
    return f"{s[0:2]}:{s[2:4]}:{s[4:6]}"


def _em_zt_api(endpoint: str, sort: str, date: str) -> list:
    """东财涨停板行情中心通用请求（push2ex，走 em_get 限流）。
    返回 data.pool 原始列表（data 为 null = 非交易日 / 参数错）。"""
    url = f"https://push2ex.eastmoney.com/{endpoint}"
    params = {"ut": ZTB_UT, "dpt": "wz.ztzt", "Pageindex": 0,
              "pagesize": 10000, "sort": sort, "date": date}
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        r = em_get(url, params=params, headers=headers, timeout=10)
        return (r.json().get("data") or {}).get("pool") or []
    except Exception as e:
        print(f"[WARN] 涨停板池 {endpoint} 请求失败: {e}", file=sys.stderr)
        return []


_ZT_POOLS = {
    "zt": ("涨停池", "getTopicZTPool", "fbt:asc"),
    "zb": ("炸板池", "getTopicZBPool", "fbt:asc"),
    "dt": ("跌停池", "getTopicDTPool", "fund:asc"),
    "yzt": ("昨日涨停池", "getYesterdayZTPool", "zs:desc"),
}


def _fmt_zt_pool(pool_key: str, date: str) -> list:
    """四池格式化。坑：价格字段原始值是 ×1000 整数，需 ÷1000；金额单位均为元。"""
    _, endpoint, sort = _ZT_POOLS[pool_key]
    raw = _em_zt_api(endpoint, sort, date)
    out = []
    for p in raw:
        base = {"code": p["c"], "name": p["n"], "price": p["p"] / 1000,
                "pct": round(p["zdp"], 2), "turnover": round(p["hs"], 2),
                "industry": p.get("hybk", ""),
                "zt_stat": f'{(p.get("zttj") or {}).get("days", "?")}天{(p.get("zttj") or {}).get("ct", "?")}板'}
        if pool_key == "zt":
            base.update({"amount": p["amount"], "float_cap": p["ltsz"],
                         "limit_days": p["lbc"],
                         "first_seal": _fmt_zt_time(p["fbt"]), "last_seal": _fmt_zt_time(p["lbt"]),
                         "seal_fund": p["fund"], "break_times": p["zbc"]})
        elif pool_key == "zb":
            base.update({"limit_price": p["ztp"] / 1000,
                         "first_seal": _fmt_zt_time(p["fbt"]), "break_times": p["zbc"],
                         "amplitude": round(p["zf"], 2), "speed": round(p["zs"], 2)})
        elif pool_key == "dt":
            base.update({"pe": p.get("pe"), "seal_fund": p["fund"],
                         "last_seal": _fmt_zt_time(p["lbt"]),
                         "board_amount": p.get("fba"), "dt_days": p.get("days"),
                         "open_times": p.get("oc")})
        elif pool_key == "yzt":
            base.update({"amplitude": round(p["zf"], 2), "speed": round(p["zs"], 2),
                         "y_first_seal": _fmt_zt_time(p["yfbt"]), "y_limit_days": p["ylbc"]})
        out.append(base)
    return out


# ═══════════════════════════════ CLI 子命令 ═══════════════════════════════

def cmd_quote(args) -> dict:
    codes = [c.strip() for c in args.codes if c.strip()]
    # 本地适配：tencent_quote 只认纯 6 位或前缀式，先把 600519.SH 这类后缀式归一成前缀式
    fixed = []
    for c in codes:
        m = re.match(r"^(\d{6})\.(sh|sz|bj)$", c, re.I)
        fixed.append(f"{m.group(2)}{m.group(1)}".lower() if m else c)
    quotes = tencent_quote(fixed)
    return {"source": "qt.gtimg.cn (腾讯财经)", "as_of": cn_today(),
            "count": len(quotes), "quotes": quotes,
            "note": "is_stale=true 表示报价非当日真实成交（停牌/废码/北交所老码定格价），不得用于估值"}


def cmd_valuation_hist(args) -> dict:
    code = norm_ticker(args.code)
    end = args.end or cn_today()
    start = args.start or "2016-01-01"
    # 当日磁盘缓存：分位数当天不变，baostock 登录+全史拉取 ~15s 没必要重复付。
    # key=code+start+end+metric；--full（大负载）不缓存。文件损坏/写失败静默降级。
    import json as _json
    import os as _os
    cache_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "data", "cache", "fengastock")
    cache_file = _os.path.join(cache_dir, f"val_{code}_{start}_{end}_{args.metric}.json")
    if not args.full:
        try:
            with open(cache_file, "r", encoding="utf-8") as cf:
                return _json.load(cf)
        except Exception:
            pass
    df = baostock_valuation_history(code, start, end)
    if df.empty:
        raise RuntimeError(f"{code} 在 {start}~{end} 无数据（检查日期区间/代码）")
    metrics = [_METRIC_MAP[m] for m in args.metric.split(",")] if args.metric \
        else list(_METRIC_MAP.values())

    latest = df.iloc[-1].to_dict()
    # 各指标在窗口内的最新值分位（0~100，越高表示当前估值越贵）
    stats = {}
    for mcol in metrics:
        s = df[mcol].dropna()
        if s.empty:
            continue
        lv = latest.get(mcol)
        stats[mcol] = {
            "latest": lv,
            "latest_date": latest["date"],
            "window_min": round(float(s.min()), 4), "window_max": round(float(s.max()), 4),
            "window_mean": round(float(s.mean()), 4),
            "latest_percentile": round(float((s <= lv).mean() * 100), 1) if lv is not None and not np.isnan(lv) else None,
        }
    show_cols = ["date", "close"] + metrics + ["turn", "tradestatus", "isST"]
    show_cols = list(dict.fromkeys(show_cols))
    out = {
        "source": "baostock query_history_k_data_plus (日频, 不复权口径)",
        "code": code, "start": start, "end": end,
        "trading_rows": int(len(df)),
        "suspended_days": int((df["tradestatus"] == "0").sum()),
        "st_days": int((df["isST"] == "1").sum()),
        "first_date": df.iloc[0]["date"], "last_date": df.iloc[-1]["date"],
        "metrics_stats": stats,
        "tail": df.tail(args.tail)[show_cols].to_dict(orient="records"),
    }
    if args.full:
        out["rows"] = df[show_cols].to_dict(orient="records")
    else:
        try:
            _os.makedirs(cache_dir, exist_ok=True)
            with open(cache_file, "w", encoding="utf-8") as cf:
                _json.dump(out, cf, ensure_ascii=False)
        except Exception:
            pass
    return out


def cmd_ipo_date(args) -> dict:
    code = norm_ticker(args.code, stock_only=True)
    info = baostock_stock_basic(code)
    if not info:
        raise RuntimeError(f"{code}: baostock 返回空（可能未上市或已退市多年）")
    return {"source": "baostock query_stock_basic", **info,
            "note": "outDate 为空 = 仍在市；status 1=上市 0=退市"}


def cmd_sw_industry(args) -> dict:
    code = norm_ticker(args.code, stock_only=True)
    df, ssl_skipped = sw_industry_history()
    sub = df[df["code"] == code]
    if sub.empty:
        raise RuntimeError(f"{code} 无申万行业归属记录")
    records = [{
        "since": r["start_date"].strftime("%Y-%m-%d"),
        "industry_code": r["industry_code"],
        "l1_code": r["l1_code"], "l2_code": r["l2_code"],
        "update_date": str(r.get("update_date", "")),
    } for _, r in sub.iterrows()]
    out = {
        "source": "swsresearch.com SwClass2021 StockClassifyUse_stock.xls (申万一二三级)",
        "code": code, "changes_count": len(records),
        "current": records[-1] if records else None,
        "history": records,
        "note": "申万官方只发布代码不发布中文名；行业名请勿套用东财/通达信体系",
    }
    if ssl_skipped:
        # 本地适配标注：站点缺中间证书，本次下载跳过了 TLS 校验（见 sw_industry_history docstring）
        out["ssl_verify_skipped"] = True
    if args.as_of:
        out["as_of"] = sw_industry_as_of(df, code, args.as_of)
    return out


def cmd_adj_factor(args) -> dict:
    code = args.code
    factors = sina_adjust_factor(code, kind=args.kind)
    if not factors:
        raise RuntimeError(f"{code} 复权因子为空（新浪对不支持的标的返回空 data；北交所无 qfq/hfq 文件会 404）")
    # 自检口径（上游实测校准）：qfq 最新一条恒为 1.0；hfq 最早一条恒为 1.0
    newest, oldest = factors[0], factors[-1]
    checks = {}
    if args.kind == "qfq":
        checks["newest_factor_is_1"] = (newest["factor"] == 1.0)
    else:
        checks["oldest_factor_is_1"] = (oldest["factor"] == 1.0)
    return {
        "source": "finance.sina.com.cn realstock qfq/hfq.js",
        "code": norm_ticker(code), "kind": args.kind,
        "count": len(factors),
        "latest": newest, "earliest": oldest,
        "self_check": checks,
        # 🔴 方向警告：qfq 因子是除数、hfq 因子是乘数，用反不报错只出错数
        "warning": "qfq=前复权除数(不复权价÷factor)；hfq=后复权乘数(不复权价×factor)。方向反了不报错只出错数。",
        "factors": factors,
    }


def cmd_macro(args) -> dict:
    out = {"sources": ["pbc.gov.cn 社会融资规模增量统计表", "stats.gov.cn 采购经理指数"]}
    errors = {}
    try:
        sf = pboc_social_financing(args.year)
        recs = sf.to_dict(orient="records")
        out["social_financing"] = {
            "year": args.year or int(recs[-1]["month"][:4]),
            "months_published": len(recs),
            "latest_month": recs[-1]["month"],
            "latest_afre_total_yi": recs[-1]["afre_total"],
            "ytd_afre_total_yi": round(float(sf["afre_total"].sum()), 1),
            "columns": list(sf.columns),
            "monthly": recs,
        }
    except Exception as e:
        errors["social_financing"] = f"{type(e).__name__}: {e}"
        out["social_financing"] = None
    try:
        out["pmi"] = nbs_pmi()
    except Exception as e:
        errors["pmi"] = f"{type(e).__name__}: {e}"
        out["pmi"] = None
    if errors:
        out["errors"] = errors
        out["note"] = "部分宏观数据源获取失败，上方对应节为 null；错误信息如实列出，未编造数据"
    return out


def cmd_lhb(args) -> dict:
    res = dragon_tiger_board(args.code, args.date or cn_today(), look_back=args.look_back)
    res["source"] = "eastmoney datacenter RPT_DAILYBILLBOARD_*"
    return res


def cmd_lhb_market(args) -> dict:
    res = daily_dragon_tiger(args.date, min_net_buy=args.min_net_buy)
    res["source"] = "eastmoney datacenter RPT_DAILYBILLBOARD_DETAILSNEW"
    return res


def cmd_limit_pool(args) -> dict:
    date = (args.date or cn_today()).replace("-", "")
    pools = list(_ZT_POOLS.keys()) if args.pool == "all" else [args.pool]
    out = {"source": "eastmoney push2ex 涨停板池 (ut=wz.ztzt)", "date": date, "pools": {}}
    for k in pools:
        label = _ZT_POOLS[k][0]
        items = _fmt_zt_pool(k, date)
        out["pools"][k] = {"label": label, "count": len(items), "items": items}
    if all(v["count"] == 0 for v in out["pools"].values()):
        out["note"] = "四池全空：通常是非交易日，或该日数据未生成（date 必须是交易日）"
    return out


def cmd_unlock(args) -> dict:
    res = lockup_expiry(args.code, args.trade_date or cn_today(), forward_days=args.forward_days)
    res["source"] = "eastmoney datacenter RPT_LIFT_STAGE"
    return res


def cmd_margin(args) -> dict:
    rows = margin_trading(args.code, page_size=args.limit)
    if not rows:
        raise RuntimeError(f"{args.code} 无两融明细（可能非两融标的）")
    return {"source": "eastmoney datacenter RPTA_WEB_RZRQ_GGMX",
            "code": norm_ticker(args.code), "count": len(rows),
            "latest": rows[0], "rows": rows}


def cmd_moneyflow(args) -> dict:
    rows = stock_fund_flow_120d(args.code)
    if not rows:
        raise RuntimeError(
            f"{args.code} 资金流为空。注意：push2his 对部分大陆住宅 IP 间歇封锁（上游 #18），"
            "可隔几分钟重试 / 换网络 / 调大 EM_MIN_INTERVAL 再试")
    recent20 = sum(d["main_net"] for d in rows[-20:])
    return {"source": "eastmoney push2his fflow/daykline",
            "code": norm_ticker(args.code), "count": len(rows),
            "recent_20d_main_net_yi": round(recent20 / 1e8, 2),
            "rows": rows}


# ═══════════════════════════════ main ═══════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fengastock.py",
                                description="A股数据工具包（vendor: simonlin1212/a-stock-data V3.7.1, Apache-2.0）")
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("quote", help="腾讯实时行情：价/PE(TTM)/PB/市值/换手/涨跌停 + is_stale")
    sp.add_argument("codes", nargs="+", help="如 600036 / sz000001 / sh000001 / BJ920982")
    sp.set_defaults(func=cmd_quote)

    sp = sub.add_parser("valuation-hist", help="baostock 日频 PE/PB/PS/PCF+换手+停牌+ST（附窗口分位）")
    sp.add_argument("code")
    sp.add_argument("--start", default="2016-01-01", help="起始日 YYYY-MM-DD（默认 2016-01-01）")
    sp.add_argument("--end", default=None, help="结束日（默认北京时间今天）")
    sp.add_argument("--metric", default=None,
                    help="逗号分隔，取值 pe/pb/ps/pcf/turn（默认全部；影响统计与输出列）")
    sp.add_argument("--tail", type=int, default=5, help="末尾样本行数（默认 5）")
    sp.add_argument("--full", action="store_true", help="输出全部逐日行（JSON 会很大）")
    sp.set_defaults(func=cmd_valuation_hist)

    sp = sub.add_parser("ipo-date", help="baostock 上市日/退市日/状态（北交所号段登录前拦截）")
    sp.add_argument("code")
    sp.set_defaults(func=cmd_ipo_date)

    sp = sub.add_parser("sw-industry", help="申万行业变迁史（历次调整；--as-of 消前视偏差）")
    sp.add_argument("code")
    sp.add_argument("--as-of", default=None, help="YYYY-MM-DD，额外给出该日当时的行业归属")
    sp.set_defaults(func=cmd_sw_industry)

    sp = sub.add_parser("adj-factor", help="新浪复权因子序列（qfq 除数 / hfq 乘数）")
    sp.add_argument("code")
    sp.add_argument("--kind", choices=["qfq", "hfq"], default="qfq")
    sp.set_defaults(func=cmd_adj_factor)

    sp = sub.add_parser("macro", help="人行社融月度12列（2021年起）+ 统计局 PMI")
    sp.add_argument("--year", type=int, default=None, help="社融年份（默认最新年）")
    sp.set_defaults(func=cmd_macro)

    # —— 第二批（东财系）——
    sp = sub.add_parser("lhb", help="个股龙虎榜：上榜记录+席位TOP5+机构动向")
    sp.add_argument("code")
    sp.add_argument("--date", default=None, help="YYYY-MM-DD（默认北京时间今天）")
    sp.add_argument("--look-back", type=int, default=30)
    sp.set_defaults(func=cmd_lhb)

    sp = sub.add_parser("lhb-market", help="全市场龙虎榜汇总")
    sp.add_argument("--date", default=None)
    sp.add_argument("--min-net-buy", type=float, default=None, help="净买入下限（万元）")
    sp.set_defaults(func=cmd_lhb_market)

    sp = sub.add_parser("limit-pool", help="涨停/炸板/跌停/昨日涨停 四池")
    sp.add_argument("--pool", choices=["zt", "zb", "dt", "yzt", "all"], default="all")
    sp.add_argument("--date", default=None, help="YYYYMMDD 或 YYYY-MM-DD（必须是交易日）")
    sp.set_defaults(func=cmd_limit_pool)

    sp = sub.add_parser("unlock", help="限售解禁日历（历史 + 未来 N 天）")
    sp.add_argument("code")
    sp.add_argument("--trade-date", default=None)
    sp.add_argument("--forward-days", type=int, default=90)
    sp.set_defaults(func=cmd_unlock)

    sp = sub.add_parser("margin", help="两融明细（日级）")
    sp.add_argument("code")
    sp.add_argument("--limit", type=int, default=30)
    sp.set_defaults(func=cmd_margin)

    sp = sub.add_parser("moneyflow", help="个股资金流 120 日（主力/超大/大/中/小单）")
    sp.add_argument("code")
    sp.set_defaults(func=cmd_moneyflow)

    return p


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = args.func(args)
        _print_json(result)
        return 0
    except Exception as e:
        _print_json({"error": str(e), "type": type(e).__name__,
                     "command": getattr(args, "command", "?"), "ts": cn_today()})
        return 1


if __name__ == "__main__":
    sys.exit(main())
