#!/usr/bin/env python3
"""feng_add_capex.py — 从 CSMAR 原始 .dta 增量导入 capital_expenditure

CSMAR 原始 754 列中有资本支出字段 C002006000 / Capexp，但导入 cn_financials 时未选入。
此脚本做增量补填：
  1. ALTER TABLE cn_financials ADD COLUMN capital_expenditure REAL
  2. 从 .dta 读取 C002006000 并 update cn_financials
  3. 回填 fundamentals.capital_expenditure

用法:
    python tools/feng_add_capex.py              # 季度数据补 CAPEX
    python tools/feng_add_capex.py --mode annual # 年度数据
    python tools/feng_add_capex.py --check      # 只检查状态，不改数据
"""
import os, sqlite3, sys, time, json

sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "data", "market_data.db")

Q_DTA = os.path.expanduser(r"~\Downloads\上市公司财务季度数据合并（90-25.3）.dta")
A_DTA = os.path.expanduser(r"~\Downloads\上市公司财务年度数据合并（90-24）.dta")

CSMAR_COL = "C002006000"  # 购建固定资产、无形资产和其他长期资产支付的现金
LEGACY_COL = "Capexp"     # 同一数据的旧版英文命名
MY_COL = "capital_expenditure"


def status(conn):
    """检查当前 capex 状态"""
    cur = conn.execute("PRAGMA table_info(cn_financials)")
    cols = [c[1] for c in cur.fetchall()]

    if MY_COL in cols:
        cur = conn.execute(
            f"SELECT COUNT(*), SUM(CASE WHEN {MY_COL} IS NOT NULL THEN 1 ELSE 0 END) FROM cn_financials"
        )
        total, has = cur.fetchone()
        print(f"  cn_financials.{MY_COL}: {has:,}/{total:,} non-NULL ({100*has/total:.1f}%)")
    else:
        print(f"  cn_financials.{MY_COL}: 列不存在 ❌")

    cur = conn.execute(
        "SELECT COUNT(*), SUM(CASE WHEN capital_expenditure IS NOT NULL THEN 1 ELSE 0 END) FROM fundamentals"
    )
    total, has = cur.fetchone()
    print(f"  fundamentals.capital_expenditure: {has:,}/{total:,} non-NULL ({100*has/total:.1f}%)")

    return MY_COL in cols


def add_column(conn):
    """给 cn_financials 加列"""
    cur = conn.execute("PRAGMA table_info(cn_financials)")
    cols = [c[1] for c in cur.fetchall()]
    if MY_COL in cols:
        print(f"  列 {MY_COL} 已存在")
        return False
    conn.execute(f"ALTER TABLE cn_financials ADD COLUMN {MY_COL} REAL")
    conn.commit()
    print(f"  列 {MY_COL} 已添加 ✅")
    return True


def import_from_dta(conn, dta_path):
    """从 .dta 读取 C002006000 / Capexp 并回填"""
    import pandas as pd

    if not os.path.exists(dta_path):
        print(f"  .dta 不存在: {dta_path}")
        return 0

    fsize = os.path.getsize(dta_path)
    print(f"\n读取 .dta ({fsize/1e9:.1f}GB)...")
    t0 = time.time()

    # 尝试 C002006000，如果没有则尝试 Capexp
    read_cols = ["Stkcd", "Accper", "Typrep"]
    col = None
    for candidate in [CSMAR_COL, LEGACY_COL]:
        try:
            test = pd.read_stata(dta_path, columns=[candidate])
            col = candidate
            break
        except (ValueError, KeyError):
            continue

    if col is None:
        print(f"  ❌ .dta 中无 {CSMAR_COL} 或 {LEGACY_COL}")
        return 0

    read_cols.append(col)
    df = pd.read_stata(dta_path, columns=read_cols, convert_categoricals=False)
    print(f"  完成: {len(df):,} 行, 字段={col} ({time.time()-t0:.0f}s)")

    # 过滤有值的行
    df_valid = df[df[col].notna()].copy()
    print(f"  非 NULL: {len(df_valid):,} 行")

    if len(df_valid) == 0:
        return 0

    # 合并报表 typrep='A'
    df_valid["Typrep"] = df_valid["Typrep"].fillna("A")
    df_valid["Accper"] = df_valid["Accper"].astype(str).str.strip()

    # 批量 UPDATE
    updated = 0
    batch = []
    t0 = time.time()

    for _, row in df_valid.iterrows():
        stkcd = str(row["Stkcd"])
        accper = row["Accper"]
        typrep = str(row.get("Typrep", "A"))
        val = float(row[col])

        conn.execute(
            f"""UPDATE cn_financials SET {MY_COL} = ?
                WHERE stkcd=? AND accper=? AND typrep=?""",
            (val, stkcd, accper, typrep),
        )
        if conn.total_changes > 0:
            updated += 1
        else:
            # 如果主键不匹配（可能 typrep 不同），尝试无 typrep 匹配
            conn.execute(
                f"""UPDATE cn_financials SET {MY_COL} = ?
                    WHERE stkcd=? AND accper=?""",
                (val, stkcd, accper),
            )
            if conn.total_changes > 0:
                updated += 1

        batch.append((stkcd, accper))
        if len(batch) >= 5000:
            conn.commit()
            print(f"  已更新 {updated:,} 行 ({time.time()-t0:.0f}s)", end="\r")
            batch = []

    conn.commit()
    print(f"\n  更新完成: {updated:,} 行 ({time.time()-t0:.0f}s)")
    return updated


def sync_fundamentals(conn):
    """从 cn_financials 回填 fundamentals.capital_expenditure"""
    print("\n回填 fundamentals...")

    # 取每只股票最新一期合并报表的 capital_expenditure
    rows = conn.execute(f"""
        SELECT f.stkcd, f.{MY_COL}
        FROM cn_financials f
        INNER JOIN (
            SELECT stkcd, MAX(accper) as max_accper
            FROM cn_financials
            WHERE typrep='A' AND if_correct=0 AND {MY_COL} IS NOT NULL
            GROUP BY stkcd
        ) latest ON f.stkcd=latest.stkcd AND f.accper=latest.max_accper
        WHERE f.typrep='A' AND f.if_correct=0 AND f.{MY_COL} IS NOT NULL
    """).fetchall()

    if not rows:
        print("  无数据可回填")
        return 0

    stkcd_to_idx = {}
    for r in conn.execute("SELECT stkcd, index_id FROM stkcd_map WHERE matched=1"):
        stkcd_to_idx[r[0]] = r[1]

    updated = 0
    for stkcd, capex in rows:
        index_id = stkcd_to_idx.get(stkcd)
        if index_id is None:
            continue
        conn.execute(
            "UPDATE fundamentals SET capital_expenditure=? WHERE index_id=?",
            (capex, index_id),
        )
        updated += 1

    conn.commit()
    print(f"  fundamentals 更新: {updated} 只股票")
    return updated


if __name__ == "__main__":
    args = sys.argv[1:]

    if not os.path.exists(DB_PATH):
        print("数据库不存在:", DB_PATH)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")

    print("=== CAPEX 状态 ===")
    has_col = status(conn)

    if "--check" in args:
        conn.close()
        sys.exit(0)

    # 加列
    if not has_col:
        add_column(conn)

    # 从 .dta 导入
    mode = "quarterly"
    if "--mode" in args:
        idx = args.index("--mode") + 1
        if idx < len(args):
            mode = args[idx]
    dta_path = Q_DTA if mode == "quarterly" else A_DTA

    n = import_from_dta(conn, dta_path)
    if n > 0:
        m = sync_fundamentals(conn)
        print(f"\n=== 完成: cn_financials +{n} 行, fundamentals +{m} 只 ===")
    else:
        print("\n⚠️  未导入任何数据")

    # 最终状态
    print("\n=== 最终状态 ===")
    status(conn)

    conn.execute("PRAGMA synchronous=FULL")
    conn.close()
