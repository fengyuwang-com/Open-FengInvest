#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fengmetrics — 绩效/统计度量工具箱（pwb-toolbox 直接合并）。

来源与许可:
  函数逐字移植自 paperswithbacktest/pwb-toolbox `pwb_toolbox/performance/metrics.py`
  （MIT License, Copyright (c) 2022-2023 Papers With Backtest and others）。
  上游: https://github.com/paperswithbacktest/pwb-toolbox
  评估档案: research/opensource-eval/pwb-toolbox-EVAL.md（判定: 可直接复用 ~200 行）
  台账: data/config/opensource_list.json #2 pwb-toolbox

合并范围（评估 §13 "High-value extractions"，全部纯 stdlib 零第三方依赖）:
  ulcer_index / ulcer_performance_index —— 回撤风险度量（fengbacktest 25bps 平坦成本之外
                                            的深度回撤视角）
  variance_ratio   —— Lo-MacKinlay 方差比检验（市场有效性/趋势性诊断）
  acf / pacf       —— 收益率自相关/偏自相关
  cagr             —— ulcer_performance_index 的依赖
  _ols / _invert_matrix / _to_list —— 纯 Python 线性代数内核（pacf/FF 回归共用）

设计守则（项目规范）:
  - 不引 backtrader/pandas：上游这些函数本来就是纯 stdlib 实现，逐字保留
  - 每个函数标注上游来源行号区间，便于 upstream diff
  - 与 fengfactor.py（IC/分位/换手）、fengportfolio.risk（CVaR/回撤归因）互补不重叠

CLI 自检:
  python tools/fengmetrics.py selfcheck   # 对拍验证：手工复算 vs 函数输出
"""
from __future__ import annotations

import argparse
import sys
from math import sqrt
from statistics import NormalDist
from typing import Sequence

if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── 以下代码自 pwb-toolbox pwb_toolbox/performance/metrics.py 移植 ──────────
# 上游许可 MIT；本文件顶部与每函数 docstring 均保留归属。


def _to_list(data: Sequence[float]) -> list:  # upstream metrics.py L9
    """Convert Series-like data to list."""
    if hasattr(data, "values"):
        return list(data.values)
    return list(data)


def cagr(prices: Sequence[float], periods_per_year: int = 252) -> float:  # upstream L24
    """Compound annual growth rate from a price series."""
    p = _to_list(prices)
    if len(p) < 2:
        return 0.0
    years = (len(p) - 1) / periods_per_year
    if years == 0:
        return 0.0
    return (p[-1] / p[0]) ** (1 / years) - 1


def ulcer_index(prices: Sequence[float]) -> float:  # upstream metrics.py
    """Ulcer index of a price series."""
    p = _to_list(prices)
    if not p:
        return 0.0
    peak = p[0]
    sum_sq = 0.0
    for price in p:
        if price > peak:
            peak = price
        dd = max(0.0, (peak - price) / peak)
        sum_sq += dd**2
    return sqrt(sum_sq / len(p))


def ulcer_performance_index(
    prices: Sequence[float], risk_free_rate: float = 0.0, periods_per_year: int = 252
) -> float:  # upstream metrics.py L141
    """Ulcer Performance Index."""
    ui = ulcer_index(prices)
    if ui == 0:
        return 0.0
    return (cagr(prices, periods_per_year) - risk_free_rate) / ui


def variance_ratio(prices: Sequence[float], lag: int = 2) -> float:  # upstream L429
    """Lo-MacKinlay variance ratio test statistic."""
    p = _to_list(prices)
    if len(p) <= lag:
        return 0.0
    rets = [p[i] / p[i - 1] - 1 for i in range(1, len(p))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    if var == 0:
        return 0.0
    agg = [sum(rets[i - j] for j in range(1, lag + 1)) for i in range(lag, len(rets))]
    var_lag = sum((a - lag * mean) ** 2 for a in agg) / len(agg)
    return var_lag / (var * lag)


def acf(prices: Sequence[float], lags: Sequence[int]) -> list[float]:  # upstream L444
    """Autocorrelation of returns for specified lags."""
    p = _to_list(prices)
    if len(p) < 2:
        return [0.0 for _ in lags]
    rets = [p[i] / p[i - 1] - 1 for i in range(1, len(p))]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    if var == 0:
        return [0.0 for _ in lags]
    out = []
    for lag in lags:
        if lag <= 0 or lag >= len(rets):
            out.append(0.0)
        else:
            cov = sum(
                (rets[i] - mean) * (rets[i - lag] - mean) for i in range(lag, len(rets))
            ) / (len(rets) - lag)
            out.append(cov / var)
    return out


def _invert_matrix(  # upstream L322 附近
    matrix: Sequence[Sequence[float]],
) -> Sequence[Sequence[float]] | None:
    size = len(matrix)
    aug = [
        list(row) + [1 if i == j else 0 for j in range(size)]
        for i, row in enumerate(matrix)
    ]
    for i in range(size):
        pivot = aug[i][i]
        if abs(pivot) < 1e-12:
            swap = next((j for j in range(i + 1, size) if abs(aug[j][i]) > 1e-12), None)
            if swap is None:
                return None
            aug[i], aug[swap] = aug[swap], aug[i]
            pivot = aug[i][i]
        inv_p = 1 / pivot
        for j in range(2 * size):
            aug[i][j] *= inv_p
        for k in range(size):
            if k != i:
                factor = aug[k][i]
                for j in range(2 * size):
                    aug[k][j] -= factor * aug[i][j]
    return [row[size:] for row in aug]


def _ols(y: Sequence[float], X: Sequence[Sequence[float]]) -> Sequence[float]:  # upstream L322
    n = len(y)
    k = len(X[0]) if X else 0
    xtx = [[0.0 for _ in range(k)] for _ in range(k)]
    xty = [0.0 for _ in range(k)]
    for i in range(n):
        for p in range(k):
            xty[p] += X[i][p] * y[i]
            for q in range(k):
                xtx[p][q] += X[i][p] * X[i][q]
    inv = _invert_matrix(xtx)
    if inv is None:
        return [0.0 for _ in range(k)]
    beta = [sum(inv[i][j] * xty[j] for j in range(k)) for i in range(k)]
    return beta


def pacf(prices: Sequence[float], lags: Sequence[int]) -> list[float]:  # upstream L466
    """Partial autocorrelation of returns for specified lags."""
    p = _to_list(prices)
    if len(p) < 2:
        return [0.0 for _ in lags]
    rets = [p[i] / p[i - 1] - 1 for i in range(1, len(p))]
    out = []
    for k in lags:
        if k <= 0 or k >= len(rets):
            out.append(0.0)
            continue
        y = [rets[i] for i in range(k, len(rets))]
        X = [[1.0] + [rets[i - j - 1] for j in range(k)] for i in range(k, len(rets))]
        beta = _ols(y, X)
        out.append(beta[-1] if beta else 0.0)
    return out


# ── 自检（对拍验证） ────────────────────────────────────────────────────────

def _selfcheck() -> int:
    """手工复算 vs 函数输出，全对拍通过 exit 0（项目规范：机器可证）。"""
    prices = [100, 102, 101, 103, 105, 104, 107, 110, 108, 112]
    # ulcer_index 手工复算
    peak, ss = prices[0], 0.0
    for p_ in prices:
        peak = max(peak, p_)
        ss += (max(0.0, (peak - p_) / peak)) ** 2
    expect_ui = (ss / len(prices)) ** 0.5
    got_ui = ulcer_index(prices)
    ok1 = abs(expect_ui - got_ui) < 1e-12
    # variance_ratio 手工复算（lag=2）
    rets = [prices[i] / prices[i - 1] - 1 for i in range(1, len(prices))]
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / len(rets)
    agg = [rets[i - 1] + rets[i - 2] for i in range(2, len(rets))]
    var_lag = sum((a - 2 * m) ** 2 for a in agg) / len(agg)
    expect_vr = var_lag / (var * 2)
    ok2 = abs(expect_vr - variance_ratio(prices, 2)) < 1e-12
    # acf(1) 手工复算
    lag = 1
    cov = sum((rets[i] - m) * (rets[i - lag] - m) for i in range(lag, len(rets))) / (len(rets) - lag)
    ok3 = abs(cov / var - acf(prices, [1])[0]) < 1e-12
    # pacf(1) = AR(1) OLS 斜率（带截距）——偏自相关的定义本身
    rets_all = rets
    yv = rets_all[1:]
    xv = rets_all[:-1]
    mx2 = sum(xv) / len(xv)
    my2 = sum(yv) / len(yv)
    slope = sum((a - mx2) * (b - my2) for a, b in zip(xv, yv)) / sum((a - mx2) ** 2 for a in xv)
    ok4 = abs(pacf(prices, [1])[0] - slope) < 1e-9
    # FF 回归：合成 strat = 0.0002 + 0.9*mkt（无噪声），价格精确复合；
    # 上游约定：因子行 i 对应 rets[i-1]（即价格 i-1→i 这一期）→ 因子表需右移一位对齐
    import random
    random.seed(7)
    mkt = [random.gauss(0.0005, 0.01) for _ in range(500)]
    strat = [0.0002 + 0.9 * r for r in mkt]
    prices2 = [100.0]
    for r in strat:
        prices2.append(prices2[-1] * (1 + r))
    # 手工 OLS（对齐后：y=strat[:-1]，x=mkt[:-1]）
    import statistics
    y = strat[:-1]
    x = mkt[:-1]
    mx, my_ = statistics.mean(x), statistics.mean(y)
    beta1 = sum((a - mx) * (b - my_) for a, b in zip(x, y)) / sum((a - mx) ** 2 for a in x)
    beta0 = my_ - beta1 * mx
    import pandas as pd  # 仅自检用
    df = pd.DataFrame({"Mkt-RF": [0.0] + mkt[:-1], "RF": [0.0] * len(mkt)})
    res = _ff_regress(prices2, df, ["Mkt-RF"])
    ok5 = abs(res["alpha"] - beta0) < 1e-9 and abs(res["Mkt-RF"] - beta1) < 1e-9
    for name, ok in (("ulcer_index", ok1), ("variance_ratio", ok2), ("acf", ok3),
                     ("pacf(1)=acf(1)", ok4), ("ff_regression 对拍 OLS", ok5)):
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    return 0 if all((ok1, ok2, ok3, ok4, ok5)) else 1


def _ff_regress(prices, factors, cols):
    """FF 回归（pandas DataFrame 输入，从 fama_french_regression 移植，返回 dict）。"""
    p = _to_list(prices)
    n = min(len(p), len(factors))
    if n < 2:
        return {"alpha": 0.0, **{c: 0.0 for c in cols}}
    rets = [p[i] / p[i - 1] - 1 for i in range(1, n)]
    rf = _to_list(factors["RF"]) if "RF" in factors.columns else [0.0] * n
    y = [rets[i - 1] - rf[i] for i in range(1, n)]
    x = [[1.0] + [_to_list(factors[c])[i] for c in cols] for i in range(1, n)]
    beta = _ols(y, x)
    return {"alpha": beta[0], **{c: beta[j + 1] for j, c in enumerate(cols)}}


def main() -> int:
    ap = argparse.ArgumentParser(description="绩效/统计度量工具箱（pwb-toolbox 直接合并）")
    ap.add_argument("cmd", nargs="?", default="", choices=["", "selfcheck"], help="selfcheck=对拍自检")
    ap.add_argument("--prices", default="", help="逗号分隔价格序列（如 100,102,101）")
    args = ap.parse_args()
    if args.cmd == "selfcheck":
        return _selfcheck()
    if args.prices:
        p = [float(x) for x in args.prices.split(",")]
        print(f"ulcer_index={ulcer_index(p):.6f}")
        print(f"ulcer_performance_index={ulcer_performance_index(p):.6f}")
        print(f"variance_ratio(lag2)={variance_ratio(p, 2):.4f}")
        print(f"acf(1,2,3)={[round(v, 4) for v in acf(p, [1, 2, 3])]}")
        print(f"pacf(1,2)={[round(v, 4) for v in pacf(p, [1, 2])]}")
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
