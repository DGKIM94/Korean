@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>nul
cd /d "%~dp0"
set "REPORT=%CD%\environment_diagnostic.txt"
(
 echo Hangul Tactile Designer diagnostic
 echo Date: %DATE% %TIME%
 echo Folder: %CD%
 echo.
 echo === where python ===
 where python 2^>^&1
 echo.
 echo === where py ===
 where py 2^>^&1
 echo.
 echo === py --list-paths ===
 py --list-paths 2^>^&1
 echo.
 echo === python version ===
 python --version 2^>^&1
 echo.
 echo === local venv ===
 if exist ".venv\Scripts\python.exe" (
   ".venv\Scripts\python.exe" --version 2^>^&1
   ".venv\Scripts\python.exe" -c "import sys; print(sys.executable); print(sys.prefix); print(sys.base_prefix)" 2^>^&1
   ".venv\Scripts\python.exe" -m pip --version 2^>^&1
   ".venv\Scripts\python.exe" "verify_hangul_tactile_install.py" 2^>^&1
 ) else (
   echo .venv does not exist.
 )
) > "%REPORT%"
type "%REPORT%"
echo.
echo Saved: %REPORT%
pause
