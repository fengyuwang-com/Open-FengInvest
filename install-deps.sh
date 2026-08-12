#!/usr/bin/env bash
# install-deps.sh — 一键安装次要工具依赖
# 核心(持仓监控/行情/组合检查)零依赖, 无需跑本脚本; 本脚本只装增强库。
set -e
cd "$(dirname "$0")"

echo "==> [1/3] 检查 Python"
python --version

echo "==> [2/3] 安装 requirements.txt 依赖"
python -m pip install -r requirements.txt

echo "==> [3/3] 验证核心功能零依赖可用"
python - <<'PY'
import sys, importlib
# 核心链路脚本必须能 import 而不失败
for mod in ("fengwatch", "fengdata", "fengportfolio"):
    try:
        importlib.import_module(f"tools.{mod}")
        print(f"  OK  tools/{mod}.py 可加载")
    except Exception as e:
        print(f"  WARN tools/{mod}.py: {e}")
sys.path.insert(0, "tools")
import fengdata
r = fengdata._yahoo_chart_http("SPY", _tries=3)
print("  Yahoo 直连(urllib):", "OK" if r.get("ok") else r.get("error"))
PY

echo ""
echo "完成。核心功能零依赖可直接运行:"
echo "  python tools/fengwatch.py daily"
echo "  python tools/fengportfolio.py check"
