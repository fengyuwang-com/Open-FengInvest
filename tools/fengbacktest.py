#!/usr/bin/env python3
"""
FengInvest 组合回测引擎（信号驱动 · 日频 · 零依赖 stdlib）

设计移植：
- vnpy 4.x alpha 信号驱动范式：预测（目标权重）与执行（再平衡）分离，
  策略只消费"目标权重表"，引擎负责撮合与盯市；
- ai-hedge-fund fund 级回测：rebalance 网格由基准实际 bar 推导（自动剔除
  非交易日）、NAV 曲线、周期收益 Sharpe、与基准等比对比；
- Qlib Exchange 成本模型（简化版）：手续费 + 滑点比例。

用法：
  python tools/fengbacktest.py --tickers 0700.HK,600036.SS --weights 0.5,0.5 \
      --rebalance monthly --start 2024-01-01 --end 2026-08-01 --benchmark 000300.SS \
      [--execution-lag 1] [--report]

数据源：本地 data/market_data.db（daily_data 表），免联网。
输出：stdout 单 JSON（指标 + NAV 曲线 + 每期交易记录）；--report 时另附 quantstats 指标与
      data/reports/backtest_<时间戳>.html（可选依赖，未安装则跳过不失败）。
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "data", "market_data.db")

# 共享论断引擎（backtest_core）：实证/显著性走共享库；缺失时功能降级不崩
try:
    import backtest_core
except Exception:
    backtest_core = None

# 成本模型（Qlib exchange 默认值的简化版）
FEE_RATE = 0.0015     # 单边佣金+规费比例
SLIPPAGE = 0.001      # 滑点比例


def load_closes(tickers):
    """从本地 DB 读收盘价序列。返回 {ticker: {date: close}}，失败标 None。"""
    if not os.path.exists(DB):
        return None
    con = sqlite3.connect(DB)
    out = {}
    for t in tickers:
        base = t.split(".")[0]
        cands = [t.upper(), t.upper().replace(".", ""), base]
        rows = con.execute(
            "SELECT d.date, d.close FROM daily_data d JOIN indices i ON d.index_id=i.id "
            "WHERE i.ticker=? OR i.ticker=? OR i.ticker=? ORDER BY d.date",
            (cands[0], cands[1], cands[2])
        ).fetchall()
        clean = [(d, c) for d, c in rows if c]
        if len(clean) >= 30:
            out[t] = dict(clean)
    con.close()
    return out


def rebalance_grid(dates, freq):
    """由基准实际 bar 推导再平衡日（vnpy/ai-hedge-fund 思路）：月末/季末/年末最后交易日。
    none = 期初一次建仓后买入持有（grid 只含首日）。"""
    if freq == "none":
        return [dates[0]]
    grid = []
    prev_key = None
    for d in dates:
        dt = datetime.strptime(d, "%Y-%m-%d")
        if freq == "monthly":
            key = (dt.year, dt.month)
        elif freq == "quarterly":
            key = (dt.year, (dt.month - 1) // 3)
        elif freq == "yearly":
            key = (dt.year,)
        else:
            return []
        if key != prev_key:
            prev_key = key
            grid.append(d)  # 每周期第一个交易日即再平衡日
    return grid


def _price_limit(ticker):
    """A股涨跌停限幅（Qlib Exchange 过滤思路，简化版）：
    主板 ±10%、创业板(300/301)/科创板(688/689) ±20%；港美股无涨跌停 → None。
    ST ±5% 无法从代码判定，不做（已知限制）。"""
    t = ticker.upper()
    if t.endswith(".SS"):
        return 0.20 if t.startswith(("688", "689")) else 0.10
    if t.endswith(".SZ"):
        return 0.20 if t.startswith(("300", "301")) else 0.10
    return None


def load_volumes(tickers):
    """从本地 DB 读日成交量（冲击成本模型用）。返回 {ticker: {date: volume}}。"""
    if not os.path.exists(DB):
        return {}
    con = sqlite3.connect(DB)
    out = {}
    for t in tickers:
        base = t.split(".")[0]
        cands = [t.upper(), t.upper().replace(".", ""), base]
        rows = con.execute(
            "SELECT d.date, d.volume FROM daily_data d JOIN indices i ON d.index_id=i.id "
            "WHERE i.ticker=? OR i.ticker=? OR i.ticker=? ORDER BY d.date",
            (cands[0], cands[1], cands[2])
        ).fetchall()
        clean = [(d, v) for d, v in rows if v]
        if clean:
            out[t] = dict(clean)
    con.close()
    return out


# quantstats 报告字段映射（reports.metrics 输出行名 → 规范键）
_QS_KEYMAP = {
    "Cumulative Return": "cumulative_return",
    "CAGR﹪": "cagr",
    "Sharpe": "sharpe",
    "Sortino": "sortino",
    "Sortino/√2": "sortino_sqrt2",
    "Omega": "omega",
    "Max Drawdown": "max_drawdown",
    "Longest DD Days": "longest_dd_days",
    "Volatility (ann.)": "volatility",
    "Calmar": "calmar",
    "Skew": "skew",
    "Kurtosis": "kurtosis",
    "Win Days": "win_rate",
    "Avg. Return": "avg_return",
    "Avg. Win": "avg_win",
    "Avg. Loss": "avg_loss",
    "Best Day": "best_day",
    "Worst Day": "worst_day",
    "Daily Value-at-Risk": "daily_var",
    "Expected Shortfall (cVaR)": "cvar",
    "Gain/Pain Ratio": "gain_pain_ratio",
    "Payoff Ratio": "payoff_ratio",
    "Profit Factor": "profit_factor",
    "Tail Ratio": "tail_ratio",
}

# 百分比口径字段（decimal → %，×100）；其余为比值/整数
_QS_PCT_FIELDS = {"cumulative_return", "cagr", "volatility", "max_drawdown",
                  "avg_return", "avg_win", "avg_loss", "best_day", "worst_day",
                  "daily_var", "cvar", "win_rate"}


def quantstats_report(nav_curve):
    """quantstats 报告层（可选依赖）：返回指标 JSON dict + HTML 路径。

    - quantstats 未安装 → 打印 "quantstats not installed, --report skipped"，返回 None（不失败）
    - 归一化坑：净值必须首日=1（/nav[0]）再传入；若全程 ≤1 则改传收益率序列，
      避免被 quantstats 误判为收益率
    - HTML 生成失败仅打印 warning，不影响主结果
    """
    try:
        import quantstats as qs
        import pandas as pd
    except ImportError:
        print("quantstats not installed, --report skipped")
        return None
    try:
        dates = [x["date"] for x in nav_curve]
        nav = pd.Series([x["nav"] for x in nav_curve], index=pd.to_datetime(dates))
        norm = nav / nav.iloc[0]                      # 归一化：首日 = 1（quantstats 识别净值的坑：base 必须 ≥1）
        # 注意：quantstats 0.0.81 的 reports.metrics 部分字段直接取原始输入
        # （价格序列会被当作收益率误算），故统一传「归一化净值的日收益率序列」——
        # 属任务允许的两种输入形式之一，规避误判。
        series = norm.pct_change().dropna()
        mt = qs.reports.metrics(series, display=False, mode="full")
        row = mt["Strategy"] if "Strategy" in mt.columns else mt.iloc[:, 0]
        out = {}
        for qk, ck in _QS_KEYMAP.items():
            if qk not in row.index:
                continue
            v = row[qk]
            if v is None or (isinstance(v, str) and v.strip() in ("", "-")):
                out[ck] = None
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                out[ck] = str(v)
                continue
            if fv != fv or abs(fv) == float("inf"):
                out[ck] = None
                continue
            if ck in _QS_PCT_FIELDS:
                fv = fv * 100                         # decimal → %
            elif ck == "longest_dd_days":
                fv = int(round(fv))
            out[ck] = round(fv, 4)
        # 可选 HTML 报告（失败仅 warning）
        try:
            out_dir = os.path.join(BASE, "data", "reports")
            os.makedirs(out_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            html_path = os.path.join(out_dir, f"backtest_{ts}.html")
            qs.reports.html(series, title=f"FengInvest Backtest {ts}", output=html_path)
            out["html"] = html_path
        except Exception as e:
            print(f"warning: quantstats HTML 报告生成失败: {e}")
            out["html"] = None
        out["note"] = ("quantstats.reports.metrics（mode=full）；输入=归一化净值（首日=1）的日收益率序列；"
                       "百分比字段单位为 %，比值字段原样")
        return out
    except Exception as e:
        print(f"warning: quantstats 指标计算失败: {e}")
        return None


def backtest(tickers, weights, freq, start, end, benchmark,
             impact=0.0, capital=1000000.0, use_limit=True,
             execution_lag=0, report=False, sig_csv=None):
    # 基准一并加载（可选：DB 无基准数据时基准曲线/超额为 null，不报错）
    load_list = tickers + ([benchmark] if benchmark else [])
    closes = load_closes(load_list)
    if closes is None:
        print(json.dumps({"error": "data/market_data.db 不存在，无法回测（需先构建数据库）"}, indent=2, ensure_ascii=False))
        return 1
    missing = [t for t in tickers if t not in closes]
    if missing:
        print(json.dumps({"error": f"以下标的在本地 DB 无数据（缺失 {len(missing)} 只）: {missing}"}, indent=2, ensure_ascii=False))
        return 1

    # 时间轴 = 所有标的日期并集，限定区间
    all_dates = set()
    for t in tickers:
        all_dates |= set(closes[t].keys())
    if benchmark and benchmark in closes:
        all_dates |= set(closes[benchmark].keys())
    dates = sorted(d for d in all_dates if start <= d <= end)
    if len(dates) < 60:
        print(json.dumps({"error": f"有效交易日不足 60 天（{len(dates)}），检查区间/数据覆盖"}, indent=2, ensure_ascii=False))
        return 1

    n = len(tickers)
    # 冲击成本需要日成交额（--impact 时惰性加载）
    volumes = load_volumes(tickers) if impact > 0 else {}
    limits = [_price_limit(t) for t in tickers]

    def _simulate(grid_set, target_override=None):
        """一次盯市循环（vnpy 信号驱动）：返回 (nav_curve, trades, holding_pnl)。
        target_override: {date: [w1..wn]} — 信号 CSV 模式：该日按 CSV 权重为目标，
        其余日保持当前仓位（仅成交日换仓）。"""
        cash = 1.0                       # 初始资金 1 单位
        shares = [0.0] * n
        nav_curve = []
        trades = []
        blocked = []                     # 被涨跌停拦截的意图（审计：为何未再平衡）
        holding_pnl = 0.0
        prev_close = [None] * n          # flat 填充：各标的上一已知收盘价
        target = list(weights)           # 目标权重（和=1）
        last_target_date = None

        for d in dates:
            # 信号 CSV 模式：到达 CSV 日期 → 更换目标权重（无前视：当日收盘后按 CSV 定目标）
            if target_override and d in target_override:
                target = target_override[d]
                last_target_date = d
            # 当日实际收盘（缺数据 → None，该标的当日不可成交）
            raw = [closes[t].get(d) for t in tickers]
            valid = [p is not None for p in raw]

            # flat 填充（vnpy 对齐）：无价标的盯市用上一已知收盘，不引入前视
            prev_px = list(prev_close)   # 昨日收盘快照（今日盯市起点）
            for i in range(n):
                if raw[i] is not None:
                    prev_close[i] = raw[i]
            prices = [raw[i] if raw[i] is not None else prev_close[i] for i in range(n)]

            # 逐日盯市 PnL 拆分（vnpy PortfolioDailyResult 思路）：
            # holding_pnl = 期初仓位 × (今收 − 昨收)——"论文在赚钱还是交易在赚钱"
            for i in range(n):
                if shares[i] and prev_px[i] is not None and prices[i] is not None:
                    holding_pnl += shares[i] * (prices[i] - prev_px[i])

            # 再平衡日：按收盘价成交 + 成本（现金实收实付；无价标的冻结不动）
            if d in grid_set:
                # 计算当前市值（无价标的按 flat 价盯市，但不可成交）
                mvs = [shares[i] * (prices[i] or 0.0) for i in range(n)]
                equity_now = cash + sum(mvs)
                for i in range(n):
                    if not valid[i] or not prices[i]:
                        continue  # 当日休市/停牌：持仓冻结，不交易
                    # 涨跌停过滤（Qlib Exchange）：涨停买不进 / 跌停卖不出
                    lim = limits[i]
                    if use_limit and lim and prev_px[i]:
                        limit_up = prices[i] >= prev_px[i] * (1 + lim)
                        limit_dn = prices[i] <= prev_px[i] * (1 - lim)
                    else:
                        limit_up = limit_dn = False
                    # 目标市值 = 该标的目标权重 × 当前净值。不做子集归一化：
                    # 缺失标的保持原仓位、偏差留在现金，下一轮双方都有效时纠正
                    want_val = equity_now * target[i]
                    want_shares = want_val / prices[i]
                    delta = want_shares - shares[i]
                    if delta > 0 and limit_up:
                        blocked.append({"date": d, "ticker": tickers[i], "action": "buy", "reason": "limit_up"})
                        continue  # 涨停板买不进，留到下期
                    if delta < 0 and limit_dn:
                        blocked.append({"date": d, "ticker": tickers[i], "action": "sell", "reason": "limit_dn"})
                        continue  # 跌停板卖不出，留到下期
                    if abs(delta) * prices[i] > equity_now * 0.001:  # 免碎单噪音
                        # 成本 = 固定费率+滑点（现状）+ 可选冲击成本二次项
                        # （Qlib: adj = impact × (成交额/日总成交额)²；归一化资金下
                        #   成交额占比极小 → 冲击≈0 属正常，--capital 传真实资金规模）
                        trade_val = abs(delta) * prices[i]
                        cost = trade_val * (FEE_RATE + SLIPPAGE)
                        if impact > 0 and d in volumes.get(tickers[i], {}):
                            daily_val = volumes[tickers[i]][d] * prices[i]
                            if daily_val > 0:
                                ratio = (trade_val * capital) / daily_val
                                cost += trade_val * impact * ratio * ratio
                        trades.append({
                            "date": d, "ticker": tickers[i],
                            "action": "buy" if delta > 0 else "sell",
                            "shares": round(abs(delta), 4),
                            "price": round(prices[i], 4),
                            "cost": round(cost, 6),
                        })
                        cash += -delta * prices[i] - cost  # 卖出收现/买入付现（净额-成本）
                        shares[i] = want_shares

            # 逐日盯市（持仓盈亏=仓位×价差，已累计 holding_pnl）
            mvs = [shares[i] * (prices[i] or 0.0) for i in range(n)]
            equity = cash + sum(mvs)
            nav_curve.append({"date": d, "nav": round(equity, 6)})

        return nav_curve, trades, blocked, holding_pnl

    # 主网格 + 买入持有对照（none 语义：期初一次建仓）
    if sig_csv:
        # 信号 CSV 模式：再平衡日 = CSV 出现的日期 ∩ 数据区间（不在区间内的日期忽略）
        grid_sig = sorted(set(sig_csv["dates"]) & set(dates))
        if not grid_sig:
            print(json.dumps({"error": "sig-csv 日期与区间无交集（检查 --start/--end 与 CSV 日期）"}, indent=2, ensure_ascii=False))
            return 1
        grid = grid_sig
        wmap = sig_csv["weights"]
        target_override = {d: wmap[d] for d in grid_sig if d in wmap}
    else:
        grid = rebalance_grid(dates, freq)
        target_override = None
    if execution_lag > 0:
        # T+1：网格日为「决策日」（信息截止当日收盘），执行顺延至下一交易日。
        # 权重生效日 = 决策日 + 1 交易日；模拟「今天收盘后决策、明天开盘执行」。
        grid_days = set(grid)
        exec_days = []
        for i, d in enumerate(dates):
            if d in grid_days and i + 1 < len(dates):
                exec_days.append(dates[i + 1])
        grid_set = set(exec_days)
        bh_grid_set = set()
        if dates[0] in grid_days and len(dates) > 1:
            bh_grid_set = {dates[1]}
    else:
        grid_set = set(grid)          # 默认（lag=0）：行为完全不变
        bh_grid_set = {dates[0]}
    nav_curve, trades, blocked, holding_pnl = _simulate(grid_set, target_override)
    bh_nav, _, _, _ = _simulate(bh_grid_set)
    bh_ret = bh_nav[-1]["nav"] / bh_nav[0]["nav"] - 1 if len(bh_nav) > 1 else 0.0

    # 基准曲线（等比缩放）
    bench_curve = None
    if benchmark and benchmark in closes:
        bc = closes[benchmark]
        bdates = [d for d in dates if d in bc]
        if bdates:
            b0 = bc[bdates[0]]
            bench_curve = [{"date": d, "nav": round(bc[d] / b0, 6)} for d in bdates]

    # 指标（ai-hedge-fund 周期收益口径）
    navs = [x["nav"] for x in nav_curve]
    rets = [navs[i] / navs[i - 1] - 1 for i in range(1, len(navs))]
    total_ret = navs[-1] / navs[0] - 1
    years = len(dates) / 252
    annual = (1 + total_ret) ** (1 / years) - 1 if years > 0 else 0.0
    sharpe = 0.0
    if rets and len(rets) > 1:
        mean_r = sum(rets) / len(rets)
        sd = (sum((r - mean_r) ** 2 for r in rets) / (len(rets) - 1)) ** 0.5
        if sd > 0:
            sharpe = mean_r / sd * (252 ** 0.5)
    peak = navs[0]
    max_dd = 0.0
    for v in navs:
        peak = max(peak, v)
        dd = v / peak - 1
        max_dd = min(max_dd, dd)

    # 显著性（共享引擎 backtest_core block bootstrap）：策略日收益均值是否显著≠0
    significance = None
    if backtest_core is not None and len(rets) > 5:
        sig = backtest_core.bootstrap_significance(rets, [0.0] * len(rets))
        if sig.get("mean_diff_pp") is not None:
            significance = {
                "method": sig.get("method"),
                "strategy_mean_daily_ret_pp": sig["mean_diff_pp"],
                "ci95_pp": [sig["ci95_low_pp"], sig["ci95_high_pp"]],
                "p_value": sig["p_value"],
                "significant": sig["significant"],
                "note": sig.get("note"),
            }

    # 基准超额
    excess = None
    if bench_curve:
        b_ret = bench_curve[-1]["nav"] / bench_curve[0]["nav"] - 1
        excess = round((total_ret - b_ret) * 100, 2)

    fees = sum(t["cost"] for t in trades)
    # PnL 拆分：holding=持有贡献；trading=残余（再平衡+费用的净影响）
    # vs_buy_and_hold = 再平衡纪律相对买入持有的净值贡献（价值投资低换手纪律的实证）
    holding_pct = holding_pnl / navs[0] * 100
    # quantstats 报告层（可选依赖；未安装/失败 → None 不崩溃）
    qs_report = quantstats_report(nav_curve) if report else None
    note = "日频收盘价撮合 + 佣金0.15% + 滑点0.1%" + (" + 涨跌停过滤" if use_limit else "") + \
           (" + 冲击成本二次项" if impact > 0 else "") + "；PnL 拆分 holding/trading（vnpy）"
    if execution_lag > 0:
        note += f"；execution-lag={execution_lag}（T+1：决策日收盘后、下一交易日执行）"
    if report and qs_report is None:
        note += "；--report 已跳过（quantstats 不可用）"
    result = {
        "tickers": tickers,
        "weights": weights,
        "period": {"start": dates[0], "end": dates[-1], "days": len(dates)},
        "rebalance": freq,
        "execution_lag": execution_lag,
        "significance": significance,
        "benchmark": benchmark,
        "metrics": {
            "total_return_pct": round(total_ret * 100, 2),
            "annual_return_pct": round(annual * 100, 2),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "sharpe": round(sharpe, 2),
            "excess_vs_benchmark_pct": excess,
            "holding_pnl_pct": round(holding_pct, 2),          # 纯持有贡献
            "trading_pnl_pct": round(total_ret * 100 - holding_pct - fees * 100, 2),  # 残余
            "fees_pct": round(fees * 100, 2),
            "vs_buy_and_hold_pct": round((total_ret - bh_ret) * 100, 2),  # 再平衡 vs 买入持有
            "total_fees": round(fees, 4),
        },
        "quantstats": qs_report,
        "trades": trades[-20:],  # 最近 20 笔（完整列表过长）
        "blocked_events": blocked[-20:],
        "blocked_count": len(blocked),
        "trades_count": len(trades),
        "nav_curve": nav_curve[:: max(1, len(nav_curve) // 200)],  # 抽样 ≤200 点
        "benchmark_curve": bench_curve[:: max(1, len(bench_curve) // 200)] if bench_curve else None,
        "note": note,
    }
    return result


def sig_csv_targets(path, tickers):
    """读信号驱动目标权重表（vnpy 信号驱动范式：策略只消费"目标权重表"）。

    CSV 约定（表头）：
      date,ticker,weight
      2024-01-31,0700.HK,0.6
      2024-01-31,600036.SS,0.4
    按 date 分组 → {date: [w_i for ticker_i]}；同一日期内权重自动归一化到 1。
    返回 {date: [w1..wn]}；CSV 里没出现的标的当日权重填 0。
    """
    import csv as _csv
    out = {}
    raw = {}
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in _csv.DictReader(f):
            d = (row.get("date") or "").strip()
            t = (row.get("ticker") or "").strip()
            try:
                w = float(row.get("weight"))
            except (TypeError, ValueError):
                continue
            raw.setdefault(d, {})[t] = w
    for d, ws in raw.items():
        vec = [0.0] * len(tickers)
        s = sum(ws.values())
        for i, t in enumerate(tickers):
            if t in ws and s > 0:
                vec[i] = ws[t] / s
        out[d] = vec
    if not out:
        print(json.dumps({"error": f"sig-csv 无有效行（需 date,ticker,weight 表头）: {path}"}, ensure_ascii=False))
    return out


def run_walkforward(tickers, weights, freq, start, end, benchmark,
                    folds, impact=0.0, capital=1000000.0, use_limit=True,
                    execution_lag=0, report=False):
    """前向验证（吸收 tickflow walkforward 思想）：时间轴切成 folds 段，
    每段独立跑一次 backtest（初始资金 1 单位、不得跨段借用信息），
    输出各段指标 + 跨段汇总（均值/最差），并拼接成一条 OOS 曲线。
    """
    # 用一段长区间把日期序列拉出来（backtest 的时间轴逻辑在函数内，这里复用 load_closes）
    load_list = tickers + ([benchmark] if benchmark else [])
    closes = load_closes(load_list)
    if closes is None:
        print(json.dumps({"error": "data/market_data.db 不存在"}, ensure_ascii=False))
        return 1
    all_dates = set()
    for t in tickers:
        all_dates |= set(closes[t].keys())
    if benchmark and benchmark in closes:
        all_dates |= set(closes[benchmark].keys())
    dates = sorted(d for d in all_dates if start <= d <= end)
    if len(dates) < folds * 5:
        print(json.dumps({"error": f"有效交易日 {len(dates)} 不足以切 {folds} 折（每折至少 5 天）"}, ensure_ascii=False))
        return 1
    n = len(dates)
    seg = (n + folds - 1) // folds
    segs = []
    for k in range(folds):
        s, e = k * seg, min(n, (k + 1) * seg)
        if e - s >= 5:
            segs.append((dates[s], dates[e - 1]))
    runs = []
    for s, e in segs:
        rc = backtest(tickers, weights, freq, s, e, benchmark,
                      impact=impact, capital=capital, use_limit=use_limit,
                      execution_lag=execution_lag, report=report)
        if not isinstance(rc, dict):        # 该段有效交易日不足等 → 跳过
            continue
        runs.append({"segment": [s, e], "days": rc["period"]["days"],
                     "metrics": rc["metrics"],
                     "significance": rc.get("significance")})
    # 汇总（仅回测全程调用 backtest 非 dict 时容错）
    valid = [r for r in runs if r["metrics"]]
    summary = None
    if valid:
        tr = [r["metrics"]["total_return_pct"] for r in valid]
        dd = [r["metrics"]["max_drawdown_pct"] for r in valid]
        summary = {
            "folds": len(valid),
            "total_return_avg_pct": round(sum(tr) / len(tr), 2),
            "total_return_min_pct": min(tr),
            "total_return_max_pct": max(tr),
            "max_drawdown_best_pct": max(dd),
            "max_drawdown_worst_pct": min(dd),
            "segments_positive": sum(1 for x in tr if x > 0),
            "segments_total": len(tr),
        }
    out = {"mode": "walkforward", "folds": len(segs), "start": start, "end": end,
           "tickers": tickers, "segments": runs, "summary": summary,
           "note": "每段独立初始资金 1 单位回测，段间无信息泄露；指标为各段口径，拼接 OOS 曲线需自行按段内天数加权"}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def run_grid(tickers, weights, start, end, benchmark,
             rebalances=("monthly",), execution_lags=(0,), impacts=(0.0,),
             capital=1000000.0, use_limit=True, report=False):
    """参数网格扫描（吸收 tickflow 网格思想）：rebalance × execution-lag × impact
    三轴全组合，每个组合跑一次 backtest，输出指标矩阵 + 最佳组合。
    """
    import itertools
    combos = list(itertools.product(rebalances, execution_lags, impacts))
    rows = []
    best = None
    for freq, lag, imp in combos:
        rc = backtest(tickers, weights, freq, start, end, benchmark,
                      impact=imp, capital=capital, use_limit=use_limit,
                      execution_lag=lag, report=report)
        if not isinstance(rc, dict):
            continue
        m = rc["metrics"]
        row = {"rebalance": freq, "execution_lag": lag, "impact": imp,
               "total_return_pct": m["total_return_pct"],
               "annual_return_pct": m["annual_return_pct"],
               "max_drawdown_pct": m["max_drawdown_pct"],
               "sharpe": m["sharpe"],
               "excess_vs_benchmark_pct": m["excess_vs_benchmark_pct"],
               "vs_buy_and_hold_pct": m["vs_buy_and_hold_pct"]}
        rows.append(row)
        if best is None or (row["sharpe"] or -9) > (best["sharpe"] or -9):
            best = row
    out = {"mode": "grid", "start": start, "end": end, "tickers": tickers,
           "combos_tested": len(combos), "combos_succeeded": len(rows),
           "axis": {"rebalance": list(rebalances), "execution_lag": list(execution_lags),
                    "impact": list(impacts)},
           "results": rows,
           "best_by_sharpe": best,
           "note": "网格遍历（各组合独立回测），best 取 Sharpe 最高；如需换指标改 run_grid"}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def run_sig_csv(tickers, weights, weight_map, start, end, benchmark,
                capital=1000000.0, use_limit=True, execution_lag=0, report=False):
    """信号 CSV 驱动回测：weight_map = {date: [w1..wn]}（来自 --sig-csv）。
    在 CSV 出现的日期上按 CSV 权重再平衡（覆盖 --weights/--rebalance），
    其余日期持有不动；成本/涨跌停/execution-lag 语义与 backtest() 一致。

    返回单次 backtest 结果 dict（含持有-交易 PnL 拆分 + 显著性）。
    """
    # 网格日 = CSV 日期（∩ 数据区间由 backtest 内部过滤）
    grid_dates = sorted(weight_map.keys())
    if not grid_dates:
        print(json.dumps({"error": "sig-csv 无有效日期行"}, ensure_ascii=False))
        return 1
    res = backtest(tickers, weights, "none", start, end, benchmark,
                   impact=0.0, capital=capital, use_limit=use_limit,
                   execution_lag=execution_lag, report=report,
                   sig_csv={"dates": grid_dates, "weights": weight_map})
    if isinstance(res, dict):
        res["mode"] = "sig-csv"
        res["sig_csv"] = {"dates": len(grid_dates), "file_hint": "见 --sig-csv 参数"}
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    return res


def verify_claim(claim_id, out_dir=None):
    """论断复测：委派给 tools/fengverify.py（唯一复测实现），保住单一事实源/同一 schema。"""
    script = os.path.join(BASE, "tools", "fengverify.py")
    if not os.path.exists(script):
        print(json.dumps({"error": f"复测引擎缺失: {script}"}, indent=2, ensure_ascii=False))
        return 1
    cmd = [sys.executable, script, str(claim_id)]
    if out_dir:
        cmd += ["--out", out_dir]
    try:
        r = subprocess.run(cmd, cwd=BASE)
        return r.returncode
    except Exception as e:
        print(json.dumps({"error": f"调用 fengverify 失败: {e}"}, indent=2, ensure_ascii=False))
        return 1


def main():
    # verify 子命令：论断复测（复用 fengverify 引擎，schema 与白话卡一致）
    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        vap = argparse.ArgumentParser(prog="fengbacktest verify", description="论断复测（复用 fengverify 引擎）")
        vap.add_argument("claim_id", help="论断编号（000-claims-def.md；当前实现 #1）")
        vap.add_argument("--out", default=None, help="输出目录（默认 fengverify 的 RETEST 自动目录）")
        va = vap.parse_args(sys.argv[2:])
        return verify_claim(va.claim_id, va.out)

    ap = argparse.ArgumentParser(description="FengInvest 组合回测（信号驱动）")
    ap.add_argument("--tickers", required=True, help="逗号分隔标的，如 0700.HK,600036.SS")
    ap.add_argument("--weights", default=None, help="逗号分隔权重（默认等权）")
    ap.add_argument("--rebalance", default="monthly", choices=["none", "monthly", "quarterly", "yearly"])
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--end", default="2026-08-01")
    ap.add_argument("--benchmark", default="000300.SS", help="基准（默认沪深300）")
    ap.add_argument("--impact", type=float, default=0.0,
                    help="冲击成本系数（Qlib 二次项，默认 0=关闭；需 --capital 配合）")
    ap.add_argument("--capital", type=float, default=1000000.0, help="真实资金规模（冲击成本模型用，默认 100 万）")
    ap.add_argument("--no-limit", action="store_true", help="关闭 A 股涨跌停过滤")
    ap.add_argument("--execution-lag", type=int, default=0,
                    help="执行延迟交易日数（1 = T+1：决策日收盘后、下一交易日执行；默认 0 当日执行）")
    ap.add_argument("--report", action="store_true",
                    help="生成 quantstats 报告（metrics JSON + data/reports HTML，需已安装 quantstats）")
    # 员工L三参数（吸收 tickflow walkforward/网格思想）
    ap.add_argument("--sig-csv", default=None,
                    help="信号驱动目标权重表 CSV（date,ticker,weight 表头；覆盖 --weights/--rebalance 网格）")
    ap.add_argument("--walkforward-fold", type=int, default=0,
                    help="前向验证折数（>0 时按折分段独立回测，输出各段+汇总，忽略 --execution-lag 组合语义）")
    ap.add_argument("--grid", default=None,
                    help="参数网格扫描，格式 'rebalance:月频列表;lag:逗号列表;impact:逗号列表'，"
                         "如 --grid 'rebalance:monthly,quarterly;lag:0,1;impact:0,0.01'")
    args = ap.parse_args()

    tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
    if not tickers:
        print(json.dumps({"error": "未指定标的(不合法: 空)"}, indent=2, ensure_ascii=False))
        return 1
    if args.weights:
        weights = [float(w) for w in args.weights.split(",")]
        if len(weights) != len(tickers):
            print(json.dumps({"error": "weights 数量与 tickers 不一致"}, ensure_ascii=False))
            return 1
        s = sum(weights)
        weights = [w / s for w in weights]
    else:
        weights = [1.0 / len(tickers)] * len(tickers)

    weight_map = None
    if args.sig_csv:
        weight_map = sig_csv_targets(args.sig_csv, tickers)

    # ---- 网格扫描（--grid）：三轴全组合 ----
    if args.grid:
        import re as _re
        axis = {"rebalance": ["monthly"], "lag": [0], "impact": [0.0]}
        for part in args.grid.split(";"):
            part = part.strip()
            if not part:
                continue
            m = _re.match(r"(\w+):(.+)", part)
            if not m:
                print(json.dumps({"error": f"--grid 段格式错误: {part}（需 key:v1,v2）"}, ensure_ascii=False))
                return 1
            key, vals = m.group(1), m.group(2)
            items = [x.strip() for x in vals.split(",") if x.strip()]
            if key == "rebalance":
                bad = [x for x in items if x not in ("none", "monthly", "quarterly", "yearly")]
                if bad:
                    print(json.dumps({"error": f"--grid rebalance 非法值: {bad}"}, ensure_ascii=False))
                    return 1
                axis["rebalance"] = items
            elif key in ("lag", "execution-lag", "execution_lag"):
                axis["lag"] = [int(x) for x in items]
            elif key == "impact":
                axis["impact"] = [float(x) for x in items]
            else:
                print(json.dumps({"error": f"--grid 未知轴: {key}（支持 rebalance/lag/impact）"}, ensure_ascii=False))
                return 1
        if weight_map is not None:
            print(json.dumps({"error": "--grid 与 --sig-csv 互斥（网格扫描基于固定目标权重）"}, ensure_ascii=False))
            return 1
        return run_grid(tickers, weights, args.start, args.end, args.benchmark,
                        rebalances=tuple(axis["rebalance"]), execution_lags=tuple(axis["lag"]),
                        impacts=tuple(axis["impact"]), capital=args.capital,
                        use_limit=not args.no_limit, report=args.report)

    # ---- 前向验证（--walkforward-fold） ----
    if args.walkforward_fold > 0:
        if weight_map is not None:
            print(json.dumps({"error": "--walkforward-fold 与 --sig-csv 暂不组合（先各跑各）"}, ensure_ascii=False))
            return 1
        # 网格/组合均使用统一 backtest 引擎（flag 已下传）
        return run_walkforward(tickers, weights, args.rebalance, args.start, args.end,
                               args.benchmark, args.walkforward_fold,
                               impact=args.impact, capital=args.capital,
                               use_limit=not args.no_limit, execution_lag=args.execution_lag,
                               report=args.report)

    # ---- 信号 CSV 驱动（--sig-csv）：覆盖权重与网格 ----
    if weight_map is not None:
        return run_sig_csv(tickers, weights, weight_map, args.start, args.end, args.benchmark,
                           capital=args.capital, use_limit=not args.no_limit,
                           execution_lag=args.execution_lag, report=args.report)

    result = backtest(tickers, weights, args.rebalance, args.start, args.end, args.benchmark,
                      impact=args.impact, capital=args.capital, use_limit=not args.no_limit,
                      execution_lag=args.execution_lag, report=args.report)
    if isinstance(result, dict):
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    return result  # 1：backtest 内已打印错误 JSON


if __name__ == "__main__":
    sys.exit(main())
