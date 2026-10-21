@echo off
rem AstrBot PC - launch the desktop window (no console).
setlocal
cd /d "%~dp0"

set "PYW="
for /f "delims=" %%I in ('where pythonw.exe 2^>nul') do (
  if not defined PYW set "PYW=%%I"
)
if not defined PYW (
  echo [ERROR] pythonw.exe not found. Install Python 3.10+ and add it to PATH.
  pause
  exit /b 1
)

start "" "%PYW%" -m astrbot_pc %*
exit /b 0