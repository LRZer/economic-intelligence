@echo off
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Project Python environment is missing. Follow README installation instructions.
  pause
  exit /b 2
)
".venv\Scripts\python.exe" "scripts\deepseek_live_check.py" --live
echo.
echo Report: reports\deepseek-live-check.json
pause
endlocal
