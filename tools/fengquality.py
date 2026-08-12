#!/usr/bin/env python3
"""
fengquality.py — M层数据质量交叉验证工具

从 stockanalysis.com 拉取 PE/Forward PE 与本地 02-market.json 对比。
差异 > 10% → exit 2 (FAIL)
差异 5-10% → exit 1 (WARNING)
差异 < 5% 或无数据 → exit 0 (PASS)

用法:
  python tools/fengquality.py --cross-check <TICKER>           # 验证已有 02-market.json
  python tools/fengquality.py --cross-check <TICKER> --file <M层JSON路径>  # 指定 02-market.json
  python tools/fengquality.py --fetch <TICKER>                 # 仅拉取 stockanalysis PE 数据
"""

import json, os, re, sys, argparse

STOCKANALYSIS_URL = "https://stockanalysis.com/quote/{exchange}/{ticker}/"

EXCHANGE_MAP = {
    "HK": "hkg",
    "SS": "shs",
    "SZ": "shs",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

THRESHOLD_WARNING = 5    # % 差异 → WARNING
THRESHOLD_FAIL = 10      # % 差异 → FAIL


def _resolve_exchange(ticker: str) -> str:
    """从 ticker 后缀推断 stockanalysis exchange code。"""
    if ".HK" in ticker.upper():
        return "hkg"
    if ".SS" in ticker.upper():
        return "shs"
    if ".SZ" in ticker.upper():
        return "shs"
    return "hkg"  # 默认 fallback


def _ticker_slug(ticker: str) -> str:
    """0700.HK → 0700, 600519.SS → 600519"""
    return ticker.split(".")[0]


def fetch_stockanalysis(ticker: str) -> dict:
    """从 stockanalysis.com 获取关键财务指标。"""
    exchange = _resolve_exchange(ticker)
    slug = _ticker_slug(ticker)
    url = STOCKANALYSIS_URL.format(exchange=exchange, ticker=slug)

    import requests
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()

    data = {}
    pairs = re.findall(
        r'<td[^>]*>([^<]+)</td>\s*<td[^>]*>([^<]+)</td>',
        r.text
    )
    for label, value in pairs:
        label = label.strip()
        value = value.strip()
        if label == "PE Ratio":
            data["pe_ttm"] = _parse_number(value)
        elif label == "Forward PE":
            data["pe_forward"] = _parse_number(value)
        elif label == "Ex-Dividend Date":
            data["ex_dividend_date"] = value

    data["url"] = url
    data["fetched_at"] = __import__("datetime").datetime.now().isoformat()
    return data


def _parse_number(s: str):
    """'16.20' → 16.2, 'N/A' → None"""
    try:
        return float(s.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def cross_check(ticker: str, market_path: str | None = None) -> dict:
    """比较 02-market.json 与 stockanalysis.com 数据。"""
    # 1) 读取本地 market 数据
    if market_path:
        if not os.path.exists(market_path):
            return {"status": "ERROR", "message": f"文件不存在: {market_path}"}
    else:
        # 自动查找最新分析目录
        base_dir = os.path.join("research", "060-companies")
        candidates = [d for d in os.listdir(base_dir) if d.upper().startswith(ticker.upper())] if os.path.isdir(base_dir) else []
        if not candidates:
            return {"status": "ERROR", "message": f"未找到 {ticker} 的分析目录"}
        candidates.sort(reverse=True)
        found = None
        for c in candidates:
            date_dir = os.path.join(base_dir, c)
            if os.path.isdir(date_dir):
                dates = sorted(os.listdir(date_dir), reverse=True)
                for d in dates:
                    p = os.path.join(date_dir, d, "02-market.json")
                    if os.path.exists(p):
                        found = p
                        break
                if found:
                    break
        if not found:
            return {"status": "ERROR", "message": f"未找到 {ticker} 的 02-market.json"}
        market_path = found

    with open(market_path, encoding="utf-8") as f:
        market = json.load(f)

    financials = market.get("financials", {})
    local_pe_ttm = financials.get("pe_ttm")
    local_pe_fwd = financials.get("pe_forward")

    # 2) 从 stockanalysis 拉数据
    try:
        remote = fetch_stockanalysis(ticker)
    except Exception as e:
        return {
            "status": "ERROR",
            "message": f"stockanalysis.com 拉取失败: {e}",
            "local_file": market_path,
        }

    # 3) 比较
    checks = []
    has_fail = False
    has_warning = False

    # PE TTM
    if local_pe_ttm and remote.get("pe_ttm"):
        diff = abs(local_pe_ttm - remote["pe_ttm"]) / max(local_pe_ttm, remote["pe_ttm"]) * 100
        level = "PASS" if diff < THRESHOLD_WARNING else ("WARNING" if diff < THRESHOLD_FAIL else "FAIL")
        if level == "FAIL":
            has_fail = True
        elif level == "WARNING":
            has_warning = True
        checks.append({
            "metric": "pe_ttm",
            "local": local_pe_ttm,
            "stockanalysis": remote["pe_ttm"],
            "diff_pct": round(diff, 1),
            "level": level,
        })
    elif local_pe_ttm and not remote.get("pe_ttm"):
        checks.append({
            "metric": "pe_ttm",
            "local": local_pe_ttm,
            "stockanalysis": None,
            "diff_pct": None,
            "level": "SKIP",
            "reason": "stockanalysis 无 PE 数据",
        })

    # Forward PE
    if local_pe_fwd and remote.get("pe_forward"):
        diff = abs(local_pe_fwd - remote["pe_forward"]) / max(local_pe_fwd, remote["pe_forward"]) * 100
        level = "PASS" if diff < THRESHOLD_WARNING else ("WARNING" if diff < THRESHOLD_FAIL else "FAIL")
        if level == "FAIL":
            has_fail = True
        elif level == "WARNING":
            has_warning = True
        checks.append({
            "metric": "pe_forward",
            "local": local_pe_fwd,
            "stockanalysis": remote["pe_forward"],
            "diff_pct": round(diff, 1),
            "level": level,
        })
    elif local_pe_fwd and not remote.get("pe_forward"):
        checks.append({
            "metric": "pe_forward",
            "local": local_pe_fwd,
            "stockanalysis": None,
            "diff_pct": None,
            "level": "SKIP",
            "reason": "stockanalysis 无 Forward PE 数据",
        })

    # 综合判定
    if has_fail:
        status = "FAIL"
    elif has_warning:
        status = "WARNING"
    elif checks:
        status = "PASS"
    else:
        status = "SKIP"
        checks.append({"metric": "pe_ttm", "level": "SKIP", "reason": "本地 02-market.json 无 PE 数据可验证"})

    return {
        "status": status,
        "local_file": market_path,
        "stockanalysis_url": remote.get("url", ""),
        "fetched_at": remote.get("fetched_at", ""),
        "checks": checks,
    }


def main():
    parser = argparse.ArgumentParser(description="M层数据质量交叉验证")
    parser.add_argument("--cross-check", metavar="TICKER", help="验证 02-market.json 数据质量")
    parser.add_argument("--file", metavar="PATH", help="指定 02-market.json 路径（配合 --cross-check 使用）")
    parser.add_argument("--fetch", metavar="TICKER", help="仅从 stockanalysis 拉取 PE 数据")
    args = parser.parse_args()

    if args.fetch:
        data = fetch_stockanalysis(args.fetch)
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0

    if args.cross_check:
        result = cross_check(args.cross_check, args.file)
        print(json.dumps(result, indent=2, ensure_ascii=False))

        if result["status"] == "FAIL":
            print(f"\n❌ 数据质量 FAIL — PE 数据差异 > {THRESHOLD_FAIL}%，建议修正后重跑", file=sys.stderr)
            return 2
        elif result["status"] == "WARNING":
            print(f"\n⚠️  数据质量 WARNING — PE 数据差异介于 {THRESHOLD_WARNING}-{THRESHOLD_FAIL}%，建议核查", file=sys.stderr)
            return 1
        elif result["status"] == "ERROR":
            print(f"\nERROR: {result['message']}", file=sys.stderr)
            return 1

        print(f"\n✅ 数据质量 PASS — 所有检查项差异 < {THRESHOLD_WARNING}%", file=sys.stderr)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
