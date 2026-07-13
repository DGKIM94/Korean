@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>nul
cd /d "%~dp0"

set "NO_PAUSE=0"
if /I "%~1"=="/nopause" set "NO_PAUSE=1"

set "VENV_DIR=%CD%\.venv"
set "REQ_FILE=%CD%\requirements_hangul_tactile_designer.txt"
set "PYTHON_EXE="
set "PYTHON_BOOTSTRAP_VERSION=3.12.10"
set "PYTHON_BOOTSTRAP_URL=https://www.python.org/ftp/python/%PYTHON_BOOTSTRAP_VERSION%/python-%PYTHON_BOOTSTRAP_VERSION%-amd64.exe"
set "PYTHON_BOOTSTRAP_TARGET=%LOCALAPPDATA%\Programs\Python\Python312"
set "PYTHON_BOOTSTRAP_INSTALLER=%TEMP%\python-%PYTHON_BOOTSTRAP_VERSION%-amd64.exe"

echo ============================================================
echo  Hangul Tactile Designer - automatic Windows installer
echo ============================================================
echo.
echo [1/6] Searching for a compatible 64-bit Python...
call :find_python

if not defined PYTHON_EXE (
    echo       Python 3.10-3.13 was not found.
    echo       Attempting an automatic per-user Python 3.12 installation...
    echo.
    call :bootstrap_python
    call :find_python
)

if not defined PYTHON_EXE goto no_python

for /f "delims=" %%V in ('"%PYTHON_EXE%" -c "import platform,struct; print(platform.python_version() + ' / ' + str(struct.calcsize('P')*8) + '-bit')"') do set "PY_INFO=%%V"
echo       Found: %PYTHON_EXE%
echo       Version: %PY_INFO%

echo [2/6] Checking the local virtual environment...
set "NEED_NEW_VENV=0"
if not exist "%VENV_DIR%\Scripts\python.exe" set "NEED_NEW_VENV=1"
if "%NEED_NEW_VENV%"=="0" (
    "%VENV_DIR%\Scripts\python.exe" -c "import sys,struct; assert sys.version_info[0] == 3 and sys.version_info[1] in (10,11,12,13); assert struct.calcsize('P')*8 == 64" >nul 2>nul
    if errorlevel 1 set "NEED_NEW_VENV=1"
)

if "%NEED_NEW_VENV%"=="1" (
    if exist "%VENV_DIR%" (
        echo       A stale, copied, or broken .venv was found. Recreating it...
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

echo [3/6] Preparing pip...
"%VENV_DIR%\Scripts\python.exe" -m ensurepip --upgrade >nul 2>nul
"%VENV_DIR%\Scripts\python.exe" -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto failed

echo [4/6] Installing application packages...
echo       The first installation can take several minutes.
"%VENV_DIR%\Scripts\python.exe" -m pip install --prefer-binary -r "%REQ_FILE%"
if errorlevel 1 goto failed

echo [5/6] Verifying the installation...
"%VENV_DIR%\Scripts\python.exe" "%CD%\verify_hangul_tactile_install.py"
if errorlevel 1 goto failed

echo [6/6] Saving installation information...
>"%CD%\.install_complete" echo Installed with %PYTHON_EXE% on %DATE% %TIME%

echo.
echo Installation completed successfully.
echo Double-click START_HERE_HangulTactileDesigner.cmd to run the program.
goto success


:find_python
set "PYTHON_EXE="

rem Prefer Python Launcher installations.
call :try_launcher 3.13
if defined PYTHON_EXE exit /b 0
call :try_launcher 3.12
if defined PYTHON_EXE exit /b 0
call :try_launcher 3.11
if defined PYTHON_EXE exit /b 0
call :try_launcher 3.10
if defined PYTHON_EXE exit /b 0

rem Check normal per-user and machine-wide Python locations.
call :try_path "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if defined PYTHON_EXE exit /b 0
call :try_path "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined PYTHON_EXE exit /b 0
call :try_path "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if defined PYTHON_EXE exit /b 0
call :try_path "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
if defined PYTHON_EXE exit /b 0

rem Microsoft Store's newer pythoncore layout.
call :try_path "%LOCALAPPDATA%\Python\pythoncore-3.13-64\python.exe"
if defined PYTHON_EXE exit /b 0
call :try_path "%LOCALAPPDATA%\Python\pythoncore-3.12-64\python.exe"
if defined PYTHON_EXE exit /b 0
call :try_path "%LOCALAPPDATA%\Python\pythoncore-3.11-64\python.exe"
if defined PYTHON_EXE exit /b 0
call :try_path "%LOCALAPPDATA%\Python\pythoncore-3.10-64\python.exe"
if defined PYTHON_EXE exit /b 0

call :try_path "%ProgramFiles%\Python313\python.exe"
if defined PYTHON_EXE exit /b 0
call :try_path "%ProgramFiles%\Python312\python.exe"
if defined PYTHON_EXE exit /b 0
call :try_path "%ProgramFiles%\Python311\python.exe"
if defined PYTHON_EXE exit /b 0
call :try_path "%ProgramFiles%\Python310\python.exe"
if defined PYTHON_EXE exit /b 0

rem Finally inspect commands on PATH; WindowsApps aliases are rejected by validation.
call :try_command python
if defined PYTHON_EXE exit /b 0
call :try_command python3
exit /b 0


:try_launcher
where py >nul 2>nul || exit /b 0
py -%1 -c "import sys,struct; assert sys.version_info[0] == 3 and sys.version_info[1] in (10,11,12,13); assert struct.calcsize('P')*8 == 64" >nul 2>nul
if errorlevel 1 exit /b 0
for /f "usebackq delims=" %%P in (`py -%1 -c "import sys; print(sys.executable)" 2^>nul`) do set "PYTHON_EXE=%%P"
exit /b 0


:try_path
set "CANDIDATE=%~1"
if not exist "%CANDIDATE%" exit /b 0
"%CANDIDATE%" -c "import sys,struct; assert sys.version_info[0] == 3 and sys.version_info[1] in (10,11,12,13); assert struct.calcsize('P')*8 == 64" >nul 2>nul
if not errorlevel 1 set "PYTHON_EXE=%CANDIDATE%"
exit /b 0


:try_command
where %~1 >nul 2>nul || exit /b 0
for /f "delims=" %%P in ('where %~1 2^>nul') do (
    call :try_path "%%P"
    if defined PYTHON_EXE exit /b 0
)
exit /b 0


:bootstrap_python
rem First try Windows Package Manager when available.
where winget >nul 2>nul
if not errorlevel 1 (
    echo       Trying Windows Package Manager...
    winget install --exact --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
    call :find_python
    if defined PYTHON_EXE (
        echo       Python was installed with winget.
        exit /b 0
    )
    echo       winget did not provide a usable Python. Trying the official installer...
)

echo       Downloading official Python %PYTHON_BOOTSTRAP_VERSION% installer...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
 "$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri '%PYTHON_BOOTSTRAP_URL%' -OutFile '%PYTHON_BOOTSTRAP_INSTALLER%'"
if errorlevel 1 (
    echo       Automatic download failed.
    exit /b 1
)

if not exist "%PYTHON_BOOTSTRAP_INSTALLER%" (
    echo       The downloaded installer was not found.
    exit /b 1
)

echo       Installing Python for the current Windows user...
"%PYTHON_BOOTSTRAP_INSTALLER%" /quiet InstallAllUsers=0 TargetDir="%PYTHON_BOOTSTRAP_TARGET%" PrependPath=0 Include_launcher=1 InstallLauncherAllUsers=0 Include_pip=1 Include_test=0 Include_doc=0 Include_tcltk=0 /log "%CD%\python_install.log"
if errorlevel 1 (
    echo       Python installer returned an error. See python_install.log.
    exit /b 1
)

call :try_path "%PYTHON_BOOTSTRAP_TARGET%\python.exe"
if defined PYTHON_EXE (
    echo       Python was installed successfully.
    exit /b 0
)

echo       Python installation completed, but python.exe was not detected.
exit /b 1


:no_python
echo.
echo [ERROR] A compatible Python could not be found or installed automatically.
echo.
echo Check the following:
echo   1. Make sure this computer is connected to the Internet.
echo   2. Corporate security software may block winget or python.org.
echo   3. Run this installer once as the current Windows user.
echo.
echo You may also install 64-bit Python 3.11, 3.12, or 3.13 manually,
echo then run START_HERE_HangulTactileDesigner.cmd again.
if exist "%CD%\python_install.log" echo Installer log: %CD%\python_install.log
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
