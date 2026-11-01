@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set "PY=.venv\Scripts\python.exe"
) else (
  set "PY=python"
)

if not exist "config.toml" (
  echo [ERROR] config.toml not found.
  echo Copy config.example.toml to config.toml and edit it first.
  pause
  exit /b 2
)

echo Starting Microsoft Rewards scheduler. Press Ctrl+C to stop.
"%PY%" main.py
if errorlevel 1 (
  echo.
  echo Scheduler exited with an error. See logs\rewards_bot.log
  pause
)
endlocal
