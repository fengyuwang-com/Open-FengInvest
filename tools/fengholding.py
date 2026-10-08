#!/usr/bin/env python3
"""
fengholding — 持仓登记/查询/校验（持仓域唯一入口）

Unix 单一职责：只做持仓域的事 —— 登记分析/SCHEMA 校验/查询/组合影响。
不抓价格（交给 fengdata）、不算退出规则（交给 fengwatch）、不跑组合盘面（交给 fengportfolio）。

Commands:
  add <TICKER> [--file FILE]   登记分析（四段：① SCHEMA 校验 → ② 价格核对 → ③ thesis 联动 → ④ 组合影响）
                              校验通过后回写默认字段（capital_zone 推断/triggers 初始化/meta 时间戳）
  validate [--all|--file FILE] 存量持仓 SCHEMA 校验（硬错 → 退出码 2）
  list [--all]                 列出持仓（默认风险口径=排除真现金；--all 含现金 = 14 全量）
  get <TICKER>                 查询单个持仓（id 优先，修 h['ticker'] 隐患）

输出契约：stdout 单 JSON 文档；退出码 0=成功 1=错误 2=校验失败/被拦截。
"""
import json, os, re, subprocess, sys
from datetime import date, datetime, timedelta

# Windows GBK fix
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOLDINGS_DIR = os.path.join(BASE, "holdings")
TOOLS = os.path.join(BASE, "tools")
FENGDATA = os.path.join(TOOLS, "fengdata.py")
FENGPORTFOLIO = os.path.join(TOOLS, "fengportfolio.py")
RESEARCH_060 = os.path.join(BASE, "research", "060-companies")

# ─── ① SCHEMA 校验 ─────────────────────────────────────────────

ASSET_TYPES = {"stock", "fund", "cash", "deposit", "bond", "other"}
ZONES = {"CN_IN", "OVERSEAS"}
MARKETS = {"CN_A", "CN_HK", "CN_OVS", "US", "GLOBAL"}
POSITION_KEYS = {
    "stock":   ["shares", "avg_cost"],
    "fund":    ["units", "nav"],
    "cash":    ["amount"],
    "deposit": ["principal", "rate"],
    "bond":    ["face_value", "price", "quantity"],
    "other":   ["cost"],
}
# TRADING 交易钱包 trade_entry 建议必填（不强制，向后兼容）：触发源 + 机械止损线
TRADE_ENTRY_SUGGESTED = ("entry_trigger", "stop_line")


def infer_capital_zone(h):
    """capital_zone 推断：CNY→CN_IN；HKD/USD→OVERSEAS；港股通手动 CN_IN+market_access=hksi。显式优先。"""
    explicit = h.get("capital_zone")
    if explicit in ZONES:
        return explicit, None
    cur = (h.get("currency") or "CNY").upper()
    if cur == "CNY":
        return "CN_IN", "按币种推断: CNY → CN_IN"
    if cur in ("HKD", "USD"):
        return "OVERSEAS", f"按币种推断: {cur} → OVERSEAS"
    return explicit, f"无法推断 capital_zone（币种 {cur} 未知），请显式填写"


def validate_holding(h, ticker=None):
    """SCHEMA 校验。返回 (hard_errors[], warnings[])。"""
    errors, warnings = [], []
    hid = h.get("id") or ticker or "?"

    # 必填基础字段
    for k in ("id", "name", "asset_type", "currency"):
        if not h.get(k):
            errors.append(f"缺少必填字段: {k}")
    if h.get("asset_type") and h["asset_type"] not in ASSET_TYPES:
        errors.append(f"asset_type 非法: {h['asset_type']}（可选: {sorted(ASSET_TYPES)}）")

    # 正交维度：权益必标 market/segment；现金也应有 market（资金池归属）
    if not h.get("market"):
        errors.append("缺少 market（资产类别: CN_A/CN_HK/CN_OVS/US/GLOBAL，可扩展）")
    elif h.get("market") and h["market"] not in MARKETS:
        warnings.append(f"market 不在参考词汇 {sorted(MARKETS)}，如为新扩展请确认拼写")
    if not h.get("segment"):
        errors.append("缺少 segment（细分板块，粒度需区分风险驱动）")

    # capital_zone：缺省推断（不报错，add 时回写）
    if not h.get("capital_zone"):
        inferred, note = infer_capital_zone(h)
        if note:
            warnings.append(f"capital_zone 缺失：{note}")

    # position 按资产类型
    pos = h.get("position") or {}
    if not isinstance(pos, dict) or not pos:
        errors.append("position 为空或缺失")
    else:
        at = h.get("asset_type", "stock")
        missing = [k for k in POSITION_KEYS.get(at, []) if k not in pos]
        if missing:
            errors.append(f"position 缺少 {at} 类型必填键: {missing}（参考 SCHEMA.md）")

    # capital / capital_rollover
    if not h.get("capital"):
        warnings.append("缺少 capital（财务追踪；成本基数/已实现盈亏将不可用）")
    if not h.get("capital_rollover"):
        warnings.append("缺少 capital_rollover（钱仓滚存；缺省按风险资本处理）")

    # 汇率快照：非 CNY 资产必须有折算汇率（人民币一盘棋）
    cur = (h.get("currency") or "CNY").upper()
    fx = (h.get("meta") or {}).get("fx_rates") or {}
    if cur != "CNY" and not fx:
        warnings.append(f"非 CNY 资产缺 meta.fx_rates 汇率快照（人民币等值折算不可用，跑 fengdata fx 后回填）")

    # thesis / triggers / reviews 结构（SCHEMA 定义了，缺省给默认值不阻塞；现金类资产不需要论文）
    is_cash = h.get("asset_type") == "cash"
    if not is_cash and not isinstance(h.get("thesis"), dict):
        warnings.append("thesis 缺失（投资论点；买入后应回填 original/exit_conditions）")
    elif not is_cash:
        the = h["thesis"]
        if not (the.get("original") or "").strip() or the.get("original") in ("券商导入初始记录", "券商导入待补", "待补"):
            warnings.append("thesis.original 为空或占位文本 —— 亏损持有无论文支撑=处置效应风险（Odean 1998），需走七层框架补齐")
        if not the.get("redlines"):
            warnings.append("thesis.redlines 为空 —— 证伪条件必填（add 新登记将拒绝）")
    if not isinstance(h.get("triggers"), dict):
        warnings.append("triggers 缺失（触发条件；add 会自动初始化默认值）")
    if not isinstance(h.get("reviews"), list):
        warnings.append("reviews 缺失（复盘记录应始终为数组）")

    # trade_entry（TRADING 交易钱包专用，可选）：无字段不阻塞；TRADING 建议补 entry_trigger+stop_line
    if h.get("account_type") == "TRADING":
        te = h.get("trade_entry")
        if not isinstance(te, dict) or not te:
            warnings.append("TRADING 账户建议补 trade_entry.entry_trigger 与 stop_line —— 交易纪律机械止损是唯一退出按钮（不强制；见 SCHEMA.md trade_entry 节）")
        else:
            for k in TRADE_ENTRY_SUGGESTED:
                if not (te.get(k) or ""):
                    warnings.append(f"trade_entry.{k} 为空 —— 建议补齐触发源/机械止损线（见 SCHEMA.md trade_entry 节）")

    return errors, warnings


# ─── 数据加载（id 优先，修 h['ticker'] 隐患） ───────────────────

def _holding_id(h):
    return h.get("id") or h.get("ticker") or "?"


def load_all():
    """全部活跃持仓（含现金）。"""
    out = []
    closed_re = re.compile(r"^hold_.+_closed_\d{4}-\d{2}-\d{2}\.json$")
    for f in sorted(os.listdir(HOLDINGS_DIR)):
        m = re.match(r"^hold_(.+)\.json$", f)
        if m and not closed_re.match(f):
            try:
                with open(os.path.join(HOLDINGS_DIR, f), encoding="utf-8") as fh:
                    out.append(json.load(fh))
            except (json.JSONDecodeError, OSError) as e:
                out.append({"_file_error": str(e), "_file": f})
    return out


def _is_cash(h):
    return h.get("qualifier") == "cash" or h.get("asset_type") == "cash"


def risk_holdings():
    """风险口径：排除真现金（=11 权益+准现金；全量 14 含现金）。"""
    return [h for h in load_all() if not _is_cash(h)]


def load_one(ticker):
    f = os.path.join(HOLDINGS_DIR, f"hold_{ticker}.json")
    if not os.path.exists(f):
        return None, f
    try:
        with open(f, encoding="utf-8") as fh:
            return json.load(fh), f
    except (json.JSONDecodeError, OSError) as e:
        return {"_file_error": str(e)}, f


# ─── ② 价格核对（子进程调 fengdata，Unix 管道） ─────────────────

def _run_json(cmd_args, timeout=90):
    try:
        r = subprocess.run(
            [sys.executable] + cmd_args,
            capture_output=True, text=True, timeout=timeout, encoding="utf-8",
        )
        m = re.search(r"\{[\s\S]*\}", r.stdout)
        return json.loads(m.group(0)) if m else None
    except Exception:
        return None


def check_price(h, ticker):
    """实时价 vs 登记价偏差（防手误/过时价）+ 汇率快照新鲜度。"""
    notes = []
    pos = h.get("position", {})
    file_px = pos.get("current_price") or pos.get("nav") or pos.get("amount")
    avg_cost = pos.get("avg_cost") or pos.get("nav")
    live_px = None
    if h.get("asset_type") not in ("cash", "deposit", "bond", "other"):
        d = _run_json([FENGDATA, ticker, "--mode", "price"])
        if d:
            live_px = (d.get("price") or {}).get("price")

    if file_px and live_px and file_px > 0:
        diff = round((live_px - file_px) / file_px * 100, 1)
        if abs(diff) > 10:
            notes.append(f"⚠️ 登记价 {file_px} 与实时价 {live_px} 偏差 {diff:+.1f}% —— 可能用了过时价/手误")
        else:
            notes.append(f"登记价核对通过（实时 {live_px}，偏差 {diff:+.1f}%）")
    elif live_px:
        notes.append(f"实时价 {live_px}（文件未登记现价，可回填 current_price）")
    else:
        notes.append("⚠️ 实时价获取失败（离线？将依赖文件登记价）")

    if avg_cost and live_px and avg_cost > 0:
        notes.append(f"当前浮盈 {(live_px - avg_cost) / avg_cost * 100:+.1f}%（成本 {avg_cost} vs 实时 {live_px}）")

    # 汇率快照新鲜度
    cur = (h.get("currency") or "CNY").upper()
    fx = (h.get("meta") or {}).get("fx_rates") or {}
    fx_date = fx.get("date")
    if cur != "CNY":
        if not fx_date:
            notes.append("⚠️ 缺 meta.fx_rates 汇率快照（建议 fengdata fx 后回填）")
        else:
            try:
                age = (date.today() - datetime.strptime(fx_date, "%Y-%m-%d").date()).days
                if age > 7:
                    notes.append(f"⚠️ 汇率快照 {fx_date} 已 {age} 天，建议刷新（fengdata fx）")
                else:
                    notes.append(f"汇率快照 {fx_date}（{age} 天前）")
            except ValueError:
                notes.append(f"⚠️ 汇率快照日期格式异常: {fx_date}")

    return {"live_price": live_px, "file_price": file_px, "notes": notes}


# ─── ③ thesis 联动 ─────────────────────────────────────────────

def check_thesis(h, ticker):
    """检测 research/060-companies/<TICKER>-*/ 研究产物 → 回填提示。"""
    notes = []
    the = h.get("thesis") or {}
    prefix = f"{ticker}-"
    dirs = []
    if os.path.isdir(RESEARCH_060):
        for d in sorted(os.listdir(RESEARCH_060)):
            if d.startswith(prefix):
                dirs.append(d)

    if dirs:
        notes.append(f"已找到研究目录: {', '.join(dirs)}")
        # 找最新一期的 07-report / thesis
        latest = None
        for d in dirs:
            base = os.path.join(RESEARCH_060, d)
            for sub in sorted(os.listdir(base), reverse=True):
                cand = os.path.join(base, sub)
                if os.path.isdir(cand):
                    latest = cand
                    break
            if latest:
                break
        if latest:
            report = os.path.join(latest, "07-report.md")
            if os.path.exists(report):
                notes.append(f"L4 报告: {os.path.relpath(report, BASE)}（买入论点/目标仓位可回填 thesis）")
            thesis_md = os.path.join(latest, "thesis.md")
            if os.path.exists(thesis_md):
                notes.append(f"thesis 文件: {os.path.relpath(thesis_md, BASE)}")
    else:
        notes.append(f"未找到 research/060-companies/{ticker}-* 研究目录（如为存量标的可后续补 P 层）")

    if not the.get("original"):
        notes.append("⚠️ thesis.original 为空 —— 买入论点未回填（见 060-companies 研究报告）")
    if not the.get("exit_conditions"):
        notes.append("⚠️ thesis.exit_conditions 为空 —— 退出条件未定义（应至少 2-3 条）")
    if the.get("benchmark") and not the.get("valuation_gap") and the.get("benchmark") != "MSFT":
        notes.append(f"⚠️ benchmark={the['benchmark']} 但缺 valuation_gap（预期价差，用于估值回归检查）")

    return {"research_dirs": dirs, "thesis_filled": bool(the.get("original")), "notes": notes}


# ─── ④ 组合影响（登记后集中度 delta + 资金池 + 预算） ───────────

THRESHOLDS = {  # 占总资产 %：黄 / 红（docs/09-portfolio.md）
    "market": (28, 35), "segment": (20, 25), "combo": (15, 20), "single": (15, 20),
}


def _fx_map():
    d = _run_json([FENGDATA, "fx"], timeout=60) or {}
    return {"CNY": 1.0,
            "HKD": d.get("HKDCNY"),
            "USD": d.get("USDCNY"),
            "CNH": d.get("USDCNY"),
            "CNY_OFFSHORE": d.get("USDCNY")}


def _norm_positions(holdings):
    """按 fengportfolio 口径规范化持仓（含人民币等值）。"""
    fx = _fx_map()
    out = []
    for h in holdings:
        cur = (h.get("currency") or "CNY").upper()
        fxr = fx.get(cur) or 1.0
        p = h.get("position", {})
        qty = p.get("shares") or p.get("units") or 0
        avg = p.get("avg_cost") or p.get("nav") or p.get("amount") or 0
        px = p.get("current_price") or p.get("nav") or p.get("amount") or 0
        mv = p.get("market_value") or (qty * px if qty and px else 0) or p.get("amount") or 0
        out.append({
            "id": _holding_id(h), "name": h.get("name", ""),
            "asset_type": h.get("asset_type", "stock"), "currency": cur,
            "zone": h.get("capital_zone") or ("CN_IN" if cur == "CNY" else "OVERSEAS"),
            "market": h.get("market", "其他"), "segment": h.get("segment", "其他"),
            "qualifier": h.get("qualifier"),
            "market_value_cny": round(mv * fxr, 2),
            "market_access": h.get("market_access"),
        })
    return out


def _pct_status(pct, th):
    yellow, red = th
    if pct > red:
        return "🔴"
    if pct > yellow:
        return "🟡"
    return "🟢"


def portfolio_impact(holdings, new_h, fx_note=None):
    """登记新持仓后的集中度 delta + 资金池 + 预算。返回影响报告。"""
    base = _norm_positions(holdings)
    new_pos = _norm_positions([new_h])[0]

    def conc(plist):
        total = sum(p["market_value_cny"] for p in plist) or 1
        equity = [p for p in plist if not (p["qualifier"] in ("cash", "quasi_cash") or p["asset_type"] == "cash")]
        pool = [p for p in plist if p["qualifier"] in ("cash", "quasi_cash") or p["asset_type"] == "cash"]
        pool_cash = sum(p["market_value_cny"] for p in pool if p["qualifier"] == "cash" or p["asset_type"] == "cash")
        pool_quasi = sum(p["market_value_cny"] for p in pool if p.get("qualifier") == "quasi_cash")

        def axis(key):
            d = {}
            for p in plist:
                d[p[key]] = d.get(p[key], 0) + p["market_value_cny"]
            return {k: round(v / total * 100, 1) for k, v in sorted(d.items(), key=lambda x: -x[1])}

        singles = {}
        for p in plist:
            singles[p["id"]] = singles.get(p["id"], 0) + p["market_value_cny"]
        return {
            "total": total,
            "equity_pct": round(sum(p["market_value_cny"] for p in equity) / total * 100, 1),
            "pool_pct": round(sum(p["market_value_cny"] for p in pool) / total * 100, 1),
            "pool_cash_pct": round(pool_cash / total * 100, 1),
            "pool_quasi_pct": round(pool_quasi / total * 100, 1),
            "market": axis("market"), "segment": axis("segment"),
            "combo": {},
            "single": {k: round(v / total * 100, 1) for k, v in singles.items()},
        }

    def combo_axis(plist, total):
        d = {}
        for p in plist:
            k = f"{p['market']}×{p['segment']}"
            d[k] = d.get(k, 0) + p["market_value_cny"]
        return {k: round(v / total * 100, 1) for k, v in sorted(d.items(), key=lambda x: -x[1])}

    before = conc(base)
    after_l = base + [new_pos]
    after = conc(after_l)
    after["combo"] = combo_axis(after_l, after["total"])

    def delta(key, axis_name):
        b = before.get(key, {}).get(axis_name, 0)
        a = after.get(key, {}).get(axis_name, 0)
        return {"before": b, "after": a, "delta": round(a - b, 1)}

    report = {
        "new_position": {
            "id": new_pos["id"], "market": new_pos["market"],
            "segment": new_pos["segment"], "qualifier": new_pos["qualifier"],
            "zone": new_pos["zone"], "market_value_cny": new_pos["market_value_cny"],
        },
        "is_pool": new_pos["qualifier"] in ("cash", "quasi_cash") or new_pos["asset_type"] == "cash",
        "market_axis": {k: delta("market", k) for k in before["market"]} ,
        "segment_axis": {k: delta("segment", k) for k in before["segment"]},
        "combo_axis": {k: delta("combo", k) for k in before["combo"]},
        "single": delta("single", new_pos["id"]),
        "pool": {
            "before_pct": before["pool_pct"], "after_pct": after["pool_pct"],
            "pool_cash_pct": after["pool_cash_pct"], "pool_quasi_pct": after["pool_quasi_pct"],
        },
        "equity_pct": {"before": before["equity_pct"], "after": after["equity_pct"]},
        "budget": {},
        "correlation": {"checked": False, "note": ""},
        "warnings": [],
    }

    # 集中度状态（新仓位后）
    for axis_name, th in [("market", THRESHOLDS["market"]), ("segment", THRESHOLDS["segment"])]:
        pct = after[axis_name].get(new_pos[axis_name], 0)
        if pct > th[1]:
            report["warnings"].append(f"登记后 {axis_name} 轴「{new_pos[axis_name]}」占 {pct}% 🔴 超红限 {th[1]}%")
        elif pct > th[0]:
            report["warnings"].append(f"登记后 {axis_name} 轴「{new_pos[axis_name]}」占 {pct}% 🟡 超黄限 {th[0]}%")
    combo_pct = after["combo"].get(f"{new_pos['market']}×{new_pos['segment']}", 0)
    if combo_pct > THRESHOLDS["combo"][1]:
        report["warnings"].append(f"登记后组合轴 {new_pos['market']}×{new_pos['segment']} 占 {combo_pct}% 🔴 超红限 {THRESHOLDS['combo'][1]}%")
    elif combo_pct > THRESHOLDS["combo"][0]:
        report["warnings"].append(f"登记后组合轴 {new_pos['market']}×{new_pos['segment']} 占 {combo_pct}% 🟡 超黄限 {THRESHOLDS['combo'][0]}%")
    single_pct = after["single"].get(new_pos["id"], 0)
    if single_pct > THRESHOLDS["single"][1]:
        report["warnings"].append(f"单标 {new_pos['id']} 占 {single_pct}% 🔴 超红限 {THRESHOLDS['single'][1]}%")
    elif single_pct > THRESHOLDS["single"][0]:
        report["warnings"].append(f"单标 {new_pos['id']} 占 {single_pct}% 🟡 超黄限 {THRESHOLDS['single'][0]}%")

    # 资金池语义
    if report["is_pool"]:
        report["warnings"].append("该标的是现金/准现金 —— 进资金池，不参与权益集中度（仅影响买入预算）")

    # 资金墙预算（调 fengportfolio check 拿现网预算数字，登记后扣减）
    pc = _run_json([FENGPORTFOLIO, "check"], timeout=120) or {}
    if pc.get("budget"):
        bd = pc["budget"]
        report["budget"] = {
            "before": bd,
            "after": {z: round(v - new_pos["market_value_cny"], 2) if z == new_pos["zone"] else v
                      for z, v in bd.items()},
            "note": f"新标的本金从 {new_pos['zone']} 池扣减（资金墙=买入预算，不产生风险告警）",
        }

    # 相关性提示（>0.8 降仓位）
    corr = _run_json([FENGPORTFOLIO, "correlate"], timeout=120) or {}
    if corr.get("ok") is False:
        report["correlation"] = {"checked": False, "note": "相关性计算需要 yfinance/pandas（未装，跳过）"}
    elif corr.get("correlations"):
        for pair, v in (corr.get("correlations") or {}).items():
            try:
                if isinstance(v, (int, float)) and abs(v) > 0.8 and new_pos["id"] in pair:
                    report["correlation"] = {"checked": True, "note": f"{pair} 相关系数 {v:.2f} > 0.8 —— 建议降仓位"}
                    break
            except TypeError:
                pass
    if not report["correlation"].get("note"):
        report["correlation"] = {"checked": True, "note": "与现有持仓相关性未超 0.8（或数据不足）"}

    return report


# ─── 默认字段回写（add 时） ─────────────────────────────────────

def apply_defaults(h):
    """回写默认字段：capital_zone 推断 / triggers 初始化 / meta 时间戳。返回 (h, notes)。"""
    notes = []
    zone, note = infer_capital_zone(h)
    if h.get("capital_zone") != zone:
        h["capital_zone"] = zone
        notes.append(f"capital_zone 回写: {zone}（{note}）" if note else f"capital_zone 回写: {zone}")

    if not isinstance(h.get("triggers"), dict) or not h["triggers"]:
        h["triggers"] = {
            "price_up_alert": 0.15,
            "price_down_alert": -0.10,
            "next_review_date": (date.today() + timedelta(days=90)).isoformat(),
            "thesis_invalidation": False,
            "stop_loss_pct": -0.20,
        }
        notes.append(f"triggers 初始化默认（止盈 15% / 止损 10% / 下次回顾 +90 天 = {h['triggers']['next_review_date']}）")
    if not isinstance(h.get("reviews"), list):
        h["reviews"] = []
    if not isinstance(h.get("trades"), list):
        h["trades"] = []
    if not isinstance(h.get("capital_rollover"), dict):
        h["capital_rollover"] = {"total_invested": 0, "recovered": 0, "recoverable_at_price": None,
                                 "zero_cost_shares": 0, "phase": "capital_at_risk"}
        notes.append("capital_rollover 初始化（风险资本阶段）")
    meta = h.setdefault("meta", {})
    meta.setdefault("created_at", date.today().isoformat())
    meta["updated_at"] = date.today().isoformat()
    meta["version"] = int(meta.get("version") or 1)
    return h, notes


# ─── Commands ──────────────────────────────────────────────────

def cmd_add(ticker, file_path=None):
    f = file_path or os.path.join(HOLDINGS_DIR, f"hold_{ticker}.json")
    if not os.path.exists(f):
        print(json.dumps({"error": f"持仓文件不存在: {f}（先写 JSON 再 add 分析）"}, indent=2, ensure_ascii=False))
        return 1
    try:
        with open(f, encoding="utf-8") as fh:
            h = json.load(fh)
    except (json.JSONDecodeError, OSError) as e:
        print(json.dumps({"error": f"JSON 解析失败: {e}"}, indent=2, ensure_ascii=False))
        return 1

    # ① SCHEMA 校验
    errors, warnings = validate_holding(h, ticker)
    report = {"ticker": ticker, "file": os.path.relpath(f, BASE), "validation": {"hard_errors": errors, "warnings": warnings}}

    # ② 价格核对（仅硬错为 0 时才耗时抓价？——抓价始终做，信息最有价值）
    report["price_check"] = check_price(h, ticker)

    # ③ thesis 联动
    report["thesis"] = check_thesis(h, ticker)

    if errors:
        report["action"] = "blocked"
        report["summary"] = "❌ SCHEMA 校验未通过，未回写（先修 hard_errors）"
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 2

    # 证伪条件必填（2026-08-16 定稿）：thesis.redlines 非空否则拒绝登记。
    # 没有可证伪条件的持有 = 没有退出按钮（红线失效只能靠"感情"），宁可不登记。
    redlines = (h.get("thesis") or {}).get("redlines")
    if not redlines:
        report["action"] = "blocked"
        report["summary"] = "❌ thesis.redlines 为空 —— 证伪条件必填（add 拒绝登记，先补 thesis.redlines 再 add）"
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 2

    # ④ 组合影响 + 默认字段回写
    holdings = load_all()
    report["portfolio_impact"] = portfolio_impact(holdings, h)
    h, notes = apply_defaults(h)
    report["defaults_applied"] = notes

    # 回写（校验通过才写）
    with open(f, "w", encoding="utf-8") as fh:
        json.dump(h, fh, indent=2, ensure_ascii=False)
    report["action"] = "registered"
    report["summary"] = f"✅ {ticker} 登记分析完成（{len(errors)} 硬错 / {len(warnings)} 警告 / 默认字段已回写）"
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def cmd_validate(all_flag, file_path=None):
    if file_path:
        targets = []
        try:
            with open(file_path, encoding="utf-8") as fh:
                targets.append((json.load(fh), file_path))
        except (json.JSONDecodeError, OSError) as e:
            print(json.dumps({"error": f"文件读取失败: {e}"}, indent=2, ensure_ascii=False))
            return 1
    else:
        targets = []
        for h in load_all():
            f = os.path.join(HOLDINGS_DIR, f"hold_{_holding_id(h)}.json")
            targets.append((h, f))

    results = []
    n_errors = 0
    for h, f in targets:
        errors, warnings = validate_holding(h)
        hid = _holding_id(h)
        if errors:
            n_errors += 1
        results.append({"id": hid, "file": os.path.basename(f), "errors": errors, "warnings": warnings})
    out = {"validated": len(results), "with_errors": n_errors, "results": results}
    if n_errors:
        out["summary"] = f"{n_errors}/{len(results)} 个持仓有硬错"
    else:
        out["summary"] = f"全部 {len(results)} 个持仓 SCHEMA 校验通过"
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 2 if n_errors else 0


def cmd_list(all_flag):
    holdings = load_all() if all_flag else risk_holdings()
    out = {
        "count": len(holdings),
        "scope": "all(含现金)" if all_flag else "risk(排除真现金)",
        "holdings": [],
    }
    for h in holdings:
        p = h.get("position", {})
        qty = p.get("shares") or p.get("units")
        avg = p.get("avg_cost") or p.get("nav") or p.get("amount")
        px = p.get("current_price") or p.get("nav") or p.get("amount")
        ret = round((px / avg - 1) * 100, 1) if (avg and px) else None
        out["holdings"].append({
            "id": _holding_id(h), "name": h.get("name"), "asset_type": h.get("asset_type"),
            "currency": h.get("currency"), "capital_zone": h.get("capital_zone"),
            "market": h.get("market"), "segment": h.get("segment"), "qualifier": h.get("qualifier"),
            "qty": qty, "avg_cost": avg, "current_price": px, "return_pct": ret,
        })
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def cmd_get(ticker):
    h, f = load_one(ticker)
    if h is None:
        print(json.dumps({"error": f"未找到持仓: {ticker}"}, indent=2, ensure_ascii=False))
        return 1
    if "_file_error" in h:
        print(json.dumps({"error": f"解析失败: {h['_file_error']}"}, indent=2, ensure_ascii=False))
        return 1
    errors, warnings = validate_holding(h, ticker)
    out = {
        "id": _holding_id(h), "file": os.path.relpath(f, BASE),
        "validation": {"hard_errors": errors, "warnings": warnings},
        "holding": h,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 2 if errors else 0


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("add", "validate", "list", "get"):
        print(json.dumps({
            "usage": "fengholding.py add <TICKER> [--file F] | validate [--all|--file F] | list [--all] | get <TICKER>",
            "note": "持仓域唯一入口：登记分析(四段)/SCHEMA 校验/查询。输出单 JSON，退出码 0/1/2。",
        }, indent=2, ensure_ascii=False))
        return 1

    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd == "add":
        if not args:
            print(json.dumps({"error": "用法: fengholding.py add <TICKER> [--file FILE]"}, indent=2, ensure_ascii=False))
            return 1
        ticker = args[0].upper()
        file_path = None
        if "--file" in args:
            file_path = args[args.index("--file") + 1]
        return cmd_add(ticker, file_path)

    if cmd == "validate":
        return cmd_validate("--all" in args, args[args.index("--file") + 1] if "--file" in args else None)

    if cmd == "list":
        return cmd_list("--all" in args)

    if cmd == "get":
        if not args:
            print(json.dumps({"error": "用法: fengholding.py get <TICKER>"}, indent=2, ensure_ascii=False))
            return 1
        return cmd_get(args[0].upper())

    return 1


if __name__ == "__main__":
    sys.exit(main())
