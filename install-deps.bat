@echo off
rem ============================================================
rem  FengInvest 依赖安装脚本 (Windows)
rem  核心功能(持仓监控/行情/组合检查) 零依赖, 无需本脚本。
rem  本脚本只装次要增强库: yfinance/akshare/pandas 等。
rem ============================================================
chcp 65001 >nul
setlocal
cd /d %~dp0

echo ============================================
echo  正在检查 Python
echo ============================================
python --version 2>nul
if errorlevel 1 (
  echo [错误] 未找到 Python, 请先安装 Python 3.9+ 并加入 PATH
  pause
  exit /b 1
)

echo.
echo ============================================
echo  正在安装 requirements.txt 中的次要依赖
echo ============================================
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo [错误] 依赖安装失败, 请检查网络或 Python pip
  pause
  exit /b 1
)

echo.
echo ============================================
echo  完成。核心功能零依赖可直接运行:
echo    python tools\fengwatch.py daily
echo    python tools\fengportfolio.py check
echo ============================================
pause
