#!/usr/bin/env python3
"""feng_total_return.py — 获取总回报指数（Total Return Index）

当前支持：
  - CN: CSI300 (000922) 中证沪深300全收益指数 → 2005-01~2019-01(Sina) / 2018-05~2024-06(csindex)
  - HK: HSIT 恒生总回报指数 → 2023-12~至今(东方财富)

由于数据源不统一且历史不连续，暂时不写入 daily_data 表，
而是保存 JSON 到 research/070-reports/ 供参考。

用法:
    python tools/feng_total_return.py
    python tools/feng_total_return.py --all
"""
import json, os, sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "research", "070-reports", "total_return_indices.json")

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

CSI300_TR_AVAILABLE = False
HSITR_AVAILABLE = True

CSI300_NOTE = "中证不公开沪深300全收益指数(H00300)序列。CSI 股息指数(000922)虽有数据但非总回报指数。如需要 TR，需从 CSI300 + 分红数据自行计算。"

def fetch_hsi_tr():
    """获取恒生总回报指数 (HSIT)：东方财富源，2023-12~至今"""
    import akshare as ak
    results = {"source": "eastmoney", "symbol": "HSIT", "name": "恒生总回报指数", "data": []}

    try:
        df = ak.stock_hk_index_daily_em(symbol="HSIT")
        if df is not None and not df.empty:
            results["data"] = [
                {"date": str(row["date"]), "close": float(row["latest"])}
                for _, row in df.iterrows()
                if row["date"]
            ]
            log(f"  HSIT TR (EM): {len(results['data'])} rows, "
                f"{results['data'][0]['date']} ~ {results['data'][-1]['date']}")
    except Exception as e:
        log(f"  HSIT TR (EM): {e}")

    return results


def fetch_hsi_tr():
    """获取恒生总回报指数 (HSIT)"""
    import akshare as ak
    results = {"source": "eastmoney", "symbol": "HSIT", "name": "恒生总回报指数", "data": []}

    try:
        df = ak.stock_hk_index_daily_em(symbol="HSIT")
        if df is not None and not df.empty:
            results["data"] = [
                {"date": str(row["date"]), "close": float(row["latest"])}
                for _, row in df.iterrows()
                if row["date"]
            ]
            log(f"  HSIT TR (EM): {len(results['data'])} rows, "
                f"{results['data'][0]['date']} ~ {results['data'][-1]['date']}")
    except Exception as e:
        log(f"  HSIT TR (EM): {e}")

    return results


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)

    hsi = fetch_hsi_tr()

    result = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "indices": [hsi],
        "notes": {
            "csi300_tr": CSI300_NOTE,
            "hsi_tr": "HSIT 通过东方财富源获取，数据始于 2023-12-01，持续更新。"
        }
    }

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    log(f"\nDone! Saved to {OUT}")
    print(f"  HSIT TR:   {len(hsi['data'])} data points")


if __name__ == "__main__":
    main()
