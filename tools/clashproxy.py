#!/usr/bin/env python3
"""clashproxy.py — Clash Verge API 控制 & 代理切换

Clash Verge Rev 的 API:
  - external-controller: 127.0.0.1:9097 (from generated config.yaml)
  - 通过 HTTP API 查询代理组、切换节点

用法:
    python tools/clashproxy.py status       # 检查 Clash 运行状态
    python tools/clashproxy.py list          # 列出代理组和节点
    python tools/clashproxy.py switch <节点名>  # 切换特定节点
    python tools/clashproxy.py group <组名>     # 查看指定组的节点
    python tools/clashproxy.py jp            # 快捷切换到日本节点
    python tools/clashproxy.py hk            # 快捷切换到香港节点
    python tools/clashproxy.py us            # 快捷切换到美国节点
    python tools/clashproxy.py auto          # 切换到自动选择
    python tools/clashproxy.py proxy-url     # 打印 HTTP 代理地址
"""
import json, os, subprocess, sys, time, urllib.request, urllib.error
import yaml

sys.stdout.reconfigure(encoding="utf-8")

CLASH_EXE = r"C:\Program Files\Clash Verge\clash-verge.exe"
CLASH_API = "http://127.0.0.1:9097"
CLASH_SECRET = "set-your-secret"
CLASH_MIXED_PORT = 7897  # from verge config
CLASH_VERGE_CONFIG = os.path.expanduser(
    r"~\AppData\Roaming\io.github.clash-verge-rev.clash-verge-rev\verge.yaml"
)

# ── API 请求 ──
def api_get(path):
    url = f"{CLASH_API}{path}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {CLASH_SECRET}")
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return None

def api_put(path, data=None):
    url = f"{CLASH_API}{path}"
    body = json.dumps(data).encode() if data else b""
    req = urllib.request.Request(url, data=body, method="PUT")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {CLASH_SECRET}")
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 204 or resp.status == 200
    except Exception:
        return False

# ── Clash 状态 ──
def is_running():
    proxies = api_get("/proxies")
    return proxies is not None

def enable_api():
    """在 verge.yaml 中启用 external-controller"""
    try:
        with open(CLASH_VERGE_CONFIG, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        if cfg.get("enable_external_controller"):
            return True  # 已经启用
        cfg["enable_external_controller"] = True
        with open(CLASH_VERGE_CONFIG, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, allow_unicode=True)
        print("🔓 已启用 external-controller（需重启 Clash 生效）")
        return True
    except Exception as e:
        print(f"⚠️ 无法修改 verge.yaml: {e}")
        return False

def start_clash():
    print("正在启动 Clash Verge...")
    enable_api()
    subprocess.Popen([CLASH_EXE], shell=True)
    for i in range(30):
        time.sleep(1)
        if is_running():
            print(f"✅ Clash 已启动（{i+1}s）")
            return True
    print("❌ Clash 启动超时")
    return False

# ── 代理组列表 ──
def list_groups():
    proxies = api_get("/proxies")
    if not proxies:
        return None
    groups = {}
    for name, info in proxies.get("proxies", {}).items():
        if info.get("type") in ("Selector", "URLTest", "Fallback", "LoadBalance"):
            groups[name] = info
    return groups

def cmd_status():
    if is_running():
        proxies = api_get("/proxies")
        if proxies:
            groups = list_groups()
            if groups:
                print("Clash 运行中 ✅")
                print(f"\n代理组 ({len(groups)} 个):")
                for name, g in sorted(groups.items()):
                    now = g.get("now", "?")
                    total = len(g.get("all", []))
                    print(f"  {name}: {now} ({total} 节点)")
            else:
                print("Clash 运行中，但无代理组")
        else:
            print("Clash 运行中 ✅")
        print(f"\n代理地址: http://127.0.0.1:{CLASH_MIXED_PORT}")
        return True
    else:
        print("Clash 未运行 ❌")
        print("用 --start 参数启动")
        return False

def cmd_list():
    groups = list_groups()
    if groups is None:
        print("Clash 未运行 ❌")
        return
    for name, g in sorted(groups.items()):
        now = g.get("now", "?")
        all_nodes = g.get("all", [])
        print(f"\n{'='*50}")
        print(f"📁 {name}  [{g['type']}]")
        print(f"  当前: {now}")
        for i, node in enumerate(all_nodes):
            mark = " ←" if node == now else ""
            country = ""
            print(f"    {i+1:3d}. {node}{mark}")

def cmd_group(group_name):
    proxies = api_get("/proxies")
    if not proxies:
        print("Clash 未运行 ❌")
        return
    if group_name not in proxies:
        print(f"组 '{group_name}' 不存在")
        print(f"可用组: {', '.join(proxies.keys())}")
        return
    g = proxies[group_name]
    now = g.get("now", "?")
    all_nodes = g.get("all", [])
    print(f"📁 {group_name}  [{g['type']}]  当前: {now}")
    for i, node in enumerate(all_nodes):
        mark = " ←" if node == now else ""
        print(f"  {i+1:3d}. {node}{mark}")

# ── 切换节点 ──
def switch_node(node_name, target_group=None):
    """切换节点。如果指定 target_group 则只在该组中查找。"""
    groups = list_groups()
    if groups is None:
        return False
    if target_group:
        if target_group in groups:
            g = groups[target_group]
            if node_name in g.get("all", []):
                ok = api_put(f"/proxies/{target_group}", {"name": node_name})
                if ok:
                    print(f"✅ 已切换到 {target_group} → {node_name}")
                    return True
                else:
                    print(f"❌ 切换失败 {target_group} → {node_name}")
                    return False
            elif any(node_name.lower() in n.lower() for n in g.get("all", [])):
                matches = [n for n in g["all"] if node_name.lower() in n.lower()]
                target = matches[0]
                ok = api_put(f"/proxies/{target_group}", {"name": target})
                if ok:
                    print(f"✅ 已切换到 {target_group} → {target}")
                    return True
        print(f"❌ 组 '{target_group}' 中未找到匹配节点: {node_name}")
        return False
    for gname, g in groups.items():
        all_nodes = g.get("all", [])
        if node_name in all_nodes:
            ok = api_put(f"/proxies/{gname}", {"name": node_name})
            if ok:
                print(f"✅ 已切换到 {gname} → {node_name}")
                return True
            else:
                print(f"❌ 切换失败 {gname} → {node_name}")
                return False
    # 模糊匹配
    for gname, g in groups.items():
        all_nodes = g.get("all", [])
        matches = [n for n in all_nodes if node_name.lower() in n.lower()]
        if matches:
            target = matches[0]
            ok = api_put(f"/proxies/{gname}", {"name": target})
            if ok:
                print(f"✅ 已切换到 {gname} → {target}")
                return True
    print(f"❌ 未找到匹配节点: {node_name}")
    if groups:
        all_names = []
        for gname, g in groups.items():
            all_names.extend(g.get("all", []))
        print(f"  共 {len(all_names)} 个节点，可尝试: jp / hk / us / auto 等关键词")
    return False

def cmd_switch_keyword(keyword):
    """按关键词搜索并切换。 关键词: jp, hk, us, sg, auto 等"""
    groups = list_groups()
    if groups is None:
        print("Clash 未运行 ❌")
        return False

    if keyword == "auto":
        # 切到自动选择组
        for gname, g in groups.items():
            if "auto" in gname.lower() or "自动" in gname:
                for node in g.get("all", []):
                    if "auto" in node.lower():
                        return switch_node(node)
        print("❌ 未找到自动选择组")
        return False

    # 模糊搜索关键词 (jp → 日本, 东京, JP, Japan, 日本東京 等)
    for gname, g in groups.items():
        for node in g.get("all", []):
            if keyword.lower() in node.lower():
                return switch_node(node)

    print(f"❌ 未找到包含 '{keyword}' 的节点")
    return False

# ── 打印代理地址 ──
def cmd_proxy_url():
    print(f"http://127.0.0.1:{CLASH_MIXED_PORT}")
    print(f"socks5://127.0.0.1:{CLASH_MIXED_PORT}")

def cmd_use_proxy():
    """返回代理字符串，可用于 requests session"""
    proxy = f"http://127.0.0.1:{CLASH_MIXED_PORT}"
    proxies = {"http": proxy, "https": proxy}
    print(json.dumps(proxies))
    return proxies

# ── 主入口 ──
if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)

    cmd = args[0]

    if cmd == "status":
        cmd_status()
    elif cmd == "list":
        cmd_list()
    elif cmd == "group" and len(args) > 1:
        cmd_group(args[1])
    elif cmd == "switch" and len(args) > 1:
        switch_node(args[1])
    elif cmd == "proxy-url":
        cmd_proxy_url()
    elif cmd == "proxy":
        cmd_use_proxy()
    elif cmd in ("jp", "hkg"):
        switch_node("jp", target_group="Proxy") or switch_node("日本", target_group="Proxy")
    elif cmd == "hk":
        switch_node("hk", target_group="Proxy") or switch_node("香港", target_group="Proxy")
    elif cmd == "us":
        switch_node("us", target_group="Proxy") or switch_node("美国", target_group="Proxy")
    elif cmd == "sg":
        switch_node("sg", target_group="Proxy") or switch_node("新加坡", target_group="Proxy")
    elif cmd == "auto":
        switch_node("auto", target_group="Proxy")
    elif cmd == "start":
        start_clash()
    else:
        print(f"未知命令: {cmd}")
        print(__doc__)
