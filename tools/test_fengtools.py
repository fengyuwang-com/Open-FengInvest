#!/usr/bin/env python3
"""test_fengtools — Integration tests for fengdata.py, fengrule.py, fengquant.py

Usage:
    python tools/test_fengtools.py          # run all tests
    python tools/test_fengtools.py --live   # include live yfinance tests (slow)
"""

import json, os, sys, subprocess, traceback

TOOLS_DIR = os.path.join(os.path.dirname(__file__), "..", "tools")

# Known-good test tickers
TICKER_0700 = "0700.HK"  # Tencent (HK internet)
TICKER_AAPL = "AAPL"     # Apple (US big tech)
TICKER_META = "META"     # Meta (US big tech)

PASS = 0
FAIL = 0
SKIP = 0


def run(cmd: list, timeout=60) -> dict:
    """Run a command and return parsed JSON result."""
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=TOOLS_DIR)
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"_parse_error": True, "stdout": result.stdout[:500], "stderr": result.stderr[:500], "rc": result.returncode}
    data["_rc"] = result.returncode
    data["_stderr"] = result.stderr[:200]
    return data


def check(name: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        name = name.replace("'", "").replace('"', '')
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} -- {detail}")


def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def test_fengdata_price():
    section("fengdata.py — price mode")

    # Normal: basic price data
    r = run(["python", "fengdata.py", TICKER_AAPL, "--price"])
    check("exits 0", r.get("_rc") == 0, str(r.get("_stderr")))
    check("has ticker", "ticker" in r, json.dumps(r.get("_parse_error")))
    check("ticker matches", r.get("ticker") == TICKER_AAPL)
    check("has price field", "price" in r, str(list(r.keys())))
    price = r.get("price", {})
    check("price > 0", isinstance(price.get("price"), (int, float)) and price["price"] > 0)
    check("has ma50", price.get("ma50") is not None)
    check("has ma200", price.get("ma200") is not None)
    check("has 1m return", price.get("return_1m_pct") is not None)
    check("has 6m return", price.get("return_6m_pct") is not None)
    check("has 52w high/low", price.get("high_52w") is not None and price.get("low_52w") is not None)


def test_fengdata_financials():
    section("fengdata.py — financials mode")

    r = run(["python", "fengdata.py", TICKER_AAPL, "--financials"])
    check("exits 0", r.get("_rc") == 0)
    check("has ticker", "ticker" in r)
    fin = r.get("financials", {})
    check("has market_cap", fin.get("market_cap") is not None and fin["market_cap"] > 0)
    check("has trailing_pe", fin.get("trailing_pe") is not None)
    check("has pb", fin.get("pb") is not None)
    check("has roe_pct", fin.get("roe_pct") is not None)
    check("has sector", fin.get("sector") is not None)
    check("has industry", fin.get("industry") is not None)
    check("has revenue_annual list", isinstance(fin.get("revenue_annual"), list) and len(fin["revenue_annual"]) > 0)
    check("has net_income_annual list", isinstance(fin.get("net_income_annual"), list))
    check("has fcf_annual list", isinstance(fin.get("fcf_annual"), list))
    check("has cash_annual list", isinstance(fin.get("cash_annual"), list))


def test_fengdata_all_mode():
    section("fengdata.py — default mode (--all)")

    r = run(["python", "fengdata.py", TICKER_AAPL])
    check("exits 0", r.get("_rc") == 0)
    check("has both price+financials", "price" in r and "financials" in r)


def test_fengdata_invalid():
    section("fengdata.py — error handling")

    r = run(["python", "fengdata.py", "INVALIDZZZ", "--price"])
    # Should either fail gracefully or return error inside JSON
    check("handles invalid ticker gracefully",
          r.get("_parse_error") != True or "error" in r.get("stdout", "").lower())


def test_fengrule():
    section("fengrule.py — L1 discipline check (0700.HK)")

    r = run(["python", "fengrule.py", TICKER_0700])
    check("exits 0", r.get("_rc") == 0)
    check("has ticker", "ticker" in r and r["ticker"] == TICKER_0700)

    rules = r.get("rules", [])
    check("has 4 rules", len(rules) == 4, str(len(rules)))

    # Check each rule
    rule_names = [rule["check"] for rule in rules]
    check("has no_knife", "no_knife" in rule_names)
    check("has no_fomo", "no_fomo" in rule_names)
    check("has no_leverage", "no_leverage" in rule_names)
    check("has true_value", "true_value" in rule_names)

    # Check individual rule structure
    for rule in rules:
        check(f"rule '{rule['check']}' has light", "light" in rule, str(list(rule.keys())))
        check(f"rule '{rule['check']}' has signal", "signal" in rule)
        check(f"rule '{rule['check']}' light valid", rule["light"] in ("GREEN", "YELLOW", "RED"))

    check("has overall_light", "overall_light" in r)
    check("overall light valid", r["overall_light"] in ("GREEN", "YELLOW", "RED"))
    check("has overall_status", "overall_status" in r)


def test_fengrule_apple():
    section("fengrule.py — AAPL")

    r = run(["python", "fengrule.py", TICKER_AAPL])
    check("exits 0", r.get("_rc") == 0)
    check("has ticker", r.get("ticker") == TICKER_AAPL)

    no_knife = [x for x in r.get("rules", []) if x["check"] == "no_knife"]
    if no_knife:
        nk = no_knife[0]
        check("no_knife has price", nk.get("price") is not None and nk["price"] > 0)
        check("no_knife has ma50", nk.get("ma50") is not None)
        check("no_knife has ma120", nk.get("ma120") is not None)


def test_fengrule_no_args():
    section("fengrule.py — no args (should error)")

    r = run(["python", "fengrule.py"])
    check("handles missing args", r.get("_parse_error") != True or "Usage" in r.get("stdout", "") or "error" in r.get("stdout", ""))


def test_fengquant_auto_peers():
    section("fengquant.py — auto peer detection (0700.HK)")

    r = run(["python", "fengquant.py", TICKER_0700])
    check("exits 0", r.get("_rc") == 0)
    check("has ticker", r.get("ticker") == TICKER_0700)

    analysis = r.get("factor_analysis", {})
    check("has target_name", "target_name" in analysis)
    check("method is continuity corrected", "continuity" in analysis.get("method", ""))

    factors = analysis.get("factors", [])
    check("has factors (>0)", len(factors) > 0, str(len(factors)))

    # Check each factor structure
    for f in factors:
        check(f"factor '{f.get('factor')}' has z_score or null",
              f.get("z_score") is None or isinstance(f["z_score"], (int, float)))

        # Bounds check: continuity correction should keep z within [-2.5, 2.5] for n<=7
        z = f.get("z_score")
        if z is not None:
            check(f"z_score {f.get('factor')}={z} within [-1.5,1.5] (continuity corrected)",
                  -1.5 <= z <= 1.5, str(z))

    check("has peer_group list", isinstance(r.get("peer_group"), list) and len(r["peer_group"]) > 0)
    check("has fetched_at", "fetched_at" in r)

    factor_names = [f["factor"] for f in factors]
    check("has value_pe factor", "value_pe" in factor_names)
    check("has quality_roe factor", "quality_roe" in factor_names)


def test_fengquant_manual_peers():
    section("fengquant.py — manual peers")

    r = run(["python", "fengquant.py", TICKER_AAPL, "--peers", "MSFT", "GOOGL"])
    check("exits 0", r.get("_rc") == 0)
    check("ticker matches", r.get("ticker") == TICKER_AAPL)

    factors = r.get("factor_analysis", {}).get("factors", [])
    check("has factors", len(factors) > 0)

    peer_names = r.get("factor_analysis", {}).get("peer_names", [])
    check("has correct peers", "Microsoft" in peer_names[0])


def test_fengquant_group():
    section("fengquant.py — peer group")

    r = run(["python", "fengquant.py", TICKER_AAPL, "--group", "us_bigtech"])
    check("exits 0", r.get("_rc") == 0)

    factors = r.get("factor_analysis", {}).get("factors", [])
    check("has factors", len(factors) > 0)

    peer_count = r.get("factor_analysis", {}).get("peer_count", 0)
    check("has multiple peers for us_bigtech group", peer_count >= 4, str(peer_count))


def test_fengquant_list():
    section("fengquant.py — --list")

    r = run(["python", "fengquant.py", "--list"])
    check("exits 0", r.get("_rc") == 0)
    check("has known_stocks", "known_stocks" in r)
    check("has peer_groups", "peer_groups" in r)
    check("known_stocks not empty", len(r.get("known_stocks", {})) > 10)


def test_fengquant_hk_internet():
    section("fengquant.py — HK internet ticker with group")

    r = run(["python", "fengquant.py", "9988.HK", "--group", "hk_internet"])
    check("exits 0", r.get("_rc") == 0)
    check("has ticker", r.get("ticker") == "9988.HK")
    factors = r.get("factor_analysis", {}).get("factors", [])
    check("has factors", len(factors) > 0)

    for f in factors:
        z = f.get("z_score")
        if z is not None:
            check(f"z within [-1.5,1.5] (continuity corrected) for {f['factor']}",
                  -1.5 <= z <= 1.5, str(z))


def test_zscore_small():
    section("fengquant.py — continuity correction standalone test")

    # Import and test the zscore_small function directly
    sys.path.insert(0, TOOLS_DIR)
    from fengquant import zscore_small

    # Test: identical values should give z ≈ 0
    arr = [10, 20, 30, 40, 50]
    z_mid = zscore_small(30, arr)
    check("middle value ≈ 0", -0.7 < z_mid < 0.7, str(z_mid))

    # Test: max value should not exceed ~2.3 for n=5
    z_max = zscore_small(50, arr)
    check("max value bounded for n=5", z_max < 2.5, str(z_max))

    # Test: min value should not exceed ~-2.3 for n=5
    z_min = zscore_small(10, arr)
    check("min value bounded for n=5", z_min > -2.5, str(z_min))

    # Test: n=1 should return 0
    z_single = zscore_small(42, [42])
    check("single element gives 0", z_single == 0.0, str(z_single))

    # Test: n=2 extreme gets ~±1.5
    z_extreme = zscore_small(100, [10, 100])
    check("n=2 extreme ±1.5-ish", z_extreme > 0.5, str(z_extreme))

    # Test: all same values (zero variance — continuity correction gives z=1.15,
    # which is the maximum for n=4, since rank=4 => pct=0.875)
    z_same = zscore_small(50, [50, 50, 50, 50])
    check("all same values bounded < 1.5", z_same < 1.5, str(z_same))

    # Test: n=3 lowest value should be ~-0.97 (was -3.09 before continuity fix)
    z_n3_low = zscore_small(10, [20, 30, 40])
    check("n=3 low ≈ -0.97", -1.1 < z_n3_low < -0.8, str(z_n3_low))

    # Test: n=6 highest should be ~1.38 (was 3.09 before continuity fix)
    z_n6_high = zscore_small(100, [10, 20, 30, 40, 50, 60])
    check("n=6 high ≈ 1.38", 1.2 < z_n6_high < 1.5, str(z_n6_high))


def test_fengquant_no_args():
    section("fengquant.py — no args (should error)")

    r = run(["python", "fengquant.py"])
    check("handles missing args", r.get("_parse_error") != True or "error" in r.get("stdout", "").lower() or "Usage" in r.get("stdout", ""))


def main():
    print(f"{'#'*60}")
    print(f"  FengInvest — 工具集成测试套件")
    print(f"  Test time: 2026-07-11")
    print(f"{'#'*60}")

    # Unit tests for zscore (no network needed)
    test_zscore_small()

    # fengdata tests
    test_fengdata_price()
    test_fengdata_financials()
    test_fengdata_all_mode()
    test_fengdata_invalid()

    # fengrule tests
    test_fengrule()
    test_fengrule_apple()
    test_fengrule_no_args()

    # fengquant tests
    test_fengquant_auto_peers()
    test_fengquant_manual_peers()
    test_fengquant_group()
    test_fengquant_list()
    test_fengquant_hk_internet()
    test_fengquant_no_args()

    # Summary
    total = PASS + FAIL
    print(f"\n{'='*60}")
    print(f"  Test Summary: {PASS}/{total} passed", end="")
    if FAIL > 0:
        print(f", {FAIL} FAILED!")
    else:
        print(f", ALL PASSED!")
    print(f"{'='*60}")

    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
