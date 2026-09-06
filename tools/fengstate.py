#!/usr/bin/env python3
"""
FengInvest 状态机引擎 — 强制七层按序执行。

每个 skill 入口先 fengstate.py check, 出口 fengstate.py complete。
状态文件 (research/temp_state_<TICKER>.json) 是唯一 truth，物理卡死跳步。
"""
import json, os, re, shutil, subprocess, sys
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESEARCH = os.path.join(BASE, "research")
STATE_DIR = os.path.join(RESEARCH, "state")
KNOWLEDGE = os.path.join(BASE, "knowledge")
DOCS = os.path.join(BASE, "docs")
SEARCH_KING = os.environ.get("SEARCH_KING_DIR", os.path.expanduser("~/FengProj/Search-King/scraper.py"))

# 八层顺序（04-quantitative/05-qualitative 在 03-discipline 后可并行，08-portfolio 在 07-report 后）
SEQUENCE = ["01-capability", "02-market", "03-discipline", "04-quantitative",
            "05-qualitative", "06-collision", "07-report", "08-portfolio"]

# 可跳步的层（L0 判定 "不懂" 时自动跳过）
SEQUENCE_SKIPPABLE = {"02-market", "03-discipline", "04-quantitative", "05-qualitative",
                       "06-collision", "07-report", "08-portfolio"}

# 每层的前置条件：必须全部完成才能进入本层
PREREQUISITES = {
    "01-capability": [],         # 只需状态文件存在（入口 init）
    "02-market":     ["01-capability"],
    "03-discipline": ["02-market"],
    "04-quantitative": ["02-market", "03-discipline"],
    "05-qualitative": ["03-discipline"],
    "06-collision":  ["03-discipline", "04-quantitative", "05-qualitative"],  # 并行分支必须都完成
    "07-report":     ["06-collision"],
    "08-portfolio":  ["07-report"],
}

def _sp(ticker):
    return os.path.join(STATE_DIR, f"temp_state_{ticker.upper()}.json")

def _log_path(ticker):
    return os.path.join(STATE_DIR, f"log_{ticker.upper()}.jsonl")

def _log_event(ticker, event_type, step, result, detail=""):
    """追加执行日志到 research/state/log_<TICKER>.jsonl"""
    log_file = _log_path(ticker)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        "step": step,
        "result": result,
        "detail": detail,
    }
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def _pre_flight():
    """执行环境预检（init/renew 时调用）。失败只报 WARN 不阻塞。"""
    checks = []
    # 1) Search-King 可用性
    if os.path.exists(SEARCH_KING):
        try:
            r = subprocess.run(
                [sys.executable, SEARCH_KING, "--check"],
                capture_output=True, text=True, timeout=10
            )
            checks.append(("Search-King", "✅" if r.returncode == 0 else "⚠️ 不可用"))
        except Exception:
            checks.append(("Search-King", "⚠️ 调用异常"))
    else:
        checks.append(("Search-King", "❌ 文件不存在"))

    # 2) knowledge/ 目录完整性
    required_principles = ["坐标原则.md", "家国原则.md", "息价原则.md", "取舍原则.md"]
    princ_dir = os.path.join(KNOWLEDGE, "principles")
    if os.path.isdir(princ_dir):
        for p in required_principles:
            fp = os.path.join(princ_dir, p)
            if not os.path.exists(fp):
                checks.append((f"knowledge/principles/{p}", "❌ 缺失"))
                break
        else:
            checks.append(("knowledge/principles/ (4原则)", "✅ 完整"))
    else:
        checks.append(("knowledge/principles/", "❌ 目录不存在"))

    # 3) docs/ 完整性
    required_docs = [
        "01-philosophy.md", "02-market.md", "03-discipline.md",
        "04-qualitative.md", "05-quantitative.md", "06-collision.md",
        "07-report.md", "08-exit.md", "09-portfolio.md",
    ]
    if os.path.isdir(DOCS):
        missing = [d for d in required_docs if not os.path.exists(os.path.join(DOCS, d))]
        if missing:
            checks.append((f"docs/ ({len(missing)}缺失)", f"⚠️ 缺 {', '.join(missing)}"))
        else:
            checks.append((f"docs/ ({len(required_docs)}文件)", "✅ 完整"))
    else:
        checks.append(("docs/", "❌ 目录不存在"))

    # 4) yfinance 可用性（fengdata.py 依赖）
    try:
        import yfinance
        checks.append(("yfinance", "✅ 可用"))
    except ImportError:
        checks.append(("yfinance", "❌ 未安装"))

    print("  [预检] 环境检查:")
    for name, status in checks:
        print(f"    {status}  {name}")
    failed = [n for n, s in checks if s.startswith("❌")]
    if failed:
        print(f"  [预检] ⚠️ {len(failed)} 项异常（不阻塞，但建议修复）")
    else:
        print("  [预检] ✅ 全部就绪")
    return 0 if not failed else 1

def cmd_init(ticker):
    """创建状态文件。如果已存在则拒绝覆盖。"""
    path = _sp(ticker)
    if os.path.exists(path):
        print("ERROR: 状态已存在: " + path)
        print("如需重新开始，用 renew 命令（保留历史记录）或先 reset。")
        return 1
    return _create_state(ticker, path)

def cmd_renew(ticker):
    """每日重分析：归档旧状态 + 创建新状态。"""
    os.makedirs(STATE_DIR, exist_ok=True)
    path = _sp(ticker)
    ticker_upper = ticker.upper()
    if os.path.exists(path):
        # 归档旧状态
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        archive_path = os.path.join(STATE_DIR, f"temp_state_{ticker_upper}_{date_str}.json")
        # 如果今天已归档过，加时间后缀
        n = 1
        while os.path.exists(archive_path):
            archive_path = os.path.join(RESEARCH, f"temp_state_{ticker_upper}_{date_str}_{n}.json")
            n += 1
        os.rename(path, archive_path)
        print("[存档] 旧状态 -> " + os.path.basename(archive_path))
    return _create_state(ticker, path, msg="（每日重分析）")

def _create_state(ticker, path, msg=""):
    os.makedirs(STATE_DIR, exist_ok=True)
    # 预检
    _pre_flight()
    state = {
        "ticker": ticker.upper(),
        "status": "active",
        "completed": {},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    print("[OK] 状态初始化: " + ticker.upper() + " " + msg)
    print("  下一层: 01-capability")
    _log_event(ticker, "init", "system", "ok", msg)
    return 0

def cmd_check(ticker, step):
    """检查前置条件是否满足。不满足 → exit(1)。"""
    path = _sp(ticker)
    if not os.path.exists(path):
        print(f"ERROR: 状态文件不存在。请先通过 Skill(\"fenginvest\") 入口启动。")
        return 1

    with open(path) as f:
        state = json.load(f)

    step = step.lower()
    if state.get("status") not in ("active", "completed"):
        print(f"ERROR: 分析已 {state['status']}，无法继续。")
        return 1

    # 如果当前层已被跳过，直接 PASS
    completed = state.get("completed", {})
    if step in completed and completed[step].get("status") == "skipped":
        print(f"[OK] {step.upper()}: 已跳过（L0=不懂），无需执行")
        return 0

    # 检查前置条件（接受 skipped 状态）
    prereqs = PREREQUISITES.get(step, [])
    missing = []
    for p in prereqs:
        if p not in completed:
            missing.append(p)
            continue
        # 如果前置层是 skipped，也算满足
        if completed[p].get("status") == "skipped":
            continue

    if missing:
        done = [p.upper() for p in prereqs if p in completed]
        missing_u = [p.upper() for p in missing]
        _log_event(ticker, "check_fail", step, "blocked",
                   f"missing: {', '.join(missing_u)}; done: {', '.join(done) if done else 'none'}")
        print("+-- 状态机拦截 ---------------------------")
        print("|  当前: " + ticker.upper() + " -> 层 " + step.upper())
        if done:
            print("|  已完成: " + ", ".join(done))
        print("|  缺前置: " + ", ".join(missing_u))
        print("|  错误: 层 " + step.upper() + " 的前置层未完成")
        print("|  解决: 先执行 Skill(\"fenginvest-" + missing_u[0].lower() + "\")")
        print("+------------------------------------------")
        return 1

    print("[OK] " + step.upper() + ": 前置条件满足")
    _log_event(ticker, "check_pass", step, "ok")
    return 0

# 每层输出文件的验证规则 — 支持 key_fields + min_items + min_sources + content_check
VERIFY_RULES = {
    # L0 (capability): json, 必须有三问回答+坐标原则+判定
    "01-capability": {
        "key_fields": ["three_questions", "dk_coordinate", "judgement"],
        "desc": "three_questions[] + dk_coordinate + judgement",
        "min_questions": 3,
    },
    # M层: json, 必须有 price_data, financials, m_layer
    "m": {
        "key_fields": ["price_data", "financials", "m_layer"],
        "desc": "price_data + financials + m_layer(4灯)",
        "m_layer_fields": ["macro", "valuation", "trend", "sentiment"],
    },
    # L1: json, 必须有 rules 数组 + overall_light
    "l1": {
        "key_fields": ["rules", "overall_light"],
        "desc": "rules[] + overall_light",
        "min_rules": 8,
    },
    # L2b: json, 必须有 factors 数组 + lights
    "l2b": {
        "key_fields": ["factors", "lights"],
        "desc": "factors[] + lights",
        "min_factors": 4,
    },
    # L3 (collision): json, 必须有决策+冲突数组
    "06-collision": {
        "key_fields": ["decision", "confidence", "position_pct", "conflicts"],
        "desc": "decision + confidence + position_pct + conflicts[]",
    },
    # P (portfolio): json, 必须有整体灯号+仪表盘
    "08-portfolio": {
        "key_fields": ["overall_light", "dashboard"],
        "desc": "overall_light + dashboard",
    },
}


def _check_acceptance(step: str, data: dict, rule: dict) -> list:
    """Validate acceptance criteria beyond key_field presence. Returns list of errors (empty = pass)."""
    errors = []

    # Check m_layer fields present
    fields = rule.get("m_layer_fields")
    if fields and "m_layer" in data:
        ml = data["m_layer"]
        missing = [f for f in fields if f not in ml]
        if missing:
            errors.append(f"m_layer 缺少: {missing}")

    # Check minimum array sizes
    min_rules = rule.get("min_rules")
    if min_rules and "rules" in data and len(data["rules"]) < min_rules:
        errors.append(f"rules[] 数量 {len(data['rules'])} < 最小 {min_rules}")

    min_factors = rule.get("min_factors")
    if min_factors and "factors" in data and len(data["factors"]) < min_factors:
        errors.append(f"factors[] 数量 {len(data['factors'])} < 最小 {min_factors}")

    min_questions = rule.get("min_questions")
    if min_questions and "three_questions" in data and len(data["three_questions"]) < min_questions:
        errors.append(f"three_questions[] 数量 {len(data['three_questions'])} < 最小 {min_questions}")

    # Check min_sources (if sources array exists)
    min_src = rule.get("min_sources")
    if min_src and "sources" in data and len(data["sources"]) < min_src:
        errors.append(f"sources[] 数量 {len(data['sources'])} < 最小 {min_src}")

    return errors


def verify_output(step: str, output_file: str) -> bool:
    """验证输出文件的结构是否符合该层要求。失败 → 打印错误，返回 False。"""
    if not output_file:
        print(f"  [VERIFY] ERROR: 层 {step.upper()} 未提供输出文件路径")
        return False

    if not os.path.exists(output_file):
        print(f"  [VERIFY] ERROR: 文件不存在: {output_file}")
        return False

    if os.path.getsize(output_file) == 0:
        print(f"  [VERIFY] ERROR: 文件为空: {output_file}")
        return False

    # JSON 层 — 解析并检查关键字段
    json_step_map = {
        "m": "m", "l1": "l1", "l2b": "l2b",
        "02-market": "m", "03-discipline": "l1", "04-quantitative": "l2b",
        "01-capability": "01-capability",
        "06-collision": "06-collision", "collision": "06-collision", "l3": "06-collision",
        "08-portfolio": "08-portfolio", "portfolio": "08-portfolio", "p": "08-portfolio",
    }

    # 所有 JSON 格式的层（含短名兼容）
    json_steps = {s.lower() for s in [
        "02-market", "03-discipline", "04-quantitative",
        "06-collision", "08-portfolio",
        "m", "l1", "l2b",
    ]}

    if step.lower() in json_steps:
        # JSON 层：解析并检查关键字段
        try:
            with open(output_file, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"  [VERIFY] ERROR: JSON 解析失败: {e}")
            return False

        # 查找对应的验证规则
        mapped_step = json_step_map.get(step.lower(), step.lower())
        rule = VERIFY_RULES.get(mapped_step)
        if rule:
            missing = [k for k in rule["key_fields"] if k not in data]
            if missing:
                print(f"  [VERIFY] ERROR: 缺少关键字段 {missing}")
                print(f"  [VERIFY] 层 {step.upper()} 需要包含: {rule['desc']}")
                return False
            # Acceptance criteria check
            accept_errors = _check_acceptance(step, data, rule)
            if accept_errors:
                for e in accept_errors:
                    print(f"  [VERIFY] ACCEPT FAIL: {e}")
                print(f"  [VERIFY] 层 {step.upper()} 未通过验收标准")
                return False
        print(f"  [VERIFY] OK: JSON 结构验证通过 + 验收标准满足")
        return True
    else:
        # Markdown 层：检查非空 + 有内容
        with open(output_file, encoding="utf-8") as f:
            content = f.read()
        if len(content.strip()) < 50:
            print(f"  [VERIFY] WARN: 内容过短 ({len(content.strip())} chars), 可能不完整")
        print(f"  [VERIFY] OK: 文件存在 ({len(content.strip())} chars)")
        return True


# 双格式闸门：JSON 层必须同目录有同名可读 .md（SKILL「产出文档规范」2026-08-15 定稿）
# 机制层强制——complete/accept 在 JSON 合规之外，再校验可读 MD 是否存在，缺则拒绝。
_JSON_LAYERS_NEED_MD = {
    "02-market", "03-discipline", "04-quantitative",
    "06-collision", "08-portfolio",
}


def _check_dual_format(step, output_file):
    """双格式闸门：JSON 层（02/03/04/06/08）必须同目录存在同名可读 .md。

    返回 True=合规或不适用（非 JSON 层 / 非 JSON 后缀）；False=缺可读 MD。
    """
    if not output_file or step.lower() not in _JSON_LAYERS_NEED_MD:
        return True
    if not output_file.lower().endswith(".json"):
        return True
    sibling = output_file[:-5] + ".md"
    if os.path.exists(sibling):
        return True
    print(f"  [DUAL-FORMAT] 缺可读 MD（双格式规范）: 期望 {sibling}")
    return False


def cmd_complete(ticker, step, output_file=None, verify=True, force=False):
    """标记某层完成，更新状态，显示下一步。

    verify=True（默认）: 对输出文件做结构化验证，失败 → return 1。
    force=True: 该层已标记完成时仍重新验证 + 覆盖记录（产物修正后重跑入口，
                2026-08-16 新增——配合 SKILL「产物修正纪律」）。
    """
    path = _sp(ticker)
    if not os.path.exists(path):
        print("ERROR: 状态文件不存在。")
        _log_event(ticker, "complete_fail", step or "?", "error", "state file not found")
        return 1

    with open(path) as f:
        state = json.load(f)

    step = step.lower()
    if step in state.get("completed", {}):
        if not force:
            print("[WARN] " + step.upper() + " 已标记完成，跳过。")
            print("      产物被修正过？用 --force 重新验证并覆盖记录。")
            return 0
        print("[FORCE] " + step.upper() + " 已标记完成，重新验证并覆盖记录。")

    if state.get("status") != "active" and not force:
        print(f"ERROR: 分析已 {state['status']}。")
        _log_event(ticker, "complete_fail", step, "error", f"status={state['status']}")
        return 1

    # 出站验证：在标记完成前校验输出文件
    # 内容与已验证版本逐字节一致（决策缓存命中）→ 跳过重复验证（ai-hedge-fund 移植）
    cache_hit = None
    if verify and output_file:
        try:
            import fengcache
            cache_hit = fengcache.get(ticker, step, output_file)
        except Exception:
            cache_hit = None
        if cache_hit and cache_hit.get("verify_ok"):
            print(f"  [CACHE] 内容与已验证版本一致（{cache_hit.get('cached_at')}），跳过重复验证")
        elif not verify_output(step, output_file):
            print(f"  [BLOCKED] 层 {step.upper()} 的输出验证未通过，拒绝标记完成")
            _log_event(ticker, "complete_fail", step, "verify_fail", output_file)
            return 1
        else:
            try:
                fengcache.put(ticker, step, output_file, verify_ok=True)
            except Exception:
                pass  # 缓存写入失败不影响主流程

            # 双格式闸门：JSON 层缺同名可读 .md 直接拒绝标记完成
            if not _check_dual_format(step, output_file):
                print(f"  [BLOCKED] 层 {step.upper()} 缺可读 MD（双格式规范），拒绝标记完成")
                _log_event(ticker, "complete_fail", step, "doc_format_fail", output_file)
                return 1

    state.setdefault("completed", {})[step] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "output": output_file,
    }
    state["updated_at"] = datetime.now(timezone.utc).isoformat()

    # 判断是否全部完成
    all_steps = set(SEQUENCE)
    done = set(state["completed"])
    if all_steps.issubset(done):
        state["status"] = "completed"
        print("\n[DONE] " + ticker.upper() + " 八层框架全部完成！")
        print("  查看: research/<TICKER>-<中文名>/<日期>/07-report.md")

    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

    # 自动备份（仅 intermediate 保存，final 不需要额外备份）
    if state.get("status") == "active":
        shutil.copy(path, path + ".bak")
        print("  [BACKUP] " + os.path.basename(path) + ".bak")

    # 执行日志
    _log_event(ticker, "complete", step, "ok", output_file or "")

    # 跨层一致性检查（C2：warning 不阻断；--no-verify 逃生门一并跳过）
    if verify:
        cw = _cross_layer_consistency(state, ticker)
        if cw:
            print(f"--- {len(cw)} 个一致性警告（不阻断，见上方 ⚠️，建议核对来源文件）---")
        else:
            print("--- 无一致性警告 ---")

    # 显示下一步
    print("[OK] " + step.upper() + " 完成 " + ("(" + output_file + ")" if output_file else ""))
    next_step = _next_step(done | {step})
    if next_step:
        print("  下一层: " + next_step + " -> Skill(\"fenginvest-" + next_step + "\")")
    return 0

def cmd_status(ticker):
    """查看当前分析进度。"""
    path = _sp(ticker)
    if not os.path.exists(path):
        print(f"无进行中的分析: {ticker.upper()}")
        return 1
    with open(path) as f:
        state = json.load(f)
    done = set(state.get("completed", {}))
    print("=== " + ticker.upper() + " 分析状态 ===")
    print("状态: " + state['status'])
    print()
    for s in SEQUENCE:
        mark = "[x]" if s in done else "[ ]"
        prereq_names = [p.upper() for p in PREREQUISITES.get(s, [])]
        prereq_str = " (需: " + ", ".join(prereq_names) + ")" if prereq_names else ""
        print("  " + mark + "  " + s.upper() + prereq_str)
    print()
    print("创建: " + (state.get('created_at', '?')[:19]))
    print("更新: " + (state.get('updated_at', '?')[:19]))
    return 0

def cmd_accept(ticker, step):
    """独立验收检查：读取状态文件，对该层的输出文件做验收标准检查。"""
    path = _sp(ticker)
    if not os.path.exists(path):
        print(f"ERROR: 状态文件不存在: {ticker.upper()}")
        return 1
    with open(path) as f:
        state = json.load(f)
    done = state.get("completed", {})
    if step not in done:
        print(f"ERROR: 层 {step.upper()} 尚未完成")
        return 1
    output = done[step].get("output", "")
    if not output or not os.path.exists(output):
        print(f"ERROR: 输出文件不存在: {output}")
        return 1
    ok = verify_output(step, output)
    if ok and not _check_dual_format(step, output):
        print(f"[REJECT] {step.upper()} 验收未通过：缺可读 MD（双格式规范）")
        return 1
    if ok:
        print(f"[ACCEPT] {step.upper()} 验收通过")
    else:
        print(f"[REJECT] {step.upper()} 验收未通过")
    return 0 if ok else 1


def _cross_layer_consistency(state, ticker):
    """跨层一致性检查：读取各层输出文件，对比关联数据。返回警告列表。"""
    warnings = []
    done = state.get("completed", {})

    def _load(path_key):
        info = done.get(path_key, {})
        out = info.get("output", "")
        if not out or not os.path.exists(out):
            return None
        try:
            with open(out, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    m_data = _load("02-market")
    l1_data = _load("03-discipline")
    l2b_data = _load("04-quantitative")

    # 1) L1 overall_light vs L2b 因子信号一致度
    if l1_data and l2b_data:
        l1_light = l1_data.get("overall_light", "")
        factors = l2b_data.get("factors", [])
        bull_count = sum(1 for f in factors if f.get("signal") == "BULL")
        bear_count = sum(1 for f in factors if f.get("signal") == "BEAR")
        bear_heavy = bear_count > 0 and (bear_count >= len(factors) * 0.7)
        if l1_light in ("🟢", "green") and bear_heavy:
            warnings.append(
                f"L1 overall_light={l1_light} 但 L2b {bear_count}/{len(factors)} 因子为 BEAR，"
                "信号不一致（来源：03-discipline.json vs 04-quantitative.json）"
            )

    # 2) M layer 趋势 vs L1 MA50/MA120 规则
    if m_data and l1_data:
        m_ml = m_data.get("m_layer", {})
        trend_light = m_ml.get("trend", "")
        if trend_light in ("🔴", "red"):
            l1_rules = l1_data.get("rules", [])
            ma_rules = [r for r in l1_rules if "均线" in str(r) or "MA" in str(r) or "年线" in str(r)]
            ma_passing = any(
                r.get("light") in ("🟢", "green") for r in ma_rules
            )
            if ma_passing:
                warnings.append(
                    f"M层趋势灯=🔴 但 L1 均线规则通过（来源：02-market.json m_layer.trend vs 03-discipline.json）"
                )

    # 3) M层 valuation vs L1 极端估值
    if m_data and l1_data:
        val_light = m_data.get("m_layer", {}).get("valuation", "")
        l1_rules = l1_data.get("rules", [])
        true_value_rule = next((r for r in l1_rules if "真价值" in str(r) or "极端估值" in str(r)), None)
        if val_light in ("🟢", "green") and true_value_rule:
            tv_light = true_value_rule.get("light", "")
            if tv_light in ("🔴", "red"):
                warnings.append(
                    f"M层估值灯=🟢 但 L1 真价值规则={tv_light}（来源：02-market.json m_layer.valuation vs 03-discipline.json）"
                )

    # 4) M层 PE vs L2b 价值因子 PE 一致性（差异>5%报警）
    if m_data and l2b_data:
        m_pe = None
        financials = m_data.get("financials", {})
        if financials.get("pe_ttm"):
            m_pe = financials["pe_ttm"]
        elif financials.get("pe"):
            m_pe = financials["pe"]
        if m_pe:
            factors = l2b_data.get("factors", [])
            pe_factor = next((f for f in factors if "PE" in f.get("factor", "").upper()), None)
            if pe_factor:
                interp = pe_factor.get("interpretation", "")
                pe_matches = re.findall(r'PE[~\s]*(\d+\.?\d*)', interp)
                if pe_matches:
                    l2b_pe = float(pe_matches[0])
                    diff_pct = abs(m_pe - l2b_pe) / max(m_pe, l2b_pe) * 100
                    if diff_pct > 5:
                        warnings.append(
                            f"M层 PE={m_pe} vs L2b 价值因子 PE≈{l2b_pe}，差异 {diff_pct:.1f}% > 5%"
                            "（来源：02-market.json financials.pe_ttm vs 04-quantitative.json PE因子interpretation）"
                        )

    for w in warnings:
        print(f"  [CONSISTENCY] ⚠️  {w}")
    return warnings


def cmd_verify(ticker):
    """验证所有已完成层的输出。返回 (通过数, 总数) / exit(1) if any fail。"""
    path = _sp(ticker)
    if not os.path.exists(path):
        print(f"ERROR: 状态文件不存在: {ticker.upper()}")
        return 1
    with open(path) as f:
        state = json.load(f)
    done = state.get("completed", {})
    if not done:
        print("无已完成层")
        return 0
    passed, failed = 0, 0
    print(f"=== 全量验证: {ticker.upper()} ({len(done)}层) ===")
    for step in SEQUENCE:
        if step not in done:
            continue
        output = done[step].get("output", "")
        if verify_output(step, output):
            passed += 1
        else:
            failed += 1
    print(f"--- {passed} 通过, {failed} 失败 ---")

    # 跨层一致性检查
    print(f"\n=== 跨层一致性检查 ===")
    cw = _cross_layer_consistency(state, ticker)
    if cw:
        print(f"--- {len(cw)} 个一致性警告 ---")
    else:
        print("--- 无一致性警告 ---")

    return 1 if failed else 0


def _get_capability_judgement(state):
    """读取 L0 输出，返回 judgement 值（'懂'/'不充分懂'/'不懂'）或 None。"""
    info = state.get("completed", {}).get("01-capability", {})
    out = info.get("output", "")
    if not out or not os.path.exists(out):
        return None
    try:
        with open(out, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("judgement")
    except (json.JSONDecodeError, UnicodeDecodeError):
        # .md 格式：尝试从中提取判定
        try:
            with open(out, encoding="utf-8") as f:
                content = f.read()
            for keyword in ["**不懂**", "**不充分懂**", "**懂**"]:
                if keyword in content:
                    return keyword.replace("**", "")
        except Exception:
            pass
    return None


def cmd_skip(ticker):
    """当 L0 判定为'不懂'时，自动将后续所有层标记为 skipped。"""
    path = _sp(ticker)
    if not os.path.exists(path):
        print(f"ERROR: 状态文件不存在: {ticker.upper()}")
        return 1

    with open(path) as f:
        state = json.load(f)

    if state.get("status") != "active":
        print(f"ERROR: 分析已 {state['status']}，无法跳过。")
        return 1

    judgement = _get_capability_judgement(state)
    if judgement is None:
        print("ERROR: 无法读取 L0 判定。请先完成 01-capability。")
        return 1

    if judgement != "不懂":
        print(f"L0 判定 = {judgement}，无需跳过。")
        return 1

    # 标记所有未完成的 skipable 层为 skipped
    now = datetime.now(timezone.utc).isoformat()
    for s in SEQUENCE_SKIPPABLE:
        if s not in state.get("completed", {}):
            state.setdefault("completed", {})[s] = {
                "timestamp": now,
                "output": None,
                "status": "skipped",
            }
            print(f"  [SKIP] {s.upper()} → skipped（L0 判定=不懂）")

    # 标记全部完成
    state["status"] = "completed"
    state["updated_at"] = now

    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

    print("\n[PASS] " + ticker.upper() + " — 不懂不碰")
    print("  后续层已全部标记为 skipped。")
    _log_event(ticker, "skip_all", "system", "ok", "L0=不懂 → all layers skipped")
    return 0


def _next_step(done):
    """找到第一个未完成的步骤（按 SEQUENCE 顺序）。"""
    for s in SEQUENCE:
        if s not in done:
            prereqs = PREREQUISITES.get(s, [])
            # 对 L2a/L2b：只要 L1 完成就允许
            if all(p in done for p in prereqs):
                return s
    return None

def cmd_reset(ticker):
    """删除状态文件，强制重来。"""
    path = _sp(ticker)
    if not os.path.exists(path):
        print(f"无状态文件: {ticker.upper()}")
        return 0
    os.remove(path)
    print("[X] " + ticker.upper() + " 状态已清除。")
    return 0

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("FengInvest State Machine - 8 stages: 01-capability 02-market 03-discipline 04-quantitative 05-qualitative 06-collision 07-report 08-portfolio")
        print()
        print("Usage:")
        print("  fengstate.py init <TICKER>          - Create new state file (reject if exists)")
        print("  fengstate.py renew <TICKER>          - Archive old state + create new")
        print("  fengstate.py check <TICKER> <layer>  - Check prerequisites (exit 1 = fail)")
        print("  fengstate.py complete <TICKER> <layer> <output> [--no-verify] [--force] - Mark layer done")
        print("    --no-verify: 跳过输出结构验证（仅用于调试/手动修复）")
        print("    --force:     已标记完成时重新验证并覆盖记录（产物修正后重跑入口）")
        print("  fengstate.py status <TICKER>         - Show progress")
        print("  fengstate.py accept <TICKER> <layer>  - 独立验收检查（仅验证输出，不修改状态）")
        print("  fengstate.py verify <TICKER>          - 全量验证所有已完成层的输出")
        print("  fengstate.py skip <TICKER>             - 当 L0=不懂，自动跳过后续所有层")
        print("  fengstate.py reset <TICKER>          - Clear state file")
        print("  fengstate.py renew <TICKER>          - Archive old state + create new")
        sys.exit(1)

    cmd = sys.argv[1]
    ticker = sys.argv[2]

    commands = {"init": cmd_init, "check": cmd_check, "complete": cmd_complete,
                "status": cmd_status, "reset": cmd_reset, "renew": cmd_renew,
                "accept": cmd_accept, "verify": cmd_verify, "skip": cmd_skip}

    if cmd not in commands:
        print(f"未知命令: {cmd}")
        sys.exit(1)

    if cmd in ("check", "complete", "accept") and len(sys.argv) < 4:
        print(f"用法: fengstate.py {cmd} <TICKER> <层> [输出文件]")
        sys.exit(1)

    step = sys.argv[3] if len(sys.argv) > 3 else None
    output = sys.argv[4] if len(sys.argv) > 4 else None
    # 解析 optional --no-verify / --force 标志
    no_verify = "--no-verify" in sys.argv
    force = "--force" in sys.argv

    fn = commands[cmd]
    if cmd in ("init", "reset", "status", "renew", "verify", "skip"):
        sys.exit(fn(ticker))
    elif cmd in ("check", "accept"):
        sys.exit(fn(ticker, step))
    elif cmd == "complete":
        sys.exit(fn(ticker, step, output, verify=not no_verify, force=force))
