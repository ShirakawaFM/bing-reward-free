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
  exit /b 2
)

"%PY%" main.py --once %*
if errorlevel 1 (
  echo Run failed. See logs\rewards_bot.log
  exit /b 1
)
exit /b 0
