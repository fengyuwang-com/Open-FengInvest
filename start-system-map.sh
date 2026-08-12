#!/bin/bash
# system-map 静态服务器 — Tailscale 网内可访问
# 用法: ./start-system-map.sh [端口]   (默认 34567, 小众端口防误杀)
# 说明: 模式参照 start-web.sh(端口检测->清理->启动), 但:
#   - 只杀占用本端口(默认34567)的进程, 绝不 taskkill 全杀 node
#   - 静态文件用 python http.server, 零依赖
#   - 绑定 0.0.0.0, Tailscale 网内其它设备可直接访问

PORT="${1:-34567}"
BASE="$(cd "$(dirname "$0")" && pwd)"
DIR="$BASE/docs"
TS_IP="$(tailscale ip -4 2>/dev/null | head -1)"

# 找占用该端口的 PID: 优先 lsof, 没有则用 netstat
port_pids() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -ti:"$PORT" -P -n 2>/dev/null
  else
    netstat -ano | grep -E "[:.]$PORT[ \t]+.*LISTENING" | awk '{print $NF}' | sort -u
  fi
}

# 端口占用检测与清理
PIDS="$(port_pids)"
if [ -n "$PIDS" ]; then
  echo "[WARN] 端口 $PORT 被占用, 清理旧进程: $PIDS"
  for pid in $PIDS; do
    kill -9 "$pid" 2>/dev/null || taskkill //F //PID "$pid" 2>/dev/null
  done
  sleep 1
fi

echo "system-map 静态服务:"
echo "  本机:     http://localhost:$PORT/system-map.html"
[ -n "$TS_IP" ] && echo "  Tailscale: http://$TS_IP:$PORT/system-map.html"
exec python -m http.server "$PORT" --bind 0.0.0.0 --directory "$DIR"
