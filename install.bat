@echo off
rem AstrBot PC - install python dependencies.
setlocal
cd /d "%~dp0"
chcp 65001 >nul

set "PY="
for /f "delims=" %%I in ('where python.exe 2^>nul') do (
  if not defined PY set "PY=%%I"
)
if not defined PY (
  echo [ERROR] python.exe not found.
  pause
  exit /b 1
)

"%PY%" -m pip install --upgrade pip
"%PY%" -m pip install -r requirements.txt
echo.
echo [AstrBot PC] dependencies ready.
pause