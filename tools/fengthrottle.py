#!/usr/bin/env python3
"""
FengInvest 数据获取限流 + TTL 缓存（OpenBB fred provider 范式移植）

解决的问题：外部数据源（行情/宏观/汇率 API）无节流地调用会被封，且重复
拉取同一数据是浪费。OpenBB 的 fred 提供方用「限流 + TTL 缓存 + single-flight」
三层保护；本工具移植前两层（single-flight 针对多线程服务，本系统是单进程
CLI，无并发场景，不做）。

行为（全部保守）：
- TTL 内命中 → 直接返回缓存，零网络请求；
- TTL 过期 → 先做主机级限流检查，未到间隔就等待（有界），超时则回退
  陈旧缓存（stale），彻底没有才报错；
- 限流状态跨进程持久化（调用记录写盘），连续运行多个命令也不会打爆 API。

用法（库）：
    from fengthrottle import cached_get
    data, source = cached_get("https://example.com/api", params={"q": "1"},
                              ttl=86400)   # source: cached_fresh|cached_stale|network

用法（CLI）：
    python tools/fengthrottle.py get <URL> [--ttl 3600] [--params k=v,k2=v2]
    python tools/fengthrottle.py stats
    python tools/fengthrottle.py prune

缓存文件：data/cache/fengthrottle.jsonl（gitignored，不入仓）。
"""
import argparse
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_FILE = os.path.join(BASE, "data", "cache", "fengthrottle.jsonl")

DEFAULT_MIN_INTERVAL = 1.2      # 每主机最小调用间隔（秒）
DEFAULT_MAX_PER_MIN = 120       # 每主机每分钟上限
DEFAULT_WAIT_TIMEOUT = 30.0     # 等待限流的最长时间（秒），超时回退 stale
# UA 可用环境变量覆盖（SEC EDGAR 要求 UA 含联系方式，如 FENG_HTTP_UA="Name email"）
DEFAULT_UA = os.environ.get("FENG_HTTP_UA", "FengInvest/1.0 (local research tool)")
MAX_ENTRIES = 5000              # 缓存条目上限（超出裁剪最旧）

_cache = None  # 进程内缓存：{key: entry, "_hosts": {host: [ts,...]}}


def _now():
    return time.time()


def _load():
    global _cache
    if _cache is not None:
        return _cache
    _cache = {"_hosts": {}}
    if not os.path.exists(CACHE_FILE):
        return _cache
    with open(CACHE_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("t") == "call":
                _cache["_hosts"].setdefault(e["host"], []).append(e["ts"])
            else:
                _cache[e["key"]] = e
    return _cache


def _save():
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    lines = []
    for key, e in _cache.items():
        if key == "_hosts":
            continue
        lines.append(json.dumps(e, ensure_ascii=False))
    for host, ts_list in _cache["_hosts"].items():
        for ts in ts_list[-60:]:  # 每主机只保留最近 60 条调用记录
            lines.append(json.dumps({"t": "call", "host": host, "ts": ts}))
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _key(url, params):
    raw = url + "|" + json.dumps(params or {}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _host_of(url):
    return urllib.parse.urlparse(url).netloc


def _rate_ok(host, min_interval, max_per_min):
    """检查主机限流。返回 (是否放行, 需等待秒数)。"""
    db = _load()
    calls = db["_hosts"].get(host, [])
    t = _now()
    # 清理窗口外记录
    calls = [ts for ts in calls if t - ts < 60]
    db["_hosts"][host] = calls
    if calls:
        since_last = t - calls[-1]
        if since_last < min_interval:
            return False, min_interval - since_last
    if len(calls) >= max_per_min:
        return False, 60.0 - (t - calls[0])
    return True, 0.0


def _record_call(host):
    db = _load()
    db["_hosts"].setdefault(host, []).append(_now())
    _save()


def _http_get(url, params, timeout):
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        ctype = resp.headers.get("Content-Type", "")
    try:
        if "json" in ctype or body.lstrip().startswith(("{", "[")):
            return json.loads(body)
        return body
    except json.JSONDecodeError:
        return body


def cached_get(url, params=None, ttl=3600, min_interval=DEFAULT_MIN_INTERVAL,
               max_per_min=DEFAULT_MAX_PER_MIN, wait_timeout=DEFAULT_WAIT_TIMEOUT,
               timeout=30):
    """限流 + TTL 缓存取数。返回 (data, source)。

    source: cached_fresh(缓存未过期) | cached_stale(限流超时回退旧缓存)
            | network(新拉取)。network/stale 都附带 etag 语义无；失败抛异常。
    """
    db = _load()
    k = _key(url, params)
    host = _host_of(url)
    entry = db.get(k)
    t = _now()

    if entry and t - entry["fetched_at"] < entry["ttl"]:
        return entry["data"], "cached_fresh"

    # 限流等待（有界）：放行 → 网络拉取；不放行 → 等至可放行或超时
    ok, wait = _rate_ok(host, min_interval, max_per_min)
    if not ok and wait <= wait_timeout:
        time.sleep(wait)
        ok, _ = _rate_ok(host, min_interval, max_per_min)

    if ok:
        try:
            data = _http_get(url, params, timeout)
        except Exception:
            # 网络失败：有陈旧缓存就回退，没有就上抛
            if entry:
                return entry["data"], "cached_stale"
            raise
        _record_call(host)
        entry = {"key": k, "url": url, "host": host,
                 "fetched_at": t, "ttl": ttl, "data": data}
        db[k] = entry
        # 上限裁剪（保留最旧条目按 key 迭代顺序）
        keys = [kk for kk in db if kk != "_hosts"]
        if len(keys) > MAX_ENTRIES:
            for kk in keys[:-MAX_ENTRIES]:
                db.pop(kk, None)
        _save()
        return data, "network"

    # 限流等待超时：回退陈旧缓存，没有则明确报错
    if entry:
        return entry["data"], "cached_stale"
    raise RuntimeError(f"主机 {host} 限流且无缓存可用（等待 {wait_timeout}s 超时）")


def cmd_get(args):
    params = {}
    for kv in (args.params or []):
        k, _, v = kv.partition("=")
        params[k] = v
    try:
        data, source = cached_get(args.url, params=params or None,
                                  ttl=args.ttl, min_interval=args.min_interval,
                                  wait_timeout=args.wait_timeout)
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        return 1
    print(json.dumps({"source": source, "data": data}, indent=2, ensure_ascii=False))
    return 0


def cmd_stats(args):
    db = _load()
    n_cache = sum(1 for k in db if k != "_hosts")
    hosts = {h: len(ts) for h, ts in db["_hosts"].items()}
    print(json.dumps({"cache_entries": n_cache, "call_log_per_host": hosts,
                      "cache_file": CACHE_FILE}, indent=2, ensure_ascii=False))
    return 0


def cmd_prune(args):
    db = _load()
    keys = [k for k in db if k != "_hosts"]
    before = len(keys)
    if before > MAX_ENTRIES:
        for kk in keys[:-MAX_ENTRIES]:
            db.pop(kk, None)
        _save()
    print(json.dumps({"pruned": before - min(before, MAX_ENTRIES),
                      "before": before, "after": min(before, MAX_ENTRIES)},
                     indent=2, ensure_ascii=False))
    return 0


def main():
    ap = argparse.ArgumentParser(description="FengInvest 限流 + TTL 缓存取数")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_get = sub.add_parser("get", help="限流缓存取数")
    p_get.add_argument("url")
    p_get.add_argument("--params", nargs="*", default=[], help="k=v 键值对")
    p_get.add_argument("--ttl", type=int, default=3600, help="缓存秒数（默认 1h）")
    p_get.add_argument("--min-interval", type=float, default=DEFAULT_MIN_INTERVAL)
    p_get.add_argument("--wait-timeout", type=float, default=DEFAULT_WAIT_TIMEOUT)
    p_get.set_defaults(func=cmd_get)

    p_stats = sub.add_parser("stats")
    p_stats.set_defaults(func=cmd_stats)

    p_prune = sub.add_parser("prune")
    p_prune.set_defaults(func=cmd_prune)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
