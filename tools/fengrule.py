#!/usr/bin/env python3
"""fengrule — L1 硬纪律检查. Uses fengdata output. Output JSON.

Usage:
    python fengrule.py 0700.HK          # full L1 check
    python fengrule.py 0700.HK --json   # raw data

Dependencies: yfinance, pandas
"""

import json, os, sys
from datetime import datetime

os.environ.pop("HTTP_PROXY", None)
os.environ.pop("HTTPS_PROXY", None)
os.environ.pop("http_proxy", None)
os.environ.pop("https_proxy", None)

import yfinance as yf
import pandas as pd


def _light(level: str, emoji: str) -> str:
    """Return light indicator: R/Y/G."""
    return f"{level}"


# 文献：本规则=趋势确认+极端估值双条件。极端估值判断（PE<10/PB<1/股息率>5%）属估值类，
# → Liu-Stambaugh-Yuan 2019（A股价值首选 EP 口径，PB 用于 A 股有口径风险）；趋势部分无直接单篇标尺
def check_no_knife(ticker: str) -> dict:
    """L1-1: 不接飞刀"""
    t = yf.Ticker(ticker)
    hist = t.history(period="1y")
    info = t.info or {}
    # yfinance默认auto_adjust=True → Close为前复权价格（除息调整）
    c = hist["Close"]

    price = float(c.iloc[-1])
    ma50 = float(c.iloc[-50:].mean()) if len(c) >= 50 else None
    ma120 = float(c.iloc[-120:].mean()) if len(c) >= 120 else None

    # Fundamentals check
    fcf_neg = False
    roe_declining = False
    rev_shrinking = False
    debt_worsening = False

    fs = t.financials
    if fs is not None and not fs.empty:
        rev = fs.loc["Total Revenue"] if "Total Revenue" in fs.index else None
        ni = fs.loc["Net Income"] if "Net Income" in fs.index else None

        if rev is not None and len(rev) >= 2:
            rev_shrinking = float(rev.iloc[0]) < float(rev.iloc[1])

    cf = t.cashflow
    if cf is not None and not cf.empty:
        fcf_vals = cf.loc["Free Cash Flow"] if "Free Cash Flow" in cf.index else None
        if fcf_vals is not None and len(fcf_vals) >= 2:
            fcf_neg = float(fcf_vals.iloc[0]) < 0 or float(fcf_vals.iloc[1]) < 0

    roe = info.get("returnOnEquity")
    roe_pct = round(roe * 100, 1) if roe else None

    # Distinguish: FCF negative because business is losing money vs investment cycle
    # If OCF positive + CAPEX large → investment cycle, not fundamental deterioration
    fcf_capex_driven = False
    if fcf_neg and cf is not None and not cf.empty:
        ocf_vals = cf.loc["Operating Cash Flow"] if "Operating Cash Flow" in cf.index else None
        capex_key = "Capital Expenditure"
        if capex_key not in cf.index:
            capex_key = "Purchase Of Property, Plant And Equipment"
        capex_vals = cf.loc[capex_key] if capex_key in cf.index else None
        if ocf_vals is not None and capex_vals is not None and len(ocf_vals) >= 1 and len(capex_vals) >= 1:
            latest_ocf = float(ocf_vals.iloc[0])
            latest_capex = abs(float(capex_vals.iloc[0]))
            if latest_ocf > latest_capex * 0.5 and latest_ocf > 0:
                fcf_capex_driven = True

    fundamentals_bad = (fcf_neg and not fcf_capex_driven) or rev_shrinking
    extreme_value = (info.get("trailingPE") or 99) < 10 or (info.get("priceToBook") or 99) < 1 or (info.get("dividendYield") or 0) > 5

    # Determine level
    if ma50 is not None and ma120 is not None and ma50 < ma120:
        if fundamentals_bad:
            # RED: hard block
            level = "RED"
            signal = "硬拦截"
            reason = f"MA50({ma50:.2f}) < MA120({ma120:.2f}) + 基本面恶化"
        elif roe_pct and roe_pct > 10 and extreme_value:
            level = "YELLOW"
            signal = "条件通过(DCA)"
            reason = f"MA50({ma50:.2f}) < MA120({ma120:.2f}) + 真价值+极端估值, 可DCA入场"
        else:
            level = "YELLOW"
            signal = "条件通过"
            reason = f"MA50({ma50:.2f}) < MA120({ma120:.2f}) + 基本面尚可, DCA条件通过"
    else:
        level = "GREEN"
        signal = "PASS"
        reason = f"Price({price:.2f}) >= MA50({ma50:.2f}) >= MA120({ma120:.2f})" if ma50 and ma120 else "趋势右侧"

    return {
        "check": "no_knife",
        "label": "不接飞刀",
        "light": level,
        "signal": signal,
        "price": price,
        "ma50": ma50,
        "ma120": ma120,
        "price_above_ma50": price > ma50 if ma50 else None,
        "ma50_above_ma120": ma50 > ma120 if ma50 and ma120 else None,
        "roe_pct": roe_pct,
        "fcf_negative": fcf_neg,
        "revenue_shrinking": rev_shrinking,
        "fundamentals_bad": fundamentals_bad,
        "extreme_valuation": extreme_value,
        "reason": reason,
    }


def check_no_fomo(ticker: str) -> dict:
    """L1-2: 不蹭热点"""
    t = yf.Ticker(ticker)
    hist = t.history(period="6mo")
    c = hist["Close"]

    price = float(c.iloc[-1])
    m1 = float((c.iloc[-1] / c.iloc[-22] - 1) * 100) if len(c) >= 22 else None

    if m1 is not None and m1 > 30:
        level = "RED"
        signal = "硬拦截"
        reason = f"上月涨幅{m1:.0f}% > 30%, 禁止买入"
    else:
        level = "GREEN"
        signal = "PASS"
        reason = f"上月涨幅{m1:.1f}% < 30%"

    return {
        "check": "no_fomo",
        "label": "不蹭热点",
        "light": level,
        "signal": signal,
        "return_1m_pct": m1,
        "reason": reason,
    }


def check_no_leverage(ticker: str) -> dict:
    """L1-3: 杠杆=0"""
    return {
        "check": "no_leverage",
        "label": "杠杆=0",
        "light": "GREEN",
        "signal": "PASS",
        "reason": "无杠杆（框架硬规则，默认通过）",
        "note": "交易账户杠杆=0是铁律，此检查需用户自行确认。脚本不访问券商账户。"
    }


def check_true_value(ticker: str) -> dict:
    """L1-4: 真价值"""
    t = yf.Ticker(ticker)
    info = t.info or {}

    fcf = info.get("freeCashflow")
    revenue = info.get("totalRevenue")
    profit_margin = info.get("profitMargins")
    sector = info.get("sector", "")
    industry = info.get("industry", "")

    # Basic checks for real value
    has_cashflow = fcf is not None and fcf > 0
    has_revenue = revenue is not None and revenue > 0
    is_profitable = profit_margin is not None and profit_margin > 0

    if has_cashflow and has_revenue and is_profitable:
        level = "GREEN"
        signal = "PASS"
        reason = f"真实消费需求 + 正现金流(FCF={fcf/1e9:.1f}B) + 盈利(利润率{profit_margin*100:.1f}%)"
    elif has_revenue and is_profitable:
        level = "YELLOW"
        signal = "存疑"
        reason = "有收入和利润但FCF为负，需进一步确认"
    else:
        level = "RED"
        signal = "假价值"
        reason = "无收入支撑或无正现金流，可能靠涨价预期维持"

    return {
        "check": "true_value",
        "label": "真价值",
        "light": level,
        "signal": signal,
        "has_cashflow": has_cashflow,
        "has_revenue": has_revenue,
        "is_profitable": is_profitable,
        "reason": reason,
    }


def _market_index_for(ticker: str) -> str:
    """Determine which market index to check based on ticker suffix."""
    suffix = ticker.split(".")[-1] if "." in ticker else ""
    return {
        "HK": "^HSI",
        "SS": "000001.SS",
        "SZ": "399001.SZ",
    }.get(suffix, "^GSPC")  # default US


def check_no_2638(ticker: str) -> dict:
    """DK: no_2638 — 大盘位置检查（A股2638分界 / 港股年线 / 美股年线）"""
    idx_ticker = _market_index_for(ticker)
    try:
        idx = yf.Ticker(idx_ticker)
        hist = idx.history(period="1y")
        c = hist["Close"]
        price = float(c.iloc[-1])
        ma200 = float(c.iloc[-200:].mean()) if len(c) >= 200 else None
    except Exception:
        return {
            "check": "no_2638",
            "label": "2638法則/大盘位置",
            "light": "YELLOW",
            "signal": "数据不可用",
            "reason": f"无法获取{idx_ticker}数据，跳过检查",
        }

    # Determine market context
    ticker_suffix = ticker.split(".")[-1] if "." in ticker else ""
    above_ma200 = price > ma200 if ma200 else None

    if ticker_suffix == "SS" or ticker_suffix == "SZ":
        # A股：2638分界线
        if price <= 2638:
            level = "RED"
            signal = "硬拦截"
            reason = f"上证指数{price:.0f} ≤ 2638，仓位≤30%，不做新增多头"
        elif above_ma200 is False and ma200:
            level = "YELLOW"
            signal = "降仓位"
            reason = f"大盘低于年线(MA200={ma200:.0f})，仓位<30%"
        else:
            level = "GREEN"
            signal = "PASS"
            reason = f"上证{price:.0f} > 2638 + 年线上方"
    else:
        # 港股/美股：年线分界
        if above_ma200 is False and ma200:
            level = "YELLOW"
            signal = "降仓位"
            reason = f"大盘{price:.0f} < 年线(MA200={ma200:.0f})，注意仓位控制"
        else:
            level = "GREEN"
            signal = "PASS"
            reason = f"大盘{price:.0f} 在年线{ma200:.0f}上方" if ma200 else f"大盘{price:.0f}"

    return {
        "check": "no_2638",
        "label": "2638法則/大盘位置",
        "light": level,
        "signal": signal,
        "index_price": price,
        "index_ma200": ma200,
        "above_ma200": above_ma200,
        "reason": reason,
    }


def check_no_chasing(ticker: str) -> dict:
    """DK: no_chasing — 年线检查（个股是否在年线之上追高）"""
    t = yf.Ticker(ticker)
    hist = t.history(period="1y")
    c = hist["Close"]
    price = float(c.iloc[-1])

    try:
        ma200 = float(c.iloc[-200:].mean()) if len(c) >= 200 else None
        ma120 = float(c.iloc[-120:].mean()) if len(c) >= 120 else None
    except (IndexError, ValueError):
        ma200, ma120 = None, None

    if ma200 is None:
        return {
            "check": "no_chasing",
            "label": "年线法则(追高检查)",
            "light": "YELLOW",
            "signal": "数据不足",
            "reason": "年线数据不足(需200个交易日)，跳过检查",
        }

    above_ma200 = price > ma200
    # 年线上方偏离程度
    deviation_pct = (price / ma200 - 1) * 100 if ma200 else 0

    if above_ma200:
        if deviation_pct > 30:
            level = "RED"
            signal = "硬拦截"
            reason = f"价格{price:.2f} 高于年线{ma200:.2f} {deviation_pct:.0f}%，严重追高"
        elif deviation_pct > 15:
            level = "YELLOW"
            signal = "警惕追高"
            reason = f"价格{price:.2f} 高于年线{ma200:.2f} {deviation_pct:.0f}%，不建议重仓"
        else:
            level = "YELLOW"
            signal = "偏高但可接受"
            reason = f"价格{price:.2f} 略高于年线{ma200:.2f}，注意回调风险"
    else:
        level = "GREEN"
        signal = "PASS"
        reason = f"价格{price:.2f} 低于年线{ma200:.2f}，安全边际充足"

    return {
        "check": "no_chasing",
        "label": "年线法则(追高检查)",
        "light": level,
        "signal": signal,
        "price": price,
        "ma200": ma200,
        "above_ma200": above_ma200,
        "deviation_from_ma200_pct": round(deviation_pct, 1),
        "reason": reason,
    }


def check_no_first_mover(ticker: str) -> dict:
    """DK: no_first_mover — 后发制人（右侧确认检查）"""
    t = yf.Ticker(ticker)
    hist = t.history(period="1y")
    c = hist["Close"]
    price = float(c.iloc[-1])

    try:
        ma50 = float(c.iloc[-50:].mean()) if len(c) >= 50 else None
        ma120 = float(c.iloc[-120:].mean()) if len(c) >= 120 else None
        ma200 = float(c.iloc[-200:].mean()) if len(c) >= 200 else None
    except (IndexError, ValueError):
        ma50, ma120, ma200 = None, None, None

    if ma50 is None or ma120 is None:
        return {
            "check": "no_first_mover",
            "label": "后发制人(右侧确认)",
            "light": "YELLOW",
            "signal": "数据不足",
            "reason": "趋势数据不足(需120个交易日)，跳过检查",
        }

    # 右侧信号判断
    price_above_ma50 = price > ma50 if ma50 else None
    ma50_above_ma120 = ma50 > ma120 if ma50 and ma120 else None
    ma120_above_ma200 = ma120 > ma200 if ma120 and ma200 else None

    # 近3月涨幅（判断是否还在做价格发现）
    try:
        price_3mo_ago = float(c.iloc[-66]) if len(c) >= 66 else None
        return_3m = (price / price_3mo_ago - 1) * 100 if price_3mo_ago else None
    except (IndexError, ValueError):
        return_3m = None

    signals = 0
    if price_above_ma50:
        signals += 1
    if ma50_above_ma120:
        signals += 1
    if ma120_above_ma200:
        signals += 1
    if return_3m and return_3m > 0:
        signals += 1

    if signals >= 3:
        level = "GREEN"
        signal = "右侧已确认"
        reason = f"右侧信号{signals}/4满足，大局已定，可以买入"
    elif signals >= 2:
        level = "YELLOW"
        signal = "偏右侧"
        reason = f"右侧信号{signals}/4满足，建议分批建仓，等更多确认"
    elif signals >= 1:
        level = "YELLOW"
        signal = "左侧/价格发现"
        reason = f"右侧信号{signals}/4满足，还在做价格发现，建议等待"
    else:
        level = "RED"
        signal = "左侧下行"
        reason = f"右侧信号{signals}/4满足，均线空头排列，禁止买入"

    return {
        "check": "no_first_mover",
        "label": "后发制人(右侧确认)",
        "light": level,
        "signal": signal,
        "price_above_ma50": price_above_ma50,
        "ma50_above_ma120": ma50_above_ma120,
        "ma120_above_ma200": ma120_above_ma200,
        "return_3m_pct": round(return_3m, 1) if return_3m else None,
        "right_side_signals": signals,
        "right_side_max": 4,
        "reason": reason,
    }


# 文献：波动率→敞口判断属「现金/波动率管理」类 → Moreira-Muir 2017（波动率高时降敞口提升风险调整收益）；
# 反证 Cederburg et al. 2020 JFE（波动率择时样本外不可实施）
def check_divergence_consensus(ticker: str) -> dict:
    """DK: divergence_or_consensus — 买分歧卖共识（分歧/共识判断）"""
    t = yf.Ticker(ticker)
    hist = t.history(period="6mo")
    c = hist["Close"]
    price = float(c.iloc[-1])

    try:
        # 波动率作为分歧/共识的代理指标
        returns = c.pct_change().dropna()
        volatility_6m = float(returns.std() * (252 ** 0.5))  # 年化波动率
        volatility_1m = float(returns.iloc[-22:].std() * (252 ** 0.5)) if len(returns) >= 22 else None
    except (IndexError, ValueError):
        volatility_6m, volatility_1m = None, None

    # 近期涨幅/跌幅（判断是否过热）
    try:
        return_1m = (price / float(c.iloc[-22]) - 1) * 100 if len(c) >= 22 else None
        return_3m = (price / float(c.iloc[-66]) - 1) * 100 if len(c) >= 66 else None
    except (IndexError, ValueError):
        return_1m, return_3m = None, None

    if volatility_6m is None:
        return {
            "check": "divergence_or_consensus",
            "label": "买分歧卖共识",
            "light": "YELLOW",
            "signal": "数据不足",
            "reason": "波动率数据不足，跳过检查",
        }

    # 判断分歧 vs 共识
    # 高波动 + 价格无明显方向 = 分歧
    # 低波动 + 趋势明确 = 共识
    # 异常高波动 = 恐慌/狂热
    if volatility_6m > 0.6:
        # 超高波动
        if return_1m and return_1m > 20:
            level = "RED"
            signal = "狂热(警惕)"
            reason = f"年化波动率{volatility_6m:.0%}异常高 + 月涨{return_1m:.0f}%，市场狂热，一致看多危险"
        elif return_1m and return_1m < -15:
            level = "YELLOW"
            signal = "恐慌(机会?)"
            reason = f"年化波动率{volatility_6m:.0%}高 + 月跌{return_1m:.0f}%，恐慌抛售中，需要分辨是真跌还是错杀"
        else:
            level = "YELLOW"
            signal = "分歧偏大"
            reason = f"年化波动率{volatility_6m:.0%}，市场存在显著分歧，注意方向选择"
    elif volatility_6m > 0.35:
        if return_1m and return_1m > 10:
            level = "YELLOW"
            signal = "共识偏多"
            reason = f"波动率{volatility_6m:.0%}中等 + 上涨中，市场正在形成共识，安全边际在缩小"
        elif return_1m and return_1m < -10:
            level = "YELLOW"
            signal = "共识偏空"
            reason = f"波动率{volatility_6m:.0%}中等 + 下跌中，市场一致看空，可能有错杀机会"
        else:
            level = "GREEN"
            signal = "存在分歧"
            reason = f"波动率{volatility_6m:.0%}适中 + 价格震荡，市场存在分歧，安全边际来源充足"
    else:
        # 低波动
        if return_1m and abs(return_1m) < 5:
            level = "YELLOW"
            signal = "共识(无人讨论)"
            reason = f"波动率仅{volatility_6m:.0%}，市场已形成共识或无人关注，缺少安全边际来源"
        else:
            level = "GREEN"
            signal = "存在分歧"
            reason = f"波动率{volatility_6m:.0%}偏低但有方向，分歧尚存"

    return {
        "check": "divergence_or_consensus",
        "label": "买分歧卖共识",
        "light": level,
        "signal": signal,
        "volatility_annualized_6m": round(volatility_6m, 3),
        "volatility_annualized_1m": round(volatility_1m, 3) if volatility_1m else None,
        "return_1m_pct": round(return_1m, 1) if return_1m else None,
        "return_3m_pct": round(return_3m, 1) if return_3m else None,
        "reason": reason,
    }


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: fengrule.py TICKER"}, indent=2))
        sys.exit(1)

    ticker = sys.argv[1].upper()

    results = {
        "ticker": ticker,
        "checked_at": datetime.now().isoformat(),
        "rules": [
            check_no_knife(ticker),
            check_no_fomo(ticker),
            check_no_leverage(ticker),
            check_true_value(ticker),
            check_no_2638(ticker),
            check_no_chasing(ticker),
            check_no_first_mover(ticker),
            check_divergence_consensus(ticker),
        ],
    }

    # Overall L1 status: worst light
    light_order = {"GREEN": 0, "YELLOW": 1, "RED": 2}
    lights = [r["light"] for r in results["rules"]]
    worst = max(lights, key=lambda x: light_order.get(x, 0))
    results["overall_light"] = worst
    results["overall_status"] = {
        "GREEN": "全部通过",
        "YELLOW": "条件通过",
        "RED": "硬拦截",
    }[worst]

    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
