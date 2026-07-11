@echo off
setlocal
chcp 65001 >nul 2>nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run install_hangul_tactile_designer.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" "launch_hangul_tactile_designer.py"
echo.
echo Exit code: %ERRORLEVEL%
pause
