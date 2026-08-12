#!/usr/bin/env python3
"""leftright.py — 左侧买入 vs 右侧买入回测 (多角度增强版)

定义:
  左信号: 收盘价 <= 52周高点 × (1 - 跌幅阈值), 默认 30%
  右信号: 收盘价上穿 N 日线（前一日低于, 当日高于或等于）

用法:
  python tools/leftright.py                           # 默认全市场全参数
  python tools/leftright.py --market CN               # 仅 A 股
  python tools/leftright.py --quick                   # 快速模式（少参数）
  python tools/leftright.py --output results.json     # 保存结果 JSON
  python tools/leftright.py --stock 0700.HK           # 单股票分析
"""

import sqlite3, sys, os, json, argparse, time, math
from pathlib import Path
from collections import defaultdict

DB = Path(__file__).parent.parent / "data" / "market_data.db"
OUT_DIR = Path(__file__).parent.parent / "research" / "050-strategies" / "leftright"

MARKET_LABELS = {"CN": "A股", "HK": "港股", "US": "美股", "JP": "日本",
                 "UK": "英国", "KR": "韩国", "IN": "印度", "TW": "台湾",
                 "AU": "澳洲", "SG": "新加坡", "CA": "加拿大", "DE": "德国",
                 "FR": "法国", "CH": "瑞士", "NL": "荷兰", "ES": "西班牙",
                 "IT": "意大利", "SE": "瑞典", "NZ": "新西兰"}

# ── 默认参数网格 ──
LEFT_DD = [0.15, 0.20, 0.30, 0.40, 0.50]   # 左侧跌幅阈值
RIGHT_MA = [50, 100, 200]                    # 右侧均线周期
HOLD_DAYS = [20, 63, 126, 252]              # 1月 / 3月 / 6月 / 12月
HOLD_LABELS = {20: "1M", 63: "3M", 126: "6M", 252: "12M"}


def get_stocks(conn, markets=None, ticker=None, incl_idx=False):
    """取股票列表。markets 为列表/None/ticker"""
    cats = ["'stock'"]
    if incl_idx:
        cats += ["'etf'", "'index'"]
    cat_sql = f"category IN ({','.join(cats)})"

    if ticker:
        cur = conn.execute(
            f"SELECT id, ticker, name, market, category FROM indices WHERE ticker=? AND {cat_sql}",
            (ticker.upper(),))
        return [dict(r) for r in cur.fetchall()]

    if markets:
        parts = []
        for m in markets:
            cur = conn.execute(
                f"SELECT id, ticker, name, market, category FROM indices WHERE market=? AND {cat_sql}",
                (m.upper(),))
            parts.extend(dict(r) for r in cur.fetchall())
        return parts

    cur = conn.execute(f"SELECT id, ticker, name, market, category FROM indices WHERE {cat_sql}")
    return [dict(r) for r in cur.fetchall()]


def fetch_ohlc(conn, stock_id, min_records=300):
    """取收盘价历史，返回 [(date, close), ...]"""
    cur = conn.execute(
        "SELECT date, close FROM daily_data WHERE index_id=? AND close IS NOT NULL ORDER BY date",
        (stock_id,))
    rows = cur.fetchall()
    return rows if len(rows) >= min_records else None


def compute_indicators(rows, ma_period):
    """计算每个交易日的 252日高点 和 ma_period 日均线。
    返回 [(date, close, high_252, ma), ...]
    """
    closes = [r[1] for r in rows]
    result = []
    for i, (date, close) in enumerate(rows):
        high_252 = max(closes[max(0, i - 251):i + 1]) if i >= 251 else None
        ma = sum(closes[i - ma_period + 1:i + 1]) / ma_period if i >= ma_period - 1 else None
        result.append((date, close, high_252, ma))
    return result


def find_signals_left(data, drawdown):
    """左侧信号: close <= 高点的 (1 - drawdown)"""
    sigs = []
    for i, (date, close, high_252, _ma) in enumerate(data):
        if high_252 is not None and close <= high_252 * (1 - drawdown):
            sigs.append((i, date, close))
    return sigs


def find_signals_right(data, ma_period):
    """右侧信号: close 上穿 MA (昨日低于, 今日高于等于)"""
    sigs = []
    for i, (date, close, _high, ma) in enumerate(data):
        if i < ma_period:  # 确保有前一日数据
            continue
        prev_close = data[i - 1][1]
        prev_ma = data[i - 1][3]
        if prev_ma is not None and prev_close < prev_ma and close >= ma:
            sigs.append((i, date, close))
    return sigs


def forward_returns(data, start_idx, hold_days_list):
    """计算多个持有期的 forward return"""
    return {
        hd: (data[start_idx + hd][1] - data[start_idx][1]) / data[start_idx][1]
        if start_idx + hd < len(data) and data[start_idx][1] else None
        for hd in hold_days_list
    }


def compute_metrics(returns):
    """从收益列表计算各种指标"""
    if not returns or len(returns) < 2:
        return None
    n = len(returns)
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]
    win_rate = len(wins) / n
    avg_ret = sum(returns) / n
    max_dd = min(returns)
    # 年化因子 (250 交易日)
    ann_factor = math.sqrt(250)
    mean_r = sum(returns) / n
    std_r = math.sqrt(sum((r - mean_r) ** 2 for r in returns) / n) if n > 1 else 0
    sharpe = (mean_r * ann_factor / std_r * ann_factor) if std_r > 0 else 0
    # 假设 2% 无风险年化, 则日无风险 = 0.02 / 250
    rf_daily = 0.02 / 250
    excess = [r - rf_daily for r in returns]
    mean_ex = sum(excess) / n
    std_ex = math.sqrt(sum((x - mean_ex) ** 2 for x in excess) / n) if n > 1 else 0
    sharpe_ex = (mean_ex / std_ex * ann_factor) if std_ex > 0 else 0
    # 盈亏比
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')
    return {
        "count": n,
        "win_rate": round(win_rate, 4),
        "avg_return": round(avg_ret, 6),
        "median_return": round(sorted(returns)[n // 2], 6),
        "max_return": round(max(returns), 6),
        "max_loss": round(min(returns), 6),
        "std": round(std_r, 6),
        "sharpe": round(sharpe_ex, 4),
        "avg_win": round(avg_win, 6) if wins else 0,
        "avg_loss": round(avg_loss, 6) if losses else 0,
        "profit_factor": round(profit_factor, 4) if profit_factor != float('inf') else None,
        "total_return": round(sum(returns), 6),
    }


def run_stock(conn, stock, left_drawdowns, right_mas, hold_days, window_size=0):
    """对单个股票运行左右信号回测，返回各参数组合的结果"""
    rows = fetch_ohlc(conn, stock["id"])
    if rows is None:
        return None

    result = {"ticker": stock["ticker"], "market": stock["market"],
              "name": stock["name"], "category": stock.get("category", "stock")}

    # 每个左侧参数
    for dd in left_drawdowns:
        data = compute_indicators(rows, 200)  # 计算指标依赖MA，用200
        sigs = find_signals_left(data, dd)
        if not sigs:
            continue
        frs = [forward_returns(data, idx, hold_days) for idx, _, _ in sigs]
        key = f"L_{dd:.2f}"
        result[key] = {"signal_count": len(sigs)}
        for hd in hold_days:
            vals = [fr[hd] for fr in frs if fr[hd] is not None]
            m = compute_metrics(vals)
            if m:
                result[key][HOLD_LABELS[hd]] = m

    # 每个右侧参数
    for ma in right_mas:
        data = compute_indicators(rows, ma)
        sigs = find_signals_right(data, ma)
        if not sigs:
            continue
        frs = [forward_returns(data, idx, hold_days) for idx, _, _ in sigs]
        key = f"R_{ma}"
        result[key] = {"signal_count": len(sigs)}
        for hd in hold_days:
            vals = [fr[hd] for fr in frs if fr[hd] is not None]
            m = compute_metrics(vals)
            if m:
                result[key][HOLD_LABELS[hd]] = m

    return result


def aggregate_metrics(metrics_list):
    """合并多个 metrics dict，返回汇总统计"""
    if not metrics_list:
        return None
    # 展平: 收集所有有效的收益数据
    # metrics_list 已经是 compute_metrics 的输出
    return metrics_list  # 直接返回列表，由调用方处理


def collect_results(results):
    """收集所有股票结果，按参数组合汇总"""
    by_market = defaultdict(list)
    by_param = defaultdict(lambda: defaultdict(list))
    pairwise = defaultdict(list)  # 配对比较: stock -> {L: [rets], R: [rets]}

    for r in results:
        if r is None:
            continue
        mkt = r["market"]
        by_market[mkt].append(r)

        # 收集信号密度
        has_left = any(k.startswith("L_") for k in r if k not in ("ticker", "market", "name", "category"))
        has_right = any(k.startswith("R_") for k in r if k not in ("ticker", "market", "name", "category"))

        if has_left and has_right:
            pairwise[r["ticker"]] = {"market": mkt, "name": r["name"], "left": [], "right": []}

        for k, v in r.items():
            if k in ("ticker", "market", "name", "category"):
                continue
            by_param[k][mkt].append(v)

    return dict(by_market), dict(by_param), dict(pairwise)


def compute_sweep_summary(by_param, hold_label="3M"):
    """参数扫描汇总表"""
    sweep = []
    for param, market_dict in sorted(by_param.items()):
        all_hd = {}
        for mkt, items in market_dict.items():
            for item in items:
                if hold_label in item:
                    h = item[hold_label]
                    for k, v in h.items():
                        all_hd.setdefault(k, []).append(v)
        summary = {"param": param}
        for k, vals in all_hd.items():
            clean = [v for v in vals if v is not None]
            if clean:
                summary[f"avg_{k}"] = round(sum(clean) / len(clean), 4)
            else:
                summary[f"avg_{k}"] = None
        sweep.append(summary)
    return sweep


def win_loss_summary(vals):
    """简化胜率"""
    if not vals:
        return None
    wins = sum(1 for v in vals if v > 0)
    return {"count": len(vals), "win_rate": round(wins / len(vals), 4),
            "avg": round(sum(vals) / len(vals), 6)}


def main(markets=None, ticker=None, quick=False, incl_idx=True, output=None):
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    left_dds = [0.30] if quick else LEFT_DD
    right_mas = [200] if quick else RIGHT_MA
    hold_days = [63, 252] if quick else HOLD_DAYS

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row

    stocks = get_stocks(conn, markets, ticker, incl_idx)
    if not stocks:
        print("[ERR] No stocks found")
        sys.exit(1)

    print(f"[DATA] {len(stocks)} stocks, "
          f"left_params={left_dds}, right_mas={right_mas}, holds={hold_days}", flush=True)

    stock_results = []
    for i, s in enumerate(stocks):
        r = run_stock(conn, s, left_dds, right_mas, hold_days)
        if r:
            stock_results.append(r)
        if (i + 1) % 200 == 0:
            print(f"  [{i + 1}/{len(stocks)}]", flush=True)

    conn.close()

    if not stock_results:
        print("[ERR] No stocks produced signals")
        sys.exit(1)

    by_market, by_param, pairwise = collect_results(stock_results)
    elapsed = time.time() - t0

    # ── 构建 JSON ──
    result = {
        "meta": {
            "date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "stocks_total": len(stocks),
            "stocks_with_signals": len(stock_results),
            "parameters": {"left_drawdowns": left_dds, "right_mas": right_mas,
                           "hold_days": hold_days, "quick": quick},
            "elapsed_s": round(elapsed, 1),
        },
        "parameter_sweep": compute_sweep_summary(by_param, "3M"),
        "by_market": {},
        "pairwise": {"count": 0, "left_wins": 0, "right_wins": 0},
        "best_params": {},
    }

    # 各市场汇总
    HOLD_LABELS_INV = {"1M": 20, "3M": 63, "6M": 126, "12M": 252}
    for mkt, items in sorted(by_market.items()):
        mkt_label = MARKET_LABELS.get(mkt, mkt)
        mkt_summary = {"stock_count": len(items)}

        for param in sorted(by_param):
            pdata = {}
            for hl_name, hl_days in HOLD_LABELS_INV.items():
                vals = []
                for item in items:
                    if param in item and hl_name in item[param]:
                        vals.append(item[param][hl_name]["avg_return"])
                if vals:
                    pdata[hl_name] = win_loss_summary(vals)
                else:
                    pdata[hl_name] = None
            mkt_summary[param] = pdata

        # 全部信号跨参数聚合
        for hold_label in ["1M", "3M", "6M", "12M"]:
            all_rets = []
            for item in items:
                for k, v in item.items():
                    if k in ("ticker", "market", "name", "category"):
                        continue
                    if hold_label in v:
                        all_rets.extend(v[hold_label].get("avg_return", 0)
                                        for _ in range(v[hold_label].get("count", 0)))
            mkt_summary[f"n_{hold_label}"] = len(all_rets)
            mkt_summary[f"avg_{hold_label}"] = round(sum(all_rets) / len(all_rets), 4) if all_rets else None

        result["by_market"][mkt] = mkt_summary

    # 配对比较
    pair_count = 0
    left_better = 0
    right_better = 0
    for ticker, info in sorted(pairwise.items()):
        pair_count += 1
        item = next((r for r in stock_results if r["ticker"] == ticker), None)
        if item is None:
            continue
        # 比较默认参数 L_0.30 和 R_200 的 3M 收益
        l_key = "L_0.30" if 0.30 in left_dds else f"L_{left_dds[0]:.2f}"
        r_key = "R_200" if 200 in right_mas else f"R_{right_mas[0]}"
        l_ret = item.get(l_key, {}).get("3M", {}).get("avg_return", None) if l_key in item else None
        r_ret = item.get(r_key, {}).get("3M", {}).get("avg_return", None) if r_key in item else None
        if l_ret is not None and r_ret is not None:
            if l_ret > r_ret:
                left_better += 1
            else:
                right_better += 1

    result["pairwise"] = {
        "count": pair_count,
        "left_better": left_better,
        "right_better": right_better,
        "left_pct": round(left_better / max(1, pair_count), 4),
        "right_pct": round(right_better / max(1, pair_count), 4),
    }

    # 最佳参数查找
    best_left = {"drawdown": None, "sharpe": -999}
    best_right = {"ma": None, "sharpe": -999}
    for param, _ in sorted(by_param.items()):
        all_sharpes = []
        for mkt, items in by_market.items():
            for item in items:
                if param in item and "3M" in item[param]:
                    s = item[param]["3M"].get("sharpe")
                    if s is not None:
                        all_sharpes.append(s)
        if not all_sharpes:
            continue
        avg_sharpe = sum(all_sharpes) / len(all_sharpes)
        if param.startswith("L_"):
            dd = float(param.split("_")[1])
            if avg_sharpe > best_left["sharpe"]:
                best_left = {"drawdown": dd, "sharpe": round(avg_sharpe, 4)}
        elif param.startswith("R_"):
            ma = int(param.split("_")[1])
            if avg_sharpe > best_right["sharpe"]:
                best_right = {"ma": ma, "sharpe": round(avg_sharpe, 4)}

    result["best_params"] = {"left_best_drawdown": best_left, "right_best_ma": best_right}

    # ── 打印摘要 ──
    print(f"\n{'=' * 65}")
    print(f"  回测完成: {len(stocks)} 只股票 ({elapsed:.0f}s)")
    print(f"{'=' * 65}")

    for mkt, m in sorted(result["by_market"].items()):
        label = MARKET_LABELS.get(mkt, mkt)
        print(f"\n[{label}] {m['stock_count']} 只股票")
        line = f"  {'参数':<12} {'信号':>5} {'胜率':>6} {'3M均收':>9} {'6M均收':>9} {'12M均收':>9}"
        print(line)
        print("  " + "-" * 55)
        for param in sorted(by_param):
            pm = m.get(param)
            if pm is None:
                continue
            h3 = pm.get("3M")
            h6 = pm.get("6M")
            h12 = pm.get("12M")
            if h3:
                c = h3.get("count", 0)
                wr = h3.get("win_rate", 0)
                a3 = h3.get("avg")
                a6 = h6.get("avg") if h6 else None
                a12 = h12.get("avg") if h12 else None
                print(f"  {param:<12} {c:>5} {wr*100:>5.0f}% "
                      + (f"{a3*100:>+7.2f}% " if a3 is not None else "    --% ")
                      + (f"{a6*100:>+7.2f}% " if a6 is not None else "    --% ")
                      + (f"{a12*100:>+7.2f}%" if a12 is not None else "    --%"))

    # 配对比较
    pc = result["pairwise"]
    print(f"\n{'─' * 65}")
    print(f"  配对比较（同股票左右信号对比）: {pc['count']} 只")
    if pc['count'] > 0:
        print(f"  左侧更好: {pc['left_better']} ({pc['left_pct']*100:.0f}%)")
        print(f"  右侧更好: {pc['right_better']} ({pc['right_pct']*100:.0f}%)")

    # 最佳参数
    print(f"\n  最佳参数:")
    print(f"    左侧最优跌幅: {best_left['drawdown']*100:.0f}%  (夏普={best_left['sharpe']})")
    print(f"    右侧最优均线: {best_right['ma']}日  (夏普={best_right['sharpe']})")

    # ── 保存 ──
    out_path = output or (OUT_DIR / f"results_{time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n[SAVED] {out_path}")

    return result


if __name__ == "__main__":
    if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="左侧 vs 右侧买入回测 (多角度增强版)")
    parser.add_argument("--market", help="市场代码 (CN/HK/US) 或逗号分隔")
    parser.add_argument("--stock", help="单股票 ticker (如 0700.HK)")
    parser.add_argument("--quick", action="store_true", help="快速模式: 少参数")
    parser.add_argument("--no-index", action="store_true", help="不包含指数和 ETF")
    parser.add_argument("--output", "-o", help="输出 JSON 路径")
    args = parser.parse_args()

    mkts = args.market.upper().split(",") if args.market else None
    main(markets=mkts, ticker=args.stock, quick=args.quick,
         incl_idx=not args.no_index, output=args.output)
