@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    call "install_hangul_tactile_designer.bat" /nopause
    if errorlevel 1 goto failed
)

echo Installing/updating PyInstaller...
".venv\Scripts\python.exe" -m pip install --upgrade pyinstaller
if errorlevel 1 goto failed

echo Building the Windows one-folder executable...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean "hangul_tactile_designer.spec"
if errorlevel 1 goto failed

echo.
echo Build completed.
echo EXE: %CD%\dist\HangulTactileDesigner\HangulTactileDesigner.exe
echo Keep the entire HangulTactileDesigner folder together when copying it.
pause
exit /b 0

:failed
echo.
echo EXE build failed. Review the error above.
pause
exit /b 1
