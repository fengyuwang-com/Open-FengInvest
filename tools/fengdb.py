#!/usr/bin/env python3
"""fengdb.py — 统一安全写库工具：可回滚批量写入（changeset）+ 快照 + 撤销

解决两条硬要求：
① 数据库必须支持回滚 —— 任何经 safe_batch 的批量写入都会自动提取一份 SQLite
   Session 变更集（二进制行级 diff，实测约 749 字节/行），写坏后用 undo 一条
   命令精确撤销（INSERT↔DELETE、UPDATE 双向反转），不需要整库备份；
② 增量同步只传小文件 —— 对外同步只传 data/changesets/*.bin（几 MB）+
   index.jsonl 里的一行记录，不再搬运 2.6GB 整库。

机制（apsw Session API，已在 apsw 3.53.4.0 上 POC 验证）：
    sess = apsw.Session(con, "main"); sess.attach("表名")
    cs = bytes(sess.changeset())                          # 提取变更集
    apsw.Changeset.apply(apsw.Changeset.invert(cs), con)  # 反转并应用 = 撤销

已知边界（SQLite Session 固有限制，不是 bug）：
- Session 只捕获「经同一连接」发生的写入；别的连接直接写的管不到；
- 只有带声明主键的表能进变更集（cn_financials / daily_data 均满足），
  无主键表 / 视图 / 虚拟表的行变化不会被捕获；
- DDL（CREATE/ALTER/DROP）不进变更集：回滚只还原行数据。建表请在
  safe_batch 之外做。

用法（库 —— 所有对 market_data.db 的批量写入一律走这里）：
    import sys; sys.path.insert(0, "tools")
    from fengdb import safe_batch
    with safe_batch(["daily_data"], "backfill_us_2024") as con:
        con.execute("INSERT INTO daily_data(index_id, date) VALUES (?, ?)",
                    ("AAPL", "2024-01-02"))
    # 正常退出 → COMMIT + 变更集落盘 data/changesets/cs_<时间戳>_<label>.bin
    #          + 向 index.jsonl 追加一行 {file, tables, label, timestamp, size_bytes}
    # 块内抛异常 → 自动 ROLLBACK，不落任何文件，异常原样上抛。
    # 注意：块内不要再自行 BEGIN/COMMIT，事务由本函数管理。

用法（CLI）：
    python tools/fengdb.py undo data/changesets/cs_20260824_121500_demo.bin [--db PATH]
    python tools/fengdb.py snapshot pre_backfill [--db PATH] [--out DIR]
    python tools/fengdb.py status

快照说明：snapshot 用 `VACUUM INTO` 导出自包含副本（源库只读访问），输出
*.db 后缀已被 .gitignore 的 `data/*.db` / `*.db` 规则覆盖，不会漏进 git；
变更集目录 data/changesets/ 与旧式快照 data/*.snap_* 由本工具配套追加的
gitignore 规则覆盖。
"""
import argparse
import contextlib
import json
import os
import re
import sys
from datetime import datetime

try:
    import apsw
except ImportError:  # pragma: no cover
    raise SystemExit("fengdb 需要 apsw（pip install apsw）")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "data", "market_data.db")  # 与 fengstockdb.py 风格一致
CHANGESET_DIR = os.path.join(BASE, "data", "changesets")
SNAPSHOT_DIR = os.path.join(BASE, "data", "snapshots")
INDEX_FILE = os.path.join(CHANGESET_DIR, "index.jsonl")

BUSY_TIMEOUT_MS = 10000

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ── 连接与命名辅助 ────────────────────────────────────────────────────────────

def _connect(db_path=None, readonly=False):
    """打开 apsw 连接。READWRITE 模式不带 CREATE，绝不误建新库文件。"""
    flags = apsw.SQLITE_OPEN_READONLY if readonly else apsw.SQLITE_OPEN_READWRITE
    con = apsw.Connection(db_path or DB_PATH, flags=flags)
    con.set_busy_timeout(BUSY_TIMEOUT_MS)
    return con


def _safe_label(label):
    """label 只保留文件名安全字符，防路径注入/非法字符。"""
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", str(label)).strip("_")
    return (s or "unlabeled")[:40]


def _unique_path(directory, stem, ext):
    """目录内防重名：<stem><ext> → <stem>_2<ext> → …"""
    p = os.path.join(directory, f"{stem}{ext}")
    n = 2
    while os.path.exists(p):
        p = os.path.join(directory, f"{stem}_{n}{ext}")
        n += 1
    return p


# ── 核心 API ─────────────────────────────────────────────────────────────────

@contextlib.contextmanager
def safe_batch(tables: list[str], label: str, db_path: str = None):
    """安全批量写入上下文：yield 一个已开显式事务的 apsw 连接。

    - tables: 要捕获变更的表名列表（须有声明主键）；只捕获经 yield 出去的
      这个连接发生的行变化。
    - label : 写入目的的人类标签，进入文件名与 index 记录。
    - db_path: 默认真库 market_data.db；测试/演练时可指向临时副本。

    正常退出 → COMMIT；提取 changeset 存 CHANGESET_DIR；index.jsonl 追加一行。
    异常退出 → ROLLBACK，不落任何文件，异常原样上抛。
    """
    os.makedirs(CHANGESET_DIR, exist_ok=True)
    con = _connect(db_path)
    sess = None
    committed = False
    try:
        con.execute("BEGIN IMMEDIATE")
        sess = apsw.Session(con, "main")
        for t in tables:
            sess.attach(str(t))
        yield con
        con.execute("COMMIT")
        committed = True
        # 事务已提交，提取并落盘变更集（失败则数据已入库但无回滚凭证，
        # 故放在 COMMIT 之后立即执行，窗口极小）
        now = datetime.now()
        fpath = _unique_path(
            CHANGESET_DIR,
            f"cs_{now.strftime('%Y%m%d_%H%M%S')}_{_safe_label(label)}",
            ".bin",
        )
        with open(fpath, "wb") as f:
            f.write(bytes(sess.changeset()))
        rec = {
            "file": os.path.basename(fpath),
            "tables": [str(t) for t in tables],
            "label": str(label),
            "timestamp": now.isoformat(timespec="seconds"),
            "size_bytes": os.path.getsize(fpath),
        }
        with open(INDEX_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except BaseException:
        if not committed:
            with contextlib.suppress(Exception):
                con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def undo_changeset(cs_file: str, db_path: str = None) -> dict:
    """把一个变更集反转（invert）后应用到库上，即精确撤销那批写入。

    返回 {"undone": True, "file": ..., "rows_affected": N}；
    rows_affected 为反转应用实际改动的行数（插入+删除+更新各计 1）。
    """
    if not os.path.exists(cs_file):
        raise FileNotFoundError(f"变更集不存在: {cs_file}")
    with open(cs_file, "rb") as f:
        cs = f.read()
    con = _connect(db_path)
    try:
        before = con.total_changes()
        con.execute("BEGIN IMMEDIATE")
        try:
            apsw.Changeset.apply(apsw.Changeset.invert(cs), con)
            con.execute("COMMIT")
        except BaseException:
            with contextlib.suppress(Exception):
                con.execute("ROLLBACK")
            raise
        rows = con.total_changes() - before
    finally:
        con.close()
    return {
        "undone": True,
        "file": os.path.basename(cs_file),
        "rows_affected": rows,
        "db": db_path or DB_PATH,
    }


def make_snapshot(label: str, db_path: str = None, out_dir: str = None) -> dict:
    """VACUUM INTO 导出自包含快照副本。源库以只读方式打开，绝不写真库。"""
    out_dir = out_dir or SNAPSHOT_DIR
    os.makedirs(out_dir, exist_ok=True)
    now = datetime.now()
    out = _unique_path(
        out_dir,
        f"market_data_{now.strftime('%Y%m%d')}_{_safe_label(label)}",
        ".db",
    )
    con = _connect(db_path or DB_PATH, readonly=True)
    try:
        con.execute("VACUUM INTO ?", (out,))
    finally:
        con.close()
    return {
        "snapshot": os.path.basename(out),
        "path": out,
        "size_bytes": os.path.getsize(out),
        "timestamp": now.isoformat(timespec="seconds"),
    }


def get_status() -> dict:
    """列出全部变更集记录 + 快照清单。"""
    changesets = []
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                fp = os.path.join(CHANGESET_DIR, rec.get("file", ""))
                rec["exists"] = os.path.exists(fp)
                changesets.append(rec)
    snapshots = []
    if os.path.isdir(SNAPSHOT_DIR):
        for name in sorted(os.listdir(SNAPSHOT_DIR)):
            if not name.endswith(".db"):
                continue
            st = os.stat(os.path.join(SNAPSHOT_DIR, name))
            snapshots.append({
                "file": name,
                "size_bytes": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            })
    return {
        "db": DB_PATH,
        "changesets_count": len(changesets),
        "changesets": changesets,
        "snapshots_count": len(snapshots),
        "snapshots": snapshots,
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def cmd_undo(args):
    try:
        res = undo_changeset(args.changeset, db_path=args.db)
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 1
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0


def cmd_snapshot(args):
    try:
        res = make_snapshot(args.label, db_path=args.db, out_dir=args.out)
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 1
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0


def cmd_status(args):
    print(json.dumps(get_status(), indent=2, ensure_ascii=False))
    return 0


def main():
    ap = argparse.ArgumentParser(description="FengInvest 统一安全写库：changeset 回滚 + 快照")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_undo = sub.add_parser("undo", help="撤销一批写入：invert+apply 变更集到库")
    p_undo.add_argument("changeset", help="cs_*.bin 变更集文件路径")
    p_undo.add_argument("--db", default=None, help="目标库路径（默认 data/market_data.db）")
    p_undo.set_defaults(func=cmd_undo)

    p_snap = sub.add_parser("snapshot", help="VACUUM INTO 只读导出整库快照")
    p_snap.add_argument("label", help="快照标签（进文件名）")
    p_snap.add_argument("--db", default=None, help="源库路径（默认 data/market_data.db）")
    p_snap.add_argument("--out", default=None, help=f"输出目录（默认 {SNAPSHOT_DIR}）")
    p_snap.set_defaults(func=cmd_snapshot)

    p_status = sub.add_parser("status", help="列出变更集索引与快照清单")
    p_status.set_defaults(func=cmd_status)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
