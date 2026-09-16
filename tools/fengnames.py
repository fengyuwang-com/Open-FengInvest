#!/usr/bin/env python3
"""fengnames.py — 生成 data/config/company_names.json（公司名总表，R27 创始人定调：名字为主、代码为辅）

来源合并（后写不覆盖先写的非空值，取更长名字优先）：
  1. cn_financials.short_name（A股 5,828 只中文名，每只取最新非空）
  2. data/config/research_list.json（研究清单名字）
  3. holdings/hold_*.json（持仓名，含 ETF）
  4. research/060-companies/ 目录名 TICKER-中文名

用法:
    python tools/fengnames.py            # 重建总表
    python tools/fengnames.py --en       # 额外用 yfinance 补英文短名（限在册标的，慢）
"""
import json, sqlite3, os, glob, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "data", "config", "company_names.json")


def put(names, tk, zh=None, en=None):
    if not tk:
        return
    tk = tk.strip().upper()
    if tk.endswith(".SH"):
        tk = tk[:-3] + ".SS"
    e = names.setdefault(tk, {})
    # 2005-2006 股改期"G "前缀是历史简称（G 苏泊尔→苏泊尔），不入名表
    if zh and zh.startswith("G "):
        zh = zh[2:]
    if zh and (not e.get("zh") or len(zh) > len(e["zh"])):
        e["zh"] = zh
    if en and not e.get("en"):
        e["en"] = en


def build(with_en=False):
    names = {}

    con = sqlite3.connect(os.path.join(BASE, "data", "market_data.db"))
    cur = con.cursor()
    for stkcd, sn in cur.execute(
        "SELECT stkcd, short_name FROM cn_financials WHERE short_name IS NOT NULL AND short_name != '' ORDER BY accper"
    ):
        if stkcd:
            s = str(stkcd)
            suf = ".SS" if s.startswith(("6", "9")) else (".BJ" if s.startswith(("4", "8")) else ".SZ")
            put(names, s + suf, zh=sn)
    con.close()

    rl = json.load(open(os.path.join(BASE, "data", "config", "research_list.json"), encoding="utf-8"))
    for c in rl.get("companies", []):
        put(names, c.get("ticker"), zh=c.get("name"))

    for h in glob.glob(os.path.join(BASE, "holdings", "hold_*.json")):
        try:
            d = json.load(open(h, encoding="utf-8"))
        except Exception:
            continue
        tk = d.get("ticker")
        if not tk:
            base = os.path.basename(h)[5:-5]
            if not base.startswith("cash"):
                tk = base
        put(names, tk, zh=d.get("name"))

    d060 = os.path.join(BASE, "research", "060-companies")
    if os.path.isdir(d060):
        for d in os.listdir(d060):
            if "-" in d:
                tk, nm = d.split("-", 1)
                put(names, tk, zh=nm)

    if with_en:
        import yfinance as yf
        targets = [tk for tk, v in names.items() if not tk.endswith((".SS", ".SZ", ".BJ"))][:200]
        for i, tk in enumerate(targets):
            try:
                en = yf.Ticker(tk).info.get("shortName")
                if en:
                    put(names, tk, en=en)
            except Exception:
                pass
            if i % 20 == 0:
                print("  en %d/%d" % (i, len(targets)), flush=True)

        # 腾讯 qt.gtimg.cn fallback（免代理）：港股英文名在行情字段里（如 TENCENT/POP MART）
        missing = [tk for tk in targets if tk.endswith(".HK") and not names[tk].get("en")]
        if missing:
            import re
            import urllib.request
            q = ",".join("hk" + tk[3:].zfill(5) for tk in missing)
            body = ""
            for _attempt in range(3):  # qt.gtimg.cn 偶发 none_match，重试即过
                req = urllib.request.Request(
                    "https://qt.gtimg.cn/q=" + q,
                    headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"})
                body = urllib.request.urlopen(req, timeout=15).read().decode("gbk", "replace")
                if "none_match" not in body:
                    break
                import time as _t
                print("  tencent none_match, retry %d" % (_attempt + 1), flush=True)
                _t.sleep(2)
            for tk, line in zip(missing, body.strip().splitlines()):
                fields = line.split("~")
                if len(fields) < 3:
                    continue
                en = next((f for f in fields
                           if re.fullmatch(r"[A-Z][A-Z0-9.\- ]{1,20}", f or "")
                           and f not in ("GP", "HKD")), None)
                if en:
                    put(names, tk, en=en)
            print("  tencent fallback: %d missing HK" % len(missing), flush=True)
            if "none_match" in body:
                print("  tencent fallback: 全部重试失败，本轮放弃", flush=True)

    json.dump(names, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1, sort_keys=True)
    zh = sum(1 for v in names.values() if v.get("zh"))
    en = sum(1 for v in names.values() if v.get("en"))
    print("written %s: %d tickers (zh=%d en=%d)" % (OUT, len(names), zh, en))


if __name__ == "__main__":
    build(with_en="--en" in sys.argv)
