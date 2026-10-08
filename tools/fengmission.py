#!/usr/bin/env python3
"""fengmission.py — 自主进化看板数据探针（只读）。

输出 JSON：三市场 dividends/daily 新鲜度 + 论断台账/策略卡计数。
GUI: /api/mission/overview 调用；CLI 可直接跑。
"""
import json
import os
import sqlite3
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "data", "market_data.db")


def db_freshness() -> dict:
    out = {}
    if not os.path.exists(DB):
        return {"_error": "no db"}
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        for m in ("US", "CN", "HK"):
            div = cur.execute(
                "SELECT MAX(d.ex_date) FROM dividends d JOIN indices i ON i.id=d.index_id WHERE i.market=?",
                (m,)).fetchone()[0]
            day = cur.execute(
                "SELECT MAX(da.date) FROM daily_data da JOIN indices i ON i.id=da.index_id WHERE i.market=?",
                (m,)).fetchone()[0]
            out[m] = {"dividends_max": div, "daily_max": day}
    finally:
        con.close()
    return out


def tool_health() -> dict:
    """读 fengprobe.py 写的冒烟报告（只读）；没跑过/太旧都显式亮灯，不静默。"""
    path = os.path.join(BASE, "data", "reports", "tool_health.json")
    if not os.path.exists(path):
        return {"status": "missing", "note": "探针从未运行（跑 python tools/fengprobe.py 或点看板按钮）"}
    try:
        with open(path, encoding="utf-8") as f:
            report = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return {"status": "corrupt", "note": f"报告不可读: {e}"}
    stale = False
    try:
        from datetime import datetime
        age_h = (datetime.now() - datetime.fromisoformat(report["generated_at"])).total_seconds() / 3600
        stale = age_h > 26  # 每日节律：超过一天+2小时余量即陈旧
        report["age_hours"] = round(age_h, 1)
    except (KeyError, ValueError, TypeError):
        stale = True
    report["stale"] = stale
    report["status"] = "ok"
    return report


def main() -> dict:
    return {"source": "fengmission.py (sqlite read-only)", "freshness": db_freshness(),
            "tool_health": tool_health()}


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False))
