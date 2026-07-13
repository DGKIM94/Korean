@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>nul
cd /d "%~dp0"

set "PY=%CD%\.venv\Scripts\python.exe"
set "PYW=%CD%\.venv\Scripts\pythonw.exe"
set "NEED_INSTALL=0"

if not exist "%PY%" set "NEED_INSTALL=1"
if "%NEED_INSTALL%"=="0" (
    "%PY%" -c "import PySide6,serial,openpyxl,numpy,scipy,sounddevice,webrtcvad,sklearn,pandas; import faster_whisper" >nul 2>nul
    if errorlevel 1 set "NEED_INSTALL=1"
)

if "%NEED_INSTALL%"=="1" (
    echo The local program environment is missing, incomplete, or copied from another PC.
    echo Python and the required packages will be prepared automatically.
    echo Internet access is required on the first run.
    echo.
    call "%CD%\install_hangul_tactile_designer.bat" /nopause
    if errorlevel 1 (
        echo.
        echo Installation did not complete.
        echo Review the messages above or python_install.log, then press any key to close.
        pause >nul
        exit /b 1
    )
)

if not exist "%PYW%" set "PYW=%PY%"
start "Hangul Tactile Designer" /D "%CD%" "%PYW%" "%CD%\launch_hangul_tactile_designer.py"
exit /b 0
