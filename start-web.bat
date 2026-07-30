@echo off
chcp 65001 > nul
setlocal enabledelayedexpansion
cd /d %~dp0fengweb
echo Building...
call npx tsc

:check
set retry=0

:kill_loop
taskkill /f /im node.exe > nul 2>&1
ping -n 3 127.0.0.1 > nul
netstat -ano | findstr ":3000 " > nul
if !errorlevel! equ 0 (
  set /a retry+=1
  if !retry! lss 3 goto kill_loop
  echo Cannot free port 3000. Close the other program and try again.
  pause
  exit /b 1
)
goto start

:start
echo Starting FengWeb on http://localhost:3000
node dist/index.js
if %errorlevel% neq 0 (
  echo Failed to start.
  pause
  exit /b 1
)
pause
