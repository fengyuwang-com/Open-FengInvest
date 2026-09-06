#!/usr/bin/env python3
"""fengfuyao.py — 同花顺 fuyao 官方接口 A 股财报回填（写库走 fengdb.safe_batch，可回滚）

数据源：https://fuyao.aicubes.cn 三张报表端点（利润表/资产负债表/现金流量表），
period=quarterly&limit=20，认证头 X-api-key。只把 MAP 里 24 个 fuyao 科目映射到
cn_financials 对应列，UPSERT 仅更新映射列，其余 170+ 列绝不触碰。

安全原则（承自临时脚本 fuyao_backfill.py，已转正）：
  1) 只写映射列：INSERT ... ON CONFLICT(stkcd,accper,typrep) DO UPDATE 仅更新 MAP 目标列；
  2) 写库一律经 fengdb.safe_batch(["cn_financials"], "fuyao_...")：每批一个事务 +
     自动落 data/changesets/cs_*.bin 变更集（可 fengdb undo 精确回滚），块内不自行 BEGIN/COMMIT；
  3) 断点续跑：完成股票写入 data/cache/fuyao_progress.json，重跑自动跳过已完成
     （旧 ~/fuyao_backfill_progress.json 首次运行自动迁移）；--force 可强制重拉；
  4) 密钥读取顺序：环境变量 HITHINK_FINANCE_API_KEY → %APPDATA%/hithink-finance/credentials.env，
     任何输出不含密钥值。

用法：
    python tools/fengfuyao.py test-conn
    python tools/fengfuyao.py backfill --tickers 600036,000001 [--force] [--batch-size 50] [--interval 1.0]
    python tools/fengfuyao.py backfill --universe [--offset M] [--limit N] [--batch-size 50]
    python tools/fengfuyao.py status

--universe：从库只读读 cn_financials 全集 DISTINCT stkcd，减进度文件已 done 得回填队列
（升序稳定排序）；--offset/--limit 在该「剩余队列」上开窗口做分块接力——每跑完一块
done 增长、剩余队列自动收缩，下一班接力直接重复 `--universe --limit N` 即可滑窗推进。

写库遇 database locked（同库另有后台单写者排队时）：等 30 秒重试，最多 3 次。

backfill 正常结束向 stdout 输出汇总 JSON：{"done": [...], "failed": [...], ...}，
单只失败记入 failed 继续下一只；过程日志走 stderr。
"""
import argparse
import json
import os
import sys
import time
import datetime
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fengdb  # noqa: E402  同目录安全写库入口（apsw + changeset）

BASE = "https://fuyao.aicubes.cn"
ENV_FILE = os.path.join(os.environ.get("APPDATA", ""), "hithink-finance", "credentials.env")
PROGRESS_FILE = os.path.join(fengdb.BASE, "data", "cache", "fuyao_progress.json")
LEGACY_PROGRESS_FILE = os.path.expanduser("~/fuyao_backfill_progress.json")

TABLE = "cn_financials"
TYPREP = "A"

# fuyao 字段 -> cn_financials 列（仅此映射表内的列会被写入，其余列绝对不动）
MAP = {
    'operating_income': 'operating_revenue_s',
    'operating_costs': 'operating_cost_s',
    'sales_fee': 'selling_expenses',
    'manage_fee': 'admin_expenses',
    'research_and_development_expenses': 'rnd_expenses',
    'interest_expenses': 'finance_expenses',
    'operating_profit': 'operating_profit',
    'profit_total': 'total_profit',
    'income_tax_expense': 'income_tax_expense',
    'net_profit': 'net_profit',
    'parent_holder_net_profit': 'parent_net_profit',
    'basic_eps': 'basic_eps_report',
    'assets_total': 'total_assets',
    'total_current_assets': 'current_assets',
    'non_current_nets_total': 'noncurrent_assets',
    'cash': 'cash',
    'accounts_receivable': 'accounts_receivable',
    'holder_equity_total': 'total_equity',
    'total_debt': 'total_liabilities',
    'act_cash_flow_net': 'operating_cf_net',      # cash 端点实际字段名（2026-08-24 三公司实测；旧脚本误写 operating_cash_flow_net 致漏采）
    'invest_cash_flow_net': 'investing_cf_net',   # 同上（旧脚本误写 investing_cash_flow_net）
    'financing_cash_flow_net': 'financing_cf_net',
    'cash_equivalents_net_addition': 'cash_net_change',
    'pay_fixed_assets_etc_cash': 'capital_expenditure',
}
REPORT_ENDPOINTS = {
    'income': '/api/a-share/financials/income-statements',
    'balance': '/api/a-share/financials/balance-sheets',
    'cash': '/api/a-share/financials/cash-flow-statements',
}

RETRY_ATTEMPTS = 3          # 单请求最多尝试次数
RETRY_BACKOFF_BASE = 1.0    # 指数退避基数秒：1s → 2s
HTTP_TIMEOUT = 40
MIN_INTERVAL = 1.0          # 限速下限：任意两次请求间隔至少 1 秒（免费额度保护）
LOCKED_RETRY_WAIT = 30      # safe_batch 遇 database locked 的等待秒数
LOCKED_RETRY_MAX = 3        # locked 最多重试次数（含首次共尝试 3 次）

_last_request_ts = 0.0


def log(msg: str):
    """过程日志走 stderr，保持 stdout 纯 JSON。"""
    print(msg, file=sys.stderr, flush=True)


# ── 密钥与进度 ────────────────────────────────────────────────────────────────

def load_key() -> str:
    """密钥读取顺序：环境变量 HITHINK_FINANCE_API_KEY → credentials.env。"""
    key = os.environ.get("HITHINK_FINANCE_API_KEY", "").strip()
    if key:
        return key
    if not os.path.exists(ENV_FILE):
        raise RuntimeError(f"未找到密钥：环境变量为空且凭据文件不存在 {ENV_FILE}")
    with open(ENV_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("HITHINK_FINANCE_API_KEY="):
                v = line.split("=", 1)[1].strip().strip('"').strip("'")
                if v:
                    return v
    raise RuntimeError(f"凭据文件中无 HITHINK_FINANCE_API_KEY：{ENV_FILE}")


def load_progress() -> dict:
    """读进度文件；发现旧版 ~/fuyao_backfill_progress.json 且新版不存在则先迁移 done 清单。"""
    migrated = False
    done = []
    if not os.path.exists(PROGRESS_FILE) and os.path.exists(LEGACY_PROGRESS_FILE):
        try:
            with open(LEGACY_PROGRESS_FILE, encoding="utf-8") as f:
                legacy = json.load(f)
            done = sorted({str(x).split(".")[0].strip() for x in legacy.get("done", []) if str(x).strip()})
            os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
            _save_progress(done, migrated_from=LEGACY_PROGRESS_FILE)
            migrated = True
            log(f"[progress] 已迁移旧进度 {len(done)} 只 ← {LEGACY_PROGRESS_FILE}")
        except Exception as e:  # 迁移失败不阻塞，继续用现有进度
            log(f"[progress] 旧进度迁移失败（忽略）：{e}")
    data = {"done": [], "failed": {}}
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            log(f"[progress] 进度文件损坏，按空进度处理：{e}")
    data["done"] = sorted({str(x).split(".")[0].strip() for x in data.get("done", []) if str(x).strip()})
    # failed 归一化为 {ticker: reason}；旧版文件没有该字段则为空
    raw_failed = data.get("failed") or {}
    data["failed"] = {
        str(k).split(".")[0].strip(): str(v)[:200]
        for k, v in (raw_failed.items() if isinstance(raw_failed, dict) else
                     ((str(x).split(".")[0].strip(), "legacy_unknown") for x in raw_failed))
        if str(k).strip()
    }
    data["_migrated"] = migrated
    return data


def _save_progress(done, migrated_from=None, failed=None):
    tmp = PROGRESS_FILE + ".tmp"
    payload = {
        "done": sorted(set(done)),
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }
    if failed is not None:
        # 兼容两种入参：{ticker: reason} 或 [{"ticker":..,"reason":..}, ...]，统一存 dict
        if isinstance(failed, dict):
            payload["failed"] = dict(failed)
        else:
            payload["failed"] = {
                str(x.get("ticker", "")).split(".")[0].strip(): str(x.get("reason", ""))[:200]
                for x in failed
                if isinstance(x, dict) and str(x.get("ticker", "")).strip()
            }
    if migrated_from:
        payload["migrated_from"] = migrated_from
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PROGRESS_FILE)


def build_universe_queue(retry_failed: bool = False) -> list:
    """--universe 队列：只读连库取 cn_financials 全集 DISTINCT stkcd，减进度文件已 done。

    默认再减历史失败清单（多为退市票 code=1002 无数据，重拉只会白烧配额）；
    retry_failed=True 把失败票重新纳入（用于换参数/换时段复测）。
    升序稳定排序，六位零填充（stkcd 存 TEXT 带前导零，zfill 兜底）；裸代码直接可用，
    fuyao 端会经 to_thscode 自动推断交易所后缀。
    """
    con = fengdb._connect(readonly=True)
    try:
        all_ids = sorted({
            str(r[0]).split(".")[0].strip().zfill(6)
            for r in con.execute(f"SELECT DISTINCT stkcd FROM {TABLE}")
        })
    finally:
        con.close()
    prog = load_progress()
    excl = set(prog["done"])
    if not retry_failed:
        excl |= set(prog["failed"].keys())
    return [t for t in all_ids if t not in excl]


# ── HTTP（重试指数退避 + 限速） ────────────────────────────────────────────────

class FuyaoError(Exception):
    pass


def _throttle(interval: float):
    """任意两次请求间隔 >= max(MIN_INTERVAL, interval)。"""
    global _last_request_ts
    gap = max(MIN_INTERVAL, interval)
    wait = _last_request_ts + gap - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    _last_request_ts = time.monotonic()


def api_get(path: str, key: str, interval: float = MIN_INTERVAL) -> dict:
    """GET 一个 fuyao 端点并解析 JSON；重试指数退避最多 RETRY_ATTEMPTS 次。

    可重试：网络异常 / 5xx / 429。其余 4xx 不重试（密钥或参数问题重试无意义）。
    失败抛 FuyaoError（消息不含密钥）。
    """
    last_err = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        _throttle(interval)
        req = urllib.request.Request(BASE + path, headers={"X-api-key": key})
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:200]
            last_err = f"HTTP {e.code}: {body}"
            if e.code == 429 or 500 <= e.code < 600:
                if attempt < RETRY_ATTEMPTS:
                    backoff = RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                    log(f"[http] {path.split('?')[0]} 第{attempt}次失败({e.code})，{backoff:.0f}s 后重试")
                    time.sleep(backoff)
                    continue
            raise FuyaoError(last_err)
        except Exception as e:
            last_err = str(e)[:200]
            if attempt < RETRY_ATTEMPTS:
                backoff = RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
                log(f"[http] {path.split('?')[0]} 第{attempt}次失败({last_err})，{backoff:.0f}s 后重试")
                time.sleep(backoff)
                continue
    raise FuyaoError(last_err or "unknown")


# ── 取数与落库 ────────────────────────────────────────────────────────────────

def ms_to_date(ms):
    """fuyao 时间戳是北京时间(UTC+8)的报告期/披露日，必须用东八区转换，否则早一天造成重复期。"""
    if not ms:
        return None
    tz = datetime.timezone(datetime.timedelta(hours=8))
    return datetime.datetime.fromtimestamp(ms / 1000, tz).strftime("%Y-%m-%d")


def norm_ticker(t: str) -> str:
    """'600036.SH' / '000001.SZ' / '600036' → 六位代码。"""
    return str(t).split(".")[0].strip()


def to_thscode(t: str) -> str:
    """补全同花顺 thscode 后缀：API 只认带交易所后缀的代码（实测裸代码报 code=1002）。

    规则：6 开头 → .SH（含 688 科创板）；0/3 开头 → .SZ；4/8/92 → .BJ（北交所）；
    2/9 开头 → B 股（.SZ / .SH）；已带后缀原样返回；无法识别抛 ValueError。
    """
    raw = str(t).strip().upper()
    c = norm_ticker(raw)
    if "." in raw:
        return raw
    if len(c) == 6 and c.isdigit():
        if c.startswith("6"):
            return c + ".SH"
        if c.startswith(("0", "3")):
            return c + ".SZ"
        if c.startswith(("4", "8", "92")):
            return c + ".BJ"
        if c.startswith("2"):
            return c + ".SZ"
        if c.startswith("9"):
            return c + ".SH"
    raise ValueError(f"无法识别的股票代码: {t}")


def fetch_one(thscode: str, key: str, interval: float) -> dict:
    """返回 {accper: {db_col: val, 'declare_date': ...}}，仅含映射列。

    端点级失败记 warning 继续（部分成功也算数）；三个端点全失败抛 FuyaoError。
    """
    periods, ok_cnt, errs = {}, 0, []
    for name, ep in REPORT_ENDPOINTS.items():
        try:
            d = api_get(f"{ep}?thscode={thscode}&period=quarterly&limit=20", key, interval)
        except FuyaoError as e:
            errs.append(f"{name}:{e}")
            log(f"  ! {name} {thscode} 失败: {e}")
            continue
        if d.get("code") != 0:
            errs.append(f"{name}:code={d.get('code')} {str(d.get('message'))[:120]}")
            log(f"  ! {name} {thscode} code={d.get('code')} {d.get('message')}")
            continue
        ok_cnt += 1
        for it in (d.get("data") or {}).get("item") or []:
            pe = it.get("period_end_ms")
            if not pe:
                continue
            accper = ms_to_date(pe)
            row = periods.setdefault(accper, {})
            for ff, dbcol in MAP.items():
                v = it.get(ff)
                if v is not None:
                    row[dbcol] = v
            rd = it.get("report_date_ms")
            if rd:
                row["declare_date"] = ms_to_date(rd)
    if ok_cnt == 0:
        raise FuyaoError("; ".join(errs) or "三端点均无返回")
    return periods


def upsert(con, stkcd: str, periods: dict) -> int:
    """批量 UPSERT 一只股票的全部期次，只更新映射列。返回写入行数。"""
    n = 0
    for accper, vals in periods.items():
        if not vals:
            continue
        cols = ["stkcd", "accper", "typrep"] + list(vals.keys())
        setc = ", ".join(f"{c}=excluded.{c}" for c in vals.keys())
        sql = (
            f"INSERT INTO {TABLE} ({','.join(cols)}) "
            f"VALUES ({','.join('?' * len(cols))}) "
            f"ON CONFLICT(stkcd,accper,typrep) DO UPDATE SET {setc}"
        )
        # fengdb.safe_batch yield 的是 apsw 连接，序列绑定即可；事务由 safe_batch 管理，块内不得 BEGIN/COMMIT
        con.execute(sql, [stkcd, accper, TYPREP] + list(vals.values()))
        n += 1
    return n


def _is_locked_error(e: Exception) -> bool:
    """识别 SQLite 锁冲突（apsw.BusyError 消息含 database is locked / table is locked）。"""
    s = str(e).lower()
    return "locked" in s


def flush_batch(batch, tag: str, done: set, failed: list) -> int:
    """一批（≤batch_size 只）经 fengdb.safe_batch 写库：成功更新进度，失败整批记 failed。

    同库另有后台单写者（WAL 排队）时遇 database locked：等 LOCKED_RETRY_WAIT 秒重试，
    最多尝试 LOCKED_RETRY_MAX 次；仍失败才整批回滚记 failed。
    """
    if not batch:
        return 0
    label = f"fuyao_{tag}"
    rows = 0
    for attempt in range(1, LOCKED_RETRY_MAX + 1):
        try:
            rows = 0
            with fengdb.safe_batch([TABLE], label) as con:
                for stkcd, periods in batch:
                    rows += upsert(con, stkcd, periods)
            break
        except Exception as e:
            if _is_locked_error(e) and attempt < LOCKED_RETRY_MAX:
                log(f"BATCH LOCKED ({label}) 第{attempt}次，{LOCKED_RETRY_WAIT}s 后重试")
                time.sleep(LOCKED_RETRY_WAIT)
                continue
            log(f"BATCH ROLLBACK ({label}): {e}")
            failed.extend({"ticker": stkcd, "reason": f"batch_rolled_back:{str(e)[:150]}"} for stkcd, _ in batch)
            return 0
    for stkcd, _p in batch:
        done.add(stkcd)
    # failed 一并落盘（修复：此前每批提交只存 done，failed 清单被清空，
    # 下一块会重拉全部永久失败票如退市 code=1002）；已翻身的票从 failed 剔除
    failed[:] = [x for x in failed if x.get("ticker") not in done]
    _save_progress(done, failed=failed)
    log(f"  committed {label}: {len(batch)} 只, {rows} 行 (累计 done={len(done)})")
    return rows


# ── 子命令 ────────────────────────────────────────────────────────────────────

def cmd_test_conn(args) -> int:
    """最小请求验证密钥（不写库）。"""
    try:
        key = load_key()
        t0 = time.monotonic()
        d = api_get(
            f"{REPORT_ENDPOINTS['income']}?thscode={to_thscode('600036')}&period=quarterly&limit=1",
            key, MIN_INTERVAL,
        )
        latency = round((time.monotonic() - t0) * 1000)
        if d.get("code") != 0:
            print(json.dumps({"ok": False, "error": f"code={d.get('code')} {d.get('message')}",
                              "base": BASE}, ensure_ascii=False))
            return 1
        items = (d.get("data") or {}).get("item") or []
        sample = items[0] if items else {}
        print(json.dumps({
            "ok": True,
            "base": BASE,
            "endpoint": REPORT_ENDPOINTS['income'],
            "api_code": d.get("code"),
            "items_returned": len(items),
            "sample_accper": ms_to_date(sample.get("period_end_ms")),
            "latency_ms": latency,
            "note": "密钥有效；本命令不写库",
        }, indent=2, ensure_ascii=False))
        return 0
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)[:300], "base": BASE}, ensure_ascii=False))
        return 1


def cmd_backfill(args) -> int:
    try:
        interval = float(args.interval)
    except ValueError:
        print(json.dumps({"error": f"--interval 非法: {args.interval}"}, ensure_ascii=False))
        return 1
    if interval < MIN_INTERVAL:
        print(json.dumps({"error": f"--interval 必须 >= {MIN_INTERVAL} 秒（免费额度保护）"}, ensure_ascii=False))
        return 1
    if not args.tickers and not args.universe:
        print(json.dumps({"error": "--tickers 与 --universe 至少给一个；--universe 从库全集减进度文件得队列"}, ensure_ascii=False))
        return 1
    tickers = []
    seen = set()
    if args.universe:
        # 库全集（升序）减已 done，即「剩余队列」；--offset/--limit 在其上开窗口分块接力
        tickers = build_universe_queue()
        lo = max(int(args.offset or 0), 0)
        hi = None if args.limit is None else lo + max(int(args.limit), 0)
        window = tickers[lo:hi]
        log(f"[universe] 剩余队列 {len(tickers)} 只 | 本块窗口 offset={lo} limit={args.limit} → {len(window)} 只")
        tickers = window
        skipped = 0
    else:
        for t in args.tickers.split(","):
            nt = norm_ticker(t)
            if nt and nt not in seen:
                seen.add(nt)
                tickers.append(nt)
        if not tickers:
            print(json.dumps({"error": "--tickers 为空，示例：--tickers 600036,000001"}, ensure_ascii=False))
            return 1
    try:
        key = load_key()
    except RuntimeError as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 1

    prog = load_progress()
    done = set(prog["done"])
    # 接住历史 failed（修复：此前每 run 重新置空，进度文件里的失败票永远记不住）
    failed = [{"ticker": t, "reason": r} for t, r in prog["failed"].items()]
    pending = list(tickers) if (args.universe or args.force) else [t for t in tickers if t not in done]
    skipped = len(tickers) - len(pending)
    tag = f"backfill_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    log(f"[backfill] 目标 {len(tickers)} 只 | 已完成跳过 {skipped} | 待拉取 {len(pending)} | 批大小 {args.batch_size}")

    rows_total, batches, batch_buf, interrupted = 0, 0, [], False
    try:
        for i, thscode in enumerate(pending, 1):
            log(f"[{i}/{len(pending)}] fetch {thscode} ...")
            try:
                thscode_api = to_thscode(thscode)  # API 需要带交易所后缀的代码
                periods = fetch_one(thscode_api, key, interval)
            except (FuyaoError, ValueError) as e:
                log(f"  ! FAILED {thscode}: {e}")
                failed.append({"ticker": thscode, "reason": str(e)[:200]})
                continue
            log(f"  -> {len(periods)} 个报告期")
            batch_buf.append((thscode, periods))
            if len(batch_buf) >= args.batch_size:
                batches += 1
                rows_total += flush_batch(batch_buf, f"{tag}_b{batches:02d}", done, failed)
                batch_buf = []
    except KeyboardInterrupt:
        interrupted = True
        log("[backfill] 收到中断，先提交已拉取的半批再退出")
    if batch_buf:
        batches += 1
        rows_total += flush_batch(batch_buf, f"{tag}_b{batches:02d}", done, failed)

    result = {
        "done": sorted(done),
        "failed": failed,
        "requested": tickers,
        "skipped_already_done": skipped,
        "rows_upserted": rows_total,
        "batches_committed": batches,
        "interrupted": interrupted,
        "changesets": f"data/changesets/index.jsonl 中 label 以 fuyao_ 开头的记录（详见 status）",
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_status(args) -> int:
    prog = load_progress()
    records = []
    if os.path.exists(fengdb.INDEX_FILE):
        with open(fengdb.INDEX_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if str(rec.get("label", "")).startswith("fuyao_"):
                    fp = os.path.join(fengdb.CHANGESET_DIR, rec.get("file", ""))
                    rec["exists"] = os.path.exists(fp)
                    records.append(rec)
    out = {
        "progress_file": PROGRESS_FILE,
        "legacy_migrated_this_run": prog.pop("_migrated", False),
        "done_count": len(prog["done"]),
        "done_recent": prog["done"][-10:],
        "progress_updated_at": prog.get("updated_at"),
        "fuyao_changesets": {
            "count": len(records),
            "total_size_bytes": sum(r.get("size_bytes", 0) for r in records),
            "recent": records[-10:],
        },
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="fuyao 官方接口 A 股财报回填到 cn_financials（safe_batch 可回滚）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_t = sub.add_parser("test-conn", help="最小请求验证密钥（不写库）")
    p_t.set_defaults(func=cmd_test_conn)

    p_b = sub.add_parser("backfill", help="回填指定股票财报（断点续跑，单只失败不影响后续）")
    p_b.add_argument("--tickers", default=None,
                     help="逗号分隔股票列表，如 600036,000001 或 600036.SH,000001.SZ；与 --universe 至少给一个")
    p_b.add_argument("--universe", action="store_true",
                     help="从库读 cn_financials 全集 DISTINCT stkcd 减进度文件已 done 得回填队列（升序）")
    p_b.add_argument("--offset", type=int, default=0, help="--universe 剩余队列窗口起点（默认 0）")
    p_b.add_argument("--limit", type=int, default=None, help="--universe 本块最多拉取只数（缺省拉到队尾）")
    p_b.add_argument("--force", action="store_true", help="已完成也重拉（默认跳过 done 清单内的股票；--universe 下无效）")
    p_b.add_argument("--batch-size", type=int, default=50, help="每批事务只数（默认 50）")
    p_b.add_argument("--interval", type=str, default=str(MIN_INTERVAL),
                     help=f"请求间隔秒数，必须 >= {MIN_INTERVAL}（默认 {MIN_INTERVAL}）")
    p_b.set_defaults(func=cmd_backfill)

    p_s = sub.add_parser("status", help="进度文件 + fuyao_ 前缀变更集记录汇总")
    p_s.set_defaults(func=cmd_status)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
