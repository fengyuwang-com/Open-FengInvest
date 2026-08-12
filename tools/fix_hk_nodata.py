#!/usr/bin/env python3
"""补爬 12 只 HK 缺失股票 — 使用 AKShare 数据源

AKShare（https://akshare.akfamily.xyz）是中国开源金融数据接口，
支持港股、A股、期货等数据。无需 Futu OpenD。

用法:
    python tools/fix_hk_nodata.py                          # 补爬全部
    python tools/fix_hk_nodata.py --ticker 0700.HK         # 单只
"""
import os, sqlite3, sys, time
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "data", "market_data.db")

# 缺失的 HK 股票（数据库中已存在索引但无 daily_data）
HK_TICKERS = {
    "0700.HK": ("00700", "腾讯控股"),
    "0388.HK": ("00388", "香港交易所"),
    "0941.HK": ("00941", "中国移动"),
    "1299.HK": ("01299", "友邦保险"),
    "1810.HK": ("01810", "小米集团-W"),
    "0981.HK": ("00981", "中芯国际"),
    "1876.HK": ("01876", "百威亚太"),
    "2269.HK": ("02269", "药明生物"),
    "0285.HK": ("00285", "比亚迪电子"),
    "2319.HK": ("02319", "蒙牛乳业"),
    "2331.HK": ("02331", "李宁"),
    "2359.HK": ("02359", "药明康德"),
}


def download_hk_akshare(ak_code, start="1990-01-01", end=None):
    """用 AKShare 下载港股日线，返回 [(date, open, high, low, close, volume), ...]"""
    import akshare as ak
    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")
    try:
        df = ak.stock_hk_hist(symbol=ak_code, period="daily",
                              start_date=start.replace("-", ""),
                              end_date=end.replace("-", ""), adjust="")
        if df.empty:
            return []
        rows = []
        for _, r in df.iterrows():
            dt = str(r["日期"])
            try:
                rows.append((
                    dt,
                    float(r["开盘"]) if r["开盘"] else None,
                    float(r["最高"]) if r["最高"] else None,
                    float(r["最低"]) if r["最低"] else None,
                    float(r["收盘"]) if r["收盘"] else None,
                    int(float(r["成交量"])) if r["成交量"] else None,
                ))
            except (ValueError, TypeError):
                continue
        return rows
    except Exception as e:
        print(f"    [ERR] AKShare 下载失败: {e}", flush=True)
        return []


def main(ticker=None):
    conn = sqlite3.connect(DB_PATH)

    targets = {ticker: HK_TICKERS[ticker]} if ticker else HK_TICKERS

    for db_ticker, (ak_code, name) in targets.items():
        # 查找数据库索引
        row = conn.execute(
            "SELECT id FROM indices WHERE ticker=? AND market='HK'", (db_ticker,)
        ).fetchone()
        if not row:
            print(f"{db_ticker} ({name}): 不在 indices 表中，跳过", flush=True)
            continue
        idx_id = row[0]

        # 检查现有数据
        cnt = conn.execute(
            "SELECT COUNT(*) FROM daily_data WHERE index_id=?", (idx_id,)
        ).fetchone()[0]
        if cnt > 0:
            print(f"{db_ticker} ({name}): 已有 {cnt} 行，跳过", flush=True)
            continue

        # 用 AKShare 下载
        print(f"{db_ticker} ({name}): AKShare 下载中...", flush=True)
        rows = download_hk_akshare(ak_code)
        if not rows:
            print(f"  -> 空数据，跳过", flush=True)
            continue

        # 写入数据库
        data = [(idx_id, *r) for r in rows]
        conn.executemany(
            "INSERT OR IGNORE INTO daily_data (index_id,date,open,high,low,close,volume) VALUES (?,?,?,?,?,?,?)",
            data,
        )
        conn.commit()
        print(f"  -> 写入 {len(rows)} 行 ({rows[0][0]} ~ {rows[-1][0]})", flush=True)
        time.sleep(1)  # AKShare rate limit

    conn.close()
    print("\n完成!", flush=True)


if __name__ == "__main__":
    t = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].startswith("--ticker") else None
    if t:
        t = sys.argv[2]
    main(ticker=t)
