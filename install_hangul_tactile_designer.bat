@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>nul
cd /d "%~dp0"

set "NO_PAUSE=0"
if /I "%~1"=="/nopause" set "NO_PAUSE=1"
set "VENV_DIR=%CD%\.venv"
set "REQ_FILE=%CD%\requirements_hangul_tactile_designer.txt"
set "PYTHON_EXE="

echo ============================================================
echo  Hangul Tactile Designer - universal installer
echo ============================================================
echo.
echo [1/5] Searching for a compatible 64-bit Python...
call :find_python
if not defined PYTHON_EXE goto no_python

for /f "delims=" %%V in ('"%PYTHON_EXE%" -c "import platform,sys; print(platform.python_version() + ' / ' + str(8*__import__('struct').calcsize('P')) + '-bit')"') do set "PY_INFO=%%V"
echo       Found: %PYTHON_EXE%
echo       Version: %PY_INFO%

echo [2/5] Checking the local virtual environment...
set "NEED_NEW_VENV=0"
if not exist "%VENV_DIR%\Scripts\python.exe" set "NEED_NEW_VENV=1"
if "%NEED_NEW_VENV%"=="0" (
    "%VENV_DIR%\Scripts\python.exe" -c "import sys,struct; assert sys.version_info[0] == 3 and sys.version_info[1] in (10,11,12); assert struct.calcsize('P')*8 == 64" >nul 2>nul
    if errorlevel 1 set "NEED_NEW_VENV=1"
)

if "%NEED_NEW_VENV%"=="1" (
    if exist "%VENV_DIR%" (
        echo       A stale or broken .venv was found. Recreating it...
        rmdir /s /q "%VENV_DIR%" >nul 2>nul
        if exist "%VENV_DIR%" goto venv_delete_failed
    ) else (
        echo       Creating a new .venv...
    )
    "%PYTHON_EXE%" -m venv "%VENV_DIR%"
    if errorlevel 1 goto failed
) else (
    echo       Existing .venv is valid.
)

echo [3/5] Preparing pip...
"%VENV_DIR%\Scripts\python.exe" -m ensurepip --upgrade >nul 2>nul
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto failed

echo [4/5] Installing application packages...
"%VENV_DIR%\Scripts\python.exe" -m pip install --prefer-binary -r "%REQ_FILE%"
if errorlevel 1 goto failed

echo [5/5] Verifying the installation...
"%VENV_DIR%\Scripts\python.exe" "%CD%\verify_hangul_tactile_install.py"
if errorlevel 1 goto failed

>"%CD%\.install_complete" echo Installed with %PYTHON_EXE% on %DATE% %TIME%
echo.
echo Installation completed successfully.
echo Double-click START_HERE_HangulTactileDesigner.cmd to run the program.
goto success

:find_python
call :try_launcher 3.12
if defined PYTHON_EXE exit /b 0
call :try_launcher 3.11
if defined PYTHON_EXE exit /b 0
call :try_launcher 3.10
if defined PYTHON_EXE exit /b 0
call :try_command python
if defined PYTHON_EXE exit /b 0
call :try_command python3
exit /b 0

:try_launcher
where py >nul 2>nul || exit /b 0
for /f "usebackq delims=" %%P in (`py -%1 -c "import sys,struct; assert sys.version_info[0] == 3 and sys.version_info[1] in (10,11,12); assert struct.calcsize('P')*8 == 64; print(sys.executable)" 2^>nul`) do set "PYTHON_EXE=%%P"
exit /b 0

:try_command
where %1 >nul 2>nul || exit /b 0
for /f "usebackq delims=" %%P in (`%1 -c "import sys,struct; assert sys.version_info[0] == 3 and sys.version_info[1] in (10,11,12); assert struct.calcsize('P')*8 == 64; print(sys.executable)" 2^>nul`) do set "PYTHON_EXE=%%P"
exit /b 0

:no_python
echo.
echo [ERROR] Compatible Python was not found.
echo Install 64-bit Python 3.11 or 3.12, then run this installer again.
echo During installation, enable "Add python.exe to PATH" if that option appears.
goto failed_end

:venv_delete_failed
echo.
echo [ERROR] The old .venv folder could not be removed.
echo Close every Python or Hangul Tactile Designer window, delete .venv manually,
echo and run this installer again.
goto failed_end

:failed
echo.
echo [ERROR] Installation failed. Review the message above.
echo You can also run diagnose_environment.bat for a diagnostic report.

:failed_end
if "%NO_PAUSE%"=="0" pause
exit /b 1

:success
if "%NO_PAUSE%"=="0" pause
exit /b 0
