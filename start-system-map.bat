@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion
rem system-map 静态服务器 — Tailscale 网内可访问
rem 用法: start-system-map.bat [端口]   (默认 34567, 小众端口防误杀)
rem 注意: 只杀占用本端口的进程, 不 taskkill 全杀 node (避免误伤 fengweb 等)

cd /d "%~dp0"
set PORT=34567
if not "%~1"=="" set PORT=%~1

rem 端口占用检测与清理
set retry=0
:kill_loop
netstat -ano | findstr ":%PORT% " | findstr "LISTENING" > nul
if !errorlevel! equ 0 (
  set /a retry+=1
  if !retry! gtr 3 (
    echo 端口 %PORT% 无法释放, 请手动关闭占用程序后重试。
    pause
    exit /b 1
  )
  for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
    taskkill /f /pid %%p > nul 2>&1
  )
  timeout /t 1 /nobreak > nul
  goto kill_loop
)

for /f "delims=" %%i in ('tailscale ip -4 2^>nul') do set TSIP=%%i

echo system-map 静态服务:
echo   本机:     http://localhost:%PORT%/system-map.html
if defined TSIP echo   Tailscale: http://%TSIP%:%PORT%/system-map.html
python -m http.server %PORT% --bind 0.0.0.0 --directory docs
if %errorlevel% neq 0 (
  echo 启动失败。
  pause
  exit /b 1
)
pause
