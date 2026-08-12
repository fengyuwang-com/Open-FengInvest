@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion
rem FengWeb 启动脚本 - 端口 23456（小众端口, 防误杀其它服务）
rem 注意: 只杀占用本端口的进程, 不 taskkill 全杀 node (避免误伤 system-map 等)

cd /d "%~dp0fengweb"
set PORT=23456
if not "%~1"=="" set PORT=%~1

echo Building...
call npx tsc
if %errorlevel% neq 0 (
  echo 编译失败。
  pause
  exit /b 1
)

rem 端口占用检测与清理: 只杀占用本端口的进程
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

echo Starting FengWeb on http://localhost:%PORT%
node dist/index.js
if %errorlevel% neq 0 (
  echo Failed to start.
  pause
  exit /b 1
)
pause
