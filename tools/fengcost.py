#!/usr/bin/env python3
"""fengcost.py — 全球交易规费计算模块

三档费率（保守/中性/激进）覆盖 19 个市场，用于回测扣费和成本分析。
数据来源: research/030-asset-classes/trading-costs.md

用法:
    python tools/fengcost.py               # 全部市场成本对照表
    python tools/fengcost.py US 5000       # 美股 $5000 一回合
    python tools/fengcost.py HK 100000 --tier conservative --etf
"""
import argparse, sys

ROUND_TRIP = {
    "CN": {"conservative": 0.0010, "neutral": 0.0015, "aggressive": 0.0025},
    "HK": {"conservative": 0.0022, "neutral": 0.0025, "aggressive": 0.0035},
    "US": {"conservative": 0.0005, "neutral": 0.0010, "aggressive": 0.0015},
    "JP": {"conservative": 0.0008, "neutral": 0.0012, "aggressive": 0.0020},
    "UK": {"conservative": 0.0060, "neutral": 0.0075, "aggressive": 0.0100},
    "DE": {"conservative": 0.0010, "neutral": 0.0015, "aggressive": 0.0025},
    "FR": {"conservative": 0.0035, "neutral": 0.0050, "aggressive": 0.0070},
    "KR": {"conservative": 0.0020, "neutral": 0.0025, "aggressive": 0.0035},
    "IN": {"conservative": 0.0025, "neutral": 0.0030, "aggressive": 0.0040},
    "TW": {"conservative": 0.0030, "neutral": 0.0040, "aggressive": 0.0055},
    "AU": {"conservative": 0.0010, "neutral": 0.0015, "aggressive": 0.0025},
    "SG": {"conservative": 0.0012, "neutral": 0.0018, "aggressive": 0.0028},
    "CH": {"conservative": 0.0015, "neutral": 0.0025, "aggressive": 0.0035},
    "NL": {"conservative": 0.0010, "neutral": 0.0015, "aggressive": 0.0025},
    "ES": {"conservative": 0.0065, "neutral": 0.0080, "aggressive": 0.0105},
    "IT": {"conservative": 0.0015, "neutral": 0.0025, "aggressive": 0.0040},
    "SE": {"conservative": 0.0010, "neutral": 0.0015, "aggressive": 0.0025},
    "NZ": {"conservative": 0.0012, "neutral": 0.0018, "aggressive": 0.0028},
    "CA": {"conservative": 0.0005, "neutral": 0.0010, "aggressive": 0.0020},
}

MARKET_NAMES = {
    "CN": "A股", "HK": "港股", "US": "美股", "JP": "日本", "UK": "英国",
    "DE": "德国", "FR": "法国", "KR": "韩国", "IN": "印度", "TW": "台湾",
    "AU": "澳洲", "SG": "新加坡", "CH": "瑞士", "NL": "荷兰", "ES": "西班牙",
    "IT": "意大利", "SE": "瑞典", "NZ": "新西兰", "CA": "加拿大",
}

ETF_REDUCTION = {
    "CN": 0.0008, "HK": 0.0020, "UK": 0.0050, "FR": 0.0030,
    "TW": 0.0030, "ES": 0.0050,
}

MIN_TRADE = {"CN": 40000, "HK": 50000, "US": 1000}

def round_trip_cost(market: str, amount: float = 1.0, tier: str = "neutral", is_etf: bool = False) -> float:
    costs = ROUND_TRIP.get(market.upper())
    if not costs:
        raise ValueError(f"未知市场: {market}")
    rate = costs[tier]
    if is_etf:
        rate -= ETF_REDUCTION.get(market.upper(), 0.0)
    return max(amount * rate, 0.0)

def single_leg_cost(market: str, amount: float = 1.0, tier: str = "neutral", is_etf: bool = False, side: str = "buy") -> float:
    rt = round_trip_cost(market.upper(), amount, tier, is_etf)
    if market.upper() == "CN":
        return rt * 0.2 if side == "buy" else rt * 0.8
    return rt / 2

def adjust_return(gross_return: float, market: str, tier: str = "neutral", is_etf: bool = False) -> float:
    """从毛回报中扣除一回合交易成本"""
    return gross_return - ROUND_TRIP[market.upper()][tier] + (ETF_REDUCTION.get(market.upper(), 0.0) if is_etf else 0.0)

def validate(market: str, gross_returns: list, tier: str = "neutral", is_etf: bool = False):
    """三档校验：给定收益列表，判断是否能在该费率下盈利"""
    cost = ROUND_TRIP[market.upper()][tier]
    if is_etf:
        cost -= ETF_REDUCTION.get(market.upper(), 0.0)
    net = [r - cost for r in gross_returns]
    avg_net = sum(net) / len(net)
    return avg_net, all(n > 0 for n in net), sum(n > 0 for n in net) / len(net)

def cli_table():
    print(f"{'市场':<6} {'代码':<4} {'保守':<8} {'中性':<8} {'激进':<8} {'最低单笔':<10}")
    print("-" * 44)
    for code in sorted(ROUND_TRIP):
        t = ROUND_TRIP[code]
        mn = f"{MIN_TRADE.get(code, '-'):>8}"
        print(f"{MARKET_NAMES[code]:<6} {code:<4} {t['conservative']:<8.4f} {t['neutral']:<8.4f} {t['aggressive']:<8.4f} {mn}")

def cli_cost(market, amount, tier, is_etf):
    rt_cost = round_trip_cost(market, amount, tier, is_etf)
    buy_cost = single_leg_cost(market, amount, tier, is_etf, "buy")
    sell_cost = single_leg_cost(market, amount, tier, is_etf, "sell")
    label = f"{MARKET_NAMES[market.upper()]}({'ETF' if is_etf else tier})"
    print(f"{label} {market.upper()} {amount:,.0f} 一回合成本:")
    print(f"  买入: {buy_cost:.4f}")
    print(f"  卖出: {sell_cost:.4f}")
    print(f"  合计: {rt_cost:.4f} ({rt_cost / amount * 100:.3f}%)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="全球交易规费计算")
    parser.add_argument("market", nargs="?", help="市场代码 (CN/HK/US/JP/UK/...)")
    parser.add_argument("amount", nargs="?", type=float, help="成交金额")
    parser.add_argument("--tier", default="neutral", choices=["conservative", "neutral", "aggressive"])
    parser.add_argument("--etf", action="store_true", help="免印花税 ETF")
    args = parser.parse_args()
    if not args.market:
        cli_table()
    elif not args.amount:
        print("请指定成交金额"); sys.exit(1)
    else:
        cli_cost(args.market.upper(), args.amount, args.tier, args.etf)
