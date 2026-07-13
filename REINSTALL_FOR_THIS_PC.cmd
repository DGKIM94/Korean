@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>nul
cd /d "%~dp0"

echo This will rebuild the local environment for this PC and start the program.
echo.
if exist ".venv" (
    echo Removing the copied or old .venv...
    rmdir /s /q ".venv"
)
del /q ".install_complete" >nul 2>nul

call "%CD%\install_hangul_tactile_designer.bat"
if errorlevel 1 exit /b 1

call "%CD%\START_HERE_HangulTactileDesigner.cmd"
exit /b 0
