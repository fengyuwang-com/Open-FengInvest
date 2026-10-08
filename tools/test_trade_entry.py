#!/usr/bin/env python3
"""test_trade_entry — fengholding.validate_holding 的 trade_entry 快速自测（纯本地，无网络）

覆盖：TRADING 账户 ①无 trade_entry（旧 JSON 向后兼容，不应报硬错）②含完整 trade_entry（无建议警告）
      ③只有空 trade_entry {}（不硬错，但给补齐提示）。

用法:
    python tools/test_trade_entry.py
"""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fengholding import validate_holding

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} -- {detail}")


def te_triggers_present(warnings):
    return any("trade_entry" in w for w in warnings)


def base_trading():
    """最小合法 TRADING 持仓（满足 validate_holding 全部必填，可复制使用）。"""
    return {
        "id": "TEST.TRADE",
        "name": "自测交易标",
        "asset_type": "stock",
        "currency": "USD",
        "capital_zone": "OVERSEAS",
        "market": "US",
        "segment": "动量/事件",
        "broker": "TESTBROKER",
        "account_type": "TRADING",
        "position": {"shares": 200, "avg_cost": 360.0},
        "capital": {"total_invested": 72000, "total_fees": 30, "total_dividends": 0,
                    "realized_pl": 0, "cost_basis": 72000, "currency": "USD"},
        "triggers": {"stop_loss_pct": -0.20, "thesis_invalidation": False,
                     "next_review_date": "2026-11-18", "price_up_alert": 0.15, "price_down_alert": -0.10},
        "reviews": [],
        "meta": {"created_at": "2026-08-20", "updated_at": "2026-08-20", "version": 1},
    }


def test_without_trade_entry():
    print("  --- 1) TRADING 无 trade_entry（旧 JSON 兼容） ---")
    for w in validate_holding(base_trading())[1]:
        print(f"       ~ {w}")
    errors, warnings = validate_holding(base_trading())
    check("无硬错（不强制、不堵塞）", not errors, str(errors))
    check("给出友好建议（trade_entry 提示）", te_triggers_present(warnings), str(warnings))


def test_with_full_trade_entry():
    print("  --- 2) TRADING 含完整 trade_entry ---")
    h = base_trading()
    h["trade_entry"] = {
        "entry_trigger": "右侧突破：周线站上 60 日高点 + 放量确认",
        "stop_line": 288.0,
        "time_window": "3个月",
        "disproof_trigger": "重组失败/业绩证伪/题材降温",
        "rollover_line": 432.0,
    }
    errors, warnings = validate_holding(h)
    check("无硬错", not errors, str(errors))
    check("无 trade_entry 建议警告", not te_triggers_present(warnings), str(warnings))


def test_empty_trade_entry():
    print("  --- 3) TRADING 只有空 trade_entry {} ---")
    h = base_trading()
    h["trade_entry"] = {}
    errors, warnings = validate_holding(h)
    check("无硬错（向后兼容）", not errors, str(errors))
    check("给补齐提示（缺 entry_trigger/stop_line）", te_triggers_present(warnings), str(warnings))


def test_non_trading_ignored():
    print("  --- 4) INVESTMENT 账户不受影响（无 trade_entry 提示） ---")
    h = base_trading()
    h["account_type"] = "INVESTMENT"
    errors, warnings = validate_holding(h)
    check("无硬错", not errors, str(errors))
    check("无 trade_entry 提示", not te_triggers_present(warnings), str(warnings))


def main():
    print("trade_entry 快速自测 — fengholding.validate_holding")
    print("=" * 60)
    test_without_trade_entry()
    test_with_full_trade_entry()
    test_empty_trade_entry()
    test_non_trading_ignored()
    print("=" * 60)
    total = PASS + FAIL
    print(f"  结果: {PASS}/{total} 通过" + (f"，{FAIL} 失败!" if FAIL else "，全部通过"))
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
