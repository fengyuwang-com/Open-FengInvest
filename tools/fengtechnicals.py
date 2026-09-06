#!/usr/bin/env python3
"""fengtechnicals — Qlib Alpha158 六因子技术分析（纯 Pandas 实现）。

从 Qlib Alpha158 提取 6 个技术因子：ROC / STD / BETA / RSQR / CORR / CNTP。
默认 20 日滚动窗口，输出当前值 + 历史分位数（百分位排名）。

Usage:
    python fengtechnicals.py 0700.HK                  # 单只分析（自动取 250 日数据）
    python fengtechnicals.py 0700.HK AAPL MSFT        # 批量分析
    python fengtechnicals.py 0700.HK --window 30      # 自定义窗口
    python fengtechnicals.py 0700.HK --json            # JSON 纯净输出（默认）
    python fengtechnicals.py 0700.HK --factor ROC      # 只算单因子

Dependencies: yfinance（外部）, pandas, numpy（内置）。
不依赖 Qlib，纯 Pandas 实现等价计算。
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

# 清除代理环境变量，避免 yfinance 连接问题
for _k in ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"]:
    os.environ.pop(_k, None)

import numpy as np
import pandas as pd


# ── 六因子元数据 ──────────────────────────────────────────────────────────────

FACTOR_META = {
    "ROC": {
        "label": "变化率",
        "desc": "Ref($close, N)/$close — N 日前收盘价与当前价之比",
        "source": "Qlib Alpha158 ROC",
        "higher_bullish": False,  # ROC>1 表示 N 日前更贵（下跌趋势），<1 表示上涨
    },
    "STD": {
        "label": "波动率",
        "desc": "Std($close, N)/$close — N 日收盘价标准差 / 当前价（归一化波动）",
        "source": "Qlib Alpha158 STD",
        "higher_bullish": None,  # 波动率无方向性，只看绝对水平
    },
    "BETA": {
        "label": "趋势斜率",
        "desc": "Slope($close, N)/$close — 线性回归斜率 / 当前价（归一化趋势）",
        "source": "Qlib Alpha158 BETA",
        "higher_bullish": True,  # 斜率正 = 上涨趋势
    },
    "RSQR": {
        "label": "趋势质量",
        "desc": "Rsquare($close, N) — 线性回归 R²（趋势线性度）",
        "source": "Qlib Alpha158 RSQR",
        "higher_bullish": None,  # 高 R² 仅表示趋势明确，方向由 BETA 决定
    },
    "CORR": {
        "label": "量价相关性",
        "desc": "Corr($close, Log($volume+1), N) — 收盘价与 log(成交量+1) 的滚动相关",
        "source": "Qlib Alpha158 CORR",
        "higher_bullish": True,  # 正相关 = 价涨量增（健康上涨）
    },
    "CNTP": {
        "label": "上涨天数比",
        "desc": "Mean($close > Ref($close,1), N) — N 日内收涨天数占比",
        "source": "Qlib Alpha158 CNTP",
        "higher_bullish": True,  # 上涨天数多 = 多头占优
    },
}

ALL_FACTORS = list(FACTOR_META.keys())


# ── 数据获取 ──────────────────────────────────────────────────────────────────

def _db_path() -> str:
    """定位 market_data.db（相对于本文件向上两级的 data/ 目录）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "data", "market_data.db")


def fetch_from_db(ticker: str, days: int = 300) -> pd.DataFrame:
    """从本地 market_data.db 读取日线数据。

    优先数据源：避免网络依赖，与 fengdata.py / fengastock.py 一致。
    """
    import sqlite3
    db = _db_path()
    if not os.path.exists(db):
        raise FileNotFoundError(f"market_data.db 不存在: {db}")

    conn = sqlite3.connect(db)
    try:
        query = """
            SELECT d.date, d.open, d.high, d.low, d.close, d.volume
            FROM daily_data d
            JOIN indices i ON d.index_id = i.id
            WHERE i.ticker = ?
            ORDER BY d.date DESC
            LIMIT ?
        """
        # 多取一些天确保有足够数据（交易日约 250 天/年）
        limit = int(days * 1.6)
        df = pd.read_sql_query(query, conn, params=(ticker, limit), parse_dates=["date"])
    finally:
        conn.close()

    if df.empty:
        raise ValueError(f"market_data.db 中无 {ticker} 数据")

    # 反转为时间正序
    df = df.sort_values("date").set_index("date")
    # 只保留最近 days 天
    if len(df) > days:
        df = df.tail(days)

    return df[["open", "high", "low", "close", "volume"]]


def fetch_from_yfinance(ticker: str, days: int = 300) -> pd.DataFrame:
    """从 yfinance 获取日线数据（备用数据源）。"""
    import yfinance as yf

    t = yf.Ticker(ticker)
    hist = t.history(period="1y")
    if hist.empty:
        raise ValueError(f"yfinance 返回空数据: {ticker}")

    df = hist[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.columns = ["open", "high", "low", "close", "volume"]
    df.index = df.index.tz_localize(None)  # 去时区
    df.index.name = "date"
    return df


def fetch_data(ticker: str, days: int = 300) -> pd.DataFrame:
    """获取日线数据：优先本地 market_data.db，失败回退 yfinance。"""
    # 优先本地 DB
    try:
        return fetch_from_db(ticker, days)
    except (FileNotFoundError, ValueError):
        pass

    # 回退 yfinance
    return fetch_from_yfinance(ticker, days)


def get_name(ticker: str) -> str:
    """获取 ticker 的公司简称：优先 DB，回退 yfinance。"""
    # 优先 DB
    import sqlite3
    db = _db_path()
    if os.path.exists(db):
        try:
            conn = sqlite3.connect(db)
            cur = conn.execute(
                "SELECT name FROM indices WHERE ticker = ?", (ticker,)
            )
            row = cur.fetchone()
            conn.close()
            if row and row[0]:
                return row[0]
        except Exception:
            pass

    # 回退 yfinance
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        return info.get("shortName") or ticker
    except Exception:
        return ticker


# ── 因子计算（纯 Pandas，等价 Qlib 表达式） ──────────────────────────────────

def _rolling_linear_regression(series: pd.Series, window: int):
    """滚动线性回归：对每个窗口拟合 y = a + b*x（x = 0..window-1）。

    返回: (slope, rsquare) 两个 Series。
    等价 Qlib 的 Slope() 和 Rsquare() 算子。
    """
    n = len(series)
    slope = pd.Series(np.nan, index=series.index, dtype=float)
    rsquare = pd.Series(np.nan, index=series.index, dtype=float)

    vals = series.values.astype(float)
    # x = [0, 1, ..., window-1]
    x = np.arange(window, dtype=float)
    x_mean = x.mean()
    x_var = ((x - x_mean) ** 2).sum()

    for i in range(window - 1, n):
        y = vals[i - window + 1: i + 1]
        if np.any(np.isnan(y)):
            continue
        y_mean = y.mean()
        if x_var == 0:
            continue
        b = ((x - x_mean) * (y - y_mean)).sum() / x_var  # 斜率
        # R² = 1 - SS_res / SS_tot
        y_pred = y_mean + b * (x - x_mean)
        ss_res = ((y - y_pred) ** 2).sum()
        ss_tot = ((y - y_mean) ** 2).sum()
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
        slope.iloc[i] = b
        rsquare.iloc[i] = r2

    return slope, rsquare


def compute_factors(df: pd.DataFrame, window: int = 20) -> dict:
    """计算 6 个 Alpha158 技术因子的完整时间序列。

    参数:
        df: 包含 open/high/low/close/volume 列的 DataFrame
        window: 滚动窗口大小（默认 20）

    返回:
        dict，键为因子名，值为 pd.Series（与 df 等长）。
    """
    close = df["close"]
    volume = df["volume"]
    log_vol = np.log(volume + 1)

    # 1. ROC: Ref($close, window) / $close
    roc = close.shift(window) / close

    # 2. STD: Std($close, window) / $close
    rolling_std = close.rolling(window, min_periods=window).std()
    std = rolling_std / close

    # 3. BETA: Slope($close, window) / $close
    slope_series, rsquare_series = _rolling_linear_regression(close, window)
    beta = slope_series / close

    # 4. RSQR: Rsquare($close, window) — 已在上面计算
    rsqr = rsquare_series

    # 5. CORR: Corr($close, Log($volume+1), window)
    # pandas rolling corr 会处理 NaN（至少 min_periods 个非 NaN 才计算）
    corr = close.rolling(window, min_periods=window).corr(log_vol)
    # Qlib 原始实现：当任一侧 std≈0 时设为 NaN（Pandas 默认行为已覆盖）

    # 6. CNTP: Mean($close > Ref($close, 1), window)
    up_days = (close > close.shift(1)).astype(float)
    cntp = up_days.rolling(window, min_periods=window).mean()

    return {
        "ROC": roc,
        "STD": std,
        "BETA": beta,
        "RSQR": rsqr,
        "CORR": corr,
        "CNTP": cntp,
    }


def percentile_rank(value: float, series: pd.Series) -> float:
    """计算 value 在 series 中的百分位排名（0~100）。

    使用 (rank - 0.5) / n 连续性修正（与 fengquant.py 一致）。
    """
    valid = series.dropna()
    if len(valid) < 2:
        return 50.0  # 数据不足返回中位数
    rank = (valid <= value).sum()
    pct = (rank - 0.5) / len(valid) * 100
    return round(max(0, min(100, pct)), 1)


# ── 输出格式 ──────────────────────────────────────────────────────────────────

def format_result(ticker: str, name: str, factors: dict, df: pd.DataFrame,
                  window: int, target_factors: list = None) -> dict:
    """格式化输出：当前值 + 历史分位数。"""
    if target_factors is None:
        target_factors = ALL_FACTORS
    result_factors = []
    for fname in target_factors:
        series = factors[fname]
        current = series.iloc[-1]
        meta = FACTOR_META[fname]

        if pd.isna(current):
            result_factors.append({
                "factor": fname,
                "label": meta["label"],
                "desc": meta["desc"],
                "source": meta["source"],
                "current_value": None,
                "percentile": None,
                "mean": None,
                "std": None,
                "min": None,
                "max": None,
                "note": "数据不足，无法计算（需至少 window 个交易日）",
            })
            continue

        pct = percentile_rank(current, series)
        result_factors.append({
            "factor": fname,
            "label": meta["label"],
            "desc": meta["desc"],
            "source": meta["source"],
            "current_value": round(float(current), 6),
            "percentile": pct,
            "mean": round(float(series.mean()), 6),
            "std": round(float(series.std()), 6),
            "min": round(float(series.min()), 6),
            "max": round(float(series.max()), 6),
            "higher_bullish": meta["higher_bullish"],
        })

    # 汇总信号
    signals = {"BULL": 0, "BEAR": 0, "NEUT": 0, "N/A": 0}
    for f in result_factors:
        cv = f["current_value"]
        hbo = f.get("higher_bullish")
        if cv is None:
            signals["N/A"] += 1
            continue
        pct = f["percentile"]
        if hbo is True:
            if pct >= 70:
                signals["BULL"] += 1
            elif pct <= 30:
                signals["BEAR"] += 1
            else:
                signals["NEUT"] += 1
        elif hbo is False:
            if pct >= 70:
                signals["BEAR"] += 1
            elif pct <= 30:
                signals["BULL"] += 1
            else:
                signals["NEUT"] += 1
        else:
            # 无方向性因子（STD/RSQR）：极端值 = 特殊状态
            if pct >= 90 or pct <= 10:
                signals["NEUT"] += 1  # 极端波动/趋势质量标记为中性但特殊
            else:
                signals["NEUT"] += 1

    # 整体技术面评级
    active = 6 - signals["N/A"]
    if active > 0:
        bull_ratio = signals["BULL"] / active
        bear_ratio = signals["BEAR"] / active
        if bull_ratio >= 0.6:
            overall = "BULLISH"
        elif bear_ratio >= 0.6:
            overall = "BEARISH"
        else:
            overall = "MIXED"
    else:
        overall = "INSUFFICIENT_DATA"

    return {
        "ticker": ticker,
        "name": name,
        "window": window,
        "data_points": len(df),
        "latest_date": str(df.index[-1].date()) if len(df) > 0 else None,
        "fetched_at": datetime.now().isoformat(),
        "factors": result_factors,
        "signal_summary": {
            "bull": signals["BULL"],
            "bear": signals["BEAR"],
            "neut": signals["NEUT"],
            "na": signals["N/A"],
            "overall": overall,
        },
    }


# ── CLI ───────────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="fengtechnicals — Qlib Alpha158 六因子技术分析",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python fengtechnicals.py 0700.HK              # 单只分析
  python fengtechnicals.py 0700.HK AAPL MSFT    # 批量分析
  python fengtechnicals.py 0700.HK --window 30  # 30 日窗口
  python fengtechnicals.py 0700.HK --factor ROC # 只看单因子
""",
    )
    parser.add_argument("tickers", nargs="+", help="一个或多个 ticker 代码")
    parser.add_argument("--window", "-w", type=int, default=20,
                        help="滚动窗口大小（默认 20）")
    parser.add_argument("--days", "-d", type=int, default=300,
                        help="获取历史数据天数（默认 300）")
    parser.add_argument("--factor", "-f", choices=ALL_FACTORS, default=None,
                        help="只计算指定因子（默认全部）")
    parser.add_argument("--json", action="store_true", default=True,
                        help="JSON 输出（默认）")
    parser.add_argument("--no-json", dest="json", action="store_false",
                        help="禁用 JSON，输出表格")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    # 支持逗号分隔（0700.HK,0005.HK）和空格分隔（0700.HK 0005.HK）两种写法
    tickers = []
    for t in args.tickers:
        tickers.extend([x.strip().upper() for x in t.split(",") if x.strip()])
    window = args.window
    days = args.days
    target_factors = [args.factor] if args.factor else ALL_FACTORS

    results = []
    errors = []

    for ticker in tickers:
        try:
            # 获取数据
            df = fetch_data(ticker, days=days)
            name = get_name(ticker)

            # 计算全部因子
            all_factors = compute_factors(df, window=window)

            # 如果只要单因子，过滤
            if args.factor:
                filtered = {k: v for k, v in all_factors.items() if k in target_factors}
            else:
                filtered = all_factors

            # 格式化输出（传入目标因子列表，只输出用户要的）
            result = format_result(ticker, name, all_factors, df, window,
                                   target_factors=target_factors)
            results.append(result)

        except Exception as e:
            errors.append({"ticker": ticker, "error": str(e)})

    # 输出
    if args.json:
        output = {
            "tool": "fengtechnicals",
            "version": "1.0.0",
            "source": "Qlib Alpha158 (pure pandas reimplementation)",
            "tickers_analyzed": len(results),
            "results": results,
        }
        if errors:
            output["errors"] = errors
        print(json.dumps(output, indent=2, ensure_ascii=False, default=str))
    else:
        # 表格输出
        for r in results:
            print(f"\n{'='*60}")
            print(f"  {r['ticker']} ({r['name']})  窗口={r['window']}  数据={r['data_points']}天")
            print(f"  最新日期: {r['latest_date']}")
            print(f"{'='*60}")
            print(f"{'因子':<8} {'标签':<10} {'当前值':>12} {'分位数%':>8} {'均值':>12} {'信号':>8}")
            print(f"{'-'*60}")
            for f in r["factors"]:
                cv = f["current_value"]
                pct = f["percentile"]
                hbo = f.get("higher_bullish")
                # 判断信号
                if cv is None:
                    sig = "N/A"
                elif hbo is True:
                    sig = "BULL" if pct >= 70 else ("BEAR" if pct <= 30 else "NEUT")
                elif hbo is False:
                    sig = "BEAR" if pct >= 70 else ("BULL" if pct <= 30 else "NEUT")
                else:
                    sig = "NEUT"

                cv_str = f"{cv:.4f}" if cv is not None else "N/A"
                pct_str = f"{pct:.1f}" if pct is not None else "N/A"
                mean_str = f"{f['mean']:.4f}" if f["mean"] is not None else "N/A"
                print(f"{f['factor']:<8} {f['label']:<10} {cv_str:>12} {pct_str:>8} {mean_str:>12} {sig:>8}")
            print(f"\n  整体技术面: {r['signal_summary']['overall']}")
            print(f"  BULL={r['signal_summary']['bull']} BEAR={r['signal_summary']['bear']} "
                  f"NEUT={r['signal_summary']['neut']} N/A={r['signal_summary']['na']}")

        if errors:
            print(f"\n{'='*60}")
            print("  错误:")
            for e in errors:
                print(f"  {e['ticker']}: {e['error']}")

    # 退出码
    sys.exit(1 if errors and not results else 0)


if __name__ == "__main__":
    main()
