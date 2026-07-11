@echo off
setlocal
chcp 65001 >nul 2>nul
cd /d "%~dp0"
echo This deletes only the local .venv and installation marker.
echo Your source code, setups, voice profiles, and result files are preserved.
choice /C YN /N /M "Continue? [Y/N] "
if errorlevel 2 exit /b 0
if exist ".venv" rmdir /s /q ".venv"
if exist ".install_complete" del /q ".install_complete"
echo Reset complete. Run START_HERE_HangulTactileDesigner.cmd.
pause
