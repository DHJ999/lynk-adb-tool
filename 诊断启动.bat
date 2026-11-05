@echo off
setlocal
cd /d "%~dp0"

set "PY="
if exist "%~dp0python\python.exe" set "PY=%~dp0python\python.exe"
if not defined PY if exist "%APPDATA%\uv\python\cpython-3.12.13-windows-x86_64-none\python.exe" set "PY=%APPDATA%\uv\python\cpython-3.12.13-windows-x86_64-none\python.exe"
if not defined PY if exist "%APPDATA%\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe" set "PY=%APPDATA%\uv\python\cpython-3.11.16-windows-x86_64-none\python.exe"
if not defined PY for %%P in (python.exe) do set "PY=%%~$PATH:P"

if not defined PY (
    echo python.exe not found.
    pause
    exit /b 1
)

echo Using Python: %PY%
"%PY%" "%~dp0lynk_adb_tool.py"
echo.
echo Program exited with code %errorlevel%.
pause
