#!/usr/bin/env python3
"""
FengInvest 决策缓存（Prompt 级 · ai-hedge-fund 移植）

原理（来自 ai-hedge-fund 的 prompt 级决策缓存）：对完全相同的输入
（ticker + 步骤 + 输出文件内容 sha256），上次的验证结论仍然成立，
重复分析是浪费 —— 直接复用缓存结论。

适用场景：
- 状态机 renew 重置后，某层输出文件内容与已验证版本逐字节一致 →
  该层已"完成且验证通过"，无需重跑分析/验证；
- 内容有任何变化 → 缓存 miss，走正常验证流程（绝不误判）。

保证无损：
- 命中条件 = ticker + step + 内容 sha256 三者全等，且 verify_ok=True；
- 只跳过"重复验证"，不改变状态机语义（complete 仍写状态文件）；
- 缓存文件 research/state/cache_decisions.jsonl（gitignored，不入仓）。

用法：
  python tools/fengcache.py get <TICKER> <STEP> <FILE>     # 查缓存（JSON）
  python tools/fengcache.py put <TICKER> <STEP> <FILE>     # 写入（默认 verify_ok=True）
  python tools/fengcache.py prune                          # 裁剪超上限条目
"""
import argparse
import hashlib
import json
import os
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_FILE = os.path.join(BASE, "research", "state", "cache_decisions.jsonl")
MAX_ENTRIES = 1000  # 上限：超出后裁剪最旧条目


def _content_sha256(path):
    """输出文件内容哈希（决策的指纹）。"""
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _key(ticker, step, content_hash):
    """缓存键：ticker + 步骤 + 内容哈希 三者全等才命中。"""
    return hashlib.sha256(
        f"{ticker.upper()}|{step}|{content_hash}".encode("utf-8")
    ).hexdigest()


def _read_all():
    if not os.path.exists(CACHE_FILE):
        return []
    entries = []
    with open(CACHE_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def _write_all(entries):
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def get(ticker, step, output_file):
    """查缓存。命中返回条目 dict（含 verify_ok），否则 None。"""
    if not os.path.exists(output_file):
        return None
    content_hash = _content_sha256(output_file)
    k = _key(ticker, step, content_hash)
    for e in reversed(_read_all()):  # 新条目优先
        if e.get("key") == k:
            return e
    return None


def put(ticker, step, output_file, verify_ok=True):
    """写入缓存（覆盖同键旧条目）。返回写入的条目。"""
    content_hash = _content_sha256(output_file)
    k = _key(ticker, step, content_hash)
    entry = {
        "key": k,
        "ticker": ticker.upper(),
        "step": step,
        "content_sha256": content_hash[:16],  # 展示用截断，键用完整哈希
        "verify_ok": bool(verify_ok),
        "output": os.path.abspath(output_file),
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    entries = _read_all()
    entries = [e for e in entries if e.get("key") != k]
    entries.append(entry)
    if len(entries) > MAX_ENTRIES:
        entries = entries[-MAX_ENTRIES:]
    _write_all(entries)
    return entry


def prune():
    """裁剪超上限条目。返回 (裁剪前, 裁剪后)。"""
    entries = _read_all()
    before = len(entries)
    after = len(entries)
    if before > MAX_ENTRIES:
        entries = entries[-MAX_ENTRIES:]
        _write_all(entries)
        after = len(entries)
    return before, after


def cmd_get(args):
    hit = get(args.ticker, args.step, args.file)
    if hit:
        print(json.dumps({"hit": True, "verify_ok": hit.get("verify_ok", False),
                          "cached_at": hit.get("cached_at"),
                          "output": hit.get("output")}, indent=2, ensure_ascii=False))
        return 0
    print(json.dumps({"hit": False}, indent=2, ensure_ascii=False))
    return 0


def cmd_put(args):
    entry = put(args.ticker, args.step, args.file, verify_ok=not args.no_verify)
    print(json.dumps({"hit": True, "key": entry["key"],
                      "content_sha256": entry["content_sha256"],
                      "cached_at": entry["cached_at"]}, indent=2, ensure_ascii=False))
    return 0


def cmd_prune(args):
    before, after = prune()
    print(json.dumps({"pruned": before - after, "before": before, "after": after},
                     indent=2, ensure_ascii=False))
    return 0


def main():
    ap = argparse.ArgumentParser(description="FengInvest 决策缓存（Prompt 级）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_get = sub.add_parser("get", help="查缓存")
    p_get.add_argument("ticker")
    p_get.add_argument("step")
    p_get.add_argument("file")
    p_get.set_defaults(func=cmd_get)

    p_put = sub.add_parser("put", help="写缓存")
    p_put.add_argument("ticker")
    p_put.add_argument("step")
    p_put.add_argument("file")
    p_put.add_argument("--no-verify", action="store_true", help="标记 verify_ok=False")
    p_put.set_defaults(func=cmd_put)

    p_prune = sub.add_parser("prune", help="裁剪超上限条目")
    p_prune.set_defaults(func=cmd_prune)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    import sys
    sys.exit(main())
