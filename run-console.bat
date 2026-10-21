@echo off
rem AstrBot PC - console mode (keep this window open to see logs).
setlocal
cd /d "%~dp0"
chcp 65001 >nul

set "PY="
for /f "delims=" %%I in ('where python.exe 2^>nul') do (
  if not defined PY set "PY=%%I"
)
if not defined PY (
  echo [ERROR] python.exe not found. Install Python 3.10+ and add it to PATH.
  pause
  exit /b 1
)

"%PY%" -m astrbot_pc %*
echo.
echo [AstrBot PC] exited with code %errorlevel%.
pause