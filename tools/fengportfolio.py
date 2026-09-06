#!/usr/bin/env python3
"""
fengportfolio — P层 组合风险管理检查（正交维度 · 人民币一盘棋）。

风险归并按「正交维度」计算，不预设任何命名桶：
  - market   资产类别/家国市场（CN_A A股 / CN_HK 港股通 / CN_OVS 中概境外 / US / GLOBAL …）
  - segment  细分板块（互联网 / 半导体·AI算力 / 保险 …）
  - qualifier 现金属性（cash 真现金 / quasi_cash 准现金）
任一维度 + 任意组合（如 market×segment）都由运行期分组求和得出，
买新标的/新板块时直接加词即可，无需改代码。

资金墙（capital_zone）只作「买入预算」提示，不再产生任何风险告警。

Usage:
    python fengportfolio.py check        # 组合检查（JSON输出）
    python fengportfolio.py status       # 仪表盘（人类可读）
    python fengportfolio.py sector       # 板块集中度（segment 轴）
    python fengportfolio.py correlate    # 两两相关性矩阵
    python fengportfolio.py stress       # 宏观情景压力测试
    python fengportfolio.py hrp          # HRP 权重（--tickers/--returns-file/--corr/--linkage/--check）
    python fengportfolio.py cov-advanced # 高级协方差矩阵（POET/Structured/Shrinkage）
    python fengportfolio.py brinson      # Brinson 绩效归因（配置/选择/交互）

数据来源: holdings/hold_*.json（真源）；汇率实时取自 fengdata --mode fx，失败回退快照。
"""

import csv
import json
import os
import re
import sys
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOLDINGS_DIR = os.path.join(BASE, "holdings")
RESEARCH = os.path.join(BASE, "research")

# 汇率快照（2026-08-12 实测）—— 运行时优先取实时，失败回退此表
FX = {"CNY": 1.0, "HKD": 0.8586, "USD": 6.7414}

# 集中度阈值（占总资产%）
# ── 阈值文献注脚（以哲学参数为主，非论文参数）──
# · 分散数量锚：Evans-Archer 1968（约 8-10 只获大部分分散效果）vs Statman 1987（30-40 只充分分散）；
#   本项目取舍取 3-8 只集中持仓，属哲学参数
# · 单标 40% 绝对上限（single_abs）：哲学参数（2026-08-16 集中投资立场定稿），阈值本身无直接文献
# · 行业集中风险（segment 轴告警）：Hou-Robinson 2006（高集中度行业收益更低，风险/创新解释）——理论注脚
THRESH = {
    "market": {"red": 35, "yellow": 28},
    "segment": {"red": 25, "yellow": 20},
    "combo": {"red": 20, "yellow": 15},
    "single": {"red": 20, "yellow": 15},
    "single_abs": {"red": 40},  # 单标绝对上限：不可突破（集中投资哲学 2026-08-16）
}


# ============ 高级协方差估计器（移植自 Qlib，纯 numpy/scipy） ============

class _POETCovEstimator:
    """POET（主正交补阈值）协方差估计器。

    参考文献:
        Fan, Liao & Mincheva (2013) Large covariance estimation by thresholding
        principal orthogonal complements. JRSS-B 75(4):603-680.

    输入: X -- (T, N) 收益矩阵（每行一个交易日，每列一个资产）
    输出: N x N 协方差矩阵

    原理:
        1. PCA 提取 k 个主因子 -> 低秩部分 Lowrank = Lambda Lambda^T
        2. 残差 u = X - Lambda F^T 做相关矩阵阈值处理（soft/hard/scad）
        3. Sigma = Sigma_lowrank + Sigma_thresholded
    """

    THRESH_SOFT = "soft"
    THRESH_HARD = "hard"
    THRESH_SCAD = "scad"

    def __init__(self, num_factors: int = 0, thresh: float = 1.0, thresh_method: str = "soft") -> None:
        """
        参数:
            num_factors: 因子数量（0 = 不用因子模型，纯 POET）
            thresh:     阈值常数（>= 0）
            thresh_method: 阈值方法 soft/hard/scad
        """
        assert num_factors >= 0, "num_factors 需 >= 0"
        assert thresh >= 0, "thresh 需 >= 0"
        assert thresh_method in (self.THRESH_SOFT, self.THRESH_HARD, self.THRESH_SCAD), \
            f"thresh_method 须为 soft/hard/scad，收到: {thresh_method}"
        self.num_factors = num_factors
        self.thresh = thresh
        self.thresh_method = thresh_method

    def estimate(self, X: "np.ndarray") -> "np.ndarray":
        """从收益矩阵 X (T, N) 估计协方差矩阵 (N, N)。"""
        np_ = _try_np()
        if np_ is None:
            raise ImportError("POET 需要 numpy")
        Y = X.T  # (N, T) -- 匹配 POET MATLAB 原始实现
        p, n = Y.shape

        if self.num_factors > 0:
            # PCA 降维：对 Y^T Y 做特征分解，取最大 k 个特征向量
            eigvals, V = np_.linalg.eigh(Y.T @ Y)  # eigh 保证实数（对称矩阵）
            order = np_.argsort(eigvals)
            V = V[:, order]
            F = V[:, -self.num_factors:][:, ::-1] * np_.sqrt(n)   # 因子得分 (T, k)
            LamPCA = Y @ F / n                                     # 因子载荷 (N, k)
            uhat = np_.asarray(Y - LamPCA @ F.T)                   # 残差 (N, T)
            Lowrank = np_.asarray(LamPCA @ LamPCA.T)               # 低秩部分 (N, N)
            rate = 1 / np_.sqrt(p) + np_.sqrt(np_.log(p) / n)
        else:
            uhat = np_.asarray(Y)
            rate = np_.sqrt(np_.log(p) / n)
            Lowrank = 0

        # 阈值收缩：先算样本相关矩阵，再阈值处理
        lamb = rate * self.thresh
        SuPCA = uhat @ uhat.T / n                                 # 残差协方差
        SuDiag = np_.diag(np_.diag(SuPCA))                          # 对角部分
        inv_diag = np_.linalg.inv(SuDiag ** 0.5)
        R = inv_diag @ SuPCA @ inv_diag                           # 相关矩阵

        # 三种阈值方法
        if self.thresh_method == self.THRESH_HARD:
            M = R * (np_.abs(R) > lamb)
        elif self.thresh_method == self.THRESH_SOFT:
            res = np_.abs(R) - lamb
            res = (res + np_.abs(res)) / 2
            M = np_.sign(R) * res
        else:  # scad
            abs_R = np_.abs(R)
            M1 = (abs_R < 2 * lamb) * np_.sign(R) * (abs_R - lamb) * (abs_R > lamb)
            M2 = ((abs_R < 3.7 * lamb) * (abs_R >= 2 * lamb) *
                  (2.7 * R - 3.7 * np_.sign(R) * lamb) / 1.7)
            M3 = (abs_R >= 3.7 * lamb) * R
            M = M1 + M2 + M3

        # 重构协方差：Sigma_U + 低秩部分
        Rthresh = M - np_.diag(np_.diag(M)) + np_.eye(p)
        SigmaU = (SuDiag ** 0.5) @ Rthresh @ (SuDiag ** 0.5)
        SigmaY = SigmaU + Lowrank
        return SigmaY


class _StructuredCovEstimator:
    """结构化协方差估计器（PCA / 因子分析）。

    参考文献:
        Fan, Liao & Liu (2016) An overview of the estimation of large covariance
        and precision matrices. Econometrics Journal 19(1):C1-C32.

    模型: X = B @ F^T + U
        cov(X) = F @ cov(B) @ F^T + diag(var(U))

    其中 F 为因子载荷（PCA/FA 估计），B 为因子得分，U 为残差。
    """

    FACTOR_MODEL_PCA = "pca"
    FACTOR_MODEL_FA = "fa"

    def __init__(self, factor_model: str = "pca", num_factors: int = 10) -> None:
        """
        参数:
            factor_model: 因子模型 "pca" 或 "fa"
            num_factors:  保留因子数
        """
        assert factor_model in (self.FACTOR_MODEL_PCA, self.FACTOR_MODEL_FA), \
            f"factor_model 须为 pca/fa，收到: {factor_model}"
        self.factor_model = factor_model
        self.num_factors = num_factors

    def estimate(self, X: "np.ndarray") -> "np.ndarray":
        """从收益矩阵 X (T, N) 估计协方差矩阵 (N, N)。"""
        np_ = _try_np()
        if np_ is None:
            raise ImportError("Structured 需要 numpy")
        from sklearn.decomposition import PCA, FactorAnalysis

        Solver = PCA if self.factor_model == self.FACTOR_MODEL_PCA else FactorAnalysis
        model = Solver(self.num_factors, random_state=0).fit(X)
        F = model.components_.T     # (N, k) 因子载荷
        B = model.transform(X)      # (T, k) 因子得分
        U = X - B @ F.T             # (T, N) 残差
        cov_b = np_.cov(B.T)        # (k, k) 因子协方差
        var_u = np_.var(U, axis=0)  # (N,)  残差方差
        return F @ cov_b @ F.T + np_.diag(var_u)


def _brinson_attribution(
    port_weights: dict,
    bench_weights: dict,
    port_returns: dict,
    bench_returns: dict,
    total_bench_return: float = None,
) -> dict:
    """Brinson 绩效归因分解（Brinson-Fachler 口径）。

    参数:
        port_weights:   {sector: weight}  组合行业权重（已归一，和=1）
        bench_weights:  {sector: weight}  基准行业权重（已归一，和=1）
        port_returns:   {sector: return}  组合各行业收益率
        bench_returns:  {sector: return}  基准各行业收益率
        total_bench_return: 基准总收益率（可选，不传则自动计算）

    经典 Brinson 三因子分解:
        RAA（配置效应） = sum((wp_i - wb_i) * (rb_i - Rb))
        RSS（选择效应） = sum(wb_i * (rp_i - rb_i))
        RIN（交互效应） = sum((wp_i - wb_i) * (rp_i - rb_i))
        RTotal = RAA + RSS + RIN

    返回 dict: {RAA, RSS, RIN, RTotal, port_total_return, bench_total_return, by_sector, ...}
    """
    sectors = sorted(set(list(port_weights.keys()) + list(bench_weights.keys())))
    Rb = total_bench_return if total_bench_return is not None else sum(
        bench_weights.get(s, 0) * bench_returns.get(s, 0) for s in sectors
    )
    Rp = sum(port_weights.get(s, 0) * port_returns.get(s, 0) for s in sectors)

    RAA = 0.0
    RSS = 0.0
    RIN = 0.0
    by_sector: dict = {}
    for s in sectors:
        wp = port_weights.get(s, 0.0)
        wb = bench_weights.get(s, 0.0)
        rp = port_returns.get(s, 0.0)
        rb = bench_returns.get(s, 0.0)
        alloc = (wp - wb) * (rb - Rb)       # 配置效应
        select = wb * (rp - rb)              # 选择效应
        interact = (wp - wb) * (rp - rb)     # 交互效应
        RAA += alloc
        RSS += select
        RIN += interact
        by_sector[s] = {
            "wp": round(wp, 6), "wb": round(wb, 6),
            "rp": round(rp, 6), "rb": round(rb, 6),
            "allocation": round(alloc, 8),
            "selection": round(select, 8),
            "interaction": round(interact, 8),
        }
    return {
        "RAA": round(RAA, 8),
        "RSS": round(RSS, 8),
        "RIN": round(RIN, 8),
        "RTotal": round(Rp - Rb, 8),
        "port_total_return": round(Rp, 8),
        "bench_total_return": round(Rb, 8),
        "by_sector": by_sector,
        "method_note": "Brinson-Fachler: RAA=配置, RSS=选择, RIN=交互, RTotal=超额",
    }


def _get_fx():
    """实时汇率（fengdata._fx_rates），失败回退 FX 快照。带模块级缓存。"""
    global FX
    try:
        import fengdata as F
        r = F._fx_rates()
        if r and r.get("USDCNY") and r.get("HKDCNY"):
            FX = {"CNY": 1.0, "HKD": r["HKDCNY"], "USD": r["USDCNY"]}
            return {"FX": FX, "live": bool(r.get("live")), "date": r.get("date")}
    except Exception:
        pass
    return {"FX": FX, "live": False, "date": "snapshot"}


_FX_INFO = None


def fx_info():
    global _FX_INFO
    if _FX_INFO is None:
        _FX_INFO = _get_fx()
    return _FX_INFO


def parse_portfolio():
    """从 holdings/ 读取真实持仓（真源），返回规范化持仓列表。

    每个 position 含: id/name/asset_type/currency/zone(资金墙,仅供买入预算)/
                    market(资产类别)/segment(板块)/qualifier(现金属性)/
                    qty/avg_cost/current_price/market_value/market_value_cny/
                    sector(=segment 兼容)/return_pct/market_access。
    """
    fx = fx_info()["FX"]
    positions = []
    if not os.path.isdir(HOLDINGS_DIR):
        print(f"ERROR: holdings/ 目录不存在: {HOLDINGS_DIR}")
        return []
    for f in sorted(os.listdir(HOLDINGS_DIR)):
        m = re.match(r"^hold_([A-Za-z0-9_.]+)\.json$", f)
        if not m:
            continue
        try:
            with open(os.path.join(HOLDINGS_DIR, f), encoding="utf-8") as fh:
                h = json.load(fh)
        except Exception:
            continue
        cur = h.get("currency", "CNY")
        fxr = fx.get(cur, 1.0)
        p = h.get("position", {})
        qty = p.get("shares") or p.get("units") or 0
        avg = p.get("avg_cost") or p.get("nav") or p.get("amount") or 0
        px = p.get("current_price") or p.get("nav") or p.get("amount") or 0
        mv = p.get("market_value") or (qty * px) or (p.get("amount") or 0)
        hid = h.get("id") or h.get("ticker") or m.group(1)
        ret = (px / avg - 1) * 100 if (avg and px) else None
        pos = {
            "id": hid,
            "name": h.get("name", ""),
            "asset_type": h.get("asset_type", "stock"),
            "currency": cur,
            "zone": h.get("capital_zone", "CN_IN" if cur == "CNY" else "OVERSEAS"),
            "market": h.get("market", "其他"),
            "segment": h.get("segment", "其他"),
            "qualifier": h.get("qualifier"),
            "qty": qty,
            "avg_cost": avg,
            "current_price": px,
            "market_value": mv,
            "market_value_cny": round(mv * fxr, 2),
            "sector": h.get("segment") or h.get("sector", "其他"),  # 兼容旧字段
            "return_pct": round(ret, 1) if ret is not None else None,
            "market_access": h.get("market_access"),  # hksi=港股通
        }
        positions.append(pos)
    return positions


def _is_pool(p):
    """资金池：真现金(cash) + 准现金(quasi_cash，低波高息当现金用)。"""
    return p.get("qualifier") in ("cash", "quasi_cash") or p.get("asset_type") == "cash"


def check_concentration(positions):
    """按正交维度分组求和（不预设桶），返回分布 + 集中度告警。

    - market 轴：各资产类别占总量%
    - segment 轴：各板块占总量%
    - combo  轴：market×segment 组合占总量%（如 CN_OVS×互联网 自然浮现）
    - 资金池：真现金% + 准现金%（qualifier），不参与权益集中度
    - 单标：占总量% 超阈告警
    """
    total = sum(p["market_value_cny"] for p in positions) or 1
    equity = [p for p in positions if not _is_pool(p)]
    equity_mv = sum(p["market_value_cny"] for p in equity)

    pool_cash = sum(p["market_value_cny"] for p in positions if p.get("qualifier") == "cash")
    pool_quasi = sum(p["market_value_cny"] for p in positions if p.get("qualifier") == "quasi_cash")

    warnings = []

    # 单标（权益，占总资产%）
    for p in equity:
        w = p["market_value_cny"] / total * 100
        if w > THRESH["single_abs"]["red"]:
            warnings.append(f"⛔ 单标绝对超限: {p['id']} ({w:.1f}% > {THRESH['single_abs']['red']}% 不可突破)")
        elif w > THRESH["single"]["red"]:
            warnings.append(f"🔴 单标超限: {p['id']} ({w:.1f}% > {THRESH['single']['red']}%)")
        elif w > THRESH["single"]["yellow"]:
            warnings.append(f"🟡 单标接近上限: {p['id']} ({w:.1f}%)")

    # market 轴
    market_w = {}
    for p in equity:
        market_w[p["market"]] = market_w.get(p["market"], 0) + p["market_value_cny"]
    for mk, v in market_w.items():
        w = v / total * 100
        if w > THRESH["market"]["red"]:
            warnings.append(f"🔴 资产类别超限: {mk} ({w:.1f}% > {THRESH['market']['red']}%)")
        elif w > THRESH["market"]["yellow"]:
            warnings.append(f"🟡 资产类别偏高: {mk} ({w:.1f}%)")

    # segment 轴
    seg_w = {}
    for p in equity:
        seg_w[p["segment"]] = seg_w.get(p["segment"], 0) + p["market_value_cny"]
    for s, v in seg_w.items():
        w = v / total * 100
        if w > THRESH["segment"]["red"]:
            warnings.append(f"🔴 板块超限: {s} ({w:.1f}% > {THRESH['segment']['red']}%)")
        elif w > THRESH["segment"]["yellow"]:
            warnings.append(f"🟡 板块偏高: {s} ({w:.1f}%)")

    # combo 轴（market×segment）
    combo_w = {}
    for p in equity:
        key = f"{p['market']}×{p['segment']}"
        combo_w[key] = combo_w.get(key, 0) + p["market_value_cny"]
    for k, v in combo_w.items():
        w = v / total * 100
        if w > THRESH["combo"]["red"]:
            warnings.append(f"🔴 组合集中: {k} ({w:.1f}% > {THRESH['combo']['red']}%)")
        elif w > THRESH["combo"]["yellow"]:
            warnings.append(f"🟡 组合偏高: {k} ({w:.1f}%)")

    return {
        "total_value": round(total, 2),
        "equity_value": round(equity_mv, 2),
        "equity_pct": equity_mv / total * 100,
        "pool": {
            "true_cash": round(pool_cash, 2),
            "true_cash_pct": pool_cash / total * 100,
            "quasi_cash": round(pool_quasi, 2),
            "quasi_cash_pct": pool_quasi / total * 100,
            "pool_total": round(pool_cash + pool_quasi, 2),
            "pool_pct": (pool_cash + pool_quasi) / total * 100,
        },
        "market_axis": {k: {"value": round(v, 2), "pct_total": v / total * 100,
                            "pct_equity": v / equity_mv * 100 if equity_mv else 0}
                        for k, v in sorted(market_w.items(), key=lambda x: -x[1])},
        "segment_axis": {k: {"value": round(v, 2), "pct_total": v / total * 100,
                             "pct_equity": v / equity_mv * 100 if equity_mv else 0}
                         for k, v in sorted(seg_w.items(), key=lambda x: -x[1])},
        "combo_axis": {k: {"value": round(v, 2), "pct_total": v / total * 100,
                           "pct_equity": v / equity_mv * 100 if equity_mv else 0}
                       for k, v in sorted(combo_w.items(), key=lambda x: -x[1])},
        "warnings": warnings,
    }


def check_drawdown(positions):
    """Check current drawdown status."""
    max_single_drawdown = 0
    worst_position = None

    for p in positions:
        ret = p.get("return_pct")
        if ret is not None and ret < 0:
            if abs(ret) > abs(max_single_drawdown):
                max_single_drawdown = ret
                worst_position = p["id"]

    return {
        "max_single_drawdown": max_single_drawdown,
        "worst_position": worst_position,
    }


def check_budget(positions):
    """资金墙 = 买入预算提示（境内池/境外池余额），不产生告警。"""
    zones = {}
    for p in positions:
        z = p.get("zone") or "其他"
        zones[z] = zones.get(z, 0) + p["market_value_cny"]
    return {z: round(v, 2) for z, v in sorted(zones.items(), key=lambda x: -x[1])}


def cmd_check():
    """Full P layer check — JSON: 正交维度盘面 + 资金池 + 买入预算。"""
    positions = parse_portfolio()
    if not positions:
        sys.exit(1)

    c = check_concentration(positions)
    d = check_drawdown(positions)
    fx = fx_info()

    lights = []
    if c["warnings"]:
        has_red = any(w.startswith("🔴") for w in c["warnings"])
        lights.append("RED" if has_red else "YELLOW")
    else:
        lights.append("GREEN")
    if d["max_single_drawdown"] < -20:
        lights.append("RED")
    elif d["max_single_drawdown"] < -15:
        lights.append("YELLOW")
    else:
        lights.append("GREEN")
    light_order = {"GREEN": 0, "YELLOW": 1, "RED": 2}
    overall = max(lights, key=lambda x: light_order.get(x, 0))

    result = {
        "checked_at": datetime.now().isoformat(),
        "overall_light": overall,
        "fx": {"live": fx["live"], "date": fx["date"], "USDCNY": fx["FX"]["USD"], "HKDCNY": fx["FX"]["HKD"]},
        "overview": {
            "total_value": c["total_value"],
            "equity_value": c["equity_value"],
            "equity_pct": round(c["equity_pct"], 1),
            "pool_pct": round(c["pool"]["pool_pct"], 1),
        },
        "pool": c["pool"],
        "market_axis": c["market_axis"],
        "segment_axis": c["segment_axis"],
        "combo_axis": c["combo_axis"],
        "warnings": c["warnings"],
        "drawdown": d,
        "budget": check_budget(positions),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _flag(w, th):
    return '🔴' if w > th["red"] else '🟡' if w > th["yellow"] else '🟢'


def cmd_status():
    """Human-readable dashboard: 正交维度盘面 + 资金池 + 买入预算。"""
    positions = parse_portfolio()
    if not positions:
        print("## 组合盘面")
        print(" · holdings/ 目录为空或无法读取")
        return 0

    c = check_concentration(positions)
    d = check_drawdown(positions)
    budget = check_budget(positions)
    fx = fx_info()

    print("## 组合盘面（正交维度 · 人民币一盘棋）")
    fx_note = "实时" if fx["live"] else f"快照({fx['date']})"
    print(f"  汇率: USDCNY={fx['FX']['USD']:.4f} HKDCNY={fx['FX']['HKD']:.4f} [{fx_note}]")
    print(f"\n[总览]")
    print(f" · 总资产        {c['total_value']:,.0f}")
    print(f" · 权益          {c['equity_value']:,.0f} ({c['equity_pct']:.1f}%)")
    print(f" · 资金池        {c['pool']['pool_total']:,.0f} ({c['pool']['pool_pct']:.1f}%)")
    print(f"    真现金       {c['pool']['true_cash']:,.0f} ({c['pool']['true_cash_pct']:.1f}%)")
    print(f"    准现金       {c['pool']['quasi_cash']:,.0f} ({c['pool']['quasi_cash_pct']:.1f}%)  <- 低波高息当现金")

    print(f"\n[资产类别 market]")
    for mk, v in c["market_axis"].items():
        print(f"  {_flag(v['pct_total'], THRESH['market'])} {mk:12s} {v['pct_total']:5.1f}%  (占权益 {v['pct_equity']:.1f}%)")

    print(f"\n[板块 segment]")
    for s, v in c["segment_axis"].items():
        print(f"  {_flag(v['pct_total'], THRESH['segment'])} {s:12s} {v['pct_total']:5.1f}%  (占权益 {v['pct_equity']:.1f}%)")

    print(f"\n[组合集中 market×segment]")
    for k, v in c["combo_axis"].items():
        print(f"  {_flag(v['pct_total'], THRESH['combo'])} {k:24s} {v['pct_total']:5.1f}%  (占权益 {v['pct_equity']:.1f}%)")

    print(f"\n[买入预算 · 资金墙=划转约束，非配置维度]")
    for z, v in budget.items():
        print(f"  💰 {z:9s} 池 ¥{v:,.0f}")

    print(f"\n最大单标回撤   {d['max_single_drawdown']:.0f}% ({d['worst_position'] or '无'})")
    if c['warnings']:
        print(f"\n警告 ({len(c['warnings'])}):")
        for w in c['warnings']:
            print(f"  {w}")
    else:
        print("\n✅ 组合结构正常，无警告")
    return 0


def cmd_sector():
    """板块集中度（segment 轴）。"""
    positions = parse_portfolio()
    if not positions:
        print("无可分析持仓")
        return 0

    c = check_concentration(positions)
    print("板块集中度（segment 轴 · 占总资产%）")
    print(f"{'板块':16s} {'占总资产':>8s} {'上限':>8s} {'状态':>6s}")
    print("-" * 44)
    for s, v in c["segment_axis"].items():
        flag = _flag(v['pct_total'], THRESH['segment'])
        print(f"{s:16s} {v['pct_total']:7.1f}% {THRESH['segment']['red']:7d}% {flag:>6s}")
    return 0


def cmd_correlate():
    """Pairwise correlation matrix of all positions（修复：用 id 而非失效的 ticker）。"""
    positions = parse_portfolio()
    if not positions:
        print("{}")
        return 0

    ids = [p["id"] for p in positions]
    try:
        import yfinance as yf
        import pandas as pd
        import numpy as np
    except ImportError:
        print(json.dumps({"error": "需要 yfinance/pandas/numpy（未安装，跳过相关性）"}, indent=2, ensure_ascii=False))
        return 0

    data = yf.download(ids, period="1y", progress=False, auto_adjust=True)
    if data.empty:
        print("{}")
        return 0

    if isinstance(data.columns, pd.MultiIndex):
        close = data["Close"]
    else:
        close = data
    returns = close.pct_change().dropna()
    corr = returns.corr()
    triu = np.triu_indices_from(corr.values, k=1)
    avg_corr = round(float(corr.values[triu].mean()), 3) if len(ids) > 1 and triu[0].size > 0 else 1.0

    result = {
        "ids": ids,
        "correlation_matrix": corr.round(3).to_dict(),
        "avg_correlation": avg_corr,
        "note": "需 yfinance+pandas+numpy（本机可选安装）",
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_stress():
    """宏观情景压力测试（修复：用 market_value_cny 而非失效的 weight_pct）。"""
    positions = parse_portfolio()
    if not positions:
        print("[]")
        return 0

    total = sum(p["market_value_cny"] for p in positions) or 1
    equity = [p for p in positions if not _is_pool(p)]
    pool_pct = 100 - sum(p["market_value_cny"] for p in equity) / total * 100

    def seg(p):
        return p.get("segment", "")

    scenarios = [
        {
            "name": "inflation_shock",
            "label": "通胀反弹 · 利率升2%",
            "impact": "高估值成长/长久期资产受压，价值/现金牛受益",
            "est_drawdown_pct": -12,
            "hit": lambda p: seg(p) in ("半导体.AI算力", "互联网", "消费电子"),
        },
        {
            "name": "recession",
            "label": "经济衰退 · 消费萎缩",
            "impact": "可选消费/旅游承压，防御性资产(医药/低波)对冲",
            "est_drawdown_pct": -18,
            "hit": lambda p: seg(p) in ("互联网", "消费电子", "旅游", "家电"),
        },
        {
            "name": "market_crash",
            "label": "市场恐慌 · VIX>40",
            "impact": "所有风险资产同跌，现金/准现金为王",
            "est_drawdown_pct": -25,
            "hit": lambda p: not _is_pool(p),
        },
        {
            "name": "china_policy",
            "label": "中国监管/地缘冲击",
            "impact": "中概/港股通(CN_OVS, CN_HK)承压，境内A股相对受益",
            "est_drawdown_pct": -15,
            "hit": lambda p: p.get("market") in ("CN_OVS", "CN_HK"),
        },
    ]

    for s in scenarios:
        affected = sum(p["market_value_cny"] for p in positions if s["hit"](p))
        s["affected_value"] = round(affected, 2)
        s["affected_pct"] = round(affected / total * 100, 1)
        s["portfolio_impact_pct"] = round(affected / total * 100 * s["est_drawdown_pct"] / 100, 1)
        s["cash_buffer"] = round(pool_pct, 1)
        del s["hit"]

    print(json.dumps(scenarios, indent=2, ensure_ascii=False))
    return 0


def cmd_optimize():
    """约束再平衡建议（移植 ai-hedge-fund risk limits 两段式钳制思路 + Qlib 约束思想）。

    确定性算法（零依赖）：把超集中度红线的标的钳制到上限，
    释放的资金按未超限标的权重占比再分配，迭代至收敛；剩余资金进现金池。
    可选 --max-turnover N（pp）：限制总换手 Σ|Δw| ≤ N（Qlib 换手约束的确定性版）。
    输出 before/after 权重 + 建议调整市值 + 换手金额。
    """
    # --max-turnover N：总换手上限（单位 pp，如 10 = 单次再平衡最多动 10% 仓位）
    max_turnover = None
    if "--max-turnover" in sys.argv:
        idx = sys.argv.index("--max-turnover")
        try:
            max_turnover = float(sys.argv[idx + 1])
        except (IndexError, ValueError):
            print(json.dumps({"error": "--max-turnover 需要数字（单位 pp，如 10）"}, ensure_ascii=False))
            return 1

    positions = parse_portfolio()
    if not positions:
        print("[]")
        return 0

    total = sum(p["market_value_cny"] for p in positions) or 1
    equity = [p for p in positions if not _is_pool(p)]
    pool_pct = 100 - sum(p["market_value_cny"] for p in equity) / total * 100

    # 约束上限（占总资产 %，取红线上限）
    LIMIT = {"single": THRESH["single"]["red"], "segment": THRESH["segment"]["red"],
             "market": THRESH["market"]["red"]}
    n = len(equity)
    weights = [p["market_value_cny"] / total * 100 for p in equity]  # %
    ids = [p["id"] for p in equity]
    segs = [p.get("segment", "") for p in equity]
    mkts = [p.get("market", "") for p in equity]

    # 迭代钳制 + 再分配（最多 50 轮收敛）
    cur = list(weights)
    freed = 0.0
    for _ in range(50):
        moved = False
        # ① 单标超限 → 钳到上限
        for i in range(n):
            if cur[i] > LIMIT["single"]:
                freed += cur[i] - LIMIT["single"]
                cur[i] = LIMIT["single"]
                moved = True
        # ② segment 超限 → 组内等比缩
        for s in set(segs):
            members = [i for i in range(n) if segs[i] == s]
            ssum = sum(cur[i] for i in members)
            if ssum > LIMIT["segment"]:
                scale = LIMIT["segment"] / ssum
                for i in members:
                    freed += cur[i] * (1 - scale)
                    cur[i] = cur[i] * scale
                moved = True
        # ③ market 超限 → 组内等比缩
        for m in set(mkts):
            members = [i for i in range(n) if mkts[i] == m]
            msum = sum(cur[i] for i in members)
            if msum > LIMIT["market"]:
                scale = LIMIT["market"] / msum
                for i in members:
                    freed += cur[i] * (1 - scale)
                    cur[i] = cur[i] * scale
                moved = True
        if not moved:
            break
        # ④ 释放资金再分配：按未超限标的占比给，超限部分退回
        candidates = [i for i in range(n) if cur[i] < LIMIT["single"] - 1e-9]
        cand_w = sum(cur[i] for i in candidates)
        if cand_w <= 1e-9 or freed <= 1e-9:
            break
        give = freed
        freed = 0.0
        for i in candidates:
            share = cur[i] / cand_w * give
            cur[i] += share
            if cur[i] > LIMIT["single"]:
                freed += cur[i] - LIMIT["single"]
                cur[i] = LIMIT["single"]

    # ⑤ 换手约束（Qlib 换手上限思想：Σ|Δw| ≤ max_turnover）
    # 超限 → 整体缩放调整幅度：部分收敛，剩余超限显式标注，留待下期再平衡
    turnover = sum(abs(cur[i] - weights[i]) for i in range(n))
    limited = False
    note = "确定性钳制：超限→压到上限，余量按未超限占比再分配，剩余留现金"
    if max_turnover is not None and turnover > max_turnover + 1e-9:
        k = max_turnover / turnover
        for i in range(n):
            cur[i] = weights[i] + (cur[i] - weights[i]) * k
        limited = True
        note += (f"；换手约束生效：总换手 {turnover:.1f}pp → 限制 {max_turnover}pp"
                 "（部分收敛，剩余超限留待下期）")

    # 输出
    result = {
        "constraints": LIMIT,
        "cash_buffer_pct": round(pool_pct, 1),
        "turnover_pct": round(turnover, 2),
        "turnover_limited": limited,
        "rebalance": [
            {
                "id": ids[i], "segment": segs[i], "market": mkts[i],
                "before_pct": round(weights[i], 2), "after_pct": round(cur[i], 2),
                "adjust_pct": round(cur[i] - weights[i], 2),
                "adjust_value_cny": round((cur[i] - weights[i]) / 100 * total, 0),
            } for i in range(n)
        ],
        "freed_to_cash_pct": round(freed, 2),
        "note": note,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def _try_np():
    try:
        import numpy as np
        return np
    except ImportError:
        return None


def _ledoit_wolf_shrink(X):
    """Ledoit-Wolf 收缩协方差（移植 Qlib model/riskmodel/shrink.py 常数目标版）。

    X: (T, N) 收益矩阵（每行一个交易日）。返回收缩后协方差矩阵。
    """
    np = _try_np()
    T, N = X.shape
    Xc = X - X.mean(axis=0)
    S = (Xc.T @ Xc) / T
    mu = np.trace(S) / N
    F = np.eye(N) * mu
    d2 = ((S - F) ** 2).sum()
    if d2 < 1e-12:
        return S
    Xc2 = Xc ** 2
    phi = (Xc2.T @ Xc2).sum() / T - (S ** 2).sum()
    alpha = max(0.0, min(1.0, phi / d2))
    return (1 - alpha) * S + alpha * F


def cmd_risk():
    """组合风险归因：Ledoit-Wolf 收缩协方差 + 边际风险贡献（移植 Qlib 风险建模）。

    历史收益序列从本地 market_data.db（daily_data 表）读取，无需联网。
    """
    np = _try_np()
    if np is None:
        print(json.dumps({"error": "需要 numpy（未安装，跳过风险归因）"}, indent=2, ensure_ascii=False))
        return 0
    positions = parse_portfolio()
    equity = [p for p in positions if not _is_pool(p)]
    if len(equity) < 2:
        print(json.dumps({"error": "权益持仓不足 2 只，无法计算协方差"}, indent=2, ensure_ascii=False))
        return 0

    ids = [p["id"] for p in equity]
    db = os.path.join(BASE, "data", "market_data.db")
    if not os.path.exists(db):
        print(json.dumps({"error": f"数据库不存在: {db}"}, indent=2, ensure_ascii=False))
        return 0

    # 从 DB 读近 1 年日收盘（容错匹配 ticker）
    import sqlite3
    con = sqlite3.connect(db)
    rets, used, missing = [], [], []
    for i, pid in enumerate(ids):
        t = pid.upper()
        # 候选: 原样 / 去点 / 去交易所后缀（.SZ/.SS/.HK 等）
        cands = [t]
        base = t.split(".")[0]
        if "." in t:
            cands.append(t.replace(".", ""))
        if base != t:
            cands.append(base)
        sql = (
            "SELECT d.date, d.close FROM daily_data d JOIN indices i ON d.index_id=i.id "
            "WHERE (i.ticker=? OR i.ticker=? OR i.ticker=?) "
            "AND d.date >= date('now','-400 days') ORDER BY d.date"
        )
        rows = con.execute(sql, (cands[0], cands[1] if len(cands) > 1 else "", cands[2] if len(cands) > 2 else "")).fetchall()
        if len(rows) < 60:
            missing.append(pid)
            continue
        closes = [r[1] for r in rows if r[1]]
        if len(closes) < 60:
            missing.append(pid)
            continue
        rets.append(np.diff(np.log(np.array(closes, dtype=float))))
        used.append(pid)
    con.close()
    if len(used) < 2:
        print(json.dumps({"error": f"DB 匹配到的标的不够（{len(used)}），缺失: {missing}"}, indent=2, ensure_ascii=False))
        return 0

    # 对齐时间轴（取公共长度）
    min_len = min(len(r) for r in rets)
    X = np.array([r[-min_len:] for r in rets]).T  # (T, N)
    cov = _ledoit_wolf_shrink(X)

    # 组合权重（占总资产，剔除缺失标的）
    total = sum(p["market_value_cny"] for p in positions) or 1
    used_pos = [p for p in equity if p["id"] in used]
    w = np.array([p["market_value_cny"] / total for p in used_pos])
    w = w / w.sum()  # 风险口径内归一

    port_var = float(w @ cov @ w)
    port_vol = float(np.sqrt(port_var))
    mctr = (cov @ w) / port_vol                       # 边际风险贡献
    ctr = w * mctr                                    # 总风险贡献
    ctr_pct = (ctr / ctr.sum() * 100) if ctr.sum() else ctr

    # ---- 新增：CVaR 95% / 最大回撤 有限差分风险贡献（skfolio Portfolio.contribution 思路）----
    # RC_i = (risk(w + h·e_i) − risk(w − h·e_i)) / (2h) × w_i
    # 有限差分法对任意（含非平滑）风险度量通用；Euler 分解校验：ΣRC ≈ risk(w)。
    port_rets = X @ w                     # 日组合收益（X 行序 = 时间序）

    def _risk_cvar(rr):
        """历史 CVaR 95%（正数损失口径）：最差 5% 日收益的均值取负。"""
        k = max(1, int(np.ceil((1.0 - 0.95) * len(rr))))
        return -float(np.mean(np.sort(rr)[:k]))

    def _risk_maxdd(rr):
        """最大回撤（正数损失口径）：eq/peak − 1 的最小值取负。"""
        eq = np.cumprod(1.0 + rr)
        peak = np.maximum.accumulate(eq)
        return -float(np.min(eq / peak - 1.0))

    def _fd_contrib(risk_fn, h):
        contrib = np.empty(len(used))
        for i in range(len(used)):
            wp = w.copy()
            wp[i] += h
            wm = w.copy()
            wm[i] -= h
            contrib[i] = (risk_fn(X @ wp) - risk_fn(X @ wm)) / (2.0 * h) * w[i]
        return contrib

    cvar_h = 1e-5                         # CVaR 分段光滑，小步长
    dd_h = 1e-1                           # 回撤非平滑（max 函数），步长需大
    cvar_95 = _risk_cvar(port_rets)
    max_dd = _risk_maxdd(port_rets)
    cvar_contrib = _fd_contrib(_risk_cvar, cvar_h)
    dd_contrib = _fd_contrib(_risk_maxdd, dd_h)
    cvar_rc_sum = float(cvar_contrib.sum())
    dd_rc_sum = float(dd_contrib.sum())

    result = {
        "tickers_used": used,
        "tickers_missing": missing,
        "daily_vol_pct": round(port_vol * 100, 2),
        "annual_vol_pct": round(port_vol * np.sqrt(252) * 100, 2),
        "risk_contribution": [
            {"id": used_pos[i]["id"], "weight_pct": round(w[i] * 100, 2),
             "mctr": round(float(mctr[i]), 5), "contribution_pct": round(float(ctr_pct[i]), 2)}
            for i in range(len(used))
        ],
        "top_risk": sorted(
            [{"id": used_pos[i]["id"], "contribution_pct": round(float(ctr_pct[i]), 2)}
             for i in range(len(used))], key=lambda x: -x["contribution_pct"])[:5],
        # 新增：CVaR / 最大回撤有限差分贡献（%口径，正数=风险；保留原 MCTR 字段不变）
        "cvar_95": round(cvar_95 * 100, 3),
        "cvar_h": cvar_h,
        "cvar_contribution": [
            {"id": used_pos[i]["id"], "weight_pct": round(w[i] * 100, 2),
             "contribution_pct": round(float(cvar_contrib[i]) * 100, 4)}
            for i in range(len(used))
        ],
        "cvar_rc_sum": round(cvar_rc_sum * 100, 4),       # ΣRC（Euler 分解校验）
        "cvar_rc_error": round((cvar_rc_sum - cvar_95) * 100, 4),
        "drawdown": round(max_dd * 100, 3),
        "drawdown_h": dd_h,
        "drawdown_contribution": [
            {"id": used_pos[i]["id"], "weight_pct": round(w[i] * 100, 2),
             "contribution_pct": round(float(dd_contrib[i]) * 100, 4)}
            for i in range(len(used))
        ],
        "drawdown_rc_sum": round(dd_rc_sum * 100, 4),
        "drawdown_rc_error": round((dd_rc_sum - max_dd) * 100, 4),
        "method_note": (
            "风险口径：vol/CVaR95/最大回撤（历史分位、eq/peak，正数=损失）；"
            "贡献=有限差分 RC_i=(risk(w+h·e_i)−risk(w−h·e_i))/(2h)×w_i，h 见 cvar_h/drawdown_h；"
            "CVaR 一阶齐次→ΣRC≈CVaR；回撤非齐次→误差较大属预期"
        ),
        "note": "Ledoit-Wolf 收缩协方差（Qlib shrink 移植）· 近1年日收益 · 本地 DB 免联网",
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


# ============ HRP（层次风险平价）============

def _arg_val(name, default=None):
    """从 sys.argv 取 --name 的值（手写解析，与 cmd_optimize 的 --max-turnover 同款）。"""
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def _load_closes_db(ids):
    """从 data/market_data.db 读日收盘（daily_data.close，容错匹配 ticker）。

    返回 (closes_map, err)：closes_map = {ticker: {date: close}}。"""
    db = os.path.join(BASE, "data", "market_data.db")
    if not os.path.exists(db):
        return None, f"数据库不存在: {db}"
    import sqlite3
    con = sqlite3.connect(db)
    out = {}
    for pid in ids:
        t = pid.upper()
        cands = [t]
        base = t.split(".")[0]
        if "." in t:
            cands.append(t.replace(".", ""))
        if base != t:
            cands.append(base)
        rows = con.execute(
            "SELECT d.date, d.close FROM daily_data d JOIN indices i ON d.index_id=i.id "
            "WHERE (i.ticker=? OR i.ticker=? OR i.ticker=?) ORDER BY d.date",
            (cands[0], cands[1] if len(cands) > 1 else "", cands[2] if len(cands) > 2 else "")
        ).fetchall()
        clean = {d: c for d, c in rows if c}
        out[pid] = clean          # 空 dict 也保留，交给 _returns_frame 走「数据不足」跳过逻辑
    con.close()
    return out, None


def _load_returns_file(path):
    """从 CSV 读日收益/收盘价：列 date,ticker,close 或 date,ticker,return。

    返回 (closes_map, err, is_return)：closes_map = {ticker: {date: value}}；
    is_return=True 表示值是收益率（非价格），False 为收盘价。"""
    if not os.path.exists(path):
        return None, f"returns-file 不存在: {path}", False
    text = None
    for enc in ("utf-8-sig", "gbk", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as fh:
                text = fh.read()
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    if text is None:
        return None, f"returns-file 无法解码（utf-8/gbk 均失败）: {path}", False
    reader = csv.reader(text.splitlines())
    try:
        header = [h.strip().lower() for h in next(reader)]
    except StopIteration:
        return None, f"returns-file 为空: {path}", False
    if "date" not in header or "ticker" not in header:
        return None, f"returns-file 需含 date/ticker 列（实际: {header}）", False
    if "return" in header:
        val_col, is_return = "return", True
    elif "close" in header:
        val_col, is_return = "close", False
    else:
        return None, f"returns-file 需含 close 或 return 值列（实际: {header}）", False
    i_date, i_tick, i_val = header.index("date"), header.index("ticker"), header.index(val_col)
    out = {}
    n_bad = 0
    for row in reader:
        if len(row) <= max(i_date, i_tick, i_val):
            continue
        d, t = row[i_date].strip(), row[i_tick].strip()
        if not d or not t:
            continue
        try:
            v = float(row[i_val])
        except ValueError:
            n_bad += 1
            continue
        out.setdefault(t, {})[d] = v
    if not out:
        return None, f"returns-file 无有效数据行: {path}", False
    return out, None, is_return


def _returns_frame(closes_map, min_days=60, is_return=False):
    """{ticker: {date: close/return}} → (X (T,N) 日收益率矩阵, tickers, skipped)。

    - 任一 ticker 数据 < min_days 日 → 跳过并记录原因（警告）
    - 剩余 ticker 公共日期对齐；close 型转简单收益率（前收 ≤0 的交易日剔除）
    - 有效 ticker < 2 或公共日期 < min_days → 返回 (None, [], skipped)
    """
    np_ = _try_np()
    skipped = []
    used_map = {}
    for t, d in closes_map.items():
        nd = len(d)
        if nd < min_days:
            skipped.append({"ticker": t, "reason": f"数据仅 {nd} 日 < {min_days} 日，跳过"})
            continue
        used_map[t] = d
    if len(used_map) < 2:
        skipped.append({"reason": f"有效 ticker 不足 2 只（{len(used_map)}），无法计算"})
        return None, [], skipped
    common = None
    for d in used_map.values():
        keys = set(d.keys())
        common = keys if common is None else (common & keys)
    common = sorted(common)
    if len(common) < min_days:
        skipped.append({"reason": f"公共日期仅 {len(common)} 日 < {min_days} 日（交易日历差异大），无法对齐"})
        return None, [], skipped
    tickers = list(used_map.keys())
    raw = np_.array([[used_map[t][dd] for dd in common] for t in tickers], dtype=float)  # (N, T)
    if is_return:
        X = raw.T                      # (T, N) 已经是收益率
    else:
        prev, cur = raw[:, :-1], raw[:, 1:]
        valid = np_.all(prev > 0, axis=0)
        if not np_.all(valid):
            n_drop = int((~valid).sum())
            if n_drop > 0:
                skipped.append({"reason": f"{n_drop} 个交易日因前收 ≤0 被剔除（复权异常）"})
            prev, cur = prev[:, valid], cur[:, valid]
        if cur.shape[1] < min_days - 1:
            skipped.append({"reason": f"剔除异常后收益天数不足 {min_days - 1}"})
            return None, [], skipped
        X = (cur / prev - 1.0).T       # (T, N) 简单收益率
    return X, tickers, skipped


def _corr_matrix(X, method):
    """相关矩阵：pearson（np.corrcoef）/ spearman（秩相关）/ kendall（tau-b 两两）。"""
    np_ = _try_np()
    if method == "pearson":
        return np_.corrcoef(X, rowvar=False)
    if method == "spearman":
        from scipy.stats import rankdata
        R = np_.apply_along_axis(rankdata, 0, X)
        return np_.corrcoef(R, rowvar=False)
    if method == "kendall":
        from scipy.stats import kendalltau
        n = X.shape[1]
        corr = np_.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                tau, _ = kendalltau(X[:, i], X[:, j])
                corr[i, j] = corr[j, i] = tau
        return corr
    raise ValueError(f"不支持的相关系数方法: {method}")


def _hrp_weights(X, corr_method="pearson", linkage_method="ward"):
    """HRP 权重（Lopez de Prado 2016 论文口径，内置实现，仅 numpy+scipy）。

    - 距离 d = √(0.5×(1−ρ))，clip [0,1]（skfolio PearsonDistance 同款 angular distance）
    - scipy linkage + optimal_leaf_ordering + leaves_list（seriation）
    - 递归二分：簇内逆方差 1/σ²（σ=日收益 std，只平方一次——已修正 Riskfolio-Lib σ⁴ 平方两次的 bug）；
      簇风险 = w^T Σ w（完整协方差，ddof=1，与 skfolio EmpiricalPrior 一致）
      α = 1 − risk_left/(risk_left + risk_right)
    返回 (weights, info)。"""
    np_ = _try_np()
    from scipy.cluster.hierarchy import leaves_list, linkage, optimal_leaf_ordering
    from scipy.spatial.distance import squareform

    n = X.shape[1]
    corr = _corr_matrix(X, corr_method)
    dist = np_.sqrt(np_.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    condensed = squareform(dist, checks=False)
    Z = linkage(condensed, method=linkage_method)
    Z_ordered = optimal_leaf_ordering(Z, condensed)
    order = leaves_list(Z_ordered).tolist()

    cov = np_.cov(X, rowvar=False)                # 完整协方差
    sigma2 = np_.diag(cov)                        # 资产方差 σ²（只平方一次）
    weights = np_.ones(n)
    items = [list(order)]
    while items:
        new_items = []
        for cluster in items:
            mid = len(cluster) // 2
            if mid == 0:
                continue                          # 单资产簇，权重恒 1（无需再分）
            left, right = cluster[:mid], cluster[mid:]
            new_items += [left, right]
            risks = []
            for ids in (left, right):
                inv = np_.zeros(n)
                inv[ids] = 1.0 / sigma2[ids]      # 簇内逆方差 1/σ²
                inv /= inv.sum()
                risks.append(float(inv @ cov @ inv))   # 簇风险 = w^T Σ w
            alpha = 1.0 - risks[0] / (risks[0] + risks[1])
            weights[left] *= alpha
            weights[right] *= 1.0 - alpha
        items = new_items
    info = {
        "corr": corr, "dist": dist, "order": order,
        "sigma2": sigma2, "port_var": float(weights @ cov @ weights),
    }
    return weights, info


def cmd_hrp():
    """层次风险平价权重（HRP）。

    输入：--tickers A,B,C（本地 DB 日收盘，任一 ticker < 60 日跳过并警告）
          或 --returns-file <CSV>（date,ticker,close 或 date,ticker,return）
    参数：--corr pearson|spearman|kendall（默认 pearson）、
          --linkage ward|single|average|complete（默认 ward）
    可选：--check 与 skfolio HierarchicalRiskParity 交叉对照（未安装则提示跳过）。
    """
    np_ = _try_np()
    if np_ is None:
        print(json.dumps({"error": "需要 numpy（未安装，跳过 HRP）"}, indent=2, ensure_ascii=False))
        return 0
    try:
        import scipy  # noqa: F401
    except ImportError:
        print(json.dumps({"error": "需要 scipy（未安装，HRP 依赖 scipy.cluster.hierarchy）"},
                          indent=2, ensure_ascii=False))
        return 0

    tickers_arg = _arg_val("--tickers")
    returns_file = _arg_val("--returns-file")
    corr_method = (_arg_val("--corr") or "pearson").lower()
    linkage_method = (_arg_val("--linkage") or "ward").lower()
    do_check = "--check" in sys.argv

    if corr_method not in ("pearson", "spearman", "kendall"):
        print(json.dumps({"error": f"--corr 只支持 pearson|spearman|kendall（收到: {corr_method}）"},
                          indent=2, ensure_ascii=False))
        return 1
    if linkage_method not in ("ward", "single", "average", "complete"):
        print(json.dumps({"error": f"--linkage 只支持 ward|single|average|complete（收到: {linkage_method}）"},
                          indent=2, ensure_ascii=False))
        return 1
    if tickers_arg and returns_file:
        print(json.dumps({"error": "--tickers 与 --returns-file 互斥，只能二选一"}, indent=2, ensure_ascii=False))
        return 1
    if not tickers_arg and not returns_file:
        print(json.dumps({"error": "需要 --tickers A,B,C 或 --returns-file <CSV>"}, indent=2, ensure_ascii=False))
        return 1

    if returns_file:
        closes_map, err, is_return = _load_returns_file(returns_file)
        source = f"returns-file: {returns_file}"
    else:
        tickers = [t.strip() for t in tickers_arg.split(",") if t.strip()]
        if not tickers:
            print(json.dumps({"error": "--tickers 为空"}, indent=2, ensure_ascii=False))
            return 1
        closes_map, err = _load_closes_db(tickers)
        source = "data/market_data.db (daily_data.close)"
        is_return = False
    if err:
        print(json.dumps({"error": err}, indent=2, ensure_ascii=False))
        return 1

    X, used, skipped = _returns_frame(closes_map, is_return=is_return)
    if X is None:
        print(json.dumps({"error": "收益率矩阵构造失败", "skipped": skipped}, indent=2, ensure_ascii=False))
        return 1
    if skipped:
        print(f"[warning] {json.dumps(skipped, ensure_ascii=False)}", file=sys.stderr)

    weights, info = _hrp_weights(X, corr_method, linkage_method)
    port_var = info["port_var"]

    # 可选交叉对照：skfolio HierarchicalRiskParity（ImportError → 提示跳过，不失败）
    checked = None
    if do_check:
        try:
            import pandas as pd
            from skfolio.optimization import HierarchicalRiskParity
        except ImportError:
            checked = "skfolio not installed, skip check"
        else:
            try:
                df = pd.DataFrame(X, columns=used)
                ptf = HierarchicalRiskParity().fit_predict(df)
                sk_w = np_.asarray(ptf.weights)
                max_diff = float(np_.abs(sk_w - weights).max())
                checked = {
                    "skfolio_weights": {t: round(float(sk_w[i]), 6) for i, t in enumerate(used)},
                    "max_abs_weight_diff": round(max_diff, 6),
                    "note": "skfolio HierarchicalRiskParity 默认参数（VARIANCE + PearsonDistance + ward + OLO seriation）",
                }
            except Exception as e:
                hint = "（skfolio 对 2 资产存在内部限制，本实现不受影响）" if len(used) == 2 else ""
                checked = f"skfolio check failed: {type(e).__name__}: {e}{hint}"

    result = {
        "weights": {t: round(float(weights[i]), 6) for i, t in enumerate(used)},
        "weight_sum": round(float(weights.sum()), 10),
        "min_weight": round(float(weights.min()), 10),
        "risk": {
            "portfolio_variance": round(port_var, 10),
            "portfolio_vol_pct": round(np_.sqrt(port_var) * 100, 3),
            "asset_std_pct": {t: round(float(np_.sqrt(info["sigma2"][i])) * 100, 3)
                              for i, t in enumerate(used)},
            "cluster_risk": "簇内逆方差 1/σ²；簇风险 = w^T Σ w（完整协方差）",
        },
        "correlation_method": corr_method,
        "linkage": linkage_method,
        "seriation": "optimal_leaf_ordering + leaves_list",
        "asset_order": [used[i] for i in info["order"]],
        "n_obs": int(X.shape[0]),
        "source": source,
        "skipped": skipped,
        "note": "HRP 论文口径 σ²（已修正 Riskfolio σ⁴ 偏差）",
        "checked": checked,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


# ============ 高级协方差矩阵估计（POET/Structured/Shrinkage） ============

def cmd_cov_advanced():
    """高级协方差矩阵估计：POET / Structured / Shrinkage（替代简单经验协方差）。

    POET: 主正交补阈值法，对 PCA 残差做 soft/hard/scad 阈值收缩
    Structured: PCA/FA 因子模型，cov = F cov(B) F^T + diag(var(U))
    Shrinkage: Ledoit-Wolf 常数目标收缩（已有，直接复用）

    用法:
      python fengportfolio.py cov-advanced --tickers A,B,C
      python fengportfolio.py cov-advanced --tickers A,B,C --method poet --num-factors 5 --thresh 0.8 --thresh-method soft
      python fengportfolio.py cov-advanced --tickers A,B,C --method structured --factor-model pca --num-factors 10
      python fengportfolio.py cov-advanced --tickers A,B,C --method shrinkage
      python fengportfolio.py cov-advanced --returns-file data.csv --method poet
    """
    np_ = _try_np()
    if np_ is None:
        print(json.dumps({"error": "需要 numpy（未安装）"}, indent=2, ensure_ascii=False))
        return 1

    method = (_arg_val("--method") or "poet").lower()
    num_factors = int(_arg_val("--num-factors") or "0")
    thresh = float(_arg_val("--thresh") or "1.0")
    thresh_method = (_arg_val("--thresh-method") or "soft").lower()
    factor_model = (_arg_val("--factor-model") or "pca").lower()
    tickers_arg = _arg_val("--tickers")
    returns_file = _arg_val("--returns-file")

    if method not in ("poet", "structured", "shrinkage"):
        print(json.dumps({"error": f"--method 只支持 poet|structured|shrinkage（收到: {method}）"},
                          ensure_ascii=False))
        return 1

    # 数据加载（复用 HRP 的数据加载逻辑）
    if returns_file:
        closes_map, err, is_return = _load_returns_file(returns_file)
        source = f"returns-file: {returns_file}"
    else:
        tickers = [t.strip() for t in (tickers_arg or "").split(",") if t.strip()]
        if not tickers:
            print(json.dumps({"error": "需要 --tickers A,B,C 或 --returns-file <CSV>"}, ensure_ascii=False))
            return 1
        closes_map, err = _load_closes_db(tickers)
        source = "data/market_data.db (daily_data.close)"
        is_return = False
    if err:
        print(json.dumps({"error": err}, ensure_ascii=False))
        return 1

    X, used, skipped = _returns_frame(closes_map, is_return=is_return)
    if X is None:
        print(json.dumps({"error": "收益率矩阵构造失败", "skipped": skipped}, ensure_ascii=False))
        return 1

    T, N = X.shape
    try:
        if method == "poet":
            estimator = _POETCovEstimator(num_factors=num_factors, thresh=thresh, thresh_method=thresh_method)
            cov = estimator.estimate(X)
            note = f"POET({thresh_method}, num_factors={num_factors}, thresh={thresh})"
        elif method == "structured":
            estimator = _StructuredCovEstimator(factor_model=factor_model, num_factors=num_factors or 10)
            cov = estimator.estimate(X)
            note = f"Structured({factor_model}, num_factors={num_factors or 10})"
        else:  # shrinkage
            cov = _ledoit_wolf_shrink(X)
            note = "Ledoit-Wolf 收缩"
    except Exception as e:
        print(json.dumps({"error": f"{method} 协方差估计失败: {type(e).__name__}: {e}",
                           "skipped": skipped}, ensure_ascii=False))
        return 1

    # 格式化输出
    cov_list = np_.round(cov, 8).tolist()
    eigenvalues = np_.sort(np_.linalg.eigvalsh(cov))[::-1].tolist()
    cond_number = float(eigenvalues[0] / eigenvalues[-1]) if eigenvalues[-1] > 1e-15 else float("inf")

    result = {
        "method": method,
        "note": note,
        "tickers": used,
        "shape": [N, N],
        "n_observations": T,
        "covariance_matrix": {used[i]: {used[j]: cov_list[i][j] for j in range(N)} for i in range(N)},
        "eigenvalues_top5": [round(e, 8) for e in eigenvalues[:5]],
        "condition_number": round(cond_number, 2),
        "source": source,
        "skipped": skipped,
    }
    if "--json" in sys.argv:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"协方差矩阵估计 — {method.upper()}")
        print(f"  方法: {note}")
        print(f"  标的: {used}")
        print(f"  观测数: {T}  资产数: {N}")
        print(f"  条件数: {cond_number:.1f}  最大特征值: {eigenvalues[0]:.6f}")
        print(f"\n协方差矩阵（前5x5）:")
        header = "".join(f"{used[j]:>12s}" for j in range(min(5, N)))
        print(f"  {'':>12s}{header}")
        for i in range(min(5, N)):
            row = "".join(f"{cov_list[i][j]:12.6f}" for j in range(min(5, N)))
            print(f"  {used[i]:>12s}{row}")
        if N > 5:
            print(f"  ... ({N-5} more rows/cols)")
    return 0


# ============ Brinson 绩效归因 ============

def cmd_brinson():
    """Brinson 绩效归因：配置效应 + 选择效应 + 交互效应。"""
    if "--help" in sys.argv or "-h" in sys.argv:
        print("Brinson 绩效归因 — Brinson-Fachler 三因子分解")
        print()
        print("用法:")
        print("  python fengportfolio.py brinson \\")
        print("    --port-weights w.json --bench-weights b.json \\")
        print("    --port-returns r.json --bench-returns r.json [--json]")
        print()
        print("  RAA（配置效应）= sum((wp_i - wb_i) * (rb_i - Rb))")
        print("  RSS（选择效应）= sum(wb_i * (rp_i - rb_i))")
        print("  RIN（交互效应）= sum((wp_i - wb_i) * (rp_i - rb_i))")
        print("  RTotal = RAA + RSS + RIN")
        print()
        print("JSON 格式: {\"板块名\": 权重(小数), ...}")
        print("示例: {\"半导体.AI算力\": 0.35, \"互联网\": 0.25, \"现金\": 0.10}")
        return 0

    def _load_json_arg(name: str) -> dict:
        """从 --name 读取 JSON 文件。"""
        path = _arg_val(name)
        if not path:
            print(json.dumps({"error": f"缺少参数 {name}"}, ensure_ascii=False))
            return None
        if not os.path.exists(path):
            print(json.dumps({"error": f"文件不存在: {path}"}, ensure_ascii=False))
            return None
        for enc in ("utf-8-sig", "gbk", "latin-1"):
            try:
                with open(path, "r", encoding=enc) as fh:
                    return json.load(fh)
            except (UnicodeDecodeError, UnicodeError):
                continue
        print(json.dumps({"error": f"无法解码 JSON: {path}"}, ensure_ascii=False))
        return None

    port_w = _load_json_arg("--port-weights")
    bench_w = _load_json_arg("--bench-weights")
    port_r = _load_json_arg("--port-returns")
    bench_r = _load_json_arg("--bench-returns")
    if port_w is None or bench_w is None or port_r is None or bench_r is None:
        return 1

    try:
        result = _brinson_attribution(
            port_weights=port_w,
            bench_weights=bench_w,
            port_returns=port_r,
            bench_returns=bench_r,
        )
    except Exception as e:
        print(json.dumps({"error": f"Brinson 归因计算失败: {type(e).__name__}: {e}"}, ensure_ascii=False))
        return 1

    if "--json" in sys.argv:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Brinson 绩效归因")
        print(f"  组合总收益: {result['port_total_return']*100:.2f}%")
        print(f"  基准总收益: {result['bench_total_return']*100:.2f}%")
        print(f"  超额收益:   {result['RTotal']*100:.4f}%")
        print(f"\n  配置效应 (RAA): {result['RAA']*100:.4f}%")
        print(f"  选择效应 (RSS): {result['RSS']*100:.4f}%")
        print(f"  交互效应 (RIN): {result['RIN']*100:.4f}%")
        print(f"\n{'行业':16s} {'wp':>6s} {'wb':>6s} {'rp':>8s} {'rb':>8s} {'配置':>10s} {'选择':>10s} {'交互':>10s}")
        print("-" * 80)
        for s, d in result["by_sector"].items():
            print(f"{s:16s} {d['wp']:6.1%} {d['wb']:6.1%} {d['rp']:8.2%} {d['rb']:8.2%}"
                  f" {d['allocation']:10.6f} {d['selection']:10.6f} {d['interaction']:10.6f}")
    return 0


if __name__ == "__main__":
    cmds = {
        "check": cmd_check,
        "status": cmd_status,
        "sector": cmd_sector,
        "correlate": cmd_correlate,
        "stress": cmd_stress,
        "optimize": cmd_optimize,
        "risk": cmd_risk,
        "hrp": cmd_hrp,
        "cov-advanced": cmd_cov_advanced,
        "brinson": cmd_brinson,
    }

    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print("FengInvest P层 — 组合风险管理（正交维度 · 人民币一盘棋）")
        print()
        print("用法:")
        print("  fengportfolio.py check         - 组合检查（JSON输出）")
        print("  fengportfolio.py status        - 仪表盘（人类可读）")
        print("  fengportfolio.py sector        - 板块集中度（segment 轴）")
        print("  fengportfolio.py correlate     - 两两相关性矩阵")
        print("  fengportfolio.py stress        - 宏观情景压力测试")
        print("  fengportfolio.py optimize [--max-turnover N] - 约束再平衡建议（钳制+可选换手上限）")
        print("  fengportfolio.py risk          - 风险归因（收缩协方差+MCTR+CVaR/回撤贡献）")
        print("  fengportfolio.py hrp [--tickers A,B,C | --returns-file f.csv]"
              " [--corr pearson|spearman|kendall] [--linkage ward|single|average|complete]"
              " [--check] - HRP 权重（层次风险平价）")
        print("  fengportfolio.py cov-advanced --tickers A,B,C [--method poet|structured|shrinkage]"
              " [--num-factors N] [--thresh T] [--thresh-method soft|hard|scad]"
              " [--factor-model pca|fa] [--returns-file f.csv] - 高级协方差矩阵估计")
        print("  fengportfolio.py brinson --port-weights w.json --bench-weights b.json"
              " --port-returns r.json --bench-returns r.json [--json] - Brinson 绩效归因")
        print()
        print("数据来源: holdings/hold_*.json（真源）+ data/market_data.db（risk/hrp/cov-advanced）")
        print("分类维度: market(资产类别) x segment(板块) x qualifier(现金属性)")
        sys.exit(1)

    sys.exit(cmds[sys.argv[1]]())
