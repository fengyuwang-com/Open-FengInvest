#!/usr/bin/env python3
"""feng_import_csmar.py — 导入 CSMAR A 股财务数据到 market_data.db

CSMAR 季度财务数据库（闲鱼 0.1 元）：
  5,822只股票, 754列, 1990-2025Q1, 2.1GB

用法:
    python tools/feng_import_csmar.py                              # 导入季度数据
    python tools/feng_import_csmar.py --mode annual                # 导入年度数据
    python tools/feng_import_csmar.py --status                     # 查看进度
    python tools/feng_import_csmar.py --update-fund                # 只更新 fundamentals 表
"""
import json, os, sqlite3, sys, time
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "data", "market_data.db")

Q_DTA = os.path.expanduser(r"~\Downloads\上市公司财务季度数据合并（90-25.3）.dta")
A_DTA = os.path.expanduser(r"~\Downloads\上市公司财务年度数据合并（90-24）.dta")

CN_FIN_TABLE = "cn_financials"
STKCD_MAP_TABLE = "stkcd_map"

# ── 正确的列映射（来自 字段说明.txt）─────────────────────────────────
# 映射策略：A=资产负债表, B=利润表, C=现金流量表, D=补充
# F=计算比率, Ind=行业分类

BS_MAP = {
    # 关键总数
    "A001000000": "total_assets",
    "A002000000": "total_liabilities",
    "A003000000": "total_equity",
    "A004000000": "total_liab_equity",
    # 资产
    "A001100000": "current_assets",
    "A001200000": "noncurrent_assets",
    "A001101000": "cash",
    "A001107000": "trading_securities",
    "A001109000": "short_term_investments",
    "A001110000": "notes_receivable",
    "A001111000": "accounts_receivable",
    "A001127000": "receivables_financing",
    "A001112000": "prepayments",
    "A001119000": "interest_receivable",
    "A001120000": "dividend_receivable",
    "A001121000": "other_receivables",
    "A001123000": "inventory_net",
    "A001128000": "contract_assets",
    "A001124000": "noncurrent_assets_1yr",
    "A001125000": "other_current_assets",
    # 非流动资产
    "A001226000": "debt_investments",
    "A001202000": "afs_financial_assets",
    "A001227000": "other_debt_investments",
    "A001211000": "investment_properties",
    "A001212000": "fixed_assets_net",
    "A001213000": "construction_in_progress",
    "A001214000": "engineering_materials",
    "A001215000": "fixed_assets_disposal",
    "A001230000": "right_of_use_assets",
    "A001218000": "intangible_assets_net",
    "A001219000": "development_expenditure",
    "A001220000": "goodwill_net",
    "A001221000": "long_term_deferred_exp",
    "A001222000": "deferred_tax_assets",
    "A001223000": "other_noncurrent_assets",
    "A001228000": "other_equity_investments",
    "A001229000": "other_noncurrent_fin_assets",
    # 负债
    "A002101000": "short_term_borrowing",
    "A002105000": "trading_fin_liabilities",
    "A002107000": "notes_payable",
    "A002108000": "accounts_payable",
    "A002109000": "advances_from_customers",
    "A002128000": "contract_liabilities",
    "A002112000": "employee_payable",
    "A002113000": "taxes_payable",
    "A002114000": "interest_payable",
    "A002115000": "dividend_payable",
    "A002120000": "other_payables",
    "A002125000": "noncurrent_liab_1yr",
    "A002126000": "other_current_liabilities",
    "A002100000": "current_liabilities",
    "A002201000": "long_term_borrowing",
    "A002203000": "bonds_payable",
    "A002211000": "lease_liabilities",
    "A002204000": "long_term_payables",
    "A002207000": "provisions",
    "A002208000": "deferred_tax_liabilities",
    "A002200000": "noncurrent_liabilities",
    # 权益
    "A003101000": "paid_in_capital",
    "A003112000": "other_equity_instruments",
    "A003102000": "capital_surplus",
    "A003103000": "surplus_reserve",
    "A003105000": "retained_earnings",
    "A003111000": "other_comprehensive_income_bs",
    "A003100000": "parent_equity",
    "A003200000": "minority_interest",
}

IS_MAP = {
    "B001100000": "total_revenue",
    "B001101000": "operating_revenue_s",
    "B001201000": "operating_cost_s",
    "B001207000": "taxes_surcharges",
    "B001209000": "selling_expenses",
    "B001210000": "admin_expenses",
    "B001216000": "rnd_expenses",
    "B001211000": "finance_expenses",
    "B001300000": "operating_profit",
    "B001400000": "non_operating_income",
    "B001500000": "non_operating_expenses",
    "B001000000": "total_profit",
    "B002100000": "income_tax_expense",
    "B002000000": "net_profit",
    "B002000101": "parent_net_profit",
    "B002000201": "minority_interest_pl",
    "B003000000": "basic_eps_report",
    "B004000000": "diluted_eps_report",
    "B005000000": "other_comprehensive_income",
    "B006000000": "total_comprehensive_income",
    "B001302000": "investment_income",
    "B001301000": "fair_value_change",
    "B001212000": "asset_impairment_loss",
    "B001307000": "credit_impairment_loss",
}

CF_MAP = {
    "C001000000": "operating_cf_net",
    "C002000000": "investing_cf_net",
    "C003000000": "financing_cf_net",
    "C004000000": "forex_effect",
    "C005000000": "cash_net_change",
    "C005001000": "cash_begin",
    "C006000000": "cash_end",
}

# ── F-codes: 比率因子（保持原名，中文备注）────────────────────────────
# 直接用 F 前缀保留在数据库中

F_COLS = {
    # 偿债能力
    "F010101A": "current_ratio",
    "F010201A": "quick_ratio",
    "F010601A": "working_capital",
    "F011201A": "debt_to_asset_ratio",
    "F011301A": "long_term_loan_to_asset",
    "F011401A": "tangible_debt_to_asset",
    "F011601A": "equity_multiplier",
    "F011701A": "debt_to_equity_ratio",
    # 特殊项目（直接从年报摘要）
    "F020101": "nonrecurring_gain_loss",
    "F020102": "deducted_parent_net_profit",
    "F020103": "weighted_avg_roe",
    "F020104": "deducted_weighted_roe",
    "F020105": "deducted_basic_eps",
    "F020108": "basic_eps_summary",
    "F020109": "diluted_eps_summary",
    # 盈利能力
    "F050101B": "asset_return_rate_A",
    "F050102B": "asset_return_rate_B",
    "F050201B": "roa_A",
    "F050202B": "roa_B",
    "F050501B": "roe_A",
    "F050502B": "roe_B",
    "F050601B": "ebit",
    "F050701B": "ebit_after_tax",
    "F050801B": "ebitda",
    "F051201B": "roic",
    "F053001B": "parent_roe_A",
    "F053002B": "parent_roe_B",
    "F053301B": "gross_margin",
    "F051401B": "operating_margin",
    "F051501B": "net_margin",
    "F051701B": "selling_expense_ratio",
    "F051801B": "admin_expense_ratio",
    "F051901B": "finance_expense_ratio",
    "F053401B": "rnd_expense_ratio",
    # 现金流质量
    "F060101B": "ocf_to_net_profit",
    "F060301B": "ocf_to_revenue",
    "F060401B": "ocf_to_op_profit",
    "F061701B": "cash_recovery_rate",
    "F061801B": "operating_index",
    # 杠杆
    "F070101B": "financial_leverage",
    "F070301B": "total_leverage",
    # 增长
    "F080601A": "total_asset_growth_A",
    "F080602A": "total_asset_growth_B",
    "F080701B": "roe_growth_A",
    "F080702B": "roe_growth_B",
    "F080801B": "eps_growth_A",
    "F080802B": "eps_growth_B",
    "F081001B": "net_profit_growth_A",
    "F081002B": "net_profit_growth_B",
    "F081301B": "parent_net_profit_growth",
    "F081601B": "revenue_growth_A",
    "F081602C": "revenue_growth_B",
    "F082601B": "sustainable_growth_rate",
    # 每股数据
    "F090101B": "eps_1",
    "F090101C": "eps_ttm_1",
    "F090201B": "comprehensive_eps_1",
    "F090201C": "comprehensive_eps_ttm_1",
    "F090501B": "total_rev_per_share_1",
    "F090501C": "total_rev_per_share_ttm_1",
    "F090601B": "rev_per_share_1",
    "F090601C": "rev_per_share_ttm_1",
    "F090901B": "op_profit_per_share_1",
    "F090901C": "op_profit_per_share_ttm_1",
    "F091001A": "bvps_1",
    "F091101A": "tangible_bvps_1",
    "F091201A": "liab_per_share_1",
    "F091701A": "parent_bvps_1",
    "F091801B": "ocf_per_share_1",
    "F091801C": "ocf_per_share_ttm_1",
    "F092101B": "fcf_per_share_1",
    "F092101C": "fcf_per_share_ttm_1",
    # 估值
    "F100101B": "pe_1",
    "F100102B": "pe_2",
    "F100103C": "pe_ttm",
    "F100201B": "ps_1",
    "F100202B": "ps_2",
    "F100203C": "ps_ttm",
    "F100301B": "pcf_1",
    "F100302B": "pcf_2",
    "F100303C": "pcf_ttm",
    "F100401A": "pb",
    "F100601B": "pe_parent_1",
    "F100602B": "pe_parent_2",
    "F100603C": "pe_parent_ttm",
    "F100701A": "pb_parent",
    "F100801A": "market_cap_A",
    "F100802A": "market_cap_B",
    "F100901A": "tobin_q_A",
    "F100902A": "tobin_q_B",
    "F100903A": "tobin_q_C",
    "F100904A": "tobin_q_D",
    "F101001A": "book_to_market_A",
    "F101002A": "book_to_market_B",
    "F101301B": "ev_to_ebitda",
    "F101302C": "ev_to_ebitda_ttm",
}

# ── 行业分类（保留原名）────────────────────────────────────────────
META_COLS = {
    "Indcd": "industry_csrc",
    "Indnme": "industry_csrc_name",
    "Indcd1": "industry_amac",
    "Indnme1": "industry_amac_name",
    "Source": "data_source",
}

ALL_MAP = {}
ALL_MAP.update(BS_MAP)
ALL_MAP.update(IS_MAP)
ALL_MAP.update(CF_MAP)
ALL_MAP.update(F_COLS)
ALL_MAP.update(META_COLS)


def get_db():
    if not os.path.exists(DB_PATH):
        print("数据库不存在:", DB_PATH)
        sys.exit(1)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")  # 加速批量导入
    return conn


def force_mode():
    return "--yes" in sys.argv or "--force" in sys.argv


def create_table(conn, drop_first=False):
    """创建 cn_financials 宽表"""
    if drop_first:
        conn.execute(f"DROP TABLE IF EXISTS {CN_FIN_TABLE}")
        conn.execute(f"DROP TABLE IF EXISTS {STKCD_MAP_TABLE}")

    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (CN_FIN_TABLE,))
    if cur.fetchone():
        print(f"  {CN_FIN_TABLE} 已存在")
        return

    # 基础列 + ALL_MAP 中的列（排除行业类 TEXT 列）
    sql_cols = []
    text_cols = set(META_COLS.values())
    for rname in ALL_MAP.values():
        if rname in text_cols:
            sql_cols.append(f'"{rname}" TEXT')
        else:
            sql_cols.append(f'"{rname}" REAL')

    conn.execute(f"""
    CREATE TABLE {CN_FIN_TABLE} (
        stkcd TEXT NOT NULL,
        accper TEXT NOT NULL,
        short_name TEXT,
        typrep TEXT,
        if_correct INTEGER DEFAULT 0,
        declare_date TEXT,
        {', '.join(sql_cols)},
        PRIMARY KEY (stkcd, accper, typrep)
    )
    """)
    conn.execute(f"""
    CREATE TABLE IF NOT EXISTS {STKCD_MAP_TABLE} (
        stkcd TEXT PRIMARY KEY,
        index_id INTEGER,
        ticker TEXT,
        name TEXT,
        market TEXT,
        matched INTEGER DEFAULT 0
    )
    """)
    print(f"  表已创建: {CN_FIN_TABLE}, {STKCD_MAP_TABLE}")


def build_stkcd_map(conn, dta_path):
    """将 CSMAR Stkcd → 数据库 index_id"""
    cur = conn.execute(f"SELECT COUNT(*) FROM {STKCD_MAP_TABLE}")
    if cur.fetchone()[0] > 0:
        print(f"  {STKCD_MAP_TABLE} 已有数据")
        return

    cn_stocks = {}
    for row in conn.execute(
        "SELECT id, ticker, name FROM indices WHERE market='CN' AND category='stock'"
    ):
        idx_id, ticker, name = row
        stkcd = ticker.split(".")[0]
        cn_stocks[stkcd] = (idx_id, ticker, name)

    import pandas as pd
    if not os.path.exists(dta_path):
        print(f"  .dta 不存在: {dta_path}")
        return

    df = pd.read_stata(dta_path, columns=["Stkcd"])
    csmar_set = set(df["Stkcd"].unique())
    print(f"  数据库CN: {len(cn_stocks)} 只, CSMAR: {len(csmar_set)} 只")

    matched, unmatched = 0, []
    for stkcd in sorted(csmar_set):
        if stkcd in cn_stocks:
            idx_id, tkr, nm = cn_stocks[stkcd]
            conn.execute(
                f"INSERT INTO {STKCD_MAP_TABLE} VALUES (?,?,?,?,?,1)",
                (stkcd, idx_id, tkr, nm, "CN"),
            )
            matched += 1
        else:
            conn.execute(
                f"INSERT INTO {STKCD_MAP_TABLE} (stkcd, matched) VALUES (?,0)",
                (stkcd,),
            )
            unmatched.append(stkcd)
    conn.commit()
    print(f"  匹配: {matched}, 未匹配: {len(unmatched)}")


def import_data(conn, dta_path):
    """导入 CSMAR 数据"""
    if not os.path.exists(dta_path):
        print(f"文件不存在: {dta_path}")
        return

    import pandas as pd

    fsize = os.path.getsize(dta_path)
    print(f"\n读取 .dta ({fsize/1e9:.1f}GB)...")
    t0 = time.time()
    df = pd.read_stata(dta_path)
    print(f"  完成: {len(df):,} 行 x {len(df.columns)} 列 ({time.time()-t0:.0f}s)")

    # 检查已有数据
    cur = conn.execute(f"SELECT COUNT(*) FROM {CN_FIN_TABLE}")
    if cur.fetchone()[0] > 0:
        if force_mode():
            conn.execute(f"DELETE FROM {CN_FIN_TABLE}")
        else:
            ans = input(f"  {CN_FIN_TABLE} 已有数据，覆盖? (y/N): ")
            if ans.lower() != "y":
                return
            conn.execute(f"DELETE FROM {CN_FIN_TABLE}")

    # 构建INSERT
    final_cols = ["stkcd", "accper", "short_name", "typrep", "if_correct", "declare_date"]
    final_cols += list(ALL_MAP.values())
    placeholders = ",".join("?" for _ in final_cols)
    insert_sql = f"INSERT INTO {CN_FIN_TABLE} ({','.join(final_cols)}) VALUES ({placeholders})"

    col_to_rname = {}  # CSMAR名 → 我们的名
    for csmar_code, rname in ALL_MAP.items():
        if csmar_code in df.columns:
            col_to_rname[csmar_code] = rname

    print(f"  映射列: {len(col_to_rname)}/{len(ALL_MAP)}")
    print(f"  写入 {len(df):,} 行...")
    t0 = time.time()
    batch = []

    for i, (_, row) in enumerate(df.iterrows()):
        vals = [
            str(row.get("Stkcd", "")),
            str(row.get("Accper", "")),
            str(row.get("ShortName", "")) if pd.notna(row.get("ShortName")) else None,
            str(row.get("Typrep", "A")),
            1 if row.get("IfCorrect") == 1 else 0,
            str(row.get("DeclareDate", "")) if pd.notna(row.get("DeclareDate")) else None,
        ]

        for csmar_code in ALL_MAP:
            if csmar_code not in df.columns:
                vals.append(None)
                continue
            # 特殊处理行业代码（字符型）
            if csmar_code in META_COLS:
                v = row.get(csmar_code)
                vals.append(str(v) if pd.notna(v) else None)
            else:
                v = row.get(csmar_code)
                if pd.notna(v):
                    try:
                        vals.append(float(v))
                    except (ValueError, TypeError):
                        vals.append(None)
                else:
                    vals.append(None)

        batch.append(vals)
        if len(batch) >= 1000:
            conn.executemany(insert_sql, batch)
            conn.commit()
            batch = []

    if batch:
        conn.executemany(insert_sql, batch)
        conn.commit()

    print(f"  写入完成 ({time.time()-t0:.0f}s)")


def update_fundamentals(conn):
    """从 cn_financials 最新数据更新 fundamentals 表"""
    print("\n更新 fundamentals 表...")

    # 取每只股票最新一期合并报表数据
    rows = conn.execute(f"""
        SELECT f.stkcd, f.accper,
               f.total_assets, f.total_liabilities, f.total_equity,
               f.net_profit, f.operating_revenue_s, f.operating_cf_net,
               f.total_profit, f.basic_eps_summary,
               f.roe_A, f.roa_A, f.parent_roe_A,
               f.gross_margin, f.net_margin, f.operating_margin,
               f.ebit, f.ebitda, f.roic,
               f.pe_ttm, f.pb, f.ps_ttm,
               f.market_cap_A, f.bvps_1, f.eps_ttm_1,
               f.debt_to_asset_ratio, f.current_ratio, f.ocf_per_share_1,
               f.revenue_growth_B, f.parent_net_profit_growth,
               f.weighted_avg_roe,
               f.industry_csrc_name
        FROM {CN_FIN_TABLE} f
        INNER JOIN (
            SELECT stkcd, MAX(accper) as max_accper
            FROM {CN_FIN_TABLE}
            WHERE typrep='A' AND if_correct=0
            GROUP BY stkcd
        ) latest ON f.stkcd=latest.stkcd AND f.accper=latest.max_accper
        WHERE f.typrep='A' AND f.if_correct=0
    """).fetchall()

    print(f"  最新数据: {len(rows)} 只股票")

    stkcd_to_idx = {}
    for r in conn.execute(f"SELECT stkcd, index_id FROM {STKCD_MAP_TABLE} WHERE matched=1"):
        stkcd_to_idx[r[0]] = r[1]

    updated = 0
    for r in rows:
        stkcd = r[0]
        index_id = stkcd_to_idx.get(stkcd)
        if index_id is None:
            continue

        (_, total_assets, total_liabilities, total_equity,
         net_profit, operating_revenue, ocf,
         total_profit, eps_summary,
         roe_A, roa_A, parent_roe_A,
         gross_margin, net_margin_val, op_margin,
         ebit, ebitda, roic_val,
         pe_ttm, pb, ps_ttm,
         mcap_A, bvps_1, eps_ttm_1,
         debt_to_asset_ratio, current_ratio, ocf_per_share,
         rev_growth_b, parent_np_growth,
         weighted_avg_roe,
         industry) = r[1:]

        conn.execute("""
            INSERT OR REPLACE INTO fundamentals
            (index_id, updated_at,
             market_cap, return_on_equity, return_on_assets,
             profit_margin, gross_margin, operating_margin,
             free_cashflow, operating_cashflow,
             debt_to_equity, current_ratio,
             book_value, eps,
             revenue_growth, earnings_growth,
             sector, industry,
             trailing_pe, price_to_book, price_to_sales,
             enterprise_value)
            VALUES (?, datetime('now'),
             ?, ?, ?,
             ?, ?, ?,
             NULL, ?,
             ?, ?,
             ?, ?,
             ?, ?,
             NULL, ?,
             ?, ?, ?,
             NULL)
        """, (
            index_id,
            mcap_A or 0,
            weighted_avg_roe or roe_A or parent_roe_A,
            roa_A,
            net_margin_val, gross_margin, op_margin,
            ocf,
            debt_to_asset_ratio, current_ratio,
            bvps_1, eps_summary or eps_ttm_1,
            rev_growth_b, parent_np_growth,
            industry,
            pe_ttm, pb, ps_ttm,
        ))
        updated += 1

    conn.commit()
    print(f"  fundamentals 更新: {updated} 只股票")


def cmd_status(conn):
    fin = conn.execute(f"SELECT COUNT(*) FROM {CN_FIN_TABLE}").fetchone()[0]
    stk = conn.execute(f"SELECT COUNT(*) FROM {STKCD_MAP_TABLE}").fetchone()[0]
    matched = conn.execute(f"SELECT COUNT(*) FROM {STKCD_MAP_TABLE} WHERE matched=1").fetchone()[0]

    print(f"  {CN_FIN_TABLE}: {fin:,} 行")
    print(f"  {STKCD_MAP_TABLE}: {stk} 只 (匹配 {matched})")

    if fin:
        yr = conn.execute(f"SELECT MIN(accper), MAX(accper) FROM {CN_FIN_TABLE}").fetchone()
        print(f"  日期范围: {yr[0]} ~ {yr[1]}")

    # fundamentals 状态
    for mkt in ["CN", "US", "HK"]:
        tot = conn.execute(
            "SELECT COUNT(*) FROM indices WHERE category='stock' AND market=?", (mkt,)
        ).fetchone()[0]
        has = conn.execute(
            "SELECT COUNT(*) FROM fundamentals f JOIN indices i ON f.index_id=i.id WHERE i.market=?", (mkt,)
        ).fetchone()[0]
        print(f"  fundamentals {mkt}: {has}/{tot}")


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--status" in args:
        conn = get_db()
        cmd_status(conn)
        conn.close()
        sys.exit(0)

    mode = "quarterly"
    if "--mode" in args:
        idx = args.index("--mode") + 1
        if idx < len(args):
            mode = args[idx]

    dta_path = Q_DTA if mode == "quarterly" else A_DTA

    if "--update-fund" in args:
        conn = get_db()
        update_fundamentals(conn)
        conn.close()
        sys.exit(0)

    conn = get_db()
    create_table(conn, drop_first=False)
    build_stkcd_map(conn, dta_path)

    import_data(conn, dta_path)

    print("\n导入后状态:")
    cmd_status(conn)

    ans = "y" if force_mode() else input("\n更新 fundamentals 表? (y/N): ")
    if ans.lower() == "y":
        update_fundamentals(conn)

    conn.execute("PRAGMA synchronous=FULL")
    conn.close()
    print("\n完成")
